"""The operator's per-agent knowledge list (D-868): `kb/agent_view.py` over HTTP.

Admin realm. A read is recorded as a tenant read; removing a document no row of ours names
is audited.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import agent_view

router = APIRouter(prefix="/v1/admin/tenants", tags=["admin"])

Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]


class AgentKnowledgeItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `held` · `missing` · `not_sent` · `not_ours` (`kb/agent_view.py`).
    verdict: Literal["held", "missing", "not_sent", "not_ours"]
    handle: str | None = None
    source_id: UUID | None = None
    name: str | None = None
    kind: str | None = None
    detail: str | None = None


class AgentKnowledgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: False when the platform's list could not be read: `held` then means "ours on record".
    listed: bool
    items: list[AgentKnowledgeItemOut]


class RemoveDocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = Field(min_length=1, max_length=2048)


@router.get(
    "/{tenant_id}/agents/{agent_id}/knowledge",
    response_model=AgentKnowledgeOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Everything one agent holds on the voice platform",
    description=(
        "Our copies (held, or missing on the platform), the client's live items not on this "
        "agent and why, and documents the platform holds that we did not send."
    ),
)
async def admin_agent_knowledge(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> AgentKnowledgeOut:
    async with tenant_session(tenant_id) as scoped:
        view = await agent_view.agent_knowledge(
            scoped, get_engine(), tenant_id=tenant_id, agent_id=agent_id
        )
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return AgentKnowledgeOut(
        agent_id=view.agent_id,
        listed=view.listed,
        items=[
            AgentKnowledgeItemOut(
                verdict=item.verdict,
                handle=item.handle,
                source_id=item.source_id,
                name=item.name,
                kind=item.kind,
                detail=item.detail,
            )
            for item in view.items
        ],
    )


@router.post(
    "/{tenant_id}/agents/{agent_id}/knowledge/remove",
    status_code=204,
    openapi_extra=permission_meta("agents:write"),
    summary="Remove a document we did not send from one agent",
    description=(
        "Deletes, on the voice platform, a document this agent holds that no record of ours "
        "names. 409 for one of the client's own items (removed from their page instead); "
        "404 when the agent does not hold it."
    ),
)
async def admin_remove_unrecorded_document(
    tenant_id: UUID,
    agent_id: UUID,
    payload: RemoveDocumentIn,
    request: Request,
    principal: AgentOperator,
) -> None:
    async with tenant_session(tenant_id) as scoped:
        await agent_view.remove_unrecorded(
            scoped, get_engine(), tenant_id=tenant_id, agent_id=agent_id, handle=payload.handle
        )
        await write_audit(
            scoped,
            action="admin.agent_document_removed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"handle": payload.handle},
        )


__all__ = ["AgentKnowledgeItemOut", "AgentKnowledgeOut", "RemoveDocumentIn", "router"]
