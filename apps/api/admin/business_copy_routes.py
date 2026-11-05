"""A client's AI-written examples and suggestions, as an operator sees them (D-827).

    GET   /v1/admin/tenants/{tenant_id}/business-copy           the copy in use, the last
                                                                run's stop reason and cost
    POST  /v1/admin/tenants/{tenant_id}/business-copy/refresh   write it again now, at our
                                                                cost
    PUT   /v1/admin/tenants/{tenant_id}/business-copy/capabilities/{capability}
                                                                correct one AI verdict

The operator's refresh is absorbed (`ASSIST_FEATURE_BUSINESS_COPY_ABSORBED`): the client's AI
allowance is not touched; the platform-wide AI brake still stops it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.capability_overrides import overrides_of, set_override
from apps.api.admin.service import tenant_exists
from apps.api.billing.ai_quota import platform_brake_tripped
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.tenancy import business_copy as service
from apps.api.tenancy.business_copy import CAPABILITY_KEYS
from apps.api.tenancy.business_copy_routes import BusinessCopyOut, render

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/business-copy", tags=["admin"])

AdminReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
#: Correcting a client's profile is the operator's client-data lever, as the business type is.
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
#: Spends our AI money, so it sits with the other ops levers, as "Suggest again" does.
OpsManager = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]


class AdminBusinessCopyOut(BusinessCopyOut):
    model: str | None
    #: What the run that wrote the copy in use was metered at, in rupees, as a string.
    cost_inr: str | None
    #: True when that run was ours to pay for (a trial's first copy, an operator's refresh).
    absorbed: bool
    last_trigger: str | None
    last_attempt_at: datetime | None
    #: Capabilities an operator set, overriding the AI (`admin/capability_overrides`).
    capability_overrides: dict[str, bool]


def _admin_out(state: service.CopyState | None, overrides: dict[str, bool]) -> AdminBusinessCopyOut:
    base = render(state).model_dump()
    has_copy = state is not None and state.copy is not None
    return AdminBusinessCopyOut(
        **base,
        model=state.model if state is not None and has_copy else None,
        cost_inr=str(state.cost_inr) if state is not None and state.cost_inr is not None else None,
        absorbed=bool(state is not None and state.absorbed),
        last_trigger=state.last_trigger if state is not None else None,
        last_attempt_at=state.last_attempt_at if state is not None else None,
        capability_overrides=overrides,
    )


async def _overrides(scoped: AsyncSession, tenant_id: UUID) -> dict[str, bool]:
    raw = (
        await scoped.execute(
            text("SELECT capability_overrides FROM business_copies WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).scalar_one_or_none()
    return overrides_of(raw)


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """A uuid naming nobody is a 404, never an empty copy for an absent account."""
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")


@router.get(
    "",
    response_model=AdminBusinessCopyOut,
    openapi_extra=permission_meta("org:read"),
    summary="The client's AI-written examples and suggestions",
)
async def admin_read_business_copy(
    tenant_id: UUID, request: Request, principal: AdminReader
) -> AdminBusinessCopyOut:

    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        state = await service.read_state(scoped)
        overrides = await _overrides(scoped, tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _admin_out(state, overrides)


@router.post(
    "/refresh",
    response_model=AdminBusinessCopyOut,
    status_code=202,
    openapi_extra=permission_meta("ops:manage"),
    summary="Write the client's examples and suggestions again, at our cost",
    description=(
        "Queues one run now, whether or not the client's details changed. Our cost, not the "
        "client's AI allowance. Refused while a run is in progress."
    ),
)
async def admin_refresh_business_copy(
    tenant_id: UUID, request: Request, principal: OpsManager
) -> AdminBusinessCopyOut:

    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        state = await service.read_state(scoped)
        if state is not None and state.running:
            raise ProblemError.conflict(
                "business_copy_refreshing",
                "The examples are being written now. Look again in a minute.",
            )
        if await platform_brake_tripped(scoped):
            raise ProblemError(
                kind="transient",
                code="ai_paused_platform_wide",
                title="AI help is paused",
                detail="AI help is paused across Calevate while usage is checked.",
                remediation="Try again once the AI brake is released.",
            )
        await service.queue_generation(scoped, tenant_id=tenant_id, trigger="operator")
        await write_audit(
            scoped,
            action="organization.business_copy_refresh_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={},
        )
        overrides = await _overrides(scoped, tenant_id)
    # Queued counts as refreshing: the screen polls until the run has written or stopped.
    return _admin_out(state, overrides).model_copy(update={"refreshing": True})


class CapabilityOverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: True or False to decide it; null to go back to the AI's judgement.
    applies: bool | None


@router.put(
    "/capabilities/{capability}",
    response_model=AdminBusinessCopyOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Correct one capability the AI judged for this client, or go back to the AI's",
    description=(
        "Sets what the business does with its callers (for example `takes_bookings`) where "
        "the AI judged it wrongly. A regeneration keeps the correction. `applies: null` "
        "restores the AI's verdict. Audited."
    ),
)
async def admin_set_capability(
    tenant_id: UUID,
    capability: str,
    payload: CapabilityOverrideIn,
    request: Request,
    principal: Operator,
) -> AdminBusinessCopyOut:
    if capability not in CAPABILITY_KEYS:
        raise ProblemError.not_found("Capability")
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        overrides = await set_override(
            scoped, tenant_id=tenant_id, capability=capability, applies=payload.applies
        )
        await write_audit(
            scoped,
            action="organization.capability_override_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"capability": capability, "applies": payload.applies},
        )
        state = await service.read_state(scoped)
    return _admin_out(state, overrides)
