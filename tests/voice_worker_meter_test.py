"""`voice_worker.meter` — the five legs of §1.3, and every refusal proved rather than assumed.

The quantity assertions are EXACT `Decimal` comparisons, never `pytest.approx`: a quantity
multiplies a rate on the server, and an approximate assertion would pass just as happily on
the float arithmetic the module exists to keep off the money path.

Nothing here prices anything, because the meter does not: the server holds the rate card
(`tests/worker_api_test.py` pins that half).
"""

from __future__ import annotations

import asyncio
import dataclasses
from decimal import Decimal

import pytest
from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import TTSUsageMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.service_metrics_observer import (
    ServiceMetricsObserver,
    ServiceUsageKind,
    ServiceUsageRecord,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from voice_worker.meter import (
    UNIT_LLM_KTOK_IN,
    UNIT_LLM_KTOK_OUT,
    UNIT_PLATFORM_MIN,
    UNIT_STT_MIN,
    UNIT_TELEPHONY_S,
    UNIT_TTS_KCHARS,
    CallMeter,
    CarrierCdr,
    CarrierFactsMissingError,
    LegNotMeterableError,
    LlmModelAmbiguousError,
    LlmModelUnnamedError,
    LlmTotalTokensMissingError,
    MeteredLeg,
    RuntimePriceUnknownError,
    RuntimeUsage,
    SpeechQuantityMissingError,
    TokenUsageNotComparableError,
    UsageRow,
)


def stt(seconds: float, *, processor: str = "SarvamSTTService") -> ServiceUsageRecord:
    return ServiceUsageRecord(
        kind=ServiceUsageKind.STT, processor=processor, timestamp=1.0, audio_seconds=seconds
    )


def tts(characters: int, *, processor: str = "SarvamTTSService") -> ServiceUsageRecord:
    return ServiceUsageRecord(
        kind=ServiceUsageKind.TTS, processor=processor, timestamp=1.0, characters=characters
    )


def llm(
    *,
    prompt: int | None,
    completion: int | None,
    total: int | None,
    model: str | None = "gpt-4o-mini",
    processor: str = "AzureLLMService",
) -> ServiceUsageRecord:
    return ServiceUsageRecord(
        kind=ServiceUsageKind.LLM,
        processor=processor,
        model=model,
        timestamp=1.0,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


CDR = CarrierCdr(
    connected_seconds=Decimal("120"),
    carrier="plivo",
    cdr_id="cdr-abc",
)
RUNTIME = RuntimeUsage(
    active_minutes=Decimal("3"),
    attested_by="founder",
    source="Pipecat Cloud invoice 2026-09",
)


def _rows(meter: CallMeter) -> dict[str, object]:
    return {row.unit_type: row for row in meter.metered_rows(carrier=CDR, runtime=RUNTIME).rows}


def _only_refusal(
    kind: type[LegNotMeterableError],
    meter: CallMeter,
    *,
    carrier: CarrierCdr | None = CDR,
    runtime: RuntimeUsage | None = RUNTIME,
) -> LegNotMeterableError:
    """The ONE refusal this meter reached, asserted to be the only one and of the right type.

    **THE SHAPE `pytest.raises` USED TO GIVE, KEPT DELIBERATELY (D-625).** `metered_rows`
    returns refusals rather than raising the first one, so every refusal test below would
    otherwise become three lines of list indexing — and the property each of them is really
    pinning is unchanged: THIS leg refused, with THIS code, for THIS reason. What the helper
    adds is the assertion the old shape could not make, because a raise ends the call: that
    exactly one leg refused and the others did not quietly refuse too.
    """
    refusals = meter.metered_rows(carrier=carrier, runtime=runtime).refusals
    assert len(refusals) == 1, [refused.code for refused in refusals]
    assert isinstance(refusals[0], kind)
    return refusals[0]


# --- the five legs -------------------------------------------------------------------


def test_all_five_legs_are_metered_once_each() -> None:
    """§1.3 sums five legs. Five is the assertion — a four-leg total is the silent-zero bug."""
    meter = CallMeter()
    meter.observe(stt(60.0))
    meter.observe(tts(1000))
    meter.observe(llm(prompt=800, completion=200, total=1000))

    metered = meter.metered_rows(carrier=CDR, runtime=RUNTIME)
    rows = metered.rows

    assert metered.refusals == ()
    assert {row.leg for row in rows} == set(MeteredLeg)
    assert [row.unit_type for row in rows] == [
        UNIT_TELEPHONY_S,
        UNIT_PLATFORM_MIN,
        UNIT_STT_MIN,
        UNIT_TTS_KCHARS,
        UNIT_LLM_KTOK_IN,
        UNIT_LLM_KTOK_OUT,
    ]


def test_carrier_leg_takes_its_quantity_from_the_cdr() -> None:
    """§1.2: the carrier billed the minute, so the quantity is not derived from our clock."""
    meter = CallMeter()
    row = _rows(meter)[UNIT_TELEPHONY_S]

    assert row.qty == Decimal("120")
    assert row.meta["cdr_id"] == "cdr-abc"
    assert row.meta["source"] == "carrier_cdr"


def test_runtime_leg_carries_only_the_attested_minutes() -> None:
    meter = CallMeter()
    row = _rows(meter)[UNIT_PLATFORM_MIN]

    assert row.qty == Decimal("3")
    assert row.meta["attested_by"] == "founder"


def test_stt_leg_sums_incremental_reports_exactly() -> None:
    """`STTUsage` values are deltas the consumer sums (pipecat metrics.py:161-170)."""
    meter = CallMeter()
    meter.observe(stt(1.5))
    meter.observe(stt(2.25))
    meter.observe(stt(0.25))

    assert meter.stt_audio_seconds == Decimal("4.0")
    row = _rows(meter)[UNIT_STT_MIN]
    assert row.qty == Decimal("4.0") / 60
    assert Decimal(row.meta["audio_seconds"]) == Decimal("4.0")
    assert row.meta["reports"] == "3"


def test_stt_seconds_never_become_a_binary_float() -> None:
    """0.1 + 0.2 is 0.30000000000000004 in binary. The quantity that multiplies a rate is
    converted through its decimal repr, so the rupee figure is the one a human would get."""
    meter = CallMeter()
    meter.observe(stt(0.1))
    meter.observe(stt(0.2))

    assert meter.stt_audio_seconds == Decimal("0.3")
    assert _rows(meter)[UNIT_STT_MIN].qty == Decimal("0.3") / 60


def test_stt_leg_meters_minutes_not_seconds() -> None:
    """`stt_min`, not `stt_s`: the Saaras rate per second (₹0.008333…) stores as 0.0083 in
    NUMERIC(12,4), 0.4% light; per minute it is ₹0.5000 exactly (D-638)."""
    meter = CallMeter()
    meter.observe(stt(90.0))

    row = _rows(meter)[UNIT_STT_MIN]
    assert UNIT_STT_MIN == "stt_min"
    assert row.qty == Decimal("1.5")
    assert row.meta["audio_seconds"] == "90.0"


def test_tts_leg_meters_characters_per_thousand() -> None:
    """`tts_kchars`, not `tts_chars`: at NUMERIC(12,4) a per-character rate stores as zero."""
    meter = CallMeter()
    meter.observe(tts(1500))
    meter.observe(tts(500))

    assert meter.tts_characters == 2000
    row = _rows(meter)[UNIT_TTS_KCHARS]
    assert row.qty == Decimal("2")
    assert row.meta["characters"] == "2000"


def test_llm_leg_reports_the_split_and_stamps_total_tokens() -> None:
    meter = CallMeter()
    meter.observe(llm(prompt=1500, completion=500, total=2000))

    rows = _rows(meter)
    in_row = rows[UNIT_LLM_KTOK_IN]
    out_row = rows[UNIT_LLM_KTOK_OUT]

    assert in_row.qty == Decimal("1.5")
    assert out_row.qty == Decimal("0.5")
    assert in_row.meta["total_tokens"] == "2000"
    assert in_row.meta["model"] == "gpt-4o-mini"


def test_llm_total_tokens_is_summed_and_never_reconstructed() -> None:
    """§1.3: `total_tokens` is the only cross-provider comparable figure. It is read, summed
    and stamped; the property asserted here is that the accessor reports the REPORTED totals
    and not prompt + completion."""
    meter = CallMeter()
    meter.observe(llm(prompt=100, completion=50, total=150))
    meter.observe(llm(prompt=200, completion=100, total=300))

    assert meter.llm_total_tokens == 450


@pytest.mark.asyncio
async def test_the_observer_seam_feeds_the_meter_from_a_real_metrics_frame() -> None:
    """End to end through the seam the pipeline actually uses: a `MetricsFrame` travelling
    between two processors becomes a `ServiceUsageRecord` becomes our count. Exercised
    through the public `on_push_frame` rather than the observer's private dispatch, so the
    test breaks if the wiring breaks and not only if our own arithmetic does."""
    meter = CallMeter()
    observer = ServiceMetricsObserver()
    meter.attach(observer)
    processor = FrameProcessor(name="SarvamTTSService")

    await observer.on_push_frame(
        FramePushed(
            source=processor,
            destination=processor,
            frame=MetricsFrame(data=[TTSUsageMetricsData(processor="SarvamTTSService", value=250)]),
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
    )

    # The handler is dispatched as its own asyncio task (`utils/base_object.py:256-261`),
    # so the event returns before it has run and one loop yield is what lets it.
    await asyncio.sleep(0)

    assert meter.tts_characters == 250


# --- the refusals, each PROVED ---------------------------------------------------------


def test_a_missing_cdr_refuses_rather_than_timing_the_call_ourselves() -> None:
    meter = CallMeter()
    exc = _only_refusal(CarrierFactsMissingError, meter, carrier=None, runtime=RUNTIME)

    assert exc.leg is MeteredLeg.CARRIER
    assert exc.code == "meter_carrier_cdr_missing"
    assert "session duration" in exc.remediation


def test_the_carrier_refusal_names_the_minutes_the_client_is_not_billed() -> None:
    """The refusal's expensive half, which it used to leave unsaid.

    `telephony_s` is `billing/models.CLIENT_BILLED_UNIT_TYPES[0]` and its `qty` is what
    `billing/service.usage_summary` reports as `minutes_used`, what the overage rungs are
    cut from and what a prepaid wallet is debited against. A refused carrier leg writes no
    such row, so the call earns nothing — a revenue fact, not a cost one, and an operator
    triaging "unmetered spend" would never look for it.
    """
    meter = CallMeter()
    exc = _only_refusal(CarrierFactsMissingError, meter, carrier=None, runtime=RUNTIME)

    assert "telephony_s" in exc.detail
    assert "plan allowance" in exc.detail
    assert "wallet" in exc.detail


def test_the_carrier_refusal_points_at_the_reader_that_refuses_rather_than_at_a_chore() -> None:
    """ "Retrieve the CDR and meter again" is not an action anybody here can take.

    Nothing in this deployment can read a CDR — `carrier.fetch_call_detail_record` refuses
    by name — so a remediation phrased as a chore sends an operator looking for a console
    button that does not exist. It has to name the blocker instead.
    """
    meter = CallMeter()
    exc = _only_refusal(CarrierFactsMissingError, meter, carrier=None, runtime=RUNTIME)

    assert "fetch_call_detail_record" in exc.remediation
    assert "BLOCKER-1" in exc.remediation


def test_the_runtime_leg_refuses_because_the_active_minute_is_unknown() -> None:
    """§7 / P-1. There is no plausible number here and no way to supply one but an invoice."""
    meter = CallMeter()
    exc = _only_refusal(RuntimePriceUnknownError, meter, carrier=CDR, runtime=None)

    assert exc.leg is MeteredLeg.RUNTIME
    assert "UNKNOWN" in exc.detail


def test_a_net_reporting_provider_refuses_instead_of_underbilling_the_cache() -> None:
    """THE §1.3 TRAP. Anthropic/Bedrock report `prompt_tokens` NET of the prompt cache, so the
    parts fall short of `total_tokens` — billing them would silently drop the cached prompt."""
    meter = CallMeter()
    meter.observe(llm(prompt=100, completion=50, total=900, model="claude-haiku"))
    exc = _only_refusal(TokenUsageNotComparableError, meter)

    assert exc.leg is MeteredLeg.LLM
    assert "900" in exc.detail


def test_usage_without_a_total_refuses_rather_than_being_dropped() -> None:
    meter = CallMeter()
    meter.observe(llm(prompt=100, completion=50, total=None))
    exc = _only_refusal(LlmTotalTokensMissingError, meter)

    assert "AzureLLMService" in exc.detail


def test_usage_without_a_model_refuses_because_a_price_is_per_model() -> None:
    meter = CallMeter()
    meter.observe(llm(prompt=100, completion=50, total=150, model=None))
    _only_refusal(LlmModelUnnamedError, meter)


def test_two_models_in_one_session_refuse_rather_than_picking_one() -> None:
    """One ledger row per call per unit type, so a second model cannot be priced beside it."""
    meter = CallMeter()
    meter.observe(llm(prompt=100, completion=50, total=150))
    meter.observe(llm(prompt=10, completion=5, total=15, model="gpt-4.1-mini"))
    exc = _only_refusal(LlmModelAmbiguousError, meter)

    assert "gpt-4.1-mini" in exc.detail


def test_every_refusal_shares_one_base_so_a_zero_substitution_is_greppable() -> None:
    for error in (
        CarrierFactsMissingError,
        RuntimePriceUnknownError,
        TokenUsageNotComparableError,
        LlmModelUnnamedError,
        LlmModelAmbiguousError,
        LlmTotalTokensMissingError,
        SpeechQuantityMissingError,
    ):
        assert issubclass(error, LegNotMeterableError)
        assert error.kind == "business_rule"
        assert error.retryable is False


# --- observing never raises -------------------------------------------------------------


def test_observing_a_live_call_never_raises_however_bad_the_record() -> None:
    """A caller is mid-sentence: a refusal helps nobody until the call is over, and an
    exception out of an observer handler would end the call. Everything unusable is
    remembered and refused later instead."""
    meter = CallMeter()
    for record in (
        stt(1.0),
        ServiceUsageRecord(kind=ServiceUsageKind.STT, processor="p", timestamp=1.0),
        ServiceUsageRecord(kind=ServiceUsageKind.TTS, processor="p", timestamp=1.0),
        llm(prompt=None, completion=None, total=None),
        llm(prompt=1, completion=1, total=2, model=None),
    ):
        meter.observe(record)

    assert meter.stt_audio_seconds == Decimal("1.0")
    assert meter.tts_characters == 0


def test_a_leg_that_reported_nothing_is_absent_rather_than_refused() -> None:
    """A silent call transcribed nothing and spoke nothing. That is no leg, not an unpriced
    one — the distinction the module must keep, since only one of the two is an incident."""
    meter = CallMeter()
    metered = meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert {row.leg for row in metered.rows} == {MeteredLeg.CARRIER, MeteredLeg.RUNTIME}
    assert metered.refusals == ()


# --- partial settlement: the legs we can price settle, the legs we cannot are recorded ---


def test_the_legs_we_measured_settle_even_though_the_carrier_leg_has_no_witness() -> None:
    """D-625, AND IT IS THE STATE OF EVERY PRODUCTION CALL ON THIS ENGINE.

    `carrier=None` and `runtime=None` is not an edge case: no call has a CDR (BLOCKER-1) and
    what a Pipecat active minute bills is an unanswered vendor question (§7 P-1). Under the
    all-or-nothing meter this raised `CarrierFactsMissingError` before anything was measured,
    so the STT seconds, TTS characters and LLM tokens this session really witnessed were
    discarded — into an append-only ledger that can never take them afterwards.

    THE ASSERTION IS BOTH HALVES AT ONCE. Rows for the three legs we witnessed, refusals for
    the two we did not, and nothing invented for either: no carrier row timed off our own
    clock, no ₹0 runtime row.
    """
    meter = CallMeter()
    meter.observe(stt(60.0))
    meter.observe(tts(1000))
    meter.observe(llm(prompt=800, completion=200, total=1000))

    metered = meter.metered_rows(carrier=None, runtime=None)

    assert {row.leg for row in metered.rows} == {MeteredLeg.STT, MeteredLeg.TTS, MeteredLeg.LLM}
    assert [refused.leg for refused in metered.refusals] == [
        MeteredLeg.CARRIER,
        MeteredLeg.RUNTIME,
    ]
    assert [refused.code for refused in metered.refusals] == [
        "meter_carrier_cdr_missing",
        "meter_runtime_active_minute_unknown",
    ]


def test_every_measured_leg_is_delivered_with_no_price_anywhere_in_the_worker() -> None:
    """The meter a production container builds has no rate card, and must not need one.

    It used to take one and REFUSE each measured leg without it (`meter_rate_card_missing`).
    No container was ever given a card — the worker may not hold one — so the STT seconds,
    TTS characters and LLM tokens of every call left as refusals with no quantity, which the
    server can neither price nor park for a later attestation.
    """
    meter = CallMeter()
    meter.observe(stt(12.5))
    meter.observe(tts(700))
    meter.observe(llm(prompt=300, completion=100, total=400, model="gemini-2.5-flash-lite"))

    metered = meter.metered_rows(carrier=None, runtime=None)

    assert {(row.unit_type, row.qty) for row in metered.rows} == {
        (UNIT_STT_MIN, Decimal("12.5") / 60),
        (UNIT_TTS_KCHARS, Decimal("0.7")),
        (UNIT_LLM_KTOK_IN, Decimal("0.3")),
        (UNIT_LLM_KTOK_OUT, Decimal("0.1")),
    }
    assert {refused.leg for refused in metered.refusals} == {
        MeteredLeg.CARRIER,
        MeteredLeg.RUNTIME,
    }


def test_a_metered_row_carries_no_money_field() -> None:
    """Hard rule 7 at the source: the wire has no money field, so neither does the row."""
    assert {field.name for field in dataclasses.fields(UsageRow)} == {
        "leg",
        "unit_type",
        "qty",
        "meta",
    }


def test_every_unit_the_meter_emits_is_one_the_ledger_accepts() -> None:
    """The worker cannot import `apps.api`, so nothing but this pins its six tokens to the
    CHECK constraint the settlement INSERT meets — where a mismatch fails the whole
    settlement transaction, not one leg."""
    from apps.api.billing.models import UNIT_TYPES

    emitted = {
        UNIT_TELEPHONY_S,
        UNIT_PLATFORM_MIN,
        UNIT_STT_MIN,
        UNIT_TTS_KCHARS,
        UNIT_LLM_KTOK_IN,
        UNIT_LLM_KTOK_OUT,
    }
    assert emitted <= set(UNIT_TYPES)


# --- an unreadable speech report is an absence, never a zero ----------------------------


def test_stt_reports_we_could_not_read_refuse_the_leg_rather_than_vanish() -> None:
    """A transcriber that reported N times and named no `audio_seconds` in any of them is
    NOT a call that transcribed nothing.

    `ServiceUsageRecord.audio_seconds` is `float | None` at source (pipecat-ai 1.10.0,
    `pipecat/observers/service_metrics_observer.py:107`), so a report with no quantity is a
    shape the vendor type permits. Dropping it left `_stt_reports` at zero, and `_stt_rows`
    reads zero as "the transcriber never reported on this call" and returns no row at all —
    so the STT leg silently left the bill. That is `LlmTotalTokensMissingError`'s argument
    ("dropping such a report would under-meter the leg silently") one leg over.
    """
    meter = CallMeter()
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.STT, processor="p", timestamp=1.0))

    refusal = _only_refusal(LegNotMeterableError, meter)
    assert refusal.leg is MeteredLeg.STT


def test_tts_reports_we_could_not_read_refuse_the_leg_rather_than_vanish() -> None:
    """The same hole on the synthesiser leg: `characters` is `int | None` at source
    (`service_metrics_observer.py:108`), and a report carrying none used to be dropped."""
    meter = CallMeter()
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.TTS, processor="p", timestamp=1.0))

    refusal = _only_refusal(LegNotMeterableError, meter)
    assert refusal.leg is MeteredLeg.TTS


def test_an_unreadable_speech_report_still_refuses_when_other_reports_were_fine() -> None:
    """The dangerous direction: reports we COULD read make the leg look healthy, so a
    partially-unreadable leg used to settle at a quantity that was short by however much the
    dropped reports carried. A short quantity is a wrong price, not a missing one."""
    meter = CallMeter()
    meter.observe(stt(10.0))
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.STT, processor="p", timestamp=1.0))

    refusal = _only_refusal(LegNotMeterableError, meter)
    assert refusal.leg is MeteredLeg.STT
