"""Pip's troubleshoot mode (D-935): "why didn't my agent pick up?", answered by checks.

Five question families, one per area, each an ORDERED list of checks. Every check asks a
question the platform already knows how to answer, through the function the gate or the
screen that owns the answer calls: `campaigns.service.launch_blockers` and
`campaign_progress` (whose `not_calling` is `dispatch_blockers` plus `check_dispatch`'s agent
and account halves), `compliance.service.account_dial_blockers` and `credits_exhausted`, the
inbound silence the engine is holding (`agents.inbound_silence_reason`), the drift sweep's
verdicts on `engine_agent_routes`, the numbers list route (`answers_calls`, holds,
activation), the healer's client incidents, `kb.service.list_sources` /
`kb.store.undelivered_source_ids`, `crm.attention.failed_deliveries` / `broken_actions`, the
team alert rows, and the call's own row. Nothing here re-derives a rule.

Why ordered checks rather than handing the model the raw facts: the order IS the
diagnosis. A platform halt explains a silent campaign before an empty wallet does, and an
unpublished agent before a missing number; a model reading eight facts picks whichever it
read last. The FIRST `problem` is the answer, and the card shows the rest as the receipt.

Three outcomes per check, and `unknown` is one of them: a read that failed, a sweep that has
not run, or a fact we do not record (`calls.knowledge_state` stopped being written when the
engine started hosting calls) is reported as unknown, never as ok and never as a guess.

Reads only. Each check runs inside a SAVEPOINT so one failed query becomes that check's
`unknown` rather than aborting the transaction the later checks share.

The model reads a few lines (`DiagnosisText`); the panel reads the structured
`Diagnosis` riding on the same string to draw the checklist card
(`service._run_one_read_tool`, `CopilotStepEvent.diagnosis`). A fix is either a screen from
the client console's inventory (`screens.CLIENT_SCREENS`, never a model-made route) or a
sentence the button sends to Pip, which then proposes the existing action under its own
tier and confirmation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.screens import CLIENT_SCREENS, where_is
from apps.api.copilot.tools import ReadTool, ToolContext, _clean, ist_stamp

log = logging.getLogger(__name__)

CheckStatus = Literal["ok", "problem", "unknown"]
Family = Literal["agent", "call", "campaign", "delivery", "knowledge"]

#: How far back the delivery and call checks look. The attention queue's window.
RECENT_DAYS: Final = 14
#: How old the oldest unsent outbox message may be before the admin twin calls it stuck.
OUTBOX_STUCK_MINUTES: Final = 5
#: The most evidence ids one check carries.
MAX_EVIDENCE: Final = 5


@dataclass(frozen=True, slots=True)
class Fix:
    """What the check's button does. `screen`/`route`/`where` come from the console's own
    inventory; `ask` is a sentence the button sends to Pip, which proposes the action."""

    label: str
    screen: str | None = None
    route: str | None = None
    where: str | None = None
    ask: str | None = None


@dataclass(frozen=True, slots=True)
class Check:
    key: str
    label: str
    status: CheckStatus
    detail: str
    evidence: tuple[str, ...] = ()
    fix: Fix | None = None


@dataclass(frozen=True, slots=True)
class Diagnosis:
    family: Family
    subject: str
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def cause(self) -> Check | None:
        """The first real cause, in the family's order."""
        return next((check for check in self.checks if check.status == "problem"), None)

    @property
    def verdict(self) -> str:
        cause = self.cause
        if cause is not None:
            return cause.detail
        if any(check.status == "unknown" for check in self.checks):
            return "Nothing we checked is wrong, but some things could not be checked."
        return "Everything we checked looks fine."


class DiagnosisText(str):
    """The model's text, carrying the structured result for the panel's card.

    A `str` because `ReadTool.run` returns text and every caller between the executor and
    the step frame (`run_read_tool`, `_run_one_read_tool`) passes the string through
    untouched; widening the executor contract for one tool family would change all of them.
    """

    diagnosis: Diagnosis

    def __new__(cls, value: str, diagnosis: Diagnosis) -> DiagnosisText:
        made = super().__new__(cls, value)
        made.diagnosis = diagnosis
        return made


# --- building blocks -------------------------------------------------------------------------


def screen_fix(label: str, screen_name: str) -> Fix:
    """A fix that opens one of the console's own screens, read from the inventory."""
    screen = next(s for s in CLIENT_SCREENS if s.name == screen_name)
    return Fix(label=label, screen=screen.name, route=screen.route, where=where_is(screen))


def ask_fix(label: str, ask: str) -> Fix:
    return Fix(label=label, ask=ask)


def ok(key: str, label: str, detail: str, *evidence: str) -> Check:
    return Check(key, label, "ok", detail, tuple(evidence[:MAX_EVIDENCE]))


def problem(key: str, label: str, detail: str, *evidence: str, fix: Fix | None = None) -> Check:
    return Check(key, label, "problem", detail, tuple(evidence[:MAX_EVIDENCE]), fix)


def unknown(key: str, label: str, detail: str, *evidence: str) -> Check:
    return Check(key, label, "unknown", detail, tuple(evidence[:MAX_EVIDENCE]))


CheckFn = Callable[[], Awaitable[Check]]


async def _guarded(session: AsyncSession, key: str, label: str, run: CheckFn) -> Check:
    """One check under a savepoint; a failure is that check's `unknown`, logged by key."""
    try:
        async with session.begin_nested():
            return await run()
    except Exception:
        log.exception("copilot_diagnose_check_failed", extra={"check": key})
        return unknown(key, label, "Could not be checked just now.")


async def _run(session: AsyncSession, steps: Sequence[tuple[str, str, CheckFn]]) -> list[Check]:
    return [await _guarded(session, key, label, run) for key, label, run in steps]


