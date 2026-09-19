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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from calevate_shared.engine import (
    ModelConfig,
    azure_openai_base_url,
    google_openai_compat_base_url,
)
from calevate_shared.events import CallEvent, TranscriptTurn
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
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
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import MODEL_CONFIGS as SARVAM_STT_MODEL_CONFIGS
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService, SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService, SarvamTTSSpeakerV3
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.workers.runner import WorkerRunner
from pydantic import ValidationError
from voice_worker import pipeline, vendor_logging
from voice_worker.knowledge import (
    LexicalIndex,
    PackCache,
    SessionKnowledge,
    load_session_knowledge,
)

# Stable document ids, so a provenance assertion names a document rather than a uuid the
# fixture invented one line earlier.
HOURS_DOC = UUID("0199c0de-0001-7000-8000-00000000000a")
CONSULTATION_DOC = UUID("0199c0de-0001-7000-8000-00000000000b")
SCAN_DOC = UUID("0199c0de-0001-7000-8000-00000000000c")

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
        tts_provider="cartesia",
        tts_model="sonic-3.5",
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


#: ⚠ **THE CARTESIA KEY IS NOT OPTIONAL FOR THIS FIXTURE ANY MORE (18 Sep 2026).** Sarvam's
#: key alone used to be enough because the TTS leg fell back to Sarvam; the founder
#: withdrew that leg, so a session whose agent speaks at all needs its vendor's key.
#: **`sarvam_api_key` STAYS AND IS STILL REQUIRED** — Saaras transcribes every call.
CREDENTIALS = pipeline.VendorCredentials(
    sarvam_api_key="sarvam-test",
    llm_api_key="llm-test",
    cartesia_api_key="cartesia-test",
)


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
    """A closed speaker set has nowhere to put a cloned voice — the structural fact behind
    D-593, and the one that outlived it.

    ⚠ **IT WAS "RECORDED, NOT ACTED ON" UNTIL 18 Sep 2026, AND IT HAS NOW BEEN ACTED ON.**
    The founder withdrew the Sarvam TEXT-TO-SPEECH leg; there is no `SarvamTTSService` in
    this pipeline any more and no default model to fall back to. The enum reading stays
    because the reason it was recorded stays: whoever proposes putting a cloned voice on a
    vendor should check whether that vendor's speaker set is open first.

    **SARVAM STT IS UNTOUCHED** — `legs.stt` below is the assertion that says so, and it is
    the half of this file that must never be deleted along with the other.
    """
    assert len(list(SarvamTTSSpeakerV3)) > 0
    assert "shubh" in {speaker.value for speaker in SarvamTTSSpeakerV3}

    legs = pipeline.build_vendor_legs(make_config(), CREDENTIALS)

    assert not isinstance(legs.tts, SarvamTTSService), (
        "the Sarvam TTS leg is back; it was withdrawn on 18 Sep 2026 and the Clear rung is Gnani's"
    )
    assert isinstance(legs.stt, SarvamSTTService), (
        "SARVAM STILL TRANSCRIBES EVERY CALL. Only the synthesis half was withdrawn, and a "
        "change that takes the STT leg with it has gone too far."
    )


