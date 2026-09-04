"""Buying, releasing and reconciling a number at the voice engine (D-537).

**THE ONLY MODULE IN THIS SYSTEM THAT SPENDS MONEY AT A VENDOR ON PURPOSE.** Everything
else here bills for work that already happened; this asks a vendor to charge us, now, for
an asset that will keep charging us every month until somebody gives it back. So it is
short, it has one caller per operation, and every irreversible step is preceded by the
check that would have made it unnecessary.

THE FOUR OPERATIONS, AND THE ORDER THEY MUST HAPPEN IN
------------------------------------------------------
    search  -> what could we buy (read-only, spends nothing)
    buy     -> POST /phone-numbers/buy, then one row, in that order
    bind    -> `agents/service.route_inbound_numbers`, already built, unchanged
    release -> unbind at the engine, DELETE at the engine, mark the row

**BUY IS NOT IDEMPOTENT AND CANNOT BE MADE SO.** The vendor's endpoint takes no
client-supplied key, so a retry buys a SECOND number and starts a SECOND rental. Three
things stand in front of that, in increasing order of how much they cost:

1. an advisory lock on the E.164 being bought, so two operators clicking at once
   serialize rather than both spending;
2. a read of `phone_numbers` under that lock — the number is globally UNIQUE there, so a
   number we already hold is refused before any vendor call;
3. and if the vendor charges us and our own INSERT then fails, the money is spent and the
   row is not written. That state is not recoverable inside a transaction, so it is
   ALARMED with the vendor's handle rather than swallowed, and
   `workers/number_rental.py::reconcile_engine_numbers` finds it again. Retrying is the
   one thing that must not happen, and the alarm says so.

**A RELEASE IS NOT WHAT HAPPENS WHEN AN AGENT IS DELETED, AND THAT IS DELIBERATE.**
`agents/lifecycle.py` releases an archived agent's numbers in the sense of UNBINDING them
at the engine (D-527), which is the property that matters — nothing of ours answers the
phone. It does NOT give the number back to the vendor, because the number belongs to the
TENANT and is routinely re-pointed at their next agent; deleting it on an agent's archival
would destroy a client's published contact point on an internal housekeeping action, and
Indian numbers are not reissued to the same holder on request. Giving it back is an
explicit offboarding act with its own route, its own audit row and its own confirmation.
What stops a paid asset being forgotten is not the delete path — it is the reconciliation
sweep, which alarms on a bought, unreleased number attached to no agent.

WHAT IS GATED AND WHAT IS NOT
------------------------------
Every operation here calls `assert_number_supply_authorized()` — including SEARCH, which
spends nothing. A search screen that works beside a buy button that refuses teaches an
operator that the gate is a glitch, and the gate is not a glitch: it is the founder's own
condition on this decision, sequenced rather than waived (`campaigns/provisioning.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from calevate_shared.engine import (
    AvailableNumber,
    NumberSearch,
    NumberSpec,
    ProvisionedNumber,
    VoiceEngine,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.models import series_for_e164
from apps.api.campaigns.provisioning import (
    PURCHASABLE_SERIES,
    assert_number_supply_authorized,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BoughtNumber:
    """What a purchase produced: a row of ours, and the vendor's own facts about it."""

    number_id: UUID
    e164: str
    engine_number_ref: str
    provider: str | None
    purchase_price_usd: Decimal | None
    monthly_rental_usd: Decimal | None


async def search_numbers(
    engine: VoiceEngine, *, country: str, pattern: str | None, provider: str | None
) -> list[AvailableNumber]:
    """What the engine says it could sell us. Read-only; spends nothing; still gated.

    The country is narrowed to the engine's own two-value enum by `NumberSearch`, so an
    operator asking for a country this vendor does not serve gets a 422 naming the field
    rather than a vendor 400 naming nothing.
    """
    assert_number_supply_authorized()
    query = NumberSearch.model_validate(
        {"country": country, "pattern": pattern, "provider": provider}
    )
    offers = list(await engine.search_numbers(query))
    log.info(
        "number_search",
        extra={"country": query.country, "provider": query.provider, "offers": len(offers)},
    )
    return offers


