"""The two Studio calls of 21 Oct 2026 on a Telugu chilli shop, held as a golden set (D-849).

Call 2 opened with a Telugu greeting, the caller said "Hello", and the agent went on in English
until asked to speak Telugu. It finished the caller's broken-off "ఒక" as "one kg", said
"noted" (which is fine: the post-call reading records it), said "I told you the price is six
hundred rupees, right?"
about a price it had never said, and call 1 ended on a doubled goodbye. Every check here is
deterministic: the composed prompt carries each rule, the reply checks catch each break, and
the four AI writers and the judge read one rule list.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from apps.api.agents.call_rules import (
    CALL_RULES,
    OPENING_LINE_MAX_CHARS,
    OPENING_LINE_RULE,
    said_line_problem,
)
from apps.api.agents.script_edits import ScriptEdit, language_problem
from apps.api.agents.test_conversations import Scenario, Turn, hard_check, missing_facts
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    claims_said_before,
    conversation_problems,
    turn_problems,
)
from apps.api.db.session import tenant_session
from apps.api.teach import pinned
from apps.workers.agent_test_ai import GENERATE_INSTRUCTION, IMPROVE_INSTRUCTION, JUDGE_INSTRUCTION
from apps.workers.script_assist import (
    _SYSTEM_INSTRUCTION,
    EDIT_INSTRUCTION,
    language_problems,
)
from calevate_shared.call_script import CallScript, ExampleLine, compile_call_script
from calevate_shared.engine import AgentConfig, compose_engine_prompt, engine_prompt_layers
from calevate_shared.spoken_style import PackChoice
from tests.kb_workflow_test import _tenant_with_published_agent

TE = "te-IN"
GREETING = (
    "నమస్కారం అండి, Raghava Organics నుండి మాట్లాడుతున్నాను. మేము పూర్తిగా రసాయనాలు లేకుండా, "
    "natural పద్ధతిలో పండించిన ఎండు మిర్చి మరియు కారం పొడి అమ్ముతాము. మీకు ఎలా సహాయపడగలను?"
)


@dataclass(frozen=True)
class _X:
    said: str
    reply: str
    tools: tuple[str, ...] = ()


CALL_1 = (
    _X(
        "ఎండుమిర్చి అంటే ఏంటిది?",
        "అది natural గా, chemicals లేకుండా పండించిన మిర్చి అండి. మీకు ఎన్ని kg ల ఎండు మిర్చి కావాలి?",
    ),
    _X("నాకొక", "ఒక కేజీ ఎండు మిర్చి అండి. ఇంటికి డెలివరీ కావాలా, లేక మీరే వచ్చి తీసుకుంటారా?"),
    _X(
        "రెండు కేజీలు కావాలండి.",
        "రెండు కేజీల ఎండు మిర్చి నోట్ చేసుకున్నాను. ఇది మీకు ఇంటికి డెలివరీ కావాలా, లేక మీరే వచ్చి తీసుకుంటారా?",
    ),
    _X("ఇంటికి కావాలండి.", "మీది ఏ ఏరియా అండి?"),
    _X("గుంటూరు గుంటూరులో ఉంటాం", "గుంటూరులో డెలివరీ చేస్తాం. మీకు ఎండు మిర్చి ధర తెలుసుకోవాలని ఉందా అండి?"),
    _X(
        "ఓకే ఓకే చాలండి చాలు చాలు ఇంకా పెట్టేయండి.",
        "మంచిది అండి, మీకు కావాల్సిన వస్తువులను నోట్ చేసుకున్నాను, thanks అండి. మంచిది అండి, thanks అండి.",
    ),
)

CALL_2 = (
    _X("Hello", "Hello. How can I help you with our natural chilli or chilli powder today?"),
    _X("తెలుగులో మాట్లాడగలరా?", "తప్పకుండా అండి. మీకు ఎండు మిర్చి కావాలా, కారం పొడి కావాలా?"),
    _X("ఇవన్నీ కాదు కానీ. ఏమున్నాయి మీ దగ్గర?", "మా దగ్గర ఎండు మిర్చి, కారం పొడి ఉన్నాయి అండి."),
    _X("మాకు", "మీకు ఎండు మిర్చి కావాలా, కారం పొడి కావాలా అండి?"),
    _X("కారం పొడి కావాలండి ఒక", "ఒక కేజీ కారం పొడి కావాలన్నమాట. ఇంటికి డెలివరీ కావాలా, లేక మీరే వచ్చి తీసుకుంటారా?"),
    _X(
        "ఒక అర కేజీ కావాలి.",
        "అర కేజీ కారం పొడి నోట్ చేసుకున్నాను. ఇంటికి డెలివరీ కావాలా, లేక మీరే వచ్చి తీసుకుంటారా?",
    ),
    _X(
        "ఇంటికి డెలివరీ చేయండి, గుంటూరులో ఉంటాం.",
        "గుంటూరుకు డెలివరీ చేస్తాం. అర కేజీ కారం పొడి ధర ఆరు వందల రూపాయలు అని మీకు చెప్పాను కదా, "
        "మీ order కి ఇంకేమైనా కావాలా?",
    ),
)


def _kinds_of_reply(x: _X) -> set[str]:
    return {p.kind for p in turn_problems(x.reply, caller_said=x.said, language=TE)}


def _cfg(*, pack: bool = False) -> tuple[AgentConfig, PackChoice | None]:
    script = CallScript(
        schema_version=2,
        business_line="Raghava Organics sells natural red chilli and chilli powder.",
        opening_line="నమస్కారం అండి, Raghava Organics నుంచి, ఏం కావాలి చెప్పండి?",
    )
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Raghava Organics receptionist",
        business="Raghava Organics",
        direction="inbound",
        language_primary=TE,
        system_prompt=compile_call_script(script),
        opening_line="నేను AI assistant ని. ఈ call record అవుతోంది.",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )
    return cfg, (PackChoice(form="en", avoid="list") if pack else None)


# --- 1. the greeting does not switch the language ----------------------------------------


def test_hello_after_a_telugu_greeting_answered_in_english_is_caught() -> None:
    hello = CALL_2[0]
    problems = turn_problems(hello.reply, caller_said=hello.said, language=TE)
    switched = [p for p in problems if p.kind == "wrong_language"]
    assert switched and "only said" in switched[0].reason and "Telugu" in switched[0].reason
    # A real English sentence is the caller's switch to make, and Telugu stays right.
    assert "wrong_language" not in _kinds_of_reply(
        _X(
            "Can you tell me the price of chilli powder please?",
            "Sure, it is for the team to confirm.",
        )
    )
    assert "wrong_language" not in _kinds_of_reply(_X("Hello", "హా అండి, చెప్పండి, ఏం కావాలి?"))


@pytest.mark.parametrize("pack", [False, True])
def test_every_prompt_says_a_greeting_is_no_switch(pack: bool) -> None:
    cfg, choice = _cfg(pack=pack)
    speak = dict(engine_prompt_layers(cfg, pack=choice))["how_to_speak"]
    assert '"Hello", "OK" or a word or two is no switch' in speak
    assert "keep the language you greeted in" in speak


# --- 2. fabrication ------------------------------------------------------------------------


def test_the_price_it_never_said_is_a_false_recall_and_fails_the_test() -> None:
    kinds = [p.kind for p in conversation_problems(CALL_2)]
    assert "false_recall" in kinds and "false_recall" in JOB_KINDS
    turns = [Turn(said=x.said, reply=x.reply) for x in CALL_2]
    check = hard_check(
        Scenario(key="k", title="Orders powder", category="business", turns=("x",), expect=""),
        turns,
        language=TE,
    )
    assert check.verdict == "failed" and "had not said that earlier" in (check.reason or "")


def test_a_price_it_did_say_may_be_recalled() -> None:
    said = (
        _X("కారం పొడి ధర ఎంత?", "అర కేజీ six hundred rupees అండి."),
        _X("సరే.", "నేను చెప్పాను కదా, six hundred rupees, ఇంకేమైనా కావాలా?"),
    )
    assert "false_recall" not in [p.kind for p in conversation_problems(said)]


def test_said_before_phrases() -> None:
    assert claims_said_before("ధర ఆరు వందల రూపాయలు అని మీకు చెప్పాను కదా")
    assert claims_said_before("ముందే చెప్పాను అండి")
    assert claims_said_before("As I told you, it is six hundred rupees.")
    assert claims_said_before("मैंने पहले ही बताया था")
    assert not claims_said_before("మీరు చెప్పినట్టు గుంటూరుకు పంపిస్తాం.")
    assert not claims_said_before("ధర చెప్పమంటారా?")


def test_noting_what_the_caller_asked_is_not_flagged_on_either_call() -> None:
    """Founder, 21 Oct 2026: "నోట్ చేసుకున్నాను" is true (the post-call reading records it)."""
    for call in (CALL_1, CALL_2):
        assert "unconfirmed_action" not in [p.kind for p in conversation_problems(call)]


def test_finishing_the_callers_broken_off_number_is_their_part() -> None:
    for x in (CALL_1[1], CALL_2[4]):
        problems = turn_problems(x.reply, caller_said=x.said, language=TE)
        assert any(p.kind == "caller_line" and "broke off" in p.reason for p in problems)
    # The caller said the whole quantity: repeating it back is right.
    assert "caller_line" not in _kinds_of_reply(_X("ఒక కేజీ కావాలి.", "ఒక కేజీ, సరే అండి."))


def test_a_short_go_on_is_the_answer_to_a_cut_line() -> None:
    for said in ("నాకొక", "మాకు", "కారం పొడి కావాలండి ఒక"):
        assert _kinds_of_reply(_X(said, "చెప్పండి అండి.")) == set(), said
    # Call 2 answered the cut "మాకు" by asking its question again.
    problems = turn_problems(CALL_2[3].reply, caller_said=CALL_2[3].said, language=TE)
    assert any(p.kind == "too_long" and "stopped mid-sentence" in p.reason for p in problems)
    # A bare number answering "how many?" is a whole answer.
    assert _kinds_of_reply(_X("రెండు", "రెండు కేజీలు, సరే అండి. ఇంటికి delivery కావాలా?")) == set()
    # Offering a reading of the cut number as one short question is the right move (D-856).
    offer = "ఒక కేజీ కావాలా అండి, ఇంకా ఎక్కువా?"
    for said in ("నాకొక", "కారం పొడి కావాలండి ఒక"):
        assert _kinds_of_reply(_X(said, offer)) == set(), said
    # Taking the guess and moving on is still finishing their sentence.
    guessed = "సరే అండి, ఒక కేజీ కారం పొడి. ఇంటికి delivery కావాలా?"
    assert "caller_line" in _kinds_of_reply(_X("కారం పొడి కావాలండి ఒక", guessed))
    cfg, _ = _cfg()
    assert "Half an answer? Offer your reading as a question" in compose_engine_prompt(cfg)


def test_the_double_goodbye_is_noted() -> None:
    problems = turn_problems(CALL_1[-1].reply, caller_said=CALL_1[-1].said, language=TE)
    assert any(p.kind == "repeated_turn" and "twice in one reply" in p.reason for p in problems)


def test_the_prompt_carries_the_fabrication_rules() -> None:
    cfg, _ = _cfg()
    prompt = compose_engine_prompt(cfg)
    assert 'Never say "as I said" about what you did not say' in prompt
    assert "Say only what your facts or the caller said, never a guess: a place" in prompt
    assert "Read back what you heard" in prompt and "Read back what you note" not in prompt
    assert "then one goodbye" in prompt


# --- cost: our block is the same on every turn --------------------------------------------


def test_our_block_is_byte_identical_and_holds_no_per_call_value_before_this_call() -> None:
    """The engine holds the instructions as agent state, written at publish
    (`engine/thinnest._agent_body`), so they are the same on every reply; this pins that the
    composition itself has no clock, counter or random part, and that a per-call value sits
    only in the client's own script or the last layer (D-814)."""
    cfg, _ = _cfg()
    cfg = cfg.model_copy(update={"forwarded_line": True})
    assert compose_engine_prompt(cfg) == compose_engine_prompt(cfg)
    layers = engine_prompt_layers(cfg)
    assert layers[-1][0] == "this_call" and "{{" in layers[-1][1]
    for name, text in layers[:-1]:
        assert "{{" not in text or name == "client_script", name


