"""Putting an inbound line on the calling platform and on its numbers (D-997).

Two transactions, in this order: the line's own engine agent is created or updated and read
back (`agents/service.publish_line`), then, once that has committed, its numbers are pointed
at it (`agents/service.route_line_numbers`). A number therefore never points at an engine
agent a rolled-back publish left unrecorded. The daily number sweep
(`campaigns/engine_numbers`) holds the same wanted state, so a binding the platform refused
here is repaired there.
"""

from __future__ import annotations

from uuid import UUID

from apps.api.agents import service as agents_service
from apps.api.agents.service import InboundRouting
from apps.api.db.session import tenant_session


async def put_line_live(*, tenant_id: UUID, line_id: UUID) -> str:
    """Publish the line's engine agent, then route its numbers to it. Returns the ref."""
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_line(session, tenant_id=tenant_id, line_id=line_id)
    await route_numbers(tenant_id=tenant_id, line_id=line_id)
    return ref


async def route_numbers(*, tenant_id: UUID, line_id: UUID) -> InboundRouting:
    """Point the line's numbers at its engine agent, or release them while its voice is off,
    deleted or silenced. A line not yet live leaves its numbers as they were."""
    async with tenant_session(tenant_id) as session:
        return await agents_service.route_line_numbers(session, line_id=line_id)


__all__ = ["put_line_live", "route_numbers"]