def test_an_agent_that_names_no_tts_provider_is_refused_rather_than_given_a_default() -> None:
    """THE CHANGE WITH TEETH IN THE 18 Sep 2026 REMOVAL, asserted where it lands.

    `_build_tts` used to fall through to Sarvam for a config that named no provider, which
    was a real default with a real price on our own rate card. There is none now: Cartesia
    would silently bill the dearer rung and Gnani has no attested price at all (hard rule
    7), so the leg refuses rather than choosing a vendor on the caller's behalf.

    A refusal here is a backstop — `agents/publishing.py` is what stops such a config
    reaching a call — and the point of a backstop is that it is loud.
    """
    config = make_config(
        models=ModelConfig(
            stt_model="saaras:v4",
            llm_provider="azure_openai",
            llm_model="calevate-gpt-4o-mini",
            llm_base_url=azure_openai_base_url("calevate-eastus2"),
        )
    )

    with pytest.raises(ValueError, match="no tts_provider"):
        pipeline.build_vendor_legs(config, CREDENTIALS)


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
    # ⚠ THE TTS FIELDS ARE CARRIED EXPLICITLY SINCE 18 Sep 2026: `_build_tts` no longer has
    # a default provider to fall back to (the Sarvam leg was withdrawn), so a `ModelConfig`
    # that names only the LLM leg cannot build a pipeline at all. That refusal is the point
    # of the change and is asserted in its own clause; here it is noise.
    config = make_config(
        models=ModelConfig(
            llm_provider="google",
            llm_model="gemini-2.5-flash-lite",
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="shubh",
        )
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
        lines = path.read_text(encoding="utf-8").splitlines()
        actual = tuple(text.strip() for text in lines[line - 1 : line - 1 + len(expected)])
        assert actual == expected, f"{module}:{line} is no longer the pinned call"

    # EVERY DENIED RECORD HAS A PIN. Without this the two lists could drift apart
    # silently — an entry added to the denylist with no source pin is an entry a version
    # bump can move out from under, which is the whole failure this pair exists to stop.
    assert set(vendor_logging.CONTENT_BEARING_RECORDS) == set(vendor_logging.CONTENT_BEARING_SOURCE)


def test_vendor_log_guard_drops_debug_and_the_content_bearing_warning() -> None:
    captured: list[str] = []
    vendor_logging._reset_for_tests()
    try:
        vendor_logging.install_vendor_log_guard(sink=captured.append)
        # A DEBUG line from anywhere: dropped by the level floor.
        logger.debug("caller said something")
        assert not captured

        # An INFO line: kept, because operators need the process to be observable.
        logger.info("session started")
        assert len(captured) == 1

        # EVERY pinned record is dropped even though each is a WARNING — all three, not
        # whichever one the frozenset iterated first, which is how the two added on
        # 19 Sep 2026 (the Plivo raw frame and the output transport's `{frame}`) would
        # have been able to arrive denied-in-name-only.
        for module, line in vendor_logging.CONTENT_BEARING_RECORDS:
            record = {"name": module, "line": line, "level": logger.level("WARNING")}
            assert vendor_logging._guard(record) is False, f"{module}:{line} was not dropped"
            neighbour = {"name": module, "line": line + 1, "level": logger.level("WARNING")}
            assert vendor_logging._guard(neighbour), f"{module}:{line + 1} was over-blocked"
    finally:
        # Put the real guard back rather than a null sink: loguru is process-global, and a
        # test that leaves logging off would hide the next one's vendor output.
        vendor_logging._reset_for_tests()
        logger.remove()
        vendor_logging.install_vendor_log_guard()


async def test_a_malformed_carrier_frame_does_not_put_the_callers_audio_in_the_log() -> None:
    """The Plivo pin, proved END TO END rather than by reading the vendor's source.

    `PlivoFrameSerializer.deserialize` answers a frame it cannot parse with
    `logger.warning(f"Failed to parse JSON message: {data}")`
    (`pipecat/serializers/plivo.py:221`) — and on a media stream `data` is the raw frame,
    whose `media.payload` is base64 PCM of the CALLER'S VOICE. One truncated frame on the
    wire is all it takes, which is why this is a scenario and not a code reading.

    The negative control is the half that matters: with the guard uninstalled the audio
    DOES reach the sink, so this test fails if the denylist entry is removed rather than
    passing for some other reason.
    """
    from pipecat.serializers.plivo import PlivoFrameSerializer

    # A frame that is real Plivo media and is truncated mid-object, so `json.loads` raises
    # with the whole payload still in `data`. The marker stands in for the audio.
    audio = "QkFTRTY0QVVESU9PRlRIRUNBTExFUg"
    truncated = f'{{"event": "media", "media": {{"payload": "{audio}"'

    def _deserialize() -> Any:
        serializer = PlivoFrameSerializer(
            stream_id="scenario-stream",
            params=PlivoFrameSerializer.InputParams(auto_hang_up=False),
        )
        return serializer.deserialize(truncated)

    guarded: list[str] = []
    unguarded: list[str] = []
    vendor_logging._reset_for_tests()
    try:
        vendor_logging.install_vendor_log_guard(sink=guarded.append)
        assert await _deserialize() is None
        assert audio not in "".join(guarded), "the caller's audio reached the log"

        # The control: loguru's own defaults, which is what an unguarded process runs.
        logger.remove()
        logger.add(unguarded.append, level="DEBUG")
        assert await _deserialize() is None
        assert audio in "".join(unguarded), (
            "the vendor no longer logs the raw frame, so this pin proves nothing; "
            "re-read pipecat/serializers/plivo.py before deleting it"
        )
    finally:
        vendor_logging._reset_for_tests()
        logger.remove()
        vendor_logging.install_vendor_log_guard()


# --------------------------------------------------------------------------------------
# 5. The in-call knowledge base, wired as a tool (§6 step 11, §9.1 step 2).
#
# The search itself is `tests/voice_worker_knowledge_test.py`'s subject and is not re-tested
# here. What this section is for is the SEAM: that the tool is advertised at all, that a
# real vendor LLM service registers its handler, and that each of the five things the
# lookup can say arrives at the model as a different word — because the failure that costs
# a client is an agent that answers "we don't offer that" out of a failed fetch.
# --------------------------------------------------------------------------------------


def knowledge_entries() -> tuple[PackEntry, ...]:
    """A small published corpus. Two of the six exist to make `ambiguous` reachable.

    The Telugu-script entry with an English gloss is the §9.2 shape — store both, index the
    English — so the `found` assertion below is over the passage the client published and
    not over the retrieval key written for the ranker.
    """
    return (
        PackEntry(
            chunk_id=uuid4(),
            document_id=HOURS_DOC,
            document_version=3,
            text="క్లినిక్ ఉదయం 9 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది.",
            gloss="The clinic is open from 9 am to 8 pm on weekdays.",
        ),
        PackEntry(
            chunk_id=uuid4(),
            document_id=CONSULTATION_DOC,
            document_version=1,
            text="Consultation fee is five hundred rupees.",
        ),
        PackEntry(
            chunk_id=uuid4(),
            document_id=SCAN_DOC,
            document_version=1,
            text="Scan fee is five hundred rupees.",
        ),
    )


def build_knowledge(config: pipeline.SessionConfig) -> tuple[SessionKnowledge, str]:
    """A loaded `SessionKnowledge` for `config`'s tenant and agent, and its digest."""
    entries = knowledge_entries()
    digest = KnowledgePack.digest(config.tenant_id, config.agent_id, entries)
    pack = KnowledgePack(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        content_sha256=digest,
        built_at=datetime(2026, 9, 14, 6, 0, tzinfo=UTC),
        entries=entries,
    )
    return (
        SessionKnowledge(
            tenant_id=pack.tenant_id,
            agent_id=pack.agent_id,
            pack=pack,
            index=LexicalIndex(pack.entries),
            requested_digest=digest,
        ),
        digest,
    )


async def invoke_tool(schema: FunctionSchema, question: str) -> dict[str, Any]:
    """Call the advertised tool the way the service would, and return what the model gets.

    `FunctionCallParams` is a plain dataclass with no runtime validation, so the three
    fields this handler never touches (`llm`, `pipeline_worker`, `context`) are stand-ins:
    building a real LLM service and a real worker to reach a handler that reads only
    `arguments` and `result_callback` would make this a test about the framework.
    """
    captured: list[Any] = []

    async def result_callback(result: Any, *, properties: Any = None) -> None:
        captured.append(result)

    handler = schema.handler
    assert handler is not None, "the schema carries no handler; nothing would run"
    await handler(
        FunctionCallParams(
            function_name=schema.name,
            tool_call_id="tool-call-1",
            arguments={pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM: question},
            llm=cast(Any, None),
            pipeline_worker=cast(Any, None),
            context=cast(Any, None),
            result_callback=cast(Any, result_callback),
        )
    )
    assert len(captured) == 1, "the tool must answer exactly once"
    return cast(dict[str, Any], captured[0])


def assembled_tool(
    knowledge: SessionKnowledge | None, **config_overrides: Any
) -> tuple[pipeline.AssembledCall, FunctionSchema]:
    """Assemble a call and hand back the ONE tool its context advertises."""
    call = pipeline.assemble_call(
        config=make_config(**config_overrides),
        legs=pipeline.VendorLegs(
            stt=_PassThrough("s"), llm=_PassThrough("l"), tts=_PassThrough("t")
        ),
        transport=FakeTransport(),
        sink=RecordingSink(),
        knowledge=knowledge,
    )
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    (schema,) = tools.standard_tools
    return call, schema


def test_the_tool_is_advertised_and_its_description_tells_the_model_to_search_in_english() -> None:
    """The description IS the design (§9.2), so the sentence that carries it is asserted.

    0.042 against Telugu script and 0.625 against English is a measurement
    (`docs/evidence/telugu-embedding-quality.md` §4), and the only thing standing between
    this product and the first number is that this string says ENGLISH. A refactor that
    tidies the description into something shorter fails here.
    """
    config = make_config()
    knowledge, _digest = build_knowledge(config)
    _call, schema = assembled_tool(knowledge)

    assert schema.name == pipeline.KNOWLEDGE_TOOL_NAME
    assert schema.required == [pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM]
    assert schema.properties[pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM]["type"] == "string"
    assert "ENGLISH" in schema.description
    # Every outcome word the payload can carry is explained to the model, or it has no way
    # to tell "we published nothing" from "I could not look".
    for outcome in ("found", "ambiguous", "not_found", "temporarily_unavailable"):
        assert outcome in schema.description
    assert pipeline.KNOWLEDGE_OUTCOME_NO_PACK in schema.description


def test_a_real_vendor_llm_service_registers_the_schemas_handler() -> None:
    """The registration path itself, through the real service rather than by assertion.

    `_sync_registered_tool_handlers` is what the base service runs on every
    `LLMContextFrame` ("the single path for keeping handlers in step with the advertised
    tools", `pipecat/services/llm_service.py:1318-1330`, read 14 Sep 2026). Driving it with
    OUR context is what proves a `FunctionSchema` carrying its own handler needs no
    `register_function` call — the claim `build_knowledge_tool`'s docstring makes.
    """
    config = make_config()
    knowledge, _digest = build_knowledge(config)
    call, _schema = assembled_tool(knowledge)
    llm = pipeline.build_vendor_legs(config, CREDENTIALS).llm
    assert isinstance(llm, AzureLLMService)

    assert not llm.has_function(pipeline.KNOWLEDGE_TOOL_NAME)
    llm._sync_registered_tool_handlers(call.context.tools)
    assert llm.has_function(pipeline.KNOWLEDGE_TOOL_NAME)


async def test_a_found_answer_reaches_the_model_as_published_words_with_its_revision() -> None:
    config = make_config()
    knowledge, _digest = build_knowledge(config)
    _call, schema = assembled_tool(knowledge)

    payload = await invoke_tool(schema, "what are the clinic timings")

    assert payload["outcome"] == "found"
    assert "only these passages" in payload["guidance"]
    top = payload["passages"][0]
    # The client's OWN published text, not the English gloss the ranker matched on.
    assert top["text"].startswith("క్లినిక్")
    assert "9 am to 8 pm" not in top["text"]
    # Provenance travels, so a dispute can be answered with the exact revision quoted.
    assert top["source_id"] == str(HOURS_DOC)
    assert top["document_version"] == 3


async def test_the_four_silences_are_four_different_words_to_the_model() -> None:
    """The whole reason the payload carries an outcome at all.

    An empty passage list would collapse these into one, and a model handed nothing
    reliably tells the caller the business does not do the thing — which is a claim about
    a client's business made on the strength of a failed object fetch.
    """
    config = make_config()
    knowledge, digest = build_knowledge(config)

    # nothing published on the subject.
    _call, schema = assembled_tool(knowledge)
    not_found = await invoke_tool(schema, "do you sell tractor tyres")
    assert not_found["outcome"] == "not_found"
    assert not_found["passages"] == []

    # two documents, same fee, one category word: the caller named a class, not a thing.
    ambiguous = await invoke_tool(schema, "what is the fee")
    assert ambiguous["outcome"] == "ambiguous"
    assert {passage["source_id"] for passage in ambiguous["passages"]} == {
        str(CONSULTATION_DOC),
        str(SCAN_DOC),
    }
    assert "tells them apart" in ambiguous["guidance"]

    # the pack did not load. The agent HAS a knowledge base; it could not be consulted.
    outage = SessionKnowledge(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        unavailable_reason="fetch_failed",
        requested_digest=digest,
    )
    _outage_call, outage_schema = assembled_tool(outage, knowledge_pack_sha256=digest)
    unavailable = await invoke_tool(outage_schema, "what are the clinic timings")
    assert unavailable["outcome"] == "temporarily_unavailable"
    assert "did not look" in unavailable["guidance"]

    # no pack at all — an ordinary agent, not an error.
    _bare_call, bare_schema = assembled_tool(None)
    absent = await invoke_tool(bare_schema, "what are the clinic timings")
    assert absent["outcome"] == pipeline.KNOWLEDGE_OUTCOME_NO_PACK

    assert (
        len(
            {
                not_found["outcome"],
                ambiguous["outcome"],
                unavailable["outcome"],
                absent["outcome"],
            }
        )
        == 4
    )


async def test_an_agent_with_no_knowledge_base_still_assembles_a_working_pipeline() -> None:
    """`knowledge=None` is a complete state, and the tool exists anyway.

    A tool that appeared only when a pack loaded would let the model answer from its own
    priors with no sign anything was missing — an invented fact told to a caller in a
    client's name.
    """
    sink = RecordingSink()
    transport = FakeTransport()
    llm = FakeLLM("నమస్కారం")
    call = pipeline.assemble_call(
        config=make_config(),
        legs=pipeline.VendorLegs(stt=_PassThrough("fake-stt"), llm=llm, tts=_PassThrough("f-tts")),
        transport=transport,
        sink=sink,
    )
    assert call.knowledge is None
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    assert [schema.name for schema in tools.standard_tools] == [pipeline.KNOWLEDGE_TOOL_NAME]

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

    assert [turn.text for turn in sink.turns if turn.speaker == "agent"] == ["నమస్కారం"]
    assert [event.status for event in sink.events] == ["in_progress", "completed"]


async def test_a_configured_pack_nobody_loaded_is_an_outage_and_says_so_to_an_operator() -> None:
    """The wiring defect has its own log line, and does NOT become `no_knowledge_base`.

    From the caller's seat an unloaded pack and an unreachable one are the same silence, so
    the model is told the same thing. An operator is told the difference, once, at assembly
    — the digest is an id and therefore loggable (hard rule 6).
    """
    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink_log, level="DEBUG")
    try:
        _call, schema = assembled_tool(None, knowledge_pack_sha256="a" * 64)
    finally:
        logger.remove(handler)

    payload = await invoke_tool(schema, "what are the clinic timings")
    assert payload["outcome"] == "temporarily_unavailable"

    blob = "\n".join(captured)
    assert "knowledge pack configured but not loaded" in blob
    assert "a" * 64 in blob


