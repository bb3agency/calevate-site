"""What each ThinnestAI call was billed as, and what the engine counted for it (D-796).

Every vendor shape is from the snapshot `thinnest-findings/mirror/snapshots/2026-10-15/pages/`
(VERIFIED-VENDOR-DOCS): `CallUsage` and `CallBilling` (`api-reference/calls/get-call.md:
1171-1294`, the documented example at :532-543) and `call.analysed` carrying both
(`api-reference/webhooks/create-webhook.md:330-340`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import own_model_prompt as omp
from apps.api.billing.engine_minutes import attest_engine_minute_price
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.tts_speaking_rate import fleet_speaking_rate, sample_tenant
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.charges import EngineCharge
from apps.api.engine.thinnest import (
    ThinnestEngine,
    parse_billing,
    parse_llm_usage,
    parse_tts_characters,
)
from apps.api.engine.vendor_http import EngineRateLimitedError, EngineRejectedError
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.workers import engine_charges, pipeline
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from calevate_shared.events import CallBilling, CallLlmUsage
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.thinnest_engine_test import _call
from tests.thinnest_intake_security_test import _analysed
from tests.thinnest_post_call_test import _operator, _usage, thinnest  # noqa: F401
from tests.thinnest_publish_limits_test import _agent_with_script, _thinnest
from tests.tts_speaking_rate_loop_test import _call as _transcribed_call
from tests.tts_speaking_rate_loop_test import _tenant

#: `CallUsage` and `CallBilling` exactly as Get Call's example shows them (get-call.md:532-543).
DOCUMENTED_USAGE: dict[str, Any] = {
    "inputTokens": 5120,
    "outputTokens": 410,
    "cachedInputTokens": 3584,
    "inputTokensEstimated": False,
    "ttsCharacters": 1840,
}
DOCUMENTED_BILLING: dict[str, Any] = {
    "keys": "off",
    "voicePlan": "standard",
    "ratePerMinuteMicro": 1820000,
    "billedSeconds": 210,
    "currency": "INR",
}


# --- parsing -------------------------------------------------------------------------------


def test_the_documented_billing_reads_in_our_names() -> None:
    assert parse_billing(DOCUMENTED_BILLING) == CallBilling(
        keys="off",
        voice_plan="standard",
        rate_inr_per_min=Decimal("1.82"),
        currency="INR",
        billed_seconds=210,
    )


def test_a_booked_call_and_an_unknown_scope_carry_no_billing() -> None:
    # "Null for a booked call that has not rung" (get-call.md:1228-1239).
    assert parse_billing(None) is None
    assert parse_billing(DOCUMENTED_BILLING | {"keys": "everything"}) is None


def test_an_own_key_call_not_yet_settled_has_no_plan_and_no_seconds() -> None:
    billing = parse_billing(
        DOCUMENTED_BILLING | {"keys": "voice", "voicePlan": None, "billedSeconds": None}
    )
    assert billing is not None
    assert (billing.keys, billing.voice_plan, billing.billed_seconds) == ("voice", None, None)
    assert billing.rate_inr_per_min == Decimal("1.82")


def test_a_rate_in_dollars_is_not_read_as_rupees() -> None:
    billing = parse_billing(DOCUMENTED_BILLING | {"currency": "USD", "voicePlan": "Premium"})
    assert billing is not None
    assert (billing.currency, billing.rate_inr_per_min) == ("USD", None)
    # The docs spell the plan in lower case (get-call.md:1253-1265); any other spelling is
    # not one of them.
    assert billing.voice_plan is None


def test_the_documented_usage_reads_with_its_estimate_flag_and_characters() -> None:
    assert parse_llm_usage(DOCUMENTED_USAGE) == CallLlmUsage(
        input_tokens=5120,
        output_tokens=410,
        cached_input_tokens=3584,
        input_tokens_estimated=False,
    )
    assert parse_tts_characters(DOCUMENTED_USAGE) == 1840
    unknown = parse_llm_usage(DOCUMENTED_USAGE | {"inputTokensEstimated": None})
    assert unknown is not None and unknown.input_tokens_estimated is None
    assert parse_tts_characters({"ttsCharacters": None}) is None
    assert parse_tts_characters(None) is None


def test_a_fetched_call_carries_its_billing_and_characters_and_a_listing_row_none() -> None:
    engine = ThinnestEngine(api_key="x")
    fetched = engine._snapshot(
        _call(usage=DOCUMENTED_USAGE, billing=DOCUMENTED_BILLING), workspace=None
    )
    assert fetched.tts_characters == 1840
    assert fetched.billing is not None and fetched.billing.billed_seconds == 210
    assert fetched.llm_usage is not None and fetched.llm_usage.input_tokens_estimated is False
    listed = engine._snapshot(_call(), workspace=None)
    assert (listed.billing, listed.tts_characters) == (None, None)


# --- what the call should have been billed as ----------------------------------------------


def test_each_rate_key_names_the_keys_and_plan_it_was_sold_on() -> None:
    assert engine_charges.expected_billing("byok_voice", own_model=False) == ("voice", None)
    assert engine_charges.expected_billing("byok_llm_voice", own_model=True) == ("llm_voice", None)
    assert engine_charges.expected_billing("studio", own_model=False) == ("off", "studio")
    assert engine_charges.expected_billing("premium", own_model=True) == ("llm", "premium")
    assert engine_charges.expected_billing("platform", own_model=False) is None
    assert engine_charges.expected_billing(None, own_model=False) is None


def test_a_base_minute_is_checked_on_its_seconds_only() -> None:
    billing = CallBilling(keys="all", rate_inr_per_min=Decimal("3"), billed_seconds=60)
    assert (
        engine_charges.billing_findings(
            billing,
            billed_seconds=60,
            engine="thinnest",
            rate_key="platform",
            own_model=False,
            our_minutes=Decimal(1),
            attested_inr_per_min=Decimal(3),
        )
        == []
    )


# --- reconciling one settled call ----------------------------------------------------------


@pytest.fixture
def variance_alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        engine_charges, "alert", lambda _s, code, **kw: raised.append((code, kw.get("detail", "")))
    )
    return raised


async def _metered_call(
    *,
    rate_key: str,
    inr_per_min: str | None,
    minutes: str = "1",
    own_model: str | None = None,
    tts: bool = False,
) -> tuple[UUID, UUID]:
    """One call metered as `workers/pipeline._meter` writes a ThinnestAI minute: the posted
    rate times the billed minutes, plus the top-up fee, with both on the row's meta."""
    tenant_id, agent_id = await _seed_tenant(f"bill_{uuid.uuid4().hex[:10]}")
    call_id = uuid7()
    fee = engine_charges.thinnest_topup_fee()
    cost = (
        engine_charges.cost_with_fee(Decimal(minutes) * Decimal(inr_per_min), fee=fee)
        if inr_per_min is not None
        else None
    )
    meta: dict[str, Any] = {
        "engine_rate_key": rate_key,
        "billed_minutes": minutes,
        "inr_per_min": inr_per_min,
        "topup_fee": str(fee),
    }
    if own_model is not None:
        meta["own_model"] = own_model
    rows: list[tuple[str, Decimal, Decimal | None]] = [("platform_min", Decimal(1), cost)]
    if tts:
        rows.append(("tts_kchars", Decimal("0.5"), Decimal("1.0000")))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                "'completed', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"out_{call_id}"},
        )
        for unit, qty, unit_cost in rows:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, "
                    ":q, :p, now(), CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit,
                    "q": qty,
                    "p": unit_cost,
                    "m": json.dumps(meta),
                },
            )
    return tenant_id, call_id


