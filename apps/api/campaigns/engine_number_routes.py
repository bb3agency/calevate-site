"""The client's own phone numbers on the voice platform: verify, details, buy, release (D-693).

On a deployment where each client has its own voice workspace, a client buys its numbers
here, in its own business name: verify the business (KYC, D-692), have its business details
approved, then pick a city, search, see OUR monthly price, buy, and point the number at an
agent. Every gate is `engine_number_purchase.purchase_readiness`, the same one the admin
console reads.

WHITE-LABEL. Nothing a client reads here names the voice platform, its plans or its
prices: the price is the attested Calevate rate, never the vendor's `monthlyPrice`.

`org:manage` for anything that spends money or sends the business's details; `org:read` for
the screens, so support impersonating a client can read them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.number_rental import RentalOutcome
from apps.api.campaigns import engine_numbers
from apps.api.campaigns.engine_business_details import (
    RESUBMITTABLE,
    submit_business_details,
)
from apps.api.campaigns.engine_number_purchase import (
    PurchaseStep,
    purchase_engine_number,
    purchase_readiness,
    release_engine_number,
)
from apps.api.campaigns.number_catalog import NumberDirection
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_numbers import BusinessDetails
from apps.api.tenancy.engine_workspace import engine_has_workspaces

router = APIRouter(prefix="/v1/numbers/own", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]
NumberBuyer = Annotated[Principal, Depends(requires("org:manage"))]
NumberViewer = Annotated[Principal, Depends(requires("org:read"))]


def _off() -> ProblemError:
    return ProblemError.not_found("Number purchase")


class OwnNumbersStatusOut(BaseModel):
    """Where this account stands on the way to buying a number, in the screen's order."""

    model_config = ConfigDict(extra="forbid")

    #: False on a deployment where numbers are not bought here; every other field is empty.
    available: bool
    #: `workspace` (being set up), `verify_business`, `business_details`, `price`, `ready`.
    step: PurchaseStep | None
    blocker: str | None
    #: `pending`, `active`, `plan_limit`, `failed`, ... — `active` means set up.
    account_setup: str | None
    kyc_status: str | None
    #: The business-details application: `none`, `submitted`, `accepted`, `rejected`,
    #: `suspended`, `expired`, `draft` or `unknown`; None before anything was sent.
    business_status: str | None
    #: On a rejected application, what to correct.
    business_review_note: str | None
    business_submitted_at: datetime | None
    #: The details may be sent (again) now: verified business, application not live.
    can_send_business_details: bool
    #: What a number costs this account each month, in rupees, when numbers are on sale.
    inr_per_month: str | None


@router.get(
    "/status",
    response_model=OwnNumbersStatusOut,
    openapi_extra=permission_meta("org:read"),
    summary="Can this account buy a phone number yet, and what is the next step",
)
async def own_numbers_status(session: Session, principal: NumberViewer) -> OwnNumbersStatusOut:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        return OwnNumbersStatusOut(
            available=False,
            step=None,
            blocker=None,
            account_setup=None,
            kyc_status=None,
            business_status=None,
            business_review_note=None,
            business_submitted_at=None,
            can_send_business_details=False,
            inr_per_month=None,
        )
    readiness = await purchase_readiness(session, tenant_id=principal.tenant_id)
    from apps.api.tenancy.engine_workspace import read_workspace_state

    state = await read_workspace_state(session, principal.tenant_id)
    return OwnNumbersStatusOut(
        available=True,
        step=readiness.step,
        blocker=readiness.blocker,
        account_setup=readiness.workspace_status,
        kyc_status=readiness.kyc_status,
        business_status=readiness.business_status,
        business_review_note=readiness.business_review_note,
        business_submitted_at=state.business_submitted_at,
        can_send_business_details=(
            state.active
            and readiness.kyc_verified
            and (readiness.business_status is None or readiness.business_status in RESUBMITTABLE)
        ),
        inr_per_month=(
            str(readiness.client_inr_per_month)
            if readiness.client_inr_per_month is not None
            else None
        ),
    )


class BusinessDetailsSentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_status: str
    business_review_note: str | None


@router.post(
    "/business-details",
    response_model=BusinessDetailsSentOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Send the verified business details for phone numbers (again, after a rejection)",
    description=(
        "Sends the business's verified legal name, GST status and certificate, as recorded "
        "under Verify your business, for approval for phone numbers. Refused with "
        "`business_details_kyc_not_verified` until the business is verified. Approval "
        "usually takes a few minutes; read it from the status."
    ),
)
async def send_business_details(request: Request, principal: NumberBuyer) -> BusinessDetailsSentOut:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        raise _off()
    tenant_id = principal.tenant_id

    async def audit_sent(session: AsyncSession, details: BusinessDetails) -> None:
        await write_audit(
            session,
            action="numbers.business_details_sent",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"status": details.status},
        )

    details = await submit_business_details(tenant_id, audit=audit_sent)
    return BusinessDetailsSentOut(
        business_status=details.status, business_review_note=details.review_note
    )


class CityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    available: int


@router.get(
    "/cities",
    response_model=list[CityOut],
    openapi_extra=permission_meta("org:read"),
    summary="The cities numbers can be searched in",
)
async def own_number_cities(session: Session, principal: NumberViewer) -> list[CityOut]:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        raise _off()
    return [
        CityOut(name=c.name, available=c.available)
        for c in await engine_numbers.available_cities(session, principal.tenant_id)
    ]


