"""The client's own surface for a phone number: browse, buy, assign.

**WHAT CHANGED AND WHAT DID NOT.** This route group used to be one endpoint that always
refused, because Model A's supply was operator-led only. A client may now browse Indian
numbers, buy one and point it at an agent — and **nothing about the two things standing in
front of that has been weakened**:

* `Settings.number_resale_authorization` is UNSET, so every route here answers
  `number_purchase_is_operator_led` today, exactly as it did before. That refusal is the
  founder's own condition on D-537, sequenced rather than waived
  (`docs/legal/LEGAL-OPS-PLAYBOOK.md:621` names the written VNO/reseller status as the
  thing that has to exist first). The flow below is built so that recording that
  instrument is the ONLY change needed to make it work.
* The client-facing sentence is the SAME whichever of our gates is closed, so the shape of
  an error still publishes nothing about our paperwork. `self_serve_purchase_refused()`
  holds it; `provisioning.provisioning_not_configured` holds the operator's version, which
  is logged and never returned.

**KYC GATES ACTIVATION, NOT THE SALE.** A number may be bought before the holder is
verified; it cannot be given to an agent until they are, and binding to an agent is the
only thing that puts a number on a handset in either direction (D-420). So an unverified
holder cannot place or take a call, which is the constraint that matters, without a
purchase screen that refuses people trying to pay us. `campaigns/number_catalog.py` argues
it and `number_not_activated` is its own named refusal, distinct from the dial gate's KYC
blockers so an operator can tell the two apart.

**THE HOLDER IS ASKED ONCE.** Who the connection is registered to belongs to the tenant,
not to the purchase, and is immutable at the database (`campaigns/number_holder.py`).

`org:manage` throughout: this is the shape of a request that spends money and accepts a
registration in the client's own name.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import number_catalog
from apps.api.campaigns.number_holder import read_holder, record_holder
from apps.api.campaigns.provisioning import (
    number_purchase_available,
    self_serve_purchase_refused,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

router = APIRouter(prefix="/v1/numbers", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` alias rather than a `Depends(...)` default: B008 is waived only for
# `**/routes.py` and this module is `provisioning_routes.py`.
NumberBuyer = Annotated[Principal, Depends(requires("org:manage"))]

# READING the number screens is a READ. Support impersonating a client is deliberately
# read-only (D-22), so a GET gated on a mutating permission is a screen that support
# cannot see while the client is on the phone asking about it — which is the whole point
# of impersonation. Buying and assigning still take `org:manage` below.
NumberViewer = Annotated[Principal, Depends(requires("org:read"))]

PURCHASE_ROUTE = "/v1/numbers/purchase"


def _assert_supply_open() -> None:
    """The client-facing gate, asked before anything reads the database.

    ONE SENTENCE FOR EVERY CLOSED GATE. Whether this deployment's engine sells numbers and
    whether we hold a written reseller authorisation are different facts, and both are
    OURS; a client who learnt which of them was missing would learn our legal state from
    the shape of an error. The operator's version of the distinction is logged by
    `provisioning.provisioning_not_configured` and is never returned here.
    """
    if not number_purchase_available():
        raise self_serve_purchase_refused()


class HolderIn(BaseModel):
    """Who every number on this account will be registered to. Asked once, ever.

    `holder_email` is an `EmailStr` because the operator sends the registration
    confirmation to it: an address that does not parse is a registration that silently
    never completes.
    """

    model_config = ConfigDict(extra="forbid")

    holder_type: Literal["individual", "business"]
    holder_name: str = Field(min_length=2, max_length=200)
    holder_email: EmailStr


class HolderOut(BaseModel):
    """The recorded holder, or `recorded: false` before there is one."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    holder_type: Literal["individual", "business"] | None = None
    holder_name: str | None = None
    holder_email: str | None = None


class OfferedNumberOut(BaseModel):
    """One number a client could buy, at the price they would pay.

    **RUPEES, AND NOT THE VENDOR'S DOLLARS.** What Calevate is charged is on the operator's
    screen only (`/v1/admin/numbers/available`). This figure is the rate an operator
    attested; a client's purchase screen carrying our cost would invite them to quote it
    back as their price. A string rather than a float, like every other money field on this
    API (hard rule 7).
    """

    model_config = ConfigDict(extra="forbid")

    e164: str
    region: str | None
    locality: str | None
    #: Always `standard` today — an ordinary DID. 140 and 160 are taken on an Indian
    #: operator's own account against a registered Principal Entity and are never sold
    #: here, so they are filtered out of the catalogue rather than refused at the buy.
    series: str
    inr_per_month: str


