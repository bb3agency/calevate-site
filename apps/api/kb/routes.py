"""Client-realm knowledge-base endpoints (FLOWS §7): submit, preview, list.

The split of permissions IS the workflow: a client owner (`kb:write`) SUBMITS and
previews here; approval and publish live on the ADMIN router instead. That is not
bureaucracy — the agent speaks under the client's own PE registration, so a change to
what it says is a change to a legal instrument, and a human reads it first.

Why approval is not simply another route in this file: an admin reaching a tenant does
so through impersonation, and impersonation is READ-ONLY by D-22. An approve endpoint
here would be permanently un-callable — reachable only with a tenant context that
refuses mutations. So the mutating half goes where D-22 says it goes: "mutations still
go through admin surfaces", with the tenant named explicitly in the path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.kb import service

router = APIRouter(prefix="/v1/kb", tags=["knowledge-base"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=10, max_length=200_000)
    kind: Literal["text", "url", "file"] = "text"
    uri: str | None = None


class SourceOut(Strict):
    id: UUID
    agent_id: UUID
    name: str
    kind: str
    status: str
    version: int
    is_active: bool
    published_at: datetime | None
    chunks: int


class SubmitOut(Strict):
    id: UUID
    version: int
    chunks: int
    status: str


class ChunkOut(Strict):
    idx: int
    content: str
    chars: int


# The two READS below are gated on `agents:read`, not `kb:write`. They were `kb:write`
# and that made the admin console's approval queue permanently unreadable: the queue is
# read through impersonation (D-22), impersonation refuses every MUTATING permission,
# and `kb:write` is one. Reading what an agent knows is an agent read; only submitting
# changes what it says.
@router.get(
    "/sources", response_model=list[SourceOut], openapi_extra=permission_meta("agents:read")
)
async def list_sources(
    session: Session,
    status: str | None = None,
    _: Principal = Depends(requires("agents:read")),
) -> list[SourceOut]:
    return [SourceOut.model_validate(r) for r in await service.list_sources(session, status=status)]


@router.post(
    "/sources",
    response_model=SubmitOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Submit knowledge for review — chunked, previewable, NOT yet live",
)
async def submit(
    payload: SubmitIn,
    session: Session,
    principal: Principal = Depends(requires("kb:write")),
) -> SubmitOut:
    assert principal.tenant_id is not None
    result = await service.submit_source(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        name=payload.name,
        body=payload.body,
        kind=payload.kind,
        uri=payload.uri,
        submitted_by=principal.user_id,
    )
    return SubmitOut.model_validate(result)


@router.get(
    "/sources/{source_id}/preview",
    response_model=list[ChunkOut],
    openapi_extra=permission_meta("agents:read"),
    summary="Side-by-side preview of exactly what the agent would learn",
)
async def preview_source(
    source_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> list[ChunkOut]:
    return [ChunkOut.model_validate(c) for c in await service.preview(session, source_id)]


__all__ = ["router"]
