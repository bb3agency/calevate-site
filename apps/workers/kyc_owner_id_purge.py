"""Deletes owner-ID files nobody decided on within `OWNER_ID_MAX_HOLD` (D-692).

An owner's Aadhaar or PAN image is kept only until a reviewer approves or rejects
(`compliance/kyc_admin_routes.review_kyc` deletes it then). This is the other half: a file
uploaded and never reviewed — the client abandoned the flow, or the review never happened —
is deleted 30 days after upload, and its row marked purged so the client's screen says so.

Bounded per tick (`BATCH`), daily. The candidate list is read untenanted through the narrow
`kyc_documents_owner_id_purge_read` policy (held owner-ID rows only); every write happens
under the owning tenant's own session. Object first, then the row: a crash between the two
leaves a row that the next tick deletes again (a no-op) and then marks, never a row that
says "deleted" over a file that is still there.
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

_STALE_SQL: Final = (
    "SELECT id, tenant_id, object_key FROM kyc_documents "
    "WHERE slot = 'owner_id' AND purged_at IS NULL AND created_at < now() - :hold "
    "ORDER BY created_at LIMIT :batch"
)


async def purge_stale_owner_ids() -> int:
    """One pass. Returns how many files were deleted."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(text(_STALE_SQL), {"hold": OWNER_ID_MAX_HOLD, "batch": BATCH})
        ).all()
    purged = 0
    for document_id, tenant_id, object_key in rows:
        await storage.delete_objects([str(object_key)])
        async with tenant_session(UUID(str(tenant_id))) as scoped:
            if await mark_purged(scoped, document_id=document_id):
                purged += 1
    return purged


async def sweep_abandoned_owner_ids(ctx: dict[str, Any]) -> str:
    """THE JOB. Retried on any failure; a give-up alerts, because a person's ID image held
    past its stated life is a broken promise rather than a slow one."""
    try:
        purged = await purge_stale_owner_ids()
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
                f"{exc.__class__.__name__} after {attempt} attempt(s): owner ID files past "
                "their 30-day hold were not deleted tonight. The sweep runs again tomorrow."
            ),
        )
        return json.dumps({"purged": 0, "failed": True})
    log.info("kyc_owner_id_purge", extra={"purged": purged})
    return json.dumps({"purged": purged})


__all__ = [
    "BATCH",
    "PURGE_HOUR",
    "PURGE_MINUTE",
    "purge_stale_owner_ids",
    "sweep_abandoned_owner_ids",
]
