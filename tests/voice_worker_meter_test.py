"""`voice_worker.meter` — the five legs of §1.3, and every refusal proved rather than assumed.

The money assertions are EXACT `Decimal` comparisons, never `pytest.approx`: the point of the
module under test is that no float touches a rupee, and an approximate assertion would pass
just as happily on the float arithmetic it exists to forbid.

The fake rate card below is a FAKE AND NOT A RATE. Its numbers are chosen to be exactly
representable and easy to check by hand; nothing in this file asserts what Sarvam or Azure
charge, because a test is not evidence of a vendor's price (hard rule 11).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
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
    UNIT_STT_S,
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
    RateCardMissingError,
    RateRefusedError,
    RuntimePriceUnknownError,
    RuntimeUsage,
    SpeechQuantityMissingError,
    TokenUsageNotComparableError,
)

# ₹0.01 per second, ₹0.002 per character, ₹1/₹4 per 1,000 tokens. Round figures so every
# expected value below can be read off by eye.
_STT_PER_S = Decimal("0.01")
_TTS_PER_CHAR = Decimal("0.002")
_LLM = {"in": Decimal("1.0000"), "out": Decimal("4.0000")}


class FakeRates:
    """A `RateCard` that answers, or refuses the way `billing/rates.llm_inr_per_ktok` does."""

    def __init__(self, *, priced_model: str | None = "gpt-4o-mini") -> None:
        self.priced_model = priced_model

    def llm_inr_per_ktok(self, model: str) -> Mapping[str, Decimal]:
        if model != self.priced_model:
            raise ValueError(f"{model!r} has no billable price.")
        return _LLM

    def tts_rate_inr_per_char(self) -> Decimal:
        return _TTS_PER_CHAR

    def stt_rate_inr_per_second(self) -> Decimal:
        return _STT_PER_S


class RefusingRates(FakeRates):
    """Every leg refused — the hard-rule-7 state of a deployment with nothing attested."""

    def tts_rate_inr_per_char(self) -> Decimal:
        raise ValueError("no attested TTS rate")

    def stt_rate_inr_per_second(self) -> Decimal:
        raise ValueError("no attested STT rate")


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
    charge_inr=Decimal("1.2000"),
    carrier="plivo",
    cdr_id="cdr-abc",
)
RUNTIME = RuntimeUsage(
    active_minutes=Decimal("3"),
    inr_per_active_minute=Decimal("0.5000"),
    attested_by="founder",
    source="Pipecat Cloud invoice 2026-09",
)


def _rows(meter: CallMeter) -> dict[str, object]:
    rows = meter.metered_rows(carrier=CDR, runtime=RUNTIME)
    return {row.unit_type: row for row in rows}


# --- the five legs -------------------------------------------------------------------


def test_all_five_legs_are_metered_once_each() -> None:
    """§1.3 sums five legs. Five is the assertion — a four-leg total is the silent-zero bug."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(stt(60.0))
    meter.observe(tts(1000))
    meter.observe(llm(prompt=800, completion=200, total=1000))

    rows = meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert {row.leg for row in rows} == set(MeteredLeg)
    assert [row.unit_type for row in rows] == [
        UNIT_TELEPHONY_S,
        UNIT_PLATFORM_MIN,
        UNIT_STT_S,
        UNIT_TTS_KCHARS,
        UNIT_LLM_KTOK_IN,
        UNIT_LLM_KTOK_OUT,
    ]


def test_carrier_leg_takes_both_quantity_and_charge_from_the_cdr() -> None:
    """§1.2: the carrier billed the minute, so neither figure is derived from our clock."""
    meter = CallMeter(rates=FakeRates())
    row = _rows(meter)[UNIT_TELEPHONY_S]

    assert row.qty == Decimal("120")
    assert row.total_inr == Decimal("1.2000")
    assert row.unit_cost_inr == Decimal("0.01")
    assert row.meta["cdr_id"] == "cdr-abc"
    assert row.meta["source"] == "carrier_cdr"


def test_carrier_leg_keeps_the_charge_whole_when_the_cdr_reports_zero_seconds() -> None:
    """A connected charge on a zero-length CDR must not divide by zero or vanish."""
    meter = CallMeter(rates=FakeRates())
    zero = CarrierCdr(
        connected_seconds=Decimal(0),
        charge_inr=Decimal("0.3000"),
        carrier="plivo",
        cdr_id="cdr-zero",
    )
    (row,) = [
        r for r in meter.metered_rows(carrier=zero, runtime=RUNTIME) if r.leg is MeteredLeg.CARRIER
    ]
    assert row.unit_cost_inr == Decimal("0.3000")
    assert row.total_inr == Decimal("0.3000")


