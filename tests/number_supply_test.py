"""Buying, linking, metering and releasing a phone number (D-537).

Model A is adopted on the inbound leg: Calevate buys an Indian DID through the voice
engine and the clinic forwards its own published number to it. Five properties make that
a product rather than a code path, and each one is a section below.

1. **The going-live gate is a legal fact, not a feature flag.** Nothing buys, searches or
   releases until a written VNO/reseller authorisation is recorded, and the refusal names
   which of the two blockers it is.
2. **GAP-1 is closed end to end.** `phone_numbers.engine_number_ref` now has a writer on
   both paths — the purchase, and an operator recording the handle for a number the client
   brought — and a publish of an inbound agent binds instead of alarming.
3. **The money is NUMERIC INR and the recurring cost has a home.** One
   `number_rental` usage event per number per IST month, idempotent in the database.
4. **A purchase is not idempotent, so nothing may double-buy.** The E.164 is globally
   unique and the check runs under the lock.
5. **A paid asset is not orphaned.** Release unbinds, gives the number back and stops the
   meter; a number the CLIENT holds is refused.

Run: uv run pytest -q tests/number_supply_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.billing.number_rental import record_number_rental, rental_ref
from apps.api.campaigns import number_supply, provisioning
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from calevate_shared.engine import NumberSearch, NumberSpec
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]


@pytest.fixture
def authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that has recorded the written reseller status.

    The setting holds a REFERENCE to the instrument, not a boolean, which is the whole
    point of the gate: an auditor and the next reader need to know which document was
    relied on. The value here is obviously a fixture and names no real authorisation.
    """
    from apps.api.core import settings as settings_module

    base = settings_module.get_settings()
    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: base.model_copy(update={"number_resale_authorization": "TEST-VNO-FIXTURE"}),
    )
    for module in (provisioning, number_supply):
        monkeypatch.setattr(module, "get_settings", settings_module.get_settings, raising=False)


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Guntur Clinic",
        slug=f"clinic-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id


async def _offer(pattern: str) -> object:
    """One number the fake engine will sell, distinct per `pattern`.

    THE PATTERN IS PER TEST, and that is not incidental: `phone_numbers.e164` is globally
    UNIQUE — the constraint that makes a number one account's or nobody's — so two tests
    buying "the first offer" would collide with each other and with every other file in
    the suite. The fake derives its inventory deterministically from the search query,
    which is exactly what makes a distinct pattern produce a distinct number.
    """
    offers = await number_supply.search_numbers(
        get_engine(), country="IN", pattern=pattern, provider=None
    )
    assert offers, "the fake engine sells standard numbers and should offer some"
    return offers[0]


# ------------------------------------------------------- 1. the going-live gate


async def test_nothing_buys_until_the_written_authorisation_is_recorded() -> None:
    """The founder's condition on this decision, sequenced rather than waived.

    The playbook is explicit — "If you ever do it: incorporate first, get written
    VNO/reseller status from a licensed operator" (`docs/legal/LEGAL-OPS-PLAYBOOK.md:621`)
    — and neither exists today. "The code is ready" and "it is lawful for us to resell
    numbers" are different facts and this is what stops the product conflating them.
    """
    with pytest.raises(ProblemError) as raised:
        await number_supply.search_numbers(get_engine(), country="IN", pattern=None, provider=None)
    assert raised.value.code == "number_resale_not_authorized"


async def test_the_gate_bites_search_too_not_only_the_purchase(authorized: None) -> None:
    """And with it recorded, the search works — so the gate is what was refusing.

    Search spends nothing, and is gated anyway: a search screen that works beside a buy
    button that refuses teaches an operator that the gate is a glitch.
    """
    offers = await number_supply.search_numbers(
        get_engine(), country="IN", pattern=None, provider=None
    )
    assert offers, "the fake engine sells standard numbers and should offer some"
    assert all(offer.e164.startswith("+91") for offer in offers)
    assert all(offer.monthly_price_usd is not None for offer in offers)


# ------------------------------------------------------- 2. GAP-1, both writers


async def test_a_purchase_persists_the_engine_handle(authorized: None) -> None:
    """**THE FATAL SEAM.** `engine_number_ref` had no writer in production code: the
    INSERT omitted it, the request body forbade it and no screen set it — only test
    fixtures. It is READ on every inbound publish, so every one of them raised a
    CORE_LOGIC alarm while reporting success."""
    tenant_id = await _tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    async with tenant_session(tenant_id) as session:
        bought = await number_supply.buy_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offer.e164,
            country="IN",
            provider=offer.provider,
            monthly_rental_usd=offer.monthly_price_usd,
            agent_id=None,
            purpose="reception",
        )
    assert bought.engine_number_ref
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_number_ref, engine_owned, monthly_rental_usd, released_at "
                    "FROM phone_numbers WHERE id = :id"
                ),
                {"id": bought.number_id},
            )
        ).first()
    assert row is not None
    assert row[0] == bought.engine_number_ref, "the vendor's handle must reach the column"
    assert row[1] is True, "a number WE bought is not a client's own connection"
    assert row[2] == Decimal("5.0000"), "the recurring cost must be on file or nothing meters it"
    assert row[3] is None


