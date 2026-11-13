"""The healer playbook `call_mistake_fix` (D-985): a real-call mistake fixed in the agent's
own script, put live, watched, and put back when it does not hold.

One step per due incident, on `run_healer`'s tick. The fix row (`agent_mistake_fixes`) is
the truth each step branches on; the incident carries the schedule, the attempt count the
ledger shows, and the escalation:

ACT      The agent's live script is read. The fix waits (`call_mistake_fix_wait_minutes`,
         at most `call_mistake_fix_max_waits` looks) while the owner has an unpublished
         change, a Pip suggestion is open, the script is hand-written, or the client's AI
         allowance is used up; it never writes over any of them. The mistake's script check
         (`mistake_lints.mistake_findings`) names the lines; none (or only the protected
         opening and notice parts) hands the kind to our team as a platform rule. Otherwise
         Pip's fix is requested for exactly those lines (`script_proposals.request_proposal`,
         `mode="change"`, `requested_by=None`), which `workers/script_proposal` writes and
         meters to the client's AI allowance like any Pip change.
VERIFY   When the suggestion is ready: the same check finds nothing on it, the whole script
         check finds nothing it did not find before, and the openings and notice records are
         unchanged. Then it goes live with a CAS on the live version read at ACT
         (`script_publish.put_draft_live`, refused if the owner autosaved meanwhile), the
         suggestion is cleared, and the owner is told. A failure discards the suggestion and
         tries again up to `call_mistake_fix_max_attempts`.
WATCH    Checked calls of the agent that started after it went live: the kind again means
         another fix from the new live script, or after the last attempt the script from
         before the first fix put back (`prompts.rollback_prompt`); more other mistakes per
         100 calls than before by `call_mistake_fix_worse_per_100_calls` (over
         `call_mistake_fix_compare_calls` calls each side) puts it back at once; enough clean
         calls (`call_mistake_fix_clean_calls`, and at least the compared calls) settle it.
         Nothing is put back once the script changed after the fix: that would throw away
         somebody else's change, so a person is asked instead.

A fix is opened by a real call showing the kind, or by the sweep of live scripts
(`check_live_scripts`, D-989) finding its cause before any call; the steps are the same.

Nothing here touches the AI or recording notices: their parts are never a fix's paths
(`mistake_fixes.PROTECTED_PARTS`), and a candidate that changed one is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript, upgrade_to_v2
from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import mistake_fixes, publishing, script_builder, script_proposals
from apps.api.agents.call_mistakes import LESSONS, WINDOW_DAYS
from apps.api.agents.capability_manifest import lint_context_for
from apps.api.agents.mistake_fixes import MistakeFix
from apps.api.agents.mistake_lints import (
    SCRIPT_FIXABLE_KINDS,
    fixable_findings,
    mistake_findings,
)
from apps.api.agents.models import MistakeFixFoundBy
from apps.api.agents.prompts import rollback_prompt
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.agents.script_publish import put_draft_live
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.healer import incidents, ledger
from apps.api.healer.incidents import Incident
from apps.api.healer.playbooks import may_run

log = get_logger(__name__)

PLAYBOOK: Final = mistake_fixes.PLAYBOOK
#: Raised when a fix needs a person: one agent's script, so `attention`, never a page.
NEEDS_PERSON: Final = "call_mistake_fix_needs_person"
#: Raised when the healer put an agent's script back after its fix did not hold.
ROLLED_BACK: Final = "call_mistake_fix_rolled_back"

#: The script parts besides the paths that a candidate must leave exactly as they were.
_UNTOUCHED: Final = (*sorted(mistake_fixes.PROTECTED_PARTS), "raw_override")


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
    """The owner's notice for this fix (`healer/notices.script_fix_notice`), told again
    whenever it changes kind. Dashboard only unless they must act (the allowance)."""
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


@dataclass(frozen=True, slots=True)
class _Agent:
    status: str
    has_draft: bool
    has_pending: bool
    proposal_open: bool


async def _agent(session: AsyncSession, agent_id: UUID) -> _Agent | None:
    row = (
        await session.execute(
            text(
                "SELECT status, script_draft IS NOT NULL, "
                "live_prompt_id IS NOT NULL AND live_prompt_id IS DISTINCT FROM system_prompt_id, "
                "script_proposal FROM agents WHERE id = :a AND deleted_at IS NULL"
            ),
            {"a": agent_id},
        )
    ).first()
    if row is None:
        return None
    pending = await script_proposals.read_proposal(session, agent_id) if row[3] else None
    return _Agent(
        status=str(row[0]),
        has_draft=bool(row[1]),
        has_pending=bool(row[2]),
        proposal_open=pending is not None and pending.status in ("drafting", "ready"),
    )


def _blocker(agent: _Agent, script: CallScript) -> str | None:
    """What the fix must not write over, or None."""
    if agent.has_draft or agent.has_pending:
        return "the owner has an unpublished change"
    if agent.proposal_open:
        return "a script suggestion is open"
    if script.raw_override:
        return "the script is hand-written"
    return None


def _change(fix: MistakeFix) -> str:
    lesson = LESSONS[fix.kind]
    if fix.found_by == "script_check":
        return (
            f"The script check found lines that make the agent do this on calls: "
            f"{lesson.label}. {lesson.instead} Change only the lines named, so it never does."
        )
    return (
        f"On real calls the agent made this mistake: {lesson.label}. {lesson.instead} "
        "Change only the lines named, so the agent stops making it."
    )


def _summary(fix: MistakeFix) -> str:
    """The version's note in the script's history."""
    label = LESSONS[fix.kind].label
    if fix.found_by == "script_check":
        return f"Fixed a line that could cause a mistake on calls: {label}"
    return f"Fixed a mistake on real calls: {label}"


def _notice_kind(fix: MistakeFix, *, waiting: bool) -> str:
    """The owner's notice (`healer/notices.script_fix_notice`): its `script_check_*` twin
    for a fix the sweep found before any call (D-989)."""
    if fix.found_by == "script_check":
        return "script_check_waiting" if waiting else "script_check_fixed"
    return "script_fix_waiting" if waiting else "script_fixed"


async def _act(incident: Incident, fix: MistakeFix) -> None:
    tenant_id, agent_id = fix.tenant_id, fix.agent_id
    async with tenant_session(tenant_id) as session:
        agent = await _agent(session, agent_id)
    if agent is None or agent.status == "archived":
        await _needs_person(incident, fix, ended="agent_gone", why="the agent is gone")
        return
    async with tenant_session(tenant_id) as session:
        # No pending change (checked below before anything is written), so the draft
        # pointer is what callers hear.
        loaded = await script_builder.load_agent_script(session, agent_id)
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent_id)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    script = upgrade_to_v2(loaded.script)
    blocker = _blocker(agent, script)
    if blocker is not None:
        await _wait(incident, fix, why=blocker)
        return
    findings = mistake_findings(script, lint, fix.kind)
    paths = mistake_fixes.fix_paths(findings)
    if not paths and fix.version_after is not None:
        # The mistake came back after a fix and the script holds no cause of it any more:
        # another attempt has nothing to change, so the fix did not hold.
        if loaded.version == fix.version_after:
            await _roll_back(
                incident,
                fix,
                ended="came_back",
                why="the mistake came back and the fixed script holds no cause of it",
            )
        else:
            await _needs_person(
                incident,
                fix,
                ended="script_changed",
                why="the mistake came back, and the script changed since, so it was not put back",
            )
        return
    if not paths and fix.found_by == "script_check":
        # Found by the sweep, and the live script changed before the fix was written: no
        # call showed the mistake and nothing causes it now, so there is nothing to fix.
        await _settle_moot(incident, fix)
        return
    if not paths:
        await _needs_person(
            incident,
            fix,
            ended="no_script_cause",
            why=(
                "no line of the agent's script causes it; the platform rule must change"
                if not findings
                else "only the opening or its notices cause it, which the healer never edits"
            ),
        )
        return
    if quota.at_ceiling or quota.platform_paused:
        async with tenant_session(tenant_id) as session:
            await _client_notice(session, incident, _notice_kind(fix, waiting=True), must_act=True)
        await _wait(incident, fix, why="the client's AI allowance is used up")
        return
    try:
        async with tenant_session(tenant_id) as session:
            proposal = await script_proposals.request_proposal(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                mode="change",
                change=_change(fix),
                answers={},
                requested_by=None,
                paths=paths,
                replace_ready=False,
                mistake_kind=fix.kind,
            )
            moved = await _set_fix(
                session,
                fix,
                "proposal_id = :pid, attempts = attempts + 1, waits = 0, "
                "version_base = :v, version_before = COALESCE(version_before, :v)",
                pid=proposal.id,
                v=loaded.version,
            )
            if not moved:
                # The fix moved under this step (an Undo, a person): drop the request too.
                raise _FixMovedError
    except ProblemError as refused:
        # Drafting or waiting: a suggestion appeared between the read and the request.
        await _wait(incident, fix, why=f"a script suggestion is open ({refused.code})")
        return
    except _FixMovedError:
        await _advance(incident, state=incident.state, next_in_s=0, outcome="waiting")  # type: ignore[arg-type]
        return
    await _record(
        incident,
        fix,
        step="act",
        outcome="ok",
        detail=f"fix asked for {len(paths)} line(s): {', '.join(paths)}"[:400],
    )
    log.info(
        "call_mistake_fix_requested",
        extra={"agent_id": str(agent_id), "kind": fix.kind, "attempt": fix.attempts + 1},
    )
    await _advance(
        incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_requested", attempted=True
    )


class _FixMovedError(Exception):
    """The fix row moved under the step."""


async def _settle_moot(incident: Incident, fix: MistakeFix) -> None:
    async with tenant_session(fix.tenant_id) as session:
        await _set_fix(session, fix, "state = 'fixed', settled_at = now(), proposal_id = NULL")
        await _close_client_notice(session, incident)
    await _record(
        incident,
        fix,
        step="act",
        outcome="skipped",
        detail="the live script no longer holds the cause the check found",
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


# --- verify and put live -----------------------------------------------------------------------


def verify_candidate(
    base: CallScript, candidate: CallScript, lint: LintContext, kind: str
) -> str | None:
    """Why `candidate` may not go live in place of `base`, or None. Static: there is no
    conversation to run against a script that is not live yet."""
    if candidate == base:
        return "the suggestion changed nothing"
    for part in _UNTOUCHED:
        if getattr(candidate, part) != getattr(base, part):
            return f"the suggestion changed {part}, which a fix never changes"
    if mistake_findings(candidate, lint, kind):
        return "the script check still finds the mistake's cause"
    before = {script_proposals.finding_key(p, base) for p in script_problems(base, lint)}
    added = [
        p
        for p in script_problems(candidate, lint)
        if script_proposals.finding_key(p, candidate) not in before
    ]
    if added:
        return f"the suggestion adds {len(added)} new script warning(s)"
    # The other kinds' own checks, which `script_problems` does not run: a fix of one
    # mistake must not write the cause of another.
    for other in sorted(SCRIPT_FIXABLE_KINDS - {kind}):
        had = {script_proposals.finding_key(p, base) for p in mistake_findings(base, lint, other)}
        if any(
            script_proposals.finding_key(p, candidate) not in had
            for p in mistake_findings(candidate, lint, other)
        ):
            return f"the suggestion adds the cause of another mistake ({other})"
    return None


async def _discard(session: AsyncSession, agent_id: UUID, proposal_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE agents SET script_proposal = NULL "
            "WHERE id = :aid AND script_proposal->>'id' = :pid"
        ),
        {"aid": agent_id, "pid": str(proposal_id)},
    )


async def _retry_or_give_up(incident: Incident, fix: MistakeFix, *, why: str) -> None:
    """A suggestion that could not go live: try again from the live script, or hand it on."""
    assert fix.proposal_id is not None
    async with tenant_session(fix.tenant_id) as session:
        await _discard(session, fix.agent_id, fix.proposal_id)
        await _set_fix(session, fix, "proposal_id = NULL")
    await _record(incident, fix, step="verify", outcome="failed", detail=why)
    if fix.attempts >= get_settings().call_mistake_fix_max_attempts:
        refreshed = await _reload(fix)
        await _needs_person(
            incident,
            refreshed or fix,
            ended="attempts_spent",
            why=f"{fix.attempts} fix(es) could not be put live: {why}",
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
    tenant_id, agent_id = fix.tenant_id, fix.agent_id
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent_id)
    if proposal is None or proposal.id != fix.proposal_id:
        await _retry_or_give_up(incident, fix, why="the suggestion was discarded or replaced")
        return
    if proposal.status == "drafting":
        await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_requested")
        return
    if proposal.status == "failed" or proposal.script is None:
        await _retry_or_give_up(
            incident, fix, why=f"the suggestion could not be written ({proposal.reason})"
        )
        return
    refused = verify_candidate(proposal.base_script, proposal.script, lint, fix.kind)
    if refused is not None:
        await _retry_or_give_up(incident, fix, why=refused)
        return
    await _put_live(incident, fix, proposal.script)


async def _put_live(incident: Incident, fix: MistakeFix, script: CallScript) -> None:
    assert fix.proposal_id is not None
    proposal_id = fix.proposal_id

    async def saved(session: AsyncSession, version: int) -> None:
        moved = await _set_fix(
            session,
            fix,
            "state = 'live', version_after = :v, live_at = now(), proposal_id = NULL",
            v=version,
        )
        if not moved:
            raise _FixMovedError
        await _discard(session, fix.agent_id, proposal_id)
        await _client_notice(session, incident, _notice_kind(fix, waiting=False), must_act=False)
        await ledger.record(
            session,
            playbook=PLAYBOOK,
            step="verify",
            outcome="ok",
            incident_id=incident.id,
            attempt=fix.attempts,
            tenant_id=fix.tenant_id,
            agent_id=fix.agent_id,
            alarm_code=incident.trigger_code,
            detail=f"fix checked and put live as version {version}",
        )

    try:
        await put_draft_live(
            tenant_id=fix.tenant_id,
            agent_id=fix.agent_id,
            summary=_summary(fix),
            created_by=None,
            script=script,
            check_version=True,
            expected_version=fix.version_base,
            on_saved=saved,
            refuse_if_draft=True,
        )
    except _FixMovedError:
        await _advance(incident, state="mitigated", next_in_s=0, outcome="fix_requested")
        return
    except ProblemError as refused:
        now = await _reload(fix)
        if now is not None and now.state == "live":
            # Saved and recorded, but the push to the calling system did not finish: the
            # watch applies it again (`_ensure_applied`).
            await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_live")
            return
        await _retry_or_give_up(incident, fix, why=f"putting it live was refused ({refused.code})")
        return
    log.info("call_mistake_fix_live", extra={"agent_id": str(fix.agent_id), "kind": fix.kind})
    await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_live")


# --- watch -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallsSince:
    """What the checked calls on each side of a fix showed."""

    after: int
    #: The fix's own kind on a call that started after it went live.
    seen_again: bool
    #: Other kinds' mistakes on the first `compared_after` calls after it, and on the last
    #: `compared_before` calls before it.
    others_after: int
    compared_after: int
    others_before: int
    compared_before: int

    def worse_by_per_100(self) -> int | None:
        """Extra other mistakes per 100 calls after the fix, or None until enough calls."""
        if self.compared_after == 0:
            return None
        after = self.others_after * 100 / self.compared_after
        before = self.others_before * 100 / self.compared_before if self.compared_before else 0
        return round(after - before)


async def calls_since(
    session: AsyncSession, *, agent_id: UUID, kind: str, live_at: datetime, compare: int
) -> CallsSince:
    """Checked calls are calls with a transcript, which the post-call checks read."""
    row = (
        await session.execute(
            text(
                "WITH checked AS (SELECT c.id, c.started_at FROM calls c WHERE c.agent_id = :a "
                "AND c.started_at IS NOT NULL AND EXISTS (SELECT 1 FROM transcript_turns t "
                "WHERE t.call_id = c.id)), "
                "after_fix AS (SELECT id FROM checked WHERE started_at > :at "
                "ORDER BY started_at LIMIT :n), "
                "before_fix AS (SELECT id FROM checked WHERE started_at <= :at "
                "ORDER BY started_at DESC LIMIT :n) "
                "SELECT (SELECT count(*) FROM checked WHERE started_at > :at), "
                "EXISTS (SELECT 1 FROM call_mistakes m WHERE m.agent_id = :a AND m.kind = :k "
                "AND m.call_started_at > :at), "
                "(SELECT count(*) FROM call_mistakes m JOIN after_fix f ON f.id = m.call_id "
                "WHERE m.kind <> :k), (SELECT count(*) FROM after_fix), "
                "(SELECT count(*) FROM call_mistakes m JOIN before_fix f ON f.id = m.call_id "
                "WHERE m.kind <> :k), (SELECT count(*) FROM before_fix)"
            ),
            {"a": agent_id, "k": kind, "at": live_at, "n": compare},
        )
    ).one()
    return CallsSince(
        after=int(row[0]),
        seen_again=bool(row[1]),
        others_after=int(row[2]),
        compared_after=int(row[3]),
        others_before=int(row[4]),
        compared_before=int(row[5]),
    )


async def _roll_back(incident: Incident, fix: MistakeFix, *, ended: str, why: str) -> None:
    """Put back the script from before the first fix, then hand it to a person."""
    assert fix.version_before is not None
    async with tenant_session(fix.tenant_id) as session:
        version = await rollback_prompt(
            session,
            tenant_id=fix.tenant_id,
            agent_id=fix.agent_id,
            version=fix.version_before,
            created_by=None,
        )
        await _set_fix(
            session,
            fix,
            "state = 'rolled_back', settled_at = now(), ended_because = :ended",
            ended=ended,
        )
        await ledger.record(
            session,
            playbook=PLAYBOOK,
            step="undo",
            outcome="ok",
            incident_id=incident.id,
            attempt=fix.attempts,
            tenant_id=fix.tenant_id,
            agent_id=fix.agent_id,
            alarm_code=incident.trigger_code,
            detail=f"{ended}: version {fix.version_before} put back as version {version}",
        )
    alert(
        "CORE_LOGIC",
        ROLLED_BACK,
        detail=f"{fix.kind}: {why}; the script from before the fix is back",
        incident_id=str(incident.id),
        tenant_id=str(fix.tenant_id),
        agent_id=str(fix.agent_id),
        reason=fix.kind,
        episode=f"{fix.agent_id}:{fix.kind}",
    )
    await _advance(incident, state="escalated", next_in_s=_wait_s(), outcome="rolled_back")


async def _watch(incident: Incident, fix: MistakeFix) -> None:
    settings = get_settings()
    assert fix.live_at is not None
    compare = settings.call_mistake_fix_compare_calls
    async with tenant_session(fix.tenant_id) as session:
        seen = await calls_since(
            session, agent_id=fix.agent_id, kind=fix.kind, live_at=fix.live_at, compare=compare
        )
        live, draft = await mistake_fixes.live_version(session, fix.agent_id)
    ours = live == fix.version_after
    if not ours and draft == fix.version_after:
        await _ensure_applied(incident, fix)
        return
    worse = seen.worse_by_per_100() if seen.compared_after >= compare else None
    too_worse = worse is not None and worse > settings.call_mistake_fix_worse_per_100_calls
    if seen.seen_again or too_worse:
        why = (
            "the mistake came back on a call after the fix"
            if seen.seen_again
            else f"other mistakes rose by {worse} per 100 calls after the fix"
        )
        if not ours:
            await _needs_person(
                incident,
                fix,
                ended="script_changed",
                why=f"{why}, and the script changed since, so it was not put back",
            )
        elif seen.seen_again and fix.attempts < settings.call_mistake_fix_max_attempts:
            async with tenant_session(fix.tenant_id) as session:
                await _set_fix(session, fix, "state = 'fixing', live_at = NULL")
            await _record(incident, fix, step="verify", outcome="failed", detail=why)
            await _advance(incident, state="mitigated", next_in_s=0, outcome="fix_requested")
        else:
            await _roll_back(
                incident, fix, ended="came_back" if seen.seen_again else "worse", why=why
            )
        return
    if seen.after >= max(settings.call_mistake_fix_clean_calls, compare):
        async with tenant_session(fix.tenant_id) as session:
            await _set_fix(session, fix, "state = 'fixed', settled_at = now()")
            await _close_client_notice(session, incident)
        await _record(
            incident,
            fix,
            step="verify",
            outcome="ok",
            detail=f"not seen on {seen.after} checked call(s) since the fix",
        )
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_live")


async def _ensure_applied(incident: Incident, fix: MistakeFix) -> None:
    """The fix is saved and is the draft, but callers do not hear it yet: apply it again."""
    try:
        await publishing.apply_to_live(
            tenant_id=fix.tenant_id, agent_id=fix.agent_id, expected_version=fix.version_after
        )
    except ProblemError as refused:
        await _record(
            incident, fix, step="act", outcome="failed", detail=f"apply refused ({refused.code})"
        )
    await _advance(incident, state="mitigated", next_in_s=_wait_s(), outcome="fix_live")


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


async def call_mistake_fix(incident: Incident) -> None:
    """One step of one fix (`_STEPS["call_mistake_fix"]`)."""
    assert incident.tenant_id is not None and incident.agent_id is not None
    async with tenant_session(incident.tenant_id) as session:
        fix = await mistake_fixes.fix_for_incident(session, incident.id)
    if fix is None:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if incident.state == "escalated" or fix.state in ("needs_person", "rolled_back"):
        await _recheck_escalated(incident, fix)
        return
    if fix.state == "fixed":
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if fix.state == "live":
        await _watch(incident, fix)
        return
    if fix.proposal_id is None:
        await _act(incident, fix)
    else:
        await _collect(incident, fix)


async def proposal_written(tenant_id: UUID, agent_id: UUID, proposal_id: UUID) -> None:
    """The fix's suggestion is stored: make its incident due now rather than at its next
    look. A no-op for a suggestion nobody's fix is waiting for."""
    async with tenant_session(tenant_id) as session:
        incident_id = (
            await session.execute(
                text(
                    "SELECT incident_id FROM agent_mistake_fixes WHERE agent_id = :a "
                    "AND proposal_id = :p AND state = 'fixing'"
                ),
                {"a": agent_id, "p": proposal_id},
            )
        ).scalar_one_or_none()
    if incident_id is not None:
        async with untenanted_session() as session:
            await incidents.retry_now(session, incident_id)


