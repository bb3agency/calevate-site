"""How many calls one client may have at once, as the operator's endpoints (F7).

    GET /v1/admin/organizations/{org_id}/call-lines   the value in force and where it comes from
    PUT /v1/admin/organizations/{org_id}/call-lines   set it, or null for Calevate's default

Operator-only: the number of lines is a commercial decision about the client, not the
client's own setting. The writer (`tenancy/call_lines.set_call_lines`) owes the client's own
workspace the new value in the saving transaction.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.tenancy.call_lines import (
    PAID_CALL_LINES_DEFAULT,
    TRIAL_CALL_LINES_DEFAULT,
    CallLines,
    read_call_lines,
    set_call_lines,
)
from apps.api.tenancy.models import CALL_LINES_MAX, CALL_LINES_MIN

Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

router = APIRouter(tags=["admin"])


class CallLinesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The number of calls at once in force.
    call_lines: int
    #: The operator's choice; `null` is Calevate's default.
    call_lines_chosen: int | None
    #: `organization` when an operator chose it, `platform` for the default.
    source: Literal["organization", "platform"]
    #: A free-trial account: its default is the trial's, and Calevate's dial gate holds it.
    on_trial: bool
    min_lines: int
    max_lines: int
    paid_default: int
    trial_default: int


class CallLinesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `null` goes back to Calevate's default.
    call_lines: int | None


def call_lines_confirmation(org_id: UUID) -> str:
    """The `X-Confirm-Action` for changing one client's calls at once (D-731): more lines is
    more calls billed at the same moment, so it is confirmed like the other commercial levers."""
    return f"set_call_lines:{org_id}"


def _out(state: CallLines) -> CallLinesOut:
    return CallLinesOut(
        call_lines=state.lines,
        call_lines_chosen=state.chosen,
        source=state.source,
        on_trial=state.on_trial,
        min_lines=CALL_LINES_MIN,
        max_lines=CALL_LINES_MAX,
        paid_default=PAID_CALL_LINES_DEFAULT,
        trial_default=TRIAL_CALL_LINES_DEFAULT,
    )


_DESCRIPTION = (
    "How many calls this client may have at once. `null` is Calevate's default: "
    f"{PAID_CALL_LINES_DEFAULT} for a paying client, {TRIAL_CALL_LINES_DEFAULT} on a free "
    f"trial; a chosen value is {CALL_LINES_MIN}-{CALL_LINES_MAX}. A paying client's own voice "
    "workspace is capped at it; a free trial's calls are counted by our dial gate, which "
    "refuses one more with `call_lines_busy`."
)


@router.get(
    "/v1/admin/organizations/{org_id}/call-lines",
    response_model=CallLinesOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="How many calls one client may have at once",
    description=_DESCRIPTION,
)
async def admin_get_call_lines(org_id: UUID, request: Request, principal: Operator) -> CallLinesOut:
    async with tenant_session(org_id) as scoped:
        state = await read_call_lines(scoped, tenant_id=org_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=org_id
        )
    return _out(state)


@router.put(
    "/v1/admin/organizations/{org_id}/call-lines",
    response_model=CallLinesOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set how many calls one client may have at once",
    description=_DESCRIPTION,
)
async def admin_set_call_lines(
    org_id: UUID,
    payload: CallLinesIn,
    request: Request,
    principal: Operator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> CallLinesOut:
    step_up.require(x_confirm_action, call_lines_confirmation(org_id))
    async with tenant_session(org_id) as scoped:
        state, moved = await set_call_lines(scoped, tenant_id=org_id, lines=payload.call_lines)
        await write_audit(
            scoped,
            action="admin.call_lines_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=client_request_ip(request),
            summary={"call_lines": payload.call_lines, "in_force": state.lines, "moved": moved},
        )
    return _out(state)


__all__ = ["CallLinesIn", "CallLinesOut", "call_lines_confirmation", "router"]
