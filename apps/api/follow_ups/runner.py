"""How a Follow-up run moves (D-940): start, step, wait, advance, stop.

THE SHAPE. A run is a small state machine on `follow_up_runs`, moved only by
compare-and-swap (BACKEND-PATTERNS §5):

* `waiting` with `wake_at` set: due at that instant. `drive` claims it (`waiting -> running`),
  executes the current step and moves it on.
* `waiting` with `wake_at` NULL: waiting on something outside the run, which is always a call
  step: a booked call-back (`scheduled_callbacks.source_execution_id` = `follow-up:<run>:<step>:
  <attempt>`), a placed call (`waiting_call_id`), or a lead held for the client to release.
* `done` / `stopped`: over, with `end_reason`.

NO SECOND DIAL PATH. A call step books a call-back; the call-back tick dials it through
`check_dispatch` and `dispatch_call` like every other call-back, and refusals, busy lines and
calling-hours deferrals are that code's. The new-lead first call stays inline in
`ingest.service.ingest_lead` (speed to lead), which creates its run here.

RETRIES ARE BOOKED AHEAD, as the new-lead plan always booked them (`lead_policy.book_retry`):
when attempt n is dialled, attempt n+1 is booked `retry_minutes` later and stands down when
it falls due if they answered meanwhile. The call's outcome then only decides whether the run
waits for that booked retry or leaves the step.

IDEMPOTENT ON (run, step, attempt): every step's outcome is one `follow_up_run_events` row
under a unique index, written in the same transaction as the move, so a worker retry finds
it and does not act twice. The two steps with outside effects carry their own keys: the
WhatsApp send (`follow-up:<run>:<step>` idempotency key) and the team alert (one per call and
address); an action records `started` first and is never run a second time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks.service import book as book_callback
from apps.api.compliance.platform_dnc import ENGINE_PERSON_REFUSALS
from apps.api.compliance.service import NO_CONSENT_RECORD_RULE
from apps.api.core.logging import get_logger
from apps.api.crm.outcomes import normalise
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.follow_ups import definition as d
from apps.api.ingest import lead_policy
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

#: `scheduled_callbacks.source_execution_id` of a Follow-up's call: `follow-up:<run>:<step>:
#: <attempt>[:<rebook tag>]`. Namespaced so it never collides with an engine execution id.
CALLBACK_PREFIX: Final = "follow-up:"
#: The worker job that moves one run on (`apps/workers/follow_ups.drive_follow_up_run`).
DRIVE_JOB: Final = "drive_follow_up_run"
#: The worker job the post-call pipeline queues once per finished call.
CALL_ENDED_JOB: Final = "follow_up_call_ended"
#: How many steps one `drive` takes before handing back; every path is shorter than
#: `definition.MAX_STEPS`, so this only bounds a definition the validator missed.
MAX_STEPS_PER_DRIVE: Final = d.MAX_STEPS + 1
#: A run claimed (`running`) and silent this long is treated as a worker that died mid-step.
STALE_CLAIM: Final = timedelta(minutes=5)
#: A run waiting on a call that ended this long ago without its outcome reaching the run.
ORPHAN_AFTER: Final = timedelta(hours=1)
AGAIN_WINDOW: Final = timedelta(days=30)

#: Refusals that end a run as `do_not_call`: the person is on a list or said no.
DO_NOT_CALL_RULES: Final = frozenset(
    {"dnc", "no_consent", "consent_expired", NO_CONSENT_RECORD_RULE, *ENGINE_PERSON_REFUSALS}
)

EndReason = str


def callback_key(run_id: UUID, step_id: str, attempt: int, tag: str | None = None) -> str:
    key = f"{CALLBACK_PREFIX}{run_id}:{step_id}:{attempt}"
    return f"{key}:{tag}" if tag else key


@dataclass(frozen=True, slots=True)
class CallbackRef:
    run_id: UUID
    step_id: str
    attempt: int


def parse_callback_key(key: str | None) -> CallbackRef | None:
    """The run, step and attempt a Follow-up call-back belongs to; None for any other."""
    if not key or not key.startswith(CALLBACK_PREFIX):
        return None
    parts = key.removeprefix(CALLBACK_PREFIX).split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return None
    try:
        run_id = UUID(parts[0])
    except ValueError:
        return None
    return CallbackRef(run_id, parts[1], int(parts[2]))


def end_reason_for_refusal(rule: str) -> EndReason:
    return "do_not_call" if rule in DO_NOT_CALL_RULES else f"refused:{rule}"[:64]


# --- reading -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveFollowUp:
    id: UUID
    version_id: UUID
    trigger: d.AnyTrigger
    steps: list[d.AnyStep]
    settings: d.Settings


@dataclass(frozen=True, slots=True)
class Run:
    id: UUID
    tenant_id: UUID
    follow_up_id: UUID
    version_id: UUID
    lead_id: UUID | None
    phone_e164: str
    status: str
    step_id: str
    attempt: int
    waiting_call_id: UUID | None
    last_call_id: UUID | None
    started_at: datetime


_RUN_COLUMNS: Final = (
    "r.id, r.tenant_id, r.follow_up_id, r.version_id, r.lead_id, r.phone_e164, r.status, "
    "r.step_id, r.attempt, r.waiting_call_id, r.last_call_id, r.started_at"
)


def _run(row: Any) -> Run:
    return Run(
        id=UUID(str(row[0])),
        tenant_id=UUID(str(row[1])),
        follow_up_id=UUID(str(row[2])),
        version_id=UUID(str(row[3])),
        lead_id=UUID(str(row[4])) if row[4] is not None else None,
        phone_e164=str(row[5]),
        status=str(row[6]),
        step_id=str(row[7]),
        attempt=int(row[8]),
        waiting_call_id=UUID(str(row[9])) if row[9] is not None else None,
        last_call_id=UUID(str(row[10])) if row[10] is not None else None,
        started_at=row[11],
    )


def _live(row: Any) -> LiveFollowUp:
    return LiveFollowUp(
        id=UUID(str(row[0])),
        version_id=UUID(str(row[1])),
        trigger=d.load_trigger(row[2]),
        steps=d.load_steps(row[3]),
        settings=d.load_settings(row[4]),
    )


_LIVE_SQL: Final = (
    "SELECT f.id, v.id, v.trigger, v.steps, v.settings FROM follow_ups f "
    "JOIN follow_up_versions v ON v.id = f.live_version_id WHERE f.status = 'live' "
)


async def live_follow_ups(session: AsyncSession, kind: str) -> list[LiveFollowUp]:
    """The account's live Follow-ups whose published trigger is `kind`, oldest first."""
    rows = (
        await session.execute(
            text(_LIVE_SQL + "AND v.trigger->>'kind' = :kind ORDER BY f.created_at, f.id"),
            {"kind": kind},
        )
    ).all()
    return [_live(r) for r in rows]