def _billing(**over: Any) -> CallBilling:
    base: dict[str, Any] = {
        "keys": "off",
        "voice_plan": "studio",
        "rate_inr_per_min": Decimal("3"),
        "currency": "INR",
        "billed_seconds": 60,
    }
    return CallBilling(**(base | over))


async def _reconcile(
    call: tuple[UUID, UUID], billing: CallBilling, *, charged: str = "3", forwarded: bool = False
) -> str:
    tenant_id, call_id = call
    return await engine_charges.reconcile_call_charge(
        tenant_id,
        call_id,
        Decimal(charged),
        engine="thinnest",
        billing=billing,
        forwarded=forwarded,
    )


@pytest.mark.rls
async def test_a_call_billed_as_it_was_sold_matches(
    variance_alarms: list[tuple[str, str]],
) -> None:
    call = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(call, _billing()) == "matched"
    own_model = await _metered_call(rate_key="premium", inr_per_min="3", own_model="gemini")
    assert await _reconcile(own_model, _billing(keys="llm", voice_plan="premium")) == "matched"
    assert variance_alarms == []


@pytest.mark.rls
async def test_a_studio_call_that_fell_back_to_the_engines_keys_names_what_ran(
    variance_alarms: list[tuple[str, str]],
) -> None:
    """Sold on our own voice key at its flat minute; the key was gone when the call started,
    so it ran on the engine's keys at the Studio band (get-call.md:200-203)."""
    call = await _metered_call(rate_key="byok_llm_voice", inr_per_min="1", tts=True)
    outcome = await _reconcile(call, _billing(keys="off", voice_plan="studio"))
    assert outcome == "variance"
    [(code, detail)] = variance_alarms
    assert code == "engine_call_cost_variance"
    assert "keys=off voice_plan=studio, not the keys=llm_voice voice_plan=none" in detail
    assert "charged-with-fee INR 3.0708" in detail
    # The keys are known, so the guess about a fallback is not made.
    assert "ran on the workspace's default keys" not in detail


