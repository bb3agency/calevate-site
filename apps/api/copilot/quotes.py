"""Whether the model's quote of the person is really in what the person wrote (D-833).

A fill or a drafted script must rest on words the person typed, and the model is asked to
copy those words into the tool call. The check is a substring test after folding both sides
the same way, so it needs no word lists and works in any language and script.

Folding is NFKC, casefold, invisible characters out, punctuation and symbols to a space,
whitespace collapsed. Punctuation is chosen by Unicode category (P* and S*) rather than with
`\\W`, because Python's `\\W` matches the vowel signs and viramas of Telugu and Devanagari
(categories Mc and Mn are not alphanumeric) and would tear an Indic word apart.

The check proves the quote came from the message; it cannot prove the quoted words ask for
anything. A model can still quote a question that asks for no change; what it cannot do is
rest a fill on an earlier turn's request, which is the failure this exists for.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

from apps.api.copilot.sanitize import strip_invisible

_SPACE: Final = re.compile(r"\s+")


def _blank_punctuation(text: str) -> str:
    return "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)


def fold(text: str) -> str:
    """`text` as the quote check compares it."""
    folded = unicodedata.normalize("NFKC", strip_invisible(text)).casefold()
    return _SPACE.sub(" ", _blank_punctuation(folded)).strip()


def quoted_in(quote: object, said: Iterable[str]) -> bool:
    """True when `quote` is a non-empty run of whole words from one of the texts in `said`.

    Whole words, so "ill" is not a quote of "fill this"."""
    if not isinstance(quote, str):
        return False
    wanted = fold(quote)
    if not wanted:
        return False
    return any(f" {wanted} " in f" {fold(text)} " for text in said)


__all__ = ["fold", "quoted_in"]
