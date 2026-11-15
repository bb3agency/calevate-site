"""Numbers a person types in Telugu digits compare equal to the same number in ASCII.

`str.isdigit()` is true for Telugu and Devanagari digits, so a cleaner built on it kept
them and the number never matched its ASCII spelling (the audit of 15 Nov 2026 found five
such cleaners after `forwarding.normalize_india`). Indic digits are generated from code
points, never typed.
"""

from __future__ import annotations

from apps.api.actions.sheets import digits_tail
from apps.api.engine.thinnest_numbers import digits

NUMBER = "9876543210"


def _telugu(ascii_number: str) -> str:
    return "".join(chr(0x0C66 + int(d)) if d.isdigit() else d for d in ascii_number)


def test_a_sheet_number_in_telugu_digits_matches_its_ascii_spelling() -> None:
    """FAILS IF: a sheet row typed in Telugu digits never matches the lead's number."""
    assert digits_tail(f"+91 {_telugu(NUMBER)}") == NUMBER


def test_an_engine_number_reads_as_ascii_digits() -> None:
    """FAILS IF: the digits sent on the number path keep a non-ASCII digit."""
    assert digits(f"+91{_telugu(NUMBER)}") == f"91{NUMBER}"
