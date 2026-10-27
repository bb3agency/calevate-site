"""When each agent line of a call's transcript started, for the call page (D-912).

ThinnestAI's transcript gives each line `at`, "when it was written down, not where it falls in
the audio" (`get-call-transcript.md:7`, 13 Oct 2026 snapshot), and an agent line is written down
with the caller line it answers: on the call of 28 Oct 2026 every agent line showed the same
time as the caller line before it. The call's timeline (D-902) does time the answer: per
caller turn, when the caller stopped (`callerStoppedAtMs`, from the start of the call) and how
long until the answer was heard (`answerAudioMs`, or `firstAudioMs` when nothing else spoke).

The timeline has one row per caller turn and no words, so a row is matched to an agent line
by order only when the counts agree: every agent line that answers a caller line has a row,
or every one but the first, which on an outbound call is the greeting the engine speaks on
pickup. Matching by order with any other count would put one line's time on another, so then
no line is moved. An agent line left unplaced that shows its caller line's time (or earlier)
gets no time at all rather than one that is not its own.

Both clocks are approximate: the transcript's is measured from `answeredAt`, an origin we
inferred (`engine/thinnest._turn_start_ms`), and whether the timeline's "start of the call" is
the same instant is not documented, so a placed line stays `start_approximate`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from calevate_shared.events import CallTimeline


@dataclass(frozen=True, slots=True)
class TimedLine:
    idx: int
    speaker: str
    start_ms: int | None


def agent_line_starts(
    lines: Sequence[TimedLine], timeline: CallTimeline | None
) -> dict[int, int | None]:
    """The new start of each agent line whose stored one is not its own, by `idx`: the time
    its answer was heard, or None where nothing places it. Lines not in the result keep
    their stored start."""
    ordered = sorted(lines, key=lambda line: line.idx)
    answers = [
        (caller, agent)
        for caller, agent in pairwise(ordered)
        if caller.speaker == "caller" and agent.speaker == "agent"
    ]
    rows = sorted(timeline.turns, key=lambda row: row.turn) if timeline else []
    first_agent = next((line.idx for line in ordered if line.speaker == "agent"), None)
    if rows and len(rows) == len(answers) - 1 and answers[0][1].idx == first_agent:
        timed = answers[1:]
    elif len(rows) == len(answers):
        timed = answers
    else:
        timed, rows = [], []
    placed: dict[int, int | None] = {}
    for (_caller, agent), row in zip(timed, rows, strict=True):
        delay = row.answer_ms if row.answer_ms is not None else row.first_sound_ms
        if row.caller_stopped_at_ms is not None and delay is not None:
            placed[agent.idx] = row.caller_stopped_at_ms + delay
    for caller, agent in answers:
        if agent.idx in placed or agent.start_ms is None or caller.start_ms is None:
            continue
        if agent.start_ms <= caller.start_ms:
            placed[agent.idx] = None
    return placed


__all__ = ["TimedLine", "agent_line_starts"]
