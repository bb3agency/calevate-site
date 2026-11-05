"""Founder-owned word lists: read from the data files, and no longer written in code."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.api.copilot import word_lists
from apps.api.copilot.identity import names_a_vendor

_INDIC = re.compile("[ऀ-ൿ]")
_HERE = Path(__file__).parent


@pytest.mark.parametrize("module", ["agent_setup_actions.py", "identity.py"])
def test_no_indian_language_word_is_written_in_these_modules(module: str) -> None:
    """FAILS IF: a Telugu or Hindi word list moves back into code (PIP-17, PIP-18); the
    founder edits them in `calevate_shared/*.json`."""
    assert not _INDIC.search((_HERE / module).read_text(encoding="utf-8"))


def test_every_screen_word_in_the_file_is_matched_with_or_without_the_joiner() -> None:
    words = word_lists.screen_words()
    assert words, "screen_words.json lists no words"
    for word in words:
        assert word_lists.mentions_screen_word(f"please {word} it")
    joined = next(word for word in words if len(word) > 3)
    with_joiner = joined[:2] + "‌" + joined[2:]
    assert word_lists.mentions_screen_word(with_joiner)
    assert not word_lists.mentions_screen_word("we sell rice and dal")


def test_every_provider_spelling_in_the_file_is_caught_in_an_answer() -> None:
    spellings = word_lists.provider_spellings()
    assert spellings, "provider_spellings.json lists no spellings"
    for spelling in spellings:
        assert names_a_vendor(f"I run on {spelling} today")
