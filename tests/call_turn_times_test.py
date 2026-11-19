"""Where each transcript line falls in the recording on the call page (`crm/turn_times`).

ThinnestAI writes a caller line down once the caller has stopped and the agent's answer
just after, so on the calls of 28 Oct and 19 Nov 2026 every agent line showed the time of
the caller line before it (0:03/0:03, 0:12/0:12 ...). The call timeline (D-902) says when
each answer was heard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.api.crm.turn_times import LineTime, TimedLine, line_times
from apps.api.engine.thinnest import parse_timeline, parse_transcript
from calevate_shared.events import CallTimeline, TurnTiming

ANSWERED = "2026-11-19T06:00:05.000+00:00"

#: Shaped like Get Call Transcript's `turns` (thinnest-findings snapshots/2026-10-29/pages/
#: api-reference/calls/get-call-transcript.md:500-511): each agent line written down a few
#: hundred ms after the caller line it answers, which is written once the caller stopped.
VENDOR_TURNS: list[dict[str, Any]] = [
    {"speaker": "customer", "text": "Hello.", "at": "2026-11-19T06:00:08.100Z", "offset": 8},
    {"speaker": "agent", "text": "Namaskaram.", "at": "2026-11-19T06:00:08.400Z", "offset": 8},
    {"speaker": "customer", "text": "Go ahead.", "at": "2026-11-19T06:00:17.200Z", "offset": 17},
    {"speaker": "agent", "text": "You registered.", "at": "2026-11-19T06:00:17.500Z", "offset": 17},
    {
        "speaker": "customer",
        "text": "Not using it.",
        "at": "2026-11-19T06:00:42.000Z",
        "offset": 42,
    },
    {"speaker": "agent", "text": "No problem.", "at": "2026-11-19T06:00:42.300Z", "offset": 42},
]

#: Get Call Timeline's `timeline` for the same call (get-call-timeline.md:503-523), counted
#: from `startedAt`, five seconds of ring before `answeredAt`.
VENDOR_TIMELINE: dict[str, Any] = {
    "v": 1,
    "turns": [
        {"turn": 1, "callerStoppedAtMs": 7_400, "answerAudioMs": 1_900, "firstAudioMs": 1_900},
        {"turn": 2, "callerStoppedAtMs": 16_500, "answerAudioMs": 2_100, "firstAudioMs": 900},
        {"turn": 3, "callerStoppedAtMs": 41_300, "answerAudioMs": 1_800, "firstAudioMs": 1_800},
    ],
}


def _vendor_lines() -> list[TimedLine]:
    turns, lost = parse_transcript(VENDOR_TURNS, "c1", answered=datetime.fromisoformat(ANSWERED))
    assert lost == 0
    return [TimedLine(t.idx, t.speaker, t.start_ms, t.start_approximate) for t in turns]


def test_a_vendor_call_gives_caller_lines_no_start_and_agent_lines_where_they_were_heard() -> None:
    times = line_times(_vendor_lines(), parse_timeline(VENDOR_TIMELINE))
    # Ring measured from the lines: the most a caller line trails its stop is 41.3 - 37.0.
    ring = 41_300 - 37_000
    assert times == {
        0: LineTime(start_ms=None, play_from_ms=0),
        1: LineTime(start_ms=7_400 + 1_900 - ring, play_from_ms=7_400 + 1_900 - ring),
        2: LineTime(start_ms=None, play_from_ms=5_000),
        3: LineTime(start_ms=16_500 + 2_100 - ring, play_from_ms=14_300),
        4: LineTime(start_ms=None, play_from_ms=14_300),
        5: LineTime(start_ms=41_300 + 1_800 - ring, play_from_ms=38_800),
    }
    # No agent line shows the second of the caller line before it any more.
    shown = [t.start_ms for t in times.values()]
    assert len([s for s in shown if s is not None]) == len({s for s in shown if s is not None})


def test_without_a_timeline_an_agent_line_keeps_its_own_written_time() -> None:
    times = line_times(_vendor_lines(), None)
    assert [times[i].start_ms for i in range(6)] == [None, 3_400, None, 12_500, None, 37_300]
    # "Play from" a caller line starts at the line before, never after their words.
    assert [times[i].play_from_ms for i in range(6)] == [0, 3_400, 3_400, 12_500, 12_500, 37_300]


def _timeline(*rows: tuple[int | None, int | None, int | None]) -> CallTimeline:
    return CallTimeline(
        turns=[
            TurnTiming(turn=n, caller_stopped_at_ms=stop, answer_ms=answer, first_sound_ms=sound)
            for n, (stop, answer, sound) in enumerate(rows, 1)
        ]
    )


LINES = [
    TimedLine(0, "agent", 300, True),
    TimedLine(1, "caller", 7_000, True),
    TimedLine(2, "agent", 7_200, True),
    TimedLine(3, "caller", 20_000, True),
    TimedLine(4, "agent", 20_100, True),
]


def test_answers_are_placed_and_a_greeting_answering_nobody_keeps_its_time() -> None:
    times = line_times(LINES, _timeline((6_200, 1_700, None), (19_000, None, 1_600)))
    assert [times[i].start_ms for i in range(5)] == [300, None, 7_900, None, 20_600]


def test_counts_that_do_not_match_place_nothing() -> None:
    times = line_times(LINES, _timeline((6_200, 1_700, None)))
    assert [times[i].start_ms for i in range(5)] == [300, None, 7_200, None, 20_100]


def test_a_row_with_no_answer_time_leaves_its_line_at_its_own_time() -> None:
    times = line_times(LINES, _timeline((6_200, None, None), (19_000, 1_600, None)))
    assert [times[i].start_ms for i in range(5)] == [300, None, 7_200, None, 20_600]


def test_exactly_timed_lines_are_shown_as_stored() -> None:
    exact = [TimedLine(0, "caller", 0), TimedLine(1, "agent", 4_000)]
    assert line_times(exact, None) == {
        0: LineTime(start_ms=0, play_from_ms=0),
        1: LineTime(start_ms=4_000, play_from_ms=4_000),
    }
    untimed = [TimedLine(0, "agent", None, True), TimedLine(1, "caller", None, True)]
    assert line_times(untimed, None) == {
        0: LineTime(start_ms=None, play_from_ms=None),
        1: LineTime(start_ms=None, play_from_ms=None),
    }
