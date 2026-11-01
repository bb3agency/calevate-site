"""Reading a saved PDF or link again (D-893 L8), queued from the API side.

The reading itself is `apps/workers/kb_read.py`. `queue_read` is its door through the
outbox, so the promise to read commits with whatever asked for it: "Read it again" on the
client's reader, and `scripts/read_saved_files.py` for the uploads saved before their words
were read. A live PDF read again is re-sent to its agents by the job (D-868).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox

READ_KB_UPLOAD_JOB: Final = "read_kb_upload"


async def queue_read(
    session: AsyncSession, *, tenant_id: UUID, source_id: UUID, force: bool
) -> None:
    """Read one saved PDF or link into its copy. `force` reads one already read or failed.

    The row says `reading` from this transaction on, so the screen that asked shows the
    reading at once and polls until the job settles it."""
    await session.execute(
        text(
            "UPDATE kb_uploads SET read_state = 'reading', read_detail = NULL, "
            "updated_at = now() WHERE source_id = :sid"
        ),
        {"sid": source_id},
    )
    await enqueue_outbox(
        session,
        job=READ_KB_UPLOAD_JOB,
        payload={"tenant_id": str(tenant_id), "source_id": str(source_id), "force": force},
    )


__all__ = [
    "READ_KB_UPLOAD_JOB",
    "queue_read",
]
