"""The operator's surface for a phone number we BUY — search, buy, link, release (D-537).

**ITS OWN PREFIX, `/v1/admin/numbers`, RATHER THAN A PATH UNDER `admin_router`.** That
router owns `/v1/admin/tenants/{tenant_id}`, which would swallow a literal `/numbers`
segment on the search route — the same reason `holds_routes` and `operator_routes` have
their own prefixes. The tenant-scoped operations still carry the tenant in their path,
here, under this prefix.

**ADMIN REALM ONLY, AND THAT IS THE PRODUCT DECISION, NOT A PERMISSION DETAIL.** Buying a
number is Model A, and the playbook names "we provision the number for self-serve" as the
unsafe shape specifically (`docs/legal/LEGAL-OPS-PLAYBOOK.md:621`). What the founder
adopted is an operator-led supply arranged during onboarding, so the buy button exists in
exactly one console and a client token cannot reach it even holding the permission —
`realm="admin"` is a separate credential domain.

**EVERY ROUTE ASKS `assert_number_supply_authorized()` THROUGH THE SERVICE, INCLUDING
SEARCH.** The gate is the founder's own condition on this decision, sequenced rather than
waived: no written VNO/reseller status is recorded, so nothing here works yet, and it
refuses with a named problem rather than a 404. See `campaigns/provisioning.py`.

**THE AUDIT ROW IS PART OF THE OPERATION, NOT A DECORATION.** A purchase spends the
business's money on a recurring commitment and a release cancels a client's contact point;
both are written to `audit_log` in the same request, with the number's ROW id and never
its E.164 (hard rule 6).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.agents import service as agents_service
from apps.api.campaigns import number_supply
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine

router = APIRouter(prefix="/v1/admin/numbers", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `number_routes.py`.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
NumberOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class AvailableNumberOut(BaseModel):
    """One number the voice platform says it could sell us, at the price it said.

    **THE PRICE IS PUBLISHED IN USD, NOT RUPEES, AND THAT IS DELIBERATE.** It is the
    vendor's own quote in the vendor's own currency; the rupee is struck once, monthly,
    when the rental is metered, at that month's rate (`billing/number_rental.py`).
    Converting here would put a second exchange rate on a screen that would not match the
    ledger, and a screen that disagrees with the ledger about money is worse than one that
    shows the source figure.

    `monthly_price_usd` may be `None` — the vendor's row carried no readable price — and
    such a number CANNOT be bought: a number with no rental on file would never be metered.
    The screen says so rather than offering a button that refuses.
    """

    model_config = ConfigDict(extra="forbid")

    e164: str
    provider: str | None
    region: str | None
    locality: str | None
    monthly_price_usd: str | None


class BuyNumberIn(BaseModel):
    """The exact number to buy, and the quote the operator accepted for it.

    `monthly_price_usd` IS ECHOED BACK FROM THE SEARCH RESULT rather than re-fetched, and
    that is what makes the recurring cost real: the purchase response carries a one-off
    price and a renewal boolean and no recurring figure at all
    (`bolna-findings/mirror/pages/api-reference/phone-numbers/buy.md:78-135`). It is the
    operator's acceptance of a quoted price, which is also what an audit row should say.
    """

    model_config = ConfigDict(extra="forbid")

    e164: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")
    country: Literal["IN", "US"] = "IN"
    provider: str | None = Field(default=None, max_length=32)
    monthly_price_usd: Decimal = Field(gt=0, le=1000)
    agent_id: UUID | None = None
    purpose: str | None = Field(default=None, max_length=120)


class BoughtNumberOut(BaseModel):
    """What was bought, and what it will cost every month until it is given back."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    e164: str
    engine_number_ref: str
    provider: str | None
    purchase_price_usd: str | None
    monthly_rental_usd: str


class EngineRefIn(BaseModel):
    """The voice platform's own handle for a number we did NOT buy.

    NOT VALIDATED BEYOND BEING NON-BLANK, and that is documented at the adapter: the
    vendor's own pages type this field three different ways (a dashed uuid, bare hex, and
    a ULID-looking string), so a format check here would refuse the very value the vendor
    issued.
    """

    model_config = ConfigDict(extra="forbid")

    engine_number_ref: str = Field(min_length=1, max_length=200)


class EngineRefOut(BaseModel):
    """What linking the number achieved at the voice platform, right now."""

    model_config = ConfigDict(extra="forbid")

    engine_number_ref: str
    bound: int
    released: int
    failed: int
    unsupported: int


