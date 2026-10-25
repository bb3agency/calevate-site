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
    TEST_CALL_OPENING_RULE,
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
    # The whole opening, quoted as spoken: greeting, then the notices (D-861, D-864).
    assert f'first turn: "{OPENING} {NOTICES}".' in start
    assert "Never greet again, repeat it or ask again if now is a good time." in start
    prompt = compose_engine_prompt(cfg)
    # The publish read-back scores containment of the notices (`agents/verification`), and a
    # caller who asks is still answered by the block that binds last.
    assert NOTICES in prompt
    assert prompt.rindex(TRUTHFUL_ANSWER_MARKER) > prompt.index(START_OF_CALL_HEADER)


def test_every_word_and_amount_is_written_in_the_languages_letters() -> None:
    """D-861 (founder, 23 Oct 2026): a Telugu agent writes English words and amounts in
    Telugu letters, amounts the English way, and learns where to breathe from the examples."""
    register = _layer(_cfg(), "spoken_register")
    assert "every word in Telugu letters, English words too" in register
    assert "English letters" not in register
    assert "ఓకే అండి, డెలివరీ. మీది ఏ ఏరియా?" in register
    assert '"వన్ ట్వంటీ రూపీస్", "టూ క్రోర్స్"' in VOICE_STYLE_GUIDANCE


def test_an_answering_agent_is_told_its_test_call_opens_another_way() -> None:
    """D-861: on a trial test call the engine speaks a calling-you line in place of the
    [OPENING] line, and a model told only that its [OPENING] line was said greeted with it
    after the owner's "Hello". An agent that calls out has no such call."""
    inbound = _cfg()
    assert TEST_CALL_OPENING_RULE in _layer(inbound, "notices")
    outbound = inbound.model_copy(update={"direction": "outbound"})
    assert TEST_CALL_OPENING_RULE not in _layer(outbound, "notices")
    assert TEST_CALL_OPENING_RULE not in _layer(_cfg(opening=""), "notices")


def test_an_agent_with_only_one_of_them_is_told_about_that_one() -> None:
    assert f'"{OPENING}".' in _layer(_cfg(notices=""), "notices")
    assert NOTICES not in _layer(_cfg(notices=""), "notices")
    alone = _layer(_cfg(opening=""), "notices")
    assert f'"{NOTICES}".' in alone and OPENING not in alone
    assert _layer(_cfg(notices="", opening=""), "notices") == ""


def test_the_chat_hears_the_honesty_rules_the_call_rules_would_have_given() -> None:
    assert "Never re-ask what they said or repeat a sentence." in VOICE_STYLE_GUIDANCE
    assert "booked, fixed, confirmed or done unless a tool" in ACTION_CLAIM_RULE
    assert "say it is noted and the team will confirm" in ACTION_CLAIM_RULE
    assert "what happens next" not in ACTION_CLAIM_RULE
    prompt = compose_engine_prompt(_cfg())
    assert (
        'No answer after searching ("the team will share that"), or still unclear after '
        "two tries: say so, then" in prompt
    )


# --- what counts as a claim -------------------------------------------------------------


def test_noting_what_the_caller_asked_is_no_claim_but_placing_or_booking_is() -> None:
    """Founder, 21 Oct 2026: "noted" is true, because the post-call reading records it."""
    assert not claims_done("సరే అండి, అర కేజీ కారం పొడి నోట్ చేసుకున్నాను.")
    assert not claims_done("మీ details రాసుకున్నాను.")
    assert not claims_done("OK, noted the order for one kg chilli powder.")
    assert claims_done("సరే అండి, మీ order place చేశాను.")
    assert claims_done("మీ booking confirm అయింది.")
    assert claims_done("OK, I've placed your order.")
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
    assert "says an order or booking is placed, booked, fixed or confirmed" in IMPROVE_INSTRUCTION
    assert "only those the caller has not already said" in _SYSTEM_INSTRUCTION
    assert "takes the details for the team to confirm" in _SYSTEM_INSTRUCTION
    products = next(
        s for s in standard_scenarios("te-IN", "inbound") if s.key == "asks_about_products"
    )
    assert "the team will confirm it" in products.expect
