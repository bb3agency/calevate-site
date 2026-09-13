"""`docs/PIPECAT-MIGRATION.md` §6 step 4: the worker pipeline, run locally against a fake transport.

**WHAT THIS FILE IS TRYING TO CATCH**, because a test that only proves the code imports is
not step 4:

1. Every default we changed is still changed, and is still DIFFERENT from the vendor's —
   each assertion reads the vendor's own default out of the installed package rather than
   restating it, so a dependency bump that moves a default fails here instead of silently
   restoring it.
2. The assembled pipeline actually RUNS: a real `PipelineWorker` under a real
   `WorkerRunner`, frames in at the head, a real user aggregator and a real assistant
   aggregator in the middle, and OUR normalized models out of the sink.
3. Hard rule 2 at its new boundary: nothing that reaches the sink is a Pipecat object.
4. Hard rule 6: the vendor's own logging cannot emit conversation content.

**WHAT IT DOES NOT EXERCISE, IN THOSE WORDS.** The user aggregator's own firing of
`on_user_turn_stopped` is NOT exercised end to end. Reaching it requires Silero VAD to
classify real audio as speech (`BaseSmartTurn.append_audio` only starts counting silence
once `_speech_triggered` is set, `pipecat/audio/turn/smart_turn/base_smart_turn.py:121-127`),
and synthetic audio that Silero reliably calls speech is not something this suite can
produce without a recording. The conversion from the framework's turn message to our
`TranscriptTurn` is exercised directly with real vendor message objects; the VAD/smart-turn
firing that produces those messages is `pre-build-blockers` §3.6 M-1..M-3, and is a
measurement on real Telugu PSTN audio, not a unit test.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from calevate_shared.engine import (
    ModelConfig,
    azure_openai_base_url,
    google_openai_compat_base_url,
)
from calevate_shared.events import CallEvent, TranscriptTurn
from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import STOP_SECS, SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMRunFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    UserTurnStoppedMessage,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import MODEL_CONFIGS as SARVAM_STT_MODEL_CONFIGS
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService, SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService, SarvamTTSSpeakerV3
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.workers.runner import WorkerRunner
from pydantic import ValidationError
from voice_worker import pipeline, vendor_logging

# --------------------------------------------------------------------------------------
# Fakes. Deliberately NOT subclasses of the vendor service base classes: a stub that
# inherits `WebsocketTTSService` inherits a connection lifecycle, and then the test is
# about the stub.
# --------------------------------------------------------------------------------------


class _PassThrough(FrameProcessor):
    """Pushes every frame on. `FrameProcessor.process_frame` does not push by itself."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.seen: list[Frame] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self.seen.append(frame)
        await self.push_frame(frame, direction)


class FakeTransport(BaseTransport):
    """A transport with no carrier, no websocket and no audio device.

    §6 step 4 asks for exactly this: "Nothing before step 6 needs an account. Pipecat is a
    library; the worker runs locally."
    """

    def __init__(self) -> None:
        super().__init__()
        self._in = _PassThrough("fake-input")
        self._out = _PassThrough("fake-output")

    def input(self) -> FrameProcessor:
        return self._in

    def output(self) -> FrameProcessor:
        return self._out


class FakeLLM(_PassThrough):
    """Answers an `LLMContextFrame` with one complete response.

    The user aggregator consumes `LLMRunFrame` and pushes an `LLMContextFrame` in its
    place, so that — not the run frame — is what an LLM service in this position sees.
    """

    def __init__(self, reply: str) -> None:
        super().__init__("fake-llm")
        self._reply = reply

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self.push_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
            await self.push_frame(LLMTextFrame(self._reply), FrameDirection.DOWNSTREAM)
            await self.push_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)


class RecordingSink:
    """The other side of the boundary. Refuses anything that is not one of our models."""

    def __init__(self) -> None:
        self.events: list[CallEvent] = []
        self.turns: list[TranscriptTurn] = []

    async def on_call_event(self, event: CallEvent) -> None:
        assert type(event) is CallEvent, f"a non-normalized object crossed the boundary: {event!r}"
        self.events.append(event)

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None:
        assert type(turn) is TranscriptTurn, f"a non-normalized object crossed: {turn!r}"
        self.turns.append(turn)


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

PROMPT = "You are Calevate's receptionist. You are an AI. This call is recorded."


