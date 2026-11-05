"""The Rytu Khata campaign calls of 4 Nov 2026 (D-969): an outbound agent that went straight to
its question with no name and no "is this a good time", explained the whole app in one turn,
read the business's WhatsApp number fast, never asked the business's own questions, said
"call whenever" to a caller who would call later, and closed with a sentence about the note
it keeps. The code keeps the structure only; no spoken line here is ours (D-915)."""

from __future__ import annotations

from typing import Any

from calevate_shared.call_script import (
    COLLECT_HEADER,
    CallScript,
    CollectField,
    compile_call_script,
)
from calevate_shared.engine import (
    CALL_BACK_TIME_RULE,
    COLLECT_RULE,
    PLACED_CALL_PERMISSION_RULE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)

OPENING = "Hello, calling from Rytu Khata. Have you installed the app?"
FIELDS = (CollectField(label="Satisfaction level"), CollectField(label="Suggestions"))


def _cfg(**over: Any) -> AgentConfig:
    fields: dict[str, Any] = {
        "tenant_id": "t",
        "agent_id": "a",
        "name": "Varsha",
        "business": "Rytu Khata",
        "direction": "outbound",
        "language_primary": "te-IN",
        "system_prompt": compile_call_script(
            CallScript(schema_version=2, opening_line=OPENING), collect=FIELDS
        ),
        "opening_line": "",
        "call_is_recorded": True,
    }
    return AgentConfig(**{**fields, **over})


def _layer(cfg: AgentConfig, name: str) -> str:
    return dict(engine_prompt_layers(cfg)).get(name, "")


# --- 1. a placed call asks whether now suits, by name --------------------------------------


def test_a_placed_call_asks_if_now_is_a_good_time_and_uses_the_name() -> None:
    notices = _layer(_cfg(), "notices")
    assert PLACED_CALL_PERMISSION_RULE in notices
    assert "good time" in PLACED_CALL_PERMISSION_RULE
    assert "THIS CALL's name" in PLACED_CALL_PERMISSION_RULE
    assert PLACED_CALL_PERMISSION_RULE not in compose_engine_prompt(_cfg(direction="inbound"))


# --- 2. one step at a time, for every agent ------------------------------------------------


def test_every_agent_gives_one_step_a_turn_and_never_asks_did_you_understand() -> None:
    prompt = compose_engine_prompt(_cfg(direction="inbound"))
    assert 'Explaining steps? One a turn, wait until done, never "understood?"' in prompt


# --- 3. numbers digit by digit, the first time ---------------------------------------------


def test_numbers_are_read_digit_by_digit_in_two_fives_from_the_first_time() -> None:
    assert "first time too: digit by digit, a comma after each" in VOICE_STYLE_GUIDANCE
    assert "a mobile five, full stop, five; offer to repeat" in VOICE_STYLE_GUIDANCE


# --- 4. later means a day, a time and a booked call back ----------------------------------


def test_later_asks_a_day_and_time_and_books_only_where_call_backs_are_kept() -> None:
    assert "day and time, say it back, book" in CALL_BACK_TIME_RULE
    assert CALL_BACK_TIME_RULE in _layer(_cfg(), "what_you_can_do")
    assert CALL_BACK_TIME_RULE not in _layer(_cfg(callbacks_offered=False), "what_you_can_do")


# --- 5. the business's own questions are asked --------------------------------------------


def test_the_business_questions_are_asked_one_a_turn_before_the_close() -> None:
    script = _cfg().system_prompt
    assert f"{COLLECT_HEADER} Ask these." in script
    assert "when it fits" not in script
    assert COLLECT_RULE in _layer(_cfg(), "what_you_can_do")
    assert "Before closing, ask each" in COLLECT_RULE and "one a turn" in COLLECT_RULE
    bare = _cfg(system_prompt=compile_call_script(CallScript(schema_version=2)))
    assert COLLECT_RULE not in _layer(bare, "what_you_can_do")


def test_a_script_compiled_with_the_old_header_still_gets_the_rule() -> None:
    old = "[WHAT TO COLLECT] Only these, when it fits.\n- Satisfaction level"
    assert COLLECT_RULE in _layer(_cfg(system_prompt=old), "what_you_can_do")
