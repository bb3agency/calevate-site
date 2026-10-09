"""The routine tick: fire every assistant routine whose slot is due (D-694 item 5).

Every minute. One UNTENANTED read finds the due routines — `copilot_routines` carries a
`FOR SELECT` policy for an untenanted session (migration `d3a7f5c19e42`), and this reads
ids and nothing else through it — then each routine is fired in ITS tenant's session by
`copilot/routines.fire_due`, which locks the row, claims the slot, queues the background
job through the outbox and advances the schedule in one transaction.

BOUNDED, NOT A FLEET WALK: the read is `LIMIT MAX_FIRES_PER_TICK`, so a tick costs one
indexed read plus at most that many short tenant sessions, however many accounts there
are. A backlog beyond the limit is fired by the next tick, a minute later.

ISOLATED PER ROUTINE. One account's lock timeout or constraint error must not stop every
routine behind it; it is logged and alarmed (`copilot_routine_fire_failed`) and the routine
stays due, so the next tick tries again — and if that is already more than
`routines.LATE_LIMIT` after its slot, the run is recorded as skipped with the reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.copilot import routines
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session

log = get_logger(__name__)

#: The ARQ name, spelled in this file for `scripts/check_job_wiring.py`.
JOB_NAME: Final = "fire_due_routines"

#: The most routines one tick fires. Each fire is one short tenant transaction.
MAX_FIRES_PER_TICK: Final = 50

_DUE_SQL: Final = (
    "SELECT id, tenant_id FROM copilot_routines WHERE enabled AND next_run_at <= :now "
    "ORDER BY next_run_at LIMIT :limit"
)


async def fire_due_routines(ctx: dict[str, Any]) -> str:
    """Fire the due routines. Returns counts for the job log; never a name or an id."""
    now = datetime.now(UTC)
    try:
        async with untenanted_session() as session:
            due = [
                (UUID(str(row[0])), UUID(str(row[1])))
                for row in (
                    await session.execute(text(_DUE_SQL), {"now": now, "limit": MAX_FIRES_PER_TICK})
                ).all()
            ]
    except Exception as failure:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=attempt * 5) from failure
        alert(
            "WORKER_TERMINAL",
            "copilot_routines_tick_failed",
            detail="the routine tick could not read which routines are due",
            error=type(failure).__name__,
        )
        raise

    counts = {"queued": 0, "skipped": 0, "not_due": 0, "failed": 0}
    for routine_id, tenant_id in due:
        try:
            async with tenant_session(tenant_id) as session:
                outcome = await routines.fire_due(session, routine_id=routine_id, now=now)
            counts[outcome] += 1
        except Exception as failure:
            counts["failed"] += 1
            log.warning(
                "copilot_routine_fire_failed",
                extra={"routine_id": str(routine_id), "error": type(failure).__name__},
            )
            alert(
                "WORKER_TERMINAL",
                "copilot_routine_fire_failed",
                detail="one routine could not be fired; it stays due and the next tick retries",
                error=type(failure).__name__,
            )
    return (
        f"queued={counts['queued']} skipped={counts['skipped']} "
        f"not_due={counts['not_due']} failed={counts['failed']}"
    )


__all__ = ["JOB_NAME", "MAX_FIRES_PER_TICK", "fire_due_routines"]
