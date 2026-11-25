"""The founder's corrected Rytu Khata request (25 Nov 2026) is read as written."""

from __future__ import annotations

from pathlib import Path

from apps.api.agents.mistake_lints import _moved_on_unconfirmed
from apps.api.agents.owner_plan import PlannedStep, owner_plan
from calevate_shared.call_script import CallScript, ConversationStage, StepOutcome

ASK = (Path(__file__).parent / "fixtures/owner_plans/rytu_khata_2026_11_25.txt").read_text(
    encoding="utf-8"
)


def _plan() -> dict[str, PlannedStep]:
    plan = owner_plan(" ".join(ASK.split()))
    assert plan is not None
    return {step.name: step for step in plan.steps}


def test_a_long_last_resort_bullet_is_a_way_out_not_part_of_the_outcome() -> None:
    steps = _plan()
    assert steps["Login"].outcome == "They are logged in."
    assert [(b.when, b.goes_to) for b in steps["Login"].branches] == [
        ("Still cannot log in after being guided step by step", "call_back")
    ]
    home = [(b.when, b.goes_to) for b in steps["App on the home screen"].branches]
    assert home == [
        ("Already has it", "Login"),
        ("Still cannot open the website after being guided step by step", "call_back"),
    ]


def test_the_rules_after_the_steps_are_no_way_out_of_the_side_step() -> None:
    side = _plan()["Not registered"]
    assert [(b.when, b.goes_to) for b in side.branches] == [
        ("Yes", "App on the home screen"),
        ("No", "end"),
    ]


def test_a_step_with_an_otherwise_is_not_pushed_to_add_a_call_back() -> None:
    def stage(sid: str, otherwise: str = "") -> ConversationStage:
        return ConversationStage.model_validate(
            {"id": sid, "name": sid, "instruction": "Guide them.", "otherwise": otherwise}
        )

    outcome = [StepOutcome(step=1, outcome="Their farm is added.")]
    guided = CallScript(
        schema_version=2, stages=[stage("s1", "s2"), stage("s2")], step_outcomes=outcome
    )
    assert _moved_on_unconfirmed(guided, None) == []  # type: ignore[arg-type]
    loose = CallScript(schema_version=2, stages=[stage("s1"), stage("s2")], step_outcomes=outcome)
    assert _moved_on_unconfirmed(loose, None)  # type: ignore[arg-type]