def make_config(**overrides: Any) -> pipeline.SessionConfig:
    models = ModelConfig(
        stt_model="saaras:v4",
        tts_provider="sarvam",
        tts_model="bulbul:v3",
        tts_voice="shubh",
        llm_provider="azure_openai",
        llm_model="calevate-gpt-4o-mini",
        llm_base_url=azure_openai_base_url("calevate-eastus2"),
    )
    base: dict[str, Any] = {
        "call_id": "call-1",
        "tenant_id": uuid4(),
        "agent_id": uuid4(),
        "agent_config_version_id": uuid4(),
        "direction": "inbound",
        "system_prompt": PROMPT,
        "prompt_sha256": pipeline.recompute_prompt_sha256(PROMPT),
        "models": models,
        "language": "te-IN",
    }
    base.update(overrides)
    return pipeline.SessionConfig(**base)


CREDENTIALS = pipeline.VendorCredentials(sarvam_api_key="sarvam-test", llm_api_key="llm-test")


def assemble(sink: RecordingSink) -> tuple[pipeline.AssembledCall, FakeTransport, FakeLLM]:
    transport = FakeTransport()
    llm = FakeLLM("నమస్కారం")
    legs = pipeline.VendorLegs(stt=_PassThrough("fake-stt"), llm=llm, tts=_PassThrough("fake-tts"))
    call = pipeline.assemble_call(config=make_config(), legs=legs, transport=transport, sink=sink)
    return call, transport, llm


# --------------------------------------------------------------------------------------
# 1. The defaults we changed, each against the vendor's own default.
# --------------------------------------------------------------------------------------


def test_smart_turn_stop_secs_is_ours_and_not_the_vendors() -> None:
    """3 s is the shipped default and is 4.6x the endpointing this migration must beat."""
    assert STOP_SECS == 3, "the vendor default moved; re-read base_smart_turn.py and re-argue"
    assert SmartTurnParams().stop_secs == 3
    assert pytest.approx(0.65) == pipeline.SMART_TURN_STOP_SECS

    params = pipeline.build_user_aggregator_params()
    strategies = params.user_turn_strategies
    assert strategies is not None
    (stop,) = strategies.stop
    assert isinstance(stop, TurnAnalyzerUserTurnStopStrategy)
    analyzer = stop._turn_analyzer
    assert isinstance(analyzer, LocalSmartTurnAnalyzerV3), (
        "the torch path (`local-smart-turn`) is deliberately not installed; v3 is the ONNX one"
    )
    assert analyzer.params.stop_secs == pytest.approx(pipeline.SMART_TURN_STOP_SECS)


def test_vad_is_configured_on_the_user_aggregator_not_the_transport() -> None:
    """The obvious place is the wrong place in 1.10.0, so pin both halves."""
    assert "vad_analyzer" not in TransportParams.model_fields
    assert "turn_analyzer" not in TransportParams.model_fields
    params = pipeline.build_user_aggregator_params()
    assert isinstance(params.vad_analyzer, SileroVADAnalyzer)


def test_function_call_timeout_is_set_because_the_default_is_no_timeout() -> None:
    signature = inspect.signature(
        __import__("pipecat.services.llm_service", fromlist=["LLMService"]).LLMService.__init__
    )
    assert signature.parameters["function_call_timeout_secs"].default is None, (
        "the vendor default changed; re-argue the value in pipeline.FUNCTION_CALL_TIMEOUT_SECS"
    )
    legs = pipeline.build_vendor_legs(make_config(), CREDENTIALS)
    # Private attribute by necessity: the service exposes no reader for it, and the whole
    # point of this test is that the value REACHED the service rather than that we typed it.
    assert legs.llm._function_call_timeout_secs == pipeline.FUNCTION_CALL_TIMEOUT_SECS
    # Above the in-call tool endpoint's own worst case (0.5 s body + 1.0 s durable), or we
    # would cancel the handler in the instant it was producing a refusal the agent can say.
    assert pipeline.FUNCTION_CALL_TIMEOUT_SECS > 1.5


def test_metrics_are_enabled_because_hard_rule_7_needs_a_real_cost() -> None:
    sink = RecordingSink()
    call, _, _ = assemble(sink)
    params = call.worker.params
    assert params.enable_metrics and params.enable_usage_metrics
    assert params.audio_in_sample_rate == pipeline.TELEPHONY_SAMPLE_RATE_HZ == 8000


