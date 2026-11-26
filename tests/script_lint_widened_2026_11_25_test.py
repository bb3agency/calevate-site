"""Three of the writer's checks read wider than they did when the script of 25 Nov 2026 got
past them (the evidence script: `tests/fixtures/script_writer_cases/recorded/
rytu_khata_install.json`, in English stand-in form):

1. A detail judged from the whole call asked in a step's instruction or line, not only in its
   collect list (`judged_field_asked_problems`, `script_shape.judged_ask_problems`).
2. Several asks listed under one question mark (`script_lint.asks_count`).
3. The close found by its role, not only by the name "Finalise the call"
   (`script_lint.closes_the_call`, `script_shape.closing_index`).

The model is never called.
"""

from __future__ import annotations

from typing import Any

from apps.api.agents import script_checks, script_lint
from apps.api.agents.script_builder import job_details
from apps.api.agents.script_heal import heal_findings
from apps.api.agents.script_lint import LintContext, asks_count, script_problems
from apps.api.agents.script_shape import closing_index, trailing_problems
from calevate_shared.call_script import END_OF_CALL, CallScript, ConversationStage
from calevate_shared.lead_fields import core_fields
from scripts import eval_script_writer as ev

JUDGED = ("Campaign goal met", "Technical comfort level", "Primary usage interest")
#: Step 1 of the 25 Nov 2026 script, as the evidence gives it.
INSTRUCTION = (
    "Ask the user to check for the Rytu Khata icon. Collect the caller name, campaign goal "
    "met, technical comfort level, primary usage interest and alternative number. If they "
    "cannot or will not reach the website rytukhata.com, offer to call back."
)
LISTED = "Then tell me your name, your goal, your tech awareness, your interest and another number?"


def _evidence() -> CallScript:
    case = next(c for c in ev.load_cases() if c.id == "rytu_khata_install")
    return ev.load_recorded(case).script


def _stage(sid: str, name: str, instruction: str = "Help them.", **extra: Any) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": name, "instruction": instruction, **extra}
    )


def _one(instruction: str = "Help them.", line: str = "") -> CallScript:
    scripts = {"en-IN": line} if line else {}
    return CallScript(schema_version=2, stages=[_stage("a", "Ask", instruction, scripts=scripts)])


def _paths(found: list[str]) -> list[str]:
    return [f.partition(": ")[0] for f in found]


# --- 1. a judged detail asked in words --------------------------------------------------------


def test_a_judged_detail_asked_in_the_instruction_and_line_is_found() -> None:
    """FAILS IF: the 25 Nov step 1, which asked three judged details in its instruction and
    two in its line and none in a collect list, passes the judged-detail lint."""
    script = _evidence()
    found = script_lint.judged_field_asked_problems(script, LintContext(judged=JUDGED))
    at_instruction = [f for f in found if f.startswith("stages.0.instruction: ")]
    assert {label for label in JUDGED if any(f'"{label}"' in f for f in at_instruction)} == set(
        JUDGED
    )
    at_line = [f for f in found if f.startswith("stages.0.scripts.en-IN: ")]
    assert len(at_line) == 2
    assert any('"Campaign goal met"' in f for f in at_line)
    assert any('"Primary usage interest"' in f for f in at_line)


def test_the_repair_hears_a_judged_ask() -> None:
    """FAILS IF: the targeted repair (`script_checks.repairs`, `heal_findings`) is not told about a
    line that asks a judged detail, so it never rewrites it."""
    script = _one(INSTRUCTION, LISTED)
    repaired = script_checks.repairs(script, LintContext(judged=JUDGED))
    assert "stages.0.scripts.en-IN" in _paths(repaired)
    assert "stages.0.instruction" in _paths(heal_findings(script, LintContext(judged=JUDGED)))


def test_the_job_names_its_judged_details() -> None:
    """FAILS IF: the job's judged details do not reach the writer's checks, also once the
    placed call drops the name."""
    stored = [
        {"key": "campaign_goal_met", "label": "Campaign goal met"},
        {"key": "technical_comfort", "label": "Technical comfort level"},
        {"key": "usage_interest", "label": "Primary usage interest"},
        {"key": "phone_type", "label": "Phone Type"},
    ]
    core = core_fields({"name": "Caller Name"})
    details = job_details(stored, core)
    assert details.judged == JUDGED
    assert details.placed().judged == JUDGED
    assert "Phone Type" in details.labels()


