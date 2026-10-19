"""The quote check behind D-833: folding, whole words, and Indic scripts kept whole."""

from __future__ import annotations

import pytest

from apps.api.copilot.quotes import fold, quoted_in


def test_folding_drops_case_punctuation_and_extra_space() -> None:
    assert fold("  Fill the HOURS:\n10 \u2013 8, please! ") == "fill the hours 10 8 please"


@pytest.mark.parametrize("word", ["నింపండి", "भर दो", "ఆదివారం"])
def test_vowel_signs_and_viramas_stay_part_of_their_word(word: str) -> None:
    """`\\W` would split these words at every vowel sign; category P/S does not."""
    assert fold(word) == word


def test_a_zero_width_character_does_not_hide_a_quote() -> None:
    assert quoted_in("fill the hours", ["fill the​ hours now"])


def test_a_quote_may_come_from_any_of_the_texts_given() -> None:
    assert quoted_in("organic groceries", ["hi", "Organic groceries, home cooks"])
    assert not quoted_in("organic groceries", ["hi", "home cooks"])


@pytest.mark.parametrize("quote", [None, 3, "", " , "])
def test_nothing_to_compare_is_not_a_quote(quote: object) -> None:
    assert not quoted_in(quote, ["anything at all"])
