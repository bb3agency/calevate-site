"""The attested cost inputs (D-840): the wallet top-up fee, the gateway fee, a rented number's
rent, and what they reach — the meter, the cost floor, the number-rent meter, and the margin
screen's charge variance."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.charge_variance import month_charge_variance
from apps.api.billing.cost_attestations import (
    attest_cost,
    attested_cost,
    attested_costs,
    parse_cost_value,
)
from apps.api.billing.engine_minutes import required_wallet_fee, wallet_fee
from apps.api.billing.floor_inputs import floor_inputs
from apps.api.billing.number_rental import record_engine_number_rental
from apps.api.billing.plans import ist_billing_month
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.ops import config_routes
from apps.api.ops.engine_minute_routes import cost_confirmation
from apps.workers import number_rental
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.model_pricing_test import _purge_table
from tests.spend_attribution_test import _client, _make_admin, _tenant

#: Every row this suite attests carries this note, so the cleanup removes only those.
_NOTE = "cost-attestations-test fixture"


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_cost_attestations is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await _purge_table(conn, "platform_cost_attestations", "source_note", [_NOTE])
    finally:
        await engine.dispose()


async def _admin() -> uuid.UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Costs', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _attest(subject: str, value: str, *, at: datetime) -> None:
    actor = await _admin()
    async with untenanted_session() as session:
        await attest_cost(
            session,
            subject=subject,
            value=parse_cost_value(subject, value),
            effective_from=at,
            source_note=_NOTE,
            actor_id=actor,
        )


def _past() -> datetime:
    """An instant in 2001 no other run attests at."""
    return datetime(2001, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )


async def test_the_carried_over_fee_is_in_force_for_every_minute() -> None:
    """The 2.36% constant became the first attested row, effective from the epoch, so every
    minute ever metered resolves the fee it was metered at."""
    async with untenanted_session() as session:
        now = await wallet_fee(session, engine="thinnest", at=datetime.now(UTC))
        old = await wallet_fee(session, engine="thinnest", at=datetime(2001, 1, 1, tzinfo=UTC))
        fake = await required_wallet_fee(session, engine="fake", at=datetime.now(UTC))
    assert now is not None and now.fee == Decimal("0.0236")
    assert old is not None and old.fee == Decimal("0.0236")
    assert fake.fee == 0 and fake.effective_from is None


async def test_an_unattested_fee_is_refused_to_a_reader_that_needs_one() -> None:
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as caught:
            await required_wallet_fee(
                session, engine="thinnest", at=datetime(1969, 12, 31, tzinfo=UTC)
            )
    assert caught.value.code == "wallet_topup_fee_unattested"


def test_a_fee_is_typed_in_percent_and_refused_at_a_hundred() -> None:
    assert parse_cost_value("razorpay_topup_fee", "2.36") == Decimal("0.0236")
    assert parse_cost_value("thinnest_number_month", "349.00") == Decimal("349.00")
    for subject, raw in (
        ("razorpay_topup_fee", "100"),
        ("razorpay_topup_fee", "-1"),
        ("thinnest_number_month", "0"),
        ("thinnest_number_month", "abc"),
    ):
        with pytest.raises(ProblemError) as caught:
            parse_cost_value(subject, raw)
        assert caught.value.code == "cost_attestation_invalid"
    with pytest.raises(ProblemError):
        parse_cost_value("vat", "1")


async def test_a_second_figure_at_the_same_instant_is_refused() -> None:
    at = _past()
    await _attest("razorpay_topup_fee", "2", at=at)
    with pytest.raises(ProblemError) as caught:
        await _attest("razorpay_topup_fee", "3", at=at)
    assert caught.value.code == "cost_attestation_duplicate_instant"


async def test_the_route_attests_a_fee_behind_step_up_and_audits_it() -> None:
    admin_id = await _admin()
    token = f"dev:admin:{admin_id}"
    started = datetime.now(UTC)
    body = {
        "value": "2.36",
        "source_note": _NOTE,
        "effective_from": _past().isoformat(),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        bare = await client.post(
            "/v1/ops/cost-attestations/razorpay_topup_fee",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        wrong = await client.post(
            "/v1/ops/cost-attestations/razorpay_topup_fee",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": cost_confirmation("thinnest_topup_fee"),
            },
            json=body,
        )
        done = await client.post(
            "/v1/ops/cost-attestations/razorpay_topup_fee",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": cost_confirmation("razorpay_topup_fee"),
            },
            json=body,
        )
        listed = await client.get(
            "/v1/ops/engine-minute-prices", headers={"Authorization": f"Bearer {token}"}
        )
    assert bare.status_code >= 400 and wrong.status_code >= 400
    assert done.status_code == 200, done.text
    assert done.json()["unit"] == "percent"
    assert done.json()["value"] == "2.36"
    costs = {row["subject"]: row for row in listed.json()["costs"]}
    assert costs["razorpay_topup_fee"]["value"] == "2.36"
    assert costs["thinnest_topup_fee"]["value"] == "2.36"
    platform = next(row for row in listed.json()["prices"] if row["rate_key"] == "platform")
    assert platform["topup_fee_percent"] == "2.36"
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'platform.cost_attested' "
                    "AND object_id = 'razorpay_topup_fee' AND at >= :t"
                ),
                {"t": started},
            )
        ).scalar_one()
    assert audited == 1


async def test_the_floor_names_the_gateway_fee_until_it_is_attested_and_then_counts_it() -> None:
    async with untenanted_session() as session:
        before = await floor_inputs(session, engine="thinnest", at=datetime.now(UTC))
    assert "razorpay_topup_fee" in before.unattested
    assert before.wallet_fee == Decimal("0.0236")
    await _attest("razorpay_topup_fee", "2", at=_past())
    async with untenanted_session() as session:
        after = await floor_inputs(session, engine="thinnest", at=datetime.now(UTC))
    assert after.gateway_fee == Decimal("0.02")
    assert after.unattested == ()


# --- the rent of a number rented in the voice platform's console --------------------------


async def _rented_number(tenant_id: uuid.UUID) -> uuid.UUID:
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, provider, engine_number_ref, "
                "engine_owned, created_at, updated_at) VALUES (:id, :tid, :e164, 'thinnest', "
                ":ref, true, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e164": f"+9180{uuid.uuid4().int % 10**8:08d}",
                "ref": f"{uuid.uuid4().int % 10**10}",
            },
        )
    return number_id


async def test_a_console_rented_number_is_metered_at_the_attested_rent_with_the_fee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DEFECT: `_LIVE_BOUGHT` left out every ThinnestAI number, so its rent never reached
    `unit_cost_paid`. Now it is metered once per number per month at the attested rent plus
    the wallet's top-up fee."""
    tenant_id, _agent = await _tenant(monthly_fee=None)
    number_id = await _rented_number(tenant_id)
    alarms: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        number_rental, "alert", lambda _stage, code, **fields: alarms.append((code, fields))
    )

    await number_rental.meter_number_rentals({})
    mine = [code for code, fields in alarms if fields.get("number_id") == str(number_id)]
    assert mine == ["number_rental_price_missing"], "an unattested rent must alarm, not skip"

    await _attest("thinnest_number_month", "349.00", at=_past())
    await number_rental.meter_number_rentals({})
    second = await number_rental.meter_number_rentals({})
    assert "'failed': 0" in second
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_cost_paid, meta->>'source_inr', meta->>'topup_fee' "
                    "FROM usage_events WHERE unit_type = 'number_rental' AND ref = :ref"
                ),
                {"ref": f"number_rental:{number_id}:{ist_billing_month(datetime.now(UTC))}"},
            )
        ).all()
    assert len(rows) == 1, "one row per number per month, however often the job runs"
    assert rows[0][0] == Decimal("357.2364")  # ₹349.00 x 1.0236
    assert (rows[0][1], rows[0][2]) == ("349.000000", "0.0236")


