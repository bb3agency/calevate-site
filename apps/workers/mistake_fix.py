"""The healer playbook `call_mistake_fix` (D-985, D-1005): a real-call mistake the script
causes is repaired in the Inbound line's or campaign's script the call was spoken from.

One step per due incident, on `run_healer`'s tick. The fix row (`agent_mistake_fixes`) is
the truth each step branches on; the incident carries the schedule, the attempt count the
ledger shows, and the escalation:

ACT      The newest call showing the kind names the line or campaign it was spoken from
         (`mistake_fixes.holder_of_latest_call`). A call on neither, or on one with no
         script, has no script to fix: the fix settles `no_job` and the owner's Training tab
         says so. The fix waits (`call_mistake_fix_wait_minutes`, at most
         `call_mistake_fix_max_waits` looks) while that line or campaign has a Pip draft
         being written or waiting for review, its script is hand-written, or the client's AI
         allowance is used up; it never writes over any of them. The mistake's script check
         (`mistake_lints.mistake_findings`) names the lines; none (or only the protected
         opening and notice parts) hands the kind to our team as a platform rule. Otherwise
         the repair pass is asked for on the holder (`agents/script_heal.queue_now`), which
         has Pip rewrite exactly the faulted lines, saves the script itself and meters it to
         the client's AI allowance (founder, 24 Nov 2026: what Pip can fix is fixed
         automatically; this replaced D-1005's draft for the owner to review).
VERIFY   Once the pass has run, the mistake's check is read again on the saved script: no
         faulted line settles the fix `fixed` from now, which the owner reads as fixed in
         their script; a line still faulted asks again up to
         `call_mistake_fix_max_attempts`, then hands the kind to our team.

A draft asked for before the repair saved scripts itself (`proposal_id` set) is still read:
one written waits for the owner as before; one never written is cleared and repaired.
Before D-1005 the healer fixed the agent's own script; a fix still `live` from then is
settled `fixed` on its next step, and its Undo stays.

Nothing here touches the AI or recording notices: their parts are never a fix's paths
(`mistake_fixes.PROTECTED_PARTS`).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from calevate_shared.call_script import upgrade_to_v2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import mistake_fixes, script_heal
from apps.api.agents.call_mistakes import WINDOW_DAYS
from apps.api.agents.capability_manifest import lint_context_for
from apps.api.agents.mistake_fixes import Holder, HolderScript, MistakeFix, holder_table
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer import incidents, ledger
from apps.api.healer.incidents import Incident
from apps.api.healer.playbooks import in_shadow

log = get_logger(__name__)

PLAYBOOK: Final = mistake_fixes.PLAYBOOK
#: Raised when a fix needs a person: one agent's script, so `attention`, never a page.
NEEDS_PERSON: Final = "call_mistake_fix_needs_person"
#: The owner's notice while the fix's draft waits for them (`healer/notices.
#: proposed_fix_notice`).
PROPOSED_NOTICE: Final = "script_fix_proposed"
#: The owner's notice while the fix waits on the AI allowance.
WAITING_NOTICE: Final = "script_fix_waiting"
#: How soon a fix looks again after asking for the repair: the pass waits out its debounce
#: (`script_heal.DEBOUNCE_S`) and then asks one model, well inside this.
REPAIR_LOOK_S: Final = 2 * 60


def _wait_s() -> int:
    return get_settings().call_mistake_fix_wait_minutes * 60


async def _record(incident: Incident, fix: MistakeFix, **kwargs: object) -> None:
    async with untenanted_session() as session:
        await ledger.record(
            session,
            playbook=PLAYBOOK,
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            agent_id=incident.agent_id,
            alarm_code=incident.trigger_code,
            attempt=fix.attempts,
            **kwargs,  # type: ignore[arg-type]
        )


async def _advance(
    incident: Incident,
    *,
    state: incidents.State,
    next_in_s: int | None,
    outcome: str,
    attempted: bool = False,
) -> None:
    async with untenanted_session() as session:
        await incidents.advance(
            session,
            incident,
            state=state,
            next_in_s=next_in_s,
            outcome=outcome,
            attempted=attempted,
        )


async def _set_fix(session: AsyncSession, fix: MistakeFix, sets: str, **values: object) -> bool:
    """`UPDATE agent_mistake_fixes SET <sets>` as a CAS on the state the step read."""
    result = await session.execute(
        text(
            f"UPDATE agent_mistake_fixes SET {sets}, updated_at = now() "
            "WHERE id = :fix_id AND state = :fix_was"
        ),
        {"fix_id": fix.id, "fix_was": fix.state, **values},
    )
    return bool(getattr(result, "rowcount", 0))


async def _client_notice(
    session: AsyncSession, incident: Incident, kind: str, *, must_act: bool
) -> None:
    """The owner's notice for this fix (`healer/notices`), told again whenever it changes
    kind. Dashboard only unless they must act (the allowance)."""
    await session.execute(
        text(
            "INSERT INTO heal_client_incidents (id, tenant_id, incident_id, agent_id, kind, "
            "protection, state, must_act, opened_at, created_at, updated_at) VALUES (:id, "
            ":tid, :iid, :aid, :kind, 'none', 'open', :act, now(), now(), now()) "
            "ON CONFLICT (incident_id, tenant_id, agent_id) DO UPDATE SET kind = EXCLUDED.kind, "
            "must_act = EXCLUDED.must_act, state = 'open', resolved_at = NULL, "
            "notified_at = CASE WHEN heal_client_incidents.kind = EXCLUDED.kind "
            "THEN heal_client_incidents.notified_at END, "
            "notified_by = CASE WHEN heal_client_incidents.kind = EXCLUDED.kind "
            "THEN heal_client_incidents.notified_by END, "
            "restored_notified_at = NULL, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": incident.tenant_id,
            "iid": incident.id,
            "aid": incident.agent_id,
            "kind": kind,
            "act": must_act,
        },
    )


async def _close_client_notice(session: AsyncSession, incident: Incident) -> None:
    await session.execute(
        text(
            "UPDATE heal_client_incidents SET state = 'resolved', resolved_at = now(), "
            "must_act = false, updated_at = now() WHERE incident_id = :iid AND state = 'open'"
        ),
        {"iid": incident.id},
    )


async def _needs_person(incident: Incident, fix: MistakeFix, *, ended: str, why: str) -> None:
    """Hand the fix to our team: settled `needs_person`, the incident escalated."""
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(
            session,
            fix,
            "state = 'needs_person', settled_at = now(), ended_because = :ended, "
            "proposal_id = NULL",
            ended=ended,
        )
        await _close_client_notice(session, incident)
    alert(
        "WORKER_TERMINAL",
        NEEDS_PERSON,
        detail=f"{fix.kind}: {why}",
        incident_id=str(incident.id),
        tenant_id=str(fix.tenant_id),
        agent_id=str(fix.agent_id),
        reason=fix.kind,
        episode=f"{fix.agent_id}:{fix.kind}",
    )
    await _record(incident, fix, step="escalate", outcome="ok", detail=f"{ended}: {why}")
    await _advance(
        incident,
        state="escalated",
        next_in_s=get_settings().call_mistake_fix_wait_minutes * 60,
        outcome="escalated",
    )


async def _no_job(incident: Incident, fix: MistakeFix, *, why: str) -> None:
    """The call had no script of its own to fix (D-1005): settled and closed, nobody paged.
    The owner's Training tab says so; the next call showing the kind looks again."""
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(
            session,
            fix,
            "state = 'needs_person', settled_at = now(), ended_because = 'no_job', "
            "proposal_id = NULL",
        )
        await _close_client_notice(session, incident)
    await _record(incident, fix, step="act", outcome="skipped", detail=f"no_job: {why}")
    await _advance(incident, state="resolved", next_in_s=None, outcome="no_job")


