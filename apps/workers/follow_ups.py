"""Follow-ups' workers (D-940): the minute tick, the per-run drive and the call-ended job.

* `follow_up_tick` (every minute): one scan finds the accounts with something to do, then per
  account: queue a drive for each run that is due, start `lead_date` Follow-ups whose date
  came, and (every ten minutes) end runs past `max_days` and move runs whose call can no
  longer arrive.
* `drive_follow_up_run`: `runner.drive` for one run. A step that keeps raising ends the run
  `step_failed` after the retry ladder and raises `follow_up_step_failed`.
* `follow_up_call_ended`: queued once per finished call by the post-call pipeline. Runs
  waiting on the call move on and `call_ended` Follow-ups start. Won and lost are not read
  here: a call never sets them (the after-call rules stop at `hot`), and every move to
  them goes through `crm.set_lead_status`, which stops the runs itself. Reading the lead's
  status here would stop runs of a lead that was ALREADY won or lost, such as a win-back
  of lost leads or the run that marked its own lead won.

Ids only in every log line (hard rule 6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import ladder_delay_s
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.db.session import admin_session, tenant_session
from apps.api.follow_ups import runner

log = get_logger(__name__)

#: The job names, spelled here for `scripts/check_job_wiring` (it resolves an enqueued name
#: through the calling file's own constants).
DRIVE_JOB: Final = "drive_follow_up_run"
CALL_ENDED_JOB: Final = "follow_up_call_ended"
#: At most this many accounts and runs per account are handled per tick; the rest are next
#: minute's, oldest first.
TENANTS_PER_TICK: Final = 200
RUNS_PER_TENANT: Final = 50
#: Orphans and `max_days` are slow clocks: every tenth minute is plenty.
SLOW_SWEEP_EVERY_MIN: Final = 10
RETRY_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 120.0)
#: The second of every minute the tick fires, clear of the outbox dispatcher's tens.
TICK_SECOND: Final = 25

_SCAN_SQL: Final = (
    "SELECT scanned_tenant_id, has_due, has_dates, has_open FROM follow_up_scan(:stale) LIMIT :n"
)

assert DRIVE_JOB == runner.DRIVE_JOB and CALL_ENDED_JOB == runner.CALL_ENDED_JOB


async def _queue_drive(tenant_id: UUID, due: runner.Due) -> None:
    await enqueue(
        DRIVE_JOB,
        {"tenant_id": str(tenant_id), "run_id": str(due.run_id)},
        job_id=job_id_for(DRIVE_JOB, str(due.run_id), due.token),
    )


async def _tenant_tick(tenant_id: UUID, *, has_due: bool, has_dates: bool, slow: bool) -> int:
    now = datetime.now(UTC)
    to_drive: list[UUID] = []
    async with tenant_session(tenant_id) as session:
        if slow:
            await runner.end_overdue(session)
            to_drive.extend(await runner.settle_orphans(session, limit=RUNS_PER_TENANT))
        if has_dates:
            await runner.start_for_dates(session, tenant_id=tenant_id, now=now)
        due = await runner.due_runs(session, limit=RUNS_PER_TENANT) if has_due or slow else []
    for item in due:
        await _queue_drive(tenant_id, item)
    for run_id in to_drive:
        await _queue_drive(tenant_id, runner.Due(run_id, f"orphan:{int(now.timestamp())}"))
    return len(due) + len(to_drive)


async def follow_up_tick(ctx: dict[str, Any]) -> str:
    """The minute tick. One admin read finds the accounts with work (`follow_up_scan`,
    a per-tenant loop inside Postgres under each tenant's own policy); each is then handled
    in its own tenant session. A failing account is logged and skipped, never the tick."""
    del ctx
    now = datetime.now(UTC)
    slow = now.minute % SLOW_SWEEP_EVERY_MIN == 0
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text(_SCAN_SQL),
                {"stale": runner.STALE_CLAIM.total_seconds(), "n": TENANTS_PER_TICK},
            )
        ).all()
    queued = failed = 0
    for tenant, has_due, has_dates, has_open in rows:
        if not (has_due or has_dates or (slow and has_open)):
            continue
        try:
            queued += await _tenant_tick(
                UUID(str(tenant)),
                has_due=bool(has_due),
                has_dates=bool(has_dates),
                slow=slow and bool(has_open),
            )
        except Exception as exc:
            failed += 1
            log.warning(
                "follow_up_tick_tenant_failed",
                extra={"tenant_id": str(tenant), "error": type(exc).__name__},
            )
    log.info("follow_up_tick", extra={"tenants": len(rows), "queued": queued, "failed": failed})
    return f"queued={queued} failed={failed}"


async def drive_follow_up_run(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    attempt = int(ctx.get("job_try", 1) or 1)
    try:
        taken = await runner.drive(tenant_id, run_id)
    except Exception as exc:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=ladder_delay_s(RETRY_BACKOFF_S, attempt)) from exc
        async with tenant_session(tenant_id) as session:
            await runner.end_run(session, run_id, reason="step_failed")
        alert(
            "WORKER_TERMINAL",
            "follow_up_step_failed",
            detail=(
                f"A Follow-up run's step failed {attempt} time(s) ({type(exc).__name__}); "
                "the run was ended."
            ),
            episode=str(run_id),
            tenant_id=str(tenant_id),
            run_id=str(run_id),
        )
        return "failed"
    return f"steps={taken}"


async def follow_up_call_ended(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    async with tenant_session(tenant_id) as session:
        moved = await runner.on_call_ended(session, call_id=call_id)
        started = await runner.start_for_call(session, tenant_id=tenant_id, call_id=call_id)
    # A started run is queued by `start_run` itself, through the outbox.
    now = int(datetime.now(UTC).timestamp())
    for run_id in moved:
        await _queue_drive(tenant_id, runner.Due(run_id, f"call:{call_id}:{now}"))
    log.info(
        "follow_up_call_ended",
        extra={"call_id": str(call_id), "moved": len(moved), "started": len(started)},
    )
    return f"moved={len(moved)} started={len(started)}"


__all__ = [
    "CALL_ENDED_JOB",
    "DRIVE_JOB",
    "drive_follow_up_run",
    "follow_up_call_ended",
    "follow_up_tick",
]