async def test_the_rent_in_force_is_the_newest_attestation_before_now() -> None:
    first = _past()
    await _attest("thinnest_number_month", "300", at=first)
    await _attest("thinnest_number_month", "349", at=first + timedelta(microseconds=1))
    async with untenanted_session() as session:
        found = await attested_cost(
            session,
            subject="thinnest_number_month",
            at=first + timedelta(microseconds=2),
        )
    assert found is not None and found.value == Decimal("349")


# --- the charge variance on the margin screen ------------------------------------------------


async def test_the_variance_compares_the_charge_with_its_fee_against_the_metered_minute() -> None:
    tenant_id, agent_id = await _tenant(monthly_fee=None)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, engine_charged_inr, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', 2.50, now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"out_{uuid.uuid4().hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, 3.0708, now(), '{}'::jsonb, now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
    async with tenant_session(tenant_id) as session:
        found = await month_charge_variance(
            session,
            tenant_id=tenant_id,
            month=ist_billing_month(datetime.now(UTC)),
            engine="thinnest",
        )
    assert found is not None
    assert found.calls == 1
    assert found.vendor_inr == Decimal("2.5590")  # ₹2.50 x 1.0236
    assert found.metered_inr == Decimal("3.0708")
    assert found.variance_inr == Decimal("0.5118")
    assert [c.call_id for c in found.largest] == [call_id]


