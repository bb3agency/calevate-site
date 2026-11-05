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

from apps.api.agents.call_mistakes import recheck_call_mistakes
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.insights.service import recheck_open_gaps

log = get_logger(__name__)

JOB_NAME: Final = "recheck_call_quality"


async def recheck_call_quality(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    async with tenant_session(tenant_id) as session:
        gaps = await recheck_open_gaps(session)
    mistakes = await recheck_call_mistakes(tenant_id)
    log.info(
        "call_quality_rechecked",
        extra={"tenant_id": str(tenant_id), "gap_rows": gaps, "mistake_rows": mistakes},
    )
    return "done"


__all__ = ["JOB_NAME", "recheck_call_quality"]
