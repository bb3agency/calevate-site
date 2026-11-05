"""Read one account's stored call-quality findings again after a check was narrowed (D-970).

Queued through the outbox, one message per account, by migration `a7d3e9c1f570`. Two parts,
each its own transaction:

1. Open knowledge gaps whose stored caller line asked for nothing (`insights.service.
   recheck_open_gaps`): the Rytu Khata call of 4 Nov 2026 listed "I will try." as a
   question to answer.
2. `said_again` and `goodbye_while_asking` rows the narrowed checks no longer find
   (`agents.call_mistakes.recheck_call_mistakes`): a number read again because the caller
   asked, a goodbye after the caller signed off.

Both only remove what the current checks no longer find, so a redelivery finds nothing left.
Ids and counts are logged, never a quote (hard rule 6).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.backoff import jittered_delay_s
from sqlalchemy.exc import DBAPIError

from apps.api.agents.call_mistakes import recheck_call_mistakes
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.db.session import tenant_session
from apps.api.insights.service import recheck_open_gaps

log = get_logger(__name__)

JOB_NAME: Final = "recheck_call_quality"

#: How long before the next try after a database error (a lock timeout, a restart).
RETRY_AFTER_S: Final = 60


async def recheck_call_quality(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    try:
        async with tenant_session(tenant_id) as session:
            gaps = await recheck_open_gaps(session)
        mistakes = await recheck_call_mistakes(tenant_id)
    except (DBAPIError, OSError) as exc:
        # arq retries only `Retry`; anything else ends the job on its first try. Both parts
        # only remove rows, so a repeat is safe. The last try raises, and the outbox's
        # unconsumed sweep re-publishes the message later.
        log.warning(
            "call_quality_recheck_retry",
            extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
        )
        if job_try(ctx) < WORKER_MAX_TRIES:
            raise Retry(defer=jittered_delay_s(RETRY_AFTER_S)) from exc
        raise
    log.info(
        "call_quality_rechecked",
        extra={"tenant_id": str(tenant_id), "gap_rows": gaps, "mistake_rows": mistakes},
    )
    return "done"


__all__ = ["JOB_NAME", "recheck_call_quality"]