class AvailableOwnNumberOut(BaseModel):
    """One number this account could buy, at OUR monthly price."""

    model_config = ConfigDict(extra="forbid")

    number: str
    e164: str
    city: str | None
    inr_per_month: str | None


class AvailableOwnNumbersOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbers: list[AvailableOwnNumberOut]
    #: Pass back as `cursor` for the next page; None when there are no more.
    next_cursor: str | None


@router.get(
    "/available",
    response_model=AvailableOwnNumbersOut,
    openapi_extra=permission_meta("org:read"),
    summary="Numbers this account could buy, a page at a time, at its monthly price",
)
async def own_numbers_available(
    session: Session,
    principal: NumberViewer,
    city: Annotated[str | None, Query(max_length=60)] = None,
    pattern: Annotated[str | None, Query(pattern=r"^\d{1,10}$")] = None,
    cursor: Annotated[str | None, Query(pattern=r"^\d{1,9}$")] = None,
) -> AvailableOwnNumbersOut:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        raise _off()
    readiness = await purchase_readiness(session, tenant_id=principal.tenant_id)
    page = await engine_numbers.search_available(
        session, principal.tenant_id, city=city, pattern=pattern, cursor=cursor
    )
    price = (
        str(readiness.client_inr_per_month) if readiness.client_inr_per_month is not None else None
    )
    return AvailableOwnNumbersOut(
        numbers=[
            AvailableOwnNumberOut(number=n.number, e164=n.e164, city=n.city, inr_per_month=price)
            for n in page.numbers
        ],
        next_cursor=page.next_cursor,
    )


class PurchaseOwnNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The number as the search listed it.
    number: str = Field(min_length=8, max_length=20, pattern=r"^\+?\d{8,15}$")
    agent_id: UUID | None = None
    direction: NumberDirection = "both"
    #: One per click of Buy, kept across retries of that click: a repeat buys one number.
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class PurchasedOwnNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    e164: str
    inr_per_month: str | None
    #: Whether the number now rings the chosen agent: `applied`/`unchanged` yes,
    #: `not_applicable` (no agent chosen), anything else means it needs attention.
    attachment: str
    replayed: bool
    #: What became of the first month: `charged` (from the wallet), `invoiced`, `trial`
    #: (free), `closed`, or `replayed` when an earlier click already bought it; null for an
    #: unpriced number. The screen words its sentence from this, so it never claims a charge
    #: that did not happen.
    first_period: RentalOutcome | None


@router.post(
    "/purchase",
    response_model=PurchasedOwnNumberOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Buy a number in this business's name — charges the first month now",
    description=(
        "Buys the number, charges this account's first month at the price the status shows, "
        "and points it at the chosen agent. Repeating the same `request_key` never buys a "
        "second number. Refused, with nothing charged, while the business is not verified "
        "or its details not approved, or if somebody else took the number."
    ),
)
async def purchase_own_number(
    payload: PurchaseOwnNumberIn, request: Request, principal: NumberBuyer
) -> PurchasedOwnNumberOut:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        raise _off()
    bought = await purchase_engine_number(
        tenant_id=principal.tenant_id,
        number=payload.number,
        agent_id=payload.agent_id,
        direction=payload.direction,
        idempotency_key=payload.request_key,
        requested_by="client",
    )
    if not bought.replayed:
        async with tenant_session(principal.tenant_id) as session:
            await write_audit(
                session,
                action="number.bought",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="phone_number",
                object_id=str(bought.number_id),
                ip=client_request_ip(request),
                summary={
                    "inr_per_month": str(bought.client_inr_per_month),
                    "attachment": bought.attachment,
                },
            )
    return PurchasedOwnNumberOut(
        number_id=bought.number_id,
        e164=bought.e164,
        inr_per_month=(
            str(bought.client_inr_per_month) if bought.client_inr_per_month is not None else None
        ),
        attachment=bought.attachment,
        replayed=bought.replayed,
        first_period=bought.first_period,
    )


class ReleaseOwnNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The client read the warning: releasing is permanent and this month is not refunded.
    confirm: Literal[True]


class ReleasedOwnNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    released: bool


@router.post(
    "/{number_id}/release",
    response_model=ReleasedOwnNumberOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Give a number up for good — no refund of this month",
    description=(
        "Releases the number permanently: it stops ringing at once, anybody may take it "
        "next, and the current month is not refunded. The monthly charge stops. Requires "
        "`confirm: true`. Releasing an already released number changes nothing."
    ),
)
async def release_own_number(
    number_id: UUID,
    payload: ReleaseOwnNumberIn,
    request: Request,
    principal: NumberBuyer,
) -> ReleasedOwnNumberOut:
    assert principal.tenant_id is not None
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(principal.tenant_id) as session:
        released = await release_engine_number(
            session, tenant_id=principal.tenant_id, number_id=number_id, by_admin=False
        )
        if released:
            await write_audit(
                session,
                action="number.released",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="phone_number",
                object_id=str(number_id),
                ip=client_request_ip(request),
                summary={"refunded": False},
            )
    return ReleasedOwnNumberOut(number_id=number_id, released=released)


__all__ = ["router"]
