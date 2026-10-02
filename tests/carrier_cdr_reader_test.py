"""`read_carrier_cdr` and `reconcile_carrier_cdrs`: the carrier's charge reaches OUR cost.

What the tests hold, in the order a reviewer asks:

1. pricing — an INR charge lands exact at the ledger's scale, anything else lands NULL and
   alarms, a CDR not yet written takes the retry ladder and then alarms;
2. no double billing — the client's billed minutes do not move and our cost moves by
   exactly the carrier's charge; one CDR writes at most one row however often it is read;
3. ordering — no cost row before the client's own `telephony_s` row exists, because the
   post-call meter treats a usage row as "already metered";
4. the sweep picks up exactly the metered calls whose carrier cost is unknown;
5. hard rule 1 — a CDR job naming another tenant's call writes nothing.

Run: uv run python -m pytest -q tests/carrier_cdr_reader_test.py
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.service import LEDGER_RUNG_KEY, margin_for_tenant, usage_summary
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierCdr
from apps.workers import carrier_events
from apps.workers.carrier_events import (
    CARRIER_CDR_META_KIND,
    CDR_JOB,
    carrier_cost_inr,
    read_carrier_cdr,
    reconcile_carrier_cdrs,
)
from arq import Retry
from sqlalchemy import text
from tests.carrier_event_job_test import (
    FakeCarrier,
    Recorder,
    install_fake_carrier,
    install_recorder,
    make_call,
    make_tenant,
)

pytestmark = [pytest.mark.rls]

_SECONDS = Decimal(95)


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> FakeCarrier:
    return install_fake_carrier(monkeypatch)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    return install_recorder(monkeypatch)


def _cdr(ccid: str, *, cost: str | None = "0.4560", currency: str | None = "INR") -> CarrierCdr:
    return CarrierCdr(
        carrier="vobiz",
        carrier_call_id=ccid,
        billed_seconds=93,
        duration_seconds=101,
        total_cost_inr=Decimal(cost) if cost is not None and currency == "INR" else None,
        currency=currency,
        answered_at=None,
        ended_at=None,
        hangup_cause="NORMAL_CLEARING",
    )


async def _metered_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, metered: bool = True, ended_ago_min: int = 0
) -> tuple[uuid.UUID, str]:
    """A finished call with the one `telephony_s` row the owned runtime's meter writes."""
    ccid = f"cuuid-{uuid.uuid4().hex}"
    call_id = await make_call(
        tenant_id, agent_id, status="completed", direction="inbound", carrier_call_id=ccid
    )
    ended = datetime.now(UTC) - timedelta(minutes=ended_ago_min)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET ended_at = :e WHERE id = :i"), {"e": ended, "i": call_id}
        )
        if metered:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    "'telephony_s', :q, NULL, :at, CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "q": _SECONDS,
                    "at": ended,
                    "m": json.dumps(
                        {
                            LEDGER_RUNG_KEY: "premium",
                            "voice_tier": "clear",
                            "duration_source": "worker_settlement",
                        }
                    ),
                },
            )
    return call_id, ccid


def _job(tenant_id: uuid.UUID, call_id: uuid.UUID, ccid: str) -> dict[str, Any]:
    return {
        "carrier": "vobiz",
        "carrier_call_id": ccid,
        "tenant_id": str(tenant_id),
        "call_id": str(call_id),
    }


async def _cost_rows(tenant_id: uuid.UUID, call_id: uuid.UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT qty, unit_cost_paid, meta, occurred_at FROM usage_events "
                        "WHERE call_id = :c AND unit_type = 'other'"
                    ),
                    {"c": call_id},
                )
            ).all()
        ]


# ------------------------------------------------------------------ pricing


