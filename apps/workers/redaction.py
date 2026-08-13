"""PII redaction (post-call pipeline step 2, SECURITY-COMPLIANCE §4).

Produces `text_redacted`, which is what EVERY API response returns by default
(hard rule 5). Raw text needs an owner/admin role check and writes an audit_log row.

Design points that matter more than the regexes:

- **Validators, not just patterns.** A 12-digit run is not an Aadhaar; Aadhaar carries
  a Verhoeff check digit, PAN has a fixed letter/digit shape, cards carry Luhn. Running
  the validator kills the false positives that would otherwise redact appointment
  reference numbers and prices out of every Telugu transcript.
- **Spoken-out digits are the hard case.** Indian callers routinely say numbers as
  words, code-mixed ("nine eight seven six", "tommidi enimidi"). A pure regex cannot
  see those, so `spoken_digit_runs` normalizes English AND Telugu digit words before
  matching. SEC-COMP §4 also allows an LLM-assisted pass; this deterministic layer runs
  first and always, so the LLM is an addition, never the only defence.
- **Redaction is lossy on purpose.** We keep the last 2 digits of a phone so staff can
  recognise a caller they are looking at, and nothing else.

Everything here is pure and synchronous — no I/O — so it is trivially testable and can
run inside any worker step without a budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Number-shaped patterns ---------------------------------------------------

_AADHAAR_RE = re.compile(r"\b(\d{4})[ -]?(\d{4})[ -]?(\d{4})\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# The `\b` after an optional `+91` CANNOT MATCH when the prefix is present with no
# separator: `1` and `9` are both word characters, so there is no boundary between
# them. That made the country-code branch dead code for exactly the format this
# product stores — `phone_e164`, per CLAUDE.md's "Phone: E.164 strings" — and
# `+919876543210` travelled through `redact()` unmasked into hot-lead notification
# email, under a docstring promising it was masked. Digit lookarounds instead of `\b`:
# they anchor on "not part of a longer run of digits", which is the property actually
# wanted, and they hold whether or not a `+91` precedes. Group 1 is still the ten
# national digits, so the `last2` tail is unchanged.
_PHONE_RE = re.compile(r"(?<![0-9])\+?(?:91[ -]?)?([6-9]\d{9})(?![0-9])")
_OTP_RE = re.compile(
    r"\b(?:otp|o\.?t\.?p|code|pin|password)\b[^0-9]{0,20}(\d{4,8})\b", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# UPI ids look like `name@bank` but must not swallow emails; checked after email.
_UPI_RE = re.compile(r"\b[\w.-]{2,}@(?:ok\w+|paytm|ybl|axl|upi|apl|ibl)\b", re.IGNORECASE)

# Digit words we may hear, English + Telugu (transliterated, as Saaras returns them).
_DIGIT_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "sunna": "0", "okati": "1", "rendu": "2", "moodu": "3", "naalugu": "4",
    "aidu": "5", "aaru": "6", "edu": "7", "enimidi": "8", "tommidi": "9",
    # Hindi, in the Latin transliterations an STT actually emits. Their absence was a
    # LIVE hard-rule-6 leak, not a gap in coverage: `redact` runs on every transcript
    # regardless of vertical or extractor, so a Hindi-speaking caller reading a number
    # digit-by-digit had it survive into `text_redacted` — the field every API response
    # defaults to — while the same caller in Telugu was masked. D-36's stack is
    # Telugu-FIRST, not Telugu-only, and this receiver takes Hindi calls today.
    #
    # Spelling varies by transliterator, so the common variants are all mapped; a wrong
    # extra spelling costs nothing, a missing one costs a phone number. `zero` is
    # already above and `sifar` is the Urdu-inflected form heard in the north.
    "shunya": "0", "sunya": "0", "sifar": "0",
    "ek": "1", "do": "2", "teen": "3", "tin": "3", "chaar": "4", "char": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "che": "6", "chah": "6", "chhah": "6",
    "saat": "7", "sat": "7", "aath": "8", "ath": "8", "nau": "9",
    # Deliberately NOT mapped: "no" (a colloquial 9). The six-word run is what makes the
    # other English collisions ("do", "che", "sat", "char", "tin") safe — nobody says six
    # of those in a row without reading out a number — but "no no no no no no" is exactly
    # what a frustrated caller says, and masking a refusal as a phone number would hide
    # the turn a DNC opt-out lives in.
}  # fmt: skip
_SPOKEN_RUN_MIN = 6

MASK = "[redacted]"
PHONE_MASK = "[phone ••{last2}]"


@dataclass(slots=True)
class RedactionResult:
    text: str
    kinds: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.kinds)


# --- Validators ---------------------------------------------------------------

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def is_valid_aadhaar(digits: str) -> bool:
    """Verhoeff checksum. UIDAI numbers also never start with 0 or 1."""
    if len(digits) != 12 or not digits.isdigit() or digits[0] in "01":
        return False
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[i % 8][int(digit)]]
    return checksum == 0


def is_valid_luhn(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        value = int(digit)
        if i % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


# --- Spoken digits ------------------------------------------------------------


def spoken_digit_runs(text: str) -> list[tuple[int, int, str]]:
    """Find runs of >= 6 consecutive digit WORDS. Returns (start, end, digits).

    Six is the threshold because shorter runs are ordinary speech ("rendu three
    o'clock"), while a phone number or an OTP read aloud is always longer.
    """
    runs: list[tuple[int, int, str]] = []
    current: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[\w']+", text):
        word = match.group(0).lower()
        mapped = _DIGIT_WORDS.get(word)
        if mapped is not None:
            current.append((match.start(), match.end(), mapped))
            continue
        if len(current) >= _SPOKEN_RUN_MIN:
            runs.append((current[0][0], current[-1][1], "".join(d for _, _, d in current)))
        current = []
    if len(current) >= _SPOKEN_RUN_MIN:
        runs.append((current[0][0], current[-1][1], "".join(d for _, _, d in current)))
    return runs


# --- The pass ------------------------------------------------------------------


def redact(text: str) -> RedactionResult:
    """Deterministic redaction pass. Order matters: the most specific patterns run
    first so a card number is not eaten by the generic phone rule."""
    kinds: list[str] = []
    out = text

    def _note(kind: str) -> None:
        if kind not in kinds:
            kinds.append(kind)

    # OTP first: it is the highest-harm short number and is context-tagged.
    def _otp(match: re.Match[str]) -> str:
        _note("otp")
        return match.group(0).replace(match.group(1), MASK)

    out = _OTP_RE.sub(_otp, out)

    def _aadhaar(match: re.Match[str]) -> str:
        digits = "".join(match.groups())
        if not is_valid_aadhaar(digits):
            return match.group(0)
        _note("aadhaar")
        return MASK

    out = _AADHAAR_RE.sub(_aadhaar, out)

    def _card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if not is_valid_luhn(digits):
            return match.group(0)
        _note("card")
        return MASK

    out = _CARD_RE.sub(_card, out)

    def _pan(match: re.Match[str]) -> str:
        _note("pan")
        return MASK

    out = _PAN_RE.sub(_pan, out)

    def _email(match: re.Match[str]) -> str:
        _note("email")
        return MASK

    out = _EMAIL_RE.sub(_email, out)

    def _upi(match: re.Match[str]) -> str:
        _note("upi")
        return MASK

    out = _UPI_RE.sub(_upi, out)

    def _phone(match: re.Match[str]) -> str:
        _note("phone")
        return PHONE_MASK.format(last2=match.group(1)[-2:])

    out = _PHONE_RE.sub(_phone, out)

    # Spoken runs last: they operate on word offsets, so they must not be invalidated
    # by earlier substitutions in the same pass — apply right-to-left.
    for start, end, digits in reversed(spoken_digit_runs(out)):
        _note("spoken_digits")
        replacement = PHONE_MASK.format(last2=digits[-2:]) if len(digits) == 10 else MASK
        out = out[:start] + replacement + out[end:]

    return RedactionResult(text=out, kinds=kinds)


__all__ = [
    "MASK",
    "PHONE_MASK",
    "RedactionResult",
    "is_valid_aadhaar",
    "is_valid_luhn",
    "redact",
    "spoken_digit_runs",
]
