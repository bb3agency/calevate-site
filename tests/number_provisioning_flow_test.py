"""Browse, buy and assign a number from the client console — and what still refuses.

The flow a verified client walks: see what is available, buy one, choose whether it
handles inbound, outbound or both, and point it at an agent. Six properties make that a
product rather than a code path.

1. **The legal gate survives all of it.** No written VNO/reseller status is recorded, so
   every client-facing route refuses today. This is the most important test in the file:
   a build that can buy a number right now is a defect.
2. **The money is attested, NUMERIC and in rupees.** A client cannot be quoted a price
   nobody has read, and the figure they are charged is not the vendor's dollar quote.
3. **A double-clicked purchase buys one number.** The `Idempotency-Key` replays the first
   answer rather than starting a second monthly rental.
4. **Hard rule 1.** A neighbour's holder, numbers and prices read back as zero rows.
5. **Assignment is the activation gate.** An unverified holder's number cannot be bound
   to an agent, and binding is what puts a number on a handset (D-420).
6. **The series comes off the number, never off the request.** There is no `series` field
   to type any more.

Run: uv run pytest -q tests/number_provisioning_flow_test.py
"""

from __future__ import annotations

import itertools
import secrets
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import record_entry
from apps.api.campaigns import number_catalog, number_supply, provisioning
from apps.api.campaigns.number_holder import read_holder, record_holder
from apps.api.campaigns.number_pricing import record_attested_price_inr
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, accept_carrier_application

pytestmark = [pytest.mark.rls]

AVAILABLE_PATH = "/v1/numbers/available"
PURCHASE_PATH = "/v1/numbers/purchase"
HOLDER_PATH = "/v1/numbers/holder"


@pytest.fixture
def authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that HAS recorded the written reseller status.

    The same fixture `tests/number_supply_test.py` uses, and it is a fixture rather than a
    default precisely because the gate is real: every test that does not ask for it is
    testing the world as it is today.
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


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Number Clinic",
        slug=f"num-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    # The carrier approves each client business before a number may be rented for it.
    # Supplied, never assumed away — without it a purchase reports
    # `carrier_application_not_accepted` in place of the answer under test.
    await accept_carrier_application(tenant_id)
    await _topup(tenant_id)
    return created


async def _member(tenant_id: uuid.UUID) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return user_id


async def _headers(org: dict[str, Any]) -> dict[str, str]:
    user_id = await _member(uuid.UUID(str(org["id"])))
    return {
        "Authorization": f"Bearer dev:client:{user_id}",
        "X-Org-Slug": str(org["slug"]),
    }