async def buy_number(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    e164: str,
    country: str,
    provider: str | None,
    monthly_rental_usd: Decimal | None,
    agent_id: UUID | None,
    purpose: str | None,
) -> BoughtNumber:
    """Buy `e164` for this tenant, then record it. **Irreversible at step two.**

    `monthly_rental_usd` COMES FROM THE SEARCH RESULT THE OPERATOR ACCEPTED, not from the
    purchase: the buy response carries a one-off `price` and a `renewal` boolean and no
    recurring figure at all (`buy.md:78-135`). Passing it in is how the recurring cost gets
    a value at all, and a purchase without one is refused rather than recorded — a number
    with no rental on file is a number the monthly meter will silently skip for ever, which
    is precisely the leak this whole decision had to close.

    THE SERIES IS READ OUT OF THE NUMBER, NEVER ASSERTED. `series_for_e164` is the same
    authority `agents/service.provision_number` uses, and a bought number whose own prefix
    makes it a 140 or a 160 is REFUSED: this product does not claim a DLT class it cannot
    show the vendor can issue, and a misclassified header is the ₹2/₹5/₹10 lakh ladder
    under the 2025 TCCCPR amendments.
    """
    assert_number_supply_authorized()
    if monthly_rental_usd is None or monthly_rental_usd <= 0:
        raise ProblemError.business_rule(
            "number_rental_price_unknown",
            "This number cannot be bought because its monthly rental price is not known.",
            remediation=(
                "Search again and buy a number the search returned a price for. A number "
                "with no rental on file would never be billed and its cost would go "
                "unmeasured."
            ),
        )
    declared = series_for_e164(e164)
    if declared is not None and declared != PURCHASABLE_SERIES:
        raise ProblemError.business_rule(
            "number_series_not_purchasable",
            f"This number's own prefix makes it a {declared}-series connection, which "
            "cannot be bought through the voice platform.",
            remediation=(
                "The 140 and 160 series are taken on an Indian operator's own account "
                "against a registered Principal Entity, and recorded here afterwards. "
                "Buy an ordinary number for answering incoming calls."
            ),
        )
    # SERIALIZE ON THE NUMBER, and hold it across the vendor call. That is a lock held
    # across a vendor request, which BACKEND-PATTERNS §5 refuses as a general shape — and
    # this is the exception it names: the resource being protected IS the vendor-side
    # purchase, the alternative is two operators buying the same number twice, and there
    # is no second key to reconcile on afterwards. The key is the E.164, not the tenant:
    # two tenants racing for one number is the collision that matters.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"number-buy:{e164}"},
    )
    # UNDER THE LOCK, and against the globally UNIQUE column rather than this tenant's
    # rows: RLS hides another tenant's number, so a scoped probe would report "available"
    # for exactly the number that is not. `count(*)` on a unique column is the database's
    # answer, not the session's — the same reasoning `provision_number` gives for letting
    # the constraint be the authority.
    held = (
        await session.execute(text("SELECT 1 FROM phone_numbers WHERE e164 = :e"), {"e": e164})
    ).first()
    if held is not None:
        raise ProblemError.conflict(
            "number_taken",
            "This number is already recorded against an account.",
            remediation=(
                "Numbers are unique across the platform. Check which account already "
                "holds this connection before buying it again."
            ),
        )
    bought: ProvisionedNumber = await engine.provision_number(
        NumberSpec(
            series=PURCHASABLE_SERIES,
            country=country,  # type: ignore[arg-type]
            e164=e164,
            provider=provider,
            purpose=purpose,
        )
    )
    ref = bought.engine_number_ref
    if ref is None:  # pragma: no cover - the adapter refuses before returning
        raise ProblemError(
            kind="dependency",
            code="engine_number_purchase_unusable",
            title="The number was bought and cannot be used",
            detail="The voice platform returned no identifier for the number it sold.",
        )
    try:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=bought.e164,
            # The series is read out of what the vendor actually sold us, not out of what
            # we asked for: a vendor that handed us a different number than we named must
            # be recorded as having done so.
            series=series_for_e164(bought.e164) or PURCHASABLE_SERIES,
            agent_id=agent_id,
            provider=bought.provider or provider,
            purpose=purpose,
            engine_number_ref=ref,
            engine_owned=True,
            purchase_price_usd=bought.purchase_price_usd,
            monthly_rental_usd=monthly_rental_usd,
        )
    except Exception:
        # THE MONEY IS ALREADY SPENT. This is the one failure in this module that cannot be
        # made safe by retrying — a retry buys a second number — so it is alarmed with the
        # vendor's own handle, which is the only thing that can find the purchase again.
        # Hard rule 6: the handle and the tenant id, never the E.164.
        alert(
            "CORE_LOGIC",
            "number_bought_but_not_recorded",
            detail=(
                "a phone number was bought at the voice platform and could not be "
                "recorded here, so it is being rented with nothing pointing at it. DO NOT "
                "RETRY THE PURCHASE — it would buy a second number. Find it in the voice "
                "platform's own number list by this handle and record or release it."
            ),
            tenant_id=str(tenant_id),
            engine_number_ref=ref,
        )
        raise
    log.info(
        "number_bought",
        extra={"tenant_id": str(tenant_id), "number_id": str(number_id), "ref": ref},
    )
    return BoughtNumber(
        number_id=number_id,
        e164=bought.e164,
        engine_number_ref=ref,
        provider=bought.provider or provider,
        purchase_price_usd=bought.purchase_price_usd,
        monthly_rental_usd=monthly_rental_usd,
    )