# --- 4. one rule list for the writers and the judge ------------------------------------------


def test_every_writer_and_the_judge_read_the_same_rules() -> None:
    cfg, _ = _cfg()
    prompt = compose_engine_prompt(cfg)
    for rule in CALL_RULES:
        assert rule.judge in JUDGE_INSTRUCTION, rule.key
        for writer in (_SYSTEM_INSTRUCTION, EDIT_INSTRUCTION, IMPROVE_INSTRUCTION):
            assert rule.writer in writer, rule.key
        if rule.expect:
            assert rule.expect in GENERATE_INSTRUCTION, rule.key
        assert rule.prompt_marker in prompt, rule.key
    for writer in (_SYSTEM_INSTRUCTION, EDIT_INSTRUCTION, IMPROVE_INSTRUCTION):
        assert OPENING_LINE_RULE in writer


def test_the_173_character_greeting_is_sent_back_to_the_writer() -> None:
    assert len(GREETING) > OPENING_LINE_MAX_CHARS
    problem = said_line_problem("opening_line", GREETING, opening=True)
    assert problem is not None and "at most 120 characters" in problem
    short = "నమస్కారం అండి, Raghava Organics కి call చేసినందుకు thanks. చెప్పండి, ఏం కావాలి?"
    assert said_line_problem("opening_line", short, opening=True) is None
    draft = CallScript(
        schema_version=2,
        opening_line=short,
        example_exchange=[
            ExampleLine(speaker="caller", text="రెండు కేజీలు కావాలి."),
            ExampleLine(speaker="agent", text="రెండు కేజీలు order place చేశాను అండి."),
        ],
    )
    problems = language_problems(draft, TE)
    assert any("example_exchange.1.text" in p and "team will confirm" in p for p in problems)
    # The owner's own long greeting, kept by a conversion, is theirs.
    kept = language_problems(
        CallScript(schema_version=2, opening_line=GREETING),
        TE,
        allowed=GREETING,
        instructions=False,
    )
    assert not [p for p in kept if "characters" in p]


def test_the_improver_may_not_write_a_long_or_claiming_opening() -> None:
    # The founder's greeting with its textbook words spoken, so only its length is left.
    spoken = GREETING.replace("మరియు", "ఇంకా").replace("అమ్ముతాము", "అమ్ముతాం")
    edit = ScriptEdit(id="e1", op="set_part", part="opening_line", text=spoken)
    found = language_problem(edit, CallScript(schema_version=2), TE, where="edits.0.text")
    assert found is not None and "characters" in found


# --- 4d. the owner hears about missing prices before the first run ---------------------------


async def test_missing_prices_are_named_until_a_fact_gives_one() -> None:
    tenant_id, _agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        assert await missing_facts(session) == ["prices"]
        await pinned.add_pinned(
            session,
            tenant_id=tenant_id,
            question="కారం పొడి ధర?",
            answer="Half kg chilli powder is ₹600.",
            origin="quick_fact",
            created_by=None,
        )
    async with tenant_session(tenant_id) as session:
        assert await missing_facts(session) == []
