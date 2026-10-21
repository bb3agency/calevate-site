"""The number an inbound call rang, and why a booked call never rang (D-842).

ThinnestAI's call record leaves `from` null on a call that came in (snapshots/2026-10-19/
pages/api-reference/calls/get-call.md:878-883), so the pipeline takes the number from the
answering agent when it holds exactly one, and the brought-number check reads the agent's
numbers when it holds several. A booked call that could not be placed carries `error`
(get-call.md:1027-1031); the one case the docs word exactly is a number lent to another agent
(channels/phone-numbers.md:696-702).

SHARED DATABASE DISCIPLINE: every row is minted here and every assertion is scoped to it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.api.billing.engine_minutes import engine_minute_cost
from apps.api.crm.service import NOT_PLACED_WORDS, get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import NOT_PLACED_REASONS
from sqlalchemy import text
from tests.healer_number_forward_test import _attest
from tests.smoke_pipeline_test import _seed_tenant

_LENT = "The number this call was to ring from is no longer on this agent."


def _number() -> str:
    return f"+9140{uuid.uuid4().int % 100_000_000:08d}"


def _snapshot(*, direction: str = "inbound", **update: object) -> ExecutionSnapshot:
    now = datetime.now(UTC)
    base = ExecutionSnapshot(
        engine_call_id=f"np_{uuid.uuid4().hex}",
        direction="inbound" if direction == "inbound" else "outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=30),
        ended_at=now,
        duration_s=30,
        from_e164="+919812345678" if direction == "inbound" else None,
    )
    return base.model_copy(update=update)


async def _attach(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, owned: bool) -> str:
    e164 = _number()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, engine_owned, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, :o, now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": e164, "o": owned},
        )
    return e164


async def _to_e164(tenant_id: uuid.UUID, call_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(text("SELECT to_e164 FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar()
    return None if value is None else str(value)


# --- the adapter ---------------------------------------------------------------------------


def test_an_inbound_call_names_the_caller_and_not_the_number_it_rang() -> None:
    engine = ThinnestEngine(api_key="ta_x")
    inbound = engine.snapshot_from_delivery(
        {
            "data": {
                "callRef": "c_1",
                "status": "completed",
                "direction": "inbound",
                "phone": "+919812345678",
                "from": None,
            }
        }
    )
    outbound = engine.snapshot_from_delivery(
        {
            "data": {
                "id": "out_1",
                "status": "completed",
                "direction": "outbound",
                "phone": "+919812345678",
                "from": "+914049998888",
            }
        }
    )
    assert (inbound.from_e164, inbound.to_e164) == ("+919812345678", None)
    assert (outbound.from_e164, outbound.to_e164) == ("+914049998888", "+919812345678")


def test_an_inbound_call_carrying_to_names_the_number_it_rang() -> None:
    """Get Call / List Calls carry `to` on a call that came in (ThinnestAI's email of
    21 Oct 2026, §21.0, D-847); a call we placed keeps `from` and ignores `to`."""
    engine = ThinnestEngine(api_key="ta_x")
    call = {
        "callRef": "c_2",
        "status": "completed",
        "direction": "inbound",
        "phone": "+919812345678",
        "from": None,
        "to": "918045678901",
    }
    assert engine.snapshot_from_delivery({"data": call}).to_e164 == "+918045678901"
    assert engine.parse_webhook({"data": call}).to_e164 == "+918045678901"
    placed = {**call, "id": "out_2", "direction": "outbound", "from": "+914049998888"}
    snapshot = engine.snapshot_from_delivery({"data": placed})
    assert (snapshot.from_e164, snapshot.to_e164) == ("+914049998888", "+919812345678")


async def test_an_inbound_call_naming_its_number_keeps_it_over_the_agents() -> None:
    tenant_id, agent_id = await _seed_tenant(f"inbto_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=True)
    rang = _number()
    call_id = await pipeline._upsert_call(tenant_id, agent_id, _snapshot(to_e164=rang), None)
    assert await _to_e164(tenant_id, call_id) == rang


def test_a_booked_call_that_was_not_placed_carries_our_reason_only() -> None:
    engine = ThinnestEngine(api_key="ta_x")

    def reason(**call: object) -> str | None:
        snap = engine.snapshot_from_delivery({"data": {"id": "sch_1", **call}})
        return snap.not_placed_reason

    assert reason(status="failed", hangup="not_placed", error=_LENT) == "from_number_withdrawn"
    assert reason(status="failed", error=_LENT.upper().rstrip(".")) == "from_number_withdrawn"
    assert reason(status="failed", hangup="not_placed", error="+919812345678 is busy") == (
        "unstated"
    )
    assert reason(status="cancelled", hangup="not_placed", error=None) == "unstated"
    assert reason(status="completed", hangup="answered", error=None) is None


# --- the pipeline fills the number ----------------------------------------------------------


async def test_an_inbound_call_takes_the_number_of_an_agent_holding_exactly_one() -> None:
    tenant_id, agent_id = await _seed_tenant(f"inbone_{uuid.uuid4().hex[:10]}")
    ours = await _attach(tenant_id, agent_id, owned=True)
    call_id = await pipeline._upsert_call(tenant_id, agent_id, _snapshot(), None)
    assert await _to_e164(tenant_id, call_id) == ours


async def test_an_inbound_call_to_an_agent_with_two_numbers_names_none() -> None:
    tenant_id, agent_id = await _seed_tenant(f"inbtwo_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=True)
    await _attach(tenant_id, agent_id, owned=False)
    call_id = await pipeline._upsert_call(tenant_id, agent_id, _snapshot(), None)
    assert await _to_e164(tenant_id, call_id) is None


async def test_an_outbound_call_never_takes_the_agents_number() -> None:
    tenant_id, agent_id = await _seed_tenant(f"outnum_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=True)
    snapshot = _snapshot(direction="outbound", to_e164=None)
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, None)
    assert await _to_e164(tenant_id, call_id) is None


# --- the brought-number check without a number on the row ----------------------------------


async def _forward_cost(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, at: datetime, rate_key: str = "premium"
) -> Decimal:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, engine_rate_key, created_at, updated_at) VALUES "
                "('thinnest', :r, :t, :a, true, :k, now(), now())"
            ),
            {"r": f"np_{uuid.uuid4().hex}", "t": tenant_id, "a": agent_id, "k": rate_key},
        )
    call_id = await pipeline._upsert_call(tenant_id, agent_id, _snapshot(forwarded=True), None)
    assert await _to_e164(tenant_id, call_id) is None
    async with tenant_session(tenant_id) as session:
        cost = await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=Decimal(60),
            at=at,
            forwarded=True,
        )
    assert cost.inr_per_min is not None
    return cost.inr_per_min


async def test_a_forward_to_an_agent_whose_numbers_are_all_brought_costs_nothing() -> None:
    at = datetime(2002, 2, 4, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {"premium": "2.50"})
    tenant_id, agent_id = await _seed_tenant(f"npall_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=False)
    await _attach(tenant_id, agent_id, owned=False)
    assert await _forward_cost(tenant_id, agent_id, at) == Decimal(0)


async def test_a_forward_to_an_own_key_agent_with_only_brought_numbers_costs_nothing() -> None:
    """A brought-number forward bills zero seconds on every key set (§25.0, D-852)."""
    at = datetime(2002, 2, 6, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {"byok_voice": "1.50"})
    tenant_id, agent_id = await _seed_tenant(f"npown_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=False)
    await _attach(tenant_id, agent_id, owned=False)
    assert await _forward_cost(tenant_id, agent_id, at, "byok_voice") == Decimal(0)


async def test_a_forward_to_an_agent_holding_a_rented_number_stays_rented() -> None:
    at = datetime(2002, 2, 5, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    await _attest(at, {"premium": "2.50"})
    tenant_id, agent_id = await _seed_tenant(f"npmix_{uuid.uuid4().hex[:10]}")
    await _attach(tenant_id, agent_id, owned=False)
    await _attach(tenant_id, agent_id, owned=True)
    assert await _forward_cost(tenant_id, agent_id, at) == Decimal("2.50")


# --- the reason is stored as our code and shown in our words --------------------------------


async def test_the_not_placed_reason_is_stored_as_a_code_and_shown_as_our_sentence() -> None:
    tenant_id, agent_id = await _seed_tenant(f"npshow_{uuid.uuid4().hex[:10]}")
    snapshot = _snapshot(
        direction="outbound",
        status="failed",
        raw_status="failed",
        to_e164="+919812345678",
        not_placed_reason="from_number_withdrawn",
    )
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, None)
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT not_placed_reason FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
        detail = await get_call(session, call_id)
    assert stored == "from_number_withdrawn"
    assert detail.not_placed_reason == NOT_PLACED_WORDS["from_number_withdrawn"]


def test_every_reason_code_has_a_sentence() -> None:
    assert set(NOT_PLACED_WORDS) == set(NOT_PLACED_REASONS)
