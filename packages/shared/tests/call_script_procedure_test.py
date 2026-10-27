"""A section's step-by-step list (D-908): compiled into the instructions text under the
section's name, pointed at from the section's own step, never into its 600 characters."""

from __future__ import annotations

import pytest
from calevate_shared.call_script import (
    CONVERSATION_HEADER,
    MAX_PROCEDURE_STEPS,
    PROCEDURE_HEADER,
    PROCEDURE_STEP_MAX,
    STAGE_DETAIL_MAX,
    CallScript,
    ConversationStage,
    ProcedureStep,
    compile_call_script,
    native_steps,
    procedure_pointer,
    script_text,
    unplaced_lines,
    without_outline,
)
from pydantic import ValidationError

INSTALL = [
    ProcedureStep(action="Ask them to open Chrome on their phone.", wait_for="they say it is open"),
    ProcedureStep(action="Ask them to type rytukhata.app in the address bar."),
    ProcedureStep(
        action="Ask them to tap Add to Home screen.", wait_for="the icon is on the screen"
    ),
]


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, stages=list(stages))


def _install(**update: object) -> ConversationStage:
    stage = ConversationStage(
        id="install",
        name="Install the app",
        instruction="Help them put the app on their phone.",
        procedure=INSTALL,
    )
    return stage.model_copy(update=update)


def test_the_list_is_compiled_under_the_section_name_in_order() -> None:
    body = compile_call_script(_script(_install()))
    section = body[body.index(f"\n{PROCEDURE_HEADER} ") + 1 :]
    assert section.splitlines()[1:5] == [
        "Install the app:",
        "1. Ask them to open Chrome on their phone. Wait for: they say it is open",
        "2. Ask them to type rytukhata.app in the address bar.",
        "3. Ask them to tap Add to Home screen. Wait for: the icon is on the screen",
    ]
    # After the outline, so the outline still reads first.
    assert body.index(CONVERSATION_HEADER) < body.index(f"\n{PROCEDURE_HEADER} ")


def test_the_engine_step_points_at_the_list_and_the_list_stays_in_the_text() -> None:
    script = _script(_install())
    (step,) = native_steps(script)
    assert step.detail.endswith(procedure_pointer("Install the app"))
    assert "rytukhata.app" not in step.detail
    # An engine with its own steps drops the outline from the text, never the lists.
    body = without_outline(compile_call_script(script))
    assert CONVERSATION_HEADER not in body
    assert "2. Ask them to type rytukhata.app in the address bar." in body


def test_a_section_without_a_list_compiles_as_before() -> None:
    plain = ConversationStage(id="greet", name="Greet", instruction="Say hello.")
    body = compile_call_script(_script(plain))
    assert PROCEDURE_HEADER not in body
    (step,) = native_steps(_script(plain))
    assert step.detail == "Say hello."


def test_the_pointer_counts_inside_the_600_characters() -> None:
    room = STAGE_DETAIL_MAX - len(procedure_pointer("Install the app")) - 1
    _install(instruction="x" * room).model_validate(_install(instruction="x" * room).model_dump())
    with pytest.raises(ValidationError, match="600"):
        ConversationStage.model_validate(_install(instruction="x" * (room + 1)).model_dump())


def test_the_list_and_each_step_are_bounded() -> None:
    too_many = [ProcedureStep(action=f"Step {i}") for i in range(MAX_PROCEDURE_STEPS + 1)]
    with pytest.raises(ValidationError):
        ConversationStage.model_validate(_install(procedure=too_many).model_dump())
    with pytest.raises(ValidationError):
        ProcedureStep(action="x" * (PROCEDURE_STEP_MAX + 1))
    with pytest.raises(ValidationError):
        ProcedureStep(action="")
    assert ProcedureStep(action="  tap\n  Save ").action == "tap Save"


def test_a_converted_prompt_counts_its_list_as_placed() -> None:
    script = _script(_install())
    assert "Add to Home screen" in script_text(script)
    raw = "1. Ask them to tap Add to Home screen."
    assert unplaced_lines(raw, script) == []
