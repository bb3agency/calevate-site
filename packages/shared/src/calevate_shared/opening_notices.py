"""The AI and recording notices said in the agent's own opening line (D-971).

Founder, 5 Nov 2026: "When an opening is saved, Pip weaves the notices into that agent's own
opening line in its own words, which the engine then speaks." The engine speaks the greeting
word for word (`snapshots/2026-10-29/pages/channels/voice.md:363-366`), so a notice the agent
says in its own words has to be written into that greeting before the call, not improvised
on it. No Indian rule prescribes the words of either notice (TCCCPR third amendment,
18 Sep 2026; DPDP Rules 2025 r.3; IT Rules amendment G.S.R. 120(E), 10 Feb 2026, which asks
for a "prominently prefixed audio disclosure" and names no wording).

Whether an opening line says a notice is never inferred from its words. The writer that weaves
a notice in returns the exact words of the line that say it, and those words are kept beside
the line they were written for (`OpeningNotices`). The stored sentence is dropped from the
first words only while the line still holds those words (`said_in`); any other line, an owner's
edit of a woven one included, keeps the stored sentence beside it (`engine.join_first_words`),
so a notice is said twice at worst, never not at all. A word list cannot carry that judgement:
"artificial jewellery", "your records", a business called "… AI Solutions" and "this call is
not recorded" all hold the words and say no notice.

`says_ai` and `says_recorded` remain for checks that cannot drop a notice: asking a writer to
repair its own line, and the extra length a line that may carry a notice is allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from calevate_shared.call_words import extend as _extend

#: Words that say "AI" in the languages agents speak. The staged languages write "AI" in
#: Latin letters (`compliance/disclosure.AI_DISCLOSURE_TEMPLATES`), which the first
#: alternatives match; the Indian-language words are the founder's (`call_words.json`).
AI_WORDS: Final = re.compile(
    _extend(r"\bAI\b|\bA\.I\.|artificial", "opening_notices.AI_WORDS"), re.IGNORECASE
)
#: Words that say "recorded".
RECORDING_WORDS: Final = re.compile(
    _extend("record", "opening_notices.RECORDING_WORDS"), re.IGNORECASE
)


def says_ai(text: str) -> bool:
    """Does `text` tell the caller they are speaking with an AI?"""
    return bool(AI_WORDS.search(text))


def says_recorded(text: str) -> bool:
    """Does `text` tell the caller the call is recorded?"""
    return bool(RECORDING_WORDS.search(text))


def _flat(text: str) -> str:
    return " ".join(text.split())


class OpeningNotices(BaseModel):
    """What the notice writer did to one opening line (D-971), kept in the script beside it.

    `ai` and `recording` are the exact words of `line` that say each notice, as the writer
    returned them; they count only while the opening is still `line` (`said_in`). `before` is
    the line the writer replaced, shown with an Undo; `kept_own` is a line the owner put back
    over the writer's, which is not rewritten again."""

    model_config = ConfigDict(extra="forbid")

    line: str = Field(default="", max_length=1000)
    ai: str = Field(default="", max_length=1000)
    recording: str = Field(default="", max_length=1000)
    before: str = Field(default="", max_length=1000)
    kept_own: str = Field(default="", max_length=1000)


@dataclass(frozen=True, slots=True)
class SaidNotices:
    """The words of one opening line that say each notice, or "" for a notice it does not
    say. Built only by `said_in` or read from a compiled script, never from a word match."""

    ai: str = ""
    recording: str = ""

    def says_ai_in(self, line: str) -> bool:
        return bool(self.ai.strip()) and _flat(self.ai) in _flat(line)

    def says_recorded_in(self, line: str) -> bool:
        return bool(self.recording.strip()) and _flat(self.recording) in _flat(line)


NONE_SAID: Final = SaidNotices()


def said_in(notices: OpeningNotices, line: str) -> SaidNotices:
    """The notices `line` says by the words the writer wove into it: none unless `line` is
    the very line they were written for."""
    if not line.strip() or _flat(notices.line) != _flat(line):
        return NONE_SAID
    said = SaidNotices(ai=_flat(notices.ai), recording=_flat(notices.recording))
    return SaidNotices(
        ai=said.ai if said.says_ai_in(line) else "",
        recording=said.recording if said.says_recorded_in(line) else "",
    )


