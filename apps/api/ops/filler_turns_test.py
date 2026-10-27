"""Which agent turns opened with a filler line (D-901): the rule the reply-time report uses
to keep filler-cut waits out of its clean typical figure."""

from __future__ import annotations

from calevate_shared.events import TranscriptTurn

from apps.api.ops.filler_turns import (
    begins_with_filler,
    filler_lines_for,
    filler_turns,
    platform_filler_lines,
)


def _turn(idx: int, speaker: str, text: str) -> TranscriptTurn:
    return TranscriptTurn.model_validate(
        {"call_id": "c1", "idx": idx, "speaker": speaker, "text": text}
    )


def test_the_platform_lines_cover_telugu_and_hindi() -> None:
    lines = platform_filler_lines()
    assert "ఒక్క సెకండ్ అండి" in lines
    assert "एक मिनट जी" in lines


def test_a_filler_must_open_the_turn_and_end_on_a_word_boundary() -> None:
    lines = filler_lines_for(["One moment"])
    assert begins_with_filler("One moment. We open at nine.", lines)
    assert begins_with_filler("  one MOMENT", lines)
    assert begins_with_filler("…One moment, please", lines)
    assert not begins_with_filler("One momentous day", lines)
    assert not begins_with_filler("We open at nine. One moment", lines)
    assert not begins_with_filler("", lines)


def test_an_indic_filler_is_matched_through_its_vowel_signs() -> None:
    lines = filler_lines_for(None)
    assert begins_with_filler("ఒక్క సెకండ్ అండి, చూస్తాను.", lines)
    assert begins_with_filler("एक मिनट जी। हम नौ बजे खुलते हैं।", lines)
    # A longer word that starts with the same letters is not the filler.
    assert not begins_with_filler("ఒక్క సెకండ్ అండిలో", lines)


def test_only_agent_turns_count_and_blank_lines_are_dropped() -> None:
    lines = filler_lines_for(["  ", "Let me check"], ["Let me check", "Hold on"])
    assert lines.count("let me check") == 1
    transcript = [
        _turn(0, "caller", "Let me check my diary"),
        _turn(1, "agent", "Let me check. Yes, Saturday works."),
        _turn(2, "agent", "Hold on, one second"),
        _turn(3, "agent", "Saturday works."),
    ]
    assert filler_turns(transcript, lines) == 2
    assert filler_turns([], lines) == 0
