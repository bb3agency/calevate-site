"""Queue the voice platform's copy of a call's content for deletion (D-798).

The platform deletes one call's recording, transcript, summary and collected fields on
request and keeps the billing record (`thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/post-call/delete-call-content.md:443-533`). Three things owe that deletion:
the retention sweep when a call passes the tenant's recording or transcript period, a DPDP
erasure for the subject's calls, and a tenant erasure for every call.

Each marks the calls (`calls.engine_content_delete_requested_at`) and puts the job on the
outbox IN THE CALLER'S TRANSACTION, so the obligation commits with the decision that made it
owed, and no vendor round trip runs inside that transaction
(`workers/engine_customer_data.delete_engine_call_content` makes it). The mark is what keeps
the retention sweep from queueing a call twice; the backstop re-queues a call still owed a
day later.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from calevate_shared.engine import tenant_of_pipecat_ref
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.processor_erasure import VOICE_PLATFORM_DELETING_ENGINES
from apps.api.core.settings import get_settings
from apps.api.reliability.service import enqueue_outbox

#: `workers/engine_customer_data.ENGINE_CONTENT_DELETE_JOB`; equal by test.
ENGINE_CONTENT_DELETE_JOB: Final = "delete_engine_call_content"

#: Calls per job: one vendor request each, so a job stays well inside the worker's timeout
#: and one failing call delays at most this many others.
CONTENT_DELETE_CHUNK: Final = 50

_CANDIDATES_SQL: Final = (
    "SELECT id, engine_call_id FROM calls WHERE id = ANY(:ids) AND engine_call_id IS NOT NULL "
    "ORDER BY id"
)
_TENANT_CANDIDATES_SQL: Final = (
    "SELECT id, engine_call_id FROM calls WHERE tenant_id = :tid AND engine_call_id IS NOT NULL "
    "AND (engine_content_deleted_at IS NULL OR COALESCE(engine_content_recordings_pending, 0) > 0) "
    "ORDER BY id"
)
_MARK_SQL: Final = (
    "UPDATE calls SET engine_content_delete_requested_at = now(), updated_at = now() "
    "WHERE id = ANY(:ids)"
)


def deletes_call_content(engine: str | None = None) -> bool:
    """Does `engine` (this deployment's by default) delete one call's content on request?"""
    return (engine or get_settings().engine) in VOICE_PLATFORM_DELETING_ENGINES


async def queue_engine_content_deletion(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_ids: Sequence[UUID] | None,
) -> int:
    """Mark these calls (None: every call of the tenant still holding content at the
    platform) and owe their deletion through the outbox, in the caller's transaction.
    Returns how many calls were queued; 0 on an engine that cannot delete per call.

    Calls our own former runtime ran are left out: their refs name rows in this database,
    which the caller has already reached (`processor_erasure.OWN_RUNTIME_ENGINES`)."""
    if not deletes_call_content():
        return 0
    if call_ids is None:
        rows = (await session.execute(text(_TENANT_CANDIDATES_SQL), {"tid": tenant_id})).all()
    else:
        if not call_ids:
            return 0
        rows = (await session.execute(text(_CANDIDATES_SQL), {"ids": list(call_ids)})).all()
    owed = [UUID(str(row[0])) for row in rows if tenant_of_pipecat_ref(str(row[1])) is None]
    if not owed:
        return 0
    await session.execute(text(_MARK_SQL), {"ids": owed})
    for start in range(0, len(owed), CONTENT_DELETE_CHUNK):
        payload = {
            "tenant_id": str(tenant_id),
            "call_ids": [str(call) for call in owed[start : start + CONTENT_DELETE_CHUNK]],
        }
        # The literal, so `scripts/check_job_wiring` reads the job name at its enqueue site.
        await enqueue_outbox(session, job="delete_engine_call_content", payload=payload)
    return len(owed)


__all__ = [
    "CONTENT_DELETE_CHUNK",
    "ENGINE_CONTENT_DELETE_JOB",
    "deletes_call_content",
    "queue_engine_content_deletion",
]
