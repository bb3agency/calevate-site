"""A scenario's "Say this line exactly" switch (D-1035): `mode` "say" on a scenario asks for
its script line, word for word, never its English description; "guide" compiles as before."""

from __future__ import annotations

import pytest
from calevate_shared.call_script import (
    SAY_EXACT_LINES,
    SAY_EXACT_STEP,
    SCENARIO_HEADER,
    SCENARIO_LEAD,
    STAGE_DETAIL_MAX,
    CallScript,
    ConversationStage,
    compile_call_script,
    native_steps,
    says_instruction,
    says_scenario_line,
    scenario_pointer,
)
from pydantic import ValidationError

DESCRIPTION = "They do not remember us; remind them who we are."
LINE = "We spoke last week about your order."


def _scenario(**fields: object) -> ConversationStage:
    data: dict[str, object] = {
        "id": "remind",
        "name": "Does not remember us",
        "instruction": DESCRIPTION,
        "step": 2,
        "scripts": {"en-IN": LINE},
    }
    data.update(fields)
    return ConversationStage.model_validate(data)


def _body(stage: ConversationStage) -> str:
    return compile_call_script(CallScript(schema_version=2, stages=[stage]))


def _scenario_section(body: str) -> str:
    return body[body.index(f"{SCENARIO_HEADER} ") :]


def test_guide_compiles_as_it_did_before_the_switch() -> None:
    body = _body(_scenario())
    pointer = scenario_pointer("Does not remember us")
    assert f"1. Does not remember us: {DESCRIPTION} {pointer}" in body
    assert _scenario_section(body).splitlines()[:3] == [
        f"{SCENARIO_HEADER} {SCENARIO_LEAD}",
        "Does not remember us:",
        f'English (India): "{LINE}"',
    ]
    assert SAY_EXACT_STEP not in body
    assert SAY_EXACT_LINES not in body


def test_say_asks_for_the_line_word_for_word_and_never_speaks_the_description() -> None:
    stage = _scenario(mode="say")
    body = _body(stage)
    pointer = scenario_pointer("Does not remember us")
    assert f"1. Does not remember us: {DESCRIPTION} {SAY_EXACT_STEP} {pointer}" in body
    assert f'Say: "{DESCRIPTION}"' not in body
    # The general lead is unchanged; the scenario's own block overrides it.
    assert _scenario_section(body).splitlines()[:4] == [
        f"{SCENARIO_HEADER} {SCENARIO_LEAD}",
        "Does not remember us:",
        SAY_EXACT_LINES,
        f'English (India): "{LINE}"',
    ]
    assert says_scenario_line(stage)
    assert not says_instruction(stage)


def test_say_reaches_the_engine_step_too() -> None:
    (step,) = native_steps(CallScript(schema_version=2, stages=[_scenario(mode="say")]))
    assert SAY_EXACT_STEP in step.detail
    assert f'Say: "{DESCRIPTION}"' not in step.detail


def test_a_section_drawn_before_scenarios_still_says_its_instruction() -> None:
    legacy = ConversationStage(
        id="greet", name="Greet", mode="say", instruction="Hello, this is the shop."
    )
    assert "1. Greet: Say: \"Hello, this is the shop.\"" in _body(legacy)
    assert says_instruction(legacy)


def test_a_say_scenario_with_no_line_yet_is_followed_in_own_words() -> None:
    stage = _scenario(mode="say", scripts={})
    body = _body(stage)
    assert f"1. Does not remember us: {DESCRIPTION}" in body
    assert "Say:" not in body
    assert SAY_EXACT_STEP not in body
    assert not says_instruction(stage)
    assert not says_scenario_line(stage)


def test_the_say_sentence_counts_against_the_step_budget() -> None:
    room = STAGE_DETAIL_MAX - len(f" {scenario_pointer('Does not remember us')}")
    fits = "x" * room
    _scenario(instruction=fits)
    with pytest.raises(ValidationError):
        _scenario(instruction=fits, mode="say")