@pytest.mark.rls
async def test_a_clear_call_priced_on_another_band_is_named_even_when_the_totals_agree(
    variance_alarms: list[tuple[str, str]],
) -> None:
    call = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(call, _billing(voice_plan="premium")) == "variance"
    [(_code, detail)] = variance_alarms
    assert "keys=off voice_plan=premium, not the keys=off voice_plan=studio" in detail
    assert "metered INR" not in detail


@pytest.mark.rls
async def test_seconds_or_rate_that_disagree_with_our_minutes_are_named(
    variance_alarms: list[tuple[str, str]],
) -> None:
    longer = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(longer, _billing(billed_seconds=120)) == "variance"
    cheaper = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(cheaper, _billing(rate_inr_per_min=Decimal("2.5"))) == "variance"
    assert "Seconds, not rate: the voice platform billed 120s" in variance_alarms[0][1]
    assert (
        "Rate: the voice platform charged INR 2.5/min against the attested INR 3/min"
        in (variance_alarms[1][1])
    )
    assert "Seconds" not in variance_alarms[1][1]


@pytest.mark.rls
async def test_the_engines_30_second_steps_match_our_pulse(
    variance_alarms: list[tuple[str, str]],
) -> None:
    """A 61-second call is three 30-second steps at half the rate each (get-call.md:
    1266-1275): 1.5 minutes on both sides."""
    call = await _metered_call(rate_key="studio", inr_per_min="3", minutes="1.5")
    assert await _reconcile(call, _billing(billed_seconds=90), charged="4.5") == "matched"
    assert variance_alarms == []


@pytest.mark.rls
async def test_unsettled_forwarded_and_foreign_rate_calls_are_not_checked_on_billing(
    variance_alarms: list[tuple[str, str]],
) -> None:
    wrong_scope = _billing(keys="all", voice_plan=None)
    unsettled = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(unsettled, wrong_scope.model_copy(update={"billed_seconds": None})) == (
        "matched"
    )
    # ThinnestAI's email of 15 Oct 2026: trust `costMicro` on a forwarded call (VENDOR-STATED).
    forwarded = await _metered_call(rate_key="standard", inr_per_min="3")
    assert await _reconcile(forwarded, wrong_scope, forwarded=True) == "matched"
    dollars = await _metered_call(rate_key="studio", inr_per_min="3")
    assert await _reconcile(dollars, _billing(rate_inr_per_min=None, currency="USD")) == "matched"
    assert variance_alarms == []