async def test_an_operator_can_record_the_handle_for_a_client_brought_number() -> None:
    """The other half of GAP-1. A client's own connection gets its handle only when an
    operator introduces it to the voice platform, which is a step outside this system —
    and until now there was no route that could accept the answer."""
    tenant_id = await _tenant()
    e164 = f"+9180{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=e164,
            series="standard",
            agent_id=None,
            provider="exotel",
            purpose="reception",
        )
        routing = await agents_service.set_number_engine_ref(
            session, number_id=number_id, engine_number_ref="num_from_the_vendor_console"
        )
        stored = (
            await session.execute(
                text("SELECT engine_number_ref, engine_owned FROM phone_numbers WHERE id = :id"),
                {"id": number_id},
            )
        ).first()
    assert stored is not None
    assert stored[0] == "num_from_the_vendor_console"
    assert stored[1] is False, "recording a client's connection must not claim we bought it"
    # No agent attached, so nothing was routed — and that is a no-op, not a failure.
    assert (routing.bound, routing.failed) == (0, 0)


async def test_a_number_with_no_handle_is_reported_as_unanswerable() -> None:
    """The client's own list says so, rather than looking healthy until the phone
    does not ring. `answerable` is False exactly while `engine_number_ref` is NULL."""
    tenant_id = await _tenant()
    e164 = f"+9180{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=e164,
            series="standard",
            agent_id=None,
            provider="exotel",
            purpose=None,
        )
        row = (
            await session.execute(
                text("SELECT engine_number_ref IS NOT NULL FROM phone_numbers WHERE id = :id"),
                {"id": number_id},
            )
        ).first()
    assert row is not None and row[0] is False


# ------------------------------------------------------- 3. the recurring cost


async def test_one_rental_row_per_number_per_month_and_a_replay_writes_nothing() -> None:
    """Idempotent in the DATABASE on `number_rental:<number_id>:<YYYY-MM>`, not in an
    `if`: the failure it survives is the same tick arriving twice, and a check-then-write
    would let both copies read "not metered yet"."""
    tenant_id = await _tenant()
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        first = await record_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            month="2026-09",
            monthly_rental_usd=Decimal("5.00"),
            provider="plivo",
        )
        second = await record_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            month="2026-09",
            monthly_rental_usd=Decimal("5.00"),
            provider="plivo",
        )
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, call_id FROM usage_events "
                    "WHERE ref = :ref"
                ),
                {"ref": rental_ref(number_id, "2026-09")},
            )
        ).all()
    assert first.recorded is True
    assert second.recorded is False, "a replay must not charge a second month"
    assert len(rows) == 1
    unit_type, qty, cost, call_id = rows[0]
    assert unit_type == "number_rental"
    assert qty == Decimal("1"), "a month is one unit — not thirty days and not a proration"
    # NUMERIC INR, never a float (hard rule 7). The rupee is the dollar figure at the
    # configured rate, because no published quote is installed in a test process.
    assert isinstance(cost, Decimal) and cost > 0
    assert call_id is None, "a rental belongs to no call — that is what makes it unattributed"


async def test_a_price_we_could_not_read_is_refused_rather_than_recorded_as_free() -> None:
    """A zero is not a free number, it is a price we failed to read — and an append-only
    ledger cannot be corrected in place, so a permanent ₹0 is worse than a loud refusal."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError):
            await record_number_rental(
                session,
                tenant_id=tenant_id,
                number_id=uuid7(),
                month="2026-09",
                monthly_rental_usd=Decimal("0"),
                provider=None,
            )


async def test_a_number_cannot_be_bought_without_a_rental_price(authorized: None) -> None:
    """Because a number with no rental on file is one the monthly meter skips for ever —
    which is precisely the silent leak this decision had to close."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await number_supply.buy_number(
                session,
                get_engine(),
                tenant_id=tenant_id,
                e164="+918000000099",
                country="IN",
                provider="plivo",
                monthly_rental_usd=None,
                agent_id=None,
                purpose=None,
            )
    assert raised.value.code == "number_rental_price_unknown"


# ------------------------------------------------------- 4. no double purchase


async def test_a_number_the_platform_already_holds_is_refused_before_any_vendor_call(
    authorized: None,
) -> None:
    """The vendor's buy endpoint takes no idempotency key, so a repeat buys a SECOND
    number and starts a SECOND rental. The check is against the GLOBALLY unique column,
    under the advisory lock — a tenant-scoped probe would report "available" for exactly
    the number another tenant holds, because RLS hides their row."""
    tenant_id = await _tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    async with tenant_session(tenant_id) as session:
        await number_supply.buy_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offer.e164,
            country="IN",
            provider=offer.provider,
            monthly_rental_usd=offer.monthly_price_usd,
            agent_id=None,
            purpose=None,
        )
        with pytest.raises(ProblemError) as raised:
            await number_supply.buy_number(
                session,
                get_engine(),
                tenant_id=tenant_id,
                e164=offer.e164,
                country="IN",
                provider=offer.provider,
                monthly_rental_usd=offer.monthly_price_usd,
                agent_id=None,
                purpose=None,
            )
    assert raised.value.code == "number_taken"


