"""`voice_worker/speaking.py`: the pipeline's frames to OUR speaking state, off the audio path.

What is proved here:

1. **The mapping** — the four pinned Pipecat frames, downstream only, become a side and a
   boolean; everything else is ignored, and a frame repeated on every hop is not a change.
2. **The debounce** — a flicker shorter than `DEBOUNCE_S` sends nothing; a state that holds
   is sent once; overlap is the caller's.
3. **The bounds** — the queue drops the oldest; a non-silent state is re-sent as a heartbeat.
4. **Failure isolation** — every failure of the far end is dropped, repeated failure turns
   the tracker off, nothing raises into the observer, and a speaking API that hangs or
   raises does not stop `run_call` from finishing and settling.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
from calevate_shared.worker_api import SpeakingStateIn, SpeakingStateOut
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    TextFrame,
    UserStartedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from tests.voice_worker_pipeline_test import CREDENTIALS, FakeTransport
from tests.voice_worker_runtime_test import _live_call
from tests.voice_worker_session_test import _agent_config
from tests.worker_api_harness import declare_pipecat_engine
from voice_worker import runtime, speaking
from voice_worker.api_client import WorkerApiClient, WorkerApiError
from voice_worker.speaking import SpeakingObserver, SpeakingTracker

#: Short enough to keep the suite quick, long enough to separate "held" from "flickered".
DEBOUNCE = 0.05


class _Api:
    """Records what reached the far end; optionally fails or hangs."""

    def __init__(self, *, fail: BaseException | None = None, hang: bool = False) -> None:
        self.sent: list[SpeakingStateIn] = []
        self.fail = fail
        self.hang = hang
        self.calls = 0

    async def post_speaking(self, engine_call_id: str, state: SpeakingStateIn) -> SpeakingStateOut:
        self.calls += 1
        if self.hang:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        self.sent.append(state)
        return SpeakingStateOut(accepted=True)


@pytest.fixture
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from declare_pipecat_engine(monkeypatch)


def _tracker(api: _Api, **kwargs: Any) -> SpeakingTracker:
    return SpeakingTracker(api, engine_call_id="pipecat:t:c", debounce_s=DEBOUNCE, **kwargs)


def _push(frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> FramePushed:
    processor = FrameProcessor()
    return FramePushed(
        source=processor, destination=processor, frame=frame, direction=direction, timestamp=0
    )


async def _settle(times: float = 3) -> None:
    await asyncio.sleep(DEBOUNCE * times)


# --- 1. mapping ----------------------------------------------------------------------


async def test_the_four_frames_map_to_sides_and_nothing_else_does() -> None:
    api = _Api()
    tracker = _tracker(api)
    observer = SpeakingObserver(tracker)
    tracker.start()
    try:
        await observer.on_push_frame(_push(BotStartedSpeakingFrame()))
        # The same frame on later hops, and upstream copies, change nothing.
        await observer.on_push_frame(_push(BotStartedSpeakingFrame()))
        await observer.on_push_frame(_push(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM))
        await observer.on_push_frame(_push(TextFrame(text="never read")))
        # The TURN frame is not the VAD frame and is deliberately not mapped.
        await observer.on_push_frame(_push(UserStartedSpeakingFrame()))
        await _settle()
        await observer.on_push_frame(_push(VADUserStartedSpeakingFrame()))
        await _settle()
        await observer.on_push_frame(_push(VADUserStoppedSpeakingFrame()))
        await observer.on_push_frame(_push(BotStoppedSpeakingFrame()))
        await _settle()
    finally:
        await tracker.aclose()
    assert [s.speaker for s in api.sent] == ["agent", "caller", None]
    assert [s.seq for s in api.sent] == [1, 2, 3]
    # Only a side, a sequence and a time cross the wire.
    assert set(api.sent[0].model_dump()) == {"speaker", "seq", "at"}


# --- 2. debounce ----------------------------------------------------------------------


async def test_a_flicker_sends_nothing_and_a_held_state_is_sent_once() -> None:
    api = _Api()
    tracker = _tracker(api)
    tracker.start()
    try:
        tracker.observe("caller", True)
        tracker.observe("caller", False)
        tracker.observe("caller", True)
        tracker.observe("caller", False)
        await _settle()
        assert api.sent == [], "a VAD flicker reached the console"
        tracker.observe("agent", True)
        await _settle()
        tracker.observe("agent", True)
        await _settle()
    finally:
        await tracker.aclose()
    assert [s.speaker for s in api.sent] == ["agent"]


async def test_overlap_is_the_callers_and_the_state_returns_to_the_agent() -> None:
    api = _Api()
    tracker = _tracker(api)
    tracker.start()
    try:
        tracker.observe("agent", True)
        await _settle()
        tracker.observe("caller", True)  # barge-in
        await _settle()
        tracker.observe("caller", False)
        await _settle()
    finally:
        await tracker.aclose()
    assert [s.speaker for s in api.sent] == ["agent", "caller", "agent"]


# --- 3. bounds ------------------------------------------------------------------------


async def test_the_queue_keeps_the_newest_and_drops_the_oldest() -> None:
    api = _Api()
    tracker = _tracker(api, queue_max=2)
    # Not started: nothing drains the queue, so it fills.
    for side, speaking_now in [
        ("agent", True),
        ("agent", False),
        ("caller", True),
        ("caller", False),
    ]:
        tracker.observe(side, speaking_now)  # type: ignore[arg-type]
        await _settle()
    tracker.start()
    await _settle()
    await tracker.aclose()
    assert [s.speaker for s in api.sent] == ["caller", None]
    assert tracker.dropped == 2


async def test_a_long_sentence_is_kept_alive_by_a_heartbeat() -> None:
    api = _Api()
    tracker = _tracker(api, heartbeat_s=DEBOUNCE)
    tracker.start()
    try:
        tracker.observe("agent", True)
        await _settle(6)
    finally:
        await tracker.aclose()
    assert len(api.sent) >= 2
    assert {s.speaker for s in api.sent} == {"agent"}
    assert len({s.at for s in api.sent}) == 1, "a heartbeat moved when the sentence began"
    assert [s.seq for s in api.sent] == sorted({s.seq for s in api.sent})


async def test_silence_is_not_heartbeated() -> None:
    api = _Api()
    tracker = _tracker(api, heartbeat_s=DEBOUNCE)
    tracker.start()
    try:
        tracker.observe("agent", True)
        tracker.observe("agent", False)
        await _settle(6)
    finally:
        await tracker.aclose()
    assert api.sent == []


async def test_a_call_that_runs_out_of_sequence_numbers_stops_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(speaking, "MAX_SPEAKING_SEQ", 1)
    api = _Api()
    tracker = _tracker(api)
    tracker.start()
    try:
        tracker.observe("agent", True)
        await _settle()
        tracker.observe("caller", True)
        await _settle()
    finally:
        await tracker.aclose()
    assert [s.speaker for s in api.sent] == ["agent"]
    assert tracker.disabled


# --- 4. failure isolation --------------------------------------------------------------


async def test_repeated_transient_failures_turn_the_tracker_off() -> None:
    api = _Api(fail=WorkerApiError("HTTP 503", retryable=True))
    tracker = _tracker(api)
    tracker.start()
    try:
        for n in range(speaking.MAX_CONSECUTIVE_FAILURES + 2):
            tracker.observe("caller", n % 2 == 0)
            await _settle()
    finally:
        await tracker.aclose()
    assert api.calls == speaking.MAX_CONSECUTIVE_FAILURES
    assert tracker.disabled
    # Once off, observing is a no-op and cannot fail.
    tracker.observe("agent", True)


async def test_a_refusal_turns_the_tracker_off_at_once() -> None:
    api = _Api(fail=WorkerApiError("HTTP 401", retryable=False))
    tracker = _tracker(api)
    tracker.start()
    try:
        tracker.observe("caller", True)
        await _settle()
        tracker.observe("caller", False)
        await _settle()
    finally:
        await tracker.aclose()
    assert api.calls == 1
    assert tracker.disabled


async def test_an_unexpected_error_is_dropped_and_a_success_resets_the_count() -> None:
    api = _Api(fail=RuntimeError("boom"))
    tracker = _tracker(api)
    tracker.start()
    try:
        tracker.observe("caller", True)
        await _settle()
        api.fail = None
        tracker.observe("caller", False)
        await _settle()
    finally:
        await tracker.aclose()
    assert not tracker.disabled
    assert tracker.dropped == 1
    assert tracker.sent == 1


async def test_the_observer_never_raises_into_the_vendors_proxy_task() -> None:
    class _Exploding(SpeakingTracker):
        def observe(self, side: Any, speaking_now: bool) -> None:
            raise RuntimeError("bug")

    observer = SpeakingObserver(_Exploding(_Api(), engine_call_id="x"))
    await observer.on_push_frame(_push(BotStartedSpeakingFrame()))


async def test_aclose_is_safe_before_start_and_twice() -> None:
    tracker = _tracker(_Api(hang=True))
    tracker.observe("agent", True)
    await tracker.aclose()
    tracker.start()
    tracker.observe("caller", True)
    await _settle()
    await tracker.aclose()
    await tracker.aclose()


async def test_the_real_client_sends_through_the_api(
    worker_token: None, _pipecat_deployment: None
) -> None:
    """The tracker against the real client and the real app: the state reaches Redis."""
    from apps.api.core.redis import get_redis
    from apps.api.crm.live_speaking import read_speaking, speaking_key
    from tests.worker_api_harness import call_ref, worker_client

    tenant_id = uuid.uuid4()
    _, ref = call_ref(tenant_id)
    async with worker_client() as api:
        tracker = SpeakingTracker(api, engine_call_id=ref, debounce_s=DEBOUNCE)
        tracker.start()
        try:
            tracker.observe("caller", True)
            await _settle(10)
        finally:
            await tracker.aclose()
    try:
        assert (await read_speaking(tenant_id, ref))[0] == "caller"
    finally:
        await get_redis().delete(speaking_key(tenant_id, ref))


@pytest.mark.rls
@pytest.mark.parametrize("failure", ["hang", "raise"])
async def test_a_broken_speaking_api_does_not_touch_the_call(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    worker_token: None,
    _pipecat_deployment: None,
) -> None:
    """The whole of `run_call`, with a speaking endpoint that never answers or always fails.

    The pipeline reports speech while it runs; the call still finishes and settles exactly as
    it would with no indicator at all, and the sender task does not outlive it.
    """
    tenant_id, agent_id, call_id, real, _sink = await _live_call()
    await PipecatEngine().create_agent(_agent_config(tenant_id, agent_id))

    class _BrokenSpeaking(WorkerApiClient):
        def __init__(self) -> None:
            super().__init__(client=real._client, base_url=real._base_url, token=real._token)
            self.attempts = 0

        async def post_speaking(self, *_args: Any, **_kwargs: Any) -> Any:
            self.attempts += 1
            if failure == "hang":
                await asyncio.Event().wait()
            raise WorkerApiError("HTTP 503", retryable=True)

    api = _BrokenSpeaking()
    trackers: list[SpeakingTracker] = []

    class _Capturing(SpeakingTracker):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            trackers.append(self)

    class _Runner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def add_workers(self, *_workers: Any) -> None:
            return None

        async def run(self) -> None:
            # Speech, as the observer would report it, while the "pipeline" runs.
            for n in range(4):
                trackers[0].observe("agent" if n % 2 else "caller", True)
                await asyncio.sleep(speaking.DEBOUNCE_S * 1.5)
                trackers[0].observe("agent" if n % 2 else "caller", False)

    class _NoPacks:
        async def fetch(self, _key: str) -> bytes | None:
            return None

    monkeypatch.setattr(runtime, "SpeakingTracker", _Capturing)
    monkeypatch.setattr(runtime, "WorkerRunner", _Runner)
    worker_runtime = runtime.WorkerRuntime(api, fetcher=_NoPacks())
    try:
        outcome = await asyncio.wait_for(
            worker_runtime.run_call(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(agent_id)),
                credentials_for=lambda _provider: CREDENTIALS,
                greeting="skip",
                transport=FakeTransport(),
            ),
            timeout=20,
        )
    finally:
        await real.aclose()

    assert api.attempts >= 1, "the indicator was never exercised"
    assert outcome.settlement.refusals == (
        ("carrier", "meter_carrier_cdr_missing"),
        ("runtime", "meter_runtime_active_minute_unknown"),
    )
    assert trackers[0]._task is None, "the sender task outlived the call"


def test_the_payload_has_no_room_for_content() -> None:
    """Hard rule 6 by construction: the wire model refuses any field it does not declare."""
    with pytest.raises(ValueError):
        SpeakingStateIn.model_validate(
            {"speaker": "caller", "seq": 1, "at": datetime.now(UTC).isoformat(), "text": "hi"}
        )
