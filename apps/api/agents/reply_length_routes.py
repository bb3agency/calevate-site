"""The longest reply one agent may give, for operators (`agents/reply_length`, D-769).

    GET   /v1/admin/tenants/{tid}/agents/{aid}/reply-length   the ceiling held and inherited
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/reply-length   set or clear (audited)

Admin only: a client neither sees nor sets it. The write is the agent write permission, like
the operator's call-handling and voice-tuning doors, and it reaches a live agent through the
live apply queued in the saving transaction.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.agents import reply_length
from apps.api.agents.reply_length import ReplyLengthState
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

admin_router = APIRouter(tags=["admin"])

_PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/reply-length"
_DESCRIPTION = (
    "The longest reply this agent may give, in tokens "
    f"({reply_length.TOKENS_MIN}-{reply_length.TOKENS_MAX}). A reply that reaches it is cut "
    "off where it stands. `max_reply_tokens` null inherits the console's "
    "`thinnest_reply_length`, which `default` reports."
)


class ReplyLengthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: The agent's own ceiling; null inherits `default`.
    max_reply_tokens: int | None
    #: The console's ceiling for agents without one of their own.
    default: int
    #: What the agent is published with.
    effective: int
    min: int
    max: int


class ReplyLengthIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_reply_tokens: int | None = Field(
        ..., ge=reply_length.TOKENS_MIN, le=reply_length.TOKENS_MAX
    )


def _out(state: ReplyLengthState) -> ReplyLengthOut:
    return ReplyLengthOut(
        agent_id=state.agent_id,
        max_reply_tokens=state.own,
        default=state.default,
        effective=state.effective,
        min=reply_length.TOKENS_MIN,
        max=reply_length.TOKENS_MAX,
    )


@admin_router.get(
    _PATH,
    response_model=ReplyLengthOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="The longest reply one client agent may give",
    description=_DESCRIPTION,
)
async def admin_get_reply_length(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> ReplyLengthOut:
    async with tenant_session(tenant_id) as scoped:
        state = await reply_length.read_reply_length(scoped, agent_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _out(state)


@admin_router.patch(
    _PATH,
    response_model=ReplyLengthOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set the longest reply one client agent may give (audited)",
    description=_DESCRIPTION,
)
async def admin_set_reply_length(
    tenant_id: UUID,
    agent_id: UUID,
    payload: ReplyLengthIn,
    request: Request,
    principal: AgentOperator,
) -> ReplyLengthOut:
    async with tenant_session(tenant_id) as scoped:
        state, moved = await reply_length.set_reply_length(
            scoped, tenant_id=tenant_id, agent_id=agent_id, tokens=payload.max_reply_tokens
        )
        if moved:
            await write_audit(
                scoped,
                action="admin.agent_reply_length_set",
                actor=principal,
                tenant_id=tenant_id,
                object_type="agent",
                object_id=str(agent_id),
                ip=client_request_ip(request),
                summary={"max_reply_tokens": state.own},
            )
    return _out(state)


__all__ = ["admin_router"]
