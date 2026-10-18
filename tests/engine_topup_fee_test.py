"""The ThinnestAI wallet top-up fee is part of a minute's cost (D-723), and it is 2.36% on every
plan (ThinnestAI email of 12 Oct 2026), not the 10% / 9% it was first read as.

The fixtures are the three production calls `engine_charge_mismatch` paged on, 10 Oct 2026:
rate key `premium`, attested ₹2.50 posted, metered without the fee. The "expected" column is
the charge with the 10% fee D-723 restated them at, which the correction then takes back to
2.36%.

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
from calevate_shared.engine import ExecutionListing, ExecutionSnapshot
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


@pytest.mark.parametrize("band", ["premium", "studio"])
async def test_a_minute_is_metered_at_the_posted_rate_plus_the_one_fee(
    on_band: Any, band: str
) -> None:
    """2.36% on every plan: the band Clear is sold on no longer moves the fee."""
    fee = "0.0236"
    expected = ("1.2795", "3.8385", "2.5590")
    on_band(band)
    assert thinnest_topup_fee() == topup_fee("thinnest") == Decimal(fee)
    assert topup_fee("fake") == 0
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

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        # A listing from before billing was listed: the sweep falls back to Get Call.
        return ExecutionListing(snapshots=[], complete=True)

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        # The sweep reads Get Call for the calls it settles (D-796); no billing to check.
        return ExecutionSnapshot(
            engine_call_id=call_id,
            status="completed",
            raw_status="completed",
            terminal=True,
            billable_ready=True,
        )


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

    async def _off(_engine: str) -> int:
        return 0

    async def _correct_this_tenant(engine_name: str) -> int:
        written = await engine_charges.correct_tenant_fees(tenant_id, fee=topup_fee(engine_name))
        return len(written)

    # As on 12 Oct 2026: D-723 restated the three calls at 10%. Two now cost more than their
    # charge with 2.36% by more than the tolerance (the 18 s call is inside it). The first
    # sweep alarms, the next is quiet.
    assert len(await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))) == 3
    monkeypatch.setattr(engine_charges, "restate_minutes_without_fee", _off)
    monkeypatch.setattr(engine_charges, "correct_overstated_fees", _off)
    first = await engine_charges.reconcile_engine_charges({})
    assert "matched=3" in first and "mismatched=2" in first
    assert raised == [("engine_charge_mismatch", "thinnest")]
    second = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=2" in second
    assert raised == [("engine_charge_mismatch", "thinnest")], "same calls, no second alarm"
    assert resolved == []

    # The fix: the sweep corrects the fee, the three calls now match, the episode ends.
    monkeypatch.setattr(engine_charges, "correct_overstated_fees", _correct_this_tenant)
    third = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=0" in third and "corrected=3" in third
    assert resolved == [("engine_charge_mismatch", "thinnest")]
    assert raised == [("engine_charge_mismatch", "thinnest")]

    fourth = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=0" in fourth and "corrected=0" in fourth

    # Per call, the cost the reconciler reads is now the charge with its fee.
    for call_id, _ecid, charge in calls:
        expected = cost_with_fee(Decimal(charge), fee=Decimal("0.0236"))
        assert await _minute_cost(tenant_id, call_id) == expected


@pytest.mark.rls
async def test_a_minute_never_restated_is_restated_at_the_stated_fee(
    monkeypatch: pytest.MonkeyPatch, on_band: Any
) -> None:
    """A minute metered without the fee and never restated is restated at 2.36% by the real
    sweep, and needs no correction."""
    import apps.workers.workspace_walk as workspace_walk

    tenant_id, ref, calls = await _production_tenant()
    engine = _Engine([EngineCharge(ecid, ref, Decimal(charge)) for _c, ecid, charge in calls])
    real_restate = engine_charges.restate_minutes_without_fee

    async def _no_clients(**_kw: Any) -> list[Any]:
        return []

    async def _tenant_of(_engine: str, agent_ref: str | None) -> uuid.UUID | None:
        return tenant_id if agent_ref == ref else None

    async def _only_this_tenant(engine_name: str) -> int:
        assert await real_restate("fake") == 0
        written = await engine_charges.restate_tenant_minutes(tenant_id, fee=topup_fee(engine_name))
        return len(written)

    async def _correct_this_tenant(engine_name: str) -> int:
        written = await engine_charges.correct_tenant_fees(tenant_id, fee=topup_fee(engine_name))
        return len(written)

    monkeypatch.setattr(workspace_walk, "active_workspaces", _no_clients)
    monkeypatch.setattr(engine_charges, "get_engine", lambda: engine)
    monkeypatch.setattr(engine_charges, "_tenant_of", _tenant_of)
    monkeypatch.setattr(engine_charges, "alert", lambda *_a, **_kw: None)
    monkeypatch.setattr(engine_charges, "resolve_alert", lambda *_a, **_kw: None)
    monkeypatch.setattr(engine_charges, "_ALARMED_KEY", f"test:{uuid.uuid4()}:{{engine}}")
    monkeypatch.setattr(engine_charges, "restate_minutes_without_fee", _only_this_tenant)
    monkeypatch.setattr(engine_charges, "correct_overstated_fees", _correct_this_tenant)
    outcome = await engine_charges.reconcile_engine_charges({})
    assert "mismatched=0" in outcome and "restated=3 corrected=0" in outcome
    for call_id, _ecid, charge in calls:
        expected = cost_with_fee(Decimal(charge), fee=Decimal("0.0236"))
        assert await _minute_cost(tenant_id, call_id) == expected


@pytest.mark.rls
async def test_the_restatement_walks_every_tenant_on_the_engine(on_band: Any) -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    assert await engine_charges.restate_minutes_without_fee("thinnest") >= 3
    after = await _ledger(tenant_id)
    assert len(after["restated"]) == 3
    assert await engine_charges.restate_minutes_without_fee("fake") == 0


# --- the correction to 2.36% (12 Oct 2026) -------------------------------------------------


async def _corrections(tenant_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT call_id, qty, unit_cost_paid, occurred_at, meta FROM usage_events "
                        "WHERE tenant_id = :t AND unit_type = 'other' AND meta->>'kind' = :k "
                        "ORDER BY call_id"
                    ),
                    {"t": tenant_id, "k": engine_charges.FEE_CORRECTION_META_KIND},
                )
            ).all()
        )


async def _minute_cost(tenant_id: uuid.UUID, call_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text(
                    "SELECT sum(qty * unit_cost_paid) FROM usage_events WHERE call_id = :c "
                    "AND (unit_type = 'platform_min' OR meta->>'kind' IN (:r, :k))"
                ),
                {
                    "c": call_id,
                    "r": engine_charges.FEE_RESTATEMENT_META_KIND,
                    "k": engine_charges.FEE_CORRECTION_META_KIND,
                },
            )
        ).scalar_one()
    return Decimal(str(total)).quantize(MONEY_Q, rounding=ROUNDING)


@pytest.mark.rls
async def test_a_restatement_written_at_ten_percent_is_taken_back_to_the_stated_fee() -> None:
    """D-723 restated the production calls at 10%; the correction appends the excess as a
    negative row, once per call, so each call costs its charge with 2.36%.

    FAILS IF: the correction rewrites a row, writes twice, touches the client's side, or
    leaves a call at anything but charge x 1.0236."""
    tenant_id, _ref, calls = await _production_tenant()
    await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))
    before = await _ledger(tenant_id)

    first, second = await asyncio.gather(
        engine_charges.correct_tenant_fees(tenant_id, fee=Decimal("0.0236")),
        engine_charges.correct_tenant_fees(tenant_id, fee=Decimal("0.0236")),
    )
    assert sorted(d for _c, d in first + second) == [
        Decimal("0.0955"),
        Decimal("0.1910"),
        Decimal("0.2865"),
    ]
    assert await engine_charges.correct_tenant_fees(tenant_id, fee=Decimal("0.0236")) == []

    after = await _ledger(tenant_id)
    assert after["credit"] == before["credit"]
    assert after["billed"] == before["billed"]
    assert after["restated"] == before["restated"]
    corrections = await _corrections(tenant_id)
    assert {row[0] for row in corrections} == {call_id for call_id, _e, _c in calls}
    for _call, qty, cost, occurred_at, meta in corrections:
        assert qty == 1 and cost < 0
        assert occurred_at == datetime(2026, 10, 10, 9, tzinfo=UTC)
        assert meta["fee"] == "0.0236" and meta["fee_was"] == "0.10"
        assert meta["corrected_row"] == engine_charges.FEE_RESTATEMENT_META_KIND
        assert meta["corrected_engine_rate_key"] == "premium"
        assert meta["voice_tier"] == "clear" and meta[LEDGER_RUNG_KEY] == "premium"
        assert "engine_rate_key" not in meta
    for call_id, _ecid, charge in calls:
        assert await _minute_cost(tenant_id, call_id) == cost_with_fee(
            Decimal(charge), fee=Decimal("0.0236")
        )


async def _minute_with_fee(tenant_id: uuid.UUID, *, fee: str, cost: str, priced: bool) -> uuid.UUID:
    """A call metered after D-723: one minute row carrying the fee its cost includes."""
    call_id = uuid7()
    meta: dict[str, str] = {"engine_rate_key": "premium", "topup_fee": fee, "voice_tier": "clear"}
    if priced:
        meta |= {"billed_minutes": "1.0", "inr_per_min": "2.500000"}
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) SELECT :id, tenant_id, agent_id, :ecid, "
                "'outbound', 'completed', now(), now() FROM calls WHERE tenant_id = :t LIMIT 1"
            ),
            {"id": call_id, "t": tenant_id, "ecid": f"out_{call_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, :p, now(), CAST(:m AS jsonb), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "p": Decimal(cost), "m": json.dumps(meta)},
        )
    return call_id


@pytest.mark.rls
async def test_a_minute_metered_with_a_higher_fee_is_corrected_and_one_at_the_fee_is_not() -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    ten = await _minute_with_fee(tenant_id, fee="0.10", cost="2.75", priced=True)
    nine = await _minute_with_fee(tenant_id, fee="0.09", cost="2.7250", priced=False)
    today = await _minute_with_fee(tenant_id, fee="0.0236", cost="2.5590", priced=True)
    written = dict(await engine_charges.correct_tenant_fees(tenant_id, fee=Decimal("0.0236")))
    # Priced from its own minutes and rate where recorded, from its fee otherwise.
    assert written == {ten: Decimal("0.1910"), nine: Decimal("0.1660")}
    assert today not in written
    assert await _minute_cost(tenant_id, ten) == Decimal("2.5590")
    assert await _minute_cost(tenant_id, nine) == Decimal("2.5590")
    rows = {row[0]: row[4] for row in await _corrections(tenant_id)}
    assert rows[ten]["corrected_row"] == "platform_min" and rows[ten]["fee_was"] == "0.10"
    assert rows[nine]["fee_was"] == "0.09"


async def _zero_length_minutes(tenant_id: uuid.UUID, meta: dict[str, str], count: int) -> None:
    """Minute rows of zero-length calls (cost ₹0) whose call ids sort before every other."""
    async with tenant_session(tenant_id) as session:
        for _n in range(count):
            call_id = uuid.UUID(int=uuid.uuid4().int >> 64)
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, created_at, updated_at) SELECT :id, tenant_id, agent_id, :ecid, "
                    "'outbound', 'completed', now(), now() FROM calls WHERE tenant_id = :t "
                    "LIMIT 1"
                ),
                {"id": call_id, "t": tenant_id, "ecid": f"out_{uuid.uuid4().hex}"},
            )
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    "'platform_min', 0, 0, now(), CAST(:m AS jsonb), now())"
                ),
                {"i": uuid7(), "t": tenant_id, "c": call_id, "m": json.dumps(meta)},
            )


@pytest.mark.rls
async def test_zero_cost_minutes_never_hold_the_restatement_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A ₹0 minute has no fee to restate and is never written for, so if the batch selected
    # it, it would head every hourly batch and the calls after it would never be restated.
    tenant_id, _ref, calls = await _production_tenant()
    await _zero_length_minutes(tenant_id, {"engine_rate_key": "premium"}, 2)
    monkeypatch.setattr(engine_charges, "_RESTATE_BATCH", 2)
    written = await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))
    written += await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))
    assert {call_id for call_id, _d in written} == {call_id for call_id, _e, _c in calls}


@pytest.mark.rls
async def test_zero_cost_minutes_never_hold_the_correction_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    await _zero_length_minutes(tenant_id, {"engine_rate_key": "premium", "topup_fee": "0.10"}, 2)
    ten = await _minute_with_fee(tenant_id, fee="0.10", cost="2.75", priced=True)
    monkeypatch.setattr(engine_charges, "_RESTATE_BATCH", 2)
    written = dict(await engine_charges.correct_tenant_fees(tenant_id, fee=Decimal("0.0236")))
    assert written == {ten: Decimal("0.1910")}


def test_the_excess_is_zero_when_nothing_is_over_the_fee() -> None:
    fee = Decimal("0.0236")
    excess = engine_charges.fee_excess
    assert excess("platform_min", Decimal("2.5590"), {"topup_fee": "0.0236"}, fee=fee) == 0
    assert excess("platform_min", Decimal("2.50"), {}, fee=fee) == 0
    restated_at_fee = {"fee": "0.0236", "metered_inr": "2.50"}
    assert excess("other", Decimal("0.0590"), restated_at_fee, fee=fee) == 0
    assert excess("other", Decimal("0.25"), {"fee": "0.10"}, fee=fee) == 0


@pytest.mark.rls
async def test_the_correction_walks_every_tenant_on_the_engine(on_band: Any) -> None:
    tenant_id, _ref, _calls = await _production_tenant()
    await engine_charges.restate_tenant_minutes(tenant_id, fee=Decimal("0.10"))
    assert await engine_charges.correct_overstated_fees("thinnest") >= 3
    assert len(await _corrections(tenant_id)) == 3
    assert await engine_charges.correct_overstated_fees("fake") == 0