# --------------------------------------------------------------------------------------
# 2. The STT choice, decided from source.
# --------------------------------------------------------------------------------------


def test_stt_is_the_only_sarvam_class_that_can_run_our_declared_model() -> None:
    assert pipeline.STT_MODEL == "saaras:v4"
    assert pipeline.STT_MODEL in SARVAM_STT_MODEL_CONFIGS
    # The realtime class is pinned to one id and it is not ours, which is what settles the
    # choice — not the fact that it is faster on the vendor's own benchmark.
    from pipecat.services.sarvam import stt as sarvam_stt

    assert sarvam_stt._REALTIME_MODEL == "saaras:v3-realtime"
    assert sarvam_stt._REALTIME_MODEL not in SARVAM_STT_MODEL_CONFIGS
    assert SarvamRealtimeSTTService.Settings is not SarvamSTTService.Settings

    legs = pipeline.build_vendor_legs(make_config(), CREDENTIALS)
    assert isinstance(legs.stt, SarvamSTTService)
    assert legs.stt._settings.model == "saaras:v4"
    assert legs.stt._settings.language == "te-IN"


def test_sarvam_keeps_local_smart_turn_because_vad_signals_is_left_unset() -> None:
    """`vad_signals` on would hand turn ownership to Sarvam and disable smart turn."""
    legs = pipeline.build_vendor_legs(make_config(), CREDENTIALS)
    assert isinstance(legs.stt, SarvamSTTService)
    assert not legs.stt._settings.vad_signals
    assert legs.stt.service_metadata_frame().user_turn_strategies is None


def test_sarvam_tts_speakers_are_a_closed_enum_which_is_the_ground_for_d593() -> None:
    """Recorded, not acted on: a closed speaker set has nowhere to put a cloned voice."""
    assert len(list(SarvamTTSSpeakerV3)) > 0
    assert "shubh" in {speaker.value for speaker in SarvamTTSSpeakerV3}
    legs = pipeline.build_vendor_legs(make_config(), CREDENTIALS)
    assert isinstance(legs.tts, SarvamTTSService)
    assert legs.tts._settings.model == "bulbul:v3"


def test_the_google_leg_is_the_openai_compat_wire_this_repo_already_speaks() -> None:
    """`gemini-2.5-flash-lite` is the PLATFORM DEFAULT, so this leg has to run.

    Two properties, and the second is the one that would rot silently. It must be an
    `OpenAILLMService` — Pipecat's own Gemini service needs `google-genai`, which this
    worker deliberately does not install, and adding it would be a second way to reach a
    vendor `copilot/service._google_leg` already reaches. And its `base_url` must be
    exactly what `google_openai_compat_base_url()` emits, not a value that merely looks
    like it: the endpoint a caller's words are sent to is the one field D-127's whole
    argument turns on, and a hand-typed host that drifted from the builder would pass any
    test that spelled the URL itself.
    """
    config = make_config(
        models=ModelConfig(llm_provider="google", llm_model="gemini-2.5-flash-lite")
    )
    legs = pipeline.build_vendor_legs(config, CREDENTIALS)
    assert isinstance(legs.llm, OpenAILLMService)
    assert str(legs.llm._client.base_url).rstrip("/") == google_openai_compat_base_url()


def test_no_caller_can_hand_the_google_leg_an_endpoint() -> None:
    """The guarantee is enforced a layer ABOVE this worker, and that is the stronger place.

    The first draft of this test asserted that `_build_llm` IGNORES a configured
    `llm_base_url` on the google leg. It failed, and the failure was the better answer:
    `ModelConfig`'s own validator refuses the combination outright, so the value cannot
    reach the worker to be ignored. A worker-side check would have been a second guard on
    a door that is already locked — and one that would keep passing if the real one were
    ever removed.

    So what is pinned here is the property the worker RELIES on: there is exactly one
    Gemini endpoint in this product, it comes from `google_openai_compat_base_url()`, and
    no row, config or caller can name another. If this refusal is ever relaxed, this test
    fails and `_build_llm`'s google branch needs the ignore the first draft assumed.

    ⚠ The validator's stated REASON is now stale, though its rule is not: it says "the
    engine builds its own client from a single API key and never reads one", which was
    written when the engine was Bolna talking the native `:generateContent` protocol. This
    worker IS the engine now and it does read a base URL — ours, from the builder, never
    from config. Fixing that sentence is this change's follow-up in `calevate_shared`.
    """
    with pytest.raises(ValidationError, match="takes no in-call base URL"):
        ModelConfig(
            llm_provider="google",
            llm_model="gemini-2.5-flash-lite",
            llm_base_url="https://attacker.example/v1",
        )


