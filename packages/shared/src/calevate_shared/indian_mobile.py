"""What an Indian mobile number is: the one rule every validator and normaliser reads.

A mobile is ten digits whose first is 6, 7, 8 or 9 (the National Numbering Plan's mobile
levels; REPORTED from en.wikipedia.org/wiki/Mobile_telephone_numbering_in_India, read
26 Nov 2026 — the DoT plan text itself was not located). Fixed-line numbers also open
with some of these digits (Bengaluru's area code is 80), so the rule tells a mobile from
a short number or a 2-5 opening, not every landline from every mobile; nothing in this
product needs the finer cut.

`ingest.normalize_phone`, `extraction.normalize_phone`, the healer's fallback phone and
the captured-number review note all read it here, so a number one accepts is never one
another refuses. The browser's copy is `apps/web/src/lib/phoneNumber.ts`.
"""

from __future__ import annotations

from typing import Final

#: The first digit of every Indian mobile number.
MOBILE_LEADING_DIGITS: Final = "6789"
#: India's country code, as E.164 writes it.
INDIA_E164_PREFIX: Final = "+91"
#: `is_indian_mobile_e164` as a regular expression, for a database CHECK or a schema pattern.
INDIAN_MOBILE_E164_PATTERN: Final = r"^\+91[6-9][0-9]{9}$"


def is_indian_mobile(national: str) -> bool:
    """Ten ASCII digits opening 6-9: an Indian mobile written without its country code."""
    return (
        len(national) == 10
        and national.isascii()
        and national.isdigit()
        and national[0] in MOBILE_LEADING_DIGITS
    )


def is_indian_mobile_e164(value: str) -> bool:
    """`+91` and an Indian mobile: the canonical form every phone column stores."""
    return value.startswith(INDIA_E164_PREFIX) and is_indian_mobile(value[len(INDIA_E164_PREFIX) :])


__all__ = [
    "INDIAN_MOBILE_E164_PATTERN",
    "INDIA_E164_PREFIX",
    "MOBILE_LEADING_DIGITS",
    "is_indian_mobile",
    "is_indian_mobile_e164",
]