async def new_lead_follow_up(
    session: AsyncSession, *, source_id: UUID | None
) -> LiveFollowUp | None:
    """The live Follow-up a new lead from `source_id` starts. Publish refuses two that
    overlap (`service.publish`), so at most one matches. An account that has never had
    "Call new leads" is given it here, so no account's leads go uncalled for want of a row."""
    follow_ups = await live_follow_ups(session, "new_lead")
    if not follow_ups:
        from apps.api.db.session import session_tenant

        if await ensure_call_new_leads(session, tenant_id=await session_tenant(session)):
            follow_ups = await live_follow_ups(session, "new_lead")
    for follow_up in follow_ups:
        trigger = follow_up.trigger
        assert isinstance(trigger, d.NewLeadTrigger)
        if trigger.source_ids is None or (
            source_id is not None and source_id in trigger.source_ids
        ):
            return follow_up
    return None


#: What "Call new leads" is for an account that never had a calling plan: call at once with
#: the lead's own agent, no retries (the old `lead_policy.DEFAULT_PLAN`).
DEFAULT_NEW_LEAD_STEPS: Final = [
    {
        "id": "s1",
        "kind": "call",
        "agent_id": None,
        "wait_minutes": 0,
        "wait_seconds": 0,
        "retries": 0,
        "retry_minutes": 60,
        "next": {"answered": None, "not_reached": None},
    }
]


async def ensure_call_new_leads(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Give the account its "Call new leads" Follow-up, live, if it has never had one.
    True when this call made it. An account that turned it off keeps it off."""
    import json

    follow_up_id = uuid7()
    made = (
        await session.execute(
            text(
                "INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings, starter) "
                "VALUES (:id, :tid, 'Call new leads', 'draft', CAST(:trigger AS jsonb), "
                "CAST(:settings AS jsonb), 'call_new_leads') "
                "ON CONFLICT (tenant_id) WHERE starter = 'call_new_leads' DO NOTHING RETURNING id"
            ),
            {
                "id": follow_up_id,
                "tid": tenant_id,
                "trigger": json.dumps(d.dump_trigger(d.NewLeadTrigger(kind="new_lead"))),
                "settings": json.dumps(d.dump_settings(d.Settings())),
            },
        )
    ).first()
    if made is None:
        return False
    version_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, trigger, "
            "settings) SELECT :vid, tenant_id, id, 1, CAST(:steps AS jsonb), trigger, settings "
            "FROM follow_ups WHERE id = :fid"
        ),
        {"vid": version_id, "fid": follow_up_id, "steps": json.dumps(DEFAULT_NEW_LEAD_STEPS)},
    )
    await session.execute(
        text(
            "UPDATE follow_ups SET live_version_id = :vid, status = 'live', updated_at = now() "
            "WHERE id = :fid"
        ),
        {"vid": version_id, "fid": follow_up_id},
    )
    return True


async def version(session: AsyncSession, version_id: UUID) -> LiveFollowUp:
    row = (
        await session.execute(
            text(
                "SELECT follow_up_id, id, trigger, steps, settings FROM follow_up_versions "
                "WHERE id = :vid"
            ),
            {"vid": version_id},
        )
    ).one()
    return _live(row)


async def load_run(session: AsyncSession, run_id: UUID, *, lock: bool = False) -> Run | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM follow_up_runs r WHERE r.id = :rid"
                + (" FOR UPDATE" if lock else "")
            ),
            {"rid": run_id},
        )
    ).first()
    return _run(row) if row is not None else None


# --- events --------------------------------------------------------------------------


async def record(
    session: AsyncSession,
    run: Run,
    *,
    step_id: str,
    kind: str,
    result: str,
    attempt: int = 0,
    call_id: UUID | None = None,
) -> bool:
    """One event. False when this (run, step, attempt, kind) was already recorded."""
    row = (
        await session.execute(
            text(
                "INSERT INTO follow_up_run_events (id, tenant_id, run_id, step_id, attempt, kind, "
                "result, call_id) VALUES (:id, :tid, :rid, :step, :attempt, :kind, :result, :cid) "
                "ON CONFLICT (run_id, step_id, attempt, kind) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": run.tenant_id,
                "rid": run.id,
                "step": step_id,
                "attempt": attempt,
                "kind": kind,
                "result": result[:64],
                "cid": call_id,
            },
        )
    ).first()
    return row is not None


async def _queue_drive(session: AsyncSession, run: Run, *, reason: str) -> None:
    """Ask a worker to move the run on, in the caller's transaction (the outbox)."""
    await enqueue_outbox_once(
        session,
        job=DRIVE_JOB,
        payload={"tenant_id": str(run.tenant_id), "run_id": str(run.id)},
        dedupe_key=f"follow-up-drive:{run.id}:{reason}",
    )


# --- starting ------------------------------------------------------------------------

StartOutcome = Literal["started", "already_in", "not_again", "not_matched"]


@dataclass(frozen=True, slots=True)
class Started:
    outcome: StartOutcome
    run: Run | None = None
    #: The run was handed to a worker: always unless `queue=False` asked to take the first
    #: step inline AND the run's turn is now.
    queued: bool = True


async def _matches_only_if(
    session: AsyncSession, only_if: d.OnlyIf | None, lead_id: UUID | None, source_id: UUID | None
) -> bool:
    if only_if is None:
        return True
    if only_if.source_ids is not None and (
        source_id is None or source_id not in only_if.source_ids
    ):
        return False
    if only_if.lead_status is None and only_if.field is None:
        return True
    if lead_id is None:
        return False
    row = (
        await session.execute(
            text("SELECT status, data FROM leads WHERE id = :lid AND deleted_at IS NULL"),
            {"lid": lead_id},
        )
    ).first()
    if row is None:
        return False
    if only_if.lead_status is not None and str(row[0]) not in only_if.lead_status:
        return False
    if only_if.field is not None:
        data = row[1] if isinstance(row[1], dict) else {}
        value = data.get(only_if.field.key)
        if value is None or str(value).strip().lower() != only_if.field.equals.strip().lower():
            return False
    return True


async def _again_refused(
    session: AsyncSession, follow_up_id: UUID, lead_id: UUID | None, again: str
) -> bool:
    if lead_id is None or again == "after_last":
        return False
    since = "" if again == "never" else "AND (ended_at IS NULL OR ended_at > :since)"
    found = (
        await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM follow_up_runs WHERE follow_up_id = :fid "
                f"AND lead_id = :lid {since})"
            ),
            {"fid": follow_up_id, "lid": lead_id, "since": datetime.now(UTC) - AGAIN_WINDOW},
        )
    ).scalar()
    return bool(found)


async def _turn(
    session: AsyncSession, follow_up_id: UUID, cap: int | None, now: datetime
) -> datetime:
    """When a new run may take its first step under `starts_per_hour`.

    A run's `started_at` is its turn, so runs still waiting for theirs count against the
    hour they will start in: the cap-th latest turn plus an hour is the next free slot.
    Counting only `now` would give every lead past the cap the same slot an hour out."""
    if cap is None:
        return now
    starts = (
        (
            await session.execute(
                text(
                    "SELECT started_at FROM follow_up_runs WHERE follow_up_id = :fid "
                    "AND started_at > :since ORDER BY started_at DESC LIMIT :cap"
                ),
                {"fid": follow_up_id, "since": now - timedelta(hours=1), "cap": cap},
            )
        )
        .scalars()
        .all()
    )
    if len(starts) < cap:
        return now
    earliest: datetime = min(starts)
    return max(now, earliest + timedelta(hours=1))


