"""The pause before an agent replies and hanging up when it has finished, as endpoints (D-751).

    GET   /v1/agents/{agent_id}/call-handling                       one agent's, with sources
    PATCH /v1/agents/{agent_id}/call-handling                       set or inherit (owner)
    GET   /v1/organization/call-handling                            the account's defaults
    PUT   /v1/organization/call-handling                            set them (owner)
    GET   /v1/admin/tenants/{tid}/agents/{aid}/call-handling        the operator's view
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-handling        the operator's door
    GET   /v1/admin/organizations/{org_id}/call-handling            the operator's view
    PUT   /v1/admin/organizations/{org_id}/call-handling            the operator's door

The writes are `org:manage`, the owner's, as caller memory's are: switching the hang-up off
leaves a finished call billed until the caller puts the phone down, which is a decision about
the account's money. Both realms call one writer (`agents/call_handling`), which queues the
live apply in the saving transaction (D-720), so the next call uses the new value.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_handling
from apps.api.agents.call_handling import (
    END_CALL_ON_FINISH_DEFAULT,
    TURN_SILENCE_DEFAULT_MS,
    AgentCallHandling,
    OrganizationCallHandling,
    SettingSource,
)
from apps.api.agents.models import TURN_SILENCE_MAX_MS, TURN_SILENCE_MIN_MS
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

Session = Annotated[AsyncSession, Depends(db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
OrgReader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

router = APIRouter(tags=["agents"])
admin_router = APIRouter(tags=["admin"])


class CallHandlingBoundsOut(BaseModel):
    """What may be chosen and what Calevate's own defaults are."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_min_ms: int
    turn_silence_max_ms: int
    platform_turn_silence_ms: int
    platform_end_call_on_finish: bool


def _bounds() -> CallHandlingBoundsOut:
    return CallHandlingBoundsOut(
        turn_silence_min_ms=TURN_SILENCE_MIN_MS,
        turn_silence_max_ms=TURN_SILENCE_MAX_MS,
        platform_turn_silence_ms=TURN_SILENCE_DEFAULT_MS,
        platform_end_call_on_finish=END_CALL_ON_FINISH_DEFAULT,
    )


class AgentCallHandlingOut(BaseModel):
    """One agent's two settings: its own value (`null` inherits), the value in force and the
    level that chose it (`agent`, `organization` or `platform`)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    turn_silence_ms: int | None
    turn_silence_ms_effective: int
    turn_silence_source: SettingSource
    end_call_on_finish: bool | None
    end_call_on_finish_effective: bool
    end_call_on_finish_source: SettingSource
    #: The account defaults an agent with no value of its own follows (`null`: Calevate's).
    organization_turn_silence_ms: int | None
    organization_end_call_on_finish: bool | None
    bounds: CallHandlingBoundsOut


class AgentCallHandlingIn(BaseModel):
    """Either or both. A field left out is untouched; `null` goes back to inheriting."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_ms: int | None = Field(default=None)
    end_call_on_finish: bool | None = Field(default=None)


class OrganizationCallHandlingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The account's own choice; `null` follows Calevate's default.
    turn_silence_ms: int | None
    turn_silence_ms_effective: int
    end_call_on_finish: bool | None
    end_call_on_finish_effective: bool
    bounds: CallHandlingBoundsOut


