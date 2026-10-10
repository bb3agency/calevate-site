"""The monthly platform fee's surfaces (D-707): the client's card, the operator's panel.

Two routers:

- `router` — `/v1/billing/platform-fee`. The client reads its fees and opens a Razorpay
  order to pay one. The order is the fee's own, recorded with purpose `platform_fee`, so
  the webhook settles the fee and never credits the wallet (`payment_events`).
- `admin_router` — `/v1/admin/tenants/{tenant_id}/platform-fee`. An operator reads a
  client's fees, grants or withdraws a waiver with a reason, and records a fee paid by
  bank transfer. Every write lands an `audit_log` row in its own transaction.

The switch itself is two ordinary settings in the ops console (`platform_fee_enabled`,
`platform_fee_inr`), so nothing here sets it. NOT mounted here — `main.py` wires both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.billing.payment_objects import PLATFORM_FEE, record_route
from apps.api.billing.payments import (
    NOTES_TENANT_KEY,
    SUPPORTED_CURRENCY,
    inr_to_paise,
    payment_capability,
    payments_not_configured,
    razorpay_orders,
)
from apps.api.billing.platform_fee import (
    GRACE_PERIOD,
    NOTES_CHARGE_KEY,
    FeeCharge,
    FeeStatus,
    attach_order,
    exemption_of,
    fee_status,
    fee_switch,
    list_charges,
    overdue_charge,
    read_charge,
    read_waiver,
    record_payment,
    set_waiver,
)
from apps.api.billing.service import to_paise
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/billing/platform-fee", tags=["billing"])
admin_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/platform-fee", tags=["admin"])

FeeRead = Annotated[Principal, Depends(requires("billing:read", realm="client"))]
FeePay = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
AdminFeeRead = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]
AdminFeeWrite = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: The idempotency route a fee order is claimed under. One order per fee: the key is the
#: charge, so a second click, or a second owner, is handed the same order.
ORDER_ROUTE: Final = "/v1/billing/platform-fee/order"

#: How many months of fees a screen lists.
HISTORY_MONTHS: Final = 12


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeeChargeOut(Strict):
    id: UUID
    #: The IST billing month, `YYYY-MM`.
    period: str
    amount_inr: Decimal
    issued_at: datetime
    #: When outbound calling pauses if this fee is still unpaid.
    grace_ends_at: datetime
    status: FeeStatus
    paid_at: datetime | None
    payment_method: str | None


class PlatformFeeOut(Strict):
    #: Is the platform-wide fee switched on? False means no client is asked for it.
    enabled: bool
    #: What a month costs while the fee is on; null when it is off or not yet priced.
    amount_inr: Decimal | None
    #: Why this account owes no fee, when it does not: `trial` or `waiver`.
    exemption: Literal["trial", "waiver"] | None
    #: Outbound calling is paused for an unpaid fee right now. Incoming calls are not.
    outbound_paused: bool
    grace_days: int
    charges: list[FeeChargeOut]


class FeeOrderOut(Strict):
    charge_id: UUID
    amount_inr: Decimal
    amount_paise: int
    currency: str
    #: The Razorpay key id for the browser Checkout, and the notes it must pass through.
    key_id: str
    notes: dict[str, str]
    #: The order to pay, or null when this deployment cannot create one (no API secret):
    #: the fee is then paid by bank transfer quoting `receipt`, and recorded by us.
    provider_order_id: str | None
    provider_order_pending: bool
    receipt: str


class WaiverIn(Strict):
    reason: str = Field(min_length=3, max_length=280)


class WaiverOut(Strict):
    waived_at: datetime
    reason: str
    #: The operator who granted the waiver, or null once their console account is removed.
    waived_by: UUID | None


class AdminPlatformFeeOut(PlatformFeeOut):
    waiver: WaiverOut | None
    #: When D-707 moved this account off an invoiced retainer onto credits, if it did.
    moved_to_credits_at: datetime | None


class ManualFeePaymentIn(Strict):
    #: The bank transfer's reference (UTR) or any reference the operator can trace.
    reference: str = Field(min_length=3, max_length=120)


class FeePaymentOut(Strict):
    charge_id: UUID
    recorded: bool
    status: FeeStatus


def fee_receipt(charge_id: UUID) -> str:
    """The provider `receipt` and idempotency key for paying one fee — 30 characters,
    inside Razorpay's 40."""
    return f"clvfee{charge_id.hex[:24]}"


def _charge_out(
    charge: FeeCharge, *, at: datetime, exemption: Literal["trial", "waiver"] | None
) -> FeeChargeOut:
    return FeeChargeOut(
        id=charge.id,
        period=charge.period,
        amount_inr=to_paise(charge.amount_inr),
        issued_at=charge.issued_at,
        grace_ends_at=charge.grace_ends_at,
        status=fee_status(charge, at=at, exemption=exemption, switch=fee_switch()),
        paid_at=charge.paid_at,
        payment_method=charge.payment_method,
    )