async def start_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    follow_up: LiveFollowUp,
    lead_id: UUID | None,
    phone_e164: str,
    trigger_ref: str,
    source_id: UUID | None = None,
    started_call_id: UUID | None = None,
    queue: bool = True,
    now: datetime | None = None,
) -> Started:
    """Put a lead into a Follow-up's live version, at its first step.

    `queue=False` is the inline new-lead path, which takes the first call itself; every
    other start is due now (or at its turn under `starts_per_hour`) and queued for a worker.
    A capped run whose turn is later is queued even under `queue=False` (`Started.queued`),
    so the inline call never jumps the cap.
    """
    moment = now or datetime.now(UTC)
    first = d.first_step(follow_up.steps)
    if first is None or not await _matches_only_if(
        session, follow_up.trigger.only_if, lead_id, source_id
    ):
        return Started("not_matched")
    if await _again_refused(session, follow_up.id, lead_id, follow_up.settings.again):
        return Started("not_again")
    wake_at = await _turn(session, follow_up.id, follow_up.settings.starts_per_hour, moment)
    queue = queue or wake_at > moment
    row = (
        await session.execute(
            text(
                "INSERT INTO follow_up_runs (id, tenant_id, follow_up_id, version_id, lead_id, "
                "phone_e164, status, step_id, wake_at, last_call_id, attempt, trigger_ref, "
                "started_at) VALUES (:id, :tid, :fid, :vid, :lid, :phone, 'waiting', :step, "
                ":wake, :call, 0, :ref, :now) ON CONFLICT DO NOTHING "
                f"RETURNING {_RUN_COLUMNS.replace('r.', '')}"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "fid": follow_up.id,
                "vid": follow_up.version_id,
                "lid": lead_id,
                "phone": phone_e164,
                "step": first.id,
                "wake": None if not queue else wake_at,
                "call": started_call_id,
                "ref": trigger_ref[:200],
                "now": wake_at,
            },
        )
    ).first()
    if row is None:
        return Started("already_in")
    run = _run(row)
    await record(session, run, step_id=first.id, kind="start", result=trigger_ref.split(":")[0])
    if queue:
        await _queue_drive(session, run, reason="start")
    return Started("started", run, queued=queue)


# --- moving --------------------------------------------------------------------------


async def _finish(
    session: AsyncSession, run: Run, *, status: str, reason: str, goal: bool = False
) -> None:
    await session.execute(
        text(
            "UPDATE follow_up_runs SET status = :status, end_reason = :reason, ended_at = now(), "
            "wake_at = NULL, waiting_call_id = NULL, goal_reached = goal_reached OR :goal, "
            "updated_at = now() WHERE id = :rid AND status IN ('running', 'waiting')"
        ),
        {"rid": run.id, "status": status, "reason": reason[:64], "goal": goal},
    )


async def advance(
    session: AsyncSession,
    run: Run,
    steps: list[d.AnyStep],
    *,
    exit_name: str,
    goal: bool = False,
    call_id: UUID | None = None,
) -> str | None:
    """Leave the current step by `exit_name`. Returns the next step id, None when it ended.

    The next step is due at once; the caller drives it or a worker does.
    """
    step = d.step_by_id(steps, run.step_id)
    target = d.exits_of(step).get(exit_name) if step is not None else None
    if target is None:
        reason = "goal" if goal else "finished"
        await _finish(session, run, status="done", reason=reason, goal=goal)
        return None
    await session.execute(
        text(
            "UPDATE follow_up_runs SET status = 'waiting', step_id = :step, attempt = 0, "
            "wake_at = now(), waiting_call_id = NULL, "
            "last_call_id = coalesce(:call, last_call_id), goal_reached = goal_reached OR :goal, "
            "updated_at = now() WHERE id = :rid AND status IN ('running', 'waiting')"
        ),
        {"rid": run.id, "step": target, "call": call_id, "goal": goal},
    )
    return target


async def wait_on_call(
    session: AsyncSession, run_id: UUID, *, call_id: UUID | None, attempt: int | None = None
) -> None:
    """The run's call was placed (or may have been): it now waits for that call to end."""
    await session.execute(
        text(
            "UPDATE follow_up_runs SET waiting_call_id = :call, last_call_id = coalesce(:call, "
            "last_call_id), attempt = coalesce(:attempt, attempt), wake_at = NULL, "
            "updated_at = now() WHERE id = :rid AND status = 'waiting'"
        ),
        {"rid": run_id, "call": call_id, "attempt": attempt},
    )


def link_run_to_call(
    run_id: UUID, attempt: int, then: Callable[[AsyncSession, UUID], Awaitable[None]] | None = None
) -> Callable[[AsyncSession, UUID], Awaitable[None]]:
    """A `dispatch_call(on_reserved=...)` hook: the run waits on the call as soon as its row
    exists, in the transaction that inserts it, so an outcome can never arrive first."""

    async def link(session: AsyncSession, call_id: UUID) -> None:
        if then is not None:
            await then(session, call_id)
        await wait_on_call(session, run_id, call_id=call_id, attempt=attempt)

    return link


async def held_run(session: AsyncSession, *, lead_id: UUID) -> Run | None:
    """The run waiting, at its first call, for the client to release this held lead."""
    row = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM follow_up_runs r WHERE r.lead_id = :lid "
                "AND r.status = 'waiting' AND r.wake_at IS NULL AND r.waiting_call_id IS NULL "
                "AND EXISTS (SELECT 1 FROM follow_up_run_events e WHERE e.run_id = r.id "
                "AND e.step_id = r.step_id AND e.kind = 'held') "
                "ORDER BY r.started_at DESC LIMIT 1"
            ),
            {"lid": lead_id},
        )
    ).first()
    return _run(row) if row is not None else None


async def end_run(session: AsyncSession, run_id: UUID, *, reason: str) -> bool:
    """End one live run as `stopped`. True when it was live."""
    run = await load_run(session, run_id)
    if run is None or run.status not in ("running", "waiting"):
        return False
    await record(session, run, step_id=run.step_id, kind="stop", result=reason, attempt=run.attempt)
    await _finish(session, run, status="stopped", reason=reason)
    await cancel_callbacks(session, [run.id], reason=STOPPED_SENTENCE)
    return True


#: What a client reads on a call-back a Follow-up no longer needs.
STOPPED_SENTENCE: Final = "This follow-up stopped, so the call was not needed."
MOVED_ON_SENTENCE: Final = "This follow-up moved on, so this call was not needed."
PAUSED_SENTENCE: Final = "This follow-up was paused, so the call was not placed."


async def cancel_callbacks(
    session: AsyncSession, run_ids: Sequence[UUID], *, reason: str, step_id: str | None = None
) -> int:
    """Call off every booked (not yet dialling) call-back of these runs."""
    if not run_ids:
        return 0
    step_clause = "AND split_part(source_execution_id, ':', 3) = :step " if step_id else ""
    result = await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'cancelled', settled_at = now(), "
            "last_refusal_reason = :reason, next_attempt_at = NULL, updated_at = now() "
            "WHERE status = 'scheduled' AND left(source_execution_id, 10) = 'follow-up:' "
            "AND split_part(source_execution_id, ':', 2) = ANY(:runs) " + step_clause
        ),
        {"reason": reason, "runs": [str(r) for r in run_ids], "step": step_id},
    )
    return rowcount_of(result)


