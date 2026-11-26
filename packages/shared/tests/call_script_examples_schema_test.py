"""A step's example turns per language (`StepExamples`, script rebuild 26 Nov 2026): the shape
the writer fills and the compiler reads, and old scripts loading without them."""

from __future__ import annotations

import pytest
from calevate_shared.call_script import (
    MAX_STEP_EXAMPLE_TURNS,
    STEP_EXAMPLE_MAX,
    CallScript,
    ConversationStage,
    StepExamples,
    script_text,
)
from pydantic import ValidationError

#: A stage as scripts were stored before examples existed: `sounds_like`, no `examples` key.
OLD_STAGE = {
    "id": "intro",
    "name": "Introduction",
    "instruction": "Ask whether they registered on the website.",
    "sounds_like": "Did you register on the website?",
}


def test_an_old_script_loads_unchanged_and_round_trips() -> None:
    raw = {"schema_version": 2, "stages": [OLD_STAGE]}
    script = CallScript.model_validate(raw)
    stage = script.stages[0]
    assert stage.examples == {}
    assert not stage.has_examples
    assert stage.sounds_like == OLD_STAGE["sounds_like"]
    again = CallScript.model_validate_json(script.model_dump_json())
    assert again == script


def test_examples_round_trip_by_language() -> None:
    said = StepExamples(
        turns=["Please open Chrome on your phone.", "Open Chrome first.", "Start with Chrome."],
        confused="Chrome, the browser on your phone. Open it first.",
        stuck="Look for a round icon named Chrome.",
        busy="When would be a better time to call you?",
    )
    stage = ConversationStage.model_validate({**OLD_STAGE, "examples": {"en-IN": said}})
    script = CallScript(schema_version=2, stages=[stage])
    again = CallScript.model_validate_json(script.model_dump_json())
    assert again.stages[0].examples["en-IN"] == said
    assert again.stages[0].has_examples


def test_blank_turns_and_empty_languages_are_dropped() -> None:
    stage = ConversationStage.model_validate(
        {
            **OLD_STAGE,
            "examples": {
                "en-IN": {"turns": ["  Open   Chrome. ", "", "  "]},
                "te-IN": {"turns": [], "confused": " "},
            },
        }
    )
    assert stage.examples == {"en-IN": StepExamples(turns=["Open Chrome."])}


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a language"):
        ConversationStage.model_validate({**OLD_STAGE, "examples": {"xx-XX": {"turns": ["Hi."]}}})


def test_at_most_five_turns() -> None:
    StepExamples(turns=["One."] * MAX_STEP_EXAMPLE_TURNS)
    with pytest.raises(ValidationError):
        StepExamples(turns=["One."] * (MAX_STEP_EXAMPLE_TURNS + 1))


@pytest.mark.parametrize("field", ["confused", "stuck", "busy"])
def test_each_line_is_bounded(field: str) -> None:
    StepExamples.model_validate({field: "a" * STEP_EXAMPLE_MAX})
    with pytest.raises(ValidationError):
        StepExamples.model_validate({field: "a" * (STEP_EXAMPLE_MAX + 1)})


def test_a_turn_is_bounded() -> None:
    with pytest.raises(ValidationError, match="at most"):
        StepExamples(turns=["a" * (STEP_EXAMPLE_MAX + 1)])


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        StepExamples.model_validate({"turns": [], "reaction": "OK."})


def test_examples_count_as_words_the_owner_wrote() -> None:
    stage = ConversationStage.model_validate(
        {**OLD_STAGE, "examples": {"en-IN": {"turns": ["Open Chrome now."], "stuck": "Tap it."}}}
    )
    text = script_text(CallScript(schema_version=2, stages=[stage]))
    assert "Open Chrome now." in text
    assert "Tap it." in text