def test_only_an_inr_charge_becomes_a_unit_cost() -> None:
    assert carrier_cost_inr(_cdr("a", cost="0.4560")) == Decimal("0.4560")
    # Quantized ONCE, half-up, at NUMERIC(12,4) — never through a float.
    assert carrier_cost_inr(_cdr("a", cost="0.123450")) == Decimal("0.1235")
    assert carrier_cost_inr(_cdr("a", currency="USD")) is None
    assert carrier_cost_inr(_cdr("a", cost=None)) is None
    assert carrier_cost_inr(_cdr("a", cost="-1.00")) is None


async def test_an_inr_cdr_records_our_cost_and_leaves_the_client_bill_alone(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.cdr = _cdr(ccid, cost="0.4560")
    async with tenant_session(tenant_id) as session:
        minutes_before = (await usage_summary(session, tenant_id=tenant_id))["minutes_used"]
        cost_before = Decimal(
            str((await margin_for_tenant(session, tenant_id=tenant_id))["cost_inr"])
        )

    assert await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid)) == "recorded"

    async with tenant_session(tenant_id) as session:
        minutes_after = (await usage_summary(session, tenant_id=tenant_id))["minutes_used"]
        cost_after = Decimal(
            str((await margin_for_tenant(session, tenant_id=tenant_id))["cost_inr"])
        )
    assert minutes_after == minutes_before, "a carrier CDR must not move what the client is billed"
    # The margin reports to the paisa; the row itself is exact (below).
    assert cost_after - cost_before == Decimal("0.46")

    [(qty, unit_cost, meta, _occurred_at)] = await _cost_rows(tenant_id, call_id)
    assert qty == Decimal(1) and unit_cost == Decimal("0.4560")
    assert meta["kind"] == CARRIER_CDR_META_KIND
    assert meta["cdr_ref"] == f"cdr:vobiz:{ccid}"
    assert meta["billed_seconds"] == 93 and meta["duration_seconds"] == 101
    assert Decimal(meta["billed_seconds_delta"]) == Decimal(93) - _SECONDS
    assert meta[LEDGER_RUNG_KEY] == "premium" and meta["voice_tier"] == "clear"
    assert "source_currency" not in meta
    assert seen.alerts == []


async def test_the_same_cdr_read_twice_writes_one_row(carrier: FakeCarrier, seen: Recorder) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.cdr = _cdr(ccid)

    assert await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid)) == "recorded"
    again = await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid))

    assert again == "already_recorded"
    assert len(await _cost_rows(tenant_id, call_id)) == 1


async def test_a_charge_in_another_currency_is_recorded_unpriced_and_alarms(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.cdr = _cdr(ccid, cost="0.0055", currency="USD")

    verdict = await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid))

    assert verdict == "recorded_unpriced"
    [(_qty, unit_cost, meta, _at)] = await _cost_rows(tenant_id, call_id)
    assert unit_cost is None and meta["currency"] == "USD"
    assert [a[1] for a in seen.alerts] == ["carrier_cdr_cost_unpriced"]


async def test_a_cdr_not_yet_written_is_retried_then_alarms(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.cdr = None

    for attempt in (1, 2):
        with pytest.raises(Retry):
            await read_carrier_cdr({"job_try": attempt}, _job(tenant_id, call_id, ccid))
    assert await read_carrier_cdr({"job_try": 3}, _job(tenant_id, call_id, ccid)) == "cdr_missing"

    assert [a[1] for a in seen.alerts] == ["carrier_cdr_missing"]
    assert await _cost_rows(tenant_id, call_id) == []


async def test_a_carrier_that_cannot_read_cdrs_is_logged_not_alarmed(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.fetch_error = ProblemError(
        kind="dependency",
        code="carrier_cdr_unavailable",
        title="No CDR reader",
        detail="This carrier has no CDR reader.",
    )

    verdict = await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid))

    assert verdict == "refused:carrier_cdr_unavailable"
    assert seen.alerts == []