class TenantNumberCostOut(BaseModel):
    """One number and what it costs US — the admin-only view of a client's numbers.

    SEPARATE FROM `GET /v1/campaigns/numbers`, which a client also reads. Our cost of
    holding a number is not a figure a client is shown: whether the rental is absorbed,
    passed through at cost, or a priced add-on is a founder pricing decision that has not
    been taken (OPERATIONS §2 gate 26), and publishing our cost before it is taken would
    make the decision for them.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    e164: str
    series: str
    dlt_status: str
    provider: str | None
    #: Did WE buy it (Model A) or is it the client's own connection (Model B)?
    engine_owned: bool
    #: Is the voice platform able to answer this number at all? False is GAP-1's symptom:
    #: the publish will report success and the phone will not ring.
    engine_linked: bool
    monthly_rental_usd: str | None
    released: bool


@router.get(
    "/available",
    response_model=list[AvailableNumberOut],
    openapi_extra=permission_meta("admin:tenants"),
    summary="What the voice platform could sell us — read-only, spends nothing",
    description=(
        "Searches the voice platform's own inventory. Read-only: nothing is reserved and "
        "nothing is charged. Refused with `number_resale_not_authorized` until a written "
        "reseller authorisation is recorded for this deployment, and with "
        "`number_provisioning_not_configured` on a voice platform that sells no numbers. "
        "Prices are the vendor's own, in USD; the rupee is struck when the rental is "
        "metered, at that month's published rate."
    ),
)
async def available_numbers(
    _: NumberOperator,
    country: Literal["IN", "US"] = Query("IN"),
    pattern: str | None = Query(None, min_length=1, max_length=8),
    provider: str | None = Query(None, max_length=32),
    # BOUNDED HERE RATHER THAN AT THE VENDOR, because their search declares no page size
    # at all (`search.md:38-70`) — so the size of this response is decided by how much
    # inventory they happen to hold, which is exactly the "grows with somebody's data"
    # shape `check_list_bounds` exists to refuse. Trimming is honest: an operator picks
    # one number from a list, and a longer list does not make the choice better.
    limit: int = Query(50, ge=1, le=200),
) -> list[AvailableNumberOut]:
    offers = await number_supply.search_numbers(
        get_engine(), country=country, pattern=pattern, provider=provider
    )
    return [
        AvailableNumberOut(
            e164=offer.e164,
            provider=offer.provider,
            region=offer.region,
            locality=offer.locality,
            monthly_price_usd=(
                str(offer.monthly_price_usd) if offer.monthly_price_usd is not None else None
            ),
        )
        for offer in offers[:limit]
    ]


@router.post(
    "/tenants/{tenant_id}/buy",
    response_model=BoughtNumberOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Buy a number for this client — spends money, and is not retryable",
    description=(
        "Buys the named number at the voice platform and records it against this client. "
        "**This spends money and cannot be undone by retrying**: the vendor's purchase "
        "endpoint takes no idempotency key, so a repeat buys a second number and starts a "
        "second monthly rental. Refused with `number_taken` if the platform already holds "
        "the number, and with `number_series_not_purchasable` for a 140 or 160 series "
        "connection, which is taken on an Indian operator's own account and recorded here "
        "afterwards. The monthly rental is metered from the price accepted here."
    ),
)
async def buy_number(
    tenant_id: UUID,
    payload: BuyNumberIn,
    session: AdminSession,
    request: Request,
    principal: NumberOperator,
) -> BoughtNumberOut:
    """Buy, record and — if the number is attached to a live agent — route, in one request.

    The tenant is resolved before anything is spent: `service.tenant_exists` is the one
    definition of "is this a live organization", and an operator who mistyped a client id
    must not learn it from a vendor charge.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        bought = await number_supply.buy_number(
            scoped,
            get_engine(),
            tenant_id=tenant_id,
            e164=payload.e164,
            country=payload.country,
            provider=payload.provider,
            monthly_rental_usd=payload.monthly_price_usd,
            agent_id=payload.agent_id,
            purpose=payload.purpose,
        )
    await write_audit(
        session,
        action="number.bought",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(bought.number_id),
        ip=client_request_ip(request),
        # The recurring commitment and the vendor, never the number itself (hard rule 6).
        summary={
            "monthly_rental_usd": str(payload.monthly_price_usd),
            "provider": bought.provider,
        },
    )
    return BoughtNumberOut(
        id=bought.number_id,
        e164=bought.e164,
        engine_number_ref=bought.engine_number_ref,
        provider=bought.provider,
        purchase_price_usd=(
            str(bought.purchase_price_usd) if bought.purchase_price_usd is not None else None
        ),
        monthly_rental_usd=str(payload.monthly_price_usd),
    )