async def _admin_user() -> uuid.UUID:
    """A `users` row the price attestation's FK can point at.

    The attestation is written directly here rather than through the admin route because
    what is under test is the PRICE gate, not the console: the route has its own realm and
    its own permission, and borrowing them would make every money test depend on them.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    return user_id


async def _attest_price(amount: str = "999.00") -> Decimal:
    attested_by = await _admin_user()
    async with untenanted_session() as session:
        price = await record_attested_price_inr(
            session,
            inr_per_month=Decimal(amount),
            source="carrier order form, fixture",
            attested_by=attested_by,
        )
    return price.inr_per_month


#: A COUNTER, not three random hex characters, and the difference is a flake.
#:
#: `phone_numbers.e164` is globally UNIQUE and the fake engine derives its inventory
#: deterministically from the search query, so two tests browsing with the same terms are
#: offered the same numbers and the second collides. A random 3-character pattern draws
#: from 4096 values, which over a dozen tests collides about one run in a hundred — a
#: failure that reads as a tenancy defect and is not one. Three characters because that is
#: the vendor's own filter width (VERIFIED-VENDOR-DOCS:
#: `bolna-findings/mirror/pages/api-reference/phone-numbers/search.md:44-50`), and the
#: route's `search_pattern` is bounded to it. The random START keeps two local runs against
#: an unreset database apart; CI runs `make db-reset` first.
_PATTERNS = itertools.count(secrets.randbelow(0x1000))


def _pattern() -> str:
    """A search filter unique to one test within this run."""
    return f"{next(_PATTERNS) % 0x1000:03x}"


async def _topup(tenant_id: uuid.UUID, amount: str = "5000.00") -> None:
    """Credit, so a purchase is not refused on the wallet it is not about.

    Supplied rather than assumed away: `_assert_can_afford` refuses before the vendor is
    called, so a fixture without this reports `number_insufficient_credit` in place of the
    property under test — the shape `accept_carrier_application` argues for.
    """
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(amount),
            reason="topup",
            ref=f"UTR-{uuid.uuid4().hex[:10]}",
        )


async def _with_holder(tenant_id: uuid.UUID) -> None:
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        await record_holder(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            holder_type="business",
            holder_name="Number Clinic Pvt Ltd",
            holder_email="owner@example.com",
        )


async def _verify_kyc(tenant_id: uuid.UUID) -> None:
    """A verified KYC record, written the way the ops route writes one.

    Only the columns the `is_verified` predicate and the table's own CHECKs need: this
    file is about numbers, and `tests/kyc_gate_test.py` owns what a record must contain.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kyc_records (id, tenant_id, status, entity_type, document_kind, "
                "document_ref, signatory_name, evidence_ref, verified_by_admin_id, "
                "submitted_at, verified_at, created_at, updated_at) VALUES (:id, :tid, "
                "'verified', 'private_limited', 'cin', 'U74999TG2026PTC123456', "
                "'A Signatory', 'ops-4471', :admin, now(), now(), now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "admin": admin_id},
        )


async def _agent(tenant_id: uuid.UUID, *, direction: str = "inbound") -> uuid.UUID:
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, created_at, updated_at) VALUES (:id, :tid, "
                "'Reception', :dir, 'draft', 'te-IN', 'This is an AI assistant and this call "
                "is recorded.', 'This is an AI assistant and this call is recorded.', 'This "
                "call is being recorded.', 'I keep a short note of what you ask about.', "
                "now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "dir": direction},
        )
    return agent_id


# ------------------------------------------- 1. the gate that must survive this work


async def test_a_client_cannot_buy_a_number_today() -> None:
    """**THE MOST IMPORTANT TEST IN THIS FILE.**

    `Settings.number_resale_authorization` is unset: no written VNO/reseller status from a
    licensed Indian operator exists, and the playbook conditions the whole self-supply
    shape on one (`docs/legal/LEGAL-OPS-PLAYBOOK.md:621`). The flow below this line is
    built so that recording that instrument is the only change needed — not so that it can
    be skipped. A purchase that succeeds here is a defect, not a feature.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _verify_kyc(tenant_id)
    await _with_holder(tenant_id)
    await _attest_price()

    async with _client() as http:
        response = await http.post(
            PURCHASE_PATH,
            headers={**await _headers(org), "Idempotency-Key": uuid.uuid4().hex},
            json={"e164": "+919876500001", "direction": "both"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "number_purchase_is_operator_led"
    async with tenant_session(tenant_id) as session:
        held = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar()
    assert held == 0, "a refused purchase must write nothing"


async def test_browsing_is_refused_too_not_only_the_purchase() -> None:
    """A catalogue that works beside a buy button that refuses teaches a client the
    refusal is a glitch. Search spends nothing and is gated anyway — the same reasoning
    `number_supply` applies to the operator's own search."""
    org = await _tenant()
    await _attest_price()
    async with _client() as http:
        response = await http.get(AVAILABLE_PATH, headers=await _headers(org))
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "number_purchase_is_operator_led"


async def test_the_service_door_refuses_even_when_a_route_does_not_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`assert_number_supply_authorized()` is the one door, and it is inside the service.

    The routes ask a client-facing question first, so this asserts the gate is not only a
    property of the HTTP layer: a future caller that forgets the route's check still
    cannot spend money.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await number_catalog.browse_numbers(session, get_engine())
    assert raised.value.code == "number_resale_not_authorized"


# ------------------------------------------------------- 2. the money


