"""The Cartesia synthesizer leg costs money the engine does not report (D-547, plan §D).

Two facts collide on a BYOK voice: Bolna charges nothing for a component you bring your
own key for (their pricing page, plan ADDENDUM 3 §3.5), and Cartesia bills a monthly PLAN
with a character allotment rather than a per-call charge. So the engine's `tts_inr` is ₹0
and there is no vendor number to meter — the cost is the operator-attested plan rate times
the characters OUR transcript says the agent spoke.

What these tests pin is the pair of failure modes that follow: metering the leg at zero
(a fabricated zero on an append-only ledger, which reads as a working leg and overstates
margin forever) and metering it at a rate nobody read (hard rule 7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.model_pricing import attest_tts_price
from apps.workers import pipeline
from apps.workers.pipeline import _tts_cost_rows
from sqlalchemy import text


async def _tenant_with_call(*, agent_chars: str) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Studio Clinic",
        slug=f"cart-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    # The agent the organisation is provisioned with. `_tts_cost_rows` never reads it — it
    # reads the TRANSCRIPT and the attested price, and the voice is decided by its caller —
    # but `calls.agent_id` is NOT NULL, so a call has to belong to one.
    agent_id: uuid.UUID = created["agent_id"]
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        for idx, (speaker, text_value) in enumerate(
            [("agent", "x" * int(agent_chars)), ("caller", "y" * 5000)]
        ):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, "
                    "text, text_redacted, created_at) VALUES (:i, :t, :c, :x, :s, :v, :v, "
                    "now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "x": idx,
                    "s": speaker,
                    "v": text_value,
                },
            )
    return tenant_id, call_id


async def _operator() -> uuid.UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def test_a_sarvam_call_still_meters_the_engines_own_leg_figure() -> None:
    """The engine buys Sarvam synthesis and reports what it charged. Nothing about D-547
    moves that row — its `qty` is still 1 and its price is still the whole leg."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        rows = await _tts_cost_rows(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            voice="sarvam",
            agent_chars=agent_chars,
            engine_tts_inr=Decimal("1.6200"),
            at=datetime.now(UTC),
        )
    assert rows == [("tts_chars", Decimal(1), Decimal("1.6200"))]


async def test_a_sarvam_call_the_engine_priced_nothing_for_writes_no_row() -> None:
    """`None` from the adapter is "the payload said nothing", not "it was free", and the
    difference is the whole of D-370: a ₹0 row is indistinguishable from a working leg."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        assert (
            await _tts_cost_rows(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                voice="sarvam",
                agent_chars=agent_chars,
                engine_tts_inr=None,
                at=datetime.now(UTC),
            )
            == []
        )


async def test_a_cartesia_call_meters_our_own_character_count_at_the_attested_rate() -> None:
    """The agent spoke 900 characters and the plan's attested rate is ₹3.4496 per 1,000,
    so the row is 0.9 thousand-characters priced at 3.4496 — ₹3.10464 of real cost that
    the engine reported as zero. The AGENT's turns only: the caller's 5,000 characters
    cost STT seconds, not TTS characters."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Startup plan ₹4,312 / 1.25M characters",
            actor_id=await _operator(),
        )
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        rows = await _tts_cost_rows(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            voice="cartesia",
            agent_chars=agent_chars,
            # ₹0 from the engine, which is the whole reason this seam exists.
            engine_tts_inr=Decimal("0"),
            at=at,
        )
    # ONE row: a ₹0 engine figure is the expected one on a BYOK leg, so there is nothing
    # of the engine's to record beside ours.
    ((unit_type, qty, unit_cost),) = rows
    assert unit_type == "tts_kchars"
    assert qty == Decimal("0.9")
    assert unit_cost == Decimal("3.4496")
    # What every reader of this ledger does with the pair, and the reason the unit is a
    # THOUSAND characters: per character the rate would store as 0.0034 and this product
    # would be ₹3.06 — our own cost, 1.4% light, for ever.
    assert qty * unit_cost == Decimal("3.10464")


