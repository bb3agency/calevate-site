"""The AI script-writing assist's two credential-free artefacts: its prompt and its parser.

CI holds no model key, so what it CAN gate is the same as for extraction
(`extraction_prompt_test.py`): the instruction's rules, and the normaliser that turns a
model's JSON into a validated `CallScript`. Both run with no network and no database.
"""

from __future__ import annotations

from apps.workers.script_assist import (
    _DRAFT_SCHEMA,
    _SYSTEM_INSTRUCTION,
    ScriptBrief,
    _script_from_model_json,
)


def test_prompt_states_its_rules() -> None:
    text = _SYSTEM_INSTRUCTION.lower()
    # Instructions in English, spoken lines in the call's language and register (decision 3).
    assert "plain english" in text and "call language" in text
    assert "never formal written language" in text
    # No invented facts — the truth-boundary rule.
    assert "never invent" in text
    # The platform owns the AI/recording answer and the call-back rule, not the draft.
    assert "recording" in text and "call backs" in text
    # A merge field is offered by example.
    assert "{{lead_name}}" in _SYSTEM_INSTRUCTION
    # The output contract covers every v2 section the parser reads.
    for key in ("business_line", "stages", "objections", "quick_facts", "example_exchange"):
        assert key in _DRAFT_SCHEMA["properties"]  # type: ignore[operator]


def test_the_brief_carries_what_the_server_knows() -> None:
    message = ScriptBrief(
        business_name="Raghava Organics",
        business_type="retail",
        direction="outbound",
        language="te-IN",
        register="Neutral spoken Telugu",
        collect=("Name", "Area"),
        knowledge_titles=("Price list",),
        answers=(("what_you_offer", "Organic chilli and oils"),),
    ).user_message()
    assert "places calls to leads" in message
    assert "Details to collect: Name; Area" in message
    assert "Knowledge documents: Price list" in message
    assert "What do you sell or do? Organic chilli and oils" in message


def test_parser_builds_a_validated_v2_script() -> None:
    script = _script_from_model_json(
        {
            "business_line": "An organic shop",
            "opening_line": "Namaskaram andi.",
            "stages": [{"name": "Need", "instruction": "Ask the need.", "exit_when": "Known."}],
            "quick_facts": [{"question": "Hours?", "answer": "9 to 6."}],
            "example_exchange": [{"speaker": "agent", "text": "Cheppandi andi."}],
            "code_mix": "natural",
        }
    )
    assert script.schema_version == 2
    assert script.opening_line == "Namaskaram andi."
    assert [s.instruction for s in script.stages] == ["Ask the need."]
    assert script.faqs[0].question == "Hours?"
    assert script.example_needs_review is True
    assert script.raw_override is None


def test_parser_tolerates_a_malformed_answer() -> None:
    script = _script_from_model_json(
        {
            "opening_line": 123,
            "stages": ["not a dict", {"name": "", "instruction": "Real.", "exit_when": ""}],
            "quick_facts": [{"question": "Q", "answer": ""}, {"question": "Q2", "answer": "A2"}],
            "code_mix": "loud",
        }
    )
    assert script.opening_line == ""
    assert [s.name for s in script.stages] == ["Section 1"]
    assert [(f.question, f.answer) for f in script.faqs] == [("Q2", "A2")]
    assert script.style.code_mix == "natural"


def test_parser_on_empty_json_is_an_empty_v2_script() -> None:
    script = _script_from_model_json({})
    assert script.schema_version == 2 and script.stages == [] and script.faqs == []
    assert script.example_needs_review is False


def test_an_edit_keeps_the_current_script_and_its_section_ids() -> None:
    from apps.workers.script_assist import _edited_script
    from calevate_shared.call_script import CallScript, ConversationStage

    current = CallScript(
        schema_version=2,
        goal="Take orders.",
        stages=[ConversationStage(id="need", name="Need", instruction="Ask what they want.")],
    )
    edited = _edited_script({"goal": "Take orders warmly.", "unknown": 1}, current)
    assert edited is not None
    assert edited.goal == "Take orders warmly." and edited.stages[0].id == "need"
    # A shape no save would accept is no draft, never half an edit.
    assert _edited_script({"stages": [{"id": "Bad Id"}]}, current) is None