async def test_a_client_cannot_be_quoted_a_price_nobody_attested(
    authorized: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 7. There is no default rate and no constant to fall back on: the vendor's
    quote is in dollars and is OUR cost, and turning it into a client-facing rupee figure
    would take a pricing decision nobody has taken (OPERATIONS §2 gate 26).

    THE EMPTY STATE IS SIMULATED, not arranged, and it has to be: the attestations are
    platform-wide and append-only, so once any test in this suite has recorded one the
    table can never be emptied again. Patching the READER is the honest way to ask "what
    does the door do when there is nothing behind it" — `require_attested_price_inr` calls
    it through the module global, so the door itself is the code under test.
    """

    async def _none(_session: Any) -> None:
        return None

    from apps.api.campaigns import number_pricing

    monkeypatch.setattr(number_pricing, "attested_price_inr", _none)
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await number_catalog.browse_numbers(session, get_engine())
    assert raised.value.code == "number_price_not_attested"


async def test_the_price_a_client_pays_is_the_attested_rupee_figure(authorized: None) -> None:
    """NUMERIC INR, frozen on the row at purchase — not the vendor's USD quote, which
    stays in `monthly_rental_usd` as what Calevate is charged."""
    amount = await _attest_price("1234.50")
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        assert offers, "the fake engine sells standard numbers"
        assert all(offer.inr_per_month == amount for offer in offers)
        bought = await number_catalog.purchase_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offers[0].e164,
            pattern=pattern,
            direction="both",
        )

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT client_inr_per_month, monthly_rental_usd, direction, series "
                    "FROM phone_numbers WHERE id = :id"
                ),
                {"id": bought.number_id},
            )
        ).first()
    assert row is not None
    assert row[0] == amount
    assert row[1] is not None and row[1] != amount, "our cost is a different fact"
    assert row[2] == "both"
    # 6. THE SERIES CAME OFF THE NUMBER. There is no `series` field on the request any
    # more: it used to be typed and trusted, and a typed word opened promotional dialling
    # from a number that was not a telemarketing header.
    assert row[3] == "standard"


# ------------------------------------------------- 3. a double click buys one number


async def test_a_repeated_purchase_with_one_key_buys_one_number(authorized: None) -> None:
    """The vendor's buy endpoint takes NO idempotency key of its own (VERIFIED-VENDOR-DOCS:
    `bolna-findings/mirror/pages/api-reference/phone-numbers/buy.md:55-76`), so a retry
    there buys a second number and starts a second monthly rental. The key is ours, and
    the second request is answered with the first purchase rather than re-run."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)
    headers = {**await _headers(org), "Idempotency-Key": uuid.uuid4().hex}

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
    body = {"e164": offers[0].e164, "search_pattern": pattern, "direction": "inbound"}

    async with _client() as http:
        first = await http.post(PURCHASE_PATH, headers=headers, json=body)
        second = await http.post(PURCHASE_PATH, headers=headers, json=body)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json(), "the replay is the first answer, not a new one"
    async with tenant_session(tenant_id) as session:
        held = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar()
    assert held == 1, "a double click must not start two monthly rentals"


async def test_a_purchase_without_an_idempotency_key_is_refused(authorized: None) -> None:
    """Required, not optional, because the vendor cannot dedupe for us and the cost of a
    missed dedupe is a second recurring commitment."""
    await _attest_price()
    org = await _tenant()
    async with _client() as http:
        response = await http.post(
            PURCHASE_PATH, headers=await _headers(org), json={"e164": "+919876500002"}
        )
    assert response.status_code == 400, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "idempotency_key_required"


# ------------------------------------------------------- 4. hard rule 1


