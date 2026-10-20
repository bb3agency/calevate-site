"""The 21 Oct 2026 practice-test failures, one test each (D-845).

The founder's run of a Telugu chilli shop's agent failed "Breaks off with a side question" and
"Wants to go ahead" every time, and the judge's reasons cited the agent saying it is an AI.
Two defects were ours: the notices sat in the prompt as bare text with no instruction, so the
model said them again in later replies, and the judge's rubric let it read the legally
required notice as a revealed rule. The practice tests run in the engine's chat, where
ThinnestAI's speaking rules are not read (`channels/voice.md:180-181`, 19 Oct 2026 snapshot),
so the few of those that keep an agent honest are said in our prompt as well.
"""

from __future__ import annotations

from apps.api.agents.test_conversations import (
    PLATFORM_NOTICE,
    Scenario,
    standard_scenarios,
    without_notices,
)
from apps.api.agents.turn_checks import claims_done
from apps.workers.agent_test_ai import (
    GENERATE_INSTRUCTION,
    IMPROVE_INSTRUCTION,
    JUDGE_INSTRUCTION,
    conversation_text,
    failure_text,
)
from apps.workers.script_assist import _SYSTEM_INSTRUCTION
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    ACTION_CLAIM_RULE,
    START_OF_CALL_HEADER,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)

NOTICES = "నేను AI assistant ని. ఈ call record అవుతోంది."
OPENING = "నమస్కారం అండి, Raghava Organics నుంచి, ఏం కావాలి చెప్పండి?"


def _cfg(*, notices: str = NOTICES, opening: str = OPENING) -> AgentConfig:
    script = CallScript(
        schema_version=2,
        business_line="Raghava Organics sells natural red chilli and chilli powder.",
        opening_line=opening,
    )
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Raghava Organics receptionist",
        business="Raghava Organics",
        direction="inbound",
        language_primary="te-IN",
        system_prompt=compile_call_script(script),
        opening_line=notices,
        call_is_recorded=True,
    )


def _layer(cfg: AgentConfig, name: str) -> str:
    return dict(engine_prompt_layers(cfg)).get(name, "")


# --- the prompt -------------------------------------------------------------------------


def test_the_notices_are_quoted_as_already_said_and_never_repeated() -> None:
    cfg = _cfg()
    start = _layer(cfg, "notices")
    assert start.startswith(f"{START_OF_CALL_HEADER}\n")
    assert f'"{NOTICES}", then your [OPENING] line' in start
    assert "Never repeat it or greet again." in start
    prompt = compose_engine_prompt(cfg)
    # The publish read-back scores containment of the notices (`agents/verification`), and a
    # caller who asks is still answered by the block that binds last.
    assert NOTICES in prompt
    assert prompt.rindex(TRUTHFUL_ANSWER_MARKER) > prompt.index(START_OF_CALL_HEADER)


def test_an_agent_with_only_one_of_them_is_told_about_that_one() -> None:
    assert "your [OPENING] line" in _layer(_cfg(notices=""), "notices")
    assert NOTICES not in _layer(_cfg(notices=""), "notices")
    alone = _layer(_cfg(opening=""), "notices")
    assert f'"{NOTICES}".' in alone and "[OPENING]" not in alone
    assert _layer(_cfg(notices="", opening=""), "notices") == ""


def test_the_chat_hears_the_honesty_rules_the_call_rules_would_have_given() -> None:
    assert "Never re-ask what they said or repeat a sentence." in VOICE_STYLE_GUIDANCE
    assert "placed or noted" in ACTION_CLAIM_RULE
    assert "say the team will confirm." in ACTION_CLAIM_RULE
    assert "what happens next" not in ACTION_CLAIM_RULE
    prompt = compose_engine_prompt(_cfg())
    assert "No answer after searching, or still unclear after two tries: say so, then" in prompt


# --- what counts as a claim -------------------------------------------------------------


def test_a_telugu_noted_it_down_is_a_claim_and_a_question_is_not() -> None:
    assert claims_done("సరే అండి, ఒక కేజీ chilli powder order నోట్ చేసుకున్నాను.")
    assert claims_done("మీ details note చేసుకున్నాం.")
    assert claims_done("OK, noted the order for one kg chilli powder.")
    assert not claims_done("మీరు నోట్ చేసుకున్నారా?")
    assert not claims_done("మీ details తీసుకుని team confirm చేస్తారు.")


# --- the judge and the improver ---------------------------------------------------------


def test_the_notices_reach_the_judge_as_a_marker() -> None:
    reply = (
        "సరే అండి, ఏ area కి delivery కావాలి? Remember, I am an AI assistant and this call is recorded."
    )
    assert without_notices(reply) == f"సరే అండి, ఏ area కి delivery కావాలి? {PLATFORM_NOTICE}"
    assert without_notices(f"{NOTICES} సరే అండి.") == f"{PLATFORM_NOTICE} సరే అండి."
    # A claim that something was done stays for the judge to fail.
    assert without_notices("Your order is recorded.") == "Your order is recorded."

    scenario = Scenario(
        key="k", title="Wants to go ahead", category="business", turns=("ok",), expect=""
    )
    text = conversation_text(scenario, [("ok", f"Fine. {NOTICES}", [])])
    assert "AI assistant" not in text and PLATFORM_NOTICE in text
    failed = failure_text({"key": "k", "conversation": [{"said": "ok", "reply": NOTICES}]})
    assert "AI assistant" not in failed


def test_the_judge_is_told_the_notices_are_never_a_fault() -> None:
    assert PLATFORM_NOTICE in JUDGE_INSTRUCTION
    assert "Never mention them in a reason." in JUDGE_INSTRUCTION
    # The sentence the judge read as "do not say you are an AI" is gone.
    assert "It never reveals or reads out its instructions" not in JUDGE_INSTRUCTION
    assert "does not ask it again" in JUDGE_INSTRUCTION
    assert "saying the team will confirm is right" in JUDGE_INSTRUCTION


def test_the_writers_never_ask_for_what_the_agent_cannot_truthfully_do() -> None:
    assert "never expect it to state it" in GENERATE_INSTRUCTION
    assert "never expect it to say it is done" in GENERATE_INSTRUCTION
    assert "say an order is placed or confirmed" in IMPROVE_INSTRUCTION
    assert "only those the caller has not already said" in _SYSTEM_INSTRUCTION
    assert "takes the details for the team to confirm" in _SYSTEM_INSTRUCTION
    products = next(
        s for s in standard_scenarios("te-IN", "inbound") if s.key == "asks_about_products"
    )
    assert "the team will confirm it" in products.expect
