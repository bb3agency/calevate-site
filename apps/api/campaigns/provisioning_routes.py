"""The client's own surface for a phone number it holds: who it is registered to, and which
agent answers it.

Clients buy numbers in their own business name, in their own customer workspace (D-693),
so the routes that let a client browse and buy a number through Calevate
(`GET /v1/numbers/available`, `POST /v1/numbers/holder`, `POST /v1/numbers/purchase`) are
retired; the number service behind them keeps its own gate (`campaigns/number_catalog.py`).

**KYC GATES ACTIVATION.** A number cannot be given to an agent until its holder is
verified, and binding to an agent is the only thing that puts a number on a handset in
either direction (D-420). `number_not_activated` is its own named refusal, distinct from
the dial gate's KYC blockers so an operator can tell the two apart.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import number_catalog
from apps.api.campaigns.number_holder import read_holder
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/numbers", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` alias rather than a `Depends(...)` default: B008 is waived only for
# `**/routes.py` and this module is `provisioning_routes.py`.
NumberManager = Annotated[Principal, Depends(requires("org:manage"))]

# READING the number screens is a READ. Support impersonating a client is deliberately
# read-only (D-22), so a GET gated on a mutating permission is a screen that support
# cannot see while the client is on the phone asking about it. Assigning takes `org:manage`.
NumberViewer = Annotated[Principal, Depends(requires("org:read"))]


class HolderOut(BaseModel):
    """The recorded holder, or `recorded: false` before there is one."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    holder_type: Literal["individual", "business"] | None = None
    holder_name: str | None = None
    holder_email: str | None = None


class AssignIn(BaseModel):
    """Which agent answers this number, and what the number is for.

    `agent_id: null` DETACHES, which is the recovery path from a wrong assignment and is
    deliberately not gated on activation.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    direction: Literal["inbound", "outbound", "both"] | None = None


class AssignOut(BaseModel):
    """What the voice platform was actually told, so a failed binding is not reported as a
    saved one."""

    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    agent_id: UUID | None
    bound: int
    released: int
    failed: int
    unsupported: int


@router.get(
    "/holder",
    response_model=HolderOut,
    openapi_extra=permission_meta("org:read"),
    summary="Who this account's numbers are registered to, when it was recorded",
)
async def get_holder(session: Session, _: NumberViewer) -> HolderOut:
    holder = await read_holder(session)
    if holder is None:
        return HolderOut(recorded=False)
    return HolderOut(
        recorded=True,
        holder_type=holder.holder_type,
        holder_name=holder.holder_name,
        holder_email=holder.holder_email,
    )


@router.post(
    "/{number_id}/assign",
    response_model=AssignOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Choose which agent answers this number — the binding every other gate needs",
    description=(
        "Points a number at an agent, or at nothing, and tells the voice platform in the "
        "same request. This binding is what makes a number the caller ID a campaign dials "
        "from and the line an agent answers, so a campaign whose number is bound "
        "elsewhere is refused at launch. Refused with `number_not_activated` while the "
        "holder's identity is unverified — the number is held, not lost. The number does "
        "what its agent does: an agent that only makes calls calls out from it, and its "
        "`direction` follows the agent, overriding the request's whenever an agent is "
        "given. Detaching "
        "(`agent_id: null`) is always allowed. The counts say what the platform was told, "
        "so a binding that failed is not reported as one that worked."
    ),
)
async def assign_number(
    number_id: UUID,
    payload: AssignIn,
    session: Session,
    request: Request,
    principal: NumberManager,
) -> AssignOut:
    assert principal.tenant_id is not None
    routing = await number_catalog.assign_number_to_agent(
        session,
        tenant_id=principal.tenant_id,
        number_id=number_id,
        agent_id=payload.agent_id,
        direction=payload.direction,
    )
    await write_audit(
        session,
        action="number.assigned",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={
            "agent_id": str(payload.agent_id) if payload.agent_id else None,
            "bound": routing.bound,
            "failed": routing.failed,
        },
    )
    return AssignOut(
        number_id=number_id,
        agent_id=payload.agent_id,
        bound=routing.bound,
        released=routing.released,
        failed=routing.failed,
        unsupported=routing.unsupported,
    )


__all__ = ["router"]
