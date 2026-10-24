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
from typing import Annotated, Final
from uuid import UUID

from calevate_shared.engine import PromptLayer
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import prompt_anatomy, prompts
from apps.api.agents.prompt_anatomy import CallerMemory, LayerOwner
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt", tags=["admin"])

# Reads the tenant DIRECTORY (organizations) cross-tenant; nothing else.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
AgentsWrite = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    notes: str | None
    created_at: datetime
    active: bool


#: The longest script body an admin may save: the hosted engine's instructions ceiling
#: (`engine/hosted_platform.THINNEST_LIMITS.prompt_chars`, 20,000). Publish still refuses a
#: body that no longer fits once the platform rules are added (`engine_prompt_too_long`).
PROMPT_BODY_MAX_CHARS: Final = 20_000


class WritePromptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=20, max_length=PROMPT_BODY_MAX_CHARS)
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
    request: Request,
    principal: AgentsWrite,
    # Bounded (D-302). `prompt_versions` is APPEND-ONLY by design — every publish, every
    # rollback and every T0 recompile writes a row and nothing ever deletes one — so this
    # is the one admin list whose length grows without anybody creating anything.
    # Newest-first, so the default page is the part of the history anyone reads.
    limit: int = Query(100, ge=1, le=200),
) -> list[PromptVersionOut]:
    async with tenant_session(tenant_id) as scoped:
        rows = await prompts.list_prompt_versions(scoped, agent_id, limit=limit)
        # D-482 L-1: a direct per-tenant admin read leaves its own ledger row. The
        # history carries the client's own operator-authored notes and the shape of how
        # often their script has been rewritten, which is the client's record and not
        # ours — and it is read WITHOUT impersonation, so nothing else records it.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
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
            scoped,
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
            scoped,
            action="prompt.rolled_back",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"to_version": payload.version, "new_version": new_version},
        )
    return RollbackOut(to_version=payload.version, new_version=new_version)


class PromptLayerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: PromptLayer
    title: str
    purpose: str
    owner: LayerOwner
    #: True when this agent's settings change the words; False when every agent gets them.
    from_agent_settings: bool
    text: str
    chars: int


class AgentPromptLayersOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: False for an agent with nothing written yet; `layers` is then empty.
    has_script: bool
    #: In the order the engine reads them.
    layers: list[PromptLayerOut]
    #: The line breaks `compose_engine_prompt` puts between layers.
    separator_chars: int
    total_chars: int
    #: The engine's ceiling on the instructions; null where it has none.
    limit_chars: int | None
    over_chars: int
    #: About what the engine adds around this on every turn (its estimate); null if unknown.
    engine_added_chars: int | None
    caller_memory: CallerMemory
    #: True when the agent has an engine object of its own.
    on_engine: bool
    #: The last scheduled comparison of the engine's copy with this composition
    #: (`engine_agent_routes.drift_state`); null when it has not been checked.
    drift_state: str | None
    drift_checked_at: datetime | None


@router.get(
    "/layers",
    response_model=AgentPromptLayersOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="What the agent is told: the composed prompt by layer, with each layer's size",
    description=(
        "The instructions a publish of this agent would send now, in engine order, with the "
        "engine's limit and the last drift sweep's verdict. Reads our tables only; it never "
        "calls the engine. Caller memory is per call and appears unfilled."
    ),
)
async def prompt_layers(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> AgentPromptLayersOut:
    async with tenant_session(tenant_id) as scoped:
        anatomy = await prompt_anatomy.read_anatomy(
            scoped, tenant_id=tenant_id, agent_id=agent_id, engine=get_engine()
        )
        # The client's script is their record, read here without impersonation (D-482 L-1).
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    size = anatomy.size
    separators = (
        sum(p.chars for p in size.layers if p.key == "separator") if size is not None else 0
    )
    return AgentPromptLayersOut(
        agent_id=agent_id,
        has_script=anatomy.has_script,
        layers=[
            PromptLayerOut(
                key=layer.key,
                title=layer.title,
                purpose=layer.guide.purpose,
                owner=layer.guide.owner,
                from_agent_settings=layer.guide.from_agent_settings,
                text=layer.text,
                chars=len(layer.text),
            )
            for layer in anatomy.layers
        ],
        separator_chars=separators,
        total_chars=size.total if size is not None else 0,
        limit_chars=size.limit if size is not None else None,
        over_chars=size.over if size is not None else 0,
        engine_added_chars=size.engine_added if size is not None else None,
        caller_memory=anatomy.caller_memory,
        on_engine=anatomy.on_engine,
        drift_state=anatomy.drift_state,
        drift_checked_at=anatomy.drift_checked_at,
    )


__all__ = ["router"]
