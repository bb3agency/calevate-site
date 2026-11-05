"""What the ops console needs from the outbox beyond the dead-letter depth.

`reliability.service.read_dead_letter_queue` answers "how many messages failed". Questions
it does not answer, and the console painted green or blank because of it:

1. **Is the queue draining at all?** A stopped worker fails nothing: every message stays
   `pending`, the dead-letter depth stays 0, and "Stuck messages 0" read healthy while
   23,844 messages waited a month. A pending message older than the longest the retry loop
   can legitimately hold one (`STALLED_AFTER`) is stuck whether or not it ever failed.
2. **Is a pending message held on purpose?** The dispatcher leaves a migration-queued row
   for a release that contains its `min_revision`, and a bulk job for a live bulk worker
   that runs it (D-972). Those wait for a deploy, not a resend, and the panel says which.
3. **Why did a job fail?** `last_error` is already redacted at the write
   (`reliability.service._stored_error`), so it may be shown; the payload never is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.health import image_revisions
from apps.api.core.queue import BULK_JOBS, bulk_jobs_served, get_queue
from apps.api.reliability.service import (
    OUTBOX_CLAIM_LEASE,
    OUTBOX_MAX_ATTEMPTS,
    OUTBOX_RETRY_BACKOFF_CAP_S,
)

#: The longest a healthy outbox keeps a message pending: every attempt at the capped backoff,
#: plus one claim lease. Derived from the retry loop's own constants so the two cannot drift.
STALLED_AFTER: Final = (
    timedelta(seconds=OUTBOX_MAX_ATTEMPTS * OUTBOX_RETRY_BACKOFF_CAP_S) + OUTBOX_CLAIM_LEASE
)

#: Text the two producers of a "never ran" dead letter write into `last_error`:
#: `reliability.service.sweep_unconsumed_outbox` and `workers/dispatcher.dispatch_outbox`.
#: `tests/ops_outbox_replay_test.py` holds both producers to these fragments.
NO_RUN_SUCCEEDED: Final = "no run succeeded"
EARLIER_RUN_FAILED: Final = "an earlier run of this message failed"

DeadLetterCause = Literal["never_ran", "earlier_run_failed"]


def dead_letter_cause(last_error: str | None) -> DeadLetterCause | None:
    """Why a dead letter never did its work, when its error says so; else None."""
    if last_error is None:
        return None
    if NO_RUN_SUCCEEDED in last_error:
        return "never_ran"
    if EARLIER_RUN_FAILED in last_error:
        return "earlier_run_failed"
    return None


@dataclass(frozen=True, slots=True)
class OutboxBacklog:
    #: Pending messages older than `STALLED_AFTER`.
    stalled: int
    #: The oldest pending message's creation time, or None when nothing is pending.
    oldest_pending_at: datetime | None
    #: Pending, queued by a migration this release does not contain: waits for a deploy.
    held_for_release: int
    #: Pending bulk jobs no live bulk worker runs: waits for the bulk worker.
    held_for_bulk_worker: int


async def _bulk_jobs_held() -> list[str]:
    """Bulk jobs not every live bulk worker runs, as the dispatcher decides it. An
    unreachable Redis holds them all, as the dispatcher does."""
    try:
        served = await bulk_jobs_served(await get_queue())
    except (RedisError, OSError):
        return sorted(BULK_JOBS)
    return sorted(BULK_JOBS - served)


async def read_outbox_backlog(session: AsyncSession) -> OutboxBacklog:
    revisions = sorted(await image_revisions())
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE created_at < now() - :stalled), "
                "min(created_at), "
                "count(*) FILTER (WHERE min_revision IS NOT NULL "
                "  AND NOT (min_revision = ANY(CAST(:revisions AS text[])))), "
                "count(*) FILTER (WHERE job = ANY(CAST(:bulk AS text[]))) "
                "FROM outbox_messages WHERE status = 'pending'"
            ),
            {"stalled": STALLED_AFTER, "revisions": revisions, "bulk": await _bulk_jobs_held()},
        )
    ).one()
    return OutboxBacklog(
        stalled=int(row[0]),
        oldest_pending_at=row[1],
        held_for_release=int(row[2]),
        held_for_bulk_worker=int(row[3]),
    )


async def read_dead_letter_errors(session: AsyncSession) -> dict[str, str | None]:
    """The most recent failed message's `last_error`, per job."""
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (job) job, last_error FROM outbox_messages "
                "WHERE status = 'failed' ORDER BY job, updated_at DESC"
            )
        )
    ).all()
    return {str(row[0]): (None if row[1] is None else str(row[1])) for row in rows}


def job_label(job: str) -> str:
    """A job name read as words: `sync_engine_call_lines` -> "Sync engine call lines".

    Derived rather than looked up in a table of our own: a label table would have to be
    kept in step with every job anyone registers, and a missing entry would show the raw
    name anyway.
    """
    words = job.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else job


__all__ = [
    "EARLIER_RUN_FAILED",
    "NO_RUN_SUCCEEDED",
    "STALLED_AFTER",
    "DeadLetterCause",
    "OutboxBacklog",
    "dead_letter_cause",
    "job_label",
    "read_dead_letter_errors",
    "read_outbox_backlog",
]
