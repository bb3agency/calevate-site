"""Put a job's changed "What it notes" on its calls, for writes made away from its own page.

The campaign and line pages' Save puts the job live itself (`campaigns/workspace_routes`,
`inbound/routes`). The Lead details screen's account-wide applies and an accepted suggestion
change a job's list from elsewhere, so they call this after their transaction committed: a
campaign holding its own engine agent while it runs or is paused, and a live line, are put
live again so their next call asks for the new details. Any other job reads its list at its
next Start, test call or Put it live, exactly as after its own Save.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES
from apps.api.campaigns.engine_agent import put_campaign_live
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.inbound.publish import put_line_live

log = get_logger(__name__)

JobKind = Literal["campaign", "line"]


async def holds_calls(tenant_id: UUID, kind: JobKind, job_id: UUID) -> bool:
    """Does the job have an engine agent its calls ring now, which a saved list must reach?"""
    async with tenant_session(tenant_id) as session:
        if kind == "line":
            return (await lines.read_line(session, job_id)).live
        held = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                    "FROM campaigns WHERE id = :c"
                ),
                {"c": job_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
            )
        ).scalar()
    return bool(held)


async def put_live(tenant_id: UUID, kind: JobKind, job_id: UUID) -> None:
    """Put the job live again when it holds calls. Raises what the publish refused."""
    if not await holds_calls(tenant_id, kind, job_id):
        return
    if kind == "campaign":
        await put_campaign_live(tenant_id=tenant_id, campaign_id=job_id, require_holding=True)
    else:
        await put_line_live(tenant_id=tenant_id, line_id=job_id)


async def put_live_each(tenant_id: UUID, jobs: list[tuple[JobKind, UUID]]) -> int:
    """`put_live` for several jobs after one apply. A refusal leaves that job on its previous
    list until its next put-live and does not stop the others; returns how many were refused.
    Logged by id and code only."""
    refused = 0
    for kind, job_id in jobs:
        try:
            await put_live(tenant_id, kind, job_id)
        except ProblemError as exc:
            refused += 1
            log.warning(
                "job_notes_put_live_refused",
                extra={"job_kind": kind, "job_id": str(job_id), "reason": exc.code},
            )
    return refused


__all__ = ["JobKind", "holds_calls", "put_live", "put_live_each"]
