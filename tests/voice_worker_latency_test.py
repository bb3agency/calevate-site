"""`voice_worker/latency.py`: Pipecat's per-turn timings reduced to OUR `CallLatency`.

Two halves. The first drives the vendor's real `UserBotLatencyObserver` with frames on a fake
clock, so a change in how 1.10.0 anchors a cycle or names a span fails here rather than in a
distribution nobody looks at. The second pins the reduction rules on hand-built breakdowns:
what is a turn, which of several first-byte reports counts, and that an unmeasurable figure
is absent rather than zero.
"""

from __future__ import annotations

import asyncio
import math

import pytest
from calevate_shared.engine import CallLatency, TurnLatency
from calevate_shared.worker_api import MAX_LATENCY_TURNS, SettlementRequest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    LatencyContribution,
    LatencyOwnerKind,
    MeasuredFrom,
    TTFBBreakdownMetrics,
    UserBotLatencyObserver,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pydantic import ValidationError
from tests.voice_worker_pipeline_test import CREDENTIALS, make_config
from voice_worker import pipeline
from voice_worker.latency import CallLatencyRecorder, leg_names


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _legs() -> pipeline.VendorLegs:
    return pipeline.build_vendor_legs(make_config(), CREDENTIALS)


async def _push(
    observer: UserBotLatencyObserver, clock: _Clock, at: float, source: FrameProcessor, frame: Frame
) -> None:
    clock.now = at
    await observer.on_push_frame(
        FramePushed(
            source=source,
            destination=source,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
    )


# --- through the vendor's observer ------------------------------------------------------


async def test_one_answered_turn_through_the_real_observer() -> None:
    legs = _legs()
    recorder = CallLatencyRecorder()
    recorder.bind(Pipeline([legs.stt, legs.llm, legs.tts]))
    clock = _Clock(100.0)
    observer = UserBotLatencyObserver(time_source=clock)
    recorder.attach(observer)
    llm, tts, stt = legs.llm.name, legs.tts.name, legs.stt.name

    # The caller fell silent at 100.0; the VAD confirmed it 0.2 s later.
    await _push(
        observer,
        clock,
        100.2,
        legs.stt,
        VADUserStoppedSpeakingFrame(stop_secs=0.2, timestamp=100.2),
    )
    await _push(observer, clock, 100.5, legs.stt, TranscriptionFrame("x", "caller", "t"))
    await _push(observer, clock, 100.6, legs.llm, LLMFullResponseStartFrame())
    await _push(
        observer,
        clock,
        100.9,
        legs.llm,
        MetricsFrame(data=[TTFBMetricsData(processor=llm, value=0.3)]),
    )
    await _push(observer, clock, 100.95, legs.llm, LLMTextFrame("y"))
    await _push(
        observer,
        clock,
        101.2,
        legs.tts,
        MetricsFrame(data=[TTFBMetricsData(processor=tts, value=0.25)]),
    )
    await _push(
        observer,
        clock,
        101.2,
        legs.tts,
        TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=8000, num_channels=1),
    )
    # The STT service's own first-byte report, which the timing must NOT come from.
    await _push(
        observer,
        clock,
        101.25,
        legs.stt,
        MetricsFrame(data=[TTFBMetricsData(processor=stt, value=9.0)]),
    )
    await _push(observer, clock, 101.3, legs.tts, BotStartedSpeakingFrame())
    # The handler is dispatched as its own task (`utils/base_object.py:256-261`).
    await asyncio.sleep(0)

    latency = recorder.call_latency()
    assert latency is not None
    (turn,) = latency.turns
    assert turn.turn == 1
    assert turn.stt_ms == pytest.approx(500.0)
    assert turn.llm_ttft_ms == pytest.approx(300.0)
    assert turn.tts_ttfa_ms == pytest.approx(250.0)
    assert latency.time_to_first_audio_ms == pytest.approx(1300.0)
    assert latency.region is None
    assert latency.parse_warnings == []


def test_the_legs_are_found_by_service_class_and_named_as_their_metrics_are() -> None:
    legs = _legs()
    found = leg_names(Pipeline([legs.stt, legs.llm, legs.tts]))
    assert found == {legs.llm.name: "llm", legs.tts.name: "tts"}


# --- the reduction rules -----------------------------------------------------------------


def _breakdown(
    *,
    silence: float | None = 10.0,
    transcript_at: float | None = 10.4,
    ttfb: tuple[tuple[str, float], ...] = (("llm#0", 0.3), ("tts#0", 0.2)),
    total: float = 1.1,
    measured_from: MeasuredFrom | None = MeasuredFrom.USER_SILENCE,
) -> LatencyBreakdown:
    contributions = []
    if transcript_at is not None:
        contributions.append(
            LatencyContribution(
                key="transcription",
                label="transcription",
                owner="stt#0",
                owner_kind=LatencyOwnerKind.SERVICE,
                start_time=10.2,
                duration_secs=transcript_at - 10.2,
            )
        )
    return LatencyBreakdown(
        ttfb=[
            TTFBBreakdownMetrics(processor=name, start_time=0.0, duration_secs=value)
            for name, value in ttfb
        ],
        contributions=contributions,
        measured_from=measured_from,
        total_secs=total,
        user_turn_start_time=silence,
    )