@router.post(
    "/tenants/{tenant_id}/{number_id}/engine-ref",
    response_model=EngineRefOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record the voice platform's handle for a number, and start it answering",
    description=(
        "Records the identifier the voice platform uses for a number the client brought "
        "on their own operator account, which is the one fact that lets an agent be set "
        "to answer it. Without it every publish of the agent answering this number "
        "reports success and the phone does not ring. If the number is attached to a live "
        "agent, the routing happens in this request rather than waiting for the next "
        "publish; the counts say what the voice platform was told."
    ),
)
async def set_engine_ref(
    tenant_id: UUID,
    number_id: UUID,
    payload: EngineRefIn,
    session: AdminSession,
    request: Request,
    principal: NumberOperator,
) -> EngineRefOut:
    async with tenant_session(tenant_id) as scoped:
        routing = await agents_service.set_number_engine_ref(
            scoped, number_id=number_id, engine_number_ref=payload.engine_number_ref
        )
    await write_audit(
        session,
        action="number.engine_ref_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={"bound": routing.bound, "failed": routing.failed},
    )
    return EngineRefOut(
        engine_number_ref=payload.engine_number_ref,
        bound=routing.bound,
        released=routing.released,
        failed=routing.failed,
        unsupported=routing.unsupported,
    )


@router.post(
    "/tenants/{tenant_id}/{number_id}/release",
    status_code=204,
    response_model=None,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Give a bought number back to the vendor and stop the monthly rental",
    description=(
        "Stops any agent answering the number, gives it back to the voice platform and "
        "stops the monthly charge. The record survives, marked released, because a closed "
        "month's costs still refer to it. Refused with `number_not_ours_to_release` for a "
        "connection the client holds in their own name — they cancel that with their own "
        "operator. Releasing an already-released number succeeds and changes nothing."
    ),
)
async def release_number(
    tenant_id: UUID,
    number_id: UUID,
    session: AdminSession,
    request: Request,
    principal: NumberOperator,
) -> None:
    async with tenant_session(tenant_id) as scoped:
        await number_supply.release_number(scoped, get_engine(), number_id=number_id)
    await write_audit(
        session,
        action="number.released",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={},
    )


_TENANT_NUMBERS = (
    "SELECT id, e164, series, dlt_status, provider, engine_owned, "
    "engine_number_ref IS NOT NULL, monthly_rental_usd, released_at IS NOT NULL "
    "FROM phone_numbers ORDER BY created_at, id LIMIT :limit"
)


@router.get(
    "/tenants/{tenant_id}",
    response_model=list[TenantNumberCostOut],
    openapi_extra=permission_meta("admin:tenants"),
    summary="This client's numbers, whether we bought them, and what each costs us",
)
async def tenant_numbers(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: NumberOperator,
    limit: int = Query(100, ge=1, le=500),
) -> list[TenantNumberCostOut]:
    """Read under the tenant's own RLS, so one client's numbers is exactly what comes back.

    THE LIMIT IS IN THE QUERY, not applied to a full result in Python: a client with a
    thousand numbers is not a realistic account, but "not realistic" is not a bound, and a
    trim after the fact still pays for the read (`check_list_bounds`'s whole subject).
    Released numbers are INCLUDED — a closed month's cost still refers to them, and an
    operator asking "what have we paid for this client" needs the ones we gave back.

    **AND IT RECORDS THE READ** (SEC-COMP §5, D-482 L-1). This is an admin-realm GET of one
    client's tenant-scoped rows OUTSIDE impersonation, which is exactly the shape that has
    to leave a trail: a client's telephone numbers are their business data, and "who looked
    at this account and when" is not answerable afterwards unless the read says so itself.
    Written LATE, in the same transaction, so the row and the read commit together.
    """
    async with tenant_session(tenant_id) as scoped:
        rows = (await scoped.execute(text(_TENANT_NUMBERS), {"limit": limit})).all()
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return [
        TenantNumberCostOut(
            id=row[0],
            e164=row[1],
            series=row[2],
            dlt_status=row[3],
            provider=row[4],
            engine_owned=row[5],
            engine_linked=row[6],
            monthly_rental_usd=str(row[7]) if row[7] is not None else None,
            released=row[8],
        )
        for row in rows
    ]


__all__ = ["router"]
