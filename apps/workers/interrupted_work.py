"""Ends Pip background jobs and teach-box teachings that a worker abandoned mid-run.

Both workers claim a row by moving it out of `queued` (`copilot/jobs.claim_job`,
`kb_teach.run_kb_teaching`). A redeploy cancels the attempt and arq retries it, and the
retry takes its own row back. A run that overruns `WorkerSettings.job_timeout` is
different: arq finishes it with `TimeoutError` and never retries it, so the row would stay
`running` (a job, holding one of the person's `MAX_ACTIVE_JOBS_PER_USER` slots) or
`reading`/`sorting` (a teaching the teach box shows as in progress) for ever.

FAILED, NOT RE-QUEUED. Both job types run well inside `job_timeout` by design
(`copilot/service.job_limits` stops a job first), so a row this finds is one whose run
hung on a provider or the database. Re-queuing it buys the same hang again, at the
client's AI cost, with nobody watching. A failed row says what happened and the person
starts it again with one request, which is also what they would do after any other
failure.

WHERE THE TENANTS COME FROM. Both tables are FORCE-RLS'd with no untenanted read, and a
walk over every organization costs a session per account every tick to find, almost
always, nothing. Every job and teaching is queued through the outbox with its tenant id in
the payload (`copilot/jobs.create_job`, `teach/teaching.start_teaching`), so the outbox
rows of the last `TENANT_LOOKBACK` name every account that could hold a stuck row: a run
starts minutes after its message and a stuck row is found on the next tick.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.jobs import COPILOT_JOB
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.teach.teaching import TEACH_JOB

log = get_logger(__name__)

#: The ARQ name, spelled in this file for `scripts/check_job_wiring.py`.
JOB_NAME: Final = "end_interrupted_work"

#: Minutes past the hour the sweep runs.
SWEEP_MINUTES: Final = frozenset({19, 49})

#: How long a row may sit in flight before it is called interrupted. Three times
#: `WorkerSettings.job_timeout` (300 s): no live run can still hold it, and a retry after a
#: redeploy has long since taken it back.
STALE_AFTER: Final = timedelta(minutes=15)

#: How far back the outbox is read for tenants. Far longer than the gap between a message
#: and its run, and far shorter than the outbox's 90-day prune floor.
TENANT_LOOKBACK: Final = timedelta(days=2)

#: The most accounts one tick visits; the rest are visited on the next tick.
MAX_TENANTS_PER_TICK: Final = 200

#: `copilot_jobs.error_code` and `kb_teachings.error_code` for a row ended here.
INTERRUPTED_JOB_CODE: Final = "copilot_job_interrupted"
INTERRUPTED_TEACHING_CODE: Final = "interrupted"

#: What the person reads on the job card.
INTERRUPTED_JOB_RESULT: Final = (
    "This task stopped before it finished and will not continue. "
    f"Ask {ASSISTANT_NAME} again to start it fresh."
)

#: `ORDER BY random()` so that past the ceiling no account is skipped on every tick.
_TENANTS_SQL: Final = """
SELECT tenant_id FROM (
  SELECT DISTINCT (payload->>'tenant_id')::uuid AS tenant_id
  FROM outbox_messages
  WHERE job = ANY(:jobs) AND created_at > :since
) recent
ORDER BY random()
LIMIT :limit
"""

_END_JOBS_SQL: Final = """
UPDATE copilot_jobs SET status = 'failed', result = :result, error_code = :code,
       finished_at = now(), updated_at = now()
WHERE status = 'running' AND updated_at < :cutoff
"""

_END_TEACHINGS_SQL: Final = """
UPDATE kb_teachings SET status = 'failed', error_code = :code, completed_at = now(),
       updated_at = now()
WHERE status IN ('reading', 'sorting') AND updated_at < :cutoff
"""


async def tenants_with_recent_work(now: datetime) -> list[UUID]:
    """Accounts that queued a Pip job or a teaching inside `TENANT_LOOKBACK`.

    A function so a test can drive the tick over a known list: the lane database holds
    other suites' tenants, and the per-tick ceiling could skip the one under test.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(_TENANTS_SQL),
                {
                    "jobs": [COPILOT_JOB, TEACH_JOB],
                    "since": now - TENANT_LOOKBACK,
                    "limit": MAX_TENANTS_PER_TICK,
                },
            )
        ).all()
    return [UUID(str(row[0])) for row in rows if row[0] is not None]


async def end_interrupted_work(ctx: dict[str, Any]) -> str:
    """Fail every job and teaching left in flight past `STALE_AFTER`. Returns counts."""
    del ctx
    now = datetime.now(UTC)
    cutoff = now - STALE_AFTER
    tenants = await tenants_with_recent_work(now)
    jobs_ended = teachings_ended = failed = 0
    for tenant_id in tenants:
        # One account's lock timeout must not leave every account after it stuck; the
        # failed account is tried again on the next tick.
        try:
            async with tenant_session(tenant_id) as session:
                jobs_ended += rowcount_of(
                    await session.execute(
                        text(_END_JOBS_SQL),
                        {
                            "result": INTERRUPTED_JOB_RESULT,
                            "code": INTERRUPTED_JOB_CODE,
                            "cutoff": cutoff,
                        },
                    )
                )
                teachings_ended += rowcount_of(
                    await session.execute(
                        text(_END_TEACHINGS_SQL),
                        {"code": INTERRUPTED_TEACHING_CODE, "cutoff": cutoff},
                    )
                )
        except Exception as failure:
            failed += 1
            log.warning(
                "copilot_work_interrupted_sweep_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
    if jobs_ended or teachings_ended:
        # An operator signal, not a page: each row is one person's request that a hung
        # provider or database call swallowed, and the person has been told on the row.
        log.warning(
            "copilot_work_interrupted",
            extra={"jobs": jobs_ended, "teachings": teachings_ended},
        )
    return f"tenants={len(tenants)} jobs={jobs_ended} teachings={teachings_ended} failed={failed}"


__all__ = [
    "INTERRUPTED_JOB_CODE",
    "INTERRUPTED_JOB_RESULT",
    "INTERRUPTED_TEACHING_CODE",
    "JOB_NAME",
    "STALE_AFTER",
    "SWEEP_MINUTES",
    "end_interrupted_work",
]