async def test_one_tenant_never_sees_another_tenants_holder_or_numbers(
    authorized: None,
) -> None:
    """Cross-tenant zero rows, on the raw session as well as through the route: the
    policy is FORCEd, so the neighbour's rows are invisible rather than filtered."""
    await _attest_price()
    owner = await _tenant()
    owner_id = uuid.UUID(str(owner["id"]))
    await _with_holder(owner_id)
    await _verify_kyc(owner_id)
    pattern = _pattern()
    async with tenant_session(owner_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        await number_catalog.purchase_number(
            session, get_engine(), tenant_id=owner_id, e164=offers[0].e164, pattern=pattern
        )

    neighbour = await _tenant()
    neighbour_id = uuid.UUID(str(neighbour["id"]))
    async with tenant_session(neighbour_id) as session:
        assert await read_holder(session) is None
        held = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar()
        assert held == 0
        holders = (await session.execute(text("SELECT count(*) FROM number_holders"))).scalar()
        assert holders == 0

    async with _client() as http:
        response = await http.get(HOLDER_PATH, headers=await _headers(neighbour))
    assert response.status_code == 200, response.text
    assert response.json()["recorded"] is False


async def test_the_holder_is_recorded_once_and_cannot_be_changed(authorized: None) -> None:
    """ "Collected once, then reused for every future number. Can't be changed later" is a
    unique constraint and an append-only trigger, not a screen's good manners: a holder
    edited after a number was registered would name an owner the operator's own record
    does not."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    headers = await _headers(org)
    body = {
        "holder_type": "individual",
        "holder_name": "S Raghava",
        "holder_email": "raghava@example.com",
    }
    async with _client() as http:
        first = await http.post(HOLDER_PATH, headers=headers, json=body)
        second = await http.post(
            HOLDER_PATH, headers=headers, json={**body, "holder_name": "Somebody Else"}
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["type"].rsplit("/", 1)[-1] == "number_holder_already_recorded"

    async with tenant_session(tenant_id) as session:
        holder = await read_holder(session)
    assert holder is not None
    assert holder.holder_name == "S Raghava"


async def test_a_purchase_without_a_holder_is_refused(authorized: None) -> None:
    """Whose connection it is, before we take one in their name. It is what keeps this
    from being number resale."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        with pytest.raises(ProblemError) as raised:
            await number_catalog.purchase_number(
                session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
            )
    assert raised.value.code == "number_holder_not_recorded"


# -------------------------------------- 5. assignment, and the activation gate


async def test_an_unverified_holders_number_cannot_be_given_to_an_agent(
    authorized: None,
) -> None:
    """KYC gates ACTIVATION, not the sale (the competitor's own sequencing, and safer for
    the same reason): the number is bought and held, and the one thing it cannot do is
    become the line an agent answers — which is the only way it could reach a handset
    (D-420). Its own rule name, so an operator can tell it from the dial gate's KYC
    blockers."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    agent_id = await _agent(tenant_id)

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
        assert bought.activated is False
        with pytest.raises(ProblemError) as raised:
            await number_catalog.assign_number_to_agent(
                session, tenant_id=tenant_id, number_id=bought.number_id, agent_id=agent_id
            )
    assert raised.value.code == provisioning.NOT_ACTIVATED_RULE

    async with tenant_session(tenant_id) as session:
        bound = (
            await session.execute(
                text("SELECT agent_id FROM phone_numbers WHERE id = :id"),
                {"id": bought.number_id},
            )
        ).scalar()
    assert bound is None, "a refused assignment must leave the number unbound"


async def test_assigning_binds_the_number_and_records_what_it_is_for(
    authorized: None,
) -> None:
    """The binding is what makes every downstream gate mean something (D-420): the
    outbound caller ID and the inbound answer are both resolved from
    `phone_numbers.agent_id`. The direction is recorded in the same act."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)
    agent_id = await _agent(tenant_id, direction="both")

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offers[0].e164,
            pattern=pattern,
            direction="inbound",
        )
        assert bought.activated is True
        await number_catalog.assign_number_to_agent(
            session,
            tenant_id=tenant_id,
            number_id=bought.number_id,
            agent_id=agent_id,
            direction="both",
        )

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT agent_id, direction, activated_at FROM phone_numbers WHERE id = :id"),
                {"id": bought.number_id},
            )
        ).first()
    assert row is not None
    assert row[0] == agent_id
    assert row[1] == "both"
    assert row[2] is not None