async def _wait(incident: Incident, fix: MistakeFix, *, why: str) -> None:
    settings = get_settings()
    if fix.waits + 1 >= settings.call_mistake_fix_max_waits:
        await _needs_person(
            incident,
            fix,
            ended="waited_too_long",
            why=f"waited {fix.waits + 1} times ({why}) without a chance to fix the script",
        )
        return
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(session, fix, "waits = waits + 1")
    if fix.waits == 0 or incident.last_outcome != "waiting":
        await _record(incident, fix, step="act", outcome="skipped", detail=f"waiting: {why}")
    await _advance(incident, state=incident.state, next_in_s=_wait_s(), outcome="waiting")  # type: ignore[arg-type]


# --- act -------------------------------------------------------------------------------------


def _change_word(holder: Holder) -> str:
    return "Inbound line" if holder.kind == "inbound_line" else "campaign"


async def _target(fix: MistakeFix) -> tuple[HolderScript | None, str]:
    """The line or campaign whose script the fix is written into, or None with why not."""
    async with tenant_session(fix.tenant_id) as session:
        latest = await mistake_fixes.holder_of_latest_call(
            session, agent_id=fix.agent_id, kind=fix.kind
        )
        if latest is None:
            return None, "no_call"
        if latest.holder is None:
            return None, "the call was on no Inbound line or campaign"
        found = await mistake_fixes.read_holder(session, latest.holder)
    if found is None:
        return None, f"the call's {_change_word(latest.holder)} is archived"
    if found.script is None:
        return None, f"the call's {_change_word(latest.holder)} has no script yet"
    return found, ""