class PurchaseIn(BaseModel):
    """Exactly the number the client picked, and what they want it for.

    **NO PRICE FIELD.** The client does not tell us what Calevate pays; the vendor's quote
    is looked up again at purchase time, which is also the freshest possible answer to
    "is this still available".

    **NO `series` FIELD EITHER, AND ITS ABSENCE IS A FIX.** It used to be asked and then
    trusted; the series is derived from the number's own prefix by `series_for_e164`,
    because an operator's typed word opened promotional dialling from a number that was
    not a telemarketing header.
    """

    model_config = ConfigDict(extra="forbid")

    e164: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")
    country: Literal["IN"] = "IN"
    #: The `pattern` the client browsed with, echoed back. The vendor's search is a
    #: prefix filter over live inventory, so the quote is re-read from the SAME search the
    #: client picked from; a number that is no longer in it is refused before any money
    #: moves, which is also the freshest answer to "is this still available".
    search_pattern: str | None = Field(default=None, min_length=1, max_length=3)
    #: What the number is FOR. It records an intent and authorises nothing: what a number
    #: may lawfully carry is `campaigns.service.SERIES_FOR_CLASSIFICATION` and, for an
    #: ordinary DID, the client's own confirmation in `campaigns/sender_attestation.py`.
    direction: Literal["inbound", "outbound", "both"] = "inbound"


