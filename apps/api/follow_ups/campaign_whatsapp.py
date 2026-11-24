"""A campaign's WhatsApp follow-up, set up from its card in one press (D-1041).

The campaign page's "Follow up on WhatsApp" card and Pip's `follow_up_campaign_whatsapp` both
call `set_up`, `switch` and `card` here, so the two doors cannot differ.

WHAT `set_up` MAKES. One Follow-up per campaign (`follow_ups.campaign_id`, starter
`campaign_whatsapp`, unique per campaign): a call this campaign placed ends with one of the
chosen outcomes, the configured wait passes (`campaign_whatsapp_follow_up_wait_minutes`), and
one WhatsApp message goes out. The message, and which of the campaign's outcomes it is for,
are Pip's (`apps/workers/campaign_whatsapp_follow_up`), never the owner's to fill in. Writing
is a model call, which a request handler may not make, so `set_up` queues the pass on the
campaign (`agents/agent_pass`, columns `campaigns.whatsapp_follow_up_*`) and the card shows
Pip writing until `install` saves it.

NOTHING IS SENT UNTIL THE OWNER SWITCHES IT ON. `install` leaves the Follow-up a draft;
`switch(on=True)` is the only thing that publishes it, and it refuses while WhatsApp has not
approved the message. Every message a run sends still passes the dispatch gate and the
recipient's WhatsApp opt-in at the moment it goes out (`crm/lead_message.send_lead_whatsapp`).

ONLY THE OWNER SETS IT UP. `set_up` ends in a WhatsApp template submitted in the business's
name, so both doors require `whatsapp/templates.TEMPLATE_PERMISSION`, the WhatsApp screen's
own (founder, 25 Nov 2026); `switch` stays `leads:dispatch`.

NOT CONNECTED IS A REFUSAL, NOT A BROKEN DRAFT. Without a connected WhatsApp account that can
send, `set_up` refuses with `whatsapp_not_connected` and makes nothing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import service
from apps.api.follow_ups.models import MAX_NAME_CHARS

log = get_logger(__name__)

#: The ARQ job that writes the message (`apps/workers/campaign_whatsapp_follow_up`).
JOB: Final = "write_campaign_whatsapp_follow_up"
SLOT: Final = agent_pass.PassSlot(
    "whatsapp_follow_up", JOB, table="campaigns", gone="archived_at", id_key="campaign_id"
)
STARTER: Final = "campaign_whatsapp"
#: The platform's own outcome for a call that ended before the talk did
#: (`crm/outcomes`, rule 5). It is the one "did not finish" every business shares, so it is
#: always chosen; the campaign's own outcomes Pip picks are added to it.
DID_NOT_FINISH: Final = "hung_up_early"
#: The longest message Pip may write: a phone screen, well inside WhatsApp's 1,024 characters.
MESSAGE_MAX: Final = 700

#: Why the last pass made nothing, as the card says it. The keys are the codes the worker
#: stores in `campaigns.whatsapp_follow_up_error`.
FAILURES: Final[dict[str, str]] = {
    "not_connected": "Connect WhatsApp, then try again.",
    "no_material": "Write this campaign's main task first, so Pip knows what to say.",
    "not_written": (
        "Pip could not write a message from what this campaign says. Add detail to the main "
        "task, then try again."
    ),
    "language": "WhatsApp messages cannot be written in this campaign's language yet.",
    "message_not_sent": "WhatsApp did not take the message for review. Try again in a minute.",
    "unavailable": "Pip could not write it just now. Try again in a minute.",
    "allowance": (
        "This month's included AI assistance is used up. Add credit, or wait for the next "
        "billing month."
    ),
}

Phase = Literal["not_connected", "none", "writing", "failed", "made"]


def _not_connected() -> ProblemError:
    return ProblemError.business_rule(
        "whatsapp_not_connected",
        "WhatsApp is not connected, so there is nothing to send the follow-up from.",
        remediation="Connect WhatsApp, then set it up again.",
    )


# --- reading ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class Made:
    """The Follow-up the card made, as the card shows it."""

    id: UUID
    status: str
    message: str | None
    #: `whatsapp_templates.status` of its message (`pending`, `approved`, `rejected`, ...);
    #: None when the step names no message of this account.
    message_status: str | None
    #: WhatsApp's code for the message's language (`te`, `hi`, `en`), for the page's `lang`.
    message_language: str | None
    outcomes: list[Outcome]
    wait_minutes: int
    sent: int
    replied: int
    has_unpublished_changes: bool


@dataclass(frozen=True, slots=True)
class Card:
    phase: Phase
    connected: bool
    #: The sentence for a pass that made nothing (`FAILURES`).
    failure: str | None
    made: Made | None


async def _campaign(session: AsyncSession, campaign_id: UUID, *, lock: bool = False) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT c.id, c.agent_id, c.whatsapp_follow_up_state, c.whatsapp_follow_up_error, "
                # A pass queued or running past the stale limit has no live job behind it.
                "c.whatsapp_follow_up_at < now() - make_interval(mins => :stale) "
                "FROM campaigns c WHERE c.id = :cid AND c.archived_at IS NULL"
                + (" FOR UPDATE" if lock else "")
            ),
            {"cid": campaign_id, "stale": agent_pass.STALE_MINUTES},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return row


async def made_id(session: AsyncSession, campaign_id: UUID) -> UUID | None:
    found = (
        await session.execute(
            text(
                "SELECT id FROM follow_ups "
                "WHERE campaign_id = :cid AND starter = 'campaign_whatsapp'"
            ),
            {"cid": campaign_id},
        )
    ).scalar()
    return UUID(str(found)) if found is not None else None


def message_step(steps: list[d.AnyStep]) -> d.WhatsAppStep | None:
    return next((s for s in steps if isinstance(s, d.WhatsAppStep)), None)


async def outcome_labels(session: AsyncSession, agent_id: UUID | None) -> dict[str, str]:
    """Every outcome key a campaign call can end with, to the words the owner reads: the
    platform's own outcomes and the campaign agent's business outcomes."""
    from apps.api.agents.call_outcomes import outcomes_in_use
    from apps.api.crm.export_words import OUTCOME_WORDS

    raw = (
        await session.execute(
            text("SELECT business_outcomes FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar()
    return {**OUTCOME_WORDS, **{o.key: o.label for o in outcomes_in_use(raw)[0]}}


async def _counts(session: AsyncSession, follow_up_id: UUID) -> tuple[int, int]:
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM follow_up_run_events e JOIN follow_up_runs r "
                "ON r.id = e.run_id WHERE r.follow_up_id = :fid AND e.kind = 'whatsapp' "
                "AND e.result = 'sent'), (SELECT count(*) FROM follow_up_runs "
                "WHERE follow_up_id = :fid AND end_reason = 'replied')"
            ),
            {"fid": follow_up_id},
        )
    ).one()
    return int(row[0]), int(row[1])


async def _made(session: AsyncSession, follow_up_id: UUID, agent_id: UUID | None) -> Made:
    row = await service.get(session, follow_up_id)
    step = message_step(row.steps)
    template = None
    if step is not None:
        template = (
            await session.execute(
                text("SELECT body, status, language FROM whatsapp_templates WHERE id = :tid"),
                {"tid": step.template_id},
            )
        ).first()
    labels = await outcome_labels(session, agent_id)
    trigger = row.trigger
    keys = (trigger.outcomes or []) if isinstance(trigger, d.CallEndedTrigger) else []
    wait = next((s for s in row.steps if isinstance(s, d.WaitStep)), None)
    wait_minutes = (
        (wait.minutes or 0) + (wait.hours or 0) * 60 + (wait.days or 0) * 1440 if wait else 0
    )
    sent, replied = await _counts(session, follow_up_id)
    return Made(
        id=row.id,
        status=row.status,
        message=str(template[0]) if template is not None else None,
        message_status=str(template[1]) if template is not None else None,
        message_language=str(template[2]) if template is not None else None,
        outcomes=[Outcome(key=k, label=labels.get(k, k.replace("_", " "))) for k in keys],
        wait_minutes=wait_minutes,
        sent=sent,
        replied=replied,
        has_unpublished_changes=row.has_unpublished_changes,
    )


async def card(session: AsyncSession, campaign_id: UUID) -> Card:
    from apps.api.crm.swipe import connected_account

    campaign = await _campaign(session, campaign_id)
    connected = await connected_account(session) is not None
    follow_up_id = await made_id(session, campaign_id)
    writing = campaign[2] in ("queued", "running") and not campaign[4]
    made = await _made(session, follow_up_id, campaign[1]) if follow_up_id else None
    if writing:
        phase: Phase = "writing"
    elif made is not None:
        phase = "made"
    elif not connected:
        phase = "not_connected"
    elif campaign[2] == "failed":
        phase = "failed"
    else:
        phase = "none"
    failure = (
        FAILURES.get(str(campaign[3]), FAILURES["unavailable"])
        if campaign[2] == "failed" and not writing
        else None
    )
    return Card(phase=phase, connected=connected, failure=failure, made=made)


def _usable(made: Made) -> bool:
    """A message WhatsApp approved or is still reviewing: nothing for Pip to write again."""
    return made.message_status in ("approved", "pending")


# --- the two writes ---------------------------------------------------------------------


async def set_up(session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID) -> Card:
    """Ask Pip to write this campaign's WhatsApp follow-up. An existing one whose message is
    approved or in review is returned as it is; one whose message WhatsApp turned down (or
    that names none) gets a new message written into it. Spends the AI allowance."""
    from apps.api.billing.ai_quota import require_ai_assist
    from apps.api.crm.swipe import connected_account

    await _campaign(session, campaign_id, lock=True)
    follow_up_id = await made_id(session, campaign_id)
    if follow_up_id is not None:
        current = await card(session, campaign_id)
        if current.made is not None and _usable(current.made):
            return current
    if await connected_account(session) is None:
        raise _not_connected()
    await require_ai_assist(session, tenant_id=tenant_id)
    await session.execute(
        text("UPDATE campaigns SET whatsapp_follow_up_error = NULL WHERE id = :cid"),
        {"cid": campaign_id},
    )
    await agent_pass.queue(session, SLOT, tenant_id=tenant_id, row_id=campaign_id)
    return await card(session, campaign_id)


def _refuse_on(detail: str, code: str) -> ProblemError:
    return ProblemError.conflict(code, detail)


async def switch(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, on: bool, user_id: UUID | None
) -> Card:
    """On publishes the Follow-up as it stands (the owner may have edited it) and turns it on;
    Off turns it off, which also stops leads waiting in it, so nothing more is sent."""
    await _campaign(session, campaign_id, lock=True)
    follow_up_id = await made_id(session, campaign_id)
    if follow_up_id is None:
        raise ProblemError.not_found("WhatsApp follow-up")
    row = await service.get(session, follow_up_id, lock=True)
    if not on:
        if row.status in ("live", "paused"):
            await service.turn_off(session, follow_up_id)
        return await card(session, campaign_id)
    if row.status == "live" and not row.has_unpublished_changes:
        return await card(session, campaign_id)
    step = message_step(row.steps)
    status = (
        (
            await session.execute(
                text("SELECT status FROM whatsapp_templates WHERE id = :tid"),
                {"tid": step.template_id},
            )
        ).scalar()
        if step is not None
        else None
    )
    if status == "pending":
        raise _refuse_on(
            "WhatsApp is still reviewing the message. It can be turned on once it is approved.",
            "whatsapp_message_in_review",
        )
    if status != "approved":
        raise _refuse_on(
            "WhatsApp has not approved this message. Ask Pip to write it again.",
            "whatsapp_message_not_approved",
        )
    if row.has_unpublished_changes:
        row = await service.publish(
            session,
            follow_up_id,
            tenant_id=tenant_id,
            expected_updated_at=row.updated_at,
            user_id=user_id,
        )
    if row.status in ("paused", "off"):
        await service.resume(session, follow_up_id, tenant_id=tenant_id)
    return await card(session, campaign_id)


# --- what the worker saves ---------------------------------------------------------------


def definition_for(
    *, campaign_id: UUID, template_id: UUID, outcomes: list[str], wait_minutes: int
) -> tuple[d.AnyTrigger, list[d.AnyStep], d.Settings]:
    """The trigger, steps and settings of a campaign's WhatsApp follow-up. A person gets the
    message once (`again: never`): a campaign may call them several times, and each ended
    call would otherwise send it again."""
    keys = list(dict.fromkeys([DID_NOT_FINISH, *outcomes]))[: d.MAX_OUTCOMES]
    trigger = d.CallEndedTrigger(
        kind="call_ended", calls="outbound", campaign_ids=[campaign_id], outcomes=keys
    )
    message = {"kind": "whatsapp", "template_id": str(template_id), "values": []}
    raw: list[dict[str, Any]] = (
        [
            {"id": "s1", "kind": "wait", "minutes": wait_minutes, "next": "s2"},
            {"id": "s2", **message},
        ]
        if wait_minutes > 0
        else [{"id": "s1", **message}]
    )
    return trigger, d.load_steps(raw), d.Settings(again="never")


def template_category(classification: str) -> str:
    """WhatsApp's category for the message: a promotional campaign's follow-up markets;
    a transactional or service campaign's is about the person's own dealings (UTILITY)."""
    return "MARKETING" if classification == "promotional" else "UTILITY"


def template_name(campaign_id: UUID) -> str:
    """A fresh name each time: a message WhatsApp turned down keeps its name in the account."""
    return f"followup_{campaign_id.hex[:12]}_{secrets.token_hex(3)}"


async def install(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    name: str,
    body: str,
    language: str,
    category: str,
    outcomes: list[str],
    user_id: UUID | None,
) -> str:
    """Send Pip's message to WhatsApp for review and save the Follow-up as a draft (or put the
    new message into the one already made). Returns `made`, or the `FAILURES` code."""
    from apps.api.crm.swipe import connected_account
    from apps.api.whatsapp import accounts, templates

    account = await connected_account(session)
    if account is None:
        return "not_connected"
    template_name_ = template_name(campaign_id)
    try:
        templates.check_template(
            name=template_name_, language=language, category=category, body=body, examples=[]
        )
    except ProblemError as refused:
        log.info("campaign_whatsapp_message_refused", extra={"reason": refused.code})
        return "not_written"
    try:
        token = await accounts.account_token(session, tenant_id=tenant_id, account=account)
    except ProblemError:
        return "not_connected"
    template_id = await templates.insert_template(
        session,
        tenant_id=tenant_id,
        account_id=account.id,
        name=template_name_,
        language=language,
        category=category,
        body=body,
        variables=[],
        origin="client",
        purpose=None,
    )
    if template_id is None:
        return "message_not_sent"
    if (
        await templates.submit(
            session, template_id=template_id, waba_id=account.waba_id, token=token
        )
        == "submit_failed"
    ):
        return "message_not_sent"
    follow_up_id = await made_id(session, campaign_id)
    if follow_up_id is not None:
        row = await service.get(session, follow_up_id, lock=True)
        step = message_step(row.steps)
        if step is not None:
            await service.edit(
                session,
                follow_up_id,
                name=None,
                step_edits=[service.StepEdit(step_id=step.id, template_id=template_id)],
                settings=None,
            )
            return "made"
    trigger, steps, settings = definition_for(
        campaign_id=campaign_id,
        template_id=template_id,
        outcomes=outcomes,
        wait_minutes=get_settings().campaign_whatsapp_follow_up_wait_minutes,
    )
    try:
        await service.create(
            session,
            tenant_id=tenant_id,
            name=" ".join(f"WhatsApp after {name}".split())[:MAX_NAME_CHARS],
            trigger=trigger,
            steps=steps,
            settings=settings,
            starter=STARTER,
            user_id=user_id,
            campaign_id=campaign_id,
        )
    except ProblemError as twin:
        if twin.code != "follow_up_campaign_exists":
            raise
    return "made"


__all__ = [
    "DID_NOT_FINISH",
    "FAILURES",
    "JOB",
    "MESSAGE_MAX",
    "SLOT",
    "STARTER",
    "Card",
    "Made",
    "Outcome",
    "card",
    "definition_for",
    "install",
    "made_id",
    "message_step",
    "outcome_labels",
    "set_up",
    "switch",
    "template_category",
    "template_name",
]
