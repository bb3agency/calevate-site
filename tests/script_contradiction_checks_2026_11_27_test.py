"""Checks before a script goes live, and its size target (founder, 27 Nov 2026).

1. The ending and the closing step disagree on how the person reaches the business
   (production, 27 Nov 2026: the ending said "message us on WhatsApp", the close "call us").
2. A step repeats an earlier step's instruction word for word.
3. A line the agent says in Telugu or Hindi written with none of its letters or with an
   English sentence; an instruction or quick fact written as romanised Telugu (production,
   27 Nov 2026: push-back answers and quick facts in romanised Telugu).
4. All of them warn and never stop Put it live.
5. The size the script screen shows: the script's length, the target and the box.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents import prompt_size, script_checks, script_gate
from apps.api.agents.script_lint import LintContext, contact_channels
from apps.api.engine.hosted_platform import THINNEST_LIMITS
from calevate_shared.call_script import (
    END_OF_CALL,
    CallScript,
    ConversationStage,
    FaqEntry,
    Objection,
    ScenarioQa,
    ScenarioQaText,
    StepExamples,
)
from calevate_shared.engine import AgentConfig

TE = "te-IN"
LINT = LintContext(language=TE, business_name="Rytu Khata")
NEW_CHECKS = ("ending_vs_close", "same_instruction", "own_letters", "romanised_instruction")


def _stage(sid: str, instruction: str = "Help them install the app.", **extra: Any) -> Any:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid.title(), "instruction": instruction, **extra}
    )


def _close(instruction: str) -> ConversationStage:
    return _stage("close", instruction, otherwise=END_OF_CALL)


def _script(*stages: ConversationStage, **extra: Any) -> CallScript:
    return CallScript(schema_version=2, stages=list(stages), **extra)


def _found(script: CallScript, check: str) -> list[script_checks.Finding]:
    return script_checks.run(script, LINT, ids=[check])


# --- 1. the ending against the close ---------------------------------------------------------


def test_an_ending_and_a_close_that_give_different_ways_to_reach_us_are_caught() -> None:
    """FAILS IF: the 27 Nov script, its ending "message us on WhatsApp" and its close "call
    us", goes live without the owner being shown it."""
    script = _script(
        _stage("help"),
        _close("Thank them, ask them to call us if they need help, and end the call."),
        ending="Thank them and ask them to message us on WhatsApp if anything comes up.",
    )
    (finding,) = _found(script, "ending_vs_close")
    assert finding.path == "ending"
    assert finding.severity == "warn"
    assert "message" in finding.problem and "call" in finding.problem
    assert "Step 2" not in finding.problem and "step 2 (Close)" in finding.problem
    assert finding.line == script.ending


def test_the_close_is_read_in_its_lines_and_small_steps_too() -> None:
    close = _close("Thank them and end the call.").model_copy(
        update={"examples": {"en-IN": StepExamples(turns=["Please call us any time."])}}
    )
    script = _script(_stage("help"), close, ending="Ask them to message us on WhatsApp.")
    assert [f.path for f in _found(script, "ending_vs_close")] == ["ending"]


@pytest.mark.parametrize(
    ("ending", "close"),
    [
        # Both name the same way.
        ("Ask them to call us if they need anything.", "Tell them to call us, then end it."),
        # One names both ways; the other names one of them.
        ("Ask them to call us or message us on WhatsApp.", "Tell them to call us, end it."),
        # The close names no way to reach us.
        ("Ask them to message us on WhatsApp.", "Thank them and end the call."),
    ],
)
def test_an_ending_and_a_close_that_agree_pass(ending: str, close: str) -> None:
    assert _found(_script(_stage("help"), _close(close), ending=ending), "ending_vs_close") == []


def test_a_way_the_line_says_not_to_use_is_not_a_way_it_gives() -> None:
    """FAILS IF: "not to call us, message us" is read as giving both ways, which would agree
    with a close that says "call us" and hide the contradiction."""
    assert contact_channels("Tell them not to call us, message us on WhatsApp.") == {"message"}
    script = _script(
        _stage("help"),
        _close("Ask them to call us, then end the call."),
        ending="Tell them not to call us, message us on WhatsApp.",
    )
    assert [f.path for f in _found(script, "ending_vs_close")] == ["ending"]


