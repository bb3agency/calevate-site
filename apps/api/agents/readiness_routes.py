"""The readiness gauge's two reads (D-870): one agent, and the account.

`agents:read`, the permission the agent screens already require: the score is a reading of
the agent's own settings, tests and knowledge, so whoever may open the agent may see it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.readiness import (
    AccountReadinessOut,
    AgentReadinessOut,
    account_readiness,
    agent_readiness,
)
from apps.api.agents.roster import AGENT_ROSTER_LIMIT, list_agents
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1", tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]


@router.get(
    "/agents/{agent_id}/readiness",
    response_model=AgentReadinessOut,
    openapi_extra=permission_meta("agents:read"),
    summary="How ready this agent is for callers (0-100), and what to fix",
)
async def get_agent_readiness(agent_id: UUID, session: Session, _: Reader) -> AgentReadinessOut:
    return await agent_readiness(session, agent_id)


@router.get(
    "/readiness",
    response_model=AccountReadinessOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Every working agent's readiness, the account's average and the biggest fixes",
)
async def get_account_readiness(
    session: Session,
    _: Reader,
    limit: Annotated[int, Query(ge=1, le=AGENT_ROSTER_LIMIT)] = 50,
) -> AccountReadinessOut:
    agents = await list_agents(session, limit=limit)
    return await account_readiness(session, agents)


__all__ = ["router"]
