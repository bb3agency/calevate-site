"""Scenarios for the ways a live call stalls: a quiet caller, the duration cap, a failing vendor.

Read `tests/scenario_harness.py` first: the model is a stand-in, so these assert the SEAM —
that our own code says the right fixed sentence at the right moment and then ends the call
the way it should, through the shipped aggregators, worker and boundary. Each behaviour has
a negative control beside it, so an assertion that could not fail would show up as one.

The one thing the fake transport adds over the harness's is what the real output transport
does when the agent stops talking: it sends `BotStoppedSpeakingFrame` upstream
(`pipecat/transports/base_output.py`), which is what arms the caller-silence timer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.utils.errors import ErrorCategory
from pipecat.workers.runner import WorkerRunner
from scenario_harness import (
    FakeTransport,
    InterruptibleTTS,
    PromptFollowingModel,
    RecordingSink,
    SpyProcessor,
    compose_agent_prompt,
    make_session_config,
    run_until_vendor_leg_fails,
)
from voice_worker import pipeline, recovery
from voice_worker.latency import CallLatencyRecorder
from voice_worker.recovery import IdleCallerPolicy, phrase_for

#: Short enough to keep the suite fast, long enough that a reply lands before it fires.
IDLE_S = 0.3

# --------------------------------------------------------------------------------------
# The rig.
# --------------------------------------------------------------------------------------


class SpeakingOutput(SpyProcessor):
    """The output transport's one behaviour these scenarios need: "the bot stopped talking"."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, TTSStoppedFrame | LLMFullResponseEndFrame
        ):
            await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
            await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)


class SpeakingTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self._out = SpeakingOutput("speaking-output")


Failure = Literal["transient", "permanent", "application"]


class FlakyModel(PromptFollowingModel):
    """The stand-in model, failing the next answers the way a vendor LLM service does.

    The greeting always succeeds. A failure is pushed the way `BaseOpenAILLMService`
    pushes one — response start, `push_error`, response end — so the turn ends with
    nothing said, which is exactly the silence the responder exists to fill.
    """

    def __init__(self, failures: Sequence[Failure] = ()) -> None:
        super().__init__()
        self.failures = list(failures)

    async def _answer(self, frame: LLMContextFrame) -> None:
        if self._greeting_request(frame.context) is None and self.failures:
            kind = self.failures.pop(0)
            await self.push_frame(LLMFullResponseStartFrame())
            if kind == "transient":
                await self.push_error(error_msg="completion timed out", exception=TimeoutError())
            elif kind == "permanent":
                await self.push_error(
                    error_msg="credential rejected", force_treat_as_permanent=True
                )
            else:
                await self.push_error(
                    error_msg="tool handler raised", category=ErrorCategory.APPLICATION
                )
            await self.push_frame(LLMFullResponseEndFrame())
            return
        await super()._answer(frame)


@dataclass
class Live:
    call: pipeline.AssembledCall
    sink: RecordingSink
    model: PromptFollowingModel
    running: asyncio.Task[None]

    @property
    def agent_said(self) -> list[str]:
        return [turn.text for turn in self.sink.turns if turn.speaker == "agent"]

    @property
    def final_status(self) -> str | None:
        terminal = [e.status for e in self.sink.events if e.ended_at is not None]
        return terminal[-1] if terminal else None

    async def say(self, text: str) -> None:
        worker = self.call.worker
        await worker.queue_frame(UserStartedSpeakingFrame())
        await worker.queue_frame(
            TranscriptionFrame(text, user_id="caller", timestamp="2026-10-06T00:00:00.000+00:00")
        )
        await worker.queue_frame(UserStoppedSpeakingFrame())

    async def utterances(self, at_least: int, timeout_s: float = 10.0) -> list[str]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if len(self.agent_said) >= at_least:
                return self.agent_said
            await asyncio.sleep(0.01)
        raise AssertionError(f"expected {at_least} agent turns, got {self.agent_said!r}")

    async def ended_by_itself(self, timeout_s: float = 10.0) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(self.running), timeout=timeout_s)
        except TimeoutError:
            raise AssertionError(
                f"the call was still up after {timeout_s}s; agent said {self.agent_said!r}"
            ) from None


