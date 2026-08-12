"""Honest degraded-tier billing (SURFACES §2b, D-35/D-36).

SURFACES §2b holds us to this: "if a premium voice is unavailable the call runs on the
cheaper voice and is **billed at the cheaper rate**, never silently upgraded." D-36 makes
that ladder real — Bulbul v3 is the default at ₹30/10k chars, v2 is the value tier at
₹15/10k — so a call genuinely CAN run on the cheaper rung.

**The finding these tests pin first: nothing tells us which voice actually ran.**
`ExecutionSnapshot` carries no TTS model, and neither does `CostBreakdown` — the engine
reports a synthesizer LEG COST and no model name, no character count. So the tier on a
usage row is an ASSUMPTION read from the agent's configuration, never a measurement, and
the ledger says so in as many words (`tts_tier_source`). The first test is a tripwire: the
day a vendor field appears, it fails and points at the code that should start using it.

Everything else follows from one rule — **an unproven tier is billed as the VALUE tier.**
Billing premium requires evidence; absence of evidence is not evidence of premium.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.billing import rates
from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

# --- the finding ---------------------------------------------------------------


def test_the_engine_tells_us_nothing_about_which_voice_ran() -> None:
    """The evidence behind `tts_tier_source = 'agent_config'`.

    If this ever fails, the vendor started reporting the synthesizer model and the
    pipeline should be reading it instead of trusting the agent row.
    """
    snapshot_fields = set(ExecutionSnapshot.model_fields)
    cost_fields = set(CostBreakdown.model_fields)
    suspects = {"tts_model", "tts_voice", "synthesizer_model", "voice", "tts_chars", "chars"}
    assert not suspects & (snapshot_fields | cost_fields), (
        "the engine now reports the voice or a character count — meter the MEASURED "
        "tier instead of the configured one, and revisit rates.ENGINE_REPORTS_TTS_MODEL"
    )
    assert rates.ENGINE_REPORTS_TTS_MODEL is False


# --- the rate card (D-35/D-36, TRD §10.1) --------------------------------------


def test_the_rate_card_is_d36s_and_is_numeric() -> None:
    assert rates.TTS_INR_PER_10K_CHARS["premium"] == Decimal("30.0000")
    assert rates.TTS_INR_PER_10K_CHARS["value"] == Decimal("15.0000")
    # The 2:1 ratio is the one thing about the ladder that needs no unmeasured
    # character-per-minute assumption to state.
    assert rates.TTS_INR_PER_10K_CHARS["value"] * 2 == rates.TTS_INR_PER_10K_CHARS["premium"]
    for rate in rates.TTS_INR_PER_10K_CHARS.values():
        assert isinstance(rate, Decimal) and not isinstance(rate, float)


def test_the_value_tier_costs_exactly_half_of_the_premium_tier() -> None:
    premium = rates.tts_cost_inr("premium", 10_000)
    value = rates.tts_cost_inr("value", 10_000)
    assert premium == Decimal("30.0000")
    assert value == Decimal("15.0000")
    assert value * 2 == premium
    assert isinstance(value, Decimal)


# --- the honesty rule: unproven is billed as value -----------------------------


def test_a_configured_voice_maps_to_its_catalog_tier() -> None:
    assert rates.billable_tier("bulbul:v3") == ("premium", "agent_config")
    assert rates.billable_tier("bulbul:v2") == ("value", "agent_config")


def test_an_unknown_or_missing_voice_is_billed_as_value_never_premium() -> None:
    """The whole point. A call we cannot attribute is a call that does not get charged
    the premium rate."""
    assert rates.billable_tier(None) == ("value", "unproven")
    assert rates.billable_tier("") == ("value", "unproven")
    assert rates.billable_tier("Bulbul:V3") == ("value", "unproven"), (
        "case-normalised guessing is how a value call gets billed premium"
    )
    assert rates.billable_tier("cartesia:sonic") == ("value", "unproven")


# --- metering records the tier -------------------------------------------------


def _snapshot(*, duration_s: int = 120, tts_inr: str = "2.0000") -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=duration_s,
        cost=CostBreakdown(
            total_inr=Decimal("6.0000"),
            platform_inr=Decimal("3.0000"),
            network_inr=Decimal("0.8000"),
            llm_inr=Decimal("0.0000"),
            tts_inr=Decimal(tts_inr),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("6.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )


async def _tenant_with_call(label: str, *, voice: str | None) -> tuple[UUID, UUID]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{label}_{uuid.uuid4().hex[:8]}")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        if voice is not None:
            await session.execute(
                text("UPDATE agents SET tts_voice = :v, tts_provider = 'sarvam' WHERE id = :a"),
                {"v": voice, "a": agent_id},
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    return tenant_id, call_id


async def _usage_rows(tenant_id: UUID, call_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE tenant_id = :t AND call_id = :c ORDER BY unit_type"
                ),
                {"t": tenant_id, "c": call_id},
            )
        ).all()
    return [
        {"unit_type": r[0], "qty": r[1], "unit_cost_paid": r[2], "meta": r[3] or {}} for r in rows
    ]


async def test_every_usage_row_records_the_tier_that_ran() -> None:
    tenant_id, call_id = await _tenant_with_call("premium", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    rows = await _usage_rows(tenant_id, call_id)
    assert rows, "the call metered something"
    for row in rows:
        assert row["meta"]["tts_tier"] == "premium"
        assert row["meta"]["tts_voice"] == "bulbul:v3"
        # Provenance, stated: this is the CONFIGURED voice, not a measurement.
        assert row["meta"]["tts_tier_source"] == "agent_config"


async def test_a_value_tier_call_is_metered_as_value() -> None:
    tenant_id, call_id = await _tenant_with_call("value", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot())
    rows = await _usage_rows(tenant_id, call_id)
    assert {row["meta"]["tts_tier"] for row in rows} == {"value"}
    assert {row["meta"]["tts_tier_source"] for row in rows} == {"agent_config"}


async def test_a_call_with_no_configured_voice_is_metered_as_value_not_premium() -> None:
    """An agent row that was never given a voice is the degraded case in the wild: we
    have no idea what spoke, so the client gets the cheaper rate."""
    tenant_id, call_id = await _tenant_with_call("novoice", voice=None)
    await _meter(tenant_id, call_id, _snapshot())
    rows = await _usage_rows(tenant_id, call_id)
    assert {row["meta"]["tts_tier"] for row in rows} == {"value"}
    assert {row["meta"]["tts_tier_source"] for row in rows} == {"unproven"}
    assert all(row["meta"]["tts_voice"] is None for row in rows)


async def test_tier_metering_does_not_change_what_the_call_cost() -> None:
    """Attribution is meta. The money on the row is still the money the engine
    reported — the margin panel must not move because a tier label appeared."""
    tenant_id, call_id = await _tenant_with_call("nomove", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text(
                    "SELECT SUM(qty * COALESCE(unit_cost_paid, 0)) FROM usage_events "
                    "WHERE tenant_id = :t AND call_id = :c"
                ),
                {"t": tenant_id, "c": call_id},
            )
        ).scalar()
    # 120s telephony + 2 platform-min + 120s stt + one tts leg + one llm leg.
    assert Decimal(str(total)) == Decimal("6.8000")


# --- the split both panels read ------------------------------------------------


async def test_the_tier_split_counts_minutes_and_cost_by_tier() -> None:
    tenant_id, premium_call = await _tenant_with_call("split", voice="bulbul:v3")
    await _meter(tenant_id, premium_call, _snapshot(duration_s=60))

    # A second call on the same tenant, on the value voice.
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM calls WHERE id = :c"), {"c": premium_call}
            )
        ).scalar()
        await session.execute(
            text("UPDATE agents SET tts_voice = 'bulbul:v2' WHERE id = :a"), {"a": agent_id}
        )
        value_call = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500002', 'completed', now(), now())"
            ),
            {"i": value_call, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:8]}"},
        )
    await _meter(tenant_id, value_call, _snapshot(duration_s=180))

    async with tenant_session(tenant_id) as session:
        split = await billing.tier_usage(session, tenant_id=tenant_id)

    assert split["minutes_premium"] == Decimal("1.00")
    assert split["minutes_value"] == Decimal("3.00")
    assert split["minutes_unattributed"] == Decimal("0.00")
    assert split["cost_premium_inr"] > Decimal("0")
    assert split["cost_value_inr"] > Decimal("0")
    assert isinstance(split["cost_value_inr"], Decimal)

    # The margin panel's single cost figure is these buckets added — one ledger, two
    # readings, no arithmetic that can drift.
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
    assert (
        split["cost_premium_inr"] + split["cost_value_inr"] + split["cost_unattributed_inr"]
        == margin["cost_inr"]
    )


async def test_a_row_with_no_tier_is_reported_separately_and_billed_as_value() -> None:
    """Rows written before tier attribution existed carry no tier. They are NOT
    relabelled (hard rule 4) and they are NOT counted as premium: the split reports
    them as unattributed and the billable side treats them as value."""
    tenant_id, call_id = await _tenant_with_call("legacy", voice="bulbul:v3")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                "120, 0.0100, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        split = await billing.tier_usage(session, tenant_id=tenant_id)

    assert split["minutes_unattributed"] == Decimal("2.00")
    assert split["minutes_premium"] == Decimal("0.00")
    assert split["minutes_billable_premium"] == Decimal("0.00")
    assert split["minutes_billable_value"] == Decimal("2.00"), "unproven bills as value"


async def test_the_split_totals_agree_with_the_usage_panel() -> None:
    """The panels must not disagree: the tier split's minutes add up to the same
    `minutes_used` the client is billed on."""
    tenant_id, call_id = await _tenant_with_call("agree", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot(duration_s=150))
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        split = await billing.tier_usage(session, tenant_id=tenant_id)
    total = split["minutes_premium"] + split["minutes_value"] + split["minutes_unattributed"]
    assert total == summary["minutes_used"] == Decimal("2.50")


async def test_the_tier_split_never_leaks_across_tenants() -> None:
    a_tenant, a_call = await _tenant_with_call("iso-a", voice="bulbul:v3")
    b_tenant, b_call = await _tenant_with_call("iso-b", voice="bulbul:v2")
    await _meter(a_tenant, a_call, _snapshot(duration_s=60))
    await _meter(b_tenant, b_call, _snapshot(duration_s=60))
    async with tenant_session(a_tenant) as session:
        a_split = await billing.tier_usage(session, tenant_id=a_tenant)
    assert a_split["minutes_premium"] == Decimal("1.00")
    assert a_split["minutes_value"] == Decimal("0.00")


# --- correcting a mis-tiered call (hard rule 4) --------------------------------


async def test_a_mis_tiered_call_is_corrected_by_a_compensating_entry() -> None:
    """Hard rule 4: the wrong row STAYS. The fix is a new row carrying the delta, and
    the margin panel picks it up because it sums qty * unit_cost_paid."""
    tenant_id, call_id = await _tenant_with_call("correct", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    before = await _usage_rows(tenant_id, call_id)

    async with tenant_session(tenant_id) as session:
        delta = await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-1",
        )
    # ₹30 was assumed, ₹15 is what a value-tier call costs: a ₹15 credit.
    assert delta == Decimal("-15.0000")

    after = await _usage_rows(tenant_id, call_id)
    originals = [row for row in after if row["meta"].get("kind") != "tts_tier_correction"]
    assert originals == before, "an append-only ledger is never edited in place"

    corrections = [row for row in after if row["meta"].get("kind") == "tts_tier_correction"]
    assert len(corrections) == 1
    correction = corrections[0]
    assert correction["qty"] == Decimal("1.0000")
    assert correction["unit_cost_paid"] == Decimal("-15.0000")
    assert correction["meta"]["billed_tier"] == "premium"
    assert correction["meta"]["actual_tier"] == "value"
    assert correction["meta"]["tts_tier"] == "value", "the row asserts the tier that RAN"


async def test_the_same_correction_is_never_applied_twice() -> None:
    tenant_id, call_id = await _tenant_with_call("twice", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        first = await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-2",
        )
        second = await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-2",
        )
    assert first == Decimal("-15.0000")
    assert second is None, "a replayed correction is not a second credit"
    rows = await _usage_rows(tenant_id, call_id)
    assert sum(1 for r in rows if r["meta"].get("kind") == "tts_tier_correction") == 1


async def test_a_correction_that_changes_nothing_writes_nothing() -> None:
    tenant_id, call_id = await _tenant_with_call("noop", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        delta = await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="value",
            actual_tier="value",
            ref="ops-3",
        )
    assert delta is None
    rows = await _usage_rows(tenant_id, call_id)
    assert not [r for r in rows if r["meta"].get("kind") == "tts_tier_correction"]


async def test_a_self_serve_wallet_is_refunded_when_the_tier_was_wrong() -> None:
    """For a self-serve client the wallet IS the bill (D-39), so a call billed at the
    premium rate it did not get has to come back — as a NEW ledger entry."""
    tenant_id, call_id = await _tenant_with_call("wallet", voice="bulbul:v3")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="topup", ref="rzp_tier"
        )
    await _meter(tenant_id, call_id, _snapshot())

    async with tenant_session(tenant_id) as session:
        before = (await billing.get_balance(session, tenant_id=tenant_id)).amount_inr
        await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-4",
        )
        after = (await billing.get_balance(session, tenant_id=tenant_id)).amount_inr
    assert after - before == Decimal("15.0000"), "the overcharge is refunded, not edited away"

    async with tenant_session(tenant_id) as session:
        reasons = (
            (
                await session.execute(
                    text(
                        "SELECT reason FROM credit_ledger WHERE tenant_id = :t AND ref = :r "
                        "ORDER BY occurred_at"
                    ),
                    {"t": tenant_id, "r": "tier-correction:ops-4"},
                )
            )
            .scalars()
            .all()
        )
    assert reasons == ["adjustment"]


async def test_a_managed_client_wallet_is_untouched_by_a_correction() -> None:
    """Managed clients are invoiced against a retainer, not a wallet (D-39) — the
    correction belongs on the cost ledger only."""
    tenant_id, call_id = await _tenant_with_call("managed", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        await billing.record_tier_correction(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            chars=10_000,
            billed_tier="premium",
            actual_tier="value",
            ref="ops-5",
        )
        entries = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert entries == 0
