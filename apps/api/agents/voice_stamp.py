"""The call-handling settings an agent was published with, as one small record (D-896).

Written onto `agents.voice_settings` by `service.publish_agent` from the config it sent, and
copied onto each call when its row is first written (`workers/pipeline._upsert_call_row`),
so the admin Voice response time screen can split reply times by what a call actually ran
on (`ops/reply_times.py`). Read off the CONFIG, not the console, for the reason the voice
mirror is: the config is what the engine was handed.

Closed-set values and numbers only, never text: the record is read across clients.
"""

from __future__ import annotations

from typing import Any, Final

from calevate_shared.call_script import KNOWN_FACTS_HEADER
from calevate_shared.engine import AgentConfig, VoiceEngine

from apps.api.agents.hosted_voices import hosted_voice_id
from apps.api.engine.hosted_platform import PLATFORM_AGENT_VALUES

#: The keys of the record, which `ops/reply_times.SETTING_KEYS` splits by.
TURN_DETECTION: Final = "turn_detection"
TURN_SILENCE_MS: Final = "turn_silence_ms"
EARLY_ANSWERS: Final = "early_answers"
FILLER_DELAY_MS: Final = "filler_delay_ms"
KNOWN_FACTS: Final = "known_facts"
KNOWN_FACTS_CHARS: Final = "known_facts_chars"
#: Our catalogue id of the voice the agent was published with (`agents/hosted_voices`), so
#: the healer can tell which voice a call spoke on after the agent's voice moved (D-987).
ENGINE_VOICE: Final = "engine_voice"


def _known_facts_chars(prompt: str) -> int:
    """Characters of the known-facts section in a script, header line included."""
    total = 0
    inside = False
    for line in prompt.splitlines():
        if line.startswith("["):
            inside = line.startswith(KNOWN_FACTS_HEADER)
        if inside:
            total += len(line) + 1
    return total


def _voice_of(config: AgentConfig) -> str | None:
    if config.engine_byok_voice_id:
        return hosted_voice_id("byok", config.engine_byok_voice_id)
    if config.engine_voice_id:
        return hosted_voice_id("engine", config.engine_voice_id)
    return None


def stamp_of(config: AgentConfig, engine: VoiceEngine) -> dict[str, Any]:
    """The record for one published config."""
    # Only an engine that speaks our filler timing (`thinnest._agent_body`) has one to record.
    filler = config.thinking_delay_ms if engine.name in PLATFORM_AGENT_VALUES else None
    chars = _known_facts_chars(config.system_prompt or "")
    return {
        TURN_DETECTION: config.turn_detection,
        TURN_SILENCE_MS: config.turn_silence_ms,
        EARLY_ANSWERS: config.early_answers,
        FILLER_DELAY_MS: filler,
        KNOWN_FACTS: chars > 0,
        KNOWN_FACTS_CHARS: chars,
        ENGINE_VOICE: _voice_of(config),
    }


__all__ = [
    "EARLY_ANSWERS",
    "ENGINE_VOICE",
    "FILLER_DELAY_MS",
    "KNOWN_FACTS",
    "KNOWN_FACTS_CHARS",
    "TURN_DETECTION",
    "TURN_SILENCE_MS",
    "stamp_of",
]
