"""Per-turn pipeline timings for one call, reduced to `calevate_shared.engine.CallLatency`.

**WHAT A TURN IS.** One caller utterance answered: Pipecat's `UserBotLatencyObserver` opens a
cycle when the VAD hears the caller stop and closes it when the bot starts speaking, and
emits a `LatencyBreakdown` for it (`pipecat/observers/user_bot_latency_observer.py:972-1008`).
The greeting is the same event anchored on the client connecting instead; it is not a turn
and is not recorded here, because nobody was waiting on a reply to something they said. We
use the vendor's cycle rather than drawing our own: it already resets on an interruption
(`:696-698`) and on the caller resuming (`:648-656`), which are exactly the boundaries a
hand-rolled grouper gets wrong.

**WHAT EACH FIELD MEANS, IN MILLISECONDS, FROM THE PINNED 1.10.0 SOURCE:**

* `stt_ms` — caller silence (the VAD timestamp minus its `stop_secs`,
  `LatencyBreakdown.user_turn_start_time`) to the last transcript before the LLM was asked:
  the end of the breakdown's `transcription` contribution (`user_bot_latency_observer.py:
  203-210`, `:661-663`, `:670-677`). That is the interval the STT service's own TTFB is defined over
  (`pipecat/services/stt_service.py:639-647`), read from frames instead of from the metric
  because `SarvamSTTService` never marks a transcript `finalized` (only the realtime class
  does, `sarvam/stt.py:1387`), so its TTFB is reported by a 2 s timeout
  (`stt_service.py:100`, `:651-670`) — after the bot has usually started speaking and the
  observer has closed the cycle, which would leave nearly every turn without the leg.
* `llm_ttft_ms` — the LLM service's TTFB: request sent to first streamed chunk
  (`pipecat/services/openai/base_llm.py:445`, `:513`; Gemini at
  `pipecat/services/google/llm.py:675`, `:697`). A turn that calls a tool runs two
  inferences and reports two; the first is kept, as `TTFATMetricsData`'s docstring advises
  for one figure per user turn (`pipecat/metrics/metrics.py:73-78`).
* `tts_ttfa_ms` — the TTS service's TTFB: text handed to the synthesizer to its first audio
  bytes (`pipecat/services/tts_service.py:1280`, `:1741`). First per turn, because the first
  sentence is the one the caller waits on. Leading silence inside those bytes is NOT
  included: the breakdown carries TTFB only (`user_bot_latency_observer.py:1024-1033`).
* `time_to_first_audio_ms` (per call) — the MEDIAN over this call's turns of caller
  silence -> bot started speaking (`LatencyBreakdown.total_secs`), the closest this runtime
  gets to what the caller experienced. It is still measured in our container, not in the
  caller's ear: the carrier leg on either side is outside it.

**THE LLM AND TTS LEGS ARE IDENTIFIED BY THE PROCESSOR THAT REPORTED THE METRIC**, whose
name is the processor's own `name` (`pipecat/processors/frame_processor.py:257`), classified
by the service base class it is an instance of. A name that matches neither contributes
nothing rather than being guessed at.

**THE HOT PATH IS UNTOUCHED BEYOND THE OBSERVER ITSELF.** The handler appends a handful of
floats per turn; nothing here does I/O. The whole report leaves in the settlement, after
the pipeline has drained.

HARD RULE 6: numbers only. The breakdown carries processor names, function names and
timestamps and no text; this module keeps only the durations.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Final, Literal

from calevate_shared.engine import CallLatency, TurnLatency
from calevate_shared.worker_api import MAX_LATENCY_TURNS
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    MeasuredFrom,
    UserBotLatencyObserver,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.llm_service import LLMService
from pipecat.services.tts_service import TTSService

#: The legs timed by their service's own TTFB. STT is timed from frames instead (see above).
TimedLeg = Literal["llm", "tts"]

_LEG_TYPES: Final[tuple[tuple[type[FrameProcessor], TimedLeg], ...]] = (
    (LLMService, "llm"),
    (TTSService, "tts"),
)


def leg_names(processor: FrameProcessor) -> dict[str, TimedLeg]:
    """Every LLM and TTS service inside `processor`, by the name its metrics carry."""
    found: dict[str, TimedLeg] = {}
    for leg_type, leg in _LEG_TYPES:
        if isinstance(processor, leg_type):
            found[processor.name] = leg
            break
    for child in processor.processors:
        found.update(leg_names(child))
    return found


#: `LatencyContribution.key` of the VAD-stop -> transcript span, which the vendor documents
#: as the stable identifier to group on (`user_bot_latency_observer.py:378-379`).
_TRANSCRIPTION_KEY: Final = "transcription"


@dataclass(frozen=True, slots=True)
class _Cycle:
    #: Caller silence -> last transcript before the LLM request, in seconds.
    stt_s: float | None
    #: First TTFB each processor reported in this cycle, in seconds.
    first_ttfb_s: dict[str, float]
    #: Caller silence -> bot speaking, in seconds, when the cycle was anchored on the caller.
    response_s: float | None


def _ms(seconds: float | None) -> float | None:
    """Seconds to rounded milliseconds. A non-finite or negative interval is absent, never
    0 — a zero reads as instant and moves a median (`TurnLatency`'s rule)."""
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return round(seconds * 1000.0, 2)


class CallLatencyRecorder:
    """Collects one call's turns from a `UserBotLatencyObserver`. One per call."""

    def __init__(self, *, max_turns: int = MAX_LATENCY_TURNS) -> None:
        self._max_turns = max_turns
        self._cycles: list[_Cycle] = []
        self._dropped = 0
        self._legs: dict[str, TimedLeg] = {}
        self._greeting_s: float | None = None

    def attach(self, observer: UserBotLatencyObserver) -> None:
        """Subscribe to the observer the pipeline runs. Like `CallMeter.attach`, the handler
        runs as its own task, so read the result only after the pipeline has drained."""
        observer.add_event_handler("on_latency_breakdown", self._on_latency_breakdown)
        observer.add_event_handler("on_first_bot_speech_latency", self._on_first_bot_speech)

    async def _on_first_bot_speech(self, observer: UserBotLatencyObserver, seconds: float) -> None:
        """The carrier connecting to the agent's first audio: what the caller waits through
        before hearing anything. Emitted once per call by the observer."""
        self._greeting_s = seconds

    @property
    def greeting_first_audio_ms(self) -> float | None:
        """Connect to first bot audio, in ms, or `None` if the agent never spoke."""
        return _ms(self._greeting_s)

    def bind(self, pipeline: FrameProcessor) -> None:
        """Learn which processor is which leg. Call once the pipeline is assembled."""
        self._legs = leg_names(pipeline)

    async def _on_latency_breakdown(
        self, observer: UserBotLatencyObserver, breakdown: LatencyBreakdown
    ) -> None:
        """Pipecat's event signature (observer, breakdown). The vendor shape stops here."""
        self.observe(breakdown)

    def observe(self, breakdown: LatencyBreakdown) -> None:
        """Record one cycle. Total, never raising: a timing is never worth a call."""
        silence = breakdown.user_turn_start_time
        if silence is None:
            return
        if len(self._cycles) >= self._max_turns:
            self._dropped += 1
            return
        stt = next(
            (
                span.start_time + span.duration_secs - silence
                for span in breakdown.contributions
                if span.key == _TRANSCRIPTION_KEY
            ),
            None,
        )
        first: dict[str, float] = {}
        for sample in breakdown.ttfb:
            first.setdefault(sample.processor, sample.duration_secs)
        response = (
            breakdown.total_secs if breakdown.measured_from is MeasuredFrom.USER_SILENCE else None
        )
        self._cycles.append(_Cycle(stt_s=stt, first_ttfb_s=first, response_s=response))

    def call_latency(self) -> CallLatency | None:
        """The call's timings in the normalized shape, or `None` if no turn was answered."""
        if not self._cycles:
            return None
        turns = [self._turn(index, cycle) for index, cycle in enumerate(self._cycles, start=1)]
        responses = [
            ms for ms in (_ms(cycle.response_s) for cycle in self._cycles) if ms is not None
        ]
        warnings: list[str] = []
        if not self._legs:
            warnings.append(
                "No language or speech-synthesis service was identified in the pipeline, so no "
                "turn attributes a first-byte time to either."
            )
        if self._dropped:
            warnings.append(
                f"{self._dropped} turn(s) after the first {self._max_turns} were not recorded."
            )
        return CallLatency(
            # Not reported: this container is not told which Pipecat Cloud region it runs
            # in, and a region written from the deployment docs would be a claim, not a
            # measurement.
            region=None,
            time_to_first_audio_ms=round(statistics.median(responses), 2) if responses else None,
            turns=turns,
            parse_warnings=warnings,
        )

    def _turn(self, index: int, cycle: _Cycle) -> TurnLatency:
        by_leg: dict[TimedLeg, float] = {}
        for processor, seconds in cycle.first_ttfb_s.items():
            leg = self._legs.get(processor)
            if leg is not None and leg not in by_leg:
                by_leg[leg] = seconds
        return TurnLatency(
            turn=index,
            stt_ms=_ms(cycle.stt_s),
            llm_ttft_ms=_ms(by_leg.get("llm")),
            tts_ttfa_ms=_ms(by_leg.get("tts")),
        )


__all__ = ["CallLatencyRecorder", "TimedLeg", "leg_names"]