#: Which screen fixes an account-level refusal, by the gate's own rule name (prefix).
_RULE_SCREENS: Final[tuple[tuple[str, str, str], ...]] = (
    ("kyc", "Verify your business", "Verify your business"),
    ("outbound_pledge", "Take the pledge", "Verify your business"),
    ("agreements", "Accept the agreements", "Agreements"),
    ("spend_cap", "Raise the limit", "Credits & billing"),
    ("no_credits", "Add credit", "Credits & billing"),
    ("payment_dispute", "Open billing", "Credits & billing"),
    ("platform_fee", "Pay the fee", "Credits & billing"),
    ("trial", "See plans", "Credits & billing"),
)


def rule_fix(rule: str) -> Fix | None:
    for prefix, label, screen in _RULE_SCREENS:
        if rule.startswith(prefix):
            return screen_fix(label, screen)
    return None


# --- shared checks -----------------------------------------------------------------------------


async def platform_outbound(session: AsyncSession) -> Check:
    """The big red switch and the maintenance drain: both stop every outbound call."""
    from apps.api.ops.maintenance import read_open_window
    from apps.api.ops.service import read_halt_state

    label = "Calevate is placing calls"
    if (await read_halt_state(session)).outbound_halted:
        return problem(
            "platform_halt",
            label,
            "Calevate has paused all outgoing calls for now.",
            "platform_state",
        )
    window = await read_open_window(session)
    if window is not None and window.state in ("draining", "active"):
        return problem(
            "maintenance",
            label,
            f"Calevate is under maintenance until {ist_stamp(window.ends_at)} IST.",
            f"maintenance_window {window.id}",
        )
    return ok("platform", label, "No platform pause or maintenance.", "platform_state")


async def account_outbound(session: AsyncSession, tenant_id: UUID) -> Check:
    """The account half of the dial gate, in its own order: lifecycle first."""
    from apps.api.compliance.service import account_dial_blockers, account_stopped_blocker

    label = "Your account may place calls"
    stopped = await account_stopped_blocker(session, tenant_id=tenant_id)
    found = [stopped] if stopped is not None else []
    found += await account_dial_blockers(session, tenant_id=tenant_id, trial_call=False)
    if not found:
        return ok("account", label, "Nothing on the account is stopping calls.", "organizations")
    rule, reason = found[0]
    return problem("account", label, reason, f"rule {rule}", fix=rule_fix(rule))


async def _agent_row(session: AsyncSession, agent_id: UUID) -> Mapping[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT name, status, direction, deleted_at IS NOT NULL AS deleted, "
                    "engine_agent_ref, inbound_silence_reason FROM agents WHERE id = :aid"
                ),
                {"aid": agent_id},
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _named(row: Mapping[str, Any]) -> str:
    return _clean(str(row["name"]))[:60]


def agent_switched_on(row: Mapping[str, Any] | None, agent_id: UUID, *, answers: bool) -> Check:
    """Is the agent there, live, and pointed the right way for this question?"""
    label = "The agent is switched on"
    evidence = f"agent_id {agent_id}"
    if row is None or row["deleted"]:
        return problem(
            "agent",
            label,
            "That agent has been deleted.",
            evidence,
            fix=screen_fix("Open agents", "Agents"),
        )
    name = _named(row)
    if row["status"] == "draft":
        return problem(
            "agent",
            label,
            f"{name} is not switched on yet.",
            evidence,
            fix=ask_fix("Put it live", f"Put {name} live"),
        )
    if row["status"] == "paused":
        return problem(
            "agent",
            label,
            f"{name} is paused.",
            evidence,
            fix=ask_fix("Switch it on", f"Switch {name} back on"),
        )
    if row["status"] == "archived":
        return problem(
            "agent",
            label,
            f"{name} is archived.",
            evidence,
            fix=screen_fix("Open agents", "Agents"),
        )
    if answers and row["direction"] == "outbound":
        return problem(
            "agent",
            label,
            f"{name} only places calls; it does not answer them.",
            evidence,
            fix=screen_fix("Open agents", "Agents"),
        )
    if not answers and row["direction"] == "inbound":
        return problem(
            "agent",
            label,
            f"{name} only answers calls; it cannot place them.",
            evidence,
            fix=screen_fix("Open agents", "Agents"),
        )
    return ok("agent", label, f"{name} is live.", evidence)


async def agent_matches_engine(
    session: AsyncSession, row: Mapping[str, Any] | None, agent_id: UUID
) -> Check:
    """The drift sweep's verdict: is the agent on the phone the one that was saved?"""
    from apps.api.agents.reconciliation import DRIFT_STATES_OUT_OF_SYNC

    label = "The agent on the phone matches what you saved"
    if row is None or not row["engine_agent_ref"]:
        return unknown(
            "drift", label, "It has not been put on the phone yet.", f"agent_id {agent_id}"
        )
    verdict = (
        await session.execute(
            text(
                "SELECT drift_state, drift_checked_at FROM engine_agent_routes "
                "WHERE agent_id = :aid AND active ORDER BY drift_checked_at DESC NULLS LAST "
                "LIMIT 1"
            ),
            {"aid": agent_id},
        )
    ).first()
    if verdict is None or verdict[1] is None:
        return unknown("drift", label, "Not checked yet.", f"agent_id {agent_id}")
    stamp = f"checked {ist_stamp(verdict[1])} IST"
    if verdict[0] in DRIFT_STATES_OUT_OF_SYNC:
        name = _named(row)
        return problem(
            "drift",
            label,
            f"{name} on the phone does not match what you saved.",
            f"drift {verdict[0]}",
            stamp,
            fix=ask_fix("Put it live again", f"Put {name} live again"),
        )
    if verdict[0] in ("unreadable", "unreachable"):
        return unknown("drift", label, "The calling platform could not be read.", stamp)
    return ok("drift", label, "It matches.", stamp)


