"""The founder's Sri Estates trial call of 30 Oct 2026 (D-947).

Outbound, Telugu, agent "Anjali". The caller's lines after the opening were "Sri Estates.",
"Yes.", "Ah." and then "Sri Estates." four times; each of the four drew the same line
(who is calling, then "which area are you looking in?"), and the call ended at 0:59 with
nothing gained. The opening said the name as "Sri-Estates" in English letters; every later
turn said "శ్రీ ఎస్టేట్స్". Each agent line below is the call's.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents.specimen_scenarios import CLASSES, scenario_of
from apps.api.agents.test_conversations import Turn, hard_check
from apps.api.agents.turn_checks import JOB_KINDS, conversation_problems
from calevate_shared.call_script import (
    CallScript,
    Pronunciation,
    SpeakingStyle,
    compile_call_script,
)
from calevate_shared.engine import (
    CLIENT_SCRIPT_CLOSE,
    OPENING_CONTINUES_RULE,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
    placed_call_line,
    said_as_taught,
)

OPENING = "నమస్కారం అండి, Sri-Estates నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"
ECHO = "Sri Estates."
LOOP = "అవునండి, శ్రీ ఎస్టేట్స్ నుంచి కాల్ చేస్తున్నాను. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?"
CALL = (
    Turn(ECHO, "మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?"),
    Turn("Yes.", "సంతోషం అండి. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?"),
    Turn("Ah.", "పర్లేదు అండి, మీకు ఏ ఏరియాలో అయితే బాగుంటుంది అనిపిస్తుందో చెప్తారా?"),
    Turn(ECHO, LOOP),
    Turn(ECHO, LOOP),
    Turn(ECHO, LOOP),
    Turn(ECHO, LOOP),
)
TAUGHT = "శ్రీ ఎస్టేట్స్"


def _body(*, taught: bool = True) -> str:
    style = SpeakingStyle(
        pronunciations=[Pronunciation(word="Sri Estates", say_as=TAUGHT)] if taught else []
    )
    return compile_call_script(CallScript(schema_version=2, opening_line=OPENING, style=style))


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": _body(),
        "opening_line": "",
        "call_is_recorded": True,
        "facts_in_knowledge": True,
        "knowledge_tool": "search_knowledge",
        "callbacks_offered": False,
    }
    return AgentConfig(**{**fields, **over})


# --- the loop -----------------------------------------------------------------------------


def test_the_calls_repeated_line_fails_the_test_as_ours_to_fix() -> None:
    kinds = [p.kind for p in conversation_problems(list(CALL), opening=OPENING)]
    assert "said_again" in kinds
    assert "said_again" in JOB_KINDS
    cls = next(c for c in CLASSES if c.key == "specimen_echoes_business_name")
    checked = hard_check(scenario_of(cls, "te-IN", "real_estate"), list(CALL), language="te-IN")
    assert checked.verdict == "failed"
    assert checked.fix == "platform"
    assert "a line it had already said on this call" in checked.reason


def test_a_reworded_retry_and_a_close_pass() -> None:
    better = (
        CALL[0],
        Turn(ECHO, "అవునండి, శ్రీ ఎస్టేట్స్ నుంచి, మీ ప్రాపర్టీ ఎంక్వైరీ గురించి కాల్ చేశాను."),
        Turn(ECHO, "ఇప్పుడు వీలు కాదేమో అండి. మా టీమ్ మీకు మళ్ళీ కాల్ చేస్తారు. థాంక్స్ అండి."),
    )
    kinds = [p.kind for p in conversation_problems(list(better), opening=OPENING)]
    assert "said_again" not in kinds


def test_saying_it_again_when_asked_is_not_said_again() -> None:
    asked = (
        Turn("Hello.", LOOP),
        Turn("మళ్ళా చెప్పండి.", LOOP),
    )
    kinds = [p.kind for p in conversation_problems(list(asked))]
    assert "said_again" not in kinds
    assert "repeated_turn" in kinds


def test_a_short_courtesy_twice_is_ordinary_speech() -> None:
    twice = (Turn("సరే.", "సరే అండి. మీ పేరు చెప్తారా?"), Turn("రాము.", "సరే అండి. రాము గారు, థాంక్స్."))
    assert "said_again" not in [p.kind for p in conversation_problems(list(twice))]


def test_the_echo_caller_says_the_accounts_own_name() -> None:
    cls = next(c for c in CLASSES if c.key == "specimen_echoes_business_name")
    scenario = scenario_of(cls, "te-IN", "real_estate", business_name="Sri  Estates")
    assert scenario.turns == ("Sri Estates.",) * 3
    assert "never says a line it already said" in scenario.expect
    assert scenario_of(cls, "en-IN", "retail").turns == ("Hello.",) * 3


# --- the rules ----------------------------------------------------------------------------


def test_the_name_said_back_is_answered_once() -> None:
    assert (
        "Asked who or why, or the business name said back? Both in one line, once, wait."
    ) in OPENING_CONTINUES_RULE
    assert OPENING_CONTINUES_RULE in compose_engine_prompt(_anjali())


def test_no_clear_reply_twice_ends_on_what_the_account_allows_after_the_script() -> None:
    trial = compose_engine_prompt(_anjali())
    rule = (
        'No answer after searching ("the team will share that"), or no clear reply twice to '
        "one question: say so, then say the business will get back to them. Never offer or "
        "book a call back."
    )
    assert rule in trial
    assert trial.index(CLIENT_SCRIPT_CLOSE) < trial.index(rule)
    paying = compose_engine_prompt(_anjali(callbacks_offered=True))
    assert "or no clear reply twice to one question: say so, then offer a call back" in paying
    assert "Ask one thing again, reworded; never pick for them." in paying
    assert "Never re-ask what they said or repeat a sentence." in paying


# --- the spoken name ----------------------------------------------------------------------


def test_the_opening_says_the_taught_name() -> None:
    first = compose_first_utterance(_anjali())
    assert first == f"నమస్కారం అండి, {TAUGHT} నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"
    # The prompt quotes what the caller heard.
    assert first in compose_engine_prompt(_anjali())


def test_without_a_taught_name_the_opening_says_the_business_as_it_writes_it() -> None:
    first = compose_first_utterance(_anjali(system_prompt=_body(taught=False)))
    assert "Sri Estates నుంచి" in first
    assert "Sri-Estates" not in first


def test_notices_are_never_rewritten() -> None:
    notice = "ఇది Sri-Estates ఏఐ అసిస్టెంట్."
    first = compose_first_utterance(_anjali(opening_line=notice))
    assert notice in first


def test_a_both_agents_placed_line_says_the_taught_name_too() -> None:
    line = placed_call_line(body=_body(), language="te-IN", business="Sri Estates", ai_notice="")
    assert "Sri" not in line
    assert TAUGHT in line


def test_names_match_whole_words_only() -> None:
    assert said_as_taught("Sri Estatesville", body="", business="Sri Estates") == "Sri Estatesville"
    assert said_as_taught("sri_estates here", body="", business="Sri Estates") == "Sri Estates here"
    assert said_as_taught("Hi-Tech Motors", body="", business="Hi-Tech Motors") == "Hi-Tech Motors"