@pytest.mark.rls
async def test_an_unpriced_minute_still_names_a_scope_that_did_not_run(
    variance_alarms: list[tuple[str, str]],
) -> None:
    agreeing = await _metered_call(rate_key="studio", inr_per_min=None)
    assert await _reconcile(agreeing, _billing()) == "unpriced"
    assert variance_alarms == []
    wrong = await _metered_call(rate_key="studio", inr_per_min=None)
    assert await _reconcile(wrong, _billing(keys="voice", voice_plan=None)) == "variance"
    [(_code, detail)] = variance_alarms
    assert detail.startswith("rate_key=studio: The call ran on keys=voice")


# --- the characters sent to the voice (B) --------------------------------------------------


def test_the_engines_character_count_wins_and_the_transcript_is_the_fallback() -> None:
    assert pipeline.spoken_characters(1840, 900) == (1840, "engine")
    assert pipeline.spoken_characters(None, 900) == (900, "transcript")
    # A count of zero is the engine's answer, not an absence.
    assert pipeline.spoken_characters(0, 900) == (0, "engine")


def _fake_snapshot(seconds: int, *, tts_characters: int | None) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=seconds,
        ended_at=datetime.now(UTC),
        cost=CostBreakdown(
            total_inr=Decimal("4.0000"),
            platform_inr=Decimal("2.0000"),
            network_inr=Decimal("0.5000"),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("4.0000"),
            fx_rate=Decimal("1"),
        ),
        tts_characters=tts_characters,
        engine="fake",
    )


async def _sources(tenant_id: UUID, call_id: UUID) -> set[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT DISTINCT meta->>'tts_characters_source' FROM usage_events "
                "WHERE call_id = :c"
            ),
            {"c": call_id},
        )
        return {str(r[0]) for r in rows}


async def test_the_fleet_counter_counts_the_engines_characters_and_says_so() -> None:
    """The speaking-rate counter takes the same count the synthesis row does, and a call
    the engine counted is sampled even with no transcript."""
    tenant_id, agent_id = await _tenant()
    month = ist_billing_month(datetime.now(UTC))
    counted = await _transcribed_call(
        tenant_id, agent_id, seconds=120, turns=[("agent", "x" * 900)]
    )
    silent = await _transcribed_call(tenant_id, agent_id, seconds=120, turns=[])
    older = await _transcribed_call(tenant_id, agent_id, seconds=120, turns=[("agent", "y" * 900)])
    async with untenanted_session() as session:
        before = await fleet_speaking_rate(session, months=[month])
    await pipeline._meter(tenant_id, counted, _fake_snapshot(120, tts_characters=1840))
    await pipeline._meter(tenant_id, silent, _fake_snapshot(120, tts_characters=600))
    await pipeline._meter(tenant_id, older, _fake_snapshot(120, tts_characters=None))
    async with untenanted_session() as session:
        after = await fleet_speaking_rate(session, months=[month])
    assert after.calls - before.calls == 3
    assert after.agent_chars - before.agent_chars == 1840 + 600 + 900
    assert await _sources(tenant_id, counted) == {"engine"}
    # The board samples the same one count per call as the counter.
    async with tenant_session(tenant_id) as session:
        board = await sample_tenant(session, tenant_id=tenant_id)
    assert sorted(s.agent_chars for s in board) == [600, 900, 1840]


async def test_an_older_call_is_counted_from_its_transcript_and_says_so() -> None:
    tenant_id, agent_id = await _tenant()
    month = ist_billing_month(datetime.now(UTC))
    call_id = await _transcribed_call(
        tenant_id, agent_id, seconds=120, turns=[("agent", "x" * 900)]
    )
    async with untenanted_session() as session:
        before = await fleet_speaking_rate(session, months=[month])
    await pipeline._meter(tenant_id, call_id, _fake_snapshot(120, tts_characters=None))
    async with untenanted_session() as session:
        after = await fleet_speaking_rate(session, months=[month])
    assert after.agent_chars - before.agent_chars == 900
    assert await _sources(tenant_id, call_id) == {"transcript"}


# --- the whole seam: a signed `call.analysed` with usage and billing -----------------------


