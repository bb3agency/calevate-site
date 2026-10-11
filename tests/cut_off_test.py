"""Agent lines the caller probably spoke over (D-739, founder 11 Oct 2026).

ThinnestAI's transcript keeps an interrupted reply whole, so we infer the cut: a reply longer
to say than the time before the caller's next turn. These pin the inference (cut, not cut,
the last turn, missing times) and that such a line never becomes a key moment.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.workers.moments import derive_moments, model_moments, prompt_line_turns
from calevate_shared.cut_off import (
    AGENT_CHARS_PER_SECOND,
    TOLERANCE_MS,
    UNHEARD_LABEL,
    likely_cut_off,
    likely_cut_off_rows,
    speaking_ms,
)
from calevate_shared.extraction import MomentCandidate


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


#: Four seconds of speech at the estimated rate.
LONG = "x" * (AGENT_CHARS_PER_SECOND * 4)


def test_a_reply_longer_than_its_gap_is_flagged() -> None:
    turns = [
        _Turn(0, "agent", LONG, 0),
        # The caller came in after one second: well inside four seconds of speech.
        _Turn(1, "caller", "Stop, how much is it?", 1_000),
    ]
    assert likely_cut_off(turns) == {0}


def test_a_reply_that_fits_its_gap_is_not() -> None:
    turns = [_Turn(0, "agent", LONG, 0), _Turn(1, "caller", "Okay.", 4_000)]
    assert likely_cut_off(turns) == set()
    # Inside the rounding of whole-second turn times.
    edge = [_Turn(0, "agent", LONG, 0), _Turn(1, "caller", "Okay.", 4_000 - TOLERANCE_MS)]
    assert likely_cut_off(edge) == set()
    assert speaking_ms(len(LONG)) == 4_000


def test_the_last_turn_and_untimed_turns_are_never_flagged() -> None:
    assert likely_cut_off([_Turn(0, "caller", "Hi", 0), _Turn(1, "agent", LONG, 500)]) == set()
    assert likely_cut_off([_Turn(0, "agent", LONG, None), _Turn(1, "caller", "Hi", 100)]) == set()
    assert likely_cut_off([_Turn(0, "agent", LONG, 0), _Turn(1, "caller", "Hi", None)]) == set()
    # Only an agent line followed by the caller: two agent lines in a row are not a cut.
    assert likely_cut_off([_Turn(0, "agent", LONG, 0), _Turn(1, "agent", "More.", 100)]) == set()
    assert likely_cut_off_rows([]) == set()


def test_the_rows_form_orders_by_index() -> None:
    rows = [(1, "caller", 5, 1_000), (0, "agent", len(LONG), 0)]
    assert likely_cut_off_rows(rows) == {0}


def test_a_cut_off_line_is_never_a_key_moment() -> None:
    turns = [
        _Turn(0, "agent", "Your order of whole chilli is booked for Friday delivery.", 0),
        _Turn(1, "caller", "Wait, no.", 500),
    ]
    unheard = likely_cut_off(turns)
    assert unheard == {0}
    extraction = {"delivery_day": "Friday delivery"}
    assert derive_moments(turns=turns, extraction=extraction, field_labels={}) != []
    assert (
        derive_moments(turns=turns, extraction=extraction, field_labels={}, unheard=unheard) == []
    )
    candidate = MomentCandidate(line=1, kind="booking_agreed", label="Order booked")
    lines = prompt_line_turns(turns)
    assert model_moments([candidate], line_turns=lines, field_labels={}, redact=str) != []
    assert (
        model_moments([candidate], line_turns=lines, field_labels={}, redact=str, unheard=unheard)
        == []
    )


def test_the_extraction_label_is_one_line_and_not_an_agent_prefix() -> None:
    # One line, so `moments.prompt_line_turns` numbers the prompt the same way; not
    # "agent:", so the rule-based reader does not count it as either speaker's words.
    assert "\n" not in UNHEARD_LABEL
    assert UNHEARD_LABEL.startswith("agent (")
