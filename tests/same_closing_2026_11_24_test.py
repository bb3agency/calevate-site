"""Replies that all end with the same words are named after a call (the founder's Rytu Khata
call of 23 Nov 2026: nearly every reply ended "tell me"), by the script check's own rule."""

from __future__ import annotations

from apps.api.agents.call_mistakes import LESSONS
from apps.api.agents.script_checks import SCRIPT_FIXABLE_KINDS
from apps.api.agents.script_lint import line_ending
from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import JOB_KINDS, SOUND_KINDS, conversation_problems

TAGGED = (
    Turn("Yes.", "Open Chrome on your phone and tell me when it is done."),
    Turn("Done.", "Now type the address in the bar and tell me when it is done."),
    Turn("OK.", "Tap the three dots at the top and tell me when it is done."),
)
VARIED = (
    Turn("Yes.", "Open Chrome on your phone and tell me when it is done."),
    Turn("Done.", "Now type the address in the bar. Does the page open?"),
    Turn("OK.", "Tap the three dots at the top. Do you see Add to Home screen?"),
)


def test_three_replies_ending_alike_are_a_sound_note() -> None:
    problems = [p for p in conversation_problems(list(TAGGED)) if p.kind == "same_closing"]
    assert len(problems) == 1
    assert "ended 3 replies" in problems[0].reason
    assert "same_closing" in SOUND_KINDS and "same_closing" not in JOB_KINDS


def test_varied_endings_are_not_named() -> None:
    assert all(p.kind != "same_closing" for p in conversation_problems(list(VARIED)))


def test_a_reply_said_again_word_for_word_counts_once() -> None:
    again = [TAGGED[0], TAGGED[0], TAGGED[0]]
    assert all(p.kind != "same_closing" for p in conversation_problems(again))


def test_goodbyes_are_not_counted() -> None:
    bye = [
        Turn("Thanks.", "Thank you so much Ravi, goodbye and take care."),
        Turn("Bye.", "It was nice talking to you, goodbye and take care."),
        Turn("OK bye.", "Have a lovely evening then, goodbye and take care."),
    ]
    assert len({line_ending(t.reply) for t in bye}) == 1
    assert all(p.kind != "same_closing" for p in conversation_problems(bye))


def test_the_lesson_has_a_script_fix() -> None:
    assert "same_closing" in LESSONS and "same_closing" in SCRIPT_FIXABLE_KINDS