async def _attest_premium(inr: str) -> None:
    async with untenanted_session() as session:
        await attest_engine_minute_price(
            session,
            engine="thinnest",
            rate_key="premium",
            inr_per_min=Decimal(inr),
            # The latest rate before the call ends at 04:33:11, distinct per run.
            effective_from=datetime(2026, 10, 6, 4, 33, tzinfo=UTC)
            - timedelta(microseconds=uuid.uuid4().int % 1_000_000),
            source_note="ThinnestAI price page, test",
            actor_id=await _operator(),
        )


async def test_an_own_model_call_is_metered_and_reconciled_from_its_delivery(
    thinnest: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    variance_alarms: list[tuple[str, str]],
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_clear_voice_band", "premium")
    await _attest_premium("2.50")
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, engine_rate_key, engine_own_model, created_at, updated_at) VALUES "
                "('thinnest', :ref, :tid, :aid, true, 'premium', 'gemini-2.5-flash-lite', "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    body = json.loads(_analysed(ref))
    # 182 seconds: seven 30-second steps, 3.5 minutes at ₹2.50, so costMicro 8.75.
    body["data"] |= {
        "usage": DOCUMENTED_USAGE | {"inputTokensEstimated": True},
        "billing": DOCUMENTED_BILLING
        | {"keys": "llm", "voicePlan": "premium", "ratePerMinuteMicro": 2500000},
        "costMicro": 8750000,
        "currency": "INR",
    }
    execution_id = body["data"]["id"]
    delivery = seal_delivery(
        json.dumps(body),
        engine="thinnest",
        execution_id=execution_id,
        event_name="call.analysed:1:2026-10-06T04:33:20Z",
    )
    outcome = await pipeline.ingest_engine_event(
        {},
        {
            "engine": "thinnest",
            "execution_id": execution_id,
            "raw_status": "call.analysed",
            "engine_agent_ref": ref,
            "delivery": delivery,
        },
    )
    assert outcome == "pipeline_enqueued"
    call_id = UUID(
        next(
            p
            for j, p in thinnest["enqueued"]
            if j == pipeline.POSTCALL_JOB and p["execution_id"] == execution_id
        )["call_id"]
    )
    await pipeline._post_call_stages(tenant_id, call_id, execution_id, delivery=delivery)

    usage = await _usage(tenant_id, call_id)
    _qty, _unit, meta = usage["llm_ktok_in"]
    assert meta["llm_input_tokens_estimated"] is True
    assert meta["tts_characters_source"] == "engine"
    async with tenant_session(tenant_id) as session:
        charged = (
            await session.execute(
                text("SELECT engine_charged_inr FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert charged == Decimal("8.75")
    assert [code for code, _ in variance_alarms if code == "engine_call_cost_variance"] == []


# --- estimated input tokens stay out of the prompt-size floor (C) --------------------------


async def test_an_estimated_input_count_is_not_a_measured_prompt() -> None:
    tenant_id, agent_id = await _agent_with_script("[BUSINESS]\nOrganics\n\n[GOAL]\nBook.")
    async with tenant_session(tenant_id) as session:
        for input_tokens, estimated in ((40_000, True), (30_000, False), (20_000, None)):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500002', 'completed', now(), now())"
                ),
                {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex}"},
            )
            meta: dict[str, Any] = {"own_model": "gemini", "llm_input_tokens": input_tokens}
            if estimated is not None:
                meta["llm_input_tokens_estimated"] = estimated
            for unit, qty in (("telephony_s", Decimal(300)), ("llm_ktok_in", Decimal(1))):
                await session.execute(
                    text(
                        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                        "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                        ":u, :q, NULL, now(), CAST(:m AS jsonb), now())"
                    ),
                    {
                        "i": uuid7(),
                        "t": tenant_id,
                        "c": call_id,
                        "u": unit,
                        "q": qty,
                        "m": json.dumps(meta),
                    },
                )
        sample = await omp.sample_tenant(session, tenant_id=tenant_id, engine=_thinnest())
    seconds = Decimal(300)
    assert sorted(sample.measured) == sorted(
        [
            omp.effective_prompt_tokens(30_000, seconds),
            omp.effective_prompt_tokens(20_000, seconds),
        ]
    )


