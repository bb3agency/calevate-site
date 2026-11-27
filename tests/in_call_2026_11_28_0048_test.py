"""The founder's test call of 28 Nov 2026 (00:48): two actions joined in one turn, a step's check
said as "will you tell me whether it saved?", a bare "OK" taken as done four times, every reply
ending alike because the style ordered one ending, and a textbook "and" said in the phrase an
example turn held it in.
"""

from __future__ import annotations

import pytest
from apps.api.agents import script_checks
from apps.api.agents.live_apply import platform_prompt_revision
from apps.api.agents.script_lint import LintContext
from apps.api.agents.script_structure import without_fixed_endings
from apps.workers.step_writer import STEP_INSTRUCTION
from calevate_shared import call_script
from calevate_shared.call_script import (
    ACTIONS_LEAD,
    CHECK_WHAT_THEY_SEE,
    OUTCOMES_LEAD,
    PROCEDURE_LEAD,
    STEPS_LEAD,
    CallScript,
    ConversationStage,
    SpeakingStyle,
    StepExamples,
    StepOutcome,
    compile_call_script,
    done_when,
    fixed_ending,
    native_steps,
    without_fixed_ending,
)
from calevate_shared.engine import VOICE_STYLE_GUIDANCE

TE = "te-IN"

# --- 1. one action a turn ---


def _expense(**extra: object) -> ConversationStage:
    return ConversationStage.model_validate(
        {
            "id": "e",
            "name": "First expense",
            "instruction": "Help them add one expense.",
            "step": 1,
            "procedure": [
                {
                    "action": "Tap Expenses",
                    "wait_for": "User confirms they are on the Expenses screen",
                },
                {"action": "Tap the plus button", "wait_for": "The new expense window is open"},
                {"action": "Tap Save", "wait_for": "User confirms the expense is saved"},
            ],
            "examples": {TE: StepExamples(turns=["Expenses నొక్కండి."]).model_dump()},
            **extra,
        }
    )


def test_the_step_lead_names_joining_and_repeats_the_action_not_the_step() -> None:
    assert PROCEDURE_LEAD.startswith("One action a turn, never two together, even where an example")
    assert "That action again, shorter." in PROCEDURE_LEAD
    assert "the same step" not in PROCEDURE_LEAD
    # "Only their done moves you on" read as any word moving on.
    assert "moves you on" not in PROCEDURE_LEAD
    assert "moves you on" not in VOICE_STYLE_GUIDANCE


def test_a_steps_own_action_list_carries_the_two_rules_it_broke() -> None:
    step = native_steps(CallScript(schema_version=2, stages=[_expense()]))[0]
    assert f"{ACTIONS_LEAD} 1. Tap Expenses." in step.detail
    assert '"OK" to a thing to do is not done' in ACTIONS_LEAD


# --- 2. never a request to report back ---


def test_both_step_leads_check_by_what_they_see_never_by_a_report() -> None:
    for lead in (OUTCOMES_LEAD, STEPS_LEAD):
        assert CHECK_WHAT_THEY_SEE in lead
        assert "ask them to and wait" not in lead
    assert "never whether it worked or to tell you" in CHECK_WHAT_THEY_SEE
    assert "Never ask them to tell you when it is done or whether it worked." in PROCEDURE_LEAD


def test_a_criterion_that_asks_for_a_confirmation_says_what_is_true_instead() -> None:
    assert done_when("User confirms the expense is saved") == "The expense is saved"
    assert done_when("The user confirms that the app opens.") == "The app opens."
    # Without its verb an "if" clause no longer says what is listened for.
    assert done_when("The user confirms if they see the icon") == (
        "The user confirms if they see the icon"
    )
    assert done_when("They see the icon") == "They see the icon"
    detail = native_steps(CallScript(schema_version=2, stages=[_expense()]))[0].detail
    assert "confirms" not in detail
    assert "Done when: The expense is saved." in detail


# --- 3. a bare "OK" ---


def test_a_bare_ok_to_an_action_is_not_done_in_every_place_an_action_list_is_read() -> None:
    assert 'A bare "OK" to it is not done: ask what they see.' in PROCEDURE_LEAD
    assert 'A bare "OK" is not done.' in VOICE_STYLE_GUIDANCE


# --- 4. one ending ordered for every sentence ---

ADDRESS = "Use {{lead_name}} garu for the name and end sentences with andi."


@pytest.mark.parametrize(
    ("said", "kept"),
    [
        (ADDRESS, "Use {{lead_name}} garu for the name."),
        ("garu, and always end every reply with ji", "garu"),
        ("Add andi at the end of every sentence.", ""),
        ("Warm; finish each line with a thank you. Short sentences.", "Warm. Short sentences."),
        ("garu or andi, never sir or madam", "garu or andi, never sir or madam"),
    ],
)
def test_an_ordered_ending_is_cut_and_the_rest_kept(said: str, kept: str) -> None:
    assert fixed_ending(said) is (said != kept)
    assert without_fixed_ending(said) == kept


def _styled() -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[_expense()],
        style=SpeakingStyle(tone="Warm and short.", address_form=ADDRESS),
    )


def test_the_compile_drops_it_from_a_stored_script() -> None:
    body = compile_call_script(_styled(), languages=(TE,))
    assert "garu for the name.\n" in body
    assert "end sentences" not in body


def test_a_write_mends_it_and_the_check_names_it_on_a_stored_script() -> None:
    script = _styled()
    found = script_checks.texts(script_checks.run(script, LintContext(), ids=["fixed_ending"]))
    assert [f.partition(": ")[0] for f in found] == ["style.address_form"]
    assert script_checks.BY_ID["fixed_ending"].mistake == "same_closing"
    mended = without_fixed_endings(script)
    assert mended.style.address_form == "Use {{lead_name}} garu for the name."
    assert mended.style.tone == "Warm and short."
    assert script_checks.run(mended, LintContext(), ids=["fixed_ending"]) == []
    assert without_fixed_endings(mended) is mended


def test_the_compile_rule_moves_the_platform_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    before = platform_prompt_revision()
    monkeypatch.setattr(call_script, "without_fixed_ending", lambda text: text.strip())
    assert platform_prompt_revision() != before


# --- 5. a textbook word in an example turn ---

#: The turn shape the call repeated ("the name and the size"), with the textbook "and".
FORMAL = "మీ పొలం పేరు మరియు సైజు ఎంటర్ చేయండి."
PLAIN = "మీ పొలం పేరు ఎంటర్ చేయండి."


def _with_turns(*turns: str, confused: str = "") -> CallScript:
    examples = {TE: StepExamples(turns=list(turns), confused=confused).model_dump()}
    stage = _expense(examples=examples)
    return CallScript(
        schema_version=2, stages=[stage], step_outcomes=[StepOutcome(step=1, outcome="Saved")]
    )


def test_a_textbook_turn_is_not_shown_while_a_plain_one_remains() -> None:
    body = compile_call_script(_with_turns(FORMAL, PLAIN, confused=FORMAL), languages=(TE,))
    assert PLAIN in body and FORMAL not in body
    # The only turn a step has is still shown: a step with no turn has nothing to sound like.
    assert FORMAL in compile_call_script(_with_turns(FORMAL), languages=(TE,))


# --- the writer ---


def test_the_writer_keeps_actions_apart_and_writes_criteria_as_what_they_see() -> None:
    assert "its aim only, never its actions listed again" in STEP_INSTRUCTION
    assert "never that they confirm or tell you" in STEP_INSTRUCTION
    assert "ONE action or asks ONE question, never two joined" in STEP_INSTRUCTION
