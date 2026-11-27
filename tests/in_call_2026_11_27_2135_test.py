"""The founder's test call of 27 Nov 2026 (21:35): a guided set-up call that called the task
finished two steps short, took every "done" at its word, said "our records show" with nothing
looked up, and gave several things to do in one turn because the script's own small steps did.
"""

from __future__ import annotations

import json

from apps.api.agents import call_mistakes, turn_checks
from apps.api.agents.script_checks import run, texts
from apps.api.agents.script_lint import LintContext, english_steps, stacked_line
from apps.api.crm.step_progress import StepProgress, StepReading, progress_json, read_progress
from apps.workers import step_progress as judge
from calevate_shared.call_script import (
    OUTCOMES_LEAD,
    CallScript,
    ConversationStage,
    ProcedureStep,
    StepExamples,
    StepOutcome,
    compile_call_script,
)
from calevate_shared.engine import AgentConfig, compose_engine_prompt
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionSchemaSpec

# --- 1. a task called finished with steps left ----------------------------------------------


def test_a_step_needs_what_they_see_and_an_early_stop_is_never_all_done() -> None:
    assert 'then ask what they see; a bare "done" is not it.' in OUTCOMES_LEAD
    assert "Never say it is all done: say what is left, and take it as a later." in OUTCOMES_LEAD


NAMES = {1: "Install", 2: "Log in", 3: "Close"}


def _turns() -> list[TranscriptTurn]:
    lines = [
        ("agent", "Please install the app."),
        ("caller", "Yes it is installed now."),
        ("agent", "Now log in with your number."),
        ("caller", "That is enough, I will see the rest later."),
        ("agent", "You have finished the set-up, thank you."),
    ]
    return [
        TranscriptTurn(call_id="c", idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate(lines)
    ]


def _raw(claimed: int, *, second: str = "not_reached") -> dict[str, object]:
    return {
        "steps": [
            {
                "step": 1,
                "state": "reached",
                "caller_turn": 1,
                "quote": "it is installed now",
                "moved_on_turn": -1,
            },
            {
                "step": 2,
                "state": second,
                "caller_turn": 3 if second == "reached" else -1,
                "quote": "That is enough" if second == "reached" else "",
                "moved_on_turn": -1,
            },
        ],
        "fields": [],
        "goal_step": -1,
        "outcomes": [],
        "claimed_done_turn": claimed,
    }


def _checked(raw: dict[str, object]) -> StepProgress:
    lines = judge.redacted_lines(_turns())
    return judge.checked(raw, names=NAMES, lines=lines, spec=ExtractionSchemaSpec(fields=[]))


def test_the_claim_counts_only_on_an_agent_line_with_a_step_unfinished() -> None:
    got = _checked(_raw(4))
    assert got.claimed_done_turn == 4
    assert call_mistakes.step_mistakes(got, _turns()) == {"claimed_complete": 4}
    assert read_progress(json.loads(progress_json(got))) == got
    # A caller line is never the agent's claim.
    assert _checked(_raw(3)).claimed_done_turn is None
    # Every step before the close reached: the task was done, whatever the judge said.
    assert _checked(_raw(4, second="reached")).claimed_done_turn is None
    assert _checked(_raw(-1)).claimed_done_turn is None


def test_the_kind_is_a_platform_kind_with_a_lesson() -> None:
    assert "claimed_complete" in turn_checks.JOB_KINDS
    assert "claimed_complete" in turn_checks.IN_CALL_KINDS
    assert call_mistakes.LESSONS["claimed_complete"].label
    progress = StepProgress(steps=(StepReading(1, "a", "reached", 1),))
    assert call_mistakes.step_mistakes(progress, _turns()) == {}


# --- 3. records nobody looked up ------------------------------------------------------------


def _stage(action: str) -> ConversationStage:
    return ConversationStage(
        id="reg",
        name="Not registered",
        instruction="Tell them gently this number was registered with us earlier.",
        procedure=[ProcedureStep(action=action, wait_for="They answer")],
    )


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, opening_line="Hello, can we talk now?", stages=list(stages))


def test_a_line_saying_records_show_it_is_found_and_a_plain_one_passes() -> None:
    claim = _script(_stage("Mention that our records show their number was already registered."))
    found = texts(run(claim, LintContext(), ids=["records_claim"]))
    assert [f.partition(": ")[0] for f in found] == ["stages.0.procedure.0.action"]
    plain = _script(_stage("Tell them they are on our list as registered."))
    assert texts(run(plain, LintContext(), ids=["records_claim"])) == []


def test_a_placed_call_says_the_list_never_records() -> None:
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="B",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="Help them.",
        opening_line="Hello, this is A from B. Is now a good time?",
        call_is_recorded=True,
    )
    assert "What THIS CALL says is our list, never records you checked." in compose_engine_prompt(
        cfg
    )


# --- 4. several things to do in one turn ----------------------------------------------------


def test_a_small_step_with_two_things_to_do_is_found() -> None:
    for line in (
        "Enter the expense amount and pick your farm.",
        "Enter the sale amount and save the entry.",
        "Select the farm and the crop from the provided list.",
    ):
        assert english_steps(line) >= 2 and stacked_line(line), line
    for line in (
        "Tap the Save button to finish adding your farm.",
        "Look for the language settings icon on your screen and tap on it.",
        "Tap the Add Farm button.",
        "Finally, tap Save to record it.",
    ):
        assert english_steps(line) <= 1 and not stacked_line(line), line


def test_the_writer_repairs_such_a_small_step() -> None:
    stage = ConversationStage(
        id="sale",
        name="First sale",
        instruction="Guide them to enter one sale.",
        procedure=[
            ProcedureStep(action="Enter the sale amount and save the entry.", wait_for="Saved")
        ],
    )
    found = texts(run(_script(stage), LintContext(), ids=["several_actions"]))
    assert [f.partition(": ")[0] for f in found] == ["stages.0.procedure.0.action"]


def test_an_example_led_script_still_forbids_a_reaction_to_open() -> None:
    stage = ConversationStage(
        id="open",
        name="Open the app",
        instruction="Help them open the app.",
        step=1,
        examples={"en-IN": StepExamples(turns=["Open the app.", "Tap the app.", "Find the app."])},
    )
    body = compile_call_script(
        CallScript(
            schema_version=2,
            stages=[stage],
            step_outcomes=[StepOutcome(step=1, outcome="The app is open.")],
        ),
        languages=("en-IN",),
    )
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="B",
        direction="inbound",
        language_primary="en-IN",
        system_prompt=body,
        opening_line="",
        call_is_recorded=True,
    )
    prompt = compose_engine_prompt(cfg)
    assert "No reaction to open; no two replies start or end alike." in prompt
    assert prompt.count("no two replies start or end alike") == 1
