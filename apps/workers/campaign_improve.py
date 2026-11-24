"""Pip's automatic Improve moves for one campaign (`campaigns/improve.run_improve`), from the
outbox after its calls end (`improve.queue_improve`): settle a decided opening test, and
narrow the calling hours when the owner has let Pip do that.

A new winning opening is saved in its own transaction, then put on the campaign's engine
agent as any script save is. A put-live refusal leaves the opening saved and is logged by
id: the campaign's next save, Start or the publish drift check brings it to the calls.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from apps.api.campaigns import improve, workspace
from apps.api.campaigns.engine_agent import put_campaign_live
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

JOB_NAME: Final = improve.IMPROVE_JOB


async def campaign_improve(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    campaign_id = UUID(str(payload["campaign_id"]))
    async with tenant_session(tenant_id) as session:
        try:
            run = await improve.run_improve(session, campaign_id)
        except ProblemError as exc:
            if exc.kind == "not_found":
                return "campaign_gone"
            raise
        holds = run.opening_applied and await workspace.holds_engine_agent(session, campaign_id)
    if holds:
        try:
            await put_campaign_live(
                tenant_id=tenant_id, campaign_id=campaign_id, require_holding=True
            )
        except ProblemError as exc:
            log.warning(
                "campaign_improve_put_live_refused",
                extra={"campaign_id": str(campaign_id), "code": exc.code},
            )
    return f"opening={run.opening_applied} hours={run.hours_applied}"


__all__ = ["JOB_NAME", "campaign_improve"]