async def test_a_transient_read_failure_takes_the_ladder_then_alarms(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id)
    carrier.fetch_error = ConnectionError("carrier unreachable")

    with pytest.raises(Retry):
        await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid))
    with pytest.raises(ConnectionError):
        await read_carrier_cdr({"job_try": 3}, _job(tenant_id, call_id, ccid))
    assert [a[1] for a in seen.alerts] == ["carrier_cdr_read_abandoned"]


async def test_no_cost_row_lands_before_the_client_is_metered(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id, ccid = await _metered_call(tenant_id, agent_id, metered=False)
    carrier.cdr = _cdr(ccid)

    with pytest.raises(Retry):
        await read_carrier_cdr({"job_try": 1}, _job(tenant_id, call_id, ccid))
    verdict = await read_carrier_cdr({"job_try": 3}, _job(tenant_id, call_id, ccid))

    assert verdict == "awaiting_metering"
    assert await _cost_rows(tenant_id, call_id) == []
    assert seen.alerts == []


async def test_a_job_naming_another_tenants_call_writes_nothing(
    carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_a, agent_a, _ = await make_tenant()
    tenant_b, _agent_b, _ = await make_tenant()
    call_id, ccid = await _metered_call(tenant_a, agent_a)
    carrier.cdr = _cdr(ccid)

    with pytest.raises(ProblemError):
        await read_carrier_cdr({"job_try": 1}, _job(tenant_b, call_id, ccid))

    assert await _cost_rows(tenant_a, call_id) == []
    assert [a[1] for a in seen.alerts] == ["carrier_cdr_read_abandoned"]


async def test_a_malformed_cdr_job_is_permanent(seen: Recorder) -> None:
    with pytest.raises(ProblemError):
        await read_carrier_cdr({"job_try": 1}, {"carrier": "vobiz"})
    assert [a[1] for a in seen.alerts] == ["carrier_cdr_read_abandoned"]


# ------------------------------------------------------------------ the sweep


async def test_the_sweep_enqueues_exactly_the_metered_calls_without_a_carrier_cost(
    monkeypatch: pytest.MonkeyPatch, carrier: FakeCarrier, seen: Recorder
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    owed, owed_ccid = await _metered_call(tenant_id, agent_id, ended_ago_min=20)
    already, already_ccid = await _metered_call(tenant_id, agent_id, ended_ago_min=20)
    await _metered_call(tenant_id, agent_id, metered=False, ended_ago_min=20)
    await _metered_call(tenant_id, agent_id, ended_ago_min=2)  # the hangup path's turn
    await make_call(tenant_id, agent_id, status="completed", direction="inbound")  # no carrier id
    carrier.cdr = _cdr(already_ccid)
    assert await read_carrier_cdr({"job_try": 1}, _job(tenant_id, already, already_ccid)) == (
        "recorded"
    )

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(carrier_events, "callable_tenants", _only_this_tenant)
    outcome = await reconcile_carrier_cdrs({})

    assert outcome.startswith("enqueued=1 unreached=0 truncated=False")
    [(_name, body, job_id, kw)] = [e for e in seen.enqueued if e[0] == CDR_JOB]
    assert body["call_id"] == str(owed) and body["carrier_call_id"] == owed_ccid
    assert job_id == f"{CDR_JOB}:vobiz:{owed_ccid}"
    assert kw == {}
    assert seen.alerts == []


async def test_a_tenant_the_sweep_cannot_read_is_reported(
    monkeypatch: pytest.MonkeyPatch, seen: Recorder
) -> None:
    async def _a_tenant_with_no_session() -> list[uuid.UUID]:
        return [uuid.uuid4()]

    def _broken(_tenant_id: uuid.UUID) -> Any:
        raise ConnectionError("pool exhausted")

    monkeypatch.setattr(carrier_events, "callable_tenants", _a_tenant_with_no_session)
    monkeypatch.setattr(carrier_events, "tenant_session", _broken)

    outcome = await reconcile_carrier_cdrs({})

    assert outcome.startswith("enqueued=0 unreached=1")
    assert [a[1] for a in seen.alerts] == ["carrier_cdr_sweep_incomplete"]