async def test_a_cartesia_call_with_no_attested_price_writes_no_row_rather_than_a_zero() -> None:
    """Hard rule 7 has no REPORTED tier and no zero tier. The voice should not have been
    offerable without a price, so this state is an operator error somebody is told about —
    never a number this code invents."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        assert (
            await _tts_cost_rows(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                voice="cartesia",
                agent_chars=agent_chars,
                engine_tts_inr=Decimal("0"),
                at=datetime(2024, 1, 1, tzinfo=UTC),
            )
            == []
        )


async def test_a_cartesia_call_whose_agent_said_nothing_meters_nothing() -> None:
    """No characters, no synthesis, no cost. `qty = 0` would be read as a WHOLE-LEG row
    by `_ROW_COST_SQL` (D-370) and would put the plan's rate on a call that never spoke."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="0")
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Startup plan",
            actor_id=await _operator(),
        )
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        assert (
            await _tts_cost_rows(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                voice="cartesia",
                agent_chars=agent_chars,
                engine_tts_inr=Decimal("0"),
                at=at,
            )
            == []
        )


async def test_a_non_zero_engine_charge_on_a_cartesia_call_is_metered_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPERATIONS §2 GATE 51 IS UNKNOWN, AND THIS IS ITS ONLY MEASUREMENT.

    Bolna's pricing page says a component you bring your own key for is not charged, and
    this seam used to ACT on that reading: on a Cartesia call it ignored `engine_tts_inr`
    entirely. If the reading is wrong, a real vendor charge vanished with no row and no
    alarm — every Cartesia call throwing away the one observation that could settle the
    gate, while the margin model quietly ran light.

    So a non-zero figure is now metered BESIDE ours (they are different money: theirs is
    the engine's charge, ours is the Cartesia plan cost for the characters our transcript
    says the agent spoke) and it raises, because a row nobody reads is not a measurement.
    """
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Startup plan",
            actor_id=await _operator(),
        )
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pipeline, "alert", lambda stage, code, **kw: raised.append((str(stage), code))
    )
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        rows = await _tts_cost_rows(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            voice="cartesia",
            agent_chars=agent_chars,
            engine_tts_inr=Decimal("0.4100"),
            at=at,
        )
    assert rows == [
        ("tts_chars", Decimal(1), Decimal("0.4100")),
        ("tts_kchars", Decimal("0.9"), Decimal("3.4496")),
    ], "the engine's charge AND our plan cost, neither standing in for the other"
    assert raised == [("WORKER_TERMINAL", "engine_billed_byok_tts")]


async def test_a_cartesia_call_the_engine_charged_nothing_for_raises_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """₹0 is the EXPECTED figure on a BYOK leg, so it is not news and must not page
    anybody. An alarm that fires on every call is an alarm nobody reads."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Startup plan",
            actor_id=await _operator(),
        )
    raised: list[str] = []
    monkeypatch.setattr(pipeline, "alert", lambda stage, code, **kw: raised.append(code))
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        rows = await _tts_cost_rows(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            voice="cartesia",
            agent_chars=agent_chars,
            engine_tts_inr=Decimal("0"),
            at=at,
        )
    assert [row[0] for row in rows] == ["tts_kchars"]
    assert raised == []


async def test_the_engines_charge_survives_a_cartesia_call_with_no_attested_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two facts are independent. A withdrawn price means OUR plan cost cannot be
    metered — that is its own alarm and its own missing row — but a charge the engine
    really made is still a charge, and dropping it would lose the second half of the money
    to the first half's gap."""
    tenant_id, call_id = await _tenant_with_call(agent_chars="900")
    raised: list[str] = []
    monkeypatch.setattr(pipeline, "alert", lambda stage, code, **kw: raised.append(code))
    async with tenant_session(tenant_id) as session:
        # The characters come from the TRANSCRIPT through the meter's own reader, which
        # is where `_meter` gets them too (D-557 hoisted the query out of this function
        # so the fleet speaking-rate counter and this cost row count one call once).
        _, agent_chars = await pipeline._agent_transcript(
            session, tenant_id=tenant_id, call_id=call_id
        )
        rows = await _tts_cost_rows(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            voice="cartesia",
            agent_chars=agent_chars,
            engine_tts_inr=Decimal("0.4100"),
            at=datetime(2024, 1, 1, tzinfo=UTC),
        )
    assert rows == [("tts_chars", Decimal(1), Decimal("0.4100"))]
    assert raised == ["engine_billed_byok_tts", "cartesia_call_without_attested_tts_price"]