def test_a_judged_word_mentioned_without_asking_is_not_found() -> None:
    """Negative controls: a statement, a note for after the call, an instruction NOT to ask,
    and the judged word as something other than the person's own."""
    for script in (
        _one(line="Your goal is to finish the setup today."),
        _one("Note their interest and their comfort after the call."),
        _one("Do not ask about their goal."),
        _one(line="Shall I tell you the interest rate on the loan?"),
        _one(line="Is the campaign live in your village?"),
    ):
        assert script_lint.judged_field_asked_problems(script, LintContext(judged=JUDGED)) == []


def test_without_the_jobs_judged_details_only_collect_lists_are_read() -> None:
    assert script_lint.judged_field_asked_problems(_one(INSTRUCTION, LISTED)) == []


# --- 2. several asks under one question mark -------------------------------------------------


def test_asks_listed_under_one_question_mark_are_counted() -> None:
    """FAILS IF: "your name, your goal, your tech awareness, your interest and another
    number?" counts as one question because it has one question mark."""
    script = _evidence()
    found = script_lint.multi_question_line_problems(script)
    assert _paths(found) == ["stages.0.scripts.en-IN"]
    assert asks_count(LISTED) == 4
    assert any(
        f.startswith("stages.0.scripts.en-IN: asks 4 questions")
        for f in script_problems(_one(line=LISTED), LintContext())
    )


def test_one_ask_a_choice_or_an_action_list_is_one_question() -> None:
    for line in (
        "Is the Rytu Khata icon on your home screen?",
        "Shall I send it to your number or your email?",
        "Have you opened the app and pressed Login?",
        "Your farm, is it added?",
        "Tell me when it is done.",
    ):
        assert asks_count(line) <= 1, line
        assert script_lint.multi_question_line_problems(_one(line=line)) == []


# --- 3. the close by its role ----------------------------------------------------------------


def test_a_step_after_a_renamed_close_is_found() -> None:
    """FAILS IF: the close is recognised only by the name "Finalise the call", so the 25 Nov
    shape with its close renamed hides the step after it."""
    stages = list(_evidence().stages)
    stages[6] = stages[6].model_copy(update={"name": "Wrap up"})
    script = _evidence().model_copy(update={"stages": stages})
    assert closing_index(script) == 6
    assert _paths(trailing_problems(script)) == ["stages.7"]
    assert _paths(script_lint.steps_after_close_problems(script)) == ["stages.7"]


def test_a_close_whose_way_on_ends_the_call_is_the_close() -> None:
    script = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Check"),
            _stage("b", "Goodbye", "Thank them.", otherwise=END_OF_CALL),
            _stage("c", "Forgot password", "Help them reset it."),
        ],
    )
    assert closing_index(script) == 1
    assert _paths(trailing_problems(script)) == ["stages.2"]


def test_an_early_end_or_a_conditional_end_is_not_the_close() -> None:
    """Negative controls: a scenario of step 1 that ends the call, and an end on a
    condition, leave the real close last and find nothing after it."""
    script = CallScript(
        schema_version=2,
        stages=[
            _stage(
                "a",
                "Check",
                "Ask if they can talk. If they are busy, end the call.",
                step=1,
                branches=[{"when": "Wrong person", "target": "wrong"}],
            ),
            _stage("wrong", "Wrong person", "Apologise and end the call.", step=1),
            _stage("b", "Login", "Ask them to log in.", step=2),
            _stage("c", "Wrap up", "Thank them and close the call.", step=3),
        ],
    )
    assert closing_index(script) == 3
    assert trailing_problems(script) == []
    conditional = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Check", "If they are busy, end the call."),
            _stage("b", "Login", "Ask them to log in."),
        ],
    )
    assert closing_index(conditional) is None


def test_the_name_still_finds_a_close_that_states_no_role() -> None:
    script = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Check"),
            _stage("b", "Finalise the call", "Thank them."),
            _stage("c", "Not registered", "Explain they have registered."),
        ],
    )
    assert closing_index(script) == 1
    assert _paths(trailing_problems(script)) == ["stages.2"]