def _bound(recorder: CallLatencyRecorder) -> CallLatencyRecorder:
    recorder._legs = {"llm#0": "llm", "tts#0": "tts"}
    return recorder


def test_a_call_nobody_answered_reports_nothing_rather_than_an_empty_object() -> None:
    recorder = _bound(CallLatencyRecorder())
    # The greeting: anchored on the client connecting, not on a caller falling silent.
    recorder.observe(_breakdown(silence=None, measured_from=MeasuredFrom.CLIENT_CONNECTED))
    assert recorder.call_latency() is None


def test_the_first_report_per_leg_is_the_turn_and_strangers_are_ignored() -> None:
    recorder = _bound(CallLatencyRecorder())
    recorder.observe(
        _breakdown(ttfb=(("llm#0", 0.3), ("other#0", 0.01), ("llm#0", 0.9), ("tts#0", 0.2)))
    )
    latency = recorder.call_latency()
    assert latency is not None
    assert latency.turns == [
        TurnLatency(turn=1, stt_ms=400.0, llm_ttft_ms=300.0, tts_ttfa_ms=200.0)
    ]


def test_an_unmeasured_leg_is_absent_never_zero() -> None:
    recorder = _bound(CallLatencyRecorder())
    recorder.observe(_breakdown(transcript_at=None, ttfb=(("tts#0", math.nan),)))
    recorder.observe(_breakdown(silence=10.5, ttfb=(("llm#0", -0.1),)))
    latency = recorder.call_latency()
    assert latency is not None
    first, second = latency.turns
    assert (first.stt_ms, first.llm_ttft_ms, first.tts_ttfa_ms) == (None, None, None)
    # Transcript at 10.4 against a silence at 10.5 is an interval that cannot have happened.
    assert (second.stt_ms, second.llm_ttft_ms, second.tts_ttfa_ms) == (None, None, None)
    assert [turn.turn for turn in latency.turns] == [1, 2]


def test_time_to_first_audio_is_the_median_of_turns_anchored_on_the_caller() -> None:
    recorder = _bound(CallLatencyRecorder())
    for total in (0.9, 1.5, 1.2):
        recorder.observe(_breakdown(total=total))
    recorder.observe(_breakdown(total=99.0, measured_from=None))
    latency = recorder.call_latency()
    assert latency is not None
    assert len(latency.turns) == 4
    assert latency.time_to_first_audio_ms == pytest.approx(1200.0)


def test_a_long_call_is_truncated_visibly() -> None:
    recorder = _bound(CallLatencyRecorder(max_turns=2))
    for _ in range(5):
        recorder.observe(_breakdown())
    latency = recorder.call_latency()
    assert latency is not None
    assert len(latency.turns) == 2
    assert latency.parse_warnings == ["3 turn(s) after the first 2 were not recorded."]


def test_a_pipeline_with_no_timed_service_says_so() -> None:
    recorder = CallLatencyRecorder()
    recorder.observe(_breakdown())
    latency = recorder.call_latency()
    assert latency is not None
    assert (latency.turns[0].llm_ttft_ms, latency.turns[0].tts_ttfa_ms) == (None, None)
    assert latency.turns[0].stt_ms == pytest.approx(400.0)
    assert len(latency.parse_warnings) == 1


# --- the wire bound ----------------------------------------------------------------------


def _settlement(latency: CallLatency) -> SettlementRequest:
    return SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        latency=latency,
    )


def test_the_settlement_carries_a_well_formed_report() -> None:
    latency = CallLatency(
        time_to_first_audio_ms=1200.0,
        turns=[TurnLatency(turn=1, stt_ms=400.0, llm_ttft_ms=None, tts_ttfa_ms=200.0)],
    )
    assert _settlement(latency).latency == latency


@pytest.mark.parametrize(
    "latency",
    [
        CallLatency(turns=[TurnLatency(turn=1, llm_ttft_ms=math.inf)]),
        CallLatency(turns=[TurnLatency(turn=1, stt_ms=-1.0)]),
        CallLatency(turns=[TurnLatency(turn=0)]),
        CallLatency(time_to_first_audio_ms=math.nan),
        CallLatency(turns=[TurnLatency(turn=1)] * (MAX_LATENCY_TURNS + 1)),
        CallLatency(parse_warnings=["x" * 501]),
        CallLatency(region="r" * 65),
    ],
)
def test_the_settlement_refuses_a_malformed_report(latency: CallLatency) -> None:
    with pytest.raises(ValidationError):
        _settlement(latency)