async def test_a_month_with_no_charged_call_has_no_variance() -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        found = await month_charge_variance(
            session,
            tenant_id=tenant_id,
            month=ist_billing_month(datetime.now(UTC)),
            engine="thinnest",
        )
    assert found is None


# --- the refusals and skips each reader owes --------------------------------------------------


async def test_a_reader_refuses_a_naive_instant() -> None:
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await attested_costs(session, at=datetime(2026, 1, 1))


async def test_a_rent_too_small_for_the_ledger_column_is_refused_before_it_is_recorded() -> None:
    """₹0.000001 a month parses (six decimals) but stores as 0.0000 in `unit_cost_paid`."""
    actor = await _admin()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as caught:
            await attest_cost(
                session,
                subject="thinnest_number_month",
                value=parse_cost_value("thinnest_number_month", "0.000001"),
                effective_from=_past(),
                source_note=_NOTE,
                actor_id=actor,
            )
    assert caught.value.code == "attested_price_not_meterable"


async def test_the_number_rent_meter_refuses_a_rent_that_is_not_a_price() -> None:
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="not a price"):
            await record_engine_number_rental(
                session,
                tenant_id=uuid.uuid4(),
                number_id=uuid.uuid4(),
                month=ist_billing_month(datetime.now(UTC)),
                inr_per_month=Decimal("0"),
                topup_fee=Decimal("0.0236"),
                provider="thinnest",
            )


async def _charged_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, cost: str | None
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, engine_charged_inr, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', 2.50, now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"out_{uuid.uuid4().hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, CAST(:cost AS numeric), now(), '{}'::jsonb, now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "cost": cost},
        )
    return call_id


async def test_an_unpriced_call_is_left_out_of_the_variance_rather_than_counted_as_zero() -> None:
    tenant_id, agent_id = await _tenant(monthly_fee=None)
    await _charged_call(tenant_id, agent_id, cost=None)
    priced = await _charged_call(tenant_id, agent_id, cost="3.0708")
    async with tenant_session(tenant_id) as session:
        found = await month_charge_variance(
            session,
            tenant_id=tenant_id,
            month=ist_billing_month(datetime.now(UTC)),
            engine="thinnest",
        )
    assert found is not None
    assert found.calls == 1
    assert [c.call_id for c in found.largest] == [priced]


async def test_the_spend_page_carries_the_variance() -> None:
    tenant_id, agent_id = await _tenant(monthly_fee=None)
    await _charged_call(tenant_id, agent_id, cost="3.0708")
    token = await _make_admin()
    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    variance = response.json()["charge_variance"]
    assert variance is not None
    assert variance["calls"] == 1
    assert len(variance["largest"]) == 1


async def test_a_rate_card_saved_with_every_floor_input_attested_raises_no_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _attest("razorpay_topup_fee", "2", at=_past())
    async with untenanted_session() as session:
        inputs = await floor_inputs(session, engine="thinnest", at=datetime.now(UTC))
    assert inputs.unattested == ()
    alarms: list[str] = []
    monkeypatch.setattr(config_routes, "alert", lambda _stage, code, **_: alarms.append(code))
    config_routes._log_margins((), own_model_prompt_tokens=None, inputs=inputs)
    assert alarms == []
