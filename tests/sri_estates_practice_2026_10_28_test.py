"""The founder's Sri Estates practice run of 28 Oct 2026 (D-910).

Outbound, Telugu, agent "Anjali". The test judge put four faults on the platform's side: four
digits of a number read back and confirmed; the call's own number asked for, with the name, in
one question; two questions joined in one sentence, then asked again word for word after a
bare "సరే"; and the opening said again after answering "is this call recorded?". Each line
below is the agent's as the run had it. The prompt carries the rule for each, and the checks
the practice tests and the call scan run see each.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    SOUND_KINDS,
    conversation_problems,
    greeted_midway,
    turn_problems,
)
from calevate_shared.engine import (
    CALL_NUMBER_RULE,
    CONFIDENTIALITY_MARKER,
    OPENING_CONTINUES_RULE,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
)

ASKS_WHICH = "సరే అండి, ఏ నంబర్‌కి పంపాలో చెప్తారా? ఆ నంబర్‌ని నోట్ చేసుకుని టీమ్‌కి చెప్తాను."
PARTIAL = (
    Turn("వేరే నంబర్ కి పంపండి.", ASKS_WHICH),
    Turn("నంబర్ 9876.", "సరే అండి, తొమ్మిది ఎనిమిది ఏడు ఆరు. ఈ నంబర్ కరెక్టేనా అండి?"),
)
TWO_AT_ONCE = "సరే అండి. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు, అలాగే మీ బడ్జెట్ ఎంత వరకు అనుకుంటున్నారు?"
REGREETED = "అవునండి, ఈ కాల్ రికార్డ్ అవుతోంది. నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": "Call people who enquired about a property.",
        "opening_line": "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను.",
        "call_is_recorded": True,
        "facts_in_knowledge": True,
        "knowledge_tool": "search_knowledge",
    }
    return AgentConfig(**{**fields, **over})


def _kinds(turns: tuple[Turn, ...] | list[Turn]) -> list[str]:
    return [p.kind for p in conversation_problems(list(turns))]


def test_the_prompt_carries_each_fix_and_keeps_the_locked_text() -> None:
    prompt = compose_engine_prompt(_anjali())
    assert VOICE_STYLE_GUIDANCE in prompt
    # The partial-number rule comes before the read-back, as its own bullet.
    partial = prompt.index("- Under ten digits of a mobile? Ask for the rest")
    assert partial < prompt.index("- Read back what you heard")
    assert "never read back, confirm, act or end on part of one" in prompt
    assert "A time or amount they said goes back in their words" in prompt
    assert "One question a turn, on one thing, last;" in prompt
    assert 'A bare "OK"? Ask one thing, reworded.' in prompt
    assert CALL_NUMBER_RULE in prompt and "for call backs too" in CALL_NUMBER_RULE
    assert OPENING_CONTINUES_RULE in prompt
    assert "even after answering a question first" in OPENING_CONTINUES_RULE
    assert CONFIDENTIALITY_MARKER in prompt and TRUTHFUL_ANSWER_MARKER in prompt
    assert prompt.index(CONFIDENTIALITY_MARKER) < prompt.index(TRUTHFUL_ANSWER_MARKER)


def test_four_digits_read_back_and_confirmed_fail_the_test() -> None:
    assert _kinds(PARTIAL) == ["partial_number"]
    assert "partial_number" in JOB_KINDS


def test_the_same_digits_in_telugu_words_count_and_a_read_back_alone_is_taken() -> None:
    said = Turn("తొమ్మిది ఎనిమిది ఏడు ఆరు.", "నైన్ ఎయిట్ సెవెన్ సిక్స్, ఇంకా చెప్పండి.")
    assert _kinds([PARTIAL[0], said]) == ["partial_number"]


def test_asking_for_the_missing_digits_is_right() -> None:
    for ask in ("ఇంకా సిక్స్ డిజిట్స్ చెప్తారా అండి?", "Six more digits, please?"):
        assert _kinds([PARTIAL[0], Turn("నంబర్ 9876.", ask)]) == [], ask
    whole = (
        *PARTIAL[:1],
        Turn("నంబర్ 9876.", "ఇంకా సిక్స్ డిజిట్స్ చెప్తారా?"),
        Turn("543210.", "నైన్ ఎయిట్ సెవెన్ సిక్స్, ఫైవ్ ఫోర్ త్రీ, టూ వన్ జీరో. కరెక్టేనా?"),
    )
    assert _kinds(whole) == []


def test_the_calls_own_number_asked_with_the_name_fails_the_test() -> None:
    asked = Turn(
        "ఒక మనిషితో మాట్లాడాలి, connect చేయండి.",
        "ఇప్పుడు ఎవరూ ఫ్రీగా లేరు అండి. మీ పేరు, ఫోన్ నంబర్ చెప్తారా?",
    )
    assert _kinds([asked]) == ["asked_known_number"]
    same = Turn(asked.said, "ఇప్పుడు ఎవరూ ఫ్రీగా లేరు అండి. ఇదే నంబర్ కి కాల్ చేయమంటారా?")
    assert _kinds([same]) == []


def test_two_questions_joined_in_one_sentence_are_noted() -> None:
    kinds = [p.kind for p in turn_problems(TWO_AT_ONCE, language="te-IN")]
    assert "several_questions" in kinds
    # A choice in one question is one question.
    one = "పొద్దున వీలవుతుందా, సాయంత్రమా?"
    assert "several_questions" not in [p.kind for p in turn_problems(one, language="te-IN")]
    # So is a single question with ఏ and an ఏరియా word.
    single = "మీరు ఏ ఏరియాలో చూస్తున్నారు?"
    assert "several_questions" not in [p.kind for p in turn_problems(single, language="te-IN")]


def test_the_same_question_after_a_bare_ok_is_noted() -> None:
    turns = [Turn("సరే, details పంపండి.", TWO_AT_ONCE), Turn("సరే.", TWO_AT_ONCE)]
    assert "asked_again" in _kinds(turns)
    assert "asked_again" in SOUND_KINDS
    reworded = [Turn("సరే, details పంపండి.", TWO_AT_ONCE), Turn("సరే.", "ఏ ఏరియా అండి?")]
    assert "asked_again" not in _kinds(reworded)
    # Asked something in between, the caller gets the answer and the question back.
    answered = [
        Turn("సరే, details పంపండి.", "ఏ ఏరియా అండి?"),
        Turn("ధర ఎంత?", "టీమ్ షేర్ చేస్తుంది అండి. ఏ ఏరియా అండి?"),
    ]
    assert "asked_again" not in _kinds(answered)


def test_the_opening_said_again_after_an_answer_is_noted() -> None:
    turns = [
        Turn("హా, చెప్పండి.", "మీరు ఇంతకు ముందు మా ప్రాజెక్ట్స్ గురించి అడిగారు."),
        Turn("ఈ call record అవుతుందా?", REGREETED),
    ]
    assert "opened_again" in _kinds(turns)
    # And as the first reply, where the practice caller's question came before anything else.
    assert "opened_again" in _kinds(turns[1:])
    assert greeted_midway(REGREETED) is not None
    # A goodbye that ends on నమస్కారం, or a "hello?" to a quiet line, is no second opening.
    assert greeted_midway("సరే అండి, టీమ్ కాల్ చేస్తుంది. ఉంటాను మరి, నమస్కారం.") is None
    assert greeted_midway("హలో? వినిపిస్తోందా అండి?") is None