class PurchasedNumberOut(BaseModel):
    """What the client now holds, what it costs them, and whether it can be used yet."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    e164: str
    series: str
    direction: Literal["inbound", "outbound", "both"]
    inr_per_month: str
    #: False while the holder's identity is unverified. The number is theirs and is being
    #: held; it cannot be given to an agent — and therefore cannot ring — until then.
    activated: bool


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
    summary="Who this account's numbers are registered to — recorded once, then fixed",
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
    "/holder",
    response_model=HolderOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Record who this account's numbers are registered to — once, and not editable",
    description=(
        "Records the person or business every number on this account will be registered "
        "to. It is asked once and reused for every number after that, and it cannot be "
        "changed afterwards: the operator who issues the connection holds the same "
        "details, and a record of ours that no longer matches theirs would name the wrong "
        "owner. A second attempt is refused with `number_holder_already_recorded`."
    ),
)
async def put_holder(
    payload: HolderIn,
    session: Session,
    request: Request,
    principal: NumberBuyer,
) -> HolderOut:
    assert principal.tenant_id is not None
    assert principal.user_id is not None
    holder = await record_holder(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        holder_type=payload.holder_type,
        holder_name=payload.holder_name,
        holder_email=str(payload.holder_email),
    )
    await write_audit(
        session,
        action="number.holder_recorded",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="number_holder",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        # The TYPE, never the name or the email: the summary is read by operators who have
        # no business reading a client's registrant details out of an audit trail.
        summary={"holder_type": payload.holder_type},
    )
    return HolderOut(
        recorded=True,
        holder_type=holder.holder_type,
        holder_name=holder.holder_name,
        holder_email=holder.holder_email,
    )


@router.get(
    "/available",
    response_model=list[OfferedNumberOut],
    openapi_extra=permission_meta("org:read"),
    summary="Indian numbers this account could buy, priced in rupees",
    description=(
        "Searches the voice platform's inventory and prices each number at the rate an "
        "operator has attested. Read-only: nothing is reserved and nothing is charged. "
        "Refused with `number_purchase_is_operator_led` while this deployment may not "
        "supply numbers, and with `number_price_not_attested` until a monthly price has "
        "been set. Identity verification is NOT required to look."
    ),
)
async def available_numbers(
    session: Session,
    _: NumberViewer,
    pattern: str | None = Query(None, min_length=1, max_length=3),
    # BOUNDED HERE because the vendor's search declares no page size at all
    # (`bolna-findings/mirror/pages/api-reference/phone-numbers/search.md:38-70`), so the
    # length of the response is otherwise decided by how much inventory they hold.
    limit: int = Query(50, ge=1, le=200),
) -> list[OfferedNumberOut]:
    _assert_supply_open()
    offers = await number_catalog.browse_numbers(
        session, get_engine(), country="IN", pattern=pattern, limit=limit
    )
    return [
        OfferedNumberOut(
            e164=offer.e164,
            region=offer.region,
            locality=offer.locality,
            series=offer.series,
            inr_per_month=str(offer.inr_per_month),
        )
        for offer in offers
    ]


@router.post(
    "/purchase",
    response_model=PurchasedNumberOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Buy one of the available numbers — idempotent, and not retryable at the vendor",
    description=(
        "Buys the named number and records it against this account. **An "
        "`Idempotency-Key` header is required**: the voice platform's purchase endpoint "
        "takes no key of its own, so a repeat without one would buy a second number and "
        "start a second monthly rental. A repeat WITH the same key is answered with the "
        "first purchase.\n\n"
        "Refused with `number_purchase_is_operator_led` while this deployment may not "
        "supply numbers, `number_holder_not_recorded` until the registrant's details are "
        "on file, `number_price_not_attested` until a monthly price is set, "
        "`number_insufficient_credit` when the wallet cannot cover the first month, and "
        "`number_taken` if the number has already gone. Identity verification is not "
        "required to buy: an unverified account's number arrives inactive and cannot be "
        "given to an agent until the verification clears."
    ),
)
async def purchase_number(
    payload: PurchaseIn,
    request: Request,
    principal: NumberBuyer,
) -> PurchasedNumberOut:
    """Claim the key, buy, record the answer — three transactions, in that order.

    **THE CLAIM COMMITS BEFORE THE VENDOR IS CALLED**, in its own transaction, which is
    `POST /v1/calls/{call_id}/assist`'s shape and exists for the same reason: written into
    the request's transaction it would be rolled back by `core/deps.db` on any later
    exception, so a retry with the key that exists to prevent a second purchase would make
    one.

    **THE `try` STOPS WHERE THE MONEY IS SPENT.** Every refusal above `purchase_number` —
    a closed gate, no holder, no price, no credit — releases the key, so a client who was
    told to top up can reuse the key they were just refused on. Once
    `number_catalog.purchase_number` returns, the vendor has been paid and the claim is
    kept whatever happens next: that half is the mechanism working, and
    `number_supply.buy_number` alarms rather than swallowing if our own row then fails.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    _assert_supply_open()

    idem_key = request.headers.get("Idempotency-Key")
    if not idem_key:
        raise ProblemError(
            kind="validation",
            status=400,
            code="idempotency_key_required",
            title="Buying a number needs an Idempotency-Key",
            detail=(
                "Buying a number spends money and starts a monthly rental, so every "
                "attempt names itself and a repeat of the same attempt is answered "
                "rather than bought again."
            ),
            remediation="Send an `Idempotency-Key` header — one fresh value per attempt.",
        )
    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=PURCHASE_ROUTE,
            method="POST",
            key=idem_key,
            request_hash=body_hash(payload.model_dump(mode="json")),
        )
    if claim.state == "replay" and claim.response_payload:
        return PurchasedNumberOut.model_validate(claim.response_payload)

    try:
        async with tenant_session(tenant_id) as buy_session:
            bought = await number_catalog.purchase_number(
                buy_session,
                get_engine(),
                tenant_id=tenant_id,
                e164=payload.e164,
                country=payload.country,
                pattern=payload.search_pattern,
                direction=payload.direction,
            )
    except Exception:
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, record_id=claim.record_id)
        raise

    out = PurchasedNumberOut(
        id=bought.number_id,
        e164=bought.e164,
        series=bought.series,
        direction=bought.direction,
        inr_per_month=str(bought.inr_per_month),
        activated=bought.activated,
    )
    # THE AUDIT AND THE CLAIM'S COMPLETION IN ONE TRANSACTION OF THEIR OWN — the record of
    # a purchase that has already happened, deliberately not the request's transaction,
    # which is the one that rolls back.
    async with tenant_session(tenant_id) as record_session:
        await write_audit(
            record_session,
            action="number.purchased",
            actor=principal,
            tenant_id=tenant_id,
            object_type="phone_number",
            object_id=str(bought.number_id),
            ip=client_request_ip(request),
            # The commitment and the intent, never the E.164 (hard rule 6).
            summary={
                "inr_per_month": str(bought.inr_per_month),
                "direction": bought.direction,
                "activated": bought.activated,
            },
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=201,
            response_payload=out.model_dump(mode="json"),
        )
    return out


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
        "holder's identity is unverified — the number is held, not lost — and with "
        "`agent_does_not_answer_inbound` for an outbound-only agent. Detaching "
        "(`agent_id: null`) is always allowed. The counts say what the platform was told, "
        "so a binding that failed is not reported as one that worked."
    ),
)
async def assign_number(
    number_id: UUID,
    payload: AssignIn,
    session: Session,
    request: Request,
    principal: NumberBuyer,
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