# --- the sweep of live scripts (D-989) ---------------------------------------------------------
#
# The checks above wait for a real call to show a kind. The founder's decision of 13 Nov 2026
# ("why cant we solve this problem from the start?") runs them on every live script too, so
# a caller never hears a mistake the script check could have found: each kind the check
# finds opens the same fix a call opens (`found_by = 'script_check'`), which then runs the
# steps above unchanged, caps, waits, verify, Undo, watch and rollback included.


def sweep_due(now: datetime, every_minutes: int) -> bool:
    """Whether the sweep runs on this minute: every `every_minutes` counted from midnight IST
    (D-709), so a changed console setting takes effect on the next minute with no state."""
    at = now.astimezone(IST)
    return (at.hour * 60 + at.minute) % every_minutes == 0


@dataclass(frozen=True, slots=True)
class _Checked:
    opened: tuple[str, ...]
    #: Every kind found has a fix opened or under way: the version is marked checked.
    complete: bool


async def _check_agent(due: mistake_fixes.DueCheck, *, room: int) -> _Checked:
    """One agent checked, at most `room` fixes opened, call-found ones first:

    1. each kind real calls showed in the owner's window that has never had a fix: calls
       before D-985 went live opened none, and a kind not seen since would sit at "Not fixed
       yet" for ever. Opened as a call fix (`found_by='call'`), as the pipeline would have;
    2. each kind whose cause the script check finds in the live script (`script_check`).

    The partial unique index keeps one kind to one fix whichever opens it. The version is
    marked checked only once every kind was offered a fix, so an agent cut short by the cap
    is checked again on the next sweep."""
    async with tenant_session(due.tenant_id) as session:
        if await mistake_fixes.checked_version(session, due.agent_id) == due.live_version:
            # Another sweep checked this version since the list was read.
            return _Checked(opened=(), complete=True)
        loaded = await script_builder.load_agent_script(session, due.agent_id, applied=True)
        if loaded.version is None:
            loaded = await script_builder.load_agent_script(session, due.agent_id)
        lint = await lint_context_for(session, tenant_id=due.tenant_id, agent_id=due.agent_id)
        seen = await mistake_fixes.never_fixed_kinds(
            session, agent_id=due.agent_id, kinds=LESSONS, days=WINDOW_DAYS
        )
    if loaded.version != due.live_version:
        # Put live between the list and this read: the next sweep checks the new version.
        return _Checked(opened=(), complete=False)
    script = upgrade_to_v2(loaded.script)
    found = [k for k in sorted(SCRIPT_FIXABLE_KINDS) if fixable_findings(script, lint, k)]
    work: list[tuple[str, MistakeFixFoundBy]] = [
        *((k, "call") for k in seen),
        *((k, "script_check") for k in found if k not in seen),
    ]
    opened: list[tuple[str, MistakeFixFoundBy]] = []
    complete = True
    async with tenant_session(due.tenant_id) as session:
        for kind, found_by in work:
            if len(opened) >= room:
                complete = False
                break
            made = await mistake_fixes.open_fixes(
                session,
                tenant_id=due.tenant_id,
                agent_id=due.agent_id,
                kinds=[kind],
                found_by=found_by,
            )
            opened += [(k, found_by) for k in made]
        if complete:
            await mistake_fixes.mark_checked(
                session, agent_id=due.agent_id, version=due.live_version
            )
    for kind, found_by in opened:
        ids = {"tenant_id": str(due.tenant_id), "agent_id": str(due.agent_id), "reason": kind}
        if found_by == "call":
            alert(
                "CORE_LOGIC",
                "call_mistake_seen",
                detail=(
                    f"A mistake on real calls ({kind}) that never had a fix; the healer is "
                    "checking the agent's script for the lines that cause it."
                ),
                episode=f"{due.agent_id}:{kind}",
                **ids,
            )
        else:
            alert(
                "CORE_LOGIC",
                "script_check_found",
                detail=(
                    f"The script check found the cause of a mistake ({kind}) in a live script "
                    "before any call; the healer is fixing those lines."
                ),
                episode=f"{due.agent_id}:{kind}",
                **ids,
            )
    return _Checked(opened=tuple(k for k, _by in opened), complete=complete)