def test_the_contradiction_is_shown_and_never_rewritten() -> None:
    """Only the owner knows which way is right, so no repair is asked to choose."""
    script = _script(
        _stage("help"),
        _close("Ask them to call us, then end the call."),
        ending="Ask them to message us on WhatsApp.",
    )
    assert not script_checks.BY_ID["ending_vs_close"].heals
    assert all(not f.startswith("ending:") for f in script_checks.repairs(script, LINT))


# --- 2. one instruction in two steps ---------------------------------------------------------


def test_a_step_that_repeats_an_earlier_instruction_is_caught() -> None:
    """FAILS IF: two steps that ask for one thing reach the in-call model unremarked."""
    script = _script(
        _stage("one", "Ask them which crop they grow."),
        _stage("two", "Help them install the app."),
        _stage("three", "ask them which crop they grow"),
    )
    (finding,) = _found(script, "same_instruction")
    assert finding.path == "stages.2.instruction"
    assert "step 1" in finding.problem


def test_steps_with_their_own_instructions_pass() -> None:
    script = _script(_stage("one", "Ask which crop they grow."), _stage("two"))
    assert _found(script, "same_instruction") == []


# --- 3. the call language's letters ----------------------------------------------------------


def _lines(**examples: StepExamples) -> CallScript:
    return _script(_stage("help", examples=examples))


def test_an_english_sentence_in_a_telugu_line_is_caught() -> None:
    """FAILS IF: a Telugu line carrying a whole English sentence is not shown (0.5.88 caught
    it in the opening only)."""
    script = _lines(
        **{TE: StepExamples(turns=["మీకు సహాయం చేస్తాను. We will help you install the app."])}
    )
    assert [f.path for f in _found(script, "own_letters")] == [f"stages.0.examples.{TE}.turns.0"]


def test_an_english_word_callers_say_in_a_telugu_line_passes() -> None:
    script = _lines(**{TE: StepExamples(turns=["ప్లే స్టోర్‌లో app ఓపెన్ చేయండి."])})
    assert _found(script, "own_letters") == []


def test_a_romanised_line_is_left_to_wrong_language() -> None:
    """FAILS IF: one romanised line is reported twice, once by each check."""
    script = _lines(**{TE: StepExamples(turns=["Meeru app install cheyandi andi."])})
    found = script_checks.run(script, LINT, ids=["wrong_language", "own_letters"])
    assert [f.check for f in found] == ["wrong_language"]


def test_an_answer_is_read_in_its_own_language() -> None:
    """The English answer of a step's question is English by design; its Telugu translation
    is a line the agent says in Telugu."""
    qa = ScenarioQa(
        question="Is it free?",
        answer="Yes, the app is free to use.",
        translations={TE: ScenarioQaText(answer="అవును. The app is free to use for everyone.")},
    )
    found = _found(_script(_stage("help", qa=[qa])), "own_letters")
    assert [f.path for f in found] == [f"stages.0.qa.0.translations.{TE}.answer"]


def test_an_english_call_is_not_read_for_letters() -> None:
    script = _lines(**{"en-IN": StepExamples(turns=["We will help you install the app."])})
    assert script_checks.run(script, LintContext(language="en-IN"), ids=["own_letters"]) == []


def test_a_romanised_push_back_answer_and_quick_fact_are_caught() -> None:
    """FAILS IF: the 27 Nov push-back answers and quick facts, romanised Telugu where the
    fields are plain English, go live unremarked."""
    script = _script(
        _stage("help"),
        objections=[
            Objection(
                objection="I have no time.",
                response="Meeru tension padakandi garu, app lo details anni undi ani cheppandi.",
            ),
            Objection(objection="Is it safe?", response="Say the app keeps their data private."),
        ],
        faqs=[
            FaqEntry(question="Cost?", answer="App ki dabbulu ledu, free ga vadukovachu andi."),
            FaqEntry(question="Hours?", answer="Open 9 am to 6 pm, Monday to Saturday."),
        ],
    )
    found = _found(script, "romanised_instruction")
    assert [f.path for f in found] == ["objections.0.response", "faqs.0.answer"]
    out = script_gate.checks_out(found, script)
    assert [c.message.split(":")[0] for c in out.findings] == ["Push-back answer 1", "Quick fact 1"]


