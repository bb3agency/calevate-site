"""The operator's surface for what a number-month costs a client. Admin realm only.

Its own `/v1/admin/number-pricing` prefix rather than a path under `admin_router`, for
`admin/number_routes.py`'s reason: that router owns `/v1/admin/tenants/{tenant_id}`, which
would swallow a literal segment beside it. This is a platform-wide rate, not a tenant's
record, so it carries no tenant in its path either.

**ONE ATTESTATION UNBLOCKS CLIENT PURCHASES, AND THAT IS THE WHOLE POINT.** Hard rule 7
keeps a price nobody has read out of a client's bill, which is why
`campaigns/number_pricing.py` refuses until this route has been used — the same standard
`ops/model_price_routes.py` applies to a model minute. It is admin-realm because a client
attesting their own price is not an attestation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.number_pricing import (
    attested_price_inr,
    record_attested_price_inr,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/admin/number-pricing", tags=["admin"])

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
PricingOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class NumberPriceIn(BaseModel):
    """The rupee figure, and what it was read from.

    `source` is required and is not decoration: hard rule 11 wants the evidence to travel
    with the claim, and a bare number on a pricing screen is the figure a later session
    repeats as though somebody had read an invoice. Name the document — the carrier's
    order form, the invoice, the quote — and its date.
    """

    model_config = ConfigDict(extra="forbid")

    #: NUMERIC on the wire as a string-safe `Decimal`, never a float (hard rule 7). The
    #: ceiling is a typo guard, not a business limit: a DID that rents for more than
    #: ₹100,000 a month is a fat finger.
    inr_per_month: Decimal = Field(gt=0, le=100000)
    source: str = Field(min_length=4, max_length=400)


class NumberPriceOut(BaseModel):
    """The rate in force, or `attested: false` when a client cannot yet be quoted one."""

    model_config = ConfigDict(extra="forbid")

    attested: bool
    inr_per_month: str | None = None
    source: str | None = None
    attested_at: str | None = None


@router.get(
    "",
    response_model=NumberPriceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="What a number-month currently costs a client, and what that figure came from",
)
async def current_price(session: AdminSession, _: PricingOperator) -> NumberPriceOut:
    price = await attested_price_inr(session)
    if price is None:
        return NumberPriceOut(attested=False)
    return NumberPriceOut(
        attested=True,
        inr_per_month=str(price.inr_per_month),
        source=price.source,
        attested_at=price.attested_at.isoformat(),
    )


@router.post(
    "",
    response_model=NumberPriceOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Attest what a number-month costs a client — a rate change is a new row",
    description=(
        "Records the monthly price a client is charged for a phone number, in rupees, "
        "with the document it was read from. Until one is recorded no client can buy a "
        "number: a price nobody has read may not reach a bill. A rate change is a new "
        "attestation — numbers already bought keep the figure they were sold at, so "
        "editing the rate in place would leave those frozen figures unexplainable."
    ),
)
async def attest_price(
    payload: NumberPriceIn,
    session: AdminSession,
    request: Request,
    principal: PricingOperator,
) -> NumberPriceOut:
    assert principal.user_id is not None
    price = await record_attested_price_inr(
        session,
        inr_per_month=payload.inr_per_month,
        source=payload.source,
        attested_by=principal.user_id,
    )
    await write_audit(
        session,
        action="number_price.attested",
        actor=principal,
        tenant_id=None,
        object_type="number_price_attestation",
        object_id=str(price.id),
        ip=client_request_ip(request),
        summary={"inr_per_month": str(price.inr_per_month), "source": price.source},
    )
    return NumberPriceOut(
        attested=True,
        inr_per_month=str(price.inr_per_month),
        source=price.source,
        attested_at=price.attested_at.isoformat(),
    )


__all__ = ["router"]