async def test_the_tool_path_logs_no_question_and_no_passage() -> None:
    """Hard rule 6 at the seam this change adds.

    `knowledge._log_answer` is already proven not to leak in its own suite; what is new
    here is a tool handler standing between the model and that call, and a tool handler is
    exactly where somebody adds "just log what was asked" next.
    """
    config = make_config()
    knowledge, _digest = build_knowledge(config)
    _call, schema = assembled_tool(knowledge)
    captured: list[str] = []

    def sink_log(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink_log, level="DEBUG")
    try:
        payload = await invoke_tool(schema, "what is the consultation fee")
    finally:
        logger.remove(handler)

    assert payload["outcome"] == "found"
    blob = "\n".join(captured)
    assert blob, "the lookup logged nothing at all, so this test proves nothing"
    for forbidden in (
        "what is the consultation fee",  # the caller's question, rewritten or not
        "Consultation fee is five hundred rupees.",  # the passage
        "The clinic is open from 9 am to 8 pm",  # a gloss
    ):
        assert forbidden not in blob
    assert "found" in blob and "elapsed_ms" in blob


async def test_a_blank_or_missing_question_is_not_found_rather_than_a_crashed_tool() -> None:
    """A handler that raised would reach the model as "the function failed and returned no
    result" (`pipecat/services/llm_service.py:301-303`) — strictly less useful to a caller
    than the honest word, and on a phone call the difference is what the agent says next."""
    config = make_config()
    knowledge, _digest = build_knowledge(config)
    _call, schema = assembled_tool(knowledge)
    handler = schema.handler
    assert handler is not None

    captured: list[Any] = []

    async def result_callback(result: Any, *, properties: Any = None) -> None:
        captured.append(result)

    for arguments in ({}, {pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM: None}):
        await handler(
            FunctionCallParams(
                function_name=schema.name,
                tool_call_id="tool-call-1",
                arguments=arguments,
                llm=cast(Any, None),
                pipeline_worker=cast(Any, None),
                context=cast(Any, None),
                result_callback=cast(Any, result_callback),
            )
        )
    assert [result["outcome"] for result in captured] == ["not_found", "not_found"]


