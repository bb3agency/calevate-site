"""The founder's Rytu Khata test call of 28 Oct 2026 (D-920).

Agent "Sindhu", Telugu, jobs answer calls + call new leads + campaigns, so direction `both`.
The agent rang the founder and opened with its answering greeting, "thanks for calling, what
do you need?", then greeted a second time after his "Hello.". A "both" agent now opens every
call it places with its own outbound opening, and the prompt quotes both first turns.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.agents.engine_limits import refuse_opening_over_limit
from apps.api.agents.prompt_size import SCRIPT_SECTION_LABELS
from apps.api.agents.service import dial_first_words
from apps.api.agents.test_conversations import Turn
from apps.api.agents.turn_checks import conversation_problems, turn_problems
from apps.api.core.errors import ProblemError
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.workers.script_assist import UnusableAnswerError, drafted_script, language_problems
from calevate_shared.call_script import (
    OUTBOUND_OPENING_HEADER,
    CallScript,
    compile_call_script,
    opening_line_of,
    outbound_opening_of,
)
from calevate_shared.engine import (
    OPENING_CONTINUES_RULE,
    START_OF_CALL_HEADER,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    CallContext,
    DisclosurePosture,
    compose_engine_prompt,
    compose_first_utterance,
    compose_placed_call_first_words,
    engine_prompt_layers,
)
from calevate_shared.spoken_style import opening_in, placed_call_opening

ANSWERING = "కాల్ చేసినందుకు థాంక్స్. చెప్పండి, ఏం కావాలి?"
AI_NOTICE = "నేను Rytu Khata నుండి Sindhuని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి."
OWN_PLACED = "మీరు మా వెబ్‌సైట్‌లో Rytu Khata గురించి అడిగారు, దాని గురించే కాల్ చేశాను. ఇప్పుడు మాట్లాడొచ్చా?"
THANKS = "థాంక్స్"


def _script(placed: str = "") -> str:
    return compile_call_script(
        CallScript(schema_version=2, opening_line=ANSWERING, outbound_opening_line=placed)
    )


def _row(direction: str = "both", placed: str = "") -> dict[str, Any]:
    return {
        "direction": direction,
        "name": "Sindhu",
        "language_primary": "te-IN",
        "business_name": "Rytu Khata",
        "prompt": _script(placed),
        "ai_disclosure_line": AI_NOTICE,
        "ai_disclosure_enabled": True,
        "recording_notice_line": "ఈ call record అవుతుంది.",
        "recording_notice_enabled": False,
        "caller_memory_notice_line": "",
        "caller_memory_enabled": False,
    }


def _cfg(direction: str = "both", placed: str = "") -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Sindhu",
        business="Rytu Khata",
        direction=direction,  # type: ignore[arg-type]
        language_primary="te-IN",
        system_prompt=_script(placed),
        opening_line=AI_NOTICE,
        ai_notice=AI_NOTICE,
        call_is_recorded=True,
    )


# --- what the person rung hears first ------------------------------------------------------


def test_a_both_agent_never_thanks_the_person_it_rang_for_calling() -> None:
    for test_call in (False, True):
        said = dial_first_words(_row(), test_call=test_call, call_is_recorded=True)
        assert said is not None
        assert THANKS not in said and "ఏం కావాలి" not in said
        # The AI notice still introduces it (hard rule 5's disclosure, D-163, D-865), and the
        # line after it is the language's placed-call question.
        assert AI_NOTICE in said
        introduced = opening_in("te-IN", "outbound", introduced=True)
        assert introduced is not None
        assert said.endswith(introduced.replace("{business}", "Rytu Khata"))


def test_its_own_outbound_opening_is_said_when_it_has_one() -> None:
    said = dial_first_words(_row(placed=OWN_PLACED), test_call=False, call_is_recorded=True)
    assert said is not None and said.endswith(OWN_PLACED) and AI_NOTICE in said


def test_agents_of_one_direction_keep_their_first_words() -> None:
    # An outbound agent's greeting is its opening; an answering agent rings out only on a test.
    assert dial_first_words(_row("outbound"), test_call=True, call_is_recorded=True) is None
    assert dial_first_words(_row("inbound"), test_call=False, call_is_recorded=True) is None
    test_line = dial_first_words(_row("inbound"), test_call=True, call_is_recorded=True)
    assert test_line is not None and THANKS not in test_line


@pytest.mark.parametrize("language", ["te-IN", "hi-IN", "en-IN"])
def test_every_offered_language_has_a_placed_call_line(language: str) -> None:
    for introduced in (False, True):
        line = placed_call_opening(language, business="Rytu Khata", introduced=introduced)
        assert line and line.rstrip().endswith("?")
        # Who is calling first; after an introduction, why (D-945), which in Telugu and
        # Hindi is the founder's "we are calling from" half until a reason line is written.
        assert introduced or "Rytu Khata" in line
    # No business name known: the question alone, never a gap where the name goes.
    blank = placed_call_opening(language, business=" ")
    assert blank.endswith("?") and "{business}" not in blank and "  " not in blank
    assert "Rytu Khata" not in blank


async def test_the_dial_sends_it_as_purpose_with_the_persons_name_filled() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"id": "out_1", "status": "ringing"})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": "Bearer ta_live_test"},
            transport=httpx.MockTransport(handler),
        ),
    )
    ctx = CallContext(lead_name="రాము", opening="నమస్కారం {{lead_name}} గారు, మాట్లాడొచ్చా?")
    await engine.start_outbound_call("ag_1", "+919876543210", ctx)
    body = json.loads(seen[-1].content)
    assert body["purpose"] == "నమస్కారం రాము గారు, మాట్లాడొచ్చా?"
    # The agent's greeting is not read: the dial brings its own first words.
    assert all(r.method == "POST" for r in seen)


# --- what the model is told was said -------------------------------------------------------


def test_the_prompt_says_which_first_turn_was_said_on_which_call() -> None:
    cfg = _cfg()
    start = dict(engine_prompt_layers(cfg))["notices"]
    answered = compose_first_utterance(cfg)
    placed = compose_placed_call_first_words(cfg)
    assert placed is not None and THANKS not in placed
    assert start.startswith(
        f"{START_OF_CALL_HEADER}\nAlready said for you as your first turn: on a call you "
        f'answer, "{answered}"; on a call you place, "{placed}".'
    )
    assert OPENING_CONTINUES_RULE in start
    prompt = compose_engine_prompt(cfg)
    assert prompt.rindex(TRUTHFUL_ANSWER_MARKER) > prompt.index(START_OF_CALL_HEADER)
    # One direction: only its one first turn, exactly as before.
    for direction in ("inbound", "outbound"):
        assert compose_placed_call_first_words(_cfg(direction)) is None
        one = dict(engine_prompt_layers(_cfg(direction)))["notices"]
        assert "on a call you place" not in one


def test_the_second_greeting_after_hello_is_noted_against_the_placed_opening() -> None:
    placed = compose_placed_call_first_words(_cfg())
    assert placed is not None
    second = Turn(
        "Hello.",
        "నమస్కారం అండి. మీరు ఇంతకు ముందు మా దగ్గర ఎంక్వైరీ చేశారు కదా, దానికి సంబంధించి మీకు ఇంకా సహాయం కావాలా అండి?",
    )
    kinds = [p.kind for p in conversation_problems([second], opening=placed)]
    assert "opened_again" in kinds


# --- where the line is kept and checked ----------------------------------------------------


def test_the_script_keeps_both_lines_apart() -> None:
    body = _script(OWN_PLACED)
    assert opening_line_of(body) == ANSWERING
    assert outbound_opening_of(body) == OWN_PLACED
    assert OUTBOUND_OPENING_HEADER in SCRIPT_SECTION_LABELS
    # A script without one compiles exactly as before.
    assert OUTBOUND_OPENING_HEADER not in _script()
    v1 = compile_call_script(CallScript(opening_line=ANSWERING, outbound_opening_line=OWN_PLACED))
    assert outbound_opening_of(v1) == OWN_PLACED


def test_a_placed_opening_over_the_dial_ceiling_is_refused_before_it_is_saved() -> None:
    posture = DisclosurePosture(
        ai_disclosure_line=AI_NOTICE,
        ai_disclosure_enabled=True,
        recording_notice_line="",
        recording_notice_enabled=False,
    )
    engine = ThinnestEngine(api_key="ta_live_test")
    refuse_opening_over_limit(
        engine,
        agent_id="a",
        direction="both",
        posture=posture,
        opening=OWN_PLACED,
        language="te-IN",
        placed=True,
    )
    with pytest.raises(ProblemError) as refused:
        refuse_opening_over_limit(
            engine,
            agent_id="a",
            direction="both",
            posture=posture,
            opening="ఇ" * 400,
            language="te-IN",
            placed=True,
        )
    assert refused.value.code == "engine_greeting_too_long"


def test_the_script_writer_keeps_an_outbound_opening_only_for_a_both_agent() -> None:
    raw = {"opening_line": "", "outbound_opening_line": OWN_PLACED}
    names = ("Rytu Khata", "Sindhu")
    both = drafted_script(raw, language="te-IN", direction="both", names=names)
    assert both.outbound_opening_line == OWN_PLACED
    one = drafted_script(raw, language="te-IN", direction="inbound", names=names)
    assert not one.outbound_opening_line
    # Its letters are judged like the answering line's (D-861): English letters other than
    # the business's and the agent's names send it back.
    with pytest.raises(UnusableAnswerError):
        drafted_script(raw, language="te-IN", direction="both")
    # And held to the opening's length rule.
    long_line = CallScript(schema_version=2, outbound_opening_line="ఇ " * 200)
    assert any(p.startswith("outbound_opening_line") for p in language_problems(long_line, "te-IN"))


def test_a_twelve_word_run_without_a_mark_fails_the_breath_check() -> None:
    """D-921: the founder heard the 6:02 pm call as unpunctuated. Its longest run between marks
    was this twelve-word Play Store line, which the old fourteen-word limit let through."""
    run_on = "సరే అండి, ప్లే స్టోర్ ఓపెన్ చేసి అందులో Rytu Khata అని సెర్చ్ చేస్తే మీకు యాప్ కనిపిస్తుంది."
    marked = "సరే అండి, ప్లే స్టోర్ ఓపెన్ చేయండి. Rytu Khata అని సెర్చ్ చేస్తే, యాప్ కనిపిస్తుంది."
    assert "no_breath" in [p.kind for p in turn_problems(run_on, language="te-IN")]
    assert "no_breath" not in [p.kind for p in turn_problems(marked, language="te-IN")]