@asynccontextmanager
async def live_call(
    *,
    model: PromptFollowingModel | None = None,
    idle: IdleCallerPolicy = IdleCallerPolicy(timeout_s=0),  # noqa: B008 - frozen value
    max_call_duration_s: int | None = None,
    language: str = "te-IN",
) -> AsyncIterator[Live]:
    config = make_session_config(system_prompt=compose_agent_prompt(), language=language)
    if max_call_duration_s is not None:
        config = pipeline.SessionConfig(
            **{
                **{name: getattr(config, name) for name in config.__dataclass_fields__},
                "max_call_duration_s": max_call_duration_s,
            }
        )
    model = model or PromptFollowingModel()
    sink = RecordingSink()
    call = pipeline.assemble_call(
        config=config,
        legs=pipeline.VendorLegs(stt=SpyProcessor("fake-stt"), llm=model, tts=InterruptibleTTS()),
        transport=SpeakingTransport(),
        sink=sink,
        idle=idle,
        wrap_up_lead_s=0.0,
    )
    started = asyncio.Event()

    @call.worker.event_handler("on_pipeline_started")
    async def _on_started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(call.worker)
    running = asyncio.create_task(runner.run())
    live = Live(call=call, sink=sink, model=model, running=running)
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        await call.start_conversation()
        await live.utterances(1)
        yield live
    finally:
        if not running.done():
            await call.worker.stop_when_done()
            try:
                await asyncio.wait_for(running, timeout=10)
            except TimeoutError:
                running.cancel()


# --------------------------------------------------------------------------------------
# The caller who goes quiet.
# --------------------------------------------------------------------------------------


async def test_a_silent_caller_is_reminded_once_and_then_the_call_ends_politely() -> None:
    async with live_call(idle=IdleCallerPolicy(timeout_s=IDLE_S)) as live:
        await live.ended_by_itself()

    assert live.agent_said[1:] == [
        phrase_for("idle_reprompt", "te-IN"),
        phrase_for("idle_goodbye", "te-IN"),
    ]
    # A caller who walked away is the ordinary end of a call, not a failure.
    assert live.final_status == "completed"
    assert live.call.idle is not None and live.call.idle.ended_call


async def test_a_caller_who_answers_the_reminder_is_not_hung_up_on() -> None:
    """Negative control: speaking resets the count, so the next silence earns a reminder."""
    async with live_call(idle=IdleCallerPolicy(timeout_s=IDLE_S)) as live:
        await live.utterances(2)
        await live.say("అవును, ఉన్నాను. అపాయింట్‌మెంట్ కావాలి.")
        said = await live.utterances(4)
        assert said[3] == phrase_for("idle_reprompt", "te-IN")
        assert phrase_for("idle_goodbye", "te-IN") not in said
        assert not live.running.done()


async def test_with_the_reminder_switched_off_a_silent_line_is_left_alone() -> None:
    """Negative control: the reminder comes from the policy, not from the harness timing."""
    async with live_call(idle=IdleCallerPolicy(timeout_s=0)) as live:
        await asyncio.sleep(IDLE_S * 3)
        assert len(live.agent_said) == 1
        assert not live.running.done()
        assert live.call.idle is None


async def test_the_reminder_is_spoken_in_the_agents_language() -> None:
    async with live_call(idle=IdleCallerPolicy(timeout_s=IDLE_S), language="hi-IN") as live:
        said = await live.utterances(2)
    assert said[1] == recovery.PHRASES["idle_reprompt"]["hi"]


def test_the_aggregator_carries_the_idle_timer_only_when_asked() -> None:
    assert pipeline.build_user_aggregator_params(idle_timeout_s=7.5).user_idle_timeout == 7.5
    assert pipeline.build_user_aggregator_params().user_idle_timeout == 0


# --------------------------------------------------------------------------------------
# The duration cap.
# --------------------------------------------------------------------------------------


async def test_a_call_that_reaches_its_cap_hears_a_goodbye_before_the_line_closes() -> None:
    async with live_call(max_call_duration_s=1) as live:
        await live.ended_by_itself(timeout_s=10)
    assert live.agent_said[-1] == phrase_for("cap_goodbye", "te-IN")
    assert live.final_status == "completed"


# --------------------------------------------------------------------------------------
# A failing vendor.
# --------------------------------------------------------------------------------------


