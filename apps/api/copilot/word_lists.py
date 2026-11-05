"""Founder-owned word lists Pip's code matches against, read from data files.

Indian-language words are never written in code (founder rule): they live in JSON files
beside `calevate_shared/spoken_style.json`, where the founder adds or removes them, and are
read the same way (`importlib.resources`, once per process). Each file carries an `_about`
saying what its words are for.

- `screen_words.json` — words that say a call walks someone through a phone or computer
  screen; a hint for Pip to ask the owner (`agent_setup_actions.screen_guide_hint`).
- `provider_spellings.json` — AI provider names spelled in Indian scripts; Pip's answers
  must not contain them (`identity.names_a_vendor`).
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any, Final

#: Telugu and Hindi spellings are written with and without the zero-width non-joiner; both
#: sides drop it before matching, so one spelling in the file covers both.
_ZWNJ: Final = "‌"


def _load(name: str) -> Any:
    return json.loads(resources.files("calevate_shared").joinpath(name).read_text(encoding="utf-8"))


def _strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{where} must be a list of non-empty strings")
    return tuple(value)


@cache
def screen_words() -> tuple[str, ...]:
    """Every screen word, all languages, without zero-width non-joiners."""
    words = _load("screen_words.json").get("words")
    if not isinstance(words, dict):
        raise ValueError("screen_words.json: `words` must map a language to its words")
    return tuple(
        word.replace(_ZWNJ, "")
        for tag, listed in words.items()
        for word in _strings(listed, f"screen_words.json: {tag}")
    )


def mentions_screen_word(text: str) -> bool:
    """Whether `text` contains a screen word from the data file (by containment: a word
    boundary means nothing between two syllables of an Indian script)."""
    plain = text.replace(_ZWNJ, "")
    return any(word in plain for word in screen_words())


@cache
def provider_spellings() -> tuple[str, ...]:
    """The provider-name spellings in Indian scripts, casefolded as `identity` compares."""
    listed = _load("provider_spellings.json").get("spellings")
    return tuple(word.casefold() for word in _strings(listed, "provider_spellings.json"))


__all__ = ["mentions_screen_word", "provider_spellings", "screen_words"]
