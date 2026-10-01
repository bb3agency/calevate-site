"""Who is speaking on this call, sent to the console's live indicator (D-656).

**WHAT CROSSES THE BOUNDARY.** `SpeakingObserver` reads four Pipecat frames and hands
`SpeakingTracker` a side and a boolean; what leaves this container is
`calevate_shared.worker_api.SpeakingStateIn` — `speaker` (`"caller"`, `"agent"` or `None`),
a sequence number and a timestamp. No frame, no audio, no text, no number (hard rules 2
and 6).

**WHICH FRAMES, read in the pinned `pipecat-ai==1.10.0` tree:**

- Caller: `VADUserStartedSpeakingFrame` / `VADUserStoppedSpeakingFrame`
  (`pipecat/frames/frames.py:1281,1296`). The user aggregator broadcasts them from its VAD
  controller (`processors/aggregators/llm_response_universal.py:1297-1307`), which is where
  `pipeline.build_user_aggregator_params` puts Silero. They are VAD-level, so they track
  audible speech; `UserStartedSpeakingFrame` is the TURN, which only ends when smart-turn
  decides, and would show the caller speaking through their own pauses.
- Agent: `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` (`frames.py:1347,1358`),
  pushed by the output transport when audio actually starts and stops playing
  (`transports/base_output.py:700-766`) — what the caller hears, not what was generated.

The vendor's own `UserBotLatencyObserver` keys on the same downstream frames
(`observers/user_bot_latency_observer.py:628-717`).

**AN OBSERVER, NOT A PROCESSOR, AND THAT IS WHAT KEEPS IT OFF THE AUDIO PATH.**
`PipelineWorker` hands each observer its own queue and task (`pipeline/worker_observer.py:
184-217`), so `on_push_frame` runs beside the pipeline rather than inside it. The
`NormalizedEventBoundary` docstring rejects an observer for TURNS because a frame arrives once
per hop; here that is harmless — a repeated "agent started" is not a change of state.
Nothing in `on_push_frame` awaits I/O and nothing may raise out of it: the vendor's proxy
loop has no `try` (`worker_observer.py:203-217`), so an exception would end this observer's
task for the rest of the call.

**DEBOUNCED, COALESCED, BOUNDED, DROPPED.** A state is sent only after it has held for
`DEBOUNCE_S`, so a VAD flicker or the instant between "caller stopped" and "agent started"
sends nothing. Sends go through a queue of `QUEUE_MAX` from which the oldest is dropped
(the newest state is the only one worth delivering), posted by one sender task with a
one-second budget and no retry. After `MAX_CONSECUTIVE_FAILURES` failures — or any refusal
a retry could not change — the tracker stops sending for the rest of the call. Nothing the
pipeline does ever waits on any of it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Final, Protocol

from calevate_shared.worker_api import (
    MAX_SPEAKING_SEQ,
    SpeakingSide,
    SpeakingStateIn,
    SpeakingStateOut,
)
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection

from voice_worker.api_client import WorkerApiError

#: How long a state must hold before it is sent. Under Silero's own smoothing this mostly
#: absorbs the hand-over gap between the two sides; the console's budget is about a second.
DEBOUNCE_S: Final = 0.2

#: How often an unchanged non-silent state is re-sent, to outlive the server's TTL
#: (`apps/api/crm/live_speaking.SPEAKING_TTL_S`, 30 s) through a long sentence.
HEARTBEAT_S: Final = 10.0

#: How many unsent states may wait. The oldest is dropped first.
QUEUE_MAX: Final = 4

#: After this many failures in a row the tracker stops sending for this call.
MAX_CONSECUTIVE_FAILURES: Final = 5

#: frame class -> (side, speaking). The only Pipecat vocabulary in this module.
_FRAME_SIDES: Final[dict[type, tuple[SpeakingSide, bool]]] = {
    VADUserStartedSpeakingFrame: ("caller", True),
    VADUserStoppedSpeakingFrame: ("caller", False),
    BotStartedSpeakingFrame: ("agent", True),
    BotStoppedSpeakingFrame: ("agent", False),
}


class SpeakingApi(Protocol):
    """The one call the tracker makes. `WorkerApiClient` satisfies it."""

    async def post_speaking(
        self, engine_call_id: str, state: SpeakingStateIn
    ) -> SpeakingStateOut: ...


class SpeakingTracker:
    """One call's speaking state: the two sides, the debounce, the queue and the sender.

    `observe` is synchronous and never raises. `start` creates the sender task and
    `aclose` ends it; neither is on the pipeline's path.
    """

    def __init__(
        self,
        api: SpeakingApi,
        *,
        engine_call_id: str,
        debounce_s: float = DEBOUNCE_S,
        heartbeat_s: float = HEARTBEAT_S,
        queue_max: int = QUEUE_MAX,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._api = api
        self._ref = engine_call_id
        self._debounce_s = debounce_s
        self._heartbeat_s = heartbeat_s
        self._now = now
        self._queue: asyncio.Queue[SpeakingStateIn] = asyncio.Queue(maxsize=queue_max)
        self._caller = False
        self._agent = False
        self._pending: SpeakingSide | None = None
        self._pending_since: datetime | None = None
        self._timer: asyncio.TimerHandle | None = None
        #: The last state queued, as `(speaker, since)`. `None` until the first one.
        self._queued: tuple[SpeakingSide | None, datetime] | None = None
        self._seq = 0
        self._failures = 0
        self._disabled = False
        self._task: asyncio.Task[None] | None = None
        #: Counters for the end-of-call log line and the tests.
        self.sent = 0
        self.dropped = 0

    @property
    def disabled(self) -> bool:
        return self._disabled

    # -- the pipeline side: synchronous, cheap, cannot fail --------------------------

    def observe(self, side: SpeakingSide, speaking: bool) -> None:
        """Record that `side` started or stopped being audible."""
        if self._disabled:
            return
        if side == "caller":
            self._caller = speaking
        else:
            self._agent = speaking
        # The caller wins a tie: overlap is a barge-in, and the agent is being interrupted.
        derived: SpeakingSide | None = (
            "caller" if self._caller else "agent" if self._agent else None
        )
        if derived == self._pending and self._pending_since is not None:
            return
        self._pending = derived
        self._pending_since = self._now()
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(self._debounce_s, self._settle)

    def _settle(self) -> None:
        """The pending state held for the debounce window; queue it if it is new."""
        self._timer = None
        since = self._pending_since
        if since is None or self._disabled:
            return
        last = None if self._queued is None else self._queued[0]
        if last == self._pending:
            # Unchanged since the last state sent — or silence before anything was sent.
            return
        self._enqueue(self._pending, since)

    def _enqueue(self, speaker: SpeakingSide | None, since: datetime) -> None:
        if self._seq >= MAX_SPEAKING_SEQ:
            self._disable("sequence exhausted")
            return
        self._seq += 1
        state = SpeakingStateIn(speaker=speaker, seq=self._seq, at=since)
        self._queued = (speaker, since)
        if self._queue.full():
            # The newest state is the only one worth delivering.
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(state)

    # -- the sender: its own task, never awaited by the pipeline ----------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._send_loop(), name="speaking-state-sender")

    async def _send_loop(self) -> None:
        while not self._disabled:
            try:
                state = await asyncio.wait_for(self._queue.get(), timeout=self._heartbeat_s)
            except TimeoutError:
                if self._queued is not None and self._queued[0] is not None:
                    self._enqueue(*self._queued)
                continue
            await self._send(state)

    async def _send(self, state: SpeakingStateIn) -> None:
        try:
            await self._api.post_speaking(self._ref, state)
        except WorkerApiError as failure:
            self._failed(retryable=failure.retryable)
        except Exception:
            # Anything else is still this indicator's problem and never the call's.
            self._failed(retryable=True)
        else:
            self._failures = 0
            self.sent += 1

    def _failed(self, *, retryable: bool) -> None:
        self.dropped += 1
        self._failures += 1
        if not retryable:
            self._disable("refused")
        elif self._failures >= MAX_CONSECUTIVE_FAILURES:
            self._disable("unreachable")

    def _disable(self, reason: str) -> None:
        if self._disabled:
            return
        self._disabled = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.warning("live speaking state disabled for this call", reason=reason)

    async def aclose(self) -> None:
        """Stop the timer and the sender. Unsent states are dropped. Never raises."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task


class SpeakingObserver(BaseObserver):
    """Feeds `SpeakingTracker` from the pipeline's own frames. Never raises."""

    def __init__(self, tracker: SpeakingTracker) -> None:
        super().__init__()
        self._tracker = tracker

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction != FrameDirection.DOWNSTREAM:
            return
        mapped = _FRAME_SIDES.get(type(data.frame))
        if mapped is None:
            return
        try:
            self._tracker.observe(*mapped)
        except Exception as failure:
            logger.warning("live speaking observer failed", reason=type(failure).__name__)


__all__ = [
    "DEBOUNCE_S",
    "HEARTBEAT_S",
    "MAX_CONSECUTIVE_FAILURES",
    "QUEUE_MAX",
    "SpeakingApi",
    "SpeakingObserver",
    "SpeakingTracker",
]
