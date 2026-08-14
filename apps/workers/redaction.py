"""PII redaction (post-call pipeline step 2, SECURITY-COMPLIANCE §4).

Produces `text_redacted`, which is what EVERY API response returns by default
(hard rule 5). Raw text needs an owner/admin role check and writes an audit_log row.

Design points that matter more than the regexes:

- **Validators, not just patterns.** A 12-digit run is not an Aadhaar; Aadhaar carries
  a Verhoeff check digit, PAN has a fixed letter/digit shape, cards carry Luhn, and a
  phone number has to satisfy the national numbering plan. Running the validator kills
  the false positives that would otherwise redact appointment reference numbers and
  prices out of every Telugu transcript.
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

# --- Phones -------------------------------------------------------------------
#
# A phone number is matched in TWO STAGES, the way Aadhaar and cards already are here:
# a loose pattern finds a candidate, and a validator built on the numbering plan decides.
# A single regex cannot do it, because the shapes that must match and the shapes that
# must NOT are separated by arithmetic (how many digits, after which prefix), not by
# characters.
#
# THE NUMBERING PLAN, because guessing it is how a client's order ids get destroyed.
# DoT's National Numbering Plan 2003 (last updated 2015) is a uniform 10-digit CLOSED
# scheme: country code 91, trunk prefix 0, and a national number of exactly 10 digits
# either way it is reached.
#   - Mobile: 10 digits, leading 6/7/8/9 (a 4-digit operator prefix starting 6-9 plus a
#     6-digit subscriber number), geographically unbound.
#   - Landline: STD code + subscriber number = 10 digits total; STD codes are 2-4 digits
#     (the eight 2-digit ones are 11, 20, 22, 33, 40, 44, 79, 80) with 6-8 digit
#     subscriber numbers. Leading digit 1-8 — level 9 is mobile, and level 1 is special
#     services except Delhi's 11.
# Sources: DoT NNP 2003 as summarised at https://ozonetel.com/indian-phone-number-system/
# and https://www.sent.dm/en/resources/phone-number-standards/in (checked Aug 2026).
#
# WHAT THAT BUYS, AND WHAT IT COSTS. A bare 10-digit run leading 6-9 is a mobile number
# and nothing else, so it is masked on sight. A bare 10-digit run leading 1-5 is a
# landline OR an order id OR an invoice reference, and the plan gives no way to tell —
# `1234567890` is pinned untouched by `redaction_test` for exactly that reason. So a
# landline is masked only when the text SAYS it is a phone: a `+` country code or the
# trunk `0` (`04023456789`, `+914023456789`). A bare `4023456789` therefore still passes
# through, deliberately: masking it would mean masking every ten-digit reference number
# a clinic reads back to a caller. The digit sweep in `scripts/pilot/redact.py` is the
# right answer for contexts where that trade goes the other way.
#
# History: the `\b` after an optional `+91` CANNOT MATCH when the prefix is present with
# no separator (`1` and `9` are both word characters), which made the country-code branch
# dead code for exactly the format this product stores — `phone_e164`, per CLAUDE.md's
# "Phone: E.164 strings" — and `+919876543210` reached hot-lead notification email
# unmasked. Digit lookarounds fixed that, and hid the rest: with only ONE contiguous run
# permitted, every separator-grouped spelling of the same number stayed unmasked
# (`98765 43210`, `+91 98765 43210`, `9876-543-210`), the trunk form was unmasked
# (`09876543210`), and no landline was covered at all. One number, several spellings,
# one masked — which is not a masked number.
_PHONE_SPAN_RE = re.compile(r"(?<![0-9])(\+?)(\d+(?:[ -]\d+)*)(?![0-9])")
#: Digit groups a phone may be written in. Real display groupings are 5+5, 4+3+3, 3+3+4,
#: 2+4+4 and the like, optionally behind a `91`; none isolates a single digit and none
#: ENDS in a two-digit group. Those two facts are load-bearing, not tidiness: without
#: them a span of unrelated numbers separated only by spaces ("9500 3000 25", "6 7 8 9 10
#: 11 12 13") merges into ten digits leading 6-9 and gets masked as a phone.
_MIN_GROUP_DIGITS = 2
_MIN_LAST_GROUP_DIGITS = 3
_MAX_GROUPS = 4  # a country code plus at most three national groups
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


def national_phone_digits(digits: str, *, explicit: bool = False) -> str | None:
    """The ten national digits of an Indian phone number, or None if this is not one.

    `digits` is one run of digits with separators already stripped; `explicit` says the
    text marked it as a phone with a leading `+` (the trunk `0` marks it just as well and
    is detected here).

    The order of the two strips matters: `+91 040 2345 6789` carries BOTH a country code
    and a trunk prefix, and the country code is the outer one.
    """
    # Country code. Length-gated rather than matched greedily, because "91" is also just
    # two digits: a 12-digit reference number starting 91 must not become a phone unless
    # what remains is itself a valid national number.
    if digits.startswith("91") and len(digits) in (12, 13):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        # Trunk prefix. Nothing but a phone number is written as 0 followed by exactly
        # ten digits, so this counts as the text saying "phone" — see `_PHONE_SPAN_RE`.
        digits, explicit = digits[1:], True
    if len(digits) != 10:
        return None
    if digits[0] in "6789":
        return digits  # mobile — nationally unique, unambiguous on its own
    if explicit and digits[0] in "12345678":
        return digits  # landline STD code + subscriber (6-8 overlap with the line above)
    return None


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
        """Mask every phone number inside one run of digits-and-separators.

        Windows of adjacent digit GROUPS are tried longest-first from each starting
        group, and a window that fails the numbering plan does not consume anything —
        that retry is the whole reason this is a loop rather than one regex. A date
        beside a number (`15-08 9876543210`) is one span to the pattern; a greedy match
        would swallow both, fail on fourteen digits, and leave the phone in the clear.
        """
        plus = bool(match.group(1))
        body = match.group(2)
        groups = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\d+", body)]
        pieces: list[str] = []
        cursor = 0
        start_group = 0
        swallowed_plus = False
        while start_group < len(groups):
            for end_group in range(min(start_group + _MAX_GROUPS, len(groups)), start_group, -1):
                window = groups[start_group:end_group]
                if any(len(g[2]) < _MIN_GROUP_DIGITS for g in window):
                    continue
                if len(window[-1][2]) < _MIN_LAST_GROUP_DIGITS:
                    continue
                national = national_phone_digits(
                    "".join(g[2] for g in window),
                    # The `+` belongs to the front of the span, so it only marks a
                    # number that starts there.
                    explicit=plus and start_group == 0,
                )
                if national is None:
                    continue
                pieces.append(body[cursor : window[0][0]])
                # Lossy on purpose: the last two digits stay so staff can recognise the
                # caller they are looking at (module docstring).
                pieces.append(PHONE_MASK.format(last2=national[-2:]))
                cursor = window[-1][1]
                swallowed_plus = swallowed_plus or (plus and start_group == 0)
                start_group = end_group
                break
            else:
                start_group += 1
        if not pieces:
            return match.group(0)
        _note("phone")
        pieces.append(body[cursor:])
        return ("" if swallowed_plus or not plus else "+") + "".join(pieces)

    out = _PHONE_SPAN_RE.sub(_phone, out)

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
    "national_phone_digits",
    "redact",
    "spoken_digit_runs",
]
