"""An agent's extra languages reach the call (D-666).

`agents.languages_extra` was stored by the admin intake and read by nothing on the way to
a call. Now:

1. `_to_config` publishes it, narrowed to the languages the product sells, never the
   primary, each once;
2. `compose_engine_prompt` names the languages the agent may answer in, and keeps the
   speaking rules and the truthful-answer floor binding in every one of them.

A one-language agent's prompt is unchanged, so only agents with extras get a new prompt
hash.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents.languages import published_extra_languages
from apps.api.agents.service import _to_config
from apps.api.engine import get_engine
from calevate_shared.engine import (
    CLIENT_SCRIPT_OPEN,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    truthful_answer_directive,
)


def _agent(**overrides: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "name": "Reception",
        "direction": "inbound",
        "language_primary": "te-IN",
        "system_prompt": "You answer the clinic's phone.",
        "opening_line": "This is an AI assistant.",
    }
    base.update(overrides)
    return AgentConfig(**base)


# ------------------------------------------------------------- the publish-side filter


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, []),
        ([], []),
        (["hi-IN", "en-IN"], ["hi-IN", "en-IN"]),
        # The primary is not an EXTRA, and a repeat is one language.
        (["te-IN", "hi-IN", "hi-IN"], ["hi-IN"]),
        # Not sold: no disclosure sentences exist for it, so it is not published.
        (["ta-IN", "en-IN", "Hindi"], ["en-IN"]),
    ],
)
def test_only_offered_languages_other_than_the_primary_are_published(
    stored: list[str] | None, expected: list[str]
) -> None:
    assert published_extra_languages("te-IN", stored) == expected


def test_to_config_carries_the_stored_extras() -> None:
    agent: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Reception",
        "direction": "inbound",
        "language_primary": "te-IN",
        "languages_extra": ["hi-IN", "te-IN"],
        "prompt": "You answer the clinic's phone.",
        "ai_disclosure_line": "This is an AI assistant.",
        "ai_disclosure_enabled": True,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": True,
        "caller_memory_notice_line": "I keep a short note of what you ask about.",
        "caller_memory_enabled": False,
        "stt_provider": "sarvam",
        "stt_model": "saaras:v4",
        "llm_model": None,
        "organization_llm_model": None,
        "tts_provider": "cartesia",
        "tts_voice": None,
        "max_call_duration_s": 600,
    }
    cfg = _to_config(uuid.uuid4(), agent, engine=get_engine())  # type: ignore[arg-type]
    assert cfg.languages_extra == ["hi-IN"]


# ------------------------------------------------------------------- the prompt


def test_a_one_language_agent_composes_exactly_as_before() -> None:
    prompt = compose_engine_prompt(_agent())
    assert "--- LANGUAGES ---" not in prompt


def test_an_agent_with_extras_is_told_which_languages_it_may_answer_in() -> None:
    prompt = compose_engine_prompt(_agent(languages_extra=["hi-IN", "en-IN"]))

    assert "--- LANGUAGES ---" in prompt
    assert "Your main language is Telugu;" in prompt
    assert "Hindi and English" in prompt
    # Platform-written, so OUTSIDE the client fence, after the speaking rules.
    assert prompt.index(VOICE_STYLE_GUIDANCE) < prompt.index("--- LANGUAGES ---")
    assert prompt.index("--- LANGUAGES ---") < prompt.index(CLIENT_SCRIPT_OPEN)
    # Hard rule 5: the floor is still the last word, in every language.
    assert prompt.endswith(truthful_answer_directive(call_is_recorded=True))
    assert TRUTHFUL_ANSWER_MARKER in prompt
    assert "in any language" in prompt
    assert "Every rule here applies in every language." in prompt
    assert "Reply in the language the caller speaks and switch when they do." in prompt
    # The spoken-output rules are unchanged.
    assert "No markdown" in prompt


def test_one_extra_language_reads_as_one_name() -> None:
    prompt = compose_engine_prompt(_agent(languages_extra=["hi-IN"]))
    assert "you also speak Hindi." in prompt