@pytest.fixture
def no_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two failures a test stages a few milliseconds apart are two turns, not one burst."""
    monkeypatch.setattr(recovery, "FAULT_DEBOUNCE_S", 0.0)


@pytest.mark.usefixtures("no_debounce")
async def test_one_failed_turn_is_apologised_for_and_the_call_carries_on() -> None:
    async with live_call(model=FlakyModel(["transient"])) as live:
        await live.say("నాకు రేపు అపాయింట్‌మెంట్ కావాలి")
        said = await live.utterances(2)
        assert said[1] == phrase_for("fault_retry", "te-IN")
        await live.say("నాకు రేపు అపాయింట్‌మెంట్ కావాలి")
        said = await live.utterances(3)
        assert said[2] not in recovery.PHRASES["fault_retry"].values()
        assert live.call.faults is not None
        # The model answered, so the run of failures is over.
        assert live.call.faults.consecutive_failures == 0
        assert not live.running.done()
    assert live.final_status == "completed"


@pytest.mark.usefixtures("no_debounce")
async def test_a_second_failure_in_a_row_ends_the_call_with_an_apology() -> None:
    async with live_call(model=FlakyModel(["transient", "transient"])) as live:
        await live.say("హలో")
        await live.utterances(2)
        await live.say("హలో?")
        await live.ended_by_itself()
    assert live.agent_said[1:] == [
        phrase_for("fault_retry", "te-IN"),
        phrase_for("fault_goodbye", "te-IN"),
    ]
    assert live.final_status == "failed"


async def test_a_burst_of_errors_from_one_failure_counts_once() -> None:
    """With the real debounce, two errors in the same instant are one failed turn."""
    async with live_call(model=FlakyModel(["transient", "transient"])) as live:
        assert live.call.faults is not None
        llm = live.model
        await live.call.faults.on_leg_error("llm", llm, _error(llm, ErrorCategory.CONNECTIVITY))
        await live.call.faults.on_leg_error("llm", llm, _error(llm, ErrorCategory.CONNECTIVITY))
        assert live.call.faults.consecutive_failures == 1
        assert not live.call.faults.ended_call


async def test_a_permanently_failed_language_leg_apologises_before_the_line_closes() -> None:
    async with live_call(model=FlakyModel(["permanent"])) as live:
        await live.say("హలో")
        await live.ended_by_itself()
    assert live.agent_said[-1] == phrase_for("fault_goodbye", "te-IN")
    assert live.final_status == "failed"


async def test_a_dead_voice_is_not_asked_to_apologise() -> None:
    """Negative control: when the TTS is the dead leg nothing can be said, so nothing is
    queued for it, and the worker's END policy hangs up as before."""
    run = await run_until_vendor_leg_fails()
    assert phrase_for("fault_goodbye", "te-IN") not in [
        turn.text for turn in run.sink.turns if turn.speaker == "agent"
    ]
    assert run.sink.events[-1].status == "failed"


async def test_a_tool_handler_failure_is_not_treated_as_a_vendor_outage() -> None:
    """Negative control: `ErrorCategory.APPLICATION` is our code, and the model already hears
    "the function failed"; the caller hears no apology from us."""
    async with live_call(model=FlakyModel(["application"])) as live:
        await live.say("హలో")
        await asyncio.sleep(0.2)
        assert live.agent_said == live.agent_said[:1]
        assert live.call.faults is not None and live.call.faults.consecutive_failures == 0
        assert not live.running.done()


def _error(processor: Any, category: ErrorCategory) -> Any:
    from pipecat.frames.frames import ErrorFrame

    return ErrorFrame(error="x", processor=processor, category=category)


# --------------------------------------------------------------------------------------
# The LLM client's own limits.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["azure_openai", "openai", "google"])
def test_every_llm_leg_is_bounded_and_does_not_retry_behind_the_callers_back(
    provider: str,
) -> None:
    config = make_session_config(system_prompt="x")
    models = config.models.model_copy(
        update={
            "llm_provider": provider,
            "llm_model": "gemini-2.5-flash-lite" if provider == "google" else "gpt-4o-mini",
            "llm_base_url": config.models.llm_base_url if provider == "azure_openai" else None,
        }
    )
    bounded = pipeline.SessionConfig(
        **{
            **{name: getattr(config, name) for name in config.__dataclass_fields__},
            "models": models,
        }
    )
    llm = pipeline._build_llm(bounded, pipeline.VendorCredentials("s", "k"))
    client = cast(Any, llm)._client
    assert client.timeout == pipeline.LLM_REQUEST_TIMEOUT_S
    assert client.max_retries == pipeline.LLM_MAX_RETRIES == 0


def test_the_vendor_default_would_wait_minutes() -> None:
    """Negative control: what the bounds replace is the SDK's own 600 s and two retries."""
    client = cast(Any, OpenAILLMService(api_key="k"))._client
    assert client.max_retries == 2
    assert client.timeout.read == 600


# --------------------------------------------------------------------------------------
# Time to first audio, and the analyzers built off the event loop.
# --------------------------------------------------------------------------------------


async def test_the_greeting_latency_is_kept_for_the_call_timings_line() -> None:
    recorder = CallLatencyRecorder()
    assert recorder.greeting_first_audio_ms is None
    await recorder._on_first_bot_speech(cast(Any, None), 0.8125)
    assert recorder.greeting_first_audio_ms == 812.5


def test_analyzers_built_ahead_are_the_ones_the_call_uses() -> None:
    built = pipeline.build_turn_analyzers()
    params = pipeline.build_user_aggregator_params(analyzers=built)
    assert params.vad_analyzer is built.vad
    assert params.user_turn_strategies is not None
    stop = params.user_turn_strategies.stop
    assert stop is not None and cast(Any, stop[0])._turn_analyzer is built.smart_turn
