"""The AI and recording notices said in the agent's own opening line (D-971).

Founder, 5 Nov 2026: "When an opening is saved, Pip weaves the notices into that agent's own
opening line in its own words, which the engine then speaks." The engine speaks the greeting
word for word (`snapshots/2026-10-29/pages/channels/voice.md:363-366`), so a notice the agent
says in its own words has to be written into that greeting before the call, not improvised
on it. No Indian rule prescribes the words of either notice (TCCCPR third amendment,
18 Sep 2026; DPDP Rules 2025 r.3; IT Rules amendment G.S.R. 120(E), 10 Feb 2026, which asks
for a "prominently prefixed audio disclosure" and names no wording).

The judgement "does this line say it" is a word list, not a model: it runs on every
composition of the first words, on every dial and on every read-back, where a model call has
no place. It fails safe: a line the list does not recognise keeps the agent's stored sentence
beside it (`engine.join_first_words`), so the notice is said twice at worst, never not at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Words that say "AI" in the languages agents speak. The staged languages write "AI" in
#: Latin letters (`compliance/disclosure.AI_DISCLOSURE_TEMPLATES`), which the first
#: alternatives match.
AI_WORDS: Final = re.compile(
    r"\bAI\b|\bA\.I\.|artificial|ఏఐ|ఏ\s?ఐ|కృత్రిమ|एआई|ए\.?\s?आई|कृत्रिम",
    re.IGNORECASE,
)
#: Words that say "recorded".
RECORDING_WORDS: Final = re.compile(r"record|రికార్డ్|రికార్డు|रिकॉर्ड|रेकॉर्ड", re.IGNORECASE)


def says_ai(text: str) -> bool:
    """Does `text` tell the caller they are speaking with an AI?"""
    return bool(AI_WORDS.search(text))


def says_recorded(text: str) -> bool:
    """Does `text` tell the caller the call is recorded?"""
    return bool(RECORDING_WORDS.search(text))


#: What a woven notice may add to the opening line's length. Both together take a 120-character
#: line to 200, ThinnestAI's greeting ceiling (`engine/thinnest.GREETING_MAX_CHARS`); the
#: publish still measures the real greeting against that ceiling.
WOVEN_AI_CHARS: Final = 50
WOVEN_RECORDING_CHARS: Final = 30

WOVEN_AI_RULE: Final = (
    "say in a few words of your own, in the call language, that they are speaking with an "
    "AI assistant"
)
WOVEN_RECORDING_RULE: Final = (
    "say in a few words of your own, in the call language, that the call is recorded"
)
NO_AI_RULE: Final = "say nothing about being an AI"
NO_RECORDING_RULE: Final = "say nothing about the call being recorded"


@dataclass(frozen=True, slots=True)
class WovenNotices:
    """Which notices the agent's switches turn on, so its opening line says them (`ai`,
    `recording`) or leaves them out. `recording` is False on an engine that records nothing:
    announcing a recording nobody makes is a false statement."""

    ai: bool
    recording: bool

    def rules(self) -> list[str]:
        return [
            WOVEN_AI_RULE if self.ai else NO_AI_RULE,
            WOVEN_RECORDING_RULE if self.recording else NO_RECORDING_RULE,
        ]

    def brief_note(self) -> str:
        """What a writer of the whole script is told about the opening line."""
        said = [
            words
            for on, words in (
                (self.ai, "that the caller is speaking with an AI assistant"),
                (self.recording, "that the call is recorded"),
            )
            if on
        ]
        if not said:
            return "The opening_line says nothing about being an AI or about recording."
        return (
            "The opening_line also says, in a few words of the agent's own in the call "
            f"language, {' and '.join(said)}; the engine speaks it word for word as the "
            "agent's first turn."
        )

    def matches(self, line: str) -> bool:
        """Does `line` say exactly the notices switched on?"""
        return says_ai(line) == self.ai and says_recorded(line) == self.recording


def woven_notice_problems(where: str, text: str, woven: WovenNotices) -> list[str]:
    """Each way `text` breaks `woven`, as the sentence a writer is sent to repair it."""
    problems: list[str] = []
    if woven.ai and not says_ai(text):
        problems.append(f"{where}: does not say it is an AI assistant; {WOVEN_AI_RULE}")
    if not woven.ai and says_ai(text):
        problems.append(f"{where}: says it is an AI, and that notice is off; {NO_AI_RULE}")
    if woven.recording and not says_recorded(text):
        problems.append(f"{where}: does not say the call is recorded; {WOVEN_RECORDING_RULE}")
    if not woven.recording and says_recorded(text):
        problems.append(
            f"{where}: says the call is recorded, and that notice is off; {NO_RECORDING_RULE}"
        )
    return problems


def opening_max_chars(base: int, text: str) -> int:
    """The longest `text` may be: `base`, plus room for each notice it says."""
    return (
        base
        + (WOVEN_AI_CHARS if says_ai(text) else 0)
        + (WOVEN_RECORDING_CHARS if says_recorded(text) else 0)
    )


def first_words_disclose(first_words: str, *, ai_notice: str, recording_notice: str) -> bool:
    """Does `first_words` say each notice switched on (`ai_notice`, `recording_notice`: the
    stored sentence when its switch is on, else empty)? Either its stored sentence word for
    word or the meaning in other words: an owner's own stored sentence may use neither word
    list's words, and is still the notice."""
    ai_said = not ai_notice.strip() or ai_notice.strip() in first_words or says_ai(first_words)
    recording_said = (
        not recording_notice.strip()
        or recording_notice.strip() in first_words
        or says_recorded(first_words)
    )
    return ai_said and recording_said


__all__ = [
    "AI_WORDS",
    "NO_AI_RULE",
    "NO_RECORDING_RULE",
    "RECORDING_WORDS",
    "WOVEN_AI_CHARS",
    "WOVEN_AI_RULE",
    "WOVEN_RECORDING_CHARS",
    "WOVEN_RECORDING_RULE",
    "WovenNotices",
    "first_words_disclose",
    "opening_max_chars",
    "says_ai",
    "says_recorded",
    "woven_notice_problems",
]
