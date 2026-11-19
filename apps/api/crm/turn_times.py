"""Where each line of a call's transcript falls in the recording, for the call page.

ThinnestAI gives each line one time, `at`, "when it was written down, not where it falls in
the audio" (thinnest-findings snapshots/2026-10-29/pages/api-reference/calls/
get-call-transcript.md:7). A line is written down once its words exist, so the two speakers'
times mean different things:

* an agent line is written as its reply is produced, just before it is heard, so its time is
  a rough start;
* a caller line can only be written once the caller has finished, so its time is when they
  STOPPED. In the vendor's own example the caller's line is written 14.8 s into the call
  while the same call's timeline has that caller stopping at 12.4 s (get-call-transcript.md:
  499-511 against get-call-timeline.md:501-516, call `out_9f2c1a44…`).

Reading a caller line's time as its start is what made every agent line show the time of the
caller line before it (the 28 Oct and 19 Nov 2026 calls): both are stamped at the moment the
caller stopped. So a vendor-timed caller line gets no start here, and "play from" on it goes
to the start of the line before, the latest point known to come before its words. Nothing
says where a caller began, and a guessed time would be shown as a fact.

An agent line answering a caller line is placed where the call's timeline (D-902) heard the
answer: `callerStoppedAtMs` plus `answerAudioMs` (or `firstAudioMs`), get-call-timeline.md:
749-831. The timeline has one row per caller turn and no words, so rows are matched to
answers by order, and only when the counts agree: every answer has a row, or every one but
the first, the greeting an outbound agent speaks on pickup. Any other count would put one
line's time on another, so then each agent line keeps its own written-down time.

The timeline counts from "the start of the call" and our stored times from `answeredAt`
(`engine/thinnest._turn_start_ms`). In the transcript example `offset` is `at - startedAt`
(get-call-transcript.md:499-507), so the two clocks may differ by the ring. The gap is
measured rather than assumed: a caller line is written at or after its caller stopped, so
the most any matched caller line's time trails its row's stop bounds the ring from below,
and subtracting it leaves a placed line at most that line's write delay late. Every
vendor-timed line stays `start_approximate`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from calevate_shared.events import CallTimeline, TurnTiming


@dataclass(frozen=True, slots=True)
class TimedLine:
    idx: int
    speaker: str
    #: The stored time: for a vendor-timed line, when it was written down.
    start_ms: int | None
    #: The time is the vendor's written-down time, not a point in the audio.
    approximate: bool = False


@dataclass(frozen=True, slots=True)
class LineTime:
    #: When the line started, to show; None when nothing says.
    start_ms: int | None
    #: Where "play from this line" seeks; None when it cannot.
    play_from_ms: int | None


def line_times(lines: Sequence[TimedLine], timeline: CallTimeline | None) -> dict[int, LineTime]:
    """Every line's start and play-from point, by `idx`."""
    ordered = sorted(lines, key=lambda line: line.idx)
    placed = _placed_answers(ordered, timeline)
    out: dict[int, LineTime] = {}
    previous: int | None = None
    for line in ordered:
        if line.idx in placed:
            start: int | None = placed[line.idx]
        elif line.approximate and line.speaker == "caller":
            start = None
        else:
            start = line.start_ms
        if start is not None:
            play: int | None = start
        elif line.approximate and line.speaker == "caller" and line.start_ms is not None:
            play = previous if previous is not None else 0
        else:
            play = None
        out[line.idx] = LineTime(start_ms=start, play_from_ms=play)
        if play is not None:
            previous = play
    return out


def _placed_answers(ordered: Sequence[TimedLine], timeline: CallTimeline | None) -> dict[int, int]:
    """The heard start of each vendor-timed agent line the timeline places, by `idx`."""
    answers = [
        (caller, agent)
        for caller, agent in pairwise(ordered)
        if caller.speaker == "caller" and agent.speaker == "agent" and agent.approximate
    ]
    rows = sorted(timeline.turns, key=lambda row: row.turn) if timeline else []
    if not rows or not answers:
        return {}
    first_agent = next((line.idx for line in ordered if line.speaker == "agent"), None)
    if len(rows) == len(answers) - 1 and answers[0][1].idx == first_agent:
        timed = answers[1:]
    elif len(rows) == len(answers):
        timed = answers
    else:
        return {}
    pairs = list(zip(timed, rows, strict=True))
    trails = [
        row.caller_stopped_at_ms - caller.start_ms
        for (caller, _agent), row in pairs
        if row.caller_stopped_at_ms is not None and caller.start_ms is not None
    ]
    ring = max(0, *trails) if trails else 0
    placed: dict[int, int] = {}
    for (_caller, agent), row in pairs:
        heard = _heard_ms(row)
        if heard is not None:
            placed[agent.idx] = max(heard - ring, 0)
    return placed


def _heard_ms(row: TurnTiming) -> int | None:
    delay = row.answer_ms if row.answer_ms is not None else row.first_sound_ms
    if row.caller_stopped_at_ms is None or delay is None:
        return None
    return row.caller_stopped_at_ms + delay


__all__ = ["LineTime", "TimedLine", "line_times"]