async def _fee_view(session: AsyncSession, *, tenant_id: UUID) -> PlatformFeeOut:

    at = datetime.now(UTC)
    switch = fee_switch()
    exemption = await exemption_of(session, tenant_id=tenant_id, at=at)
    charges = await list_charges(session, tenant_id=tenant_id, limit=HISTORY_MONTHS)
    paused = await overdue_charge(session, tenant_id=tenant_id, at=at)
    return PlatformFeeOut(
        enabled=switch.enabled,
        amount_inr=to_paise(switch.amount_inr) if switch.charging and switch.amount_inr else None,
        exemption=exemption,
        outbound_paused=paused is not None,
        grace_days=GRACE_PERIOD.days,
        charges=[_charge_out(c, at=at, exemption=exemption) for c in charges],
    )


@router.get(
    "",
    response_model=PlatformFeeOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This account's monthly platform fee: the switch, the fees raised, and any pause",
)
async def read_platform_fee(principal: FeeRead) -> PlatformFeeOut:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        return await _fee_view(session, tenant_id=principal.tenant_id)


@router.post(
    "/{charge_id}/order",
    response_model=FeeOrderOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Open the payment for one monthly platform fee (a separate payment, D-707)",
    description=(
        "Creates the Razorpay order for exactly this fee's amount, recorded so the webhook "
        "settles the fee and never credits calling credit. Idempotent: the same fee always "
        "returns the same order. A paid or waived fee is refused."
    ),
)
async def open_fee_order(charge_id: UUID, principal: FeePay) -> FeeOrderOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
        if charge is None:
            raise ProblemError.not_found("Platform fee")
        exemption = await exemption_of(session, tenant_id=tenant_id, at=at)
    status = fee_status(charge, at=at, exemption=exemption, switch=fee_switch())
    if status in ("paid", "waived"):
        raise ProblemError.business_rule(
            "platform_fee_not_payable",
            "This platform fee is already paid or is not owed.",
            remediation="Nothing to pay. Refresh the Billing page.",
        )

    capability = payment_capability()
    if not capability.available:
        raise payments_not_configured(capability.reason)
    key_id = get_settings().razorpay_key_id
    assert key_id is not None, "the capability check proved this is set"
    amount = to_paise(charge.amount_inr)
    receipt = fee_receipt(charge.id)
    notes = {NOTES_TENANT_KEY: str(tenant_id), NOTES_CHARGE_KEY: str(charge.id)}

    def _out(order_id: str | None) -> FeeOrderOut:
        return FeeOrderOut(
            charge_id=charge.id,
            amount_inr=amount,
            amount_paise=inr_to_paise(amount),
            currency=SUPPORTED_CURRENCY,
            key_id=key_id,
            notes=notes,
            provider_order_id=order_id,
            provider_order_pending=order_id is None,
            receipt=receipt,
        )

    if not capability.creates_orders:
        return _out(None)
    if charge.provider_order_id is not None:
        return _out(charge.provider_order_id)

    scope = scope_key(tenant_id=tenant_id, user_id=None)
    async with tenant_session(tenant_id) as session:
        claim = await claim_idempotency(
            session,
            scope=scope,
            route=ORDER_ROUTE,
            method="POST",
            key=receipt,
            request_hash=body_hash({"tenant_id": str(tenant_id), "receipt": receipt}),
        )
    if claim.state == "replay" and claim.response_payload:
        return FeeOrderOut.model_validate(claim.response_payload)
    try:
        order = await razorpay_orders().create_order(
            amount_inr=amount, receipt=receipt, notes=notes
        )
    except Exception:
        async with tenant_session(tenant_id) as session:
            await fail_idempotency(session, record_id=claim.record_id)
        raise
    result = _out(order.order_id)
    async with tenant_session(tenant_id) as session:
        # OUR record of the order: its tenant, its amount and that it pays a fee, which the
        # webhook checks the captured payment against before it settles anything.
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order.order_id,
            kind="order",
            purpose=PLATFORM_FEE,
            amount_inr=amount,
        )
        await attach_order(
            session, tenant_id=tenant_id, charge_id=charge.id, order_id=order.order_id
        )
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=result.model_dump(mode="json"),
        )
    log.info(
        "platform_fee_order_created",
        extra={"tenant_id": str(tenant_id), "charge_id": str(charge.id)},
    )
    return result


