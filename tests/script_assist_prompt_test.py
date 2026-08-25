"""The AI script-writing assist's two credential-free artefacts: its prompt and its parser.

CI holds no model key, so what it CAN gate is the same as for extraction
(`extraction_prompt_test.py`): the instruction's rules, and the normaliser that turns a
model's JSON into a validated `CallScript`. Both run with no network and no database.
"""

from __future__ import annotations

from apps.workers.script_assist import _SYSTEM_INSTRUCTION, _script_from_model_json


def test_prompt_states_its_rules() -> None:
    text = _SYSTEM_INSTRUCTION.lower()
    # Telugu-first, phone-appropriate.
    assert "telugu" in text
    # No invented facts — the truth-boundary rule.
    assert "never invent" in text
    # The platform owns the AI/recording answer, not the draft.
    assert "recording" in text
    # A merge field is offered by example.
    assert "{{lead_name}}" in _SYSTEM_INSTRUCTION
    # The output contract is JSON with the three keys the parser reads.
    assert "opening_line" in _SYSTEM_INSTRUCTION
    assert "steps" in _SYSTEM_INSTRUCTION
    assert "faqs" in _SYSTEM_INSTRUCTION


def test_parser_builds_a_validated_call_script() -> None:
    script = _script_from_model_json(
        {
            "opening_line": "Namaste, welcome.",
            "steps": ["Ask the caller's need.", "Confirm it back."],
            "faqs": [{"question": "Hours?", "answer": "9 to 6."}],
        }
    )
    assert script.opening_line == "Namaste, welcome."
    assert [s.instruction for s in script.steps] == ["Ask the caller's need.", "Confirm it back."]
    assert script.faqs[0].question == "Hours?"
    assert script.raw_override is None  # structured, not raw


def test_parser_tolerates_a_malformed_answer() -> None:
    # Empty steps/FAQ entries are dropped; a non-dict FAQ is skipped; a missing key is fine.
    script = _script_from_model_json(
        {
            "opening_line": 123,  # wrong type -> empty opening
            "steps": ["Real step.", "", "  "],
            "faqs": [
                "not a dict",
                {"question": "Q", "answer": ""},
                {"question": "Q2", "answer": "A2"},
            ],
        }
    )
    assert script.opening_line == ""
    assert [s.instruction for s in script.steps] == ["Real step."]
    assert [(f.question, f.answer) for f in script.faqs] == [("Q2", "A2")]


def test_parser_on_empty_json_is_an_empty_script() -> None:
    script = _script_from_model_json({})
    assert script.opening_line == ""
    assert script.steps == []
    assert script.faqs == []
