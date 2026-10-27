"""Agent lines on the call page get the time they were heard, or none (D-912).

On the Sri Estates call of 28 Oct 2026 every agent line showed the time of the caller line
before it (0:00, 0:07, 0:20 ...): ThinnestAI writes the two down together. The call timeline
(D-902) times each answer from the moment the caller stopped.
"""

from __future__ import annotations

from apps.api.crm.turn_times import TimedLine, agent_line_starts
from calevate_shared.events import CallTimeline, TurnTiming

#: The call's first six lines as the transcript stored them: each agent line at its caller
#: line's time.
LINES = [
    TimedLine(0, "caller", 0),
    TimedLine(1, "agent", 0),
    TimedLine(2, "caller", 7_000),
    TimedLine(3, "agent", 7_000),
    TimedLine(4, "caller", 20_000),
    TimedLine(5, "agent", 20_000),
]


def _timeline(*rows: tuple[int | None, int | None, int | None]) -> CallTimeline:
    return CallTimeline(
        turns=[
            TurnTiming(turn=n, caller_stopped_at_ms=stop, answer_ms=answer, first_sound_ms=sound)
            for n, (stop, answer, sound) in enumerate(rows, 1)
        ]
    )


def test_each_answer_is_placed_where_the_timeline_heard_it() -> None:
    timeline = _timeline((1_000, 1_500, 900), (6_200, 1_700, None), (19_000, None, 1_200))
    assert agent_line_starts(LINES, timeline) == {1: 2_500, 3: 7_900, 5: 20_200}


def test_with_no_row_for_the_greeting_the_rest_are_placed_and_the_greeting_has_no_time() -> None:
    timeline = _timeline((6_200, 1_700, None), (19_000, 1_600, None))
    assert agent_line_starts(LINES, timeline) == {1: None, 3: 7_900, 5: 20_600}


def test_counts_that_do_not_match_move_nothing_and_drop_the_borrowed_times() -> None:
    one_row = _timeline((6_200, 1_700, None))
    expected = {1: None, 3: None, 5: None}
    assert agent_line_starts(LINES, one_row) == expected
    assert agent_line_starts(LINES, None) == expected
    # A line that already has its own, later time keeps it.
    own = [*LINES[:3], TimedLine(3, "agent", 9_000)]
    assert agent_line_starts(own, None) == {1: None}


def test_a_row_with_no_answer_time_leaves_its_line_unplaced() -> None:
    timeline = _timeline((1_000, 1_500, None), (6_200, None, None), (19_000, 1_600, None))
    assert agent_line_starts(LINES, timeline) == {1: 2_500, 3: None, 5: 20_600}
