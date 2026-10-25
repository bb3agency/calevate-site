"""The opening is the agent's own first turn (D-864, founder 23 Oct 2026).

The Sri Estates trial call: the engine spoke "నమస్కారం అండి, Sri Estates నుంచి call
చేస్తున్నాను. ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?", the caller said "Hello.", and the agent
greeted again ("నమస్కారం అండి. మీరు ఇంతకు ముందు"); asked who it was, it said who and why and
then asked again whether now suited. The opening also wrote "call" in English letters.
"""

from __future__ import annotations

from apps.api.agents.specimen_scenarios import CLASSES, scenario_of
from apps.api.agents.test_conversations import Turn, hard_check
from apps.api.agents.turn_checks import SOUND_KINDS, conversation_problems, opened_again
from apps.workers.first_run import greeting_fits
from apps.workers.script_assist import language_problems
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    OPENING_CONTINUES_RULE,
    START_OF_CALL_HEADER,
    TRUTHFUL_ANSWER_MARKER,
    WHO_IS_CALLING_RULE,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
    engine_prompt_layers,
)
from calevate_shared.spoken_guard import latin_word_problem, latin_words

OPENING = "నమస్కారం అండి, Sri Estates నుంచి కాల్ చేస్తున్నాను. ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?"
NOTICE = "ఇది Sri Estates ఏఐ అసిస్టెంట్."


def _cfg(direction: str = "outbound", *, notices: str = NOTICE) -> AgentConfig:
    script = CallScript(schema_version=2, opening_line=OPENING)
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Anjali",
        business="Sri Estates",
        direction=direction,  # type: ignore[arg-type]
        language_primary="te-IN",
        system_prompt=compile_call_script(script),
        opening_line=notices,
        call_is_recorded=True,
    )


def _start(cfg: AgentConfig) -> str:
    return dict(engine_prompt_layers(cfg)).get("notices", "")


# --- the prompt ---------------------------------------------------------------------------


def test_the_prompt_quotes_the_exact_opening_already_spoken_and_says_to_go_on() -> None:
    for direction in ("inbound", "outbound", "both"):
        cfg = _cfg(direction)
        start = _start(cfg)
        spoken = compose_first_utterance(cfg)
        assert spoken == f"{OPENING} {NOTICE}", "greeting first, then the notice (D-861)"
        assert start.startswith(
            f'{START_OF_CALL_HEADER}\nAlready said for you as your first turn: "{spoken}".'
        )
        assert OPENING_CONTINUES_RULE in start
        prompt = compose_engine_prompt(cfg)
        # The publish read-back's containment check on the notices still holds, and the
        # truthful-answer block still binds after it.
        assert NOTICE in prompt
        assert prompt.rindex(TRUTHFUL_ANSWER_MARKER) > prompt.index(START_OF_CALL_HEADER)
    rule = OPENING_CONTINUES_RULE
    assert "Never greet again" in rule and "ask again if now is a good time" in rule
    assert '("hello", "yes", in any language)' in rule
    assert "why you are calling or your first question" in rule


def test_who_is_calling_no_longer_asks_whether_now_suits() -> None:
    assert "good time" not in WHO_IS_CALLING_RULE
    assert WHO_IS_CALLING_RULE in _start(_cfg("both"))
    assert WHO_IS_CALLING_RULE not in _start(_cfg("outbound"))


def test_with_no_notice_the_opening_alone_is_quoted_and_with_neither_nothing() -> None:
    assert f'"{OPENING}".' in _start(_cfg(notices=""))
    bare = _cfg(notices="").model_copy(update={"system_prompt": "Be kind."})
    assert _start(bare) == ""


def test_what_the_section_costs() -> None:
    """Printed for the decision row; the budgets themselves are `agent_prompt_budget_test`."""
    start = _start(_cfg("both"))
    spoken = compose_first_utterance(_cfg("both"))
    print(f"START OF THE CALL: {len(start)} chars, of which the quoted opening {len(spoken)}")
    assert len(start) - len(spoken) < 500


# --- the turn check -----------------------------------------------------------------------


