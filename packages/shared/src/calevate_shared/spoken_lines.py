"""The founder's fixed lines and phrase lists in Indian languages (audit of 5 Nov 2026, G4).

Every sentence a caller hears, or a practice caller says, that the platform wrote rather than
the client or a model lives in `spoken_lines.json` beside this module, with the do-not-call
phrase lists, so the founder corrects them without a code change and each entry records whether
a native speaker reviewed it. `spoken_style.json` is the sibling for HOW a language is spoken
(register, word swaps, examples); this file is WHAT we say in it.

An entry's `by_language` is what the code reads; its `drafts` are machine-drafted lines kept for
the founder to approve and never read. A consumer that finds no line for a language never
invents one: it says so, skips the step, or uses English where that is safe, and documents
which.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any, Final, Literal

from calevate_shared.languages import find_language

ReviewStatus = Literal["needs_native_review", "native_reviewed"]

#: The Unicode name prefix of each script's letters, by ISO 15924 code
#: (`calevate_shared.languages.Script`).
_SCRIPT_LETTERS: Final[dict[str, str]] = {
    "Beng": "BENGALI",
    "Deva": "DEVANAGARI",
    "Gujr": "GUJARATI",
    "Guru": "GURMUKHI",
    "Knda": "KANNADA",
    "Mlym": "MALAYALAM",
    "Orya": "ORIYA",
    "Taml": "TAMIL",
    "Telu": "TELUGU",
}


@cache
def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        resources.files(__package__).joinpath("spoken_lines.json").read_text(encoding="utf-8")
    )
    return raw


def _entry(key: str) -> Mapping[str, Any]:
    entries: Mapping[str, Any] = _raw()["entries"]
    if key not in entries:
        raise KeyError(f"spoken_lines.json has no entry {key!r}")
    entry: Mapping[str, Any] = entries[key]
    return entry


def _frozen(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return {k: _frozen(v) for k, v in value.items()}
    return value


def by_language(key: str) -> dict[str, Any]:
    """The entry's live values keyed as the file keys them (a BCP-47 tag, a Meta or notice
    language code, or a gender), lists as tuples. A fresh dict each call."""
    return {k: _frozen(v) for k, v in _entry(key)["by_language"].items()}


def lines(key: str) -> dict[str, str]:
    """An entry whose values are single lines."""
    return {k: str(v) for k, v in _entry(key)["by_language"].items()}


def drafts(key: str) -> dict[str, Any]:
    """The machine-drafted values the founder has not approved; never spoken."""
    return {k: _frozen(v) for k, v in _entry(key).get("drafts", {}).items()}


def review(key: str) -> ReviewStatus:
    status: ReviewStatus = _entry(key)["review"]
    return status


def entry_keys() -> tuple[str, ...]:
    return tuple(_raw()["entries"])


def in_own_script(text: str, tag: str) -> bool:
    """Whether `text` is written in the letters of `tag`'s language: always for a language
    written in Latin letters, else at least one letter of its own script (D-745: a Telugu
    sentence in Latin letters is read by the voice as English)."""
    language = find_language(tag)
    if language is None:
        return False
    prefix = _SCRIPT_LETTERS.get(language.script.iso15924)
    if prefix is None:
        return True
    return any(unicodedata.name(ch, "").startswith(prefix) for ch in text)


__all__ = [
    "ReviewStatus",
    "by_language",
    "drafts",
    "entry_keys",
    "in_own_script",
    "lines",
    "review",
]