def _blocker(target: HolderScript) -> str | None:
    """What the fix must not write over, or None."""
    if target.proposal is not None and target.proposal.status in ("drafting", "ready"):
        return f"a Pip draft is open on the {_change_word(target.holder)}"
    if target.script is not None and target.script.raw_override:
        return "the script is hand-written"
    return None


async def _agent_gone(session: AsyncSession, agent_id: UUID) -> bool:
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :a AND deleted_at IS NULL"),
            {"a": agent_id},
        )
    ).scalar_one_or_none()
    return status is None or status == "archived"


async def _act(incident: Incident, fix: MistakeFix) -> None:
    tenant_id = fix.tenant_id
    async with tenant_session(tenant_id) as session:
        gone = await _agent_gone(session, fix.agent_id)
    if gone:
        await _needs_person(incident, fix, ended="agent_gone", why="the agent is gone")
        return
    target, why = await _target(fix)
    if target is None and why == "no_call":
        # Opened by the sweep of agent scripts before D-1005, with no call behind it: there
        # is no line or campaign to fix it on.
        await _settle_moot(incident, fix)
        return
    if target is None:
        await _no_job(incident, fix, why=why)
        return
    await _request_repair(incident, fix, target)


async def _request_repair(incident: Incident, fix: MistakeFix, target: HolderScript) -> None:
    """Ask for the repair of the holder's lines the mistake's own check names, or settle why
    not: no line causes it (our team's), Pip off or the allowance used up (wait)."""
    tenant_id = fix.tenant_id
    assert target.script is not None
    blocker = _blocker(target)
    if blocker is not None:
        await _wait(incident, fix, why=blocker)
        return
    script = upgrade_to_v2(target.script)
    async with tenant_session(tenant_id) as session:
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=fix.agent_id)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
        pip_on = await account_content_may_reach_models(session, tenant_id=tenant_id)
    findings = mistake_findings(script, lint, fix.kind)
    paths = mistake_fixes.fix_paths(findings)
    if not paths:
        await _needs_person(
            incident,
            fix,
            ended="no_script_cause",
            why=(
                "no line of the script causes it; the platform rule must change"
                if not findings
                else "only the opening or its notices cause it, which the healer never edits"
            ),
        )
        return
    if not pip_on:
        # The owner turned Pip off after this fix opened (`open_fixes` opens none while it
        # is off), so no model is asked to write it.
        await _wait(incident, fix, why="Pip is off for this account")
        return
    if quota.at_ceiling or quota.platform_paused:
        async with tenant_session(tenant_id) as session:
            await _client_notice(session, incident, WAITING_NOTICE, must_act=True)
        await _wait(incident, fix, why="the client's AI allowance is used up")
        return
    holder = target.holder
    async with tenant_session(tenant_id) as session:
        moved = await _set_fix(
            session,
            fix,
            "attempts = attempts + 1, waits = 0, inbound_line_id = :line, campaign_id = :campaign",
            line=holder.id if holder.kind == "inbound_line" else None,
            campaign=holder.id if holder.kind == "campaign" else None,
        )
        if moved:
            # In the same transaction as the fix's move, so a step that lost the race to a
            # person asks for nothing.
            await script_heal.queue_now(
                session, script_heal.holder_kind(holder.kind), holder.id, tenant_id=tenant_id
            )
    if not moved:
        await _advance(incident, state=incident.state, next_in_s=0, outcome="waiting")  # type: ignore[arg-type]
        return
    await _record(
        incident,
        fix,
        step="act",
        outcome="ok",
        detail=(
            f"repair asked for on {holder.kind} {holder.id}, {len(paths)} line(s): "
            f"{', '.join(paths)}"
        )[:400],
    )
    log.info(
        "call_mistake_fix_requested",
        extra={"holder_id": str(holder.id), "kind": fix.kind, "attempt": fix.attempts + 1},
    )
    await _advance(
        incident,
        state="mitigated",
        next_in_s=REPAIR_LOOK_S,
        outcome="fix_requested",
        attempted=True,
    )