def test_the_calls_second_greeting_and_second_can_you_talk_are_caught() -> None:
    greeted = [Turn(said="Hello.", reply="నమస్కారం అండి. మీరు ఇంతకు ముందు")]
    reasked = [
        Turn(
            said="Tell me, tell me, who is it?",
            reply=(
                "Sri Estates నుంచి అండి. మీరు ఇంతకు ముందు మా వెబ్‌సైట్‌లో ప్రాపర్టీ గురించి "
                "ఎంక్వైరీ చేశారు కదా. మీకు ఇప్పుడు మాట్లాడటం కుదురుతుందా అండి?"
            ),
        )
    ]
    assert [p.kind for p in conversation_problems(greeted)] == ["opened_again"]
    # The same reply also told the caller they had enquired on the website, which nothing
    # on that call said (D-888).
    assert [p.kind for p in conversation_problems(reasked)] == ["opened_again", "invented_source"]
    assert "opened_again" in SOUND_KINDS


def test_going_on_after_hello_passes_and_only_the_first_reply_is_judged() -> None:
    good = Turn(
        said="హలో.",
        reply="మీరు మా వెబ్‌సైట్‌లో ప్రాపర్టీ గురించి అడిగారు కదా, ఏ ఏరియాలో చూస్తున్నారు?",
    )
    assert opened_again(good.reply) is None
    later = Turn(said="ఓకే, బై.", reply="సరే అండి, నమస్కారం.")
    assert conversation_problems([good, later]) == []
    assert opened_again("Hello! How can I help?") is not None
    assert opened_again("Is this a good time to talk?") is not None
    assert opened_again("अभी बात कर सकते हैं?") is not None
    assert opened_again("Hi-tech City లో ఉంది అండి.") is None


def test_the_hello_caller_is_a_standing_practice_test() -> None:
    cls = next(c for c in CLASSES if c.key == "specimen_hello_after_opening")
    scenario = scenario_of(cls, "te-IN", "real_estate")
    assert scenario.turns == ("హలో.",)
    assert "Never greets again" in scenario.expect
    checked = hard_check(
        scenario, [Turn(said="హలో.", reply="నమస్కారం అండి, ఎలా ఉన్నారు?")], language="te-IN"
    )
    assert checked.verdict != "failed", "a sound note, never the verdict (D-828)"
    assert "opened_again" in {p.kind for p in checked.sounds}


# --- the opening in the language's own letters (D-861) ------------------------------------

CALL_OPENING = "నమస్కారం అండి, Sri Estates నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?"


def test_english_letters_in_a_written_opening_are_caught_but_names_are_kept() -> None:
    names = ("Sri Estates", "Anjali")
    assert latin_words(CALL_OPENING, "te-IN", names=names) == ["call"]
    assert latin_words(OPENING, "te-IN", names=names) == []
    assert latin_words("Hello, Sri Estates here. Can we talk?", "en-IN") == []
    assert latin_words("नमस्ते, मैं Anjali, call कर रही हूँ?", "hi-IN", names=names) == ["call"]
    problem = latin_word_problem("opening_line", CALL_OPENING, "te-IN", names=names)
    assert problem is not None and "“call”" in problem


def test_the_first_runs_greeting_rule_refuses_english_letters() -> None:
    names = ("Sri Estates", "Anjali")
    assert not greeting_fits(CALL_OPENING, "te-IN", names=names)
    assert greeting_fits(CALL_OPENING.replace("call", "కాల్"), "te-IN", names=names)


def test_the_script_writers_opening_is_sent_back_for_english_letters() -> None:
    written = CallScript(schema_version=2, opening_line=CALL_OPENING)
    problems = language_problems(written, "te-IN", names=("Sri Estates",))
    assert any(p.startswith("opening_line: writes “call”") for p in problems)
    fixed = written.model_copy(update={"opening_line": CALL_OPENING.replace("call", "కాల్")})
    assert not any(
        "English letters" in p for p in language_problems(fixed, "te-IN", names=("Sri Estates",))
    )
    # The owner's own line, kept by a conversion, is theirs.
    assert not any(
        "English letters" in p
        for p in language_problems(written, "te-IN", allowed=CALL_OPENING, names=())
    )
