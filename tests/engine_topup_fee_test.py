"""The ThinnestAI wallet top-up fee is part of a minute's cost (D-723).

The fixtures are the three production calls `engine_charge_mismatch` paged on, 10 Oct 2026:
rate key `premium`, attested ₹2.50 posted, pay-as-you-go (10% fee), metered without the fee.

    18 s  qty 0.3000  metered ₹1.25  costMicro ₹1.25  expected ₹1.375
    64 s  qty 1.0667  metered ₹3.75  costMicro ₹3.75  expected ₹4.125
    47 s  qty 0.7833  metered ₹2.50  costMicro ₹2.50  expected ₹2.75
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.engine_minutes import (
    attest_engine_minute_price,
    cost_with_fee,
    engine_minute_cost,
    thinnest_topup_fee,
    topup_fee,
)
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import LEDGER_RUNG_KEY, record_entry
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.charges import EngineCharge, EngineChargeListing
from apps.workers import engine_charges
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

#: (seconds, metered qty, ledger cost without the fee, costMicro charge) — production rows.
PRODUCTION_CALLS: tuple[tuple[int, str, str, str], ...] = (
    (18, "0.3000", "1.25", "1.25"),
    (64, "1.0667", "3.75", "3.75"),
    (47, "0.7833", "2.50", "2.50"),
)


@pytest.fixture
def on_band(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.api.core.settings import get_settings

    def _set(band: str) -> None:
        monkeypatch.setattr(get_settings(), "thinnest_clear_voice_band", band)

    _set("premium")
    return _set


# --- metering ------------------------------------------------------------------------------


async def _attest_platform(inr: str) -> datetime:
    """A `platform` rate at an instant no other suite prices at, returned for the read."""
    actor = uuid.uuid4()
    instant = datetime(2001, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": actor},
        )
        await attest_engine_minute_price(
            session,
            engine="thinnest",
            rate_key="platform",
            inr_per_min=Decimal(inr),
            effective_from=instant,
            source_note="ThinnestAI price page, posted rate",
            actor_id=actor,
        )
    return instant


@pytest.mark.parametrize(
    ("band", "fee", "expected"),
    [
        ("premium", "0.10", ("1.3750", "4.1250", "2.7500")),
        ("studio", "0.09", ("1.3625", "4.0875", "2.7250")),
    ],
)
async def test_a_minute_is_metered_at_the_posted_rate_plus_the_plans_fee(
    on_band: Any, band: str, fee: str, expected: tuple[str, str, str]
) -> None:
    on_band(band)
    assert thinnest_topup_fee() == topup_fee("thinnest") == Decimal(fee)
    assert topup_fee("pipecat") == 0
    at = await _attest_platform("2.50")
    tenant_id, _agent = await _seed_tenant(f"fee_{uuid.uuid4().hex[:10]}")
    for (seconds, _qty, _cost, _charge), want in zip(PRODUCTION_CALLS, expected, strict=True):
        async with tenant_session(tenant_id) as session:
            priced = await engine_minute_cost(
                session,
                engine="thinnest",
                tenant_id=tenant_id,
                call_id=uuid7(),
                seconds=Decimal(seconds),
                at=at,
            )
        assert priced.inr_per_min == Decimal("2.50")
        assert priced.topup_fee == Decimal(fee)
        assert priced.cost.total_inr == priced.cost.platform_inr == Decimal(want)
        # The figure the reconciler expects for a charge of the posted minutes.
        posted = priced.billed_minutes * Decimal("2.50")
        assert priced.cost.total_inr == cost_with_fee(posted, fee=Decimal(fee))


def test_the_reconciler_and_the_meter_share_one_fee_helper() -> None:
    from apps.api.billing import engine_minutes

    assert engine_charges.thinnest_topup_fee is engine_minutes.thinnest_topup_fee
    assert engine_charges.cost_with_fee is engine_minutes.cost_with_fee
    assert engine_charges.topup_fee is engine_minutes.topup_fee


# --- the compensating rows -----------------------------------------------------------------


async def _production_tenant() -> tuple[uuid.UUID, str, list[tuple[uuid.UUID, str, str]]]:
    """A ThinnestAI tenant holding the three production calls as they were metered: no
    `topup_fee` on the minute row. Returns the tenant, its agent ref and per call
    `(call_id, engine_call_id, charge)`."""
    ref = f"ag_{uuid.uuid4().hex[:12]}"
    tenant_id, agent_id = await _seed_tenant(ref)
    calls: list[tuple[uuid.UUID, str, str]] = []
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
        for seconds, qty, cost, charge in PRODUCTION_CALLS:
            call_id = uuid7()
            ecid = f"out_{call_id.hex}"
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, duration_s, created_at, updated_at) VALUES (:id, :tid, :aid, "
                    ":ecid, 'outbound', 'completed', :d, now(), now())"
                ),
                {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": ecid, "d": seconds},
            )
            meta = {
                "engine_rate_key": "premium",
                "billed_minutes": str(Decimal(seconds + 29) // 30 / 2),
                "inr_per_min": "2.500000",
                "voice_tier": "clear",
                LEDGER_RUNG_KEY: "premium",
            }
            unit = (Decimal(cost) / Decimal(qty)).quantize(MONEY_Q, rounding=ROUNDING)
            for unit_type, row_qty, row_unit in (
                ("telephony_s", Decimal(seconds), None),
                ("platform_min", Decimal(qty), unit),
            ):
                await session.execute(
                    text(
                        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                        "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, "
                        ":q, :p, :at, CAST(:m AS jsonb), now())"
                    ),
                    {
                        "i": uuid7(),
                        "t": tenant_id,
                        "c": call_id,
                        "u": unit_type,
                        "q": row_qty,
                        "p": row_unit,
                        "at": datetime(2026, 10, 10, 9, tzinfo=UTC),
                        "m": json.dumps(meta),
                    },
                )
            # What the client paid for the call: the wallet debit the meter writes.
            await record_entry(
                session,
                tenant_id=tenant_id,
                delta=Decimal("-3.00"),
                reason="usage",
                ref=str(call_id),
                allow_negative=True,
            )
            calls.append((call_id, ecid, charge))
    return tenant_id, ref, calls


async def _ledger(tenant_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        credit = (
            await session.execute(
                text("SELECT count(*), sum(delta) FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).one()
        billed = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid FROM usage_events "
                    "WHERE tenant_id = :t AND unit_type <> 'other' ORDER BY id"
                ),
                {"t": tenant_id},
            )
        ).all()
        restated = (
            await session.execute(
                text(
                    "SELECT call_id, qty, unit_cost_paid, occurred_at, meta FROM usage_events "
                    "WHERE tenant_id = :t AND unit_type = 'other' AND meta->>'kind' = :k "
                    "ORDER BY call_id"
                ),
                {"t": tenant_id, "k": engine_charges.FEE_RESTATEMENT_META_KIND},
            )
        ).all()
    return {"credit": tuple(credit), "billed": [tuple(r) for r in billed], "restated": restated}


@pytest.mark.rls
async def test_the_missing_fee_is_appended_once_and_moves_only_our_cost(on_band: Any) -> None:
    tenant_id, _ref, calls = await _production_tenant()
    before = await _ledger(tenant_id)

    # Two sweeps at once write one row per call between them.
    first, second = await asyncio.gather(
        engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10")),
        engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10")),
    )
    assert sorted(d for _c, d in first + second) == [
        Decimal("0.1250"),
        Decimal("0.2500"),
        Decimal("0.3750"),
    ]
    assert await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10")) == []

    after = await _ledger(tenant_id)
    # The client's side is untouched: the wallet, and every row a bill is priced from.
    assert after["credit"] == before["credit"]
    assert after["billed"] == before["billed"]
    restated = after["restated"]
    assert len(restated) == 3
    assert {row[0] for row in restated} == {call_id for call_id, _e, _c in calls}
    for _call, qty, cost, occurred_at, meta in restated:
        assert qty == 1 and cost > 0
        assert occurred_at == datetime(2026, 10, 10, 9, tzinfo=UTC)
        assert meta["fee"] == "0.10" and meta["corrected_engine_rate_key"] == "premium"
        assert meta["voice_tier"] == "clear" and meta[LEDGER_RUNG_KEY] == "premium"
        # Never read back as a minute to restate, nor as a cost-unit restatement target.
        assert "engine_rate_key" not in meta and "source_currency" not in meta


@pytest.mark.rls
async def test_a_minute_metered_with_the_fee_is_not_restated() -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    fee_call = uuid7()
    async with tenant_session(tenant_id) as session:
        # A call metered after the fix: its minute row says which fee it already includes.
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) SELECT :id, tenant_id, agent_id, :ecid, "
                "'outbound', 'completed', now(), now() FROM calls WHERE tenant_id = :t LIMIT 1"
            ),
            {"id": fee_call, "t": tenant_id, "ecid": f"out_{fee_call.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, 2.75, now(), CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": fee_call,
                "m": json.dumps({"engine_rate_key": "premium", "topup_fee": "0.10"}),
            },
        )
    written = await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))
    assert fee_call not in {call_id for call_id, _d in written}
    assert len(written) == 3


# --- the reconciler ------------------------------------------------------------------------


class _Engine:
    name = "thinnest"

    def __init__(self, charges: list[EngineCharge]) -> None:
        self._charges = charges

    def holds_credentials(self) -> bool:
        return True

    async def list_call_charges(self, *, since: date) -> EngineChargeListing:
        return EngineChargeListing(charges=list(self._charges), complete=True)


@pytest.mark.rls
async def test_the_sweep_alarms_once_then_clears_after_the_fee_is_restated(
    monkeypatch: pytest.MonkeyPatch, on_band: Any
) -> None:
    import apps.workers.workspace_walk as workspace_walk

    tenant_id, ref, calls = await _production_tenant()
    engine = _Engine([EngineCharge(ecid, ref, Decimal(charge)) for _c, ecid, charge in calls])

    async def _no_clients(**_kw: Any) -> list[Any]:
        return []

    async def _tenant_of(_engine: str, agent_ref: str | None) -> uuid.UUID | None:
        return tenant_id if agent_ref == ref else None

    raised: list[tuple[str, str | None]] = []
    resolved: list[tuple[str, str | None]] = []
    monkeypatch.setattr(workspace_walk, "active_workspaces", _no_clients)
    monkeypatch.setattr(engine_charges, "get_engine", lambda: engine)
    # Only this tenant: the shared test database holds other suites' routes on this engine.
    monkeypatch.setattr(engine_charges, "_tenant_of", _tenant_of)
    monkeypatch.setattr(
        engine_charges,
        "alert",
        lambda _s, code, *, episode=None, **_kw: raised.append((code, episode)),
    )
    monkeypatch.setattr(
        engine_charges,
        "resolve_alert",
        lambda _s, code, *, episode=None: resolved.append((code, episode)),
    )
    monkeypatch.setattr(engine_charges, "_ALARMED_KEY", f"test:{uuid.uuid4()}:{{engine}}")

    real_restate = engine_charges.restate_minutes_without_fee

    async def _before_the_fix(_engine: str) -> int:
        return 0

    # Before the fix: the three calls mismatch. The first sweep alarms, the next is quiet.
    monkeypatch.setattr(engine_charges, "restate_minutes_without_fee", _before_the_fix)
    first = await engine_charges.reconcile_engine_charges({})
    assert "matched=3" in first and "mismatched=3" in first
    assert raised == [("engine_charge_mismatch", "thinnest")]
    second = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=3" in second
    assert raised == [("engine_charge_mismatch", "thinnest")], "same calls, no second alarm"
    assert resolved == []

    # The fix: the sweep restates the fee first, the three calls now match, the episode ends.
    async def _only_this_tenant(engine_name: str) -> int:
        assert await real_restate("pipecat") == 0
        written = await engine_charges.restate_tenant_minutes(tenant_id, fee=topup_fee(engine_name))
        return len(written)

    monkeypatch.setattr(engine_charges, "restate_minutes_without_fee", _only_this_tenant)
    third = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=0" in third and "restated=3" in third
    assert resolved == [("engine_charge_mismatch", "thinnest")]
    assert raised == [("engine_charge_mismatch", "thinnest")]

    fourth = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=0" in fourth and "restated=0" in fourth

    # Per call, the cost the reconciler reads is now the charge with its fee.
    async with tenant_session(tenant_id) as session:
        for call_id, _ecid, charge in calls:
            total = (
                await session.execute(
                    text(
                        "SELECT sum(qty * unit_cost_paid) FROM usage_events "
                        "WHERE call_id = :c AND (unit_type = 'platform_min' "
                        "OR meta->>'kind' = :k)"
                    ),
                    {"c": call_id, "k": engine_charges.FEE_RESTATEMENT_META_KIND},
                )
            ).scalar_one()
            expected = cost_with_fee(Decimal(charge), fee=Decimal("0.10"))
            assert engine_charges.within_tolerance(
                Decimal(str(total)).quantize(MONEY_Q, rounding=ROUNDING), expected
            )
            assert abs(Decimal(str(total)) - expected) < Decimal("0.001")


@pytest.mark.rls
async def test_the_restatement_walks_every_tenant_on_the_engine(on_band: Any) -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    assert await engine_charges.restate_minutes_without_fee("thinnest") >= 3
    after = await _ledger(tenant_id)
    assert len(after["restated"]) == 3
    assert await engine_charges.restate_minutes_without_fee("pipecat") == 0
