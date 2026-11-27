"""What a call's model reads from the client script is said once and agrees with itself
(founder, 27 Nov 2026): a step's instruction, actions and outcome in its step only, one
closing, no English example turns in a call whose main language is not English, no phrase
list beside the variety rule, and no caller's-name field inside the cacheable script.

Caller-facing lines are placeholders: Telugu is written by the step writer, never in a test.
"""

from __future__ import annotations

import pytest
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS
from calevate_shared.call_script import (
    CALLER_NAME_SLOT,
    ENDING_HEADER,
    OBJECTIONS_LEAD,
    OUTCOMES_HEADER,
    OUTCOMES_LEAD,
    STAGE_DETAIL_MAX,
    STEP_EXAMPLES_LEAD,
    CallScript,
    ConversationStage,
    Objection,
    ProcedureStep,
    SpeakingStyle,
    StageBranch,
    StepExamples,
    StepOutcome,
    compile_call_script,
    native_steps,
    without_outline,
)
from calevate_shared.engine import (
    CALLER_NAME_ONLY_MARK,
    THIS_CALL_HEADER,
    AgentConfig,
    compose_engine_prompt,
    fenced_script,
)

TE, EN, HI = "te-IN", "en-IN", "hi-IN"
NAMES = (
    "Introduction",
    "Registered",
    "App on home screen",
    "Login",
    "Language",
    "My Farms",
    "First expense",
    "First sale",
    "Dashboard",
    "Questions",
    "Close",
)


def _turns(tag: str, name: str) -> StepExamples:
    def turn(n: int) -> str:
        return f"<{tag}: {name} turn {n} with one action>".ljust(80, ".")

    return StepExamples(turns=[turn(n) for n in range(1, 5)], confused=turn(5), stuck=turn(6))


def _actions(i: int) -> list[ProcedureStep]:
    return [
        ProcedureStep(
            action=f"Action {i}.{n}: ask them to tap button {n}", wait_for=f"{i}.{n} seen"
        )
        for n in (1, 2, 3)
    ]


def _rytu(*, languages: tuple[str, ...] = (TE, EN)) -> CallScript:
    """Eleven steps shaped like the Rytu Khata campaign: six with a three-action list, every
    one with four turns, a confused and a stuck turn per language, an outcome per step, and
    a last step whose only way out ends the call."""
    stages = []
    for i, name in enumerate(NAMES, 1):
        last = i == len(NAMES)
        stages.append(
            ConversationStage(
                id=f"s{i}",
                step=i,
                name=name,
                instruction=f"Instruction {i}: help them with {name.lower()}, one action a turn.",
                procedure=_actions(i) if 2 < i < 9 else [],
                examples={tag: _turns(tag, name) for tag in languages},
                branches=[] if last else [StageBranch(when="Still stuck", target="call_back")],
                otherwise="end" if last else f"s{i + 1}",
            )
        )
    return CallScript(
        schema_version=2,
        business_line="A farm accounts app.",
        identity="You are Varsha.",
        goal="Help registered farmers start using the app.",
        opening_line="<te: Hello {{lead_name}} garu, a good time?>",
        stages=stages,
        step_outcomes=[StepOutcome(step=n, outcome=f"Outcome {n} reached") for n in range(1, 12)],
        ending="Thank them warmly and end the call.",
    )


def _what_the_model_reads(script: CallScript, *, native: bool) -> str:
    body = compile_call_script(script, languages=(TE, EN))
    if not native:
        return body
    steps = native_steps(script)
    return "\n".join([without_outline(body), *(f"{s.title}: {s.detail}" for s in steps)])


@pytest.mark.parametrize("native", [True, False])
def test_each_steps_instruction_actions_and_outcome_are_read_once(native: bool) -> None:
    """FAILS IF: a step's instruction, an action or an outcome reaches the model twice, with
    the stages sent as engine steps or kept in the text outline."""
    script = _rytu()
    read = _what_the_model_reads(script, native=native)
    for i, stage in enumerate(script.stages, 1):
        assert read.count(f"Instruction {i}:") == 1, (native, i)
        assert read.count(f"Outcome {i} reached") == 1, (native, i)
        for action in stage.procedure:
            assert read.count(action.action) == 1, (native, action.action)


