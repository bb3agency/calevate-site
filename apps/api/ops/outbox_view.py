"""What the ops console needs from the outbox beyond the dead-letter depth.

`reliability.service.read_dead_letter_queue` answers "how many messages failed". Two
questions it does not answer, and the console painted green because of it:

1. **Is the queue draining at all?** A stopped worker fails nothing: every message stays
   `pending`, the dead-letter depth stays 0, and "Stuck messages 0" read healthy while
   23,844 messages waited a month. A pending message older than the longest the retry loop
   can legitimately hold one (`STALLED_AFTER`) is stuck whether or not it ever failed.
2. **Why did a job fail?** `last_error` is already redacted at the write
   (`reliability.service._stored_error`), so it may be shown; the payload never is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@dataclass(frozen=True, slots=True)
class OutboxBacklog:
    #: Pending messages older than `STALLED_AFTER`.
    stalled: int
    #: The oldest pending message's creation time, or None when nothing is pending.
    oldest_pending_at: datetime | None


async def read_outbox_backlog(session: AsyncSession) -> OutboxBacklog:
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE created_at < now() - :stalled), "
                "min(created_at) FROM outbox_messages WHERE status = 'pending'"
            ),
            {"stalled": STALLED_AFTER},
        )
    ).one()
    return OutboxBacklog(stalled=int(row[0]), oldest_pending_at=row[1])


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
    "STALLED_AFTER",
    "OutboxBacklog",
    "job_label",
    "read_dead_letter_errors",
    "read_outbox_backlog",
]
