"""LIKE patterns from typed text.

A search box's text is a VALUE, so it is always a bound parameter; but inside a LIKE
pattern `%` and `_` are still operators, and a bound `%` matches every row. Escaping them
keeps "A_B" finding itself and a lone `%` from returning the whole table (and from
building a pattern Postgres has to backtrack through). Postgres' default LIKE escape is
the backslash, so no `ESCAPE` clause is needed in the statement.
"""

from __future__ import annotations


def escape_like(needle: str) -> str:
    """`needle` with LIKE's operators made literal: backslash first, then `%` and `_`."""
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_pattern(needle: str) -> str:
    """A pattern matching `needle` anywhere in the value."""
    return f"%{escape_like(needle)}%"


def suffix_pattern(needle: str) -> str:
    """A pattern matching values that END with `needle`."""
    return f"%{escape_like(needle)}"


__all__ = ["contains_pattern", "escape_like", "suffix_pattern"]
