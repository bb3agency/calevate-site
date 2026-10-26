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

from apps.api.engine.hosted_platform import PLATFORM_AGENT_VALUES

#: The keys of the record, which `ops/reply_times.SETTING_KEYS` splits by.
TURN_DETECTION: Final = "turn_detection"
TURN_SILENCE_MS: Final = "turn_silence_ms"
EARLY_ANSWERS: Final = "early_answers"
FILLER_DELAY_MS: Final = "filler_delay_ms"
KNOWN_FACTS: Final = "known_facts"
KNOWN_FACTS_CHARS: Final = "known_facts_chars"


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


def stamp_of(config: AgentConfig, engine: VoiceEngine) -> dict[str, Any]:
    """The record for one published config."""
    filler = PLATFORM_AGENT_VALUES.get(engine.name, {}).get("thinkingDelayMs")
    chars = _known_facts_chars(config.system_prompt or "")
    return {
        TURN_DETECTION: config.turn_detection,
        TURN_SILENCE_MS: config.turn_silence_ms,
        EARLY_ANSWERS: config.early_answers,
        FILLER_DELAY_MS: filler if isinstance(filler, int) else None,
        KNOWN_FACTS: chars > 0,
        KNOWN_FACTS_CHARS: chars,
    }


__all__ = [
    "EARLY_ANSWERS",
    "FILLER_DELAY_MS",
    "KNOWN_FACTS",
    "KNOWN_FACTS_CHARS",
    "TURN_DETECTION",
    "TURN_SILENCE_MS",
    "stamp_of",
]
