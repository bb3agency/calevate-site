"""Auto-recharge, as the client sees it (D-699). The rules are in `billing/auto_recharge.py`.

    GET    /v1/billing/auto-recharge                    settings, mandate and this month
    PUT    /v1/billing/auto-recharge                    save threshold, amount, cap, on/off
    POST   /v1/billing/auto-recharge/mandate            start UPI Autopay or a card mandate
    POST   /v1/billing/auto-recharge/mandate/confirm    the browser's return from Checkout
    DELETE /v1/billing/auto-recharge/mandate            withdraw the mandate
    GET    /v1/billing/auto-recharge/charges            the recharges we started

Reads are `billing:read`; everything that can spend the client's money is `org:manage`,
which an impersonating admin does not hold (D-22), so an operator can never set up or
trigger a mandate on a client's behalf.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from apps.api.billing.auto_recharge import (
    AutoRechargeState,
    begin_mandate,
    cancel_mandate,
    confirm_mandate,
    read_auto_recharge,
    save_auto_recharge,
)
from apps.api.billing.razorpay_api import MANDATE_MAX_DEBIT_INR
from apps.api.billing.service import to_paise
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/billing/auto-recharge", tags=["billing"])

Reader = Annotated[Principal, Depends(requires("billing:read", realm="client"))]
Writer = Annotated[Principal, Depends(requires("org:manage", realm="client"))]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError('money crosses the wire as a string ("2000.00"), never as a float')
    return value


class AutoRechargeOut(_Strict):
    enabled: bool
    threshold_inr: Decimal
    amount_inr: Decimal
    monthly_cap_inr: Decimal
    #: `none`, `pending`, `confirmed`, `rejected`, `cancelled` or `paused`.
    mandate_status: str
    mandate_method: Literal["upi", "card"] | None
    mandate_max_inr: Decimal | None
    consecutive_failures: int
    disabled_reason: str | None
    month_charged_inr: Decimal
    pending_charge_inr: Decimal | None
    #: The largest single automatic payment allowed without the client approving it.
    max_debit_inr: Decimal
    #: A threshold covering the ~1.5 days a recharge takes to land, from recent calling.
    suggested_threshold_inr: Decimal | None


def _out(state: AutoRechargeState) -> AutoRechargeOut:
    method = state.mandate_method if state.mandate_method in ("upi", "card") else None
    return AutoRechargeOut(
        enabled=state.enabled,
        threshold_inr=state.threshold_inr,
        amount_inr=state.amount_inr,
        monthly_cap_inr=state.monthly_cap_inr,
        mandate_status=state.mandate_status,
        mandate_method=method,  # type: ignore[arg-type]
        mandate_max_inr=state.mandate_max_inr,
        consecutive_failures=state.consecutive_failures,
        disabled_reason=state.disabled_reason,
        month_charged_inr=state.month_charged_inr,
        pending_charge_inr=state.pending_charge_inr,
        max_debit_inr=to_paise(MANDATE_MAX_DEBIT_INR),
        suggested_threshold_inr=state.suggested_threshold_inr,
    )


class AutoRechargeIn(_Strict):
    enabled: bool
    threshold_inr: Decimal = Field(max_digits=10, decimal_places=2)
    amount_inr: Decimal = Field(max_digits=10, decimal_places=2)
    monthly_cap_inr: Decimal = Field(max_digits=10, decimal_places=2)

    _floats = field_validator("threshold_inr", "amount_inr", "monthly_cap_inr", mode="before")(
        _no_float
    )


class MandateIn(_Strict):
    method: Literal["upi", "card"]
    #: The largest single recharge this mandate may debit.
    max_debit_inr: Decimal = Field(max_digits=10, decimal_places=2)

    _floats = field_validator("max_debit_inr", mode="before")(_no_float)


class MandateCheckoutOut(_Strict):
    key_id: str
    order_id: str
    customer_id: str
    amount_paise: int
    notes: dict[str, str]


class MandateConfirmIn(_Strict):
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class ChargeOut(_Strict):
    amount_inr: Decimal
    status: Literal["pending", "captured", "failed"]
    failure_code: str | None
    created_at: datetime
    settled_at: datetime | None


@router.get(
    "",
    response_model=AutoRechargeOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Auto-recharge settings, the approved payment method and this month's charges",
)
async def read_settings(principal: Reader) -> AutoRechargeOut:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        return _out(await read_auto_recharge(session, tenant_id=principal.tenant_id))


@router.put(
    "",
    response_model=AutoRechargeOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save auto-recharge: threshold, recharge amount, monthly limit, on or off",
)
async def save_settings(
    payload: AutoRechargeIn, request: Request, principal: Writer
) -> AutoRechargeOut:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        state = await save_auto_recharge(
            session,
            tenant_id=principal.tenant_id,
            enabled=payload.enabled,
            threshold_inr=to_paise(payload.threshold_inr),
            amount_inr=to_paise(payload.amount_inr),
            monthly_cap_inr=to_paise(payload.monthly_cap_inr),
            actor_user_id=principal.user_id,
            ip=client_request_ip(request),
        )
    return _out(state)


@router.post(
    "/mandate",
    response_model=MandateCheckoutOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Start approving UPI Autopay or a card for automatic recharges",
    description=(
        "Creates the payment provider's customer and an approval order with a per-payment "
        "limit; the browser then opens the payment window with `recurring` set. The ₹1 "
        "approval payment is added to the balance."
    ),
)
async def start_mandate(
    payload: MandateIn, request: Request, principal: Writer
) -> MandateCheckoutOut:
    assert principal.tenant_id is not None and principal.user_id is not None
    checkout = await begin_mandate(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        method=payload.method,
        max_debit_inr=to_paise(payload.max_debit_inr),
        ip=client_request_ip(request),
    )
    return MandateCheckoutOut(
        key_id=checkout.key_id,
        order_id=checkout.order_id,
        customer_id=checkout.customer_id,
        amount_paise=checkout.amount_paise,
        notes=checkout.notes,
    )


@router.post(
    "/mandate/confirm",
    response_model=AutoRechargeOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Verify the approval returned by the payment window",
)
async def confirm(payload: MandateConfirmIn, principal: Writer) -> AutoRechargeOut:
    assert principal.tenant_id is not None
    state = await confirm_mandate(
        tenant_id=principal.tenant_id,
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
    )
    return _out(state)


@router.delete(
    "/mandate",
    response_model=AutoRechargeOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Withdraw the automatic-payment approval and turn auto-recharge off",
)
async def withdraw(request: Request, principal: Writer) -> AutoRechargeOut:
    assert principal.tenant_id is not None
    return _out(
        await cancel_mandate(
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            ip=client_request_ip(request),
        )
    )


@router.get(
    "/charges",
    response_model=list[ChargeOut],
    openapi_extra=permission_meta("billing:read"),
    summary="The automatic recharges started on this account, newest first",
)
async def read_charges(
    principal: Reader, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ChargeOut]:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT amount_inr, status, failure_code, created_at, settled_at "
                    "FROM auto_recharge_charges WHERE tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"tid": principal.tenant_id, "limit": limit},
            )
        ).all()
    return [
        ChargeOut(
            amount_inr=to_paise(Decimal(str(r[0]))),
            status=r[1],
            failure_code=r[2],
            created_at=r[3],
            settled_at=r[4],
        )
        for r in rows
    ]


__all__ = ["router"]
