"""Deletes KYC files that are due to go and are still held (D-692).

Two populations, one pass:

* an owner's Aadhaar or PAN image nobody decided on within `OWNER_ID_MAX_HOLD` — the client
  abandoned the flow, or the review never happened — is deleted 30 days after upload;
* any file whose deletion was already REQUESTED and has not succeeded, whatever its age: an
  owner ID a reviewer decided on (`compliance/kyc_admin_routes.review_kyc`) or a superseded
  upload (`compliance/kyc_documents.record_document`), whose immediate delete after the
  request failed. `purged_at` is written only after the delete succeeds, so this is where a
  failed delete is retried.

Bounded per tick (`BATCH`), daily. The candidate list is read untenanted through the narrow
`kyc_documents_owner_id_purge_read` policy (held rows that are owner IDs or requested for
deletion); every write happens under the owning tenant's own session. Object first, then
the row: a crash between the two leaves a row that the next tick deletes again (a no-op)
and then marks, never a row that says "deleted" over a file that is still there.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.compliance.kyc_documents import OWNER_ID_MAX_HOLD, mark_purged
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import storage

log = get_logger(__name__)

PURGE_HOUR: Final = frozenset({4})
PURGE_MINUTE: Final = frozenset({17})
#: Files per tick. Uploads are rare and abandonment rarer; a backlog past this drains over
#: following nights rather than holding one tick open.
BATCH: Final = 500

_DUE_SQL: Final = (
    "SELECT id, tenant_id, object_key FROM kyc_documents "
    "WHERE purged_at IS NULL AND (delete_requested_at IS NOT NULL "
    "  OR (slot = 'owner_id' AND created_at < now() - :hold)) "
    "ORDER BY COALESCE(delete_requested_at, created_at) LIMIT :batch"
)


class KycPurgeIncompleteError(RuntimeError):
    """At least one due file could not be deleted; every other one was processed."""


async def purge_due_kyc_documents() -> int:
    """One pass. Returns how many files were deleted.

    One file's failure does not stop the pass; the pass then raises
    `KycPurgeIncompleteError` so the job retries and, on give-up, alarms."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(text(_DUE_SQL), {"hold": OWNER_ID_MAX_HOLD, "batch": BATCH})
        ).all()
    purged = failed = 0
    for document_id, tenant_id, object_key in rows:
        try:
            await storage.delete_objects([str(object_key)])
        except storage.StorageUnavailableError:
            log.warning("kyc_document_purge_item_failed", extra={"document_id": str(document_id)})
            failed += 1
            continue
        async with tenant_session(UUID(str(tenant_id))) as scoped:
            if await mark_purged(scoped, document_id=document_id):
                purged += 1
    if failed:
        raise KycPurgeIncompleteError(f"{failed} of {len(rows)} due KYC file(s) not deleted")
    return purged


async def sweep_abandoned_owner_ids(ctx: dict[str, Any]) -> str:
    """THE JOB. Retried on any failure; a give-up alerts, because a person's ID image held
    past its stated life is a broken promise rather than a slow one."""
    try:
        purged = await purge_due_kyc_documents()
    except Exception as exc:
        attempt = int(ctx.get("job_try", 1) or 1)
        log.warning(
            "kyc_owner_id_purge_failed",
            extra={"reason": exc.__class__.__name__, "attempt": attempt},
        )
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=60 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "kyc_owner_id_purge_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s): KYC files that are "
                "due for deletion (decided owner IDs, replaced uploads, or owner IDs past "
                "their 30-day hold) were not all deleted tonight. The sweep runs again "
                "tomorrow."
            ),
        )
        return json.dumps({"purged": 0, "failed": True})
    log.info("kyc_owner_id_purge", extra={"purged": purged})
    return json.dumps({"purged": purged})


__all__ = [
    "BATCH",
    "PURGE_HOUR",
    "PURGE_MINUTE",
    "KycPurgeIncompleteError",
    "purge_due_kyc_documents",
    "sweep_abandoned_owner_ids",
]