async def stop_runs(
    session: AsyncSession, *, where: str, params: dict[str, Any], reason: str
) -> int:
    """Stop every live run matching `where` (a clause over `r`), with one reason."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM follow_up_runs r JOIN follow_up_versions v "
                f"ON v.id = r.version_id WHERE r.status IN ('running', 'waiting') AND {where} "
                "FOR UPDATE OF r"
            ),
            params,
        )
    ).all()
    runs = [_run(r) for r in rows]
    for run in runs:
        await record(
            session, run, step_id=run.step_id, kind="stop", result=reason, attempt=run.attempt
        )
        await _finish(session, run, status="stopped", reason=reason)
    await cancel_callbacks(session, [r.id for r in runs], reason=STOPPED_SENTENCE)
    if runs:
        log.info("follow_up_runs_stopped", extra={"reason": reason, "count": len(runs)})
    return len(runs)


async def stop_for_phones(session: AsyncSession, *, phones: Sequence[str], reason: str) -> int:
    """The do-not-call list grew or a person opted out: their runs end now."""
    if not phones:
        return 0
    return await stop_runs(
        session, where="r.phone_e164 = ANY(:phones)", params={"phones": list(phones)}, reason=reason
    )


async def stop_for_reply(session: AsyncSession, *, phone_e164: str) -> int:
    """A lead wrote on WhatsApp: runs of Follow-ups that stop on a reply end."""
    return await stop_runs(
        session,
        where="r.phone_e164 = :phone AND coalesce((v.settings->>'stop_on_reply')::boolean, true)",
        params={"phone": phone_e164},
        reason="replied",
    )


async def stop_for_won_lost(
    session: AsyncSession, *, lead_id: UUID, status: str, except_run: UUID | None = None
) -> int:
    """A lead was marked won or lost: runs of Follow-ups that stop on it end, except the run
    that set it, which goes on to its next step."""
    if status not in ("won", "lost"):
        return 0
    return await stop_runs(
        session,
        where=(
            "r.lead_id = :lid AND r.id IS DISTINCT FROM :except "
            "AND coalesce((v.settings->>'stop_on_won_lost')::boolean, true)"
        ),
        params={"lid": lead_id, "except": except_run},
        reason=f"lead_{status}",
    )


# --- calls ---------------------------------------------------------------------------


async def hours_plan(session: AsyncSession) -> lead_policy.LeadCallPlan:
    """The account's calling hours, days and holidays (Leads & hours), which every Follow-up
    call keeps to; the agent, wait and retries are the step's."""
    return await lead_policy.load_plan(session)


def call_plan(
    hours: lead_policy.LeadCallPlan, step: d.CallStep, agent_id: UUID | None
) -> lead_policy.LeadCallPlan:
    return replace(
        hours,
        calling_agent_id=agent_id,
        wait_seconds=step.wait_s,
        retry_attempts=step.retries,
        retry_interval_minutes=step.retry_minutes,
    )


async def book_retry(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
    step: d.CallStep,
    lead_id: UUID | None,
    agent_id: UUID,
    phone_e164: str,
    attempt: int,
) -> datetime | None:
    """After attempt `attempt` of a call step was placed, book the next try (the plan's
    `book_retry`, keyed to the run)."""
    hours = await hours_plan(session)
    return await lead_policy.book_retry(
        session,
        tenant_id=tenant_id,
        plan=call_plan(hours, step, agent_id),
        lead_id=lead_id,
        agent_id=agent_id,
        phone_e164=phone_e164,
        attempt=attempt,
        root="",
        key=lambda n: callback_key(run_id, step.id, n),
    )


async def new_lead_call_plan(session: AsyncSession) -> lead_policy.LeadCallPlan:
    """The account's hours with the live new-lead Follow-up's first call step: what a
    new-lead call-back booked before D-940 (`lead-retry:`) retries under now."""
    hours = await hours_plan(session)
    follow_up = await new_lead_follow_up(session, source_id=None)
    first = d.first_step(follow_up.steps) if follow_up is not None else None
    if not isinstance(first, d.CallStep):
        return hours
    return call_plan(hours, first, first.agent_id)


async def book_next_try(
    session: AsyncSession,
    ref: CallbackRef,
    *,
    agent_id: UUID,
    lead_id: UUID | None,
    phone_e164: str,
) -> datetime | None:
    """A Follow-up call-back was dialled: book the step's next try, as `book_retry` does
    for the inline first call."""
    run = await load_run(session, ref.run_id)
    if run is None:
        return None
    step = d.step_by_id((await version(session, run.version_id)).steps, ref.step_id)
    if not isinstance(step, d.CallStep):
        return None
    return await book_retry(
        session,
        tenant_id=run.tenant_id,
        run_id=run.id,
        step=step,
        lead_id=lead_id,
        agent_id=agent_id,
        phone_e164=phone_e164,
        attempt=ref.attempt,
    )


async def _calling_agent(session: AsyncSession, step: d.CallStep, run: Run) -> UUID | None:
    """The step's agent if it is published, else the lead's own agent if that one is."""
    candidates: list[UUID] = [step.agent_id] if step.agent_id is not None else []
    if run.lead_id is not None:
        lead_agent = (
            await session.execute(
                text("SELECT agent_id FROM leads WHERE id = :lid"), {"lid": run.lead_id}
            )
        ).scalar()
        if lead_agent is not None:
            candidates.append(UUID(str(lead_agent)))
    for candidate in dict.fromkeys(candidates):
        ref = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL "
                    "AND archived_at IS NULL"
                ),
                {"aid": candidate},
            )
        ).scalar()
        if isinstance(ref, str) and ref:
            return candidate
    return None


async def call_answered_elsewhere(session: AsyncSession, ref: CallbackRef) -> None:
    """A booked retry stood down because the lead answered (or rang in) meanwhile: the
    call step is answered."""
    run = await load_run(session, ref.run_id, lock=True)
    if run is None or run.status != "waiting" or run.step_id != ref.step_id:
        return
    follow = await version(session, run.version_id)
    if await record(
        session, run, step_id=run.step_id, kind="call", result="answered", attempt=ref.attempt
    ):
        await advance(session, run, follow.steps, exit_name="answered")
        await _queue_drive(session, run, reason=f"{run.step_id}:answered")


CallbackVerdict = Literal["dial", "stale"]


async def callback_still_wanted(session: AsyncSession, ref: CallbackRef) -> CallbackVerdict:
    """Is the run still at this call step, in a live Follow-up? Asked when the call-back
    falls due, before the gate."""
    row = (
        await session.execute(
            text(
                "SELECT r.status, r.step_id, f.status FROM follow_up_runs r "
                "JOIN follow_ups f ON f.id = r.follow_up_id WHERE r.id = :rid"
            ),
            {"rid": ref.run_id},
        )
    ).first()
    if row is None or row[0] != "waiting" or row[1] != ref.step_id or row[2] != "live":
        return "stale"
    return "dial"


STALE_CALLBACK_REASON: Final = MOVED_ON_SENTENCE