async def test_a_verified_holder_activates_a_number_bought_before_verification(
    authorized: None,
) -> None:
    """The holder may be verified AFTER the purchase, and the number has to become usable
    without a second job somebody has to remember to run — the half-wired seam nobody
    comes back for. The assignment activates it."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    agent_id = await _agent(tenant_id)

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
    await _verify_kyc(tenant_id)
    async with tenant_session(tenant_id) as session:
        await number_catalog.assign_number_to_agent(
            session, tenant_id=tenant_id, number_id=bought.number_id, agent_id=agent_id
        )
        activated = (
            await session.execute(
                text("SELECT activated_at FROM phone_numbers WHERE id = :id"),
                {"id": bought.number_id},
            )
        ).scalar()
    assert activated is not None


async def test_detaching_is_never_blocked_by_activation(authorized: None) -> None:
    """Taking a number OFF an agent is the safe direction and the recovery path from a
    wrong assignment. Refusing it would trap a client whose verification lapsed with a
    live binding they cannot remove."""
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
        # No raise: the unactivated number can still be detached.
        await number_catalog.assign_number_to_agent(
            session, tenant_id=tenant_id, number_id=bought.number_id, agent_id=None
        )


async def test_a_purchase_is_refused_cleanly_when_the_wallet_cannot_cover_it(
    authorized: None,
) -> None:
    """Refused BEFORE the vendor is called, so there is no part-completed purchase.

    The alternative — buy, then discover the wallet is empty — leaves a number rented at
    the vendor against a client who cannot pay the first month, and `buy_number` alarms
    rather than retrying because a retry buys a second one.
    """
    await _attest_price("999.00")
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)
    # Spend the fixture's credit back down to nothing, rather than building a tenant
    # without it: `_tenant` tops up so that every other test is about its own subject.
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-5000.00"),
            reason="adjustment",
            ref=f"fixture-{uuid.uuid4().hex[:10]}",
        )

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        with pytest.raises(ProblemError) as raised:
            await number_catalog.purchase_number(
                session,
                get_engine(),
                tenant_id=tenant_id,
                e164=offers[0].e164,
                pattern=pattern,
            )
    assert raised.value.code == number_catalog.NO_CREDIT_RULE
    async with tenant_session(tenant_id) as session:
        held = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar()
    assert held == 0, "a refused purchase must buy nothing"


async def test_the_numbers_list_says_who_answers_each_one_and_whether_it_is_usable(
    authorized: None,
) -> None:
    """`GET /v1/campaigns/numbers` carries the binding, the direction and the activation.

    Without them the console's assignment panel can only report its own last action: it
    cannot say which agent is on a number, which is the binding every downstream gate
    depends on (D-420), nor whether the number is usable at all.

    NO PRICE FIELD, and that is deliberate: what a number costs is on the offer list where
    a client is choosing what to buy, and publishing a figure on the numbers they already
    hold would take a pricing decision nobody has taken (OPERATIONS §2 gate 26).
    """
    await _attest_price()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)
    agent_id = await _agent(tenant_id, direction="both")

    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session,
            get_engine(),
            tenant_id=tenant_id,
            e164=offers[0].e164,
            pattern=pattern,
            direction="both",
        )
        await number_catalog.assign_number_to_agent(
            session, tenant_id=tenant_id, number_id=bought.number_id, agent_id=agent_id
        )

    async with _client() as http:
        response = await http.get("/v1/campaigns/numbers", headers=await _headers(org))
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    row = rows[str(bought.number_id)]
    assert row["agent_id"] == str(agent_id)
    assert row["direction"] == "both"
    assert row["activated"] is True
    # OUR cost stays off a client screen (gate 26: whether it is absorbed, passed
    # through or an add-on is an untaken pricing decision, and publishing it would
    # take that decision). What THIS client agreed to pay for THIS number is not
    # that, and a recurring charge invisible on the thing it is charged for is the
    # opposite defect.
    assert "monthly_rental_usd" not in row
    assert row["inr_per_month"] is not None
