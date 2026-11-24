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




def test_every_provider_spelling_in_the_file_is_caught_in_an_answer() -> None:
    spellings = word_lists.provider_spellings()
    assert spellings, "provider_spellings.json lists no spellings"
    for spelling in spellings:
        assert names_a_vendor(f"I run on {spelling} today")