async def healer_open(session: AsyncSession, agent_id: UUID) -> Check:
    label = "No open problem with its calls"
    row = (
        await session.execute(
            text(
                "SELECT id, opened_at FROM heal_client_incidents WHERE agent_id = :aid "
                "AND state = 'open' ORDER BY opened_at DESC LIMIT 1"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return ok("healer", label, "None open.", f"agent_id {agent_id}")
    return problem(
        "healer",
        label,
        f"We are fixing a problem with this agent's calls, open since {ist_stamp(row[1])} IST.",
        f"incident {row[0]}",
        fix=screen_fix("See what happened", "Needs attention"),
    )


# --- family: why didn't my agent pick up? -----------------------------------------------------


async def diagnose_agent(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> Diagnosis:
    from apps.api.agents.service import (
        INBOUND_SILENCE_CREDITS,
        INBOUND_SILENCE_HEALER,
        INBOUND_SILENCE_TRUTHFUL_ANSWER,
    )
    from apps.api.campaigns.routes import list_numbers
    from apps.api.compliance.service import credits_exhausted
    from apps.api.core.context import Principal
    from apps.api.tenancy.engine_workspace import engine_has_workspaces, read_workspace_state

    row = await _agent_row(session, agent_id)
    name = _named(row) if row is not None else "this agent"

    async def switched_on() -> Check:
        return agent_switched_on(row, agent_id, answers=True)

    async def credit() -> Check:
        label = "There is credit to answer calls"
        if await credits_exhausted(session, tenant_id=tenant_id):
            return problem(
                "credit",
                label,
                "Your credit has run out, so agents stop answering.",
                "wallet",
                fix=screen_fix("Add credit", "Credits & billing"),
            )
        return ok("credit", label, "There is credit.", "wallet")

    async def silence() -> Check:
        label = "Its line is open"
        reason = None if row is None else row["inbound_silence_reason"]
        evidence = f"agent_id {agent_id}"
        if reason == INBOUND_SILENCE_TRUTHFUL_ANSWER:
            return problem(
                "silence",
                label,
                f"{name} was taken off its number after failing a safety check.",
                evidence,
                fix=ask_fix("Put it live again", f"Put {name} live again"),
            )
        if reason == INBOUND_SILENCE_HEALER:
            return problem(
                "silence",
                label,
                f"We took {name} off its line because its calls kept failing.",
                evidence,
                fix=screen_fix("See what happened", "Needs attention"),
            )
        if reason == INBOUND_SILENCE_CREDITS:
            return problem(
                "silence",
                label,
                f"{name} is playing the out-of-credit message.",
                evidence,
                fix=screen_fix("Add credit", "Credits & billing"),
            )
        return ok("silence", label, "Nothing is holding its line.", evidence)

    async def workspace() -> Check:
        label = "Your calling space is set up"
        if not engine_has_workspaces():
            return ok("workspace", label, "Not needed.", "tenant_engine_workspaces")
        state = await read_workspace_state(session, tenant_id)
        if state.active:
            return ok("workspace", label, "Set up.", "tenant_engine_workspaces")
        return problem(
            "workspace",
            label,
            "Your calling space is still being set up.",
            f"workspace {state.status}",
        )

    async def number() -> Check:
        label = "A number rings this agent"
        principal = Principal(realm="client", user_id=None, tenant_id=tenant_id, role="owner")
        mine = [n for n in await list_numbers(session, principal) if n.agent_id == agent_id]
        if not mine:
            return problem(
                "number",
                label,
                f"No phone number is attached to {name}.",
                f"agent_id {agent_id}",
                fix=ask_fix("Attach a number", f"Attach a phone number to {name}"),
            )
        evidence = [f"number_id {n.id}" for n in mine]
        if all(n.held for n in mine):
            return problem(
                "number",
                label,
                f"{name}'s number is on hold.",
                *evidence,
                fix=screen_fix("Open your number", "Your phone number"),
            )
        if not any(n.activated for n in mine):
            return problem(
                "number",
                label,
                f"{name}'s number waits for your business check.",
                *evidence,
                fix=screen_fix("Verify your business", "Verify your business"),
            )
        if not any(n.answerable for n in mine):
            return problem(
                "number",
                label,
                f"{name}'s number is not connected to it on the calling platform.",
                *evidence,
                fix=ask_fix("Put it live again", f"Put {name} live again"),
            )
        return ok("number", label, "Its number is connected.", *evidence)

    async def drift() -> Check:
        return await agent_matches_engine(session, row, agent_id)

    async def healer() -> Check:
        return await healer_open(session, agent_id)

    async def recent() -> Check:
        label = "Recent calls reached it"
        rows = (
            await session.execute(
                text(
                    "SELECT id, status, started_at FROM calls WHERE agent_id = :aid "
                    "AND direction = 'inbound' ORDER BY created_at DESC LIMIT 5"
                ),
                {"aid": agent_id},
            )
        ).all()
        if not rows:
            return unknown("recent", label, "No call has reached it yet.", f"agent_id {agent_id}")
        evidence = [f"call_id {r[0]}" for r in rows]
        if all(r[1] == "failed" for r in rows):
            return problem(
                "recent",
                label,
                f"The last {len(rows)} calls to {name} failed.",
                *evidence,
                fix=screen_fix("Open call logs", "Call logs"),
            )
        return ok("recent", label, f"Last call {ist_stamp(rows[0][2])} IST.", *evidence)

    checks = await _run(
        session,
        (
            ("agent", "The agent is switched on", switched_on),
            ("credit", "There is credit to answer calls", credit),
            ("silence", "Its line is open", silence),
            ("workspace", "Your calling space is set up", workspace),
            ("number", "A number rings this agent", number),
            ("drift", "The agent on the phone matches what you saved", drift),
            ("healer", "No open problem with its calls", healer),
            ("recent", "Recent calls reached it", recent),
        ),
    )
    return Diagnosis("agent", f"Why {name} did not pick up", tuple(checks))


# --- family: why did this call fail? ----------------------------------------------------------

#: What a call's own end state says, in a client's words.
_CALL_ENDS: Final[dict[str, str]] = {
    "no_answer": "They did not pick up.",
    "busy": "Their line was busy.",
    "voicemail": "It went to voicemail.",
    "failed": "The call could not be connected.",
}


async def diagnose_call(session: AsyncSession, tenant_id: UUID, call_id: UUID) -> Diagnosis:
    from apps.api.compliance.service import person_level_refusal

    found = (
        await session.execute(
            text(
                "SELECT c.agent_id, c.direction, c.status, c.duration_s, c.not_placed_reason, "
                "c.forwarded_to_phone, c.summary_state, c.recording_url IS NOT NULL, "
                "c.to_e164, c.from_e164 FROM calls c WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if found is None:
        return Diagnosis(
            "call",
            "That call",
            (
                problem(
                    "call",
                    "The call is in this account",
                    "No call with that id in this account.",
                    f"call_id {call_id}",
                ),
            ),
        )
    agent_id = UUID(str(found[0]))
    direction, status = str(found[1]), str(found[2])
    outbound = direction == "outbound"
    row = await _agent_row(session, agent_id)
    evidence = f"call_id {call_id}"

    async def record() -> Check:
        label = "How the call ended"
        if found[4] is not None:
            reason = (
                "the number it was to call from was taken away"
                if found[4] == "from_number_withdrawn"
                else "the calling platform held it"
            )
            return problem(
                "record",
                label,
                f"It was never placed: {reason}.",
                evidence,
                f"not_placed {found[4]}",
            )
        if found[5]:
            return ok("record", label, "It was put through to a phone.", evidence)
        if status in _CALL_ENDS:
            fix = (
                ask_fix("Call again", "Call this person back")
                if outbound and status != "failed"
                else None
            )
            return problem(
                "record", label, _CALL_ENDS[status], evidence, f"status {status}", fix=fix
            )
        if status in ("queued", "ringing", "in_progress"):
            return ok("record", label, "It has not finished yet.", evidence, f"status {status}")
        return ok(
            "record",
            label,
            f"It connected for {found[3] or 0} seconds.",
            evidence,
            f"status {status}",
        )

    async def platform() -> Check:
        return await platform_outbound(session)

    async def account() -> Check:
        return await account_outbound(session, tenant_id)

    async def agent() -> Check:
        return agent_switched_on(row, agent_id, answers=not outbound)

    async def person() -> Check:
        label = "This person may be called"
        phone = found[8] if outbound else found[9]
        if not phone:
            return unknown("person", label, "The number is no longer on file.", evidence)
        refused = await person_level_refusal(session, tenant_id=tenant_id, phone_e164=str(phone))
        if refused is None:
            return ok("person", label, "Nothing stops calling them.", evidence)
        return problem(
            "person",
            label,
            refused.reason or "This person may not be called.",
            evidence,
            f"rule {refused.rule}",
            fix=screen_fix("Open do not call", "Do not call"),
        )

    async def summary() -> Check:
        label = "The summary was written"
        if found[6] == "failed":
            return problem(
                "summary",
                label,
                "The summary could not be written.",
                evidence,
                fix=ask_fix("Summarise again", "Summarise this call again"),
            )
        if found[6] == "pending":
            return unknown("summary", label, "The summary is still being written.", evidence)
        return ok("summary", label, "Done.", evidence)

    steps: list[tuple[str, str, CheckFn]] = [("record", "How the call ended", record)]
    if outbound:
        steps += [
            ("platform", "Calevate is placing calls", platform),
            ("account", "Your account may place calls", account),
        ]
    steps.append(("agent", "The agent is switched on", agent))
    if outbound:
        steps.append(("person", "This person may be called", person))
    steps.append(("summary", "The summary was written", summary))
    checks = await _run(session, steps)
    return Diagnosis("call", "Why this call failed", tuple(checks))


# --- family: why is my campaign not calling? --------------------------------------------------


async def diagnose_campaign(session: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> Diagnosis:
    from apps.api.campaigns import service as campaigns_service
    from apps.api.core.errors import ProblemError

    try:
        progress = await campaigns_service.campaign_progress(session, campaign_id)
    except ProblemError:
        return Diagnosis(
            "campaign",
            "That campaign",
            (
                problem(
                    "campaign",
                    "The campaign is in this account",
                    "No campaign with that id in this account.",
                    f"campaign_id {campaign_id}",
                ),
            ),
        )
    name = _clean(str(progress["name"]))[:60]
    status = str(progress["status"])
    evidence = f"campaign_id {campaign_id}"

    async def platform() -> Check:
        return await platform_outbound(session)

    async def state() -> Check:
        label = "The campaign is running"
        if status == "running":
            return ok("state", label, "It is running.", evidence)
        if status == "paused":
            why = progress["pause_reason"]
            return problem(
                "state",
                label,
                f"{name} is paused" + (f": {_clean(str(why))}." if why else "."),
                evidence,
                fix=ask_fix("Resume it", f"Resume the campaign {name}"),
            )
        if status == "draft":
            return problem(
                "state",
                label,
                f"{name} has not been launched.",
                evidence,
                fix=ask_fix("Launch it", f"Launch the campaign {name}"),
            )
        if status == "scheduled":
            return problem(
                "state",
                label,
                f"{name} starts {ist_stamp(progress['scheduled_start_at'])} IST.",
                evidence,
            )
        return problem("state", label, f"{name} has finished.", evidence)

    async def gate() -> Check:
        label = "Nothing blocks its calls"
        if status in ("draft", "scheduled"):
            blockers = await campaigns_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
            found = [(b.rule, b.reason) for b in blockers if b.rule != "status"]
        elif status == "running":
            found = [(b["rule"], b["reason"]) for b in progress["not_calling"]]
        else:
            return unknown("gate", label, "Only checked for a campaign that can call.", evidence)
        if not found:
            return ok("gate", label, "Nothing blocks it.", evidence)
        rule, reason = found[0]
        more = f" ({len(found) - 1} more)" if len(found) > 1 else ""
        return problem(
            "gate",
            label,
            _clean(reason) + more,
            evidence,
            f"rule {rule}",
            fix=rule_fix(rule) or ask_fix("Show the details", f"What blocks the campaign {name}?"),
        )

    async def hours() -> Check:
        label = "It is inside calling hours"
        if status != "running":
            return unknown("hours", label, "Only checked while it runs.", evidence)
        if progress["waiting_for_calling_hours"]:
            window = progress["calling_hours"]
            span = f"{window['start']}-{window['end']} IST" if window else "09:00-21:00 IST"
            return problem("hours", label, f"It is outside its calling hours ({span}).", evidence)
        return ok("hours", label, "Yes.", evidence)

    async def contacts() -> Check:
        label = "People are left to call"
        counts: Mapping[str, int] = progress["contacts"]
        pending = int(counts.get("pending", 0))
        retrying = int(progress.get("retries_waiting") or 0)
        if pending or retrying:
            return ok("contacts", label, f"{pending} waiting, {retrying} to try again.", evidence)
        if not progress["total"]:
            return problem(
                "contacts",
                label,
                f"{name} has nobody on its list.",
                evidence,
                fix=ask_fix("Add people", f"Add leads to the campaign {name}"),
            )
        return problem("contacts", label, "Everyone on the list has been called.", evidence)

    checks = await _run(
        session,
        (
            ("platform", "Calevate is placing calls", platform),
            ("state", "The campaign is running", state),
            ("gate", "Nothing blocks its calls", gate),
            ("hours", "It is inside calling hours", hours),
            ("contacts", "People are left to call", contacts),
        ),
    )
    return Diagnosis("campaign", f"Why {name} is not calling", tuple(checks))


# --- family: why didn't the lead reach my Sheet / webhook / WhatsApp? -------------------------

Channel = Literal["sheet", "webhook", "whatsapp"]
CHANNELS: Final[tuple[Channel, ...]] = ("sheet", "webhook", "whatsapp")
_CHANNEL_WORDS: Final[dict[str, str]] = {
    "sheet": "your Google Sheet",
    "webhook": "your system",
    "whatsapp": "WhatsApp",
}


async def diagnose_delivery(
    session: AsyncSession, tenant_id: UUID, channel: Channel, call_id: UUID | None
) -> Diagnosis:
    from apps.api.actions.credentials import list_credentials
    from apps.api.core.context import Principal
    from apps.api.crm.attention import broken_actions, failed_deliveries
    from apps.api.integrations.routes import list_endpoints

    where = _CHANNEL_WORDS[channel]
    kind = "google_sheets" if channel == "sheet" else "webhook"
    principal = Principal(realm="client", user_id=None, tenant_id=tenant_id, role="owner")

    async def connected() -> Check:
        label = f"{where[0].upper()}{where[1:]} is connected"
        if channel == "whatsapp":
            rows = (
                await session.execute(
                    text(
                        "SELECT id, verified_at IS NOT NULL FROM team_alert_contacts "
                        "WHERE channel = 'whatsapp' AND removed_at IS NULL"
                    )
                )
            ).all()
            if not rows:
                return problem(
                    "connected",
                    label,
                    "No WhatsApp number gets your alerts.",
                    "team_alert_contacts",
                    fix=screen_fix("Set up alerts", "Alerts"),
                )
            if not any(r[1] for r in rows):
                return problem(
                    "connected",
                    label,
                    "Your WhatsApp number is not confirmed yet.",
                    *[f"contact_id {r[0]}" for r in rows],
                    fix=screen_fix("Confirm it", "Alerts"),
                )
            return ok(
                "connected",
                label,
                "A confirmed number gets alerts.",
                *[f"contact_id {r[0]}" for r in rows if r[1]],
            )
        endpoints = [e for e in await list_endpoints(session, 200, principal) if e.kind == kind]
        if not endpoints:
            return problem(
                "connected",
                label,
                f"Nothing sends leads to {where} yet.",
                "outbound_webhooks",
                fix=screen_fix("Connect it", "Integrations"),
            )
        live = [e for e in endpoints if e.active]
        if not live:
            return problem(
                "connected",
                label,
                f"The connection to {where} is switched off.",
                *[f"endpoint_id {e.id}" for e in endpoints],
                fix=ask_fix("Switch it on", f"Switch the connection to {where} on"),
            )
        if channel == "sheet" and not [
            c for c in await list_credentials(session) if c.kind == "google_sheets"
        ]:
            return problem(
                "connected",
                label,
                "Your Google account is not connected.",
                "integration_credentials",
                fix=screen_fix("Connect Google", "Integrations"),
            )
        return ok("connected", label, "Connected and on.", *[f"endpoint_id {e.id}" for e in live])

    async def this_call() -> Check:
        label = "This call was sent"
        if call_id is None:
            return unknown("this_call", label, "No call was named.")
        if channel == "whatsapp":
            alert = (
                await session.execute(
                    text(
                        "SELECT a.id, a.status FROM team_alerts a JOIN team_alert_contacts t "
                        "ON t.id = a.contact_id WHERE a.call_id = :cid AND t.channel = 'whatsapp' "
                        "ORDER BY a.created_at DESC LIMIT 1"
                    ),
                    {"cid": call_id},
                )
            ).first()
            if alert is None:
                rule = (
                    await session.execute(
                        text(
                            "SELECT r.id FROM team_alert_rules r JOIN calls c "
                            "ON c.agent_id = r.agent_id WHERE c.id = :cid"
                        ),
                        {"cid": call_id},
                    )
                ).first()
                if rule is None:
                    return problem(
                        "this_call",
                        label,
                        "This agent has no alert set up.",
                        f"call_id {call_id}",
                        fix=screen_fix("Set up alerts", "Alerts"),
                    )
                return problem(
                    "this_call",
                    label,
                    "The call did not match your alert rules.",
                    f"call_id {call_id}",
                    f"rule {rule[0]}",
                    fix=screen_fix("Check the rules", "Alerts"),
                )
            if alert[1] == "failed":
                return problem(
                    "this_call",
                    label,
                    "The WhatsApp alert for this call failed.",
                    f"alert {alert[0]}",
                    fix=screen_fix("Check alerts", "Alerts"),
                )
            if alert[1] == "queued":
                return unknown(
                    "this_call", label, "The alert is still waiting to send.", f"alert {alert[0]}"
                )
            return ok("this_call", label, f"Alert {alert[1]}.", f"alert {alert[0]}")
        sent = (
            await session.execute(
                text("SELECT status, crm_notified_at FROM calls WHERE id = :cid"),
                {"cid": call_id},
            )
        ).first()
        if sent is None:
            return problem(
                "this_call", label, "No call with that id in this account.", f"call_id {call_id}"
            )
        if sent[1] is not None:
            return ok("this_call", label, f"Sent {ist_stamp(sent[1])} IST.", f"call_id {call_id}")
        if sent[0] in ("queued", "ringing", "in_progress"):
            return unknown("this_call", label, "The call has not finished.", f"call_id {call_id}")
        return problem(
            "this_call", label, "This call's details were not sent yet.", f"call_id {call_id}"
        )

    async def failures() -> Check:
        label = "Recent sends arrived"
        if channel == "whatsapp":
            rows = (
                await session.execute(
                    text(
                        "SELECT a.id FROM team_alerts a JOIN team_alert_contacts t "
                        "ON t.id = a.contact_id WHERE t.channel = 'whatsapp' AND a.status = "
                        "'failed' AND a.created_at > now() - make_interval(days => :d) "
                        "ORDER BY a.created_at DESC LIMIT 5"
                    ),
                    {"d": RECENT_DAYS},
                )
            ).all()
            if rows:
                return problem(
                    "failures",
                    label,
                    f"{len(rows)} WhatsApp alert(s) failed lately.",
                    *[f"alert {r[0]}" for r in rows],
                    fix=screen_fix("Check alerts", "Alerts"),
                )
            return ok("failures", label, "None failed lately.", "team_alerts")
        failed = await failed_deliveries(session, limit=20)
        mine = [
            item
            for item in failed.items
            if (kind == "google_sheets") == ("spreadsheet" in item.title)
        ]
        if not mine:
            return ok("failures", label, "None failed lately.", "webhook_deliveries")
        first = mine[0]
        return problem(
            "failures",
            label,
            _clean(first.detail),
            *[f"delivery_id {item.id}" for item in mine],
            fix=ask_fix("Send it again", "Resend the failed delivery"),
        )

    async def actions() -> Check:
        label = "In-call actions can run"
        broken = await broken_actions(session, limit=5)
        if not broken.items:
            return ok("actions", label, "None is broken.", "action_invocations")
        return problem(
            "actions",
            label,
            _clean(broken.items[0].title),
            *[f"action_id {item.id}" for item in broken.items],
            fix=screen_fix("Reconnect", "Integrations"),
        )

    steps: list[tuple[str, str, CheckFn]] = [
        ("connected", f"{where[0].upper()}{where[1:]} is connected", connected),
        ("this_call", "This call was sent", this_call),
        ("failures", "Recent sends arrived", failures),
    ]
    if channel == "whatsapp":
        steps.append(("actions", "In-call actions can run", actions))
    checks = await _run(session, steps)
    return Diagnosis("delivery", f"Why the lead did not reach {where}", tuple(checks))


# --- family: why isn't my knowledge used? -----------------------------------------------------


async def diagnose_knowledge(
    session: AsyncSession, tenant_id: UUID, agent_id: UUID | None
) -> Diagnosis:
    from apps.api.kb import service as kb_service
    from apps.api.kb.reconciliation import KB_DRIFT_STATES_OUT_OF_SYNC
    from apps.api.kb.store import find_items, undelivered_source_ids
    from apps.api.teach import questions as teach_questions

    sources = await kb_service.list_sources(session, limit=200)
    row = None if agent_id is None else await _agent_row(session, agent_id)
    name = _named(row) if row is not None else "your agents"

    async def added() -> Check:
        label = "Something has been added"
        if not sources:
            return problem(
                "added",
                label,
                "Nothing has been added to what your agents know.",
                "kb_sources",
                fix=screen_fix("Add knowledge", "What your agents know"),
            )
        return ok("added", label, f"{len(sources)} item(s) on file.", "kb_sources")

    async def published() -> Check:
        label = "It has been approved"
        if sources and not any(s["published_at"] is not None for s in sources):
            waiting = [s for s in sources if s["status"] == "pending_approval"]
            return problem(
                "published",
                label,
                "None of it is approved yet" + (", it is waiting for review." if waiting else "."),
                *[f"source_id {s['id']}" for s in waiting],
            )
        return ok("published", label, "Approved.", "kb_sources")

    async def states() -> Check:
        label = "Nothing is stuck"
        stuck, total = await find_items(
            session,
            tenant_id=tenant_id,
            kinds=None,
            states=["needs_attention"],
            contains=None,
            offset=0,
            limit=5,
        )
        if total:
            return problem(
                "states",
                label,
                f"{total} item(s) need attention.",
                *[item.ref for item in stuck],
                fix=screen_fix("Fix them", "What your agents know"),
            )
        reading, busy = await find_items(
            session,
            tenant_id=tenant_id,
            kinds=None,
            states=["being_read", "getting_ready"],
            contains=None,
            offset=0,
            limit=5,
        )
        if busy:
            return problem(
                "states",
                label,
                f"{busy} item(s) are still being prepared.",
                *[item.ref for item in reading],
            )
        return ok("states", label, "Nothing stuck.", "kb_sources")

    async def delivered() -> Check:
        label = "The agents get the words"
        undelivered = await undelivered_source_ids(session)
        opaque = [s for s in sources if s["is_active"] and s["id"] in undelivered]
        if opaque:
            return problem(
                "delivered",
                label,
                f"{len(opaque)} saved file(s) or link(s) are not used by agents yet.",
                *[f"source_id {s['id']}" for s in opaque],
                fix=screen_fix("See them", "What your agents know"),
            )
        return ok("delivered", label, "Yes.", "kb_sources")

    async def on_agent() -> Check:
        label = f"{name[0].upper()}{name[1:]} holds the latest"
        if agent_id is None:
            return unknown("on_agent", label, "No agent was named.")
        verdict = (
            await session.execute(
                text(
                    "SELECT kb_drift_state, kb_drift_checked_at FROM engine_agent_routes "
                    "WHERE agent_id = :aid AND active ORDER BY kb_drift_checked_at DESC "
                    "NULLS LAST LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).first()
        if verdict is None or verdict[1] is None:
            return unknown("on_agent", label, "Not checked yet.", f"agent_id {agent_id}")
        stamp = f"checked {ist_stamp(verdict[1])} IST"
        if verdict[0] in KB_DRIFT_STATES_OUT_OF_SYNC:
            return problem(
                "on_agent",
                label,
                f"{name} does not hold your latest knowledge.",
                f"kb_drift {verdict[0]}",
                stamp,
                fix=ask_fix("Put it live again", f"Put {name} live again"),
            )
        if verdict[0] in ("unreadable", "unreachable"):
            return unknown("on_agent", label, "The calling platform could not be read.", stamp)
        return ok("on_agent", label, "Yes.", stamp)

    async def gaps() -> Check:
        label = "Callers' questions are covered"
        found = await teach_questions.list_questions(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
        if found.open_count:
            return problem(
                "gaps",
                label,
                f"{found.open_count} question(s) callers asked are not in it yet.",
                *[f"question {q.key}" for q in found.items],
                fix=ask_fix("Answer them", "What questions does my agent need answered?"),
            )
        return ok("gaps", label, "No open questions.", "knowledge_gaps")

    checks = await _run(
        session,
        (
            ("added", "Something has been added", added),
            ("published", "It has been approved", published),
            ("states", "Nothing is stuck", states),
            ("delivered", "The agents get the words", delivered),
            ("on_agent", "The agent holds the latest", on_agent),
            ("gaps", "Callers' questions are covered", gaps),
        ),
    )
    return Diagnosis(
        "knowledge",
        f"Why {name} do not use your knowledge"
        if agent_id is None
        else f"Why {name} does not use your knowledge",
        tuple(checks),
    )


# --- what the model reads ---------------------------------------------------------------------


def render(diagnosis: Diagnosis) -> DiagnosisText:
    """A few lines for the model. The person sees the card, so the answer is one line."""
    cause = diagnosis.cause
    lines = [f"{diagnosis.subject}: {diagnosis.verdict}"]
    if cause is not None and cause.fix is not None:
        fix = cause.fix
        lines.append(
            f"Fix: {fix.label}"
            + (f" (on {fix.where})" if fix.where else "")
            + (f'; the button asks you: "{fix.ask}"' if fix.ask else "")
        )
    tally = {
        status: sum(c.status == status for c in diagnosis.checks)
        for status in ("ok", "problem", "unknown")
    }
    lines.append(
        f"Checked {len(diagnosis.checks)}: {tally['ok']} fine, {tally['problem']} wrong, "
        f"{tally['unknown']} unknown. The person sees these as a checklist card: answer in one "
        "short line naming the first cause, never a guess past what is listed."
    )
    for check in diagnosis.checks:
        lines.append(
            f"- {check.status}: {check.label}: {check.detail} "
            + " ".join(f"[{e}]" for e in check.evidence)
        )
    return DiagnosisText(_clean("\n".join(lines)), diagnosis)


# --- the area reads ---------------------------------------------------------------------------


def _uuid(args: Mapping[str, Any], key: str) -> UUID | None:
    raw = args.get(key)
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _missing(key: str, where: str) -> str:
    return f"`{key}` was missing or is not an id. Take it from the SCREEN STATE or {where}."


async def _agent_diagnose(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    agent_id = _uuid(args, "agent_id")
    if agent_id is None:
        return _missing("agent_id", "agents_list")
    assert context.tenant_id is not None
    return render(await diagnose_agent(session, context.tenant_id, agent_id))


async def _call_diagnose(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    call_id = _uuid(args, "call_id")
    if call_id is None:
        return _missing("call_id", "calls_recent")
    assert context.tenant_id is not None
    return render(await diagnose_call(session, context.tenant_id, call_id))


async def _campaign_diagnose(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    campaign_id = _uuid(args, "campaign_id")
    if campaign_id is None:
        return _missing("campaign_id", "campaigns_list")
    assert context.tenant_id is not None
    return render(await diagnose_campaign(session, context.tenant_id, campaign_id))


async def _delivery_diagnose(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    channel = args.get("channel")
    if channel not in CHANNELS:
        return "`channel` must be one of: " + ", ".join(CHANNELS) + "."
    assert context.tenant_id is not None
    return render(
        await diagnose_delivery(session, context.tenant_id, channel, _uuid(args, "call_id"))
    )


async def _knowledge_diagnose(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    assert context.tenant_id is not None
    return render(await diagnose_knowledge(session, context.tenant_id, _uuid(args, "agent_id")))


def _params(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_ID: Final = {"type": "string"}
_ID_OR_NULL: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}

#: Client realm only: the admin realm asks through `admin_diagnose`, which runs these same
#: families for any client plus the platform's own checks, so the admin array is not
#: charged five flat schemas.
DIAGNOSE_READS: Final[tuple[ReadTool, ...]] = (
    ReadTool(
        name="agent_diagnose",
        description="Why an agent does not answer calls: ordered checks, first cause, fix.",
        parameters=_params(agent_id=_ID),
        permission="agents:read",
        run=_agent_diagnose,
    ),
    ReadTool(
        name="call_diagnose",
        description="Why one call failed: ordered checks, first cause, fix.",
        parameters=_params(call_id=_ID),
        permission="calls:read",
        run=_call_diagnose,
    ),
    ReadTool(
        name="campaign_diagnose",
        description="Why a campaign is not calling: ordered checks, first cause, fix.",
        parameters=_params(campaign_id=_ID),
        permission="leads:read",
        run=_campaign_diagnose,
    ),
    ReadTool(
        name="delivery_diagnose",
        description="Why a lead did not reach a Sheet, webhook or WhatsApp.",
        parameters=_params(channel={"type": "string", "enum": list(CHANNELS)}, call_id=_ID_OR_NULL),
        permission="org:read",
        run=_delivery_diagnose,
    ),
    ReadTool(
        name="knowledge_diagnose",
        description="Why the agents do not use the business's knowledge.",
        parameters=_params(agent_id=_ID_OR_NULL),
        permission="agents:read",
        run=_knowledge_diagnose,
    ),
)

DIAGNOSE_READ_NAMES: Final[frozenset[str]] = frozenset(tool.name for tool in DIAGNOSE_READS)

#: The families by the question an operator names in `admin_diagnose`.
FAMILIES: Final[tuple[Family, ...]] = ("agent", "call", "campaign", "delivery", "knowledge")


async def diagnose_family(
    session: AsyncSession, tenant_id: UUID, family: str, args: Mapping[str, Any]
) -> Diagnosis | str:
    """One family by name, for the admin twin. A string is a refusal the model can act on."""
    target = _uuid(args, "id")
    if family == "knowledge":
        return await diagnose_knowledge(session, tenant_id, target)
    if family == "delivery":
        channel = args.get("channel")
        if channel not in CHANNELS:
            return "`channel` must be one of: " + ", ".join(CHANNELS) + "."
        return await diagnose_delivery(session, tenant_id, channel, target)
    if target is None:
        return "`id` is required for that question: the agent, call or campaign id."
    runner = {"agent": diagnose_agent, "call": diagnose_call, "campaign": diagnose_campaign}
    if family not in runner:
        return "`question` must be one of: " + ", ".join(FAMILIES) + "."
    return await runner[family](session, tenant_id, target)


def with_platform(diagnosis: Diagnosis, platform: Sequence[Check]) -> Diagnosis:
    """The platform's own checks first: a vendor outage explains everything after it."""
    return Diagnosis(diagnosis.family, diagnosis.subject, (*platform, *diagnosis.checks))


async def platform_checks(session: AsyncSession, tenant_id: UUID) -> list[Check]:
    """Operator-only checks: the calling platform's health, the outbox, the workspace.

    `session` is the admin session; the workspace row is read under the client's own."""
    from apps.api.db.session import tenant_session
    from apps.api.tenancy.engine_workspace import engine_has_workspaces, read_workspace_state

    async def vendor() -> Check:
        label = "The calling platform is answering"
        row = (
            await session.execute(
                text(
                    "SELECT coalesce(sum(server_errors + unreachable), 0), max(bucket_start) "
                    "FROM platform_engine_health "
                    "WHERE bucket_start > now() - interval '15 minutes'"
                )
            )
        ).first()
        errors = int(row[0]) if row is not None else 0
        if errors:
            return problem(
                "vendor",
                label,
                f"{errors} failed request(s) in 15 minutes.",
                "platform_engine_health",
            )
        return ok("vendor", label, "No failures in 15 minutes.", "platform_engine_health")

    async def outbox() -> Check:
        label = "Background work is moving"
        row = (
            await session.execute(
                text(
                    "SELECT count(*), min(created_at) FROM outbox_messages WHERE status = 'pending'"
                )
            )
        ).first()
        waiting = int(row[0]) if row is not None else 0
        if waiting and row is not None and isinstance(row[1], datetime):
            minutes = int((datetime.now(row[1].tzinfo) - row[1]).total_seconds() // 60)
            if minutes >= OUTBOX_STUCK_MINUTES:
                return problem(
                    "outbox",
                    label,
                    f"{waiting} message(s) waiting, oldest {minutes} min.",
                    "outbox_messages",
                )
        return ok("outbox", label, f"{waiting} waiting.", "outbox_messages")

    async def workspace() -> Check:
        label = "The client's calling space is set up"
        if not engine_has_workspaces():
            return ok("workspace", label, "Not needed.", "tenant_engine_workspaces")
        async with tenant_session(tenant_id) as scoped:
            state = await read_workspace_state(scoped, tenant_id)
        if state.active:
            return ok("workspace", label, "Active.", "tenant_engine_workspaces")
        return problem(
            "workspace",
            label,
            f"Workspace {state.status}"
            + (f", last error {state.last_error_code}" if state.last_error_code else "")
            + f", {state.attempts} attempt(s).",
            "tenant_engine_workspaces",
        )

    return await _run(
        session,
        (
            ("vendor", "The calling platform is answering", vendor),
            ("outbox", "Background work is moving", outbox),
            ("workspace", "The client's calling space is set up", workspace),
        ),
    )


__all__ = [
    "CHANNELS",
    "DIAGNOSE_READS",
    "DIAGNOSE_READ_NAMES",
    "FAMILIES",
    "Check",
    "Diagnosis",
    "DiagnosisText",
    "Fix",
    "diagnose_agent",
    "diagnose_call",
    "diagnose_campaign",
    "diagnose_delivery",
    "diagnose_family",
    "diagnose_knowledge",
    "platform_checks",
    "render",
    "with_platform",
]
