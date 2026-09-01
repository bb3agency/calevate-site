"""`rowcount_of`, including the arm that is not a SQLAlchemy `CursorResult`.

This helper is the one place this repository decides how many rows a statement changed,
and every caller reads 0 as "I lost the race, skip". It sits on the tenancy-session
guarded surface for that reason: a wrong answer here does not raise, it makes a CAS
writer believe it won when it did not.

The `CursorResult` arm is exercised by every DB test in the suite. The FALLBACK arm —
anything else carrying a `rowcount` attribute — was not exercised by anything, which is
how a helper whose whole job is defensive ends up with its defensive half untested.
"""

from __future__ import annotations

from typing import Any

from apps.api.db.result import rowcount_of


class _Reports:
    """Not a `CursorResult`. A driver wrapper, a test double, or a future SQLAlchemy
    result type all reach the fallback exactly like this."""

    def __init__(self, value: Any) -> None:
        self.rowcount = value


def test_a_non_cursor_result_reporting_a_count_is_believed() -> None:
    assert rowcount_of(_Reports(3)) == 3


def test_a_count_of_zero_is_zero_and_not_confused_with_absence() -> None:
    """0 and "no rowcount" mean the same to a caller — both are 'skip' — but they must
    not be reached by different paths, or a future edit can make one of them mean
    'proceed'."""
    assert rowcount_of(_Reports(0)) == 0


def test_a_negative_count_is_refused_rather_than_passed_on() -> None:
    """DBAPIs report -1 for "not applicable". Passing that through would make
    `if rowcount_of(...)` truthy — a NEGATIVE count read as "rows changed", which is the
    inversion this clamp exists to prevent."""
    assert rowcount_of(_Reports(-1)) == 0


def test_a_result_with_no_rowcount_at_all_is_zero() -> None:
    assert rowcount_of(object()) == 0


def test_a_non_integer_rowcount_is_not_coerced() -> None:
    """A string is refused rather than `int()`-ed. Coercing would turn a driver's odd
    answer into a confident number, and the safe direction here is always 0."""
    assert rowcount_of(_Reports("7")) == 0
    assert rowcount_of(_Reports(None)) == 0