async def _check_repair(incident: Incident, fix: MistakeFix) -> None:
    """After the repair was asked for: wait while it runs, then settle `fixed` when the
    mistake's own check no longer faults a line of the holder's script, else ask again up to
    `call_mistake_fix_max_attempts` and hand it to our team after that."""
    holder = fix.holder
    assert holder is not None
    async with tenant_session(fix.tenant_id) as session:
        running = await script_heal.pending(
            session, script_heal.holder_kind(holder.kind), holder.id
        )
        target = None if running else await mistake_fixes.read_holder(session, holder)
    if running:
        await _advance(
            incident, state="mitigated", next_in_s=REPAIR_LOOK_S, outcome="fix_requested"
        )
        return
    if target is None or target.script is None:
        await _settle_moot(incident, fix)
        return
    async with tenant_session(fix.tenant_id) as session:
        lint = await lint_context_for(session, tenant_id=fix.tenant_id, agent_id=fix.agent_id)
    left = mistake_fixes.fix_paths(mistake_findings(upgrade_to_v2(target.script), lint, fix.kind))
    if not left:
        await _repaired(incident, fix)
        return
    if fix.attempts >= get_settings().call_mistake_fix_max_attempts:
        await _needs_person(
            incident,
            fix,
            ended="attempts_spent",
            why=f"{fix.attempts} repair(s) left {len(left)} line(s): {', '.join(left)}",
        )
        return
    await _record(incident, fix, step="verify", outcome="failed", detail="lines still faulted")
    await _request_repair(incident, fix, target)


async def _repaired(incident: Incident, fix: MistakeFix) -> None:
    """The holder's script no longer causes the mistake: settled `fixed` from now, which the
    owner reads as fixed in their script, and the next calls are counted against."""
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(
            session, fix, "state = 'fixed', settled_at = now(), live_at = now(), proposal_id = NULL"
        )
        await _close_client_notice(session, incident)
    await _record(incident, fix, step="verify", outcome="ok", detail="repaired in the script")
    log.info("call_mistake_fix_repaired", extra={"agent_id": str(fix.agent_id), "kind": fix.kind})
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


