"""Agent endpoints. Reads are client-realm; publish is admin-only.

D-21 draws the control boundary and it is enforced here: clients CAN see their agents,
but editing an extraction schema is admin-only, because a schema change regenerates
prompt hints and needs a regression run — that routes through us, which is the
managed-service moat, not an oversight.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import publish_agent
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/agents", tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]


class AgentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    direction: str
    status: str
    language_primary: str
    # Shown to the client verbatim: they are legally the Principal Entity, so they
    # need to be able to read what their agent announces (SEC-COMP §1).
    disclosure_line: str
    engine: str
    published: bool
    extraction_fields: list[ExtractionField] = []


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    engine_agent_ref: str
    status: str


@router.get("", response_model=list[AgentOut], openapi_extra=permission_meta("agents:read"))
async def list_agents(
    session: Session, _: Principal = Depends(requires("agents:read"))
) -> list[AgentOut]:
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.status, a.language_primary, "
                "a.disclosure_line, a.engine, a.engine_agent_ref, es.fields "
                "FROM agents a LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.deleted_at IS NULL ORDER BY a.created_at"
            )
        )
    ).all()
    return [
        AgentOut(
            id=r[0],
            name=r[1],
            direction=r[2],
            status=r[3],
            language_primary=r[4],
            disclosure_line=r[5],
            engine=r[6],
            published=bool(r[7]),
            extraction_fields=[ExtractionField.model_validate(f) for f in (r[8] or [])],
        )
        for r in rows
    ]


@router.get("/{agent_id}", response_model=AgentOut, openapi_extra=permission_meta("agents:read"))
async def get_agent(
    agent_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> AgentOut:
    agents = await list_agents(session)  # RLS-scoped; small list per tenant in v1
    found = next((a for a in agents if a.id == agent_id), None)
    if found is None:
        raise ProblemError.not_found("Agent")
    return found


@router.post(
    "/{agent_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Create/update the agent on the engine and record its routing (admin only)",
)
async def publish(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    assert principal.tenant_id is not None
    ref = await publish_agent(session, tenant_id=principal.tenant_id, agent_id=agent_id)
    await write_audit(
        session,
        action="agent.published",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=request.client.host if request.client else None,
    )
    return PublishOut(agent_id=agent_id, engine_agent_ref=ref, status="live")


__all__ = ["router"]