class OrganizationCallHandlingIn(BaseModel):
    """Both, required: the body states the whole resource, so `null` is "follow Calevate"."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_ms: int | None
    end_call_on_finish: bool | None


def _agent_out(state: AgentCallHandling) -> AgentCallHandlingOut:
    return AgentCallHandlingOut(
        agent_id=state.agent_id,
        turn_silence_ms=state.turn_silence_ms,
        turn_silence_ms_effective=state.turn_silence.ms,
        turn_silence_source=state.turn_silence.source,
        end_call_on_finish=state.end_call_on_finish,
        end_call_on_finish_effective=state.end_call.enabled,
        end_call_on_finish_source=state.end_call.source,
        organization_turn_silence_ms=state.organization_turn_silence_ms,
        organization_end_call_on_finish=state.organization_end_call_on_finish,
        bounds=_bounds(),
    )


def _org_out(state: OrganizationCallHandling) -> OrganizationCallHandlingOut:
    return OrganizationCallHandlingOut(
        turn_silence_ms=state.turn_silence_ms,
        turn_silence_ms_effective=state.turn_silence.ms,
        end_call_on_finish=state.end_call_on_finish,
        end_call_on_finish_effective=state.end_call.enabled,
        bounds=_bounds(),
    )


def _changes(payload: AgentCallHandlingIn) -> dict[str, int | bool | None]:
    return {
        f: getattr(payload, f) for f in call_handling.AGENT_FIELDS if f in payload.model_fields_set
    }


_AGENT_DESCRIPTION = (
    "`turn_silence_ms` is how long the caller must be quiet before the agent replies, "
    f"{TURN_SILENCE_MIN_MS}-{TURN_SILENCE_MAX_MS} ms; longer suits callers reading out "
    "numbers, shorter answers sooner. `end_call_on_finish` releases the line when the agent "
    "has finished; with it off a finished call stays connected, and charged, until the caller "
    "hangs up. Each resolves agent, then the account default, then Calevate's "
    f"({TURN_SILENCE_DEFAULT_MS} ms, hang-up on); `*_source` names the level in force.\n\n"
    "A change reaches a live agent straight after the save and applies from its next call; "
    "a call in progress finishes as it started. Out-of-range values are refused with "
    "`turn_silence_out_of_range`."
)
_ORG_DESCRIPTION = (
    "The account defaults every agent without a value of its own follows. `null` follows "
    "Calevate's. A change reaches every live agent that inherits it, from its next call."
)


@router.get(
    "/v1/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The pause before an agent replies, and whether it hangs up when finished",
    description=_AGENT_DESCRIPTION,
)
async def get_agent_call_handling(
    agent_id: UUID, session: Session, _: AgentReader
) -> AgentCallHandlingOut:
    return _agent_out(await call_handling.read_agent_call_handling(session, agent_id))


@router.patch(
    "/v1/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set an agent's pause before replying and hang-up, or let it inherit",
    description=_AGENT_DESCRIPTION,
)
async def set_agent_call_handling(
    agent_id: UUID,
    payload: AgentCallHandlingIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> AgentCallHandlingOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    state, moved = await call_handling.set_agent_call_handling(
        session, tenant_id=principal.tenant_id, agent_id=agent_id, changes=_changes(payload)
    )
    await write_audit(
        session,
        action="agent.call_handling_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={**_changes(payload), "changed": list(moved)},
    )
    return _agent_out(state)


@router.get(
    "/v1/organization/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's default pause before replying and hang-up",
    description=_ORG_DESCRIPTION,
)
async def get_organization_call_handling(
    session: Session, _: OrgReader
) -> OrganizationCallHandlingOut:
    return _org_out(await call_handling.read_organization_call_handling(session))


@router.put(
    "/v1/organization/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set this account's default pause before replying and hang-up",
    description=_ORG_DESCRIPTION,
)
async def set_organization_call_handling(
    payload: OrganizationCallHandlingIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> OrganizationCallHandlingOut:
    assert principal.tenant_id is not None
    state, moved = await call_handling.set_organization_call_handling(
        session,
        tenant_id=principal.tenant_id,
        turn_silence_ms=payload.turn_silence_ms,
        end_call_on_finish=payload.end_call_on_finish,
    )
    await write_audit(
        session,
        action="organization.call_handling_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={**payload.model_dump(), "changed": list(moved)},
    )
    return _org_out(state)


@admin_router.get(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client agent's pause before replying and hang-up",
    description=_AGENT_DESCRIPTION,
)
async def admin_get_agent_call_handling(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> AgentCallHandlingOut:
    async with tenant_session(tenant_id) as scoped:
        state = await call_handling.read_agent_call_handling(scoped, agent_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _agent_out(state)


@admin_router.patch(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set one client agent's pause before replying and hang-up",
    description=_AGENT_DESCRIPTION,
)
async def admin_set_agent_call_handling(
    tenant_id: UUID,
    agent_id: UUID,
    payload: AgentCallHandlingIn,
    request: Request,
    principal: AgentOperator,
) -> AgentCallHandlingOut:
    async with tenant_session(tenant_id) as scoped:
        state, moved = await call_handling.set_agent_call_handling(
            scoped, tenant_id=tenant_id, agent_id=agent_id, changes=_changes(payload)
        )
        await write_audit(
            scoped,
            action="admin.agent_call_handling_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={**_changes(payload), "changed": list(moved)},
        )
    return _agent_out(state)


@admin_router.get(
    "/v1/admin/organizations/{org_id}/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's default pause before replying and hang-up",
    description=_ORG_DESCRIPTION,
)
async def admin_get_organization_call_handling(
    org_id: UUID, request: Request, principal: Operator
) -> OrganizationCallHandlingOut:
    async with tenant_session(org_id) as scoped:
        state = await call_handling.read_organization_call_handling(scoped)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=org_id
        )
    return _org_out(state)


@admin_router.put(
    "/v1/admin/organizations/{org_id}/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set one client's default pause before replying and hang-up",
    description=_ORG_DESCRIPTION,
)
async def admin_set_organization_call_handling(
    org_id: UUID,
    payload: OrganizationCallHandlingIn,
    request: Request,
    principal: Operator,
) -> OrganizationCallHandlingOut:
    async with tenant_session(org_id) as scoped:
        state, moved = await call_handling.set_organization_call_handling(
            scoped,
            tenant_id=org_id,
            turn_silence_ms=payload.turn_silence_ms,
            end_call_on_finish=payload.end_call_on_finish,
        )
        await write_audit(
            scoped,
            action="admin.organization_call_handling_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=client_request_ip(request),
            summary={**payload.model_dump(), "changed": list(moved)},
        )
    return _org_out(state)


__all__ = [
    "AgentCallHandlingIn",
    "AgentCallHandlingOut",
    "OrganizationCallHandlingIn",
    "OrganizationCallHandlingOut",
    "admin_router",
    "router",
]
