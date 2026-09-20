"""Browse, buy, assign — the client's own three operations on a phone number.

`campaigns/number_supply.py` is the vendor-facing half: it searches, spends, records and
releases, and every one of its operations already asks `assert_number_supply_authorized()`.
This module is the CLIENT-facing half, and it adds the four facts a client purchase needs
that an operator-led one does not:

1. **WHOSE CONNECTION IT IS** — `number_holder.py`. The registered owner is the client,
   collected once and immutable. It is what keeps this from being number resale.
2. **WHAT THEY PAY** — `number_pricing.py`, an operator attestation in rupees. The
   vendor's USD quote is OUR cost and never becomes a client-facing figure (hard rule 7).
3. **WHETHER THEY CAN AFFORD IT** — the wallet, read before anything is spent, so a
   purchase refuses cleanly instead of part-completing.
4. **WHETHER THE HOLDER IS VERIFIED** — which gates ACTIVATION, not the purchase. A
   number can be bought before KYC clears; it cannot be bound to an agent until it does,
   and binding is the only thing that puts a number on a handset (D-420). So an
   unverified holder cannot place a call, which is the constraint that actually matters,
   without a purchase screen that refuses people who are trying to pay us.

**THE LEGAL GATE IS ASKED FIRST ON EVERY OPERATION AND IS NOT WEAKENED HERE.**
`Settings.number_resale_authorization` is unset, so browse and buy both refuse today with
`number_resale_not_authorized`. Nothing in this module can clear it: it is a written
instrument an operator records, the founder's own condition on D-537, sequenced rather
than waived (`campaigns/provisioning.py`). What this module does is make the flow work the
day that reference exists.

**`direction` IS A PURCHASE INTENT AND IS NOT A COMPLIANCE ANSWER.** A client buys a
number for inbound, outbound or both, and that is recorded. What the number may LAWFULLY
carry is decided elsewhere and stays decided elsewhere:
`campaigns.service.SERIES_FOR_CLASSIFICATION` allows only 140 and 160 for commercial voice,
and an ordinary DID reaches service/transactional dialling only through a client's own
attestation in `campaigns/sender_attestation.py`. Nothing here widens either. A client who
buys a `standard` number "for outbound" gets exactly the same refusal at launch as before,
which is the point: a purchase intent that could authorise a call would be a second,
disagreeing answer to a question those two modules already answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine import AvailableNumber, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.models import NUMBER_DIRECTIONS, series_for_e164
from apps.api.agents.service import InboundRouting
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import get_balance
from apps.api.campaigns import number_supply
from apps.api.campaigns.number_holder import HolderIdentity, require_holder
from apps.api.campaigns.number_pricing import AttestedNumberPrice, require_attested_price_inr
from apps.api.campaigns.provisioning import (
    NOT_ACTIVATED_RULE,
    PURCHASABLE_SERIES,
    assert_holder_verified_for_activation,
    assert_number_supply_authorized,
)
from apps.api.compliance.kyc import read_kyc
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

NumberDirection = Literal["inbound", "outbound", "both"]

#: Refused because the wallet cannot cover the first month.
NO_CREDIT_RULE: Final = "number_insufficient_credit"


@dataclass(frozen=True, slots=True)
class OfferedNumber:
    """One number a client could buy, at the price THEY would pay.

    **NO VENDOR FIGURE ON THIS OBJECT AT ALL.** `AvailableNumber.monthly_price_usd` is
    what Calevate is charged and is on the operator's screen only
    (`/v1/admin/numbers/available`); a client's screen carries the attested rupee price or
    nothing. Two currencies on one purchase screen is how a client ends up quoting our
    cost back to us as their price.
    """

    e164: str
    region: str | None
    locality: str | None
    series: str
    inr_per_month: Decimal


@dataclass(frozen=True, slots=True)
class PurchasedNumber:
    """What the client now holds, and what it will cost them every month."""

    number_id: UUID
    e164: str
    series: str
    direction: NumberDirection
    inr_per_month: Decimal
    activated: bool
    holder: HolderIdentity


async def browse_numbers(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    country: str = "IN",
    pattern: str | None = None,
    limit: int = 50,
) -> list[OfferedNumber]:
    """What a client could buy, priced in rupees. Read-only; spends nothing; still gated.

    NO KYC CHECK. Seeing what is available is not a transaction, and refusing to show a
    catalogue to a client who has not yet sent us documents teaches them the product does
    not work rather than what they have to do. The purchase is where verification matters,
    and even there it gates ACTIVATION rather than the sale.

    Offers the engine returns that are not an ordinary DID are DROPPED rather than shown
    and then refused at the buy: `PURCHASABLE_SERIES` is the only class this product can
    buy, because 140 and 160 are taken on an Indian operator's own account against a
    registered Principal Entity (`number_supply.buy_number` refuses them by name).
    """
    assert_number_supply_authorized()
    price = await require_attested_price_inr(session)
    offers: list[AvailableNumber] = await number_supply.search_numbers(
        engine, country=country, pattern=pattern, provider=None
    )
    out: list[OfferedNumber] = []
    for offer in offers:
        series = series_for_e164(offer.e164) or PURCHASABLE_SERIES
        if series != PURCHASABLE_SERIES:
            continue
        # A NUMBER THE VENDOR PUT NO PRICE ON IS NOT OFFERED. `buy_number` refuses one
        # with `number_rental_price_unknown` — a number with no rental on file would never
        # be metered — so listing it would be a button that cannot work.
        if offer.monthly_price_usd is None:
            continue
        out.append(
            OfferedNumber(
                e164=offer.e164,
                region=offer.region,
                locality=offer.locality,
                series=series,
                inr_per_month=price.inr_per_month,
            )
        )
        if len(out) >= limit:
            break
    return out


async def _vendor_quote_for(
    engine: VoiceEngine, *, e164: str, country: str, pattern: str | None
) -> AvailableNumber:
    """The vendor's own offer for exactly this number, looked up rather than accepted.

    **THE CLIENT NEVER SENDS US A PRICE.** The operator's route echoes the quote back from
    the search it ran, which is right for an operator accepting a cost on the business's
    behalf; a client sending one would be a client deciding what Calevate pays. So the
    number is re-found in the vendor's own inventory here, and a number that is no longer
    in it is refused before any money moves — which is also the freshest possible answer to
    "is this still available", asked at the only moment it matters.

    `pattern` is THE ONE THE CLIENT BROWSED WITH, echoed back, not one derived from the
    number: the vendor's filter is a 3-character prefix (VERIFIED-VENDOR-DOCS:
    `bolna-findings/mirror/pages/api-reference/phone-numbers/search.md:44-50`) and a
    search built from different terms is a different page of inventory, so the lookup has
    to ask the question the client answered rather than a similar one.
    """
    offers = await number_supply.search_numbers(
        engine, country=country, pattern=pattern, provider=None
    )
    for offer in offers:
        if offer.e164 == e164 and offer.monthly_price_usd is not None:
            return offer
    raise ProblemError.conflict(
        "number_no_longer_available",
        "That number is no longer available.",
        remediation="Search again and pick another number — nothing has been charged.",
    )


_TIER_SQL = "SELECT plan_tier FROM organizations LIMIT 1"


async def _assert_can_afford(session: AsyncSession, *, tenant_id: UUID, amount: Decimal) -> None:
    """Refuse a purchase the wallet cannot cover, BEFORE the vendor is called.

    ONLY FOR A PREPAID ACCOUNT. A managed client is invoiced against a retainer and has no
    wallet, so a balance test would refuse them for a number they are not paying from —
    the reasoning `wallet.read_wallet` gives for taking `prepaid` as an argument rather
    than deriving it. `PREPAID_TIERS` rather than the literal tiers, because that tuple is
    the one place the motion is named.

    It is a PRE-CHECK, not a hold. The wallet is not debited here: a number's rental is
    metered monthly by `billing/number_rental.py`, so there is nothing to reserve and a
    reservation would be a second money path for one charge. What this prevents is the
    part-completed purchase — a vendor charged, a rental started, and a client with no
    credit to meet the first month of it.
    """
    tier = (await session.execute(text(_TIER_SQL))).scalar()
    if str(tier) not in PREPAID_TIERS:
        return
    balance = await get_balance(session, tenant_id=tenant_id)
    if balance.amount_inr >= amount:
        return
    raise ProblemError.business_rule(
        NO_CREDIT_RULE,
        f"There is not enough credit on this account to cover this number's first month "
        f"(₹{amount}).",
        remediation="Top up, then come back and buy the number. Nothing has been charged.",
    )


async def purchase_number(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    e164: str,
    country: str = "IN",
    pattern: str | None = None,
    direction: NumberDirection = "inbound",
) -> PurchasedNumber:
    """Buy `e164` for this client. **Irreversible once `number_supply.buy_number` returns.**

    THE ORDER IS EVERY REFUSAL THAT COSTS NOTHING, THEN THE ONE THING THAT COSTS MONEY,
    and each step is ordered by whose problem it is:

    1. our legal state — no written reseller authorisation refuses everyone, so asking a
       client for paperwork first would waste their time on a blocker they cannot clear;
    2. our price — an unattested rate means we cannot quote, which is also ours;
    3. their holder identity — the first thing they can actually do;
    4. their credit — checked before the vendor, never after;
    5. the vendor's own current quote;
    6. the purchase, which `number_supply.buy_number` performs under an advisory lock with
       its own carrier-application gate, series check and not-retryable alarm.

    The row is then completed in the SAME transaction as the INSERT, so a number cannot
    exist with no direction and no price: `agents/service.provision_number` writes the row
    and does not know about either column.
    """
    assert_number_supply_authorized()
    price = await require_attested_price_inr(session)
    holder = await require_holder(session)
    await _assert_can_afford(session, tenant_id=tenant_id, amount=price.inr_per_month)
    quote = await _vendor_quote_for(engine, e164=e164, country=country, pattern=pattern)

    # VERIFIED HOLDERS GET A USABLE NUMBER IMMEDIATELY; everyone else gets one that cannot
    # be bound to an agent until they are verified. Read here rather than at the attach so
    # the purchase response can tell them which of the two they have.
    verified = (await read_kyc(session, tenant_id=tenant_id)).is_verified

    bought = await number_supply.buy_number(
        session,
        engine,
        tenant_id=tenant_id,
        e164=e164,
        country=country,
        provider=quote.provider,
        monthly_rental_usd=quote.monthly_price_usd,
        # NOT BOUND AT PURCHASE. Binding is what puts a number on a handset, so it is its
        # own deliberate act with its own activation gate (`assign_number_to_agent`).
        agent_id=None,
        purpose=None,
    )
    await session.execute(
        text(
            "UPDATE phone_numbers SET direction = :dir, client_inr_per_month = :inr, "
            "activated_at = CASE WHEN :verified THEN now() ELSE NULL END, "
            "updated_at = now() WHERE id = :id"
        ),
        {
            "dir": direction,
            "inr": price.inr_per_month,
            "verified": verified,
            "id": bought.number_id,
        },
    )
    log.info(
        "client_number_purchased",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(bought.number_id),
            "direction": direction,
            "activated": verified,
        },
    )
    return PurchasedNumber(
        number_id=bought.number_id,
        e164=bought.e164,
        series=series_for_e164(bought.e164) or PURCHASABLE_SERIES,
        direction=direction,
        inr_per_month=price.inr_per_month,
        activated=verified,
        holder=holder,
    )


_NUMBER_STATE = "SELECT activated_at, released_at FROM phone_numbers WHERE id = :nid FOR UPDATE"


async def assign_number_to_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    agent_id: UUID | None,
    direction: NumberDirection | None = None,
) -> InboundRouting:
    """Point a number at an agent — the act that makes every other gate mean something.

    **THIS IS THE ACTIVATION GATE, AND IT IS HERE BECAUSE THIS IS THE DOOR.** The outbound
    caller ID and the inbound answer are both resolved from `phone_numbers.agent_id`
    (D-420), so a number bound to nothing cannot reach a handset in either direction. An
    unverified holder's number is therefore stopped by refusing this one operation, rather
    than by a flag each dial path has to remember to read.

    It activates rather than merely checking: the holder may have been verified since the
    purchase, and a number that stayed unusable until somebody ran a second job would be a
    seam nobody comes back for. The write is under `FOR UPDATE` on the row, so two tabs
    cannot both decide.

    `agent_id=None` DETACHES, and is deliberately not gated on activation: taking a number
    off an agent is the safe direction, and refusing it would trap a client whose
    verification lapsed with a live binding they cannot remove.

    Every refusal about the AGENT — a neighbour's id, an archived agent, an agent that does
    not answer inbound — belongs to `agents/service.attach_number_to_agent` and is not
    re-implemented here (one way per problem).
    """
    row = (await session.execute(text(_NUMBER_STATE), {"nid": number_id})).first()
    if row is None:
        raise ProblemError.not_found("Number")
    activated_at, released_at = row
    if agent_id is not None and released_at is None and activated_at is None:
        # RAISES on an unverified holder, in `provisioning.py` where the other two gates
        # live, so the three refusals a client can meet on a number are written once each.
        await assert_holder_verified_for_activation(session, tenant_id=tenant_id)
        await session.execute(
            text(
                "UPDATE phone_numbers SET activated_at = now(), updated_at = now() "
                "WHERE id = :nid AND activated_at IS NULL"
            ),
            {"nid": number_id},
        )
    if direction is not None:
        assert direction in NUMBER_DIRECTIONS
        await session.execute(
            text("UPDATE phone_numbers SET direction = :dir, updated_at = now() WHERE id = :nid"),
            {"dir": direction, "nid": number_id},
        )
    return await agents_service.attach_number_to_agent(
        session, number_id=number_id, agent_id=agent_id
    )


__all__ = [
    "NOT_ACTIVATED_RULE",
    "NO_CREDIT_RULE",
    "AttestedNumberPrice",
    "NumberDirection",
    "OfferedNumber",
    "PurchasedNumber",
    "assign_number_to_agent",
    "browse_numbers",
    "purchase_number",
]