async def _settle_moot(incident: Incident, fix: MistakeFix) -> None:
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(session, fix, "state = 'fixed', settled_at = now(), proposal_id = NULL")
        await _close_client_notice(session, incident)
    await _record(
        incident,
        fix,
        step="act",
        outcome="skipped",
        detail="no call showed it, so there is no line or campaign to fix it on",
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


# --- the written draft ---------------------------------------------------------------------


async def _clear_draft(session: AsyncSession, holder: Holder, proposal_id: UUID) -> None:
    await session.execute(
        text(
            f"UPDATE {holder_table(holder.kind)} SET script_proposal = NULL "
            "WHERE id = :h AND script_proposal->>'id' = :p"
        ),
        {"h": holder.id, "p": str(proposal_id)},
    )


async def _retry_or_give_up(incident: Incident, fix: MistakeFix, *, why: str) -> None:
    """A draft that is no use to the owner: cleared, then tried again from the holder's
    script, or handed on."""
    assert fix.proposal_id is not None
    async with tenant_session(fix.tenant_id) as session:
        if fix.holder is not None:
            await _clear_draft(session, fix.holder, fix.proposal_id)
        await _set_fix(session, fix, "proposal_id = NULL")
    await _record(incident, fix, step="verify", outcome="failed", detail=why)
    if fix.attempts >= get_settings().call_mistake_fix_max_attempts:
        refreshed = await _reload(fix)
        await _needs_person(
            incident,
            refreshed or fix,
            ended="attempts_spent",
            why=f"{fix.attempts} fix(es) could not be written: {why}",
        )
        return
    await _advance(incident, state="mitigated", next_in_s=0, outcome="fix_requested")


async def _reload(fix: MistakeFix) -> MistakeFix | None:
    async with tenant_session(fix.tenant_id) as session:
        if fix.incident_id is None:
            return None
        return await mistake_fixes.fix_for_incident(session, fix.incident_id)


async def _collect(incident: Incident, fix: MistakeFix) -> None:
    assert fix.proposal_id is not None
    holder = fix.holder
    if holder is None:
        # Asked for on the agent's own script before D-1005, whose suggestion is retired:
        # dropped, and asked for again where the call was spoken from.
        async with tenant_session(fix.tenant_id) as session:
            await _set_fix(session, fix, "proposal_id = NULL")
        await _advance(incident, state=incident.state, next_in_s=0, outcome="fix_requested")  # type: ignore[arg-type]
        return
    async with tenant_session(fix.tenant_id) as session:
        found = await mistake_fixes.read_holder(session, holder)
    draft = found.proposal if found is not None else None
    if draft is None or draft.id != fix.proposal_id:
        if found is None:
            await _retry_or_give_up(incident, fix, why=f"the {_change_word(holder)} is archived")
            return
        # Cleared before this step saw it written: the owner has dealt with it, so there is
        # no draft to tell them about.
        await _gone_unseen(incident, fix)
        return
    if draft.status == "drafting":
        # Asked for as a draft before the repair saved it itself; nothing writes such a draft
        # any more, so it is cleared and the lines are repaired instead.
        async with tenant_session(fix.tenant_id) as session:
            await _clear_draft(session, holder, fix.proposal_id)
            await _set_fix(session, fix, "proposal_id = NULL")
        await _advance(incident, state="mitigated", next_in_s=0, outcome="fix_requested")
        return
    if draft.status == "failed" or draft.script is None:
        await _retry_or_give_up(
            incident, fix, why=f"the draft could not be written ({draft.reason})"
        )
        return
    if draft.script == draft.base_script:
        await _retry_or_give_up(incident, fix, why="the draft changed nothing")
        return
    await _proposed(incident, fix)


async def _proposed(incident: Incident, fix: MistakeFix) -> None:
    """The draft is written: settled `proposed`, the owner told, and the incident kept open
    until they have kept or discarded it."""
    async with tenant_session(fix.tenant_id) as session:
        moved = await _set_fix(session, fix, "state = 'proposed', settled_at = now()")
        if moved:
            await _client_notice(session, incident, PROPOSED_NOTICE, must_act=False)
    if moved:
        await _record(
            incident,
            fix,
            step="verify",
            outcome="ok",
            detail=f"fix drafted on {fix.holder.kind if fix.holder else 'none'} for review",
        )
        log.info("call_mistake_fix_proposed", extra={"agent_id": str(fix.agent_id)})
    await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_proposed")


async def _gone_unseen(incident: Incident, fix: MistakeFix) -> None:
    """The fix's draft left its line or campaign (kept, discarded or replaced) before this
    step saw it written: settled as reviewed, with no "fix ready" notice for a draft that is
    no longer there."""
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(session, fix, "state = 'proposed', settled_at = now()")
        await _close_client_notice(session, incident)
    await _record(
        incident, fix, step="verify", outcome="ok", detail="the draft was gone before it was seen"
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="reviewed")


async def _await_review(incident: Incident, fix: MistakeFix) -> None:
    """Look again while the draft waits; once the owner kept or discarded it, close."""
    async with tenant_session(fix.tenant_id) as session:
        waiting = await mistake_fixes.draft_waiting(session, fix)
        if not waiting:
            await _close_client_notice(session, incident)
    if waiting:
        await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_proposed")
        return
    await _record(incident, fix, step="verify", outcome="ok", detail="the owner reviewed it")
    await _advance(incident, state="resolved", next_in_s=None, outcome="reviewed")


async def _settle_live(incident: Incident, fix: MistakeFix) -> None:
    """A fix the healer put live on the agent's own script before D-1005: no longer watched
    against the agent's script, which is no longer the owner's to change. Its Undo stays."""
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(session, fix, "state = 'fixed', settled_at = now()")
        await _close_client_notice(session, incident)
    await _record(
        incident, fix, step="verify", outcome="ok", detail="settled: no longer watched (D-1005)"
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


# --- the step ---------------------------------------------------------------------------------


async def _recheck_escalated(incident: Incident, fix: MistakeFix) -> None:
    """A fix handed to a person closes on its own once the kind has not shown on this
    agent's calls for the owner's whole window."""
    async with tenant_session(fix.tenant_id) as session:
        recent = (
            await session.execute(
                text(
                    "SELECT 1 FROM call_mistakes WHERE agent_id = :a AND kind = :k AND "
                    "call_started_at > now() - make_interval(days => :d) LIMIT 1"
                ),
                {"a": fix.agent_id, "k": fix.kind, "d": WINDOW_DAYS},
            )
        ).first()
    if recent is None:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    await _advance(incident, state="escalated", next_in_s=_wait_s(), outcome="escalated")


async def _shadow(incident: Incident, fix: MistakeFix) -> None:
    """Dry run (`playbooks.in_shadow`): write the lines the fix would have asked for and
    change nothing. The fix row goes too: left `fixing`, the owner's Training tab would say
    the script is being fixed when nothing will fix it. The next call showing the kind opens
    it again, and runs for real once the dry run ends."""
    target, why = await _target(fix)
    paths: list[str] = []
    if target is not None and target.script is not None:
        async with tenant_session(fix.tenant_id) as session:
            lint = await lint_context_for(session, tenant_id=fix.tenant_id, agent_id=fix.agent_id)
        paths = mistake_fixes.fix_paths(
            mistake_findings(upgrade_to_v2(target.script), lint, fix.kind)
        )
    async with tenant_session(fix.tenant_id) as session:
        await session.execute(
            text(
                "DELETE FROM agent_mistake_fixes WHERE id = :id AND state = 'fixing' "
                "AND proposal_id IS NULL AND attempts = 0"
            ),
            {"id": fix.id},
        )
        await _close_client_notice(session, incident)
    if target is None:
        detail = f"dry run: nothing to fix ({why})"
    elif paths:
        detail = f"dry run: would ask for {len(paths)} line(s): {', '.join(paths)}"
    else:
        detail = "dry run: no line of the script causes it; would hand it to our team"
    await _record(incident, fix, step="act", outcome="shadow", detail=detail[:400])
    await _advance(incident, state="resolved", next_in_s=None, outcome="shadow")


async def call_mistake_fix(incident: Incident) -> None:
    """One step of one fix (`_STEPS["call_mistake_fix"]`)."""
    assert incident.tenant_id is not None and incident.agent_id is not None
    async with tenant_session(incident.tenant_id) as session:
        fix = await mistake_fixes.fix_for_incident(session, incident.id)
    if fix is None:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if (
        in_shadow(PLAYBOOK)
        and incident.state == "open"
        and fix.state == "fixing"
        and fix.proposal_id is None
        and fix.attempts == 0
    ):
        await _shadow(incident, fix)
        return
    if fix.state == "proposed":
        await _await_review(incident, fix)
        return
    if incident.state == "escalated" or fix.state in ("needs_person", "rolled_back"):
        await _recheck_escalated(incident, fix)
        return
    if fix.state == "fixed":
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if fix.state == "live":
        await _settle_live(incident, fix)
        return
    if fix.proposal_id is not None:
        await _collect(incident, fix)
    elif fix.holder is not None and fix.attempts > 0:
        await _check_repair(incident, fix)
    else:
        await _act(incident, fix)


__all__ = [
    "NEEDS_PERSON",
    "PLAYBOOK",
    "PROPOSED_NOTICE",
    "REPAIR_LOOK_S",
    "call_mistake_fix",
]