def test_an_action_list_too_long_for_its_step_is_read_once_under_step_by_step() -> None:
    """FAILS IF: actions a full step could not hold are lost, or said in both places."""
    long = [ProcedureStep(action=f"Long action {n} " + "x" * 120) for n in range(1, 7)]
    script = _rytu()
    stages = [*script.stages[:3], script.stages[3].model_copy(update={"procedure": long})]
    script = script.model_copy(update={"stages": [*stages, *script.stages[4:]]})
    for native in (True, False):
        read = _what_the_model_reads(script, native=native)
        for n in range(1, 7):
            assert read.count(f"Long action {n} ") == 1, (native, n)


def test_an_outcome_a_full_step_cannot_hold_is_said_once_in_step_outcomes() -> None:
    """FAILS IF: an outcome that did not fit its step is dropped or said twice."""
    script = _rytu()
    full = script.stages[0].model_copy(update={"instruction": "Instruction 1: " + "y" * 520})
    script = script.model_copy(update={"stages": [full, *script.stages[1:]]})
    body = compile_call_script(script, languages=(TE, EN))
    assert "\nIntroduction: Outcome 1 reached" in body.split(OUTCOMES_HEADER, 1)[1]
    for native in (True, False):
        assert _what_the_model_reads(script, native=native).count("Outcome 1 reached") == 1


def test_the_outcome_rule_is_said_once() -> None:
    body = compile_call_script(_rytu(), languages=(TE, EN))
    assert body.count(OUTCOMES_LEAD) == 1
    assert body.count(STEP_EXAMPLES_LEAD) == 1


def test_one_closing_when_the_last_step_shows_how_the_call_ends() -> None:
    """FAILS IF: the ending and a closing step's example turns both render."""
    body = compile_call_script(_rytu(), languages=(TE, EN))
    assert ENDING_HEADER not in body
    assert "Thank them warmly" not in body
    # A script whose last step shows no words keeps its ending.
    plain = _rytu()
    close = plain.stages[-1].model_copy(update={"examples": {}})
    plain = plain.model_copy(update={"stages": [*plain.stages[:-1], close]})
    assert f"{ENDING_HEADER}\nThank them warmly" in compile_call_script(plain, languages=(TE,))


def test_a_step_that_can_go_on_is_not_a_closing() -> None:
    """FAILS IF: a step with a way out that does not end the call counts as the close."""
    script = _rytu()
    close = script.stages[-1].model_copy(update={"otherwise": "s1"})
    script = script.model_copy(update={"stages": [*script.stages[:-1], close]})
    assert ENDING_HEADER in compile_call_script(script, languages=(TE,))


def test_a_telugu_call_shows_no_english_turns_and_keeps_other_indian_languages() -> None:
    """FAILS IF: English example turns render in a call whose main language is Telugu."""
    script = _rytu(languages=(TE, EN, HI))
    body = compile_call_script(script, languages=(TE, EN, HI))
    assert '"<te-IN:' in body and '"<hi-IN:' in body
    assert "<en-IN:" not in body
    english_first = compile_call_script(script, languages=(EN, TE))
    assert '"<en-IN:' in english_first and '"<te-IN:' in english_first


def test_no_phrase_list_and_objections_read_like_the_examples() -> None:
    script = _rytu().model_copy(
        update={
            "style": SpeakingStyle(tone="Warm", sample_phrases=["One second."]),
            "objections": [Objection(objection="Too costly.", response="It is free.")],
        }
    )
    body = compile_call_script(script, languages=(TE,))
    assert "One second." not in body
    assert "Tone: Warm" in body
    assert f"{OBJECTIONS_LEAD}\nQ: Too costly.\nA: It is free." in body
    assert "not words to copy" in STEP_EXAMPLES_LEAD and "not words to copy" in OBJECTIONS_LEAD


def _cfg(body: str) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="Rytu Khata",
        direction="outbound",
        language_primary=TE,
        languages_extra=[EN],
        system_prompt=without_outline(body),
        opening_line="<te: I am Varsha, an AI assistant.>",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )


def test_the_callers_name_is_never_a_field_inside_the_script() -> None:
    """FAILS IF: a `{{lead_name}}` is left in the fenced script, where the first field the
    engine fills ends the part of the prompt a new call reuses."""
    script = _rytu().model_copy(
        update={
            "goal": "{{lead_name}} registered last week; help them start.",
            "ending": "",
        }
    )
    stage = script.stages[0].model_copy(
        update={"examples": {TE: StepExamples(turns=["<te: {{lead_name}} garu, did you?>"])}}
    )
    script = script.model_copy(update={"stages": [stage, *script.stages[1:]]})
    body = compile_call_script(script, languages=(TE,))
    assert f"[GOAL]\n{CALLER_NAME_SLOT} registered last week" in body
    # The opening is spoken by the engine and keeps its field.
    assert "Hello {{lead_name}} garu" in body
    prompt = compose_engine_prompt(_cfg(body))
    assert "{{" not in fenced_script(body)
    assert prompt.index("{{") > prompt.index(THIS_CALL_HEADER)
    assert CALLER_NAME_SLOT.strip("()") == CALLER_NAME_ONLY_MARK.strip("[]")


def test_a_custom_field_still_moves_its_section_after_the_fixed_ones() -> None:
    script = _rytu().model_copy(update={"goal": "Ask about {{crop}}."})
    body = compile_call_script(script, languages=(TE,))
    assert body.index("[GOAL]") > body.index("[STEP BY STEP]")


def test_the_rytu_shaped_script_fits_and_is_measured() -> None:
    script = _rytu()
    body = compile_call_script(script, languages=(TE, EN))
    cfg = _cfg(body).model_copy(update={"script_steps": native_steps(script)})
    prompt = compose_engine_prompt(cfg)
    steps = sum(len(s.detail) + len(s.title) for s in native_steps(script))
    print(
        f"rytu-shaped, 11 steps: body {len(without_outline(body))}, steps {steps}, "
        f"prompt {len(prompt)} chars"
    )
    assert len(prompt) <= INSTRUCTIONS_MAX_CHARS
    assert max(len(s.detail) for s in native_steps(script)) <= STAGE_DETAIL_MAX


def _side_step_script(otherwise: str) -> CallScript:
    """Step 2 branches to a side step numbered with step 3, as the canvas places it."""

    def stage(sid: str, step: int, name: str, **extra: object) -> ConversationStage:
        return ConversationStage(
            id=sid, step=step, name=name, instruction=f"{name} instruction.", **extra
        )

    return CallScript(
        schema_version=2,
        stages=[
            stage("a", 1, "Introduction"),
            stage(
                "b",
                2,
                "Why we called",
                branches=[StageBranch(when="Never registered", target="side")],
            ),
            stage("c", 3, "App on home screen"),
            stage("side", 3, "Not registered", otherwise=otherwise),
            stage("d", 4, "Login"),
        ],
        step_outcomes=[StepOutcome(step=n, outcome=f"Outcome {n} reached") for n in (1, 2, 3, 4)],
    )


def test_a_side_step_leading_into_its_step_takes_the_outcome_of_the_step_reaching_it() -> None:
    """FAILS IF: a side step that goes on to its own step must first reach that step's outcome."""
    steps = native_steps(_side_step_script(otherwise="c"))
    side = next(s for s in steps if s.title == "Not registered")
    assert "Outcome 2 reached" in side.detail
    assert "Outcome 3 reached" not in side.detail


def test_a_side_step_in_place_of_its_step_keeps_that_steps_outcome() -> None:
    steps = native_steps(_side_step_script(otherwise="d"))
    side = next(s for s in steps if s.title == "Not registered")
    assert "Outcome 3 reached" in side.detail


def test_step_outcomes_name_steps_and_never_number_them() -> None:
    """FAILS IF: an outcome no step had room for is numbered, which disagrees with the engine's
    positional step list once a side step shifts it."""
    script = _side_step_script(otherwise="c")
    full = script.stages[4].model_copy(update={"instruction": "Login " + "y" * STAGE_DETAIL_MAX})
    script = script.model_copy(update={"stages": [*script.stages[:4], full]})
    section = compile_call_script(script, languages=(EN,)).split(OUTCOMES_HEADER, 1)[1]
    assert "\nLogin: Outcome 4 reached" in section
    assert "Step 4" not in section