# --------------------------------------------------------------------------------------
# 3. Assembly and a real local run.
# --------------------------------------------------------------------------------------


def test_pipeline_is_the_shipped_ordering() -> None:
    sink = RecordingSink()
    call, transport, llm = assemble(sink)
    # `Pipeline` wraps the caller's list with its own source and sink, so drop the ends.
    middle = call.pipeline._processors[1:-1]
    assert middle == [
        transport.input(),
        call.pipeline._processors[2],  # stt
        call.aggregators.user(),
        llm,
        call.pipeline._processors[5],  # tts
        transport.output(),
        call.aggregators.assistant(),
    ]
    # The assistant aggregator is AFTER the output, not before.
    assert middle.index(call.aggregators.assistant()) > middle.index(transport.output())


async def test_start_conversation_honours_greet_first() -> None:
    """The greeting decision is config, and it is READ — not a field nobody consults."""
    sink = RecordingSink()
    call, _, _ = assemble(sink)
    assert call.greet_first
    assert await call.start_conversation() is True
    assert call.context.messages[-1]["role"] == "developer"

    silent = pipeline.assemble_call(
        config=make_config(greet_first=False),
        legs=pipeline.VendorLegs(
            stt=_PassThrough("s"), llm=_PassThrough("l"), tts=_PassThrough("t")
        ),
        transport=FakeTransport(),
        sink=sink,
    )
    before = len(silent.context.messages)
    assert await silent.start_conversation() is False
    assert len(silent.context.messages) == before


def test_prompt_sha_is_recomputed_not_echoed() -> None:
    sink = RecordingSink()
    call, _, _ = assemble(sink)
    assert call.observed_prompt_sha256 == pipeline.recompute_prompt_sha256(PROMPT)
    assert call.prompt_matches_config_version

    stale = make_config(prompt_sha256="0" * 64)
    drifted = pipeline.assemble_call(
        config=stale,
        legs=pipeline.VendorLegs(
            stt=_PassThrough("s"), llm=_PassThrough("l"), tts=_PassThrough("t")
        ),
        transport=FakeTransport(),
        sink=sink,
    )
    assert not drifted.prompt_matches_config_version


async def test_local_run_against_a_fake_transport_emits_normalized_events() -> None:
    """The real thing: worker + runner + real aggregators, frames in, our models out."""
    sink = RecordingSink()
    call, transport, _ = assemble(sink)
    worker = call.worker

    started = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def _started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=20)
        assert [event.status for event in sink.events] == ["in_progress"]

        # Kick the conversation off the way the shipped example does.
        await worker.queue_frame(LLMRunFrame())
        for _ in range(200):
            if sink.turns:
                break
            await asyncio.sleep(0.01)

        await worker.stop_when_done()
        await asyncio.wait_for(run, timeout=20)
    finally:
        if not run.done():
            run.cancel()

    # An agent turn came out of the REAL assistant aggregator, as our model.
    agent_turns = [turn for turn in sink.turns if turn.speaker == "agent"]
    assert agent_turns, "the assistant aggregator produced no turn"
    assert agent_turns[0].text == "నమస్కారం"
    assert agent_turns[0].call_id == "call-1"
    assert agent_turns[0].text_redacted is None  # workers/redaction.py owns that column
    assert agent_turns[0].lang == "te-IN"

    # And the call closed exactly once.
    assert [event.status for event in sink.events] == ["in_progress", "completed"]
    assert {event.engine for event in sink.events} == {"pipecat"}

    # Frames really traversed the fake transport rather than the test faking the middle.
    assert any(isinstance(frame, LLMTextFrame) for frame in transport.output().seen)