_NUMBER_FOR_RELEASE = (
    "SELECT e164, series, provider, engine_number_ref, engine_owned, released_at "
    "FROM phone_numbers WHERE id = :id"
)


async def release_number(session: AsyncSession, engine: VoiceEngine, *, number_id: UUID) -> None:
    """Give a bought number back to the vendor and stop the rental. Offboarding only.

    UNBIND FIRST, THEN DELETE, THEN MARK. The order is the safety property: a number
    deleted at the vendor while still bound would leave our routing table pointing at a
    handle that no longer exists, and a row marked released before the vendor agreed would
    stop the meter on a rental that is still being charged. Each step is idempotent on its
    own — `unbind_inbound_number` and `release_number` both treat absent as success — so a
    retry after a partial failure completes rather than compounding.

    A NUMBER WE DID NOT BUY IS REFUSED. Under Model B the client is the subscriber of
    record on their own carrier account; "releasing" it here would delete our record of a
    connection the vendor never held and the client still pays for.

    The row SURVIVES, with `released_at` set. It is what a closed month's cost query still
    needs, it is what stops the monthly meter, and deleting it would break `e164`'s global
    uniqueness as a record of who once held what.
    """
    assert_number_supply_authorized()
    row = (await session.execute(text(_NUMBER_FOR_RELEASE), {"id": number_id})).first()
    if row is None:
        raise ProblemError.not_found("Number")
    e164, series, provider, engine_number_ref, engine_owned, released_at = row
    if not engine_owned:
        raise ProblemError.business_rule(
            "number_not_ours_to_release",
            "This number is the client's own connection, so it cannot be given back here.",
            remediation=(
                "The client is the subscriber of record with their own operator and "
                "cancels it there. Detach it from the agent instead."
            ),
        )
    if released_at is not None:
        # Already given back. The caller's postcondition holds, so this is success and not
        # a conflict — an offboarding that raises on a step already taken is an offboarding
        # somebody abandons half done.
        return
    spec = ProvisionedNumber(
        e164=str(e164),
        provider=provider,
        engine_number_ref=engine_number_ref,
        series=series,
    )
    await engine.unbind_inbound_number(spec)
    await engine.release_number(spec)
    await session.execute(
        text(
            "UPDATE phone_numbers SET released_at = now(), agent_id = NULL, "
            "updated_at = now() WHERE id = :id AND released_at IS NULL"
        ),
        {"id": number_id},
    )
    log.info("number_released", extra={"number_id": str(number_id)})


__all__ = ["BoughtNumber", "buy_number", "release_number", "search_numbers"]
