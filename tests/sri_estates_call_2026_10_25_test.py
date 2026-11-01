"""The Sri Estates production calls of 25 Oct 2026 (D-888).

Outbound, Telugu, agent "Anjali", a property office in Guntur whose facts name only the town.
Four faults: it invented places, projects and how the caller had enquired ("you enquired on
our website"); at about 8 pm on a Sunday it offered "this weekend, Saturday or Sunday" and
agreed that tomorrow was Thursday; it never asked the caller's name; and it asked "two or three
BHK?" of a caller who wanted five.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.api.agents.test_conversations import RuleContext, Turn, hard_check, probe_scenario
from apps.api.agents.turn_checks import JOB_KINDS, conversation_problems
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    DAYS_RULE,
    NAME_LINE,
    NAME_RULE,
    THIS_CALL_HEADER,
    TODAY_LINE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
    today_value,
)

OPENING = "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?"
#: "You enquired on our website" — said when the caller asked which project they had seen.
WEBSITE = "మీరు మా వెబ్‌సైట్‌లో ఎంక్వైరీ చేశారు అండి. ఏ ఏరియా లో చూస్తున్నారు?"


def _anjali(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Anjali",
        "business": "Sri Estates",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": compile_call_script(CallScript(schema_version=2, opening_line=OPENING)),
        "opening_line": "",
        "call_is_recorded": True,
    }
    return AgentConfig(**{**fields, **over})


# --- 1. say only what the facts or the caller said ---------------------------------------


def test_the_facts_rule_names_places_projects_availability_and_how_they_found_you() -> None:
    facts = dict(engine_prompt_layers(_anjali()))["business_facts"]
    assert "Say only what your facts or the caller said" in facts
    for named in ("a place", "a project", "stock or availability", "how they found you"):
        assert named in facts
    # Not knowing has one way to be said, in the cannot-help rule rather than a second rule.
    can_do = dict(engine_prompt_layers(_anjali()))["what_you_can_do"]
    assert '"the team will share that"' in can_do
    assert '"the team will share that"' not in facts


def test_telling_the_caller_where_they_enquired_fails_the_test() -> None:
    said = [Turn("నేను మీ ఏ ప్రాజెక్ట్ చూశానో గుర్తు లేదు.", WEBSITE)]
    kinds = [p.kind for p in conversation_problems(said)]
    assert kinds == ["invented_source"]
    assert "invented_source" in JOB_KINDS
    verdict = hard_check(probe_scenario("ai", "te-IN"), [Turn(said[0].said, WEBSITE)])
    assert verdict.verdict == "failed" and verdict.fix == "platform"
    assert "named a website or listing" in (verdict.reason or "")


def test_a_source_the_caller_or_the_facts_named_or_a_question_is_no_invention() -> None:
    caller_said = [Turn("నేను మీ వెబ్‌సైట్ లో చూశాను.", WEBSITE)]
    assert conversation_problems(caller_said) == []
    facts_say = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE)]
    assert conversation_problems(facts_say, known="Leads come from our website form.") == []
    asked = [Turn("ఎవరు మీరు?", "మీరు మా వెబ్‌సైట్ చూశారా అండి?")]
    assert "invented_source" not in [p.kind for p in conversation_problems(asked)]
    searched = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE, tools=["search_knowledge"])]
    assert conversation_problems(searched) == []


def test_the_test_run_judges_against_what_the_agent_was_given() -> None:
    said = [Turn("ఏ ప్రాజెక్ట్?", WEBSITE)]
    scenario = probe_scenario("ai", "te-IN")
    told = RuleContext(known="Callers usually find us on our website.")
    assert "website or listing" in (hard_check(scenario, said).reason or "")
    assert "website or listing" not in (hard_check(scenario, said, rules=told).reason or "")


# --- 2. today's date and weekday ----------------------------------------------------------


def test_today_is_the_ist_day_with_its_weekday() -> None:
    # 20:00 IST on Sunday 25 Oct 2026, when the agent offered "this weekend".
    assert today_value(datetime(2026, 10, 25, 14, 30, tzinfo=UTC)) == (
        "Sunday, 25 October 2026; then Mon 26 Oct, Tue 27 Oct, Wed 28 Oct, Thu 29 Oct, "
        "Fri 30 Oct, Sat 31 Oct"
    )
    # 19:00 UTC is already Monday in India.
    assert today_value(datetime(2026, 10, 25, 19, 0, tzinfo=UTC)).startswith(
        "Monday, 26 October 2026; then Tue 27 Oct"
    )


def test_every_agent_reads_today_and_the_name_and_the_rules_that_use_them() -> None:
    for direction in ("outbound", "inbound", "both"):
        prompt = compose_engine_prompt(_anjali(direction=direction))
        assert f"{THIS_CALL_HEADER}\n{TODAY_LINE}\n{NAME_LINE}" in prompt
        # The rules sit with the others after the client script, before the floor.
        for rule in (NAME_RULE, DAYS_RULE):
            assert prompt.index(rule) > prompt.index(OPENING)
            assert prompt.index(rule) < prompt.index(CONFIDENTIALITY_MARKER)
    assert "never a past one" in DAYS_RULE and "Ask which" in DAYS_RULE
    assert "Ask once, to book, call back or hand over, or at the close" in NAME_RULE


# --- 3 and 4. open questions for what the caller decides, the next days for a visit -------


def test_choices_are_for_times_and_a_count_is_asked_openly() -> None:
    assert '"morning or evening?"' in VOICE_STYLE_GUIDANCE
    assert "never for counts or amounts" in VOICE_STYLE_GUIDANCE
