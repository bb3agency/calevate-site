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
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.deletion import RECORDING_FLOOR_DAYS
from apps.api.compliance.processor_erasure import (
    CALL_OUTSTANDING_SQL,
    CALL_READY_SQL,
    VOICE_PLATFORM_DELETING_ENGINES,
)
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

#: `workers/engine_customer_data.ENGINE_CONTENT_DELETE_JOB`; equal by test.
ENGINE_CONTENT_DELETE_JOB: Final = "delete_engine_call_content"

#: Calls per job: one vendor request each, so a job stays well inside the worker's timeout
#: and one failing call delays at most this many others.
CONTENT_DELETE_CHUNK: Final = 50

#: Whether the platform's copy of a call may go now without taking the only copy of a
#: recording inside the retention floor (`deletion.RECORDING_FLOOR_DAYS`): we hold the AI
#: leg's audio ourselves (its pointer, or an erasure's hold on it, since an erasure clears
#: the pointer before it queues this), the call never connected so nothing was recorded, or
#: the floor has passed. `processor_erasure.CALL_READY_SQL`, the rule the overdue alarm
#: judges a held erasure task's calls by, so the two agree.
_READY_SQL: Final = CALL_READY_SQL
_CANDIDATES_SQL: Final = (
    f"SELECT c.id, c.engine_call_id, {_READY_SQL} FROM calls c "
    "WHERE c.id = ANY(:ids) AND c.engine_call_id IS NOT NULL ORDER BY c.id"
)
_TENANT_CANDIDATES_SQL: Final = (
    f"SELECT c.id, c.engine_call_id, {_READY_SQL} FROM calls c "
    "WHERE c.tenant_id = :tid AND c.engine_call_id IS NOT NULL "
    f"AND {CALL_OUTSTANDING_SQL} ORDER BY c.id"
)
#: The same rule over a `voice_engine` task's calls (its raw vendor ids), for the contact
#: erasure: `DELETE /contacts/{id}` takes the person's recordings with it
#: (`workspace/data-and-erasure.md:21`), so it waits on exactly what a per-call deletion
#: waits on (D-810).
_TASK_CALLS_READY_SQL: Final = (
    f"SELECT c.engine_call_id, {_READY_SQL} FROM calls c "
    "WHERE split_part(c.engine_call_id, '@', 1) = ANY(:refs) ORDER BY c.id"
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
    Returns how many calls are owed; 0 on an engine that cannot delete per call.

    Calls our own former runtime ran are left out: their refs name rows in this database,
    which the caller has already reached (`processor_erasure.OWN_RUNTIME_ENGINES`).

    A call whose recording we do not hold yet, inside the floor, is marked but not sent:
    deleting the platform's copy then would destroy the only copy of a recording the floor
    says we keep (`workers/retention`: no under-floor recording is destroyed early). The
    retention sweep's backstop re-asks every marked, undeleted call a day later, so the
    deletion goes once our copy lands or the floor passes."""
    if not deletes_call_content():
        return 0
    floor = {"floor": RECORDING_FLOOR_DAYS}
    if call_ids is None:
        statement, params = _TENANT_CANDIDATES_SQL, {"tid": tenant_id, **floor}
    else:
        if not call_ids:
            return 0
        statement, params = _CANDIDATES_SQL, {"ids": list(call_ids), **floor}
    rows = (await session.execute(text(statement), params)).all()
    owed = [row for row in rows if tenant_of_pipecat_ref(str(row[1])) is None]
    if not owed:
        return 0
    await session.execute(text(_MARK_SQL), {"ids": [UUID(str(row[0])) for row in owed]})
    ready = [UUID(str(row[0])) for row in owed if row[2]]
    if len(ready) < len(owed):
        log.info(
            "engine_content_deletion_deferred",
            extra={"tenant_id": str(tenant_id), "deferred": len(owed) - len(ready)},
        )
    for start in range(0, len(ready), CONTENT_DELETE_CHUNK):
        payload = {
            "tenant_id": str(tenant_id),
            "call_ids": [str(call) for call in ready[start : start + CONTENT_DELETE_CHUNK]],
        }
        # The literal, so `scripts/check_job_wiring` reads the job name at its enqueue site.
        await enqueue_outbox(session, job="delete_engine_call_content", payload=payload)
    return len(owed)


async def calls_awaiting_our_copy(
    session: AsyncSession, *, raw_call_ids: Sequence[str], workspace: str
) -> int:
    """How many of these calls, held in `workspace`, the platform may not yet lose: a
    connected call inside the floor whose recording we do not hold. Calls in another
    workspace are not counted, since a contact erasure acts on one workspace only."""
    if not raw_call_ids:
        return 0
    rows = (
        await session.execute(
            text(_TASK_CALLS_READY_SQL),
            {"refs": list(raw_call_ids), "floor": RECORDING_FLOOR_DAYS},
        )
    ).all()
    return sum(1 for handle, ready in rows if not ready and scope_of(str(handle)) == workspace)


__all__ = [
    "CONTENT_DELETE_CHUNK",
    "ENGINE_CONTENT_DELETE_JOB",
    "calls_awaiting_our_copy",
    "deletes_call_content",
    "queue_engine_content_deletion",
]