async def check_live_scripts(ctx: dict[str, Any]) -> str:
    """The sweep: up to `script_check_sweep_agents` live or paused agents whose live script
    changed since it was last checked, every `script_check_sweep_minutes`, opening at most
    `script_check_sweep_max_fixes` fixes. Stopped by the healer's switches like the fix
    itself (`playbooks.may_run`). Deterministic and free: no model is called here, the fixes
    it opens are written and metered by the playbook's own steps."""
    del ctx
    settings = get_settings()
    if not sweep_due(datetime.now(UTC), settings.script_check_sweep_minutes):
        return "not_due"
    if not may_run(PLAYBOOK):
        return "paused"
    async with admin_session() as session:
        due = await mistake_fixes.checks_due(session, limit=settings.script_check_sweep_agents)
    room = settings.script_check_sweep_max_fixes
    opened = checked = 0
    for agent in due:
        try:
            done = await _check_agent(agent, room=room - opened)
        except Exception:
            # One agent's script must not stop the others; it stays unchecked, so the next
            # sweep tries it again.
            log.exception("script_check_agent_failed", extra={"agent_id": str(agent.agent_id)})
            continue
        opened += len(done.opened)
        checked += done.complete
    log.info(
        "script_check_swept",
        extra={"agents": len(due), "checked": checked, "opened": opened},
    )
    return f"checked:{checked} opened:{opened}"


__all__ = [
    "NEEDS_PERSON",
    "PLAYBOOK",
    "ROLLED_BACK",
    "CallsSince",
    "call_mistake_fix",
    "calls_since",
    "check_live_scripts",
    "proposal_written",
    "sweep_due",
    "verify_candidate",
]