def test_runtime_leg_prices_only_the_attested_minutes_and_rate() -> None:
    meter = CallMeter(rates=FakeRates())
    row = _rows(meter)[UNIT_PLATFORM_MIN]

    assert row.qty == Decimal("3")
    assert row.unit_cost_inr == Decimal("0.5000")
    assert row.total_inr == Decimal("1.5000")
    assert row.meta["attested_by"] == "founder"


def test_stt_leg_sums_incremental_reports_exactly() -> None:
    """`STTUsage` values are deltas the consumer sums (pipecat metrics.py:161-170)."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(stt(1.5))
    meter.observe(stt(2.25))
    meter.observe(stt(0.25))

    assert meter.stt_audio_seconds == Decimal("4.0")
    row = _rows(meter)[UNIT_STT_S]
    assert row.qty == Decimal("4.0")
    assert row.unit_cost_inr == _STT_PER_S
    assert row.total_inr == Decimal("0.040")
    assert row.meta["reports"] == "3"


def test_stt_seconds_never_become_a_binary_float() -> None:
    """0.1 + 0.2 is 0.30000000000000004 in binary. The quantity that multiplies a rate is
    converted through its decimal repr, so the rupee figure is the one a human would get."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(stt(0.1))
    meter.observe(stt(0.2))

    assert meter.stt_audio_seconds == Decimal("0.3")
    assert _rows(meter)[UNIT_STT_S].total_inr == Decimal("0.003")


def test_tts_leg_meters_characters_per_thousand() -> None:
    """`tts_kchars`, not `tts_chars`: at NUMERIC(12,4) a per-character rate stores as zero."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(tts(1500))
    meter.observe(tts(500))

    assert meter.tts_characters == 2000
    row = _rows(meter)[UNIT_TTS_KCHARS]
    assert row.qty == Decimal("2")
    assert row.unit_cost_inr == Decimal("2.000")  # ₹0.002/char x 1,000
    assert row.total_inr == Decimal("4.000")
    assert row.meta["characters"] == "2000"


def test_llm_leg_bills_the_reported_split_and_stamps_total_tokens() -> None:
    meter = CallMeter(rates=FakeRates())
    meter.observe(llm(prompt=1500, completion=500, total=2000))

    rows = _rows(meter)
    in_row = rows[UNIT_LLM_KTOK_IN]
    out_row = rows[UNIT_LLM_KTOK_OUT]

    assert in_row.qty == Decimal("1.5")
    assert in_row.unit_cost_inr == Decimal("1.0000")
    assert in_row.total_inr == Decimal("1.5000")
    assert out_row.qty == Decimal("0.5")
    assert out_row.unit_cost_inr == Decimal("4.0000")
    assert out_row.total_inr == Decimal("2.0000")
    assert in_row.meta["total_tokens"] == "2000"


def test_llm_total_tokens_is_summed_and_never_reconstructed() -> None:
    """§1.3: `total_tokens` is the only cross-provider comparable figure. It is read, summed
    and stamped; the property asserted here is that the accessor reports the REPORTED totals
    and not prompt + completion."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(llm(prompt=100, completion=50, total=150))
    meter.observe(llm(prompt=200, completion=100, total=300))

    assert meter.llm_total_tokens == 450


