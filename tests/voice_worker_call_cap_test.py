"""`max_call_duration_s` on the engine we run ourselves: where it comes from, what it does.

**THE DEFECT.** The console writes a call cap (`agents/publishing_routes.py:403`),
`AgentConfig` carries it, and the rented engine pushes it as `call_terminate`
(`engine/bolna.py:4106`). It appeared NOWHERE in `engine/pipecat.py`, nowhere in the worker
session payload and nowhere in `apps/voice-worker` — and `assemble_call` sets
`idle_timeout_secs=None` deliberately, because a phone call has its own end. So on
`owned_runtime` a call that never ended never ended, burning a client's credits against a
cap they had set and been shown. A money defect (hard rule 7) before a trust one.

**WHAT IS ASSERTED, AND WHY IT IS THE FRAME AND NOT A METHOD CALL.** The vendor's own rule
is that a running pipeline is changed by PUSHING A FRAME, never by calling a method on an
object inside it (`AGENTS.md:153`) — reaching in jumps the queue ahead of frames already in
flight. And the frame is `EndWorkerFrame`, which drains (`pipecat/frames/frames.py:
1800-1810`: "closed nicely (flushing all the queued frames)"), not a cancel, which would cut
the caller off mid-word. This repo has paid for that distinction once already:
`handle_sigterm=True` was shipped believing it drained, and it calls `cancel()`.

So the stub below records BOTH: the frames pushed, and every method a cap might have been
tempted to call instead. A cap that cancelled would pass an assertion about the call ending
and fail the one that matters to the person on the phone.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from apps.api.agents.models import CALL_CAP_DEFAULT_S
from calevate_shared.engine import AgentConfig, ModelConfig, azure_openai_base_url
from calevate_shared.worker_api import DEFAULT_CALL_CAP_S
from pipecat.frames.frames import EndWorkerFrame
from tests.voice_worker_pipeline_test import (
    FakeTransport,
    RecordingSink,
    _PassThrough,
    make_config,
)
from voice_worker import pipeline
from voice_worker.pipeline import CallDurationCap

#: Long enough that nothing in this file reaches it by accident, short enough to be a real
#: number rather than a sentinel.
NEVER_S = 3600


class RecordingWorker:
    """A `PipelineWorker` as the cap uses it: one push, and the methods it must NOT call."""

    def __init__(self) -> None:
        self.pushed: list[Any] = []
        self.handlers: dict[str, list[Any]] = {}
        self.cancelled = False
        self.stopped = False

    async def queue_frames(self, frames: Any) -> None:
        self.pushed.extend(frames)

    async def cancel(self) -> None:  # pragma: no cover - asserted never to run
        self.cancelled = True

    async def stop_when_done(self) -> None:  # pragma: no cover - asserted never to run
        self.stopped = True

    def add_event_handler(self, name: str, handler: Any) -> None:
        self.handlers.setdefault(name, []).append(handler)


def cap_for(worker: RecordingWorker, limit_s: int) -> CallDurationCap:
    return CallDurationCap(worker=worker, limit_s=limit_s, call_id="call-1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_cap_ends_the_call_by_pushing_a_frame() -> None:
    """A PUSH, and the frame is the draining one.

    `limit_s=0` rather than a patched clock: the cap's only timing dependency is one
    `asyncio.sleep`, and zero exercises the same code path a real cap reaches without
    making the test wait for it or the assertion depend on a monkeypatch.
    """
    worker = RecordingWorker()
    cap = cap_for(worker, 0)
    cap.arm()
    await asyncio.sleep(0.05)

    assert len(worker.pushed) == 1
    frame = worker.pushed[0]
    assert isinstance(frame, EndWorkerFrame)
    # THE REASON IS OURS AND SAYS WHY THE CALL ENDED, so a transcript that stops mid-sentence
    # has an explanation an operator can find.
    assert "cap" in str(frame.reason)
    # AND NOTHING WAS CALLED ON THE PIPELINE. A cancel would cut the caller off mid-word;
    # reaching for `stop_when_done()` would jump the queue ahead of frames in flight.
    assert not worker.cancelled
    assert not worker.stopped


@pytest.mark.asyncio
async def test_a_call_under_its_cap_is_untouched() -> None:
    """The ordinary call. Nothing is pushed and the conversation ends on its own."""
    worker = RecordingWorker()
    cap = cap_for(worker, NEVER_S)
    cap.arm()
    await asyncio.sleep(0.05)
    assert worker.pushed == []
    assert cap.armed
    await cap.disarm()
    assert worker.pushed == []
    assert not cap.armed


@pytest.mark.asyncio
async def test_disarming_stops_the_clock_so_no_task_outlives_the_call() -> None:
    """Pipecat Cloud reuses a container across sessions (§8.2), so a timer that outlived its
    call would end somebody else's."""
    worker = RecordingWorker()
    cap = cap_for(worker, 0)
    cap.arm()
    await cap.disarm()
    await asyncio.sleep(0.05)
    assert worker.pushed == []
    # Disarming twice, and disarming something never armed, are both no-ops: the pipeline's
    # finish handler runs on every exit including the ones that never started.
    await cap.disarm()
    assert not cap.armed