async def test_the_digest_on_the_config_is_the_object_key_the_fetcher_is_asked_for() -> None:
    """The seam end to end: config digest -> `pack_object_key` -> pack -> the tool's answer.

    This is the one test here that goes through the real `load_session_knowledge`, because
    the thing being checked is the CONTRACT between `SessionConfig.knowledge_pack_sha256`
    and the object store — that the field an entrypoint reads is the field that decides
    which object is fetched, and not a second spelling of it.
    """
    entries = knowledge_entries()
    tenant_id, agent_id = uuid4(), uuid4()
    digest = KnowledgePack.digest(tenant_id, agent_id, entries)
    pack = KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=digest,
        built_at=datetime(2026, 9, 14, 6, 0, tzinfo=UTC),
        entries=entries,
    )
    asked: list[str] = []
    objects = {pack_object_key(tenant_id, agent_id, digest): pack.model_dump_json().encode()}

    class Fetcher:
        async def fetch(self, object_key: str) -> bytes | None:
            asked.append(object_key)
            return objects.get(object_key)

    config = make_config(tenant_id=tenant_id, agent_id=agent_id, knowledge_pack_sha256=digest)
    knowledge = await load_session_knowledge(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        content_sha256=cast(str, config.knowledge_pack_sha256),
        fetcher=Fetcher(),
        cache=PackCache(),
    )
    assert asked == [pack_object_key(tenant_id, agent_id, digest)]

    call = pipeline.assemble_call(
        config=config,
        legs=pipeline.VendorLegs(
            stt=_PassThrough("s"), llm=_PassThrough("l"), tts=_PassThrough("t")
        ),
        transport=FakeTransport(),
        sink=RecordingSink(),
        knowledge=knowledge,
    )
    assert call.knowledge is knowledge
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    (schema,) = tools.standard_tools
    payload = await invoke_tool(schema, "what are the clinic timings")
    assert payload["outcome"] == "found"
