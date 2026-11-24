"""The conversation rules every agent carries after the founder's Rytu Khata campaign call of
23 Nov 2026: a step taken as done on a reply that did not say so ("Friday"), an answer to a
question the caller never asked with a reassurance no fact held, a long cut-off turn, replies
that all opened and ended alike, and a step's check said for the caller instead of asked."""

from __future__ import annotations

import pytest
from apps.api.agents.live_apply import platform_prompt_revision
from calevate_shared import call_script, engine
from calevate_shared.call_script import (
    OUTCOMES_LEAD,
    PROCEDURE_LEAD,
    SCENARIO_LEAD,
    CallScript,
    ConversationStage,
    ProcedureStep,
    ScenarioQa,
    StepOutcome,
    compile_call_script,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_RULE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    truthful_answer_directive,
)
from calevate_shared.spoken_guard import has_indic_letters

#: One clause per fault, as every agent's prompt says it.
SPEAKING_RULES = (
    # A turn carries one point: the cut-off reply answered two things and began a third.
    "Say one thing a turn, one instruction or one question, in one or two short sentences, "
    "then stop.",
    # Only what was asked is answered.
    "Answer just what they asked.",
    # No acknowledgement or closing words used reply after reply.
    "React only when it fits, and never begin or end two replies alike.",
    # A reply off the point (a misheard "Friday") is asked about, never guessed at.
    "- If a reply is unclear, cut off or no answer to you, never guess or move on: ask once, "
    "briefly, in other words.",
    # A step's result is asked for, never asserted for them.
    "A step is done only when they say so or say what they see.",
)


def _config(direction: str, body: str = "Help them.", **extra: object) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "tenant_id": "t",
            "agent_id": "a",
            "name": "A",
            "business": "B",
            "direction": direction,
            "language_primary": "te-IN",
            "system_prompt": body,
            "opening_line": "",
            "call_is_recorded": True,
            **extra,
        }
    )


def _guided_script() -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[
            ConversationStage(
                id="open",
                name="Open the app",
                instruction="Help them open the app.",
                step=1,
                procedure=[
                    ProcedureStep(action="Ask them to open the app.", wait_for="It is open")
                ],
                scripts={"en-IN": "Let us open the app together."},
                qa=[ScenarioQa(question="Is it free?", answer="Yes, it is free.")],
            )
        ],
        step_outcomes=[StepOutcome(step=1, outcome="They have seen the app's main screen.")],
    )


@pytest.mark.parametrize("direction", ["inbound", "outbound", "both"])
@pytest.mark.parametrize("screen", [False, True])
def test_every_agent_carries_the_rules(direction: str, screen: bool) -> None:
    prompt = compose_engine_prompt(_config(direction, caller_has_screen=screen))
    for rule in SPEAKING_RULES:
        assert prompt.count(rule) == 1, (direction, screen, rule)
    # A reassurance is one of the things never said without a fact behind it.
    assert "how such businesses work, a reassurance or how they found you." in prompt


def test_a_job_scripts_steps_outcomes_and_answers_say_when_to_move_on() -> None:
    body = compile_call_script(_guided_script())
    prompt = compose_engine_prompt(_config("outbound", body))
    # A step moves on only on a reply that meets its Wait for; anything else is asked about.
    assert "Go to the next only when what they say meets its Wait for" in PROCEDURE_LEAD
    # An outcome is reached by what the person says, and a look-and-see one is asked for.
    assert "only when what they say shows the outcome, never assumed or said" in OUTCOMES_LEAD
    assert "if it needs them to look or do something, ask and wait" in OUTCOMES_LEAD
    # A scenario's answer is given only to its own question.
    assert "give an answer only when they ask its question." in SCENARIO_LEAD
    for lead in (PROCEDURE_LEAD, OUTCOMES_LEAD, SCENARIO_LEAD):
        assert lead in prompt, lead


@pytest.mark.parametrize("name", ["PROCEDURE_LEAD", "OUTCOMES_LEAD", "SCENARIO_LEAD"])
def test_each_script_lead_moves_the_platform_revision(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job's script is compiled at every publish, so a lead reaches live agents only when
    the revision the platform walk keys on moves with it."""
    before = platform_prompt_revision()
    monkeypatch.setattr(call_script, name, getattr(call_script, name) + " x")
    assert platform_prompt_revision() != before


def test_the_speaking_rules_move_the_platform_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    before = platform_prompt_revision()
    monkeypatch.setattr(engine, "VOICE_STYLE_GUIDANCE", VOICE_STYLE_GUIDANCE + " x")
    assert platform_prompt_revision() != before


def test_the_rules_are_english_name_no_business_and_no_stock_words() -> None:
    for rule in (*SPEAKING_RULES, PROCEDURE_LEAD, OUTCOMES_LEAD, SCENARIO_LEAD):
        assert not has_indic_letters(rule), rule
        assert "Rytu" not in rule and "farm" not in rule.lower()
    # A word named in a prompt comes back more often, so the variety rule names none.
    assert not has_indic_letters(VOICE_STYLE_GUIDANCE)


def test_the_locked_blocks_are_unchanged_and_still_last() -> None:
    prompt = compose_engine_prompt(_config("outbound", compile_call_script(_guided_script())))
    truthful = truthful_answer_directive(call_is_recorded=True)
    assert CONFIDENTIALITY_RULE in prompt and truthful in prompt
    assert prompt.index(VOICE_STYLE_GUIDANCE) < prompt.index(CONFIDENTIALITY_RULE)
    assert prompt.index(CONFIDENTIALITY_RULE) < prompt.index(truthful)
