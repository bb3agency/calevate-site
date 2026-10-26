"""The two jobs around a PDF's or link's read copy (D-893 L8), queued from the API side.

The reading itself is `apps/workers/kb_read.py`. These are its doors through the outbox,
so the promise to read (or to re-send) commits with whatever asked for it:

* `queue_read` — one saved PDF or link: "Read it again" on the client's reader, and
  `scripts/read_saved_files.py` for the uploads saved before their words were read.
* `queue_redelivery` — every live PDF and link of every client, re-sent after an operator
  flips `kb_send_extracted_files`, so the agents get the change without anyone publishing.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox

READ_KB_UPLOAD_JOB: Final = "read_kb_upload"
REDELIVER_EXTRACTED_KNOWLEDGE_JOB: Final = "redeliver_extracted_knowledge"


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


async def queue_redelivery(session: AsyncSession) -> None:
    """Re-send every live PDF and link to every agent, in the caller's transaction."""
    await enqueue_outbox(session, job=REDELIVER_EXTRACTED_KNOWLEDGE_JOB, payload={})


__all__ = [
    "READ_KB_UPLOAD_JOB",
    "REDELIVER_EXTRACTED_KNOWLEDGE_JOB",
    "queue_read",
    "queue_redelivery",
]