@pytest.mark.asyncio
async def test_arming_twice_starts_one_clock() -> None:
    """A re-`StartFrame` must not start a second timer — `call_started`'s own rule."""
    worker = RecordingWorker()
    cap = cap_for(worker, NEVER_S)
    cap.arm()
    cap.arm()
    await asyncio.sleep(0)
    assert cap.armed
    await cap.disarm()
    assert worker.pushed == []


@pytest.mark.asyncio
async def test_the_cap_is_armed_by_the_pipelines_own_start_and_disarmed_by_its_finish() -> None:
    """THE CLOCK STARTS WHEN THE PIPELINE DOES, NOT WHEN THE CALL WAS ASSEMBLED.

    `assemble_call` runs while the phone is still ringing — the knowledge pack fetch and the
    caller-memory read happen on that wall clock — so a cap counted from construction would
    be shorter than the one the client set.
    """
    worker = RecordingWorker()
    cap = cap_for(worker, NEVER_S)
    cap.attach(worker)  # type: ignore[arg-type]

    assert not cap.armed
    for started in worker.handlers["on_pipeline_started"]:
        await started(worker, None)
    assert cap.armed
    for finished in worker.handlers["on_pipeline_finished"]:
        await finished(worker, None)
    assert not cap.armed


def test_the_cap_comes_from_the_agents_configuration_and_not_from_this_container() -> None:
    """An assembled call is held to the AGENT's number, whatever it is."""
    legs = pipeline.VendorLegs(
        stt=_PassThrough("stt"), llm=_PassThrough("llm"), tts=_PassThrough("tts")
    )
    call = pipeline.assemble_call(
        config=make_config(max_call_duration_s=97),
        legs=legs,
        transport=FakeTransport(),
        sink=RecordingSink(),
    )
    assert call.cap is not None
    assert call.cap.limit_s == 97


def test_the_workers_default_cap_is_the_platforms_and_is_not_a_second_spelling_of_it() -> None:
    """⚠ **THE DRIFT GUARD THIS WHOLE ARRANGEMENT EXISTS FOR.**

    `packages/shared` cannot import `apps/`, so `DEFAULT_CALL_CAP_S` is read off
    `AgentConfig.max_call_duration_s` rather than retyped — and this asserts that the number
    really is the console's `CALL_CAP_DEFAULT_S`. A platform constant with two spellings is
    hard rule 4's defect, and the version of it that costs money is a console showing a
    client one cap while the container enforces another.
    """
    assert DEFAULT_CALL_CAP_S == CALL_CAP_DEFAULT_S
    assert pipeline.SessionConfig.__dataclass_fields__["max_call_duration_s"].default == (
        CALL_CAP_DEFAULT_S
    )


def capped_agent_config(tenant_id: uuid.UUID, agent_id: uuid.UUID, cap: int) -> AgentConfig:
    """`voice_worker_session_test._agent_config` with the one field under test changed."""
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name="Sri Lakshmi Tailors receptionist",
        direction="inbound",
        language_primary="te-IN",
        system_prompt="You are the receptionist for Sri Lakshmi Tailors.",
        opening_line="Idi AI assistant. Ee call record avutundi.",
        max_call_duration_s=cap,
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v4",
            llm_provider="azure_openai",
            llm_model="calevate-gpt-4o-mini",
            llm_base_url=azure_openai_base_url("calevate-eastus2"),
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="anushka",
        ),
    )


@pytest.mark.rls
@pytest.mark.asyncio
async def test_the_cap_travels_the_whole_way_from_the_published_row_to_the_session(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE HOP, END TO END: `agent_config_versions.resolved_config` -> `WorkerSessionOut` ->
    `SessionConfig`. Until this landed the cap stopped at the row.

    The real client against the real app, and then the real `load_session_config` over it —
    so what is proved is the CONTRACT rather than either half's opinion of it.
    """
    from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
    from tests.kb_workflow_test import _tenant_with_published_agent
    from tests.owned_runtime_tools_test import tool_client
    from tests.worker_api_harness import declare_pipecat_engine
    from voice_worker.config import load_session_config

    engine = declare_pipecat_engine(monkeypatch)
    next(engine)
    try:
        tenant_id, agent_id = await _tenant_with_published_agent()
        tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
        await PipecatEngine().create_agent(capped_agent_config(tenant_id, agent_id, 1234))
        ref = engine_agent_ref_for(str(tenant_id), str(agent_id))

        async with tool_client() as api:
            config = await load_session_config(
                api,
                call_id="call-1",
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                engine_agent_ref=ref,
            )
        assert config.max_call_duration_s == 1234
    finally:
        next(engine, None)