async def call_refused(session: AsyncSession, ref: CallbackRef, *, rule: str) -> None:
    """A Follow-up call-back was refused for good (the person, or the account's trial):
    the run ends with that reason."""
    run = await load_run(session, ref.run_id, lock=True)
    if run is None or run.status not in ("running", "waiting") or run.step_id != ref.step_id:
        return
    reason = end_reason_for_refusal(rule)
    await record(
        session,
        run,
        step_id=run.step_id,
        kind="call",
        result=f"blocked:{rule}",
        attempt=ref.attempt,
    )
    await _finish(session, run, status="stopped", reason=reason)
    await cancel_callbacks(session, [run.id], reason=STOPPED_SENTENCE)


async def on_call_ended(session: AsyncSession, *, call_id: UUID) -> list[UUID]:
    """The runs this finished call moves on. Returns the ids to drive."""
    call = (
        await session.execute(text("SELECT status FROM calls WHERE id = :cid"), {"cid": call_id})
    ).first()
    if call is None:
        return []
    answered = str(call[0]) == "completed"
    rows = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS}, coalesce((SELECT max(split_part(c.source_execution_id, "
                "':', 4)::int) FROM scheduled_callbacks c WHERE c.last_call_id = :cid AND "
                "left(c.source_execution_id, 10) = 'follow-up:' AND "
                "split_part(c.source_execution_id, ':', 2) = r.id::text), r.attempt) "
                "FROM follow_up_runs r WHERE r.status = 'waiting' AND (r.waiting_call_id = :cid "
                "OR r.id::text IN (SELECT split_part(source_execution_id, ':', 2) FROM "
                "scheduled_callbacks WHERE last_call_id = :cid AND "
                "left(source_execution_id, 10) = 'follow-up:')) FOR UPDATE OF r"
            ),
            {"cid": call_id},
        )
    ).all()
    moved: list[UUID] = []
    for row in rows:
        run = _run(row)
        attempt = int(row[12])
        follow = await version(session, run.version_id)
        step = d.step_by_id(follow.steps, run.step_id)
        if not isinstance(step, d.CallStep):
            continue
        result = "answered" if answered else "no_answer"
        if not await record(
            session,
            run,
            step_id=run.step_id,
            kind="call",
            result=result,
            attempt=attempt,
            call_id=call_id,
        ):
            continue
        if answered:
            await cancel_callbacks(session, [run.id], reason=MOVED_ON_SENTENCE, step_id=step.id)
            await advance(session, run, follow.steps, exit_name="answered", call_id=call_id)
            moved.append(run.id)
            continue
        booked = (
            await session.execute(
                text(
                    "SELECT 1 FROM scheduled_callbacks WHERE status IN ('scheduled', 'dialing') "
                    "AND source_execution_id LIKE :key"
                ),
                {"key": callback_key(run.id, step.id, attempt + 1) + "%"},
            )
        ).first()
        if booked is not None:
            # The next try is already on the books (booked when this one was dialled).
            await session.execute(
                text(
                    "UPDATE follow_up_runs SET attempt = :attempt, waiting_call_id = NULL, "
                    "last_call_id = :cid, updated_at = now() WHERE id = :rid"
                ),
                {"rid": run.id, "attempt": attempt + 1, "cid": call_id},
            )
            continue
        if attempt < step.retries and await _paused(session, run.follow_up_id):
            # The pause called the booked next try off; the run keeps its tries rather than
            # leaving the step as if every try was spent. Due now, so it books that try the
            # moment the Follow-up is live again: the claim and the tick skip a paused one,
            # and `resume`'s own wake would miss it while this try's call-back still reads
            # `dialing`.
            await session.execute(
                text(
                    "UPDATE follow_up_runs SET attempt = :attempt, waiting_call_id = NULL, "
                    "wake_at = now(), last_call_id = :cid, updated_at = now() WHERE id = :rid"
                ),
                {"rid": run.id, "attempt": attempt + 1, "cid": call_id},
            )
            continue
        await advance(session, run, follow.steps, exit_name="not_reached", call_id=call_id)
        moved.append(run.id)
    return moved


async def _paused(session: AsyncSession, follow_up_id: UUID) -> bool:
    status = (
        await session.execute(
            text("SELECT status FROM follow_ups WHERE id = :fid"), {"fid": follow_up_id}
        )
    ).scalar()
    return status == "paused"


async def _book_call_step(
    session: AsyncSession, run: Run, step: d.CallStep, now: datetime
) -> StepResult:
    """Execute a call step from a worker: book its call-back through the tick."""
    agent_id = await _calling_agent(session, step, run)
    if agent_id is None:
        return StepResult.finish("refused:agent_not_published", result="blocked:agent")
    hours = await hours_plan(session)
    key = callback_key(run.id, step.id, run.attempt)
    # A step booked before and called off (a pause) books again at once under a fresh key:
    # a settled call-back is never re-opened (`callbacks.service._UPSERT`).
    rebook = await _ever_booked(session, key)
    due = lead_policy.align(hours, now if rebook else now + timedelta(seconds=step.wait_s))
    if due is None:
        return StepResult.finish("refused:closed", result="blocked:closed")
    if rebook:
        key = callback_key(run.id, step.id, run.attempt, tag=uuid7().hex[-8:])
    await book_callback(
        session,
        callback_id=uuid7(),
        tenant_id=run.tenant_id,
        agent_id=agent_id,
        source_call_id=None,
        source_execution_id=key,
        lead_id=run.lead_id,
        phone_e164=run.phone_e164,
        requested_at=due,
        booked_at=now,
        note="A follow-up call",
        language=None,
    )
    await record(
        session,
        run,
        step_id=step.id,
        kind="booked",
        result="rebooked" if rebook else "booked",
        attempt=run.attempt,
    )
    return StepResult.wait_for_call()


async def _ever_booked(session: AsyncSession, key: str) -> bool:
    found = (
        await session.execute(
            text("SELECT 1 FROM scheduled_callbacks WHERE source_execution_id LIKE :key LIMIT 1"),
            {"key": key + "%"},
        )
    ).first()
    return found is not None


# --- executing steps -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepResult:
    """What one step came to: leave by an exit, wait until an instant, wait on a call, or end."""

    kind: Literal["exit", "until", "call", "end"]
    exit_name: str | None = None
    result: str = ""
    until: datetime | None = None
    reason: str | None = None
    goal: bool = False

    @classmethod
    def go(cls, exit_name: str, result: str, *, goal: bool = False) -> StepResult:
        return cls("exit", exit_name=exit_name, result=result, goal=goal)

    @classmethod
    def wait_until(cls, until: datetime) -> StepResult:
        return cls("until", until=until, result="waiting")

    @classmethod
    def wait_for_call(cls) -> StepResult:
        return cls("call", result="booked")

    @classmethod
    def finish(cls, reason: str, *, result: str) -> StepResult:
        return cls("end", reason=reason, result=result)


async def _decide(
    session: AsyncSession, run: Run, step: d.DecideStep, goal: str | None
) -> StepResult:
    row = None
    if run.last_call_id is not None:
        row = (
            await session.execute(
                # The voice platform's own reading of the call (`calls.insights`: converted,
                # interested, callback, ...) is the third key, after the agent's business
                # outcome and our call outcome. Read through `to_jsonb(c)` so a call row
                # written before that column existed simply has none.
                text(
                    "SELECT c.business_outcome, c.outcome_tag, "
                    "to_jsonb(c)->'insights'->>'outcome' FROM calls c WHERE c.id = :cid"
                ),
                {"cid": run.last_call_id},
            )
        ).first()
    keys = [] if row is None else [k for k in (row[0], normalise(row[1]), row[2]) if k]
    chosen = next((k for k in keys if k in step.on), None)
    if chosen is None:
        return StepResult.go("other", "branch:other")
    return StepResult.go(chosen, f"branch:{chosen}", goal=goal is not None and chosen == goal)


def _ist_date(moment: datetime) -> date:
    return (moment.astimezone(UTC).replace(tzinfo=None) + IST).date()


def at_ist(day: date, clock: str) -> datetime:
    """`day` at `clock` (IST wall clock), as a UTC instant."""
    wall = datetime.combine(day, d.clock(clock))
    return (wall - IST).replace(tzinfo=UTC)


async def _lead_date(session: AsyncSession, lead_id: UUID | None, key: str) -> date | None:
    if lead_id is None:
        return None
    value = (
        await session.execute(
            text("SELECT data->>:key FROM leads WHERE id = :lid AND deleted_at IS NULL"),
            {"lid": lead_id, "key": key},
        )
    ).scalar()
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


async def _wait(session: AsyncSession, run: Run, step: d.WaitStep, now: datetime) -> StepResult:
    started = await record(session, run, step_id=step.id, kind="waiting", result="waiting")
    if not started:
        return StepResult.go("next", "waited")
    if step.until_field is not None:
        day = await _lead_date(session, run.lead_id, step.until_field)
        if day is None:
            return StepResult.go("next", "no_date")
        until = at_ist(day + timedelta(days=step.offset_days), step.at or "10:00")
        return StepResult.wait_until(until) if until > now else StepResult.go("next", "date_passed")
    minutes = (step.minutes or 0) + (step.hours or 0) * 60 + (step.days or 0) * 1440
    return StepResult.wait_until(now + timedelta(minutes=minutes))


async def _template_values(session: AsyncSession, run: Run, step: d.WhatsAppStep) -> list[str]:
    lead = (
        await session.execute(
            text(
                "SELECT l.name, l.data, a.name FROM leads l "
                "LEFT JOIN agents a ON a.id = l.agent_id "
                "WHERE l.id = :lid"
            ),
            {"lid": run.lead_id},
        )
    ).first()
    business = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :tid"), {"tid": run.tenant_id}
        )
    ).scalar()
    data = lead[1] if lead is not None and isinstance(lead[1], dict) else {}
    values: list[str] = []
    for value in step.values:
        if value.source == "lead_field":
            values.append(str(data.get(value.key or "") or ""))
        elif value.source == "lead_name":
            values.append(str(lead[0] or "") if lead is not None else "")
        elif value.source == "agent_name":
            values.append(str(lead[2] or "") if lead is not None else "")
        elif value.source == "business_name":
            values.append(str(business or ""))
        else:
            values.append(value.text or "")
    return values


