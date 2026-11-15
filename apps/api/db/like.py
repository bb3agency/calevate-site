"""LIKE patterns from typed text.

A search box's text is a VALUE, so it is always a bound parameter; but inside a LIKE
pattern `%` and `_` are still operators, and a bound `%` matches every row. Escaping them
keeps "A_B" finding itself and a lone `%` from returning the whole table (and from
building a pattern Postgres has to backtrack through). Postgres' default LIKE escape is
the backslash, so no `ESCAPE` clause is needed in the statement.
"""

from __future__ import annotations

import re

from calevate_shared.extraction import ascii_digits


def escape_like(needle: str) -> str:
    """`needle` with LIKE's operators made literal: backslash first, then `%` and `_`."""
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_pattern(needle: str) -> str:
    """A pattern matching `needle` anywhere in the value."""
    return f"%{escape_like(needle)}%"


def suffix_pattern(needle: str) -> str:
    """A pattern matching values that END with `needle`."""
    return f"%{escape_like(needle)}"


#: Digits in any script, with the separators people write a phone number with.
_PHONE_SHAPED = re.compile(r"^[\d\s()+.\-]+$")

#: An Indian national number: what is left once a country code or trunk `0` is dropped.
_NATIONAL_DIGITS = 10


def phone_suffix_pattern(needle: str) -> str:
    """A suffix pattern on an E.164 column for a search term.

    A term written like a phone matches on its digits, so `98765 43210`, `+91 98765 43210`,
    `098765-43210` and the same number in Telugu digits all find `+919876543210`; past ten
    digits only the national ten are kept, so a trunk `0` does not stop the match. Any
    other term is a plain suffix, which matches no stored number and leaves the name half
    of the search to answer it."""
    if _PHONE_SHAPED.match(needle):
        digits = ascii_digits(needle)
        if digits:
            return f"%{digits[-_NATIONAL_DIGITS:]}"
    return suffix_pattern(needle)


__all__ = ["contains_pattern", "escape_like", "phone_suffix_pattern", "suffix_pattern"]
