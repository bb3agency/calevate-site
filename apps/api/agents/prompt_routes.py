"""Admin prompt versioning + rollback endpoints (ROADMAP M2 admin polish).

These live on the ADMIN surface with the tenant named in the path, exactly like the
KB approval endpoints (D-22): an admin reaches a tenant through impersonation, and
impersonation is read-only, so a mutating prompt route on the client realm would be
permanently un-callable. The `app.admin` GUC opens the tenant DIRECTORY only — it
does not unlock `agents` or `prompt_versions` — so every handler enters the tenant's
own RLS scope explicitly via `tenant_session(tenant_id)` for the actual work, and
writes its audit row on the admin session.

Audit summaries carry version NUMBERS, never prompt bodies: prompts routinely embed
client business detail (hard rule 6).

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import prompts
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt", tags=["admin"])

# Reads the tenant DIRECTORY (organizations) cross-tenant; nothing else.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
AgentsWrite = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    notes: str | None
    created_at: datetime
    active: bool


class WritePromptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=20, max_length=8000)
    notes: str | None = Field(default=None, max_length=200)


class PromptWrittenOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int


class RollbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class RollbackOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_version: int
    new_version: int


@router.get(
    "",
    response_model=list[PromptVersionOut],
    openapi_extra=permission_meta("agents:write"),
    summary="Prompt version history, newest first — `active` is the pointer, not a flag",
)
async def prompt_history(
    tenant_id: UUID,
    agent_id: UUID,
    _: AgentsWrite,
    # Bounded (D-302). `prompt_versions` is APPEND-ONLY by design — every publish, every
    # rollback and every T0 recompile writes a row and nothing ever deletes one — so this
    # is the one admin list whose length grows without anybody creating anything.
    # Newest-first, so the default page is the part of the history anyone reads.
    limit: int = Query(100, ge=1, le=200),
) -> list[PromptVersionOut]:
    async with tenant_session(tenant_id) as scoped:
        rows = await prompts.list_prompt_versions(scoped, agent_id, limit=limit)
    return [PromptVersionOut.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=PromptWrittenOut,
    status_code=201,
    openapi_extra=permission_meta("agents:write"),
    summary="Write a new immutable prompt version; a LIVE agent is re-published",
)
async def write_prompt(
    tenant_id: UUID,
    agent_id: UUID,
    payload: WritePromptIn,
    session: AdminSession,
    request: Request,
    principal: AgentsWrite,
) -> PromptWrittenOut:
    async with tenant_session(tenant_id) as scoped:
        version = await prompts.write_prompt_version(
            scoped,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=payload.body,
            notes=payload.notes,
            created_by=principal.user_id,
        )
    await write_audit(
        session,
        action="prompt.version_written",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        # The version NUMBER, never the body (hard rule 6).
        summary={"version": version},
    )
    return PromptWrittenOut(version=version)


@router.post(
    "/rollback",
    response_model=RollbackOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Republish an earlier version as a NEW version (FLOWS §7 doctrine)",
    description="Copy-forward, never pointer-rewind: history stays linear and audited.",
)
async def rollback_prompt(
    tenant_id: UUID,
    agent_id: UUID,
    payload: RollbackIn,
    session: AdminSession,
    request: Request,
    principal: AgentsWrite,
) -> RollbackOut:
    async with tenant_session(tenant_id) as scoped:
        new_version = await prompts.rollback_prompt(
            scoped,
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=payload.version,
            created_by=principal.user_id,
        )
    await write_audit(
        session,
        action="prompt.rolled_back",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"to_version": payload.version, "new_version": new_version},
    )
    return RollbackOut(to_version=payload.version, new_version=new_version)


__all__ = ["router"]