async def _admin_view(session: AsyncSession, *, tenant_id: UUID) -> AdminPlatformFeeOut:

    base = await _fee_view(session, tenant_id=tenant_id)
    waiver = await read_waiver(session, tenant_id=tenant_id)
    moved = (
        await session.execute(
            text("SELECT moved_to_credits_at FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).scalar()
    return AdminPlatformFeeOut(
        **base.model_dump(),
        waiver=None
        if waiver is None
        else WaiverOut(
            waived_at=waiver.waived_at, reason=waiver.reason, waived_by=waiver.waived_by
        ),
        moved_to_credits_at=moved,
    )


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")


@admin_router.get(
    "",
    response_model=AdminPlatformFeeOut,
    openapi_extra=permission_meta("billing:read"),
    summary="One client's monthly platform fee: fees raised, payments, waiver and any pause",
)
async def admin_read_platform_fee(
    tenant_id: UUID, request: Request, principal: AdminFeeRead
) -> AdminPlatformFeeOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        view = await _admin_view(scoped, tenant_id=tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return view


@admin_router.put(
    "/waiver",
    response_model=AdminPlatformFeeOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Excuse this client from the monthly platform fee, with a reason (audited)",
    description=(
        "A waived client is raised no fee and an unpaid one stops pausing their outbound "
        "calls at once. The reason is kept on the account and in the audit log."
    ),
)
async def waive_platform_fee(
    tenant_id: UUID, payload: WaiverIn, request: Request, principal: AdminFeeWrite
) -> AdminPlatformFeeOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        changed = await set_waiver(
            scoped,
            tenant_id=tenant_id,
            reason=payload.reason,
            operator_id=principal.user_id,
            at=datetime.now(UTC),
        )
        if changed:
            await write_audit(
                scoped,
                action="tenant.platform_fee_waived",
                actor=principal,
                tenant_id=tenant_id,
                object_type="organizations",
                object_id=str(tenant_id),
                ip=client_request_ip(request),
                summary={"reason": payload.reason.strip()},
            )
        return await _admin_view(scoped, tenant_id=tenant_id)


@admin_router.delete(
    "/waiver",
    response_model=AdminPlatformFeeOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Withdraw this client's platform fee waiver (audited)",
)
async def withdraw_platform_fee_waiver(
    tenant_id: UUID, request: Request, principal: AdminFeeWrite
) -> AdminPlatformFeeOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        previous = await read_waiver(scoped, tenant_id=tenant_id)
        changed = await set_waiver(
            scoped, tenant_id=tenant_id, reason=None, operator_id=None, at=datetime.now(UTC)
        )
        if changed:
            await write_audit(
                scoped,
                action="tenant.platform_fee_waiver_withdrawn",
                actor=principal,
                tenant_id=tenant_id,
                object_type="organizations",
                object_id=str(tenant_id),
                ip=client_request_ip(request),
                summary={"previous_reason": previous.reason if previous else ""},
            )
        return await _admin_view(scoped, tenant_id=tenant_id)


@admin_router.post(
    "/{charge_id}/payments",
    response_model=FeePaymentOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record a monthly platform fee paid by bank transfer (audited)",
    description=(
        "For a fee the client paid outside Checkout. Records the fee's own amount against "
        "the reference given; recording the same fee twice writes nothing."
    ),
)
async def record_manual_fee_payment(
    tenant_id: UUID,
    charge_id: UUID,
    payload: ManualFeePaymentIn,
    request: Request,
    principal: AdminFeeWrite,
) -> FeePaymentOut:
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        charge = await read_charge(scoped, tenant_id=tenant_id, charge_id=charge_id)
        if charge is None:
            raise ProblemError.not_found("Platform fee")
        recorded = await record_payment(
            scoped,
            tenant_id=tenant_id,
            charge=charge,
            amount_inr=charge.amount_inr,
            method="manual",
            payment_ref=payload.reference,
            paid_at=at,
            recorded_by=principal.user_id,
        )
        if recorded:
            await write_audit(
                scoped,
                action="tenant.platform_fee_paid_manually",
                actor=principal,
                tenant_id=tenant_id,
                object_type="monthly_fee_charges",
                object_id=str(charge.id),
                ip=client_request_ip(request),
                summary={"period": charge.period, "reference": payload.reference.strip()},
            )
        settled = await read_charge(scoped, tenant_id=tenant_id, charge_id=charge_id)
        exemption = await exemption_of(scoped, tenant_id=tenant_id, at=at)
    assert settled is not None
    return FeePaymentOut(
        charge_id=charge_id,
        recorded=recorded,
        status=fee_status(settled, at=at, exemption=exemption, switch=fee_switch()),
    )


__all__ = ["ORDER_ROUTE", "admin_router", "fee_receipt", "router"]
