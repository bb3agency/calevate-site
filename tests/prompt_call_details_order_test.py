"""Every per-call value in an agent's instructions comes after every fixed line (D-814).

ThinnestAI caches the prompt from its start up to the first value it fills per call
(VENDOR-STATED, ThinnestAI email of 18 Oct 2026), so a value inside our rules would leave the
rules after it outside the cache on every turn. These tests compose the instructions the way
a ThinnestAI publish does (`agents/service._to_config`) and check where the values sit.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from apps.api.agents.service import _to_config
from apps.api.engine.fake import FakeEngine
from apps.api.engine.hosted_platform import THINNEST_LIMITS
from apps.api.engine.thinnest import THINNEST_CAPABILITIES
from calevate_shared.engine import (
    CALLER_HIDDEN_LINE,
    CALLER_HIDDEN_VARIABLE,
    CALLER_MEMORY_GUIDANCE,
    CONFIDENTIALITY_MARKER,
    FORWARDED_LINE_RULE,
    LAYER_SEPARATOR,
    NAME_LINE,
    NAME_VARIABLE,
    THIS_CALL_HEADER,
    TODAY_LINE,
    TODAY_VARIABLE,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
    without_this_call,
)

#: A value the engine fills per call: its `{{name}}` syntax, or our own memory slot.
_PER_CALL = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}|\{caller_memory\}")


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Reception",
        "direction": "inbound",
        "language_primary": "te-IN",
        "languages_extra": None,
        "prompt": "[IDENTITY] Reception for the shop\n[TASK FLOW]\nGreet, then help.\n",
        "ai_disclosure_line": "This is an AI assistant.",
        "ai_disclosure_enabled": True,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": True,
        "caller_memory_notice_line": "I keep a short note of what you ask about.",
        "caller_memory_enabled": True,
        "forwarded_line": True,
        "stt_provider": None,
        "stt_model": None,
        "llm_model": None,
        "organization_llm_model": None,
        "tts_provider": None,
        "tts_voice": None,
        "max_call_duration_s": 600,
    }
    return {**row, **over}


def _thinnest_config(**over: Any) -> AgentConfig:
    engine = FakeEngine(name="thinnest", capabilities=THINNEST_CAPABILITIES)
    return _to_config(uuid.uuid4(), _row(**over), engine=engine)  # type: ignore[arg-type]


def test_the_per_call_values_come_after_every_fixed_line() -> None:
    cfg = _thinnest_config()
    prompt = compose_engine_prompt(cfg)
    first_value = _PER_CALL.search(prompt)
    assert first_value is not None
    assert first_value.group(0) == "{{" + TODAY_VARIABLE + "}}"
    # Everything from the first value on is the per-call section, the last layer.
    layer, text = engine_prompt_layers(cfg)[-1]
    assert layer == "this_call"
    assert prompt.endswith(LAYER_SEPARATOR + text)
    assert first_value.start() > prompt.index(THIS_CALL_HEADER)
    assert prompt.index(THIS_CALL_HEADER) > prompt.index(TRUTHFUL_ANSWER_MARKER)
    assert prompt.index(TRUTHFUL_ANSWER_MARKER) > prompt.index(CONFIDENTIALITY_MARKER)
    # The rule that reads the value stays with the other rules, before the floor.
    assert prompt.index(FORWARDED_LINE_RULE) < prompt.index(CONFIDENTIALITY_MARKER)
    assert text == f"{THIS_CALL_HEADER}\n{TODAY_LINE}\n{NAME_LINE}\n{CALLER_HIDDEN_LINE}"


def test_on_thinnest_the_memory_is_the_engines_and_every_value_is_one_it_fills() -> None:
    cfg = _thinnest_config()
    assert THINNEST_LIMITS.remembers_callers and cfg.caller_memory_in_engine
    prompt = compose_engine_prompt(cfg)
    # Only values the dial (`start_outbound_call`) or the lookup (`worker/engine_lookups`)
    # sends.
    assert [m.group(0) for m in _PER_CALL.finditer(prompt)] == [
        "{{" + name + "}}" for name in (TODAY_VARIABLE, NAME_VARIABLE, CALLER_HIDDEN_VARIABLE)
    ]
    # The switch still reaches the engine as its recap setting (`voice.pastConversations`).
    assert cfg.caller_memory_enabled


def test_an_engine_without_memory_of_its_own_keeps_our_memory_section() -> None:
    cfg = _to_config(uuid.uuid4(), _row(), engine=FakeEngine())  # type: ignore[arg-type]
    assert not cfg.caller_memory_in_engine
    assert CALLER_MEMORY_GUIDANCE in compose_engine_prompt(cfg)


def test_an_agent_without_a_forwarded_line_reads_only_the_date_and_name() -> None:
    cfg = _thinnest_config(forwarded_line=False)
    layers = engine_prompt_layers(cfg)
    assert layers[-2][0] == "truthful_answers"
    assert layers[-1] == ("this_call", f"{THIS_CALL_HEADER}\n{TODAY_LINE}\n{NAME_LINE}")
    assert CALLER_HIDDEN_VARIABLE not in compose_engine_prompt(cfg)


def test_the_section_after_the_truthful_answers_holds_values_and_no_instruction() -> None:
    """The truthful-answer block stays the last instruction (hard rule 5) because what follows
    it is labelled values only (D-888 put today's date and the name there for every agent)."""
    for forwarded in (True, False):
        layer, text = engine_prompt_layers(_thinnest_config(forwarded_line=forwarded))[-1]
        header, *lines = text.split("\n")
        assert layer == "this_call" and header == THIS_CALL_HEADER
        assert lines and all(re.fullmatch(r"[A-Z][a-z ]+: \{\{[a-z_]+\}\}", line) for line in lines)
        prompt = compose_engine_prompt(_thinnest_config(forwarded_line=forwarded))
        assert without_this_call(prompt) + LAYER_SEPARATOR + text == prompt
