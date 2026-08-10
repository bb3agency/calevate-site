"""Knowledge-base endpoints (FLOWS §7).

The split of permissions IS the workflow: a client owner (`kb:write`) may SUBMIT and
preview, an admin operator approves and publishes. That is not bureaucracy — the agent
speaks under the client's own PE registration, so a change to what it says is a change
to a legal instrument, and a human reads it first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
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


class RejectIn(Strict):
    reason: str = Field(min_length=3, max_length=500)


class PublishOut(Strict):
    source_id: UUID
    version: int
    status: str


@router.get("/sources", response_model=list[SourceOut], openapi_extra=permission_meta("kb:write"))
async def list_sources(
    session: Session,
    status: str | None = None,
    _: Principal = Depends(requires("kb:write")),
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
    openapi_extra=permission_meta("kb:write"),
    summary="Side-by-side preview of exactly what the agent would learn",
)
async def preview_source(
    source_id: UUID, session: Session, _: Principal = Depends(requires("kb:write"))
) -> list[ChunkOut]:
    return [ChunkOut.model_validate(c) for c in await service.preview(session, source_id)]


@router.post(
    "/sources/{source_id}/approve",
    openapi_extra=permission_meta("agents:write"),
    summary="Admin approval gate (D-28: stays ours whichever provider wins)",
)
async def approve(
    source_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    await service.approve_source(session, source_id=source_id, approved_by=principal.user_id)
    await write_audit(
        session,
        action="kb.approved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
    )
    return {"status": "approved"}


@router.post(
    "/sources/{source_id}/reject",
    openapi_extra=permission_meta("agents:write"),
)
async def reject(
    source_id: UUID,
    payload: RejectIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    await service.reject_source(session, source_id=source_id, reason=payload.reason)
    await write_audit(
        session,
        action="kb.rejected",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
        summary={"reason": payload.reason},
    )
    return {"status": "rejected"}


@router.post(
    "/sources/{source_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Push to the engine KB and make this the active version",
    description="Rollback is republishing an earlier version (FLOWS §7).",
)
async def publish(
    source_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    assert principal.tenant_id is not None
    version = await service.publish_source(
        session, tenant_id=principal.tenant_id, source_id=source_id
    )
    await write_audit(
        session,
        action="kb.published",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
        summary={"version": version},
    )
    return PublishOut(source_id=source_id, version=version, status="live")


__all__ = ["router"]