async def _tell_team(session: AsyncSession, run: Run, step: d.TellTeamStep) -> StepResult:
    from apps.api.team_alerts import service as team_alerts

    if run.last_call_id is None:
        return StepResult.go("next", "not_sent:no_call")
    agent = (
        await session.execute(
            text("SELECT agent_id FROM calls WHERE id = :cid"), {"cid": run.last_call_id}
        )
    ).scalar()
    contact_id = await team_alerts.resolved_contact(
        session,
        team_alerts.Rule(contact_id=step.contact_id, on_outcomes=(), on_fields=(), in_call=False),
    )
    if agent is None or contact_id is None:
        return StepResult.go("next", "not_sent:no_address")
    queued = await team_alerts.queue_for_follow_up(
        session,
        tenant_id=run.tenant_id,
        agent_id=UUID(str(agent)),
        call_id=run.last_call_id,
        contact_id=contact_id,
        why=step.why,
        follow_up_id=run.follow_up_id,
    )
    return StepResult.go("next", "sent" if queued else "already_told")


async def _set_status(session: AsyncSession, run: Run, step: d.SetStatusStep) -> StepResult:
    from apps.api.core.errors import ProblemError
    from apps.api.crm import service as crm

    if run.lead_id is None:
        return StepResult.go("next", "skipped:no_lead")
    try:
        moved = await crm.set_lead_status(
            session,
            run.lead_id,
            status=step.status,
            actor=f"follow-up:{run.follow_up_id}",
            follow_up_run_id=run.id,
        )
    except ProblemError as refused:
        return StepResult.go("next", f"skipped:{refused.code}")
    return StepResult.go("next", f"status:{step.status}" if moved else "unchanged")


async def _assign(session: AsyncSession, run: Run, step: d.AssignStep) -> StepResult:
    from apps.api.core.errors import ProblemError
    from apps.api.crm import service as crm

    if run.lead_id is None:
        return StepResult.go("next", "skipped:no_lead")
    try:
        await crm.assert_assignable(session, step.user_id)
        changed = await crm.set_lead_assignee(
            session,
            run.lead_id,
            assignee=crm.AssigneeChange(user_id=step.user_id),
            actor=f"follow-up:{run.follow_up_id}",
        )
    except ProblemError as refused:
        return StepResult.go("next", f"skipped:{refused.code}")
    return StepResult.go("next", "assigned" if changed else "unchanged")


async def execute_in_session(
    session: AsyncSession, run: Run, step: d.AnyStep, settings: d.Settings, now: datetime
) -> StepResult:
    """Every step that touches only our database."""
    if isinstance(step, d.CallStep):
        return await _book_call_step(session, run, step, now)
    if isinstance(step, d.DecideStep):
        return await _decide(session, run, step, settings.goal)
    if isinstance(step, d.WaitStep):
        return await _wait(session, run, step, now)
    if isinstance(step, d.AssignStep):
        return await _assign(session, run, step)
    if isinstance(step, d.SetStatusStep):
        return await _set_status(session, run, step)
    if isinstance(step, d.TellTeamStep):
        return await _tell_team(session, run, step)
    assert isinstance(step, d.EndStep)
    return StepResult.finish("goal" if step.goal else "finished", result="end")


async def apply(
    session: AsyncSession,
    run: Run,
    steps: list[d.AnyStep],
    step: d.AnyStep,
    outcome: StepResult,
) -> bool:
    """Record what the step came to and move the run. True when the next step is due now."""
    if outcome.kind == "until":
        await session.execute(
            text(
                "UPDATE follow_up_runs SET status = 'waiting', wake_at = :until, "
                "updated_at = now() "
                "WHERE id = :rid AND status = 'running'"
            ),
            {"rid": run.id, "until": outcome.until},
        )
        return False
    if outcome.kind == "call":
        await session.execute(
            text(
                "UPDATE follow_up_runs SET status = 'waiting', wake_at = NULL, updated_at = now() "
                "WHERE id = :rid AND status = 'running'"
            ),
            {"rid": run.id},
        )
        return False
    await record(
        session, run, step_id=step.id, kind=step.kind, result=outcome.result, attempt=run.attempt
    )
    if outcome.kind == "end":
        is_goal = outcome.reason == "goal"
        status = "done" if outcome.reason in ("goal", "finished") else "stopped"
        await _finish(
            session, run, status=status, reason=outcome.reason or "finished", goal=is_goal
        )
        return False
    assert outcome.exit_name is not None
    return (
        await advance(session, run, steps, exit_name=outcome.exit_name, goal=outcome.goal)
        is not None
    )