async def test_transcription_frames_never_reach_the_tail_which_is_why_events_are_the_boundary() -> (
    None
):
    """Pins the source fact the boundary's design rests on.

    The user aggregator CONSUMES `TranscriptionFrame`. If that ever changes, a tail-placed
    normalizer becomes viable and this comment stops being true — so assert it rather than
    trusting a line number in a docstring.
    """
    sink = RecordingSink()
    call, transport, _ = assemble(sink)
    worker = call.worker
    started = asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def _started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=20)
        await worker.queue_frame(
            TranscriptionFrame("హలో", user_id="caller", timestamp="2026-09-13T00:00:00.000+00:00")
        )
        await asyncio.sleep(0.2)
        await worker.stop_when_done()
        await asyncio.wait_for(run, timeout=20)
    finally:
        if not run.done():
            run.cancel()

    assert not any(isinstance(frame, TranscriptionFrame) for frame in transport.output().seen), (
        "TranscriptionFrame now reaches the tail; re-read NormalizedEventBoundary's design note"
    )


async def test_boundary_converts_the_frameworks_turn_messages_to_our_models() -> None:
    """The caller half, driven with the vendor's real message types.

    See this module's docstring for what is NOT exercised here and why.
    """
    sink = RecordingSink()
    boundary = pipeline.NormalizedEventBoundary(config=make_config(), sink=sink)
    await boundary.call_started()
    await boundary.user_turn(
        UserTurnStoppedMessage(
            content="నాకు అపాయింట్‌మెంట్ కావాలి", timestamp="2026-09-13T00:00:00.000+00:00"
        )
    )
    await boundary.assistant_turn(
        AssistantTurnStoppedMessage(
            content="సరే", interrupted=False, timestamp="2026-09-13T00:00:01.000+00:00"
        )
    )
    # Realtime mode's `content=None`, and an interrupted turn with nothing spoken, are real
    # outcomes rather than errors — neither becomes a blank row.
    await boundary.user_turn(
        UserTurnStoppedMessage(content=None, timestamp="2026-09-13T00:00:02.000+00:00")
    )
    await boundary.assistant_turn(
        AssistantTurnStoppedMessage(
            content="", interrupted=True, timestamp="2026-09-13T00:00:02.000+00:00"
        )
    )
    await boundary.call_ended()
    await boundary.call_ended()  # idempotent

    assert [(turn.idx, turn.speaker) for turn in sink.turns] == [(0, "caller"), (1, "agent")]
    assert [event.status for event in sink.events] == ["in_progress", "completed"]
    assert all(turn.start_ms is not None and turn.end_ms is not None for turn in sink.turns)


# --------------------------------------------------------------------------------------
# 4. Hard rule 6 at the vendor's own log calls.
# --------------------------------------------------------------------------------------


def test_the_pinned_content_bearing_log_line_is_still_that_line() -> None:
    """A version bump that moves the line must fail here, not leak in production."""
    import pipecat

    root = Path(pipecat.__file__).parent.parent
    for (module, line), expected in vendor_logging.CONTENT_BEARING_SOURCE.items():
        path = root / (module.replace(".", "/") + ".py")
        actual = path.read_text(encoding="utf-8").splitlines()[line - 1].strip()
        assert actual == expected, f"{module}:{line} is no longer the pinned call"


def test_vendor_log_guard_drops_debug_and_the_content_bearing_warning() -> None:
    captured: list[str] = []
    vendor_logging._reset_for_tests()
    try:
        vendor_logging.install_vendor_log_guard(sink=captured.append)
        module, line = next(iter(vendor_logging.CONTENT_BEARING_RECORDS))

        # A DEBUG line from anywhere: dropped by the level floor.
        logger.debug("caller said something")
        assert not captured

        # An INFO line: kept, because operators need the process to be observable.
        logger.info("session started")
        assert len(captured) == 1

        # The pinned record: dropped even though it is a WARNING.
        record = {"name": module, "line": line, "level": logger.level("WARNING")}
        assert vendor_logging._guard(record) is False
        neighbour = {"name": module, "line": line + 1, "level": logger.level("WARNING")}
        assert vendor_logging._guard(neighbour)
    finally:
        # Put the real guard back rather than a null sink: loguru is process-global, and a
        # test that leaves logging off would hide the next one's vendor output.
        vendor_logging._reset_for_tests()
        logger.remove()
        vendor_logging.install_vendor_log_guard()