def test_an_instruction_in_telugu_letters_is_the_owners_to_keep() -> None:
    script = _script(_stage("help"), ending="ధన్యవాదాలు చెప్పి కాల్ ముగించండి.")
    assert _found(script, "romanised_instruction") == []


# --- 4. severity -----------------------------------------------------------------------------


def test_the_new_checks_warn_and_never_stop_put_it_live() -> None:
    """FAILS IF: one of them becomes a refusal: each MAY send a call wrong, none is wrong on
    every call (D-989)."""
    for check in NEW_CHECKS:
        assert script_checks.BY_ID[check].severity == "warn", check
        assert check not in script_checks.BLOCKING


# --- 5. the size target ----------------------------------------------------------------------


def _size(script_text: str) -> prompt_size.PromptSize:
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Asha",
        direction="inbound",
        language_primary=TE,
        system_prompt=script_text,
        opening_line="నమస్కారం, ఎలా సహాయం చేయగలను?",
    )
    return prompt_size.measure(cfg, THINNEST_LIMITS.prompt_chars)


def test_the_target_is_well_under_the_box() -> None:
    """FAILS IF: the target is not 2,000 tokens at Google's ratio, or leaves no room under
    the box beside the platform's own layers."""
    assert prompt_size.SCRIPT_TARGET_CHARS == 8_000
    empty = _size("[GOAL]\nHelp.")
    assert empty.script_limit is not None
    assert empty.script_limit > prompt_size.SCRIPT_TARGET_CHARS


def test_the_size_counts_the_script_once_against_its_target_and_its_box() -> None:
    small, large = _size("[GOAL]\nHelp."), _size("[GOAL]\n" + "x" * 9_000)
    script_layer = [p.chars for p in large.layers if p.key == "client_script"]
    assert [large.script_chars] == script_layer
    assert large.limit is not None
    assert large.script_limit == large.limit - (large.total - large.script_chars)
    assert not small.over_target and large.over_target
    assert large.fits, "the target is never the box"


def test_the_checks_read_carries_the_size() -> None:
    size = _size("[GOAL]\n" + "x" * 9_000)
    out = script_gate.checks_out([], None, size).size
    assert out is not None
    assert out.script_chars == size.script_chars
    assert out.target_chars == prompt_size.SCRIPT_TARGET_CHARS
    assert out.limit_chars == size.script_limit
    assert out.over_target and out.fits
    assert script_gate.checks_out([]).size is None


@pytest.mark.rls
async def test_the_lines_checks_endpoint_shows_the_size() -> None:
    from tests.inbound_lines_test import _call, _fresh_engine, _line, _live_agent

    _fresh_engine()
    tenant_id, agent_id, token = await _live_agent()
    line_id = await _line(tenant_id, agent_id)
    code, checks = await _call(token, "GET", f"/{line_id}/script/checks")
    assert code == 200, checks
    size = checks["size"]
    assert size["target_chars"] == prompt_size.SCRIPT_TARGET_CHARS
    assert size["script_chars"] > 0
    # The test engine has no box; ThinnestAI's is `test_the_target_is_well_under_the_box`'s.
    assert size["limit_chars"] is None
    assert size["fits"] is True


def test_a_repair_never_rewrites_a_steps_plan() -> None:
    """FAILS IF: the automatic repair may rewrite a step's instruction or an action (27 Nov
    2026: the repair right after a kept Rytu Khata draft rewrote eight owner instructions and
    added call backs the owner had forbidden). Spoken lines stay repairable."""
    from apps.api.agents.script_checks import repairable
    from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep

    script = CallScript(
        schema_version=2,
        stages=[
            ConversationStage(
                id="s1",
                name="Install",
                instruction="Open Chrome, type the site and tap Install app.",
                sounds_like="Open Chrome.",
                procedure=[ProcedureStep(action="Open Chrome.", wait_for="It is open.")],
            )
        ],
    )
    assert not repairable(script, "stages.0.instruction: several actions")
    assert not repairable(script, "stages.0.procedure.0.action: several actions")
    assert repairable(script, "stages.0.sounds_like: several actions")