# --- driving -------------------------------------------------------------------------

_CLAIM_SQL: Final = (
    "UPDATE follow_up_runs r SET status = 'running', updated_at = now() FROM follow_ups f "
    "WHERE r.id = :rid AND f.id = r.follow_up_id AND f.status = 'live' AND ("
    "(r.status = 'waiting' AND r.wake_at <= now()) "
    "OR (r.status = 'running' AND r.updated_at < now() - make_interval(secs => :stale))) "
    f"RETURNING {_RUN_COLUMNS}"
)


async def _claim(session: AsyncSession, run_id: UUID) -> Run | None:
    row = (
        await session.execute(
            text(_CLAIM_SQL), {"rid": run_id, "stale": STALE_CLAIM.total_seconds()}
        )
    ).first()
    return _run(row) if row is not None else None


def _system_principal(tenant_id: UUID) -> Any:
    from apps.api.core.context import Principal

    return Principal(realm="client", user_id=None, tenant_id=tenant_id, role="owner")


async def _send_whatsapp(run: Run, step: d.WhatsAppStep) -> StepResult:
    from apps.api.core.errors import ProblemError
    from apps.api.crm import swipe
    from apps.api.crm.lead_message import send_lead_whatsapp
    from apps.api.db.session import tenant_session

    if run.lead_id is None:
        return StepResult.go("not_sent", "not_sent:no_lead")
    async with tenant_session(run.tenant_id) as session:
        values = await _template_values(session, run, step)
        try:
            out = await send_lead_whatsapp(
                session,
                principal=_system_principal(run.tenant_id),
                lead_id=run.lead_id,
                payload=swipe.WhatsAppSendIn(template_id=step.template_id, values=values),
                idempotency_key=f"follow-up:{run.id}:{step.id}",
                audit_extra={"follow_up_id": str(run.follow_up_id), "run_id": str(run.id)},
                actor=f"follow-up:{run.follow_up_id}",
            )
        except ProblemError as refused:
            return StepResult.go("not_sent", f"not_sent:{refused.code}")
    if out.status == "sent":
        return StepResult.go("sent", "sent")
    return StepResult.go("not_sent", f"not_sent:{out.rule or out.status}")


async def _run_action(run: Run, step: d.ActionStep) -> StepResult:
    from apps.api.actions import service as actions
    from apps.api.actions.execution import CallFacts, execute_action
    from apps.api.db.session import tenant_session

    async with tenant_session(run.tenant_id) as session:
        first_try = await record(
            session, run, step_id=step.id, kind="started", result="started", attempt=run.attempt
        )
    if not first_try:
        # It may have run before a crash; an outside effect is never repeated.
        return StepResult.go("failed", "failed:unconfirmed")
    async with tenant_session(run.tenant_id) as session:
        tool = await actions.get_tool(session, tool_id=step.action_id)
        if tool is None or not tool.enabled:
            return StepResult.go("failed", "failed:action_off")
        call = None
        if run.last_call_id is not None:
            row = (
                await session.execute(
                    text(
                        "SELECT engine_call_id, direction, from_e164, to_e164 FROM calls "
                        "WHERE id = :cid"
                    ),
                    {"cid": run.last_call_id},
                )
            ).first()
            if row is not None:
                caller = row[3] if row[1] == "outbound" else row[2]
                call = CallFacts(
                    call_ref=row[0] or str(run.last_call_id),
                    caller_e164=caller,
                    direction=row[1],
                    call_id=run.last_call_id,
                )
        result = await execute_action(
            session, tool=tool, received={}, source="after_call", call=call
        )
    return (
        StepResult.go("done", "done")
        if result.ok
        else StepResult.go("failed", f"failed:{result.status}")
    )


async def drive(tenant_id: UUID, run_id: UUID) -> int:
    """Move one run on as far as it can go now. Returns the number of steps taken.

    Each step is claimed by CAS (`waiting -> running`), executed and recorded in one
    transaction; a step with an outside effect (WhatsApp, an action) runs between its claim
    and its record with no transaction open, so no connection is held across the network.
    """
    from apps.api.db.session import tenant_session

    taken = 0
    for _ in range(MAX_STEPS_PER_DRIVE):
        async with tenant_session(tenant_id) as session:
            run = await _claim(session, run_id)
            if run is None:
                return taken
            follow = await version(session, run.version_id)
            step = d.step_by_id(follow.steps, run.step_id)
            if step is None:
                await _finish(session, run, status="stopped", reason="step_missing")
                return taken
            if not isinstance(step, d.WhatsAppStep | d.ActionStep):
                outcome = await execute_in_session(
                    session, run, step, follow.settings, datetime.now(UTC)
                )
                taken += 1
                if not await apply(session, run, follow.steps, step, outcome):
                    return taken
                continue
        outcome = (
            await _send_whatsapp(run, step)
            if isinstance(step, d.WhatsAppStep)
            else await _run_action(run, step)
        )
        taken += 1
        async with tenant_session(tenant_id) as session:
            current = await load_run(session, run_id, lock=True)
            if current is None or current.status != "running" or current.step_id != step.id:
                return taken
            if not await apply(session, current, follow.steps, step, outcome):
                return taken
    log.warning("follow_up_drive_step_limit", extra={"run_id": str(run_id)})
    return taken


# --- triggers ------------------------------------------------------------------------


async def start_for_call(session: AsyncSession, *, tenant_id: UUID, call_id: UUID) -> list[UUID]:
    """`call_ended` Follow-ups this finished call starts. Test calls never start one, and
    neither does a call a Follow-up placed itself, so a journey cannot feed itself."""
    call = (
        await session.execute(
            text(
                "SELECT direction, agent_id, lead_id, from_e164, to_e164, outcome_tag, "
                "business_outcome, trial_call OR paid_test_call OR forwarding_test_id IS NOT NULL "
                "FROM calls c WHERE id = :cid AND NOT EXISTS (SELECT 1 FROM follow_up_runs r "
                "WHERE r.last_call_id = c.id OR r.waiting_call_id = c.id) AND NOT EXISTS ("
                "SELECT 1 FROM scheduled_callbacks s WHERE s.last_call_id = c.id AND "
                "left(s.source_execution_id, 10) = 'follow-up:')"
            ),
            {"cid": call_id},
        )
    ).first()
    if call is None or call[7]:
        return []
    direction = str(call[0])
    phone = call[4] if direction == "outbound" else call[3]
    if not phone:
        return []
    keys = {k for k in (normalise(call[5]), call[6]) if k}
    started: list[UUID] = []
    for follow_up in await live_follow_ups(session, "call_ended"):
        trigger = follow_up.trigger
        assert isinstance(trigger, d.CallEndedTrigger)
        if trigger.calls not in ("both", direction):
            continue
        if trigger.agent_ids is not None and (
            call[1] is None or UUID(str(call[1])) not in trigger.agent_ids
        ):
            continue
        if trigger.outcomes is not None and not keys & set(trigger.outcomes):
            continue
        result = await start_run(
            session,
            tenant_id=tenant_id,
            follow_up=follow_up,
            lead_id=UUID(str(call[2])) if call[2] is not None else None,
            phone_e164=str(phone),
            trigger_ref=f"call:{call_id}",
            started_call_id=call_id,
        )
        if result.run is not None:
            started.append(result.run.id)
    return started


