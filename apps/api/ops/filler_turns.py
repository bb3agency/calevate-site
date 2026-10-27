"""Which agent turns of a call began with a filler line (D-901).

The voice platform's reply time (`CallQuality.reply_ms_*`) ends at the agent's first sound,
and a filler line said while a reply is slow is a first sound: the time to the answer itself
is not reported (VENDOR-STATED, ThinnestAI's email of 27 Oct 2026, `docs/vendor/
thinnest-replies-2026-10-12.md` §37). So a call whose replies opened with fillers has a reply
time held near the filler delay however long the answer took. Counting those turns lets the
Voice response time report (`ops/reply_times.py`) give a typical figure over calls with none.

The count is what the TRANSCRIPT shows. Whether the platform writes filler lines into the
transcript at all is UNKNOWN (its docs, mirror of 19 Oct 2026, do not say), so zero means
"none found", never "none played". An Ear acknowledgement also ends the measurement and is
not a line we send, so it is not counted.

The lines matched are every line the agent could have been given: its own, its account's,
and the platform's in every language (`spoken_style.thinking_lines`). The union rather than
the one list in force at the call: the settings may have changed since, and a line from any
of them at the start of an agent turn is a filler either way.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from functools import cache
from typing import Final

from calevate_shared.events import TranscriptTurn
from calevate_shared.languages import LANGUAGES
from calevate_shared.spoken_style import thinking_lines

#: Punctuation a transcript may put around a filler ("Ek minute ji..." / "one moment,").
#: The non-ASCII ones by code point (ellipsis, en and em dash, danda and double danda, curly
#: quotes), because several look like their ASCII cousins.
_TRIM: Final = " .,!?;:-\"'()" + "".join(
    map(chr, (0x2026, 0x2013, 0x2014, 0x0964, 0x0965, 0x201C, 0x201D, 0x2018, 0x2019))
)


def _normalise(text: str) -> str:
    """Case-folded, NFC, inner whitespace collapsed, outer punctuation trimmed."""
    folded = unicodedata.normalize("NFC", text).casefold()
    return " ".join(folded.split()).strip(_TRIM)


def _is_word_character(char: str) -> bool:
    """A letter, a combining mark (Indic vowel signs are marks) or a digit."""
    return unicodedata.category(char)[0] in ("L", "M", "N")


@cache
def platform_filler_lines() -> tuple[str, ...]:
    """The platform's own filler lines in every language that has any."""
    return thinking_lines(tuple(language.bcp47 for language in LANGUAGES.values()))


def filler_lines_for(*line_sets: Iterable[str] | None) -> tuple[str, ...]:
    """The given lines and the platform's, normalised, blanks and repeats dropped."""
    seen: list[str] = []
    for lines in (*line_sets, platform_filler_lines()):
        for line in lines or ():
            normal = _normalise(line)
            if normal and normal not in seen:
                seen.append(normal)
    return tuple(seen)


def begins_with_filler(text: str, normalised_lines: Sequence[str]) -> bool:
    """Does this turn open with one of the lines, ending on a word boundary? A line must be
    the turn's opening words, so "One moment" does not match "One momentous"."""
    turn = _normalise(text)
    for line in normalised_lines:
        if turn.startswith(line) and (
            len(turn) == len(line) or not _is_word_character(turn[len(line)])
        ):
            return True
    return False


def filler_turns(transcript: Sequence[TranscriptTurn], normalised_lines: Sequence[str]) -> int:
    """How many agent turns begin with a filler line."""
    return sum(
        1
        for turn in transcript
        if turn.speaker == "agent" and begins_with_filler(turn.text, normalised_lines)
    )


__all__ = ["begins_with_filler", "filler_lines_for", "filler_turns", "platform_filler_lines"]
