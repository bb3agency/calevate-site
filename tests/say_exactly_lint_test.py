"""The script checks read a "say" scenario's description as an instruction (D-1035): the
words it says are its script line, so the description is never judged as a spoken line."""

from __future__ import annotations

from apps.api.agents.script_lint import instruction_fields, spoken_fields, step_line
from calevate_shared.call_script import CallScript, ConversationStage


def _script(stage: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, stages=[stage])


def test_a_say_scenarios_description_is_an_instruction() -> None:
    stage = ConversationStage(
        id="remind",
        name="Does not remember us",
        mode="say",
        instruction="Remind them who we are.",
        step=1,
        scripts={"en-IN": "We spoke last week about your order."},
    )
    script = _script(stage)
    assert ("stages.0.instruction", stage.instruction) in instruction_fields(script)
    assert ("stages.0.instruction", stage.instruction) not in spoken_fields(script)
    assert step_line(script, 0)[0] == "stages.0.sounds_like"


def test_a_say_section_from_before_scenarios_is_still_a_spoken_line() -> None:
    stage = ConversationStage(
        id="greet", name="Greet", mode="say", instruction="Hello, this is the shop."
    )
    script = _script(stage)
    assert ("stages.0.instruction", stage.instruction) in spoken_fields(script)
    assert ("stages.0.instruction", stage.instruction) not in instruction_fields(script)
    assert step_line(script, 0) == ("stages.0.instruction", stage.instruction)