@pytest.mark.asyncio
async def test_the_observer_seam_feeds_the_meter_from_a_real_metrics_frame() -> None:
    """End to end through the seam the pipeline actually uses: a `MetricsFrame` travelling
    between two processors becomes a `ServiceUsageRecord` becomes our count. Exercised
    through the public `on_push_frame` rather than the observer's private dispatch, so the
    test breaks if the wiring breaks and not only if our own arithmetic does."""
    meter = CallMeter(rates=FakeRates())
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
    meter = CallMeter(rates=FakeRates())
    with pytest.raises(CarrierFactsMissingError) as exc:
        meter.metered_rows(carrier=None, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.CARRIER
    assert exc.value.code == "meter_carrier_cdr_missing"
    assert "session duration" in exc.value.remediation


def test_the_runtime_leg_refuses_because_the_active_minute_is_unknown() -> None:
    """§7 / P-1. There is no plausible number here and no way to supply one but an invoice."""
    meter = CallMeter(rates=FakeRates())
    with pytest.raises(RuntimePriceUnknownError) as exc:
        meter.metered_rows(carrier=CDR, runtime=None)

    assert exc.value.leg is MeteredLeg.RUNTIME
    assert "UNKNOWN" in exc.value.detail


def test_no_rate_card_refuses_every_measured_leg() -> None:
    meter = CallMeter(rates=None)
    meter.observe(stt(10.0))
    with pytest.raises(RateCardMissingError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.STT


def test_a_refusing_rate_card_refuses_the_stt_leg_by_name() -> None:
    meter = CallMeter(rates=RefusingRates())
    meter.observe(stt(10.0))
    with pytest.raises(RateRefusedError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.STT
    assert "no attested STT rate" in exc.value.detail


def test_a_refusing_rate_card_refuses_the_tts_leg_by_name() -> None:
    meter = CallMeter(rates=RefusingRates())
    meter.observe(tts(500))
    with pytest.raises(RateRefusedError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.TTS


def test_an_unpriced_model_refuses_rather_than_metering_the_language_leg_free() -> None:
    """`llm_inr_per_ktok` raises for a model nobody attested; that refusal reaches the ledger."""
    meter = CallMeter(rates=FakeRates(priced_model="gpt-4o-mini"))
    meter.observe(llm(prompt=100, completion=100, total=200, model="gemini-2.5-flash-lite"))
    with pytest.raises(RateRefusedError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.LLM
    assert "gemini-2.5-flash-lite" in exc.value.detail


def test_a_net_reporting_provider_refuses_instead_of_underbilling_the_cache() -> None:
    """THE §1.3 TRAP. Anthropic/Bedrock report `prompt_tokens` NET of the prompt cache, so the
    parts fall short of `total_tokens` — billing them would silently drop the cached prompt."""
    meter = CallMeter(rates=FakeRates(priced_model="claude-haiku"))
    meter.observe(llm(prompt=100, completion=50, total=900, model="claude-haiku"))
    with pytest.raises(TokenUsageNotComparableError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert exc.value.leg is MeteredLeg.LLM
    assert "900" in exc.value.detail


def test_usage_without_a_total_refuses_rather_than_being_dropped() -> None:
    meter = CallMeter(rates=FakeRates())
    meter.observe(llm(prompt=100, completion=50, total=None))
    with pytest.raises(LlmTotalTokensMissingError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert "AzureLLMService" in exc.value.detail


def test_usage_without_a_model_refuses_because_a_price_is_per_model() -> None:
    meter = CallMeter(rates=FakeRates())
    meter.observe(llm(prompt=100, completion=50, total=150, model=None))
    with pytest.raises(LlmModelUnnamedError):
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)


def test_two_models_in_one_session_refuse_rather_than_picking_one() -> None:
    """One ledger row per call per unit type, so a second model cannot be priced beside it."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(llm(prompt=100, completion=50, total=150))
    meter.observe(llm(prompt=10, completion=5, total=15, model="gpt-4.1-mini"))
    with pytest.raises(LlmModelAmbiguousError) as exc:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert "gpt-4.1-mini" in exc.value.detail


def test_every_refusal_shares_one_base_so_a_zero_substitution_is_greppable() -> None:
    for error in (
        CarrierFactsMissingError,
        RuntimePriceUnknownError,
        RateCardMissingError,
        RateRefusedError,
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
    meter = CallMeter(rates=None)
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
    meter = CallMeter(rates=RefusingRates())
    rows = meter.metered_rows(carrier=CDR, runtime=RUNTIME)

    assert {row.leg for row in rows} == {MeteredLeg.CARRIER, MeteredLeg.RUNTIME}


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
    meter = CallMeter(rates=FakeRates())
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.STT, processor="p", timestamp=1.0))

    with pytest.raises(LegNotMeterableError) as refusal:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)
    assert refusal.value.leg is MeteredLeg.STT


def test_tts_reports_we_could_not_read_refuse_the_leg_rather_than_vanish() -> None:
    """The same hole on the synthesiser leg: `characters` is `int | None` at source
    (`service_metrics_observer.py:108`), and a report carrying none used to be dropped."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.TTS, processor="p", timestamp=1.0))

    with pytest.raises(LegNotMeterableError) as refusal:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)
    assert refusal.value.leg is MeteredLeg.TTS


def test_an_unreadable_speech_report_still_refuses_when_other_reports_were_fine() -> None:
    """The dangerous direction: reports we COULD read make the leg look healthy, so a
    partially-unreadable leg used to settle at a quantity that was short by however much the
    dropped reports carried. A short quantity is a wrong price, not a missing one."""
    meter = CallMeter(rates=FakeRates())
    meter.observe(stt(10.0))
    meter.observe(ServiceUsageRecord(kind=ServiceUsageKind.STT, processor="p", timestamp=1.0))

    with pytest.raises(LegNotMeterableError) as refusal:
        meter.metered_rows(carrier=CDR, runtime=RUNTIME)
    assert refusal.value.leg is MeteredLeg.STT