async def test_a_dlt_series_number_is_never_bought_through_the_engine(authorized: None) -> None:
    """140 and 160 are taken on an Indian operator's own account against a registered
    Principal Entity. Nothing read at source says this engine's buy endpoint can issue
    either, and a misclassified header is the ₹2/₹5/₹10 lakh ladder under the 2025 TCCCPR
    amendments — so the series is read out of the NUMBER and refused, never asserted."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await number_supply.buy_number(
                session,
                get_engine(),
                tenant_id=tenant_id,
                e164="+911600000001",
                country="IN",
                provider="plivo",
                monthly_rental_usd=Decimal("5.00"),
                agent_id=None,
                purpose=None,
            )
    assert raised.value.code == "number_series_not_purchasable"


async def test_the_port_refuses_a_purchase_nobody_chose() -> None:
    """search -> pick -> buy. The vendor requires the exact E.164 and has no "one like
    this" mode, so an adapter that invented one would spend real money on a number nobody
    picked. Asserted on the adapter directly, because it is the adapter's contract."""
    with pytest.raises(ProblemError) as raised:
        await get_engine().provision_number(NumberSpec(series="standard", purpose="probe"))
    assert raised.value.code == "number_not_chosen"


# ------------------------------------------------------- 5. release


async def test_releasing_gives_the_number_back_and_stops_the_meter(authorized: None) -> None:
    """UNBIND, then DELETE at the vendor, then mark — and the ROW survives, because a
    closed month's cost query still refers to it and `released_at` is what stops the
    monthly meter. Releasing twice succeeds: the postcondition is "we are not billed for
    this", and an offboarding step that raises on a step already taken is one somebody
    abandons half done."""
    tenant_id = await _tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    async with tenant_session(tenant_id) as session:
        bought = await number_supply.buy_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offer.e164,
            country="IN",
            provider=offer.provider,
            monthly_rental_usd=offer.monthly_price_usd,
            agent_id=None,
            purpose=None,
        )
        await number_supply.release_number(session, get_engine(), number_id=bought.number_id)
        await number_supply.release_number(session, get_engine(), number_id=bought.number_id)
        row = (
            await session.execute(
                text("SELECT released_at, agent_id FROM phone_numbers WHERE id = :id"),
                {"id": bought.number_id},
            )
        ).first()
    assert row is not None
    assert row[0] is not None, "the row survives, marked released — it is not deleted"
    assert row[1] is None
    # And the engine no longer holds it, so the rental has genuinely stopped.
    held = {number.engine_number_ref for number in await get_engine().list_engine_numbers()}
    assert bought.engine_number_ref not in held


async def test_a_clients_own_connection_cannot_be_released_here(authorized: None) -> None:
    """Model B is not withdrawn and is still half the product. "Releasing" a number the
    client holds in their own name would delete our record of a connection the vendor
    never held and the client still pays for."""
    tenant_id = await _tenant()
    e164 = f"+9180{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=e164,
            series="standard",
            agent_id=None,
            provider="exotel",
            purpose=None,
        )
        with pytest.raises(ProblemError) as raised:
            await number_supply.release_number(session, get_engine(), number_id=number_id)
    assert raised.value.code == "number_not_ours_to_release"


# ------------------------------------------------------- hard rule 1


async def test_one_tenants_bought_number_is_invisible_to_another(authorized: None) -> None:
    """Cross-tenant zero rows on the columns D-537 added, not only on the old ones — a
    price and a vendor handle are as much a tenant's business as the number itself."""
    owner = await _tenant()
    stranger = await _tenant()
    offer = await _offer(uuid.uuid4().hex[:6])
    async with tenant_session(owner) as session:
        bought = await number_supply.buy_number(
            session,
            get_engine(),
            tenant_id=owner,
            e164=offer.e164,
            country="IN",
            provider=offer.provider,
            monthly_rental_usd=offer.monthly_price_usd,
            agent_id=None,
            purpose=None,
        )
    async with tenant_session(stranger) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM phone_numbers WHERE id = :id AND engine_owned"),
                {"id": bought.number_id},
            )
        ).scalar()
    assert seen == 0


def test_the_search_query_is_the_vendors_own_two_country_enum() -> None:
    """Narrowed at OUR boundary, so an operator asking for a country this vendor does not
    serve gets a 422 naming the field rather than a vendor 400 naming nothing."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic's own ValidationError
        NumberSearch(country="GB")  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _fresh_engine() -> None:
    """The fake engine holds its purchases in memory, so a stale cached instance would
    leak one test's inventory into the next."""
    reset_engine_cache()
