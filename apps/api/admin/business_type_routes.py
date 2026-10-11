"""The operator's "Confirm business type" prompt (D-722).

    GET   /v1/admin/tenants/{tenant_id}/business-type           the type on file, or the one
                                                                the account was given by
                                                                default and the AI's suggestion
    POST  /v1/admin/tenants/{tenant_id}/business-type/confirm   a person's choice; the agents'
                                                                lead details and scripts follow

Confirming is the only way an unconfirmed account gets a type back. Changing the type of an
account that already has one stays the profile form's job (`PATCH /v1/admin/tenants/{id}`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from scripts.seed import BUSINESS_TYPE_LABELS

from apps.api.admin import business_type as service
from apps.api.admin.routes import Vertical
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/business-type", tags=["admin"])

AdminReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessTypeChoiceOut(_Out):
    value: str
    label: str


class UnconfirmedOut(_Out):
    #: The type the account was given without anybody choosing it, and runs WITHOUT.
    given: str
    given_label: str
    #: The AI's suggestion, once it has read the business; None while it has not, or when
    #: no model could answer.
    suggested: str | None
    suggested_label: str | None
    reason: str | None
    suggested_at: datetime | None


class BusinessTypeOut(_Out):
    tenant_id: UUID
    business_type: str | None
    business_type_label: str | None
    unconfirmed: UnconfirmedOut | None
    #: Every type, in picker order (`scripts/seed.BUSINESS_TYPE_LABELS`).
    choices: list[BusinessTypeChoiceOut]


class ConfirmBusinessTypeIn(_Out):
    business_type: Vertical


def _label(value: str | None) -> str | None:
    return None if value is None else BUSINESS_TYPE_LABELS.get(value, value)


def _out(tenant_id: UUID, state: service.BusinessTypeState) -> BusinessTypeOut:
    pending = state.unconfirmed
    return BusinessTypeOut(
        tenant_id=tenant_id,
        business_type=state.business_type,
        business_type_label=_label(state.business_type),
        unconfirmed=None
        if pending is None
        else UnconfirmedOut(
            given=pending.given,
            given_label=_label(pending.given) or pending.given,
            suggested=pending.suggested,
            suggested_label=_label(pending.suggested),
            reason=pending.reason,
            suggested_at=pending.suggested_at,
        ),
        choices=[BusinessTypeChoiceOut(value=k, label=v) for k, v in BUSINESS_TYPE_LABELS.items()],
    )


@router.get(
    "",
    response_model=BusinessTypeOut,
    openapi_extra=permission_meta("org:read"),
    summary="The client's business type, or the one it was given by default",
)
async def read_business_type(
    tenant_id: UUID,
    request: Request,
    principal: AdminReader,
) -> BusinessTypeOut:
    async with tenant_session(tenant_id) as scoped:
        state = await service.read_state(scoped, tenant_id=tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _out(tenant_id, state)


@router.post(
    "/confirm",
    response_model=BusinessTypeOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Confirm the client's business type",
    description=(
        "Sets the business type as a person's choice. The client's agents that have no lead "
        "details of their own get this type's details; every agent's script is recompiled to "
        "ask for them, and live agents are updated from their next call. Details a client "
        "chose are kept."
    ),
)
async def confirm_business_type(
    tenant_id: UUID,
    payload: ConfirmBusinessTypeIn,
    request: Request,
    principal: Operator,
) -> BusinessTypeOut:
    async with tenant_session(tenant_id) as scoped:
        before = await service.confirm(
            scoped, tenant_id=tenant_id, business_type=payload.business_type
        )
        await write_audit(
            scoped,
            action="organization.business_type_confirmed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"before": before, "after": payload.business_type},
        )
        state = await service.read_state(scoped, tenant_id=tenant_id)
    return _out(tenant_id, state)