def kept_by_owner(notices: OpeningNotices, line: str) -> bool:
    """Did the owner put `line` back over the writer's (Undo), so it is not woven again?"""
    return bool(line.strip()) and _flat(notices.kept_own) == _flat(line)


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

    def matches(self, said: SaidNotices, line: str) -> bool:
        """Does `line` say, by the words woven into it (`said`), exactly the notices switched
        on? A line nobody wove a notice into says none, whatever words it holds."""
        return said.says_ai_in(line) == self.ai and said.says_recorded_in(line) == self.recording


def woven_notice_problems(where: str, text: str, woven: WovenNotices) -> list[str]:
    """Each way `text` breaks `woven` by its words, as the sentence a writer of a whole
    script is sent to repair it. A hint to the writer only: that writer names no notice
    words, so its line drops no stored sentence (`said_in`) whatever this says."""
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


def unwoven_notice_problems(
    where: str, line: str, woven: WovenNotices, said: SaidNotices
) -> list[str]:
    """Each way `line` breaks `woven` by the words the notice writer named as saying each
    notice (`said`), as the sentence the writer is sent to repair it. Unlike
    `woven_notice_problems` no word list decides it: a line counts as saying a notice only
    through those words, and the named words must themselves say it."""
    problems: list[str] = []
    if woven.ai and not said.says_ai_in(line):
        problems.append(
            f"{where}: ai_notice_words must be words copied exactly from the line that say it "
            f"is an AI assistant; {WOVEN_AI_RULE}"
        )
    elif woven.ai and not says_ai(said.ai):
        problems.append(f"{where}: ai_notice_words do not say it is an AI assistant")
    if not woven.ai and said.ai:
        problems.append(f"{where}: says it is an AI, and that notice is off; {NO_AI_RULE}")
    if woven.recording and not said.says_recorded_in(line):
        problems.append(
            f"{where}: recording_notice_words must be words copied exactly from the line that "
            f"say the call is recorded; {WOVEN_RECORDING_RULE}"
        )
    elif woven.recording and not says_recorded(said.recording):
        problems.append(f"{where}: recording_notice_words do not say the call is recorded")
    if not woven.recording and said.recording:
        problems.append(
            f"{where}: says the call is recorded, and that notice is off; {NO_RECORDING_RULE}"
        )
    return problems


def opening_max_chars(base: int, text: str) -> int:
    """The longest `text` may be: `base`, plus room for each notice it may say. A word match
    is enough here because it only lengthens the allowance; the engine's greeting ceiling is
    still measured on the real first words at publish."""
    return (
        base
        + (WOVEN_AI_CHARS if says_ai(text) else 0)
        + (WOVEN_RECORDING_CHARS if says_recorded(text) else 0)
    )


def first_words_disclose(
    first_words: str, *, ai_notice: str, recording_notice: str, said: SaidNotices = NONE_SAID
) -> bool:
    """Does `first_words` say each notice switched on (`ai_notice`, `recording_notice`: the
    stored sentence when its switch is on, else empty)? Either its stored sentence word for
    word or the words the notice writer wove into the opening line (`said`). Never a word
    match: "not recorded" holds the word and is no notice."""
    ai_said = (
        not ai_notice.strip()
        or _flat(ai_notice) in _flat(first_words)
        or said.says_ai_in(first_words)
    )
    recording_said = (
        not recording_notice.strip()
        or _flat(recording_notice) in _flat(first_words)
        or said.says_recorded_in(first_words)
    )
    return ai_said and recording_said


__all__ = [
    "AI_WORDS",
    "NONE_SAID",
    "NO_AI_RULE",
    "NO_RECORDING_RULE",
    "RECORDING_WORDS",
    "WOVEN_AI_CHARS",
    "WOVEN_AI_RULE",
    "WOVEN_RECORDING_CHARS",
    "WOVEN_RECORDING_RULE",
    "OpeningNotices",
    "SaidNotices",
    "WovenNotices",
    "first_words_disclose",
    "kept_by_owner",
    "opening_max_chars",
    "said_in",
    "says_ai",
    "says_recorded",
    "unwoven_notice_problems",
    "woven_notice_problems",
]