#: How many leads one Follow-up starts from a date in one tick; the rest start next tick.
DATE_STARTS_PER_TICK: Final = 200


async def start_for_dates(session: AsyncSession, *, tenant_id: UUID, now: datetime) -> int:
    """`lead_date` Follow-ups whose date falls due today (IST) at or after their time:
    each lead starts once per date (`trigger_ref` = `<field>:<date>`)."""
    today = _ist_date(now)
    count = 0
    for follow_up in await live_follow_ups(session, "lead_date"):
        trigger = follow_up.trigger
        assert isinstance(trigger, d.LeadDateTrigger)
        if now < at_ist(today, trigger.at):
            continue
        target = today - timedelta(days=trigger.offset_days)
        ref = f"{trigger.field}:{target.isoformat()}"
        rows = (
            await session.execute(
                text(
                    "SELECT l.id, l.phone_e164 FROM leads l WHERE l.deleted_at IS NULL "
                    "AND left(l.data->>:field, 10) = :day AND NOT EXISTS (SELECT 1 FROM "
                    "follow_up_runs r WHERE r.follow_up_id = :fid AND r.lead_id = l.id AND "
                    "(r.trigger_ref = :ref OR r.status IN ('running', 'waiting'))) "
                    "ORDER BY l.id LIMIT :n"
                ),
                {
                    "field": trigger.field,
                    "day": target.isoformat(),
                    "fid": follow_up.id,
                    "ref": ref,
                    "n": DATE_STARTS_PER_TICK,
                },
            )
        ).all()
        for lead_id, phone in rows:
            result = await start_run(
                session,
                tenant_id=tenant_id,
                follow_up=follow_up,
                lead_id=UUID(str(lead_id)),
                phone_e164=str(phone),
                trigger_ref=ref,
                now=now,
            )
            count += result.run is not None
    return count


# --- sweeps --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Due:
    run_id: UUID
    #: Changes whenever the run is due again, so a queued job is never deduplicated against
    #: an earlier one for a different step.
    token: str


async def due_runs(session: AsyncSession, *, limit: int) -> list[Due]:
    """Runs of live Follow-ups due now, or claimed by a worker that went quiet."""
    rows = (
        await session.execute(
            text(
                "SELECT r.id, r.step_id, r.attempt, "
                "floor(extract(epoch FROM coalesce(r.wake_at, r.updated_at)))::bigint "
                "FROM follow_up_runs r JOIN follow_ups f ON f.id = r.follow_up_id "
                "WHERE f.status = 'live' AND ((r.status = 'waiting' AND r.wake_at <= now()) OR "
                "(r.status = 'running' AND r.updated_at < now() - make_interval(secs => :stale))) "
                "ORDER BY r.wake_at NULLS FIRST LIMIT :n"
            ),
            {"n": limit, "stale": STALE_CLAIM.total_seconds()},
        )
    ).all()
    return [Due(UUID(str(r[0])), f"{r[1]}:{r[2]}:{r[3]}") for r in rows]


async def end_overdue(session: AsyncSession) -> int:
    """`settings.max_days` passed: the run ends."""
    return await stop_runs(
        session,
        where=(
            "r.started_at < now() - make_interval(days => "
            "coalesce((v.settings->>'max_days')::int, CAST(:default_days AS int)))"
        ),
        params={"default_days": d.MAX_DAYS_DEFAULT},
        reason="max_days",
    )


async def settle_orphans(session: AsyncSession, *, limit: int) -> list[UUID]:
    """Runs waiting at a call step with nothing left that could move them: every call-back
    of the step is settled (missed, failed, cancelled) and no placed call is still open.
    They leave the step `not_reached`, or by the call's outcome if the call ended and its
    outcome never reached the run. Returns the runs to drive."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM follow_up_runs r "
                "JOIN follow_ups f ON f.id = r.follow_up_id "
                "WHERE f.status = 'live' AND r.status = 'waiting' AND r.wake_at IS NULL "
                "AND r.updated_at < now() - make_interval(secs => :quiet) "
                "AND NOT EXISTS (SELECT 1 FROM scheduled_callbacks c WHERE c.status IN "
                "('scheduled', 'dialing') AND left(c.source_execution_id, 10) = 'follow-up:' "
                "AND split_part(c.source_execution_id, ':', 2) = r.id::text) "
                "AND NOT EXISTS (SELECT 1 FROM lead_call_holds h WHERE h.lead_id = r.lead_id "
                "AND h.status = 'held') "
                "AND (r.waiting_call_id IS NULL OR EXISTS (SELECT 1 FROM calls k WHERE "
                "k.id = r.waiting_call_id AND k.status NOT IN ('queued', 'ringing', "
                "'in_progress') AND k.updated_at < now() - make_interval(secs => :quiet))) "
                "ORDER BY r.updated_at LIMIT :n FOR UPDATE OF r SKIP LOCKED"
            ),
            {"quiet": ORPHAN_AFTER.total_seconds(), "n": limit},
        )
    ).all()
    moved: list[UUID] = []
    for row in rows:
        run = _run(row)
        if run.waiting_call_id is not None:
            moved.extend(await on_call_ended(session, call_id=run.waiting_call_id))
            continue
        follow = await version(session, run.version_id)
        step = d.step_by_id(follow.steps, run.step_id)
        if not isinstance(step, d.CallStep):
            continue
        await record(
            session, run, step_id=step.id, kind="call", result="not_placed", attempt=run.attempt
        )
        await advance(session, run, follow.steps, exit_name="not_reached")
        moved.append(run.id)
    return moved


__all__ = [
    "CALLBACK_PREFIX",
    "CALL_ENDED_JOB",
    "DATE_STARTS_PER_TICK",
    "DO_NOT_CALL_RULES",
    "DRIVE_JOB",
    "STALE_CALLBACK_REASON",
    "CallbackRef",
    "Due",
    "LiveFollowUp",
    "Run",
    "StepResult",
    "advance",
    "apply",
    "at_ist",
    "book_next_try",
    "book_retry",
    "call_answered_elsewhere",
    "call_plan",
    "call_refused",
    "callback_key",
    "callback_still_wanted",
    "drive",
    "due_runs",
    "end_overdue",
    "end_reason_for_refusal",
    "end_run",
    "execute_in_session",
    "held_run",
    "hours_plan",
    "link_run_to_call",
    "live_follow_ups",
    "load_run",
    "new_lead_follow_up",
    "on_call_ended",
    "parse_callback_key",
    "record",
    "settle_orphans",
    "start_for_call",
    "start_for_dates",
    "start_run",
    "stop_for_phones",
    "stop_for_reply",
    "stop_for_won_lost",
    "stop_runs",
    "version",
    "wait_on_call",
]