# --- a call that ended before the agent spoke ----------------------------------------------


def test_a_call_that_ended_before_the_agent_spoke_is_carrier_only() -> None:
    assert parse_billing(DOCUMENTED_BILLING, hangup="before_agent") == CallBilling(
        keys="off",
        voice_plan="standard",
        rate_inr_per_min=Decimal("1.82"),
        currency="INR",
        billed_seconds=210,
        carrier_only=True,
    )
    snapshot = ThinnestEngine(api_key="x")._snapshot(
        _call(hangup="before_agent", billing=DOCUMENTED_BILLING), workspace=None
    )
    assert snapshot.billing is not None and snapshot.billing.carrier_only is True
    assert parse_billing(DOCUMENTED_BILLING, hangup="answered") == parse_billing(DOCUMENTED_BILLING)


def _findings(billing: CallBilling, *, our_minutes: Decimal | None) -> list[str]:
    assert billing.billed_seconds is not None
    return engine_charges.billing_findings(
        billing,
        billed_seconds=billing.billed_seconds,
        engine="thinnest",
        rate_key="studio",
        own_model=False,
        our_minutes=our_minutes,
        attested_inr_per_min=Decimal(3),
    )


def test_a_carrier_block_is_named_as_seconds_and_never_as_rate() -> None:
    """Charged the carrier's fee only and rounded to its block (get-call.md:1276-1285), so
    the rate is not compared; the block's length is not documented, so seconds that differ
    from our pulse are still named, as the carrier's block."""
    block = _billing(billed_seconds=60, rate_inr_per_min=Decimal("9"), carrier_only=True)
    [finding] = _findings(block, our_minutes=Decimal("0.5"))
    assert finding.startswith("Seconds, not rate: the call ended before the agent spoke")
    assert "carrier's block of 60s" in finding and "30-second pulse of 0.5 min" in finding
    assert _findings(block, our_minutes=Decimal(1)) == []


def test_a_minute_row_without_its_minutes_is_checked_on_scope_only() -> None:
    wrong = _billing(keys="voice", voice_plan=None, billed_seconds=600)
    [finding] = _findings(wrong, our_minutes=None)
    assert finding.startswith("The call ran on keys=voice")


# --- billing of calls the hourly sweep settles ---------------------------------------------

_PENDING = "engine_charges:billing_pending:thinnest"


@pytest.fixture
async def pending() -> Any:
    from apps.api.core.redis import get_redis

    redis = get_redis()
    await redis.delete(_PENDING)
    yield redis
    await redis.delete(_PENDING)


class _GetCall:
    """An engine whose Get Call answers from a script: a snapshot, or an error to raise."""

    name = "thinnest"

    def __init__(self, answers: dict[str, ExecutionSnapshot | Exception]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        self.asked.append(call_id)
        answer = self.answers[call_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _settled(engine_call_id: str, billing: CallBilling | None) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=engine_call_id,
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        billing=billing,
        engine="thinnest",
    )


async def _settled_by_sweep() -> tuple[UUID, UUID, str]:
    """A metered call with no charge yet, settled by the sweep's comparison of one log row."""
    tenant_id, call_id = await _metered_call(rate_key="studio", inr_per_min="3")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT agent_id FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, engine_rate_key, created_at, updated_at) VALUES ('thinnest', :ref, "
                ":tid, :aid, true, 'studio', now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    charge = EngineCharge(
        engine_call_id=f"out_{call_id}", engine_agent_ref=ref, charged_inr=Decimal("3")
    )
    await engine_charges._compare("thinnest", charge, engine_charges._Tally())
    # A second sweep finds the charge recorded and queues nothing more.
    await engine_charges._compare("thinnest", charge, engine_charges._Tally())
    return tenant_id, call_id, f"out_{call_id}"


def _drain(engine: _GetCall) -> Any:
    return engine_charges.check_late_billing(engine)  # type: ignore[arg-type]


