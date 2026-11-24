"""D-1022: the conversation rules every agent carries, from the Rytu Khata campaign call of
19 Nov 2026 (a reaction with nothing after it, a line said again after an answer that changed
the plan, "anything else?" reply after reply and after "that's all", a name asked or invented),
and the checks that name those faults on real calls."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from apps.api.agents import turn_checks
from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.test_conversations import Turn as Exchange
from apps.api.agents.turn_checks import conversation_problems
from calevate_shared.engine import (
    NAME_RULE,
    AgentConfig,
    compose_engine_prompt,
    join_first_words,
)
from calevate_shared.languages import offered_language_tags
from calevate_shared.spoken_guard import SPOKEN_LINE_RULES, generation_guidance

RULES = (
    "Say one thing a turn, one instruction or one question, in one or two short sentences, "
    "then stop.",
    "React only when it fits, and never begin or end two replies alike.",
    "Never ask again what they already told you, and never say a sentence twice;",
    'Ask "anything else?" once, when the task is done.',
    'Whole sentences ending in "." or "?";',
    "- If THIS CALL has no name, never invent one; ask once, only to book, call back, hand over "
    "or close.",
)


def _config(direction: str, **extra: object) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "tenant_id": "t",
            "agent_id": "a",
            "name": "A",
            "business": "B",
            "direction": direction,
            "language_primary": "te-IN",
            "system_prompt": "Help them.",
            "opening_line": "",
            "call_is_recorded": True,
            **extra,
        }
    )


@pytest.mark.parametrize("direction", ["inbound", "outbound", "both"])
def test_every_agent_carries_the_rules(direction: str) -> None:
    prompt = compose_engine_prompt(_config(direction))
    for rule in RULES:
        assert prompt.count(rule) == 1, (direction, rule)


def test_a_screen_agent_says_a_step_again_shorter() -> None:
    prompt = compose_engine_prompt(_config("outbound", caller_has_screen=True))
    assert "to say something again, say it shorter, in other words." in prompt


def test_the_rules_are_english_and_name_no_business() -> None:
    from calevate_shared.spoken_guard import has_indic_letters

    for rule in (*RULES, NAME_RULE):
        assert not has_indic_letters(rule)
        assert "Rytu" not in rule and "farm" not in rule.lower()


def test_every_offered_languages_writer_guide_asks_for_full_punctuation() -> None:
    for tag in offered_language_tags():
        guide = generation_guidance(tag)
        assert guide.endswith(SPOKEN_LINE_RULES), tag
    assert "every sentence ends with a full stop" in SPOKEN_LINE_RULES


def test_an_opening_without_a_mark_is_closed_before_the_notice() -> None:
    notice = "This call is recorded."
    joined = join_first_words(notice, "Hello from the shop", ai_notice="", language="en-IN")
    assert joined == "Hello from the shop. This call is recorded."
    asked = join_first_words(notice, "Hello, can we talk now?", ai_notice="", language="en-IN")
    assert asked == "Hello, can we talk now? This call is recorded."
    assert join_first_words("", "Hello from the shop", ai_notice="", language="en-IN") == (
        "Hello from the shop"
    )


def test_a_reaction_the_caller_had_to_follow_with_a_question_is_stalled() -> None:
    exchanges = [
        Exchange("I have not used it at all so far.", "OK, no problem."),
        Exchange("So tell me, what is this actually?", ""),
    ]
    kinds = {p.kind for p in conversation_problems(exchanges)}
    assert "stalled" in kinds
    assert "stalled" in turn_checks.SOUND_KINDS and "stalled" in LESSONS


@pytest.mark.parametrize(
    ("said", "reply", "said_next"),
    [
        ("One minute, let me open it.", "Sure.", "OK, what now?"),
        ("I have not used it.", "OK, no problem.", "I will try it later."),
        ("I have not used it.", "OK, shall I tell you what it does?", "What is it?"),
        ("How much is it?", "It is free.", "Where do I get it?"),
        ("That is all.", "Thank you, bye.", "Bye?"),
    ],
)
def test_a_few_words_that_fit_are_not_stalled(said: str, reply: str, said_next: str) -> None:
    assert not turn_checks.stalled(said, reply, said_next)


def test_offering_more_after_that_is_all_is_offering_too_soon() -> None:
    exchanges = [Exchange("That's all, nothing else.", "OK, is there anything else?")]
    kinds = {p.kind for p in conversation_problems(exchanges)}
    assert "offered_more_too_soon" in kinds


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str


def test_a_real_call_names_the_stall_on_the_reply() -> None:
    turns = [
        _Turn(0, "caller", "Hello."),
        _Turn(1, "agent", "Hello, I am calling from the shop, can we talk now?"),
        _Turn(2, "caller", "Go ahead."),
        _Turn(3, "agent", "Are you using our app on the phone?"),
        _Turn(4, "caller", "I have not used it at all so far."),
        _Turn(5, "agent", "OK, no problem."),
        _Turn(6, "caller", "So tell me, what is this actually?"),
        _Turn(7, "agent", "It keeps your accounts. Shall I show you how?"),
    ]
    assert mistakes_in(turns, language="en-IN").get("stalled") == 5