@pytest.mark.rls
async def test_a_call_the_sweep_settles_is_checked_once_from_get_call(
    pending: Any, variance_alarms: list[tuple[str, str]]
) -> None:
    _tenant_id, matched_id, matched_ecid = await _settled_by_sweep()
    _tenant_id, wrong_id, wrong_ecid = await _settled_by_sweep()
    queued = await pending.hgetall(_PENDING)
    assert set(queued) == {str(matched_id), str(wrong_id)}
    assert json.loads(queued[str(matched_id)])["attempts"] == 0
    engine = _GetCall(
        {
            matched_ecid: _settled(matched_ecid, _billing()),
            wrong_ecid: _settled(wrong_ecid, _billing(keys="voice", voice_plan=None)),
        }
    )
    assert await _drain(engine) == 2
    [(code, detail)] = variance_alarms
    assert code == "engine_call_cost_variance"
    assert detail.startswith("rate_key=studio: The call ran on keys=voice")
    assert await pending.hgetall(_PENDING) == {}
    # Checked calls are gone, so the next run asks nothing.
    assert await _drain(engine) == 0
    assert len(engine.asked) == 2


@pytest.mark.rls
async def test_a_late_call_that_cannot_be_checked_is_dropped_without_an_alarm(
    pending: Any, variance_alarms: list[tuple[str, str]]
) -> None:
    tenant_id, call_id, ecid = await _settled_by_sweep()
    unsettled = _settled(ecid, _billing(billed_seconds=None))
    assert (
        await engine_charges.check_settled_billing(tenant_id, call_id, unsettled, engine="thinnest")
        == "not_checked"
    )
    assert await _drain(_GetCall({ecid: unsettled})) == 1
    assert variance_alarms == []
    assert await pending.hgetall(_PENDING) == {}


@pytest.mark.parametrize(
    "busy",
    [
        EngineRateLimitedError(),
        EngineRejectedError(status=503),
        ProblemError(kind="dependency", code="engine_unreachable", title="t", detail="d"),
    ],
)
async def test_a_busy_vendor_stops_the_run_and_spends_no_attempt(
    pending: Any, busy: ProblemError
) -> None:
    entry = json.dumps({"tenant_id": str(uuid.uuid4()), "engine_call_id": "out_a", "attempts": 0})
    await pending.hset(_PENDING, mapping={"a": entry, "b": entry})
    engine = _GetCall({"out_a": busy})
    assert await _drain(engine) == 0
    assert engine.asked == ["out_a"]
    held = await pending.hgetall(_PENDING)
    assert {key: json.loads(value)["attempts"] for key, value in held.items()} == {"a": 0, "b": 0}


async def test_a_call_get_call_keeps_refusing_is_given_up_after_its_attempts(
    pending: Any,
) -> None:
    entry = {"tenant_id": str(uuid.uuid4()), "engine_call_id": "out_gone", "attempts": 0}
    await pending.hset(_PENDING, "gone", json.dumps(entry))
    engine = _GetCall({"out_gone": EngineRejectedError(status=404)})
    for attempt in range(1, engine_charges.BILLING_CHECK_ATTEMPTS):
        assert await _drain(engine) == 0
        assert json.loads(await pending.hget(_PENDING, "gone"))["attempts"] == attempt
    await _drain(engine)
    assert await pending.hgetall(_PENDING) == {}


async def test_a_run_reads_at_most_its_bound(pending: Any) -> None:
    entry = json.dumps({"tenant_id": str(uuid.uuid4()), "engine_call_id": "out_x", "attempts": 0})
    total = engine_charges.BILLING_CHECKS_PER_RUN + 3
    await pending.hset(_PENDING, mapping={str(uuid.UUID(int=i)): entry for i in range(total)})
    engine = _GetCall({"out_x": _settled("out_x", None)})
    assert await _drain(engine) == engine_charges.BILLING_CHECKS_PER_RUN
    assert len(await pending.hgetall(_PENDING)) == 3


async def test_without_redis_nothing_is_queued_or_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def _down() -> Any:
        raise ConnectionError("redis down")

    monkeypatch.setattr(engine_charges, "get_redis", _down)
    await engine_charges.queue_billing_check("thinnest", uuid.uuid4(), uuid.uuid4(), "out_1")
    assert await _drain(_GetCall({})) == 0
