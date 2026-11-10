"""Inputs whose stored or wire form is ASCII digits refuse other scripts' digits at the door.

THE DEFECT (journey audit E10, 10 Nov 2026). Python's `re` and pydantic-core's regex both
read `\\d` as any Unicode decimal digit (general category Nd), not `[0-9]`. So a Telugu or
Devanagari keyboard's own digits passed every `Field(pattern=r"...\\d...")`:

* the business's handover contact (`tenancy/business_profile.BusinessContactIn`) and the
  line-down forwarding phone (`healer/routes.FallbackPhoneIn`) passed validation and then
  hit the table's `[0-9]` CHECK, an unhandled IntegrityError, so the owner got a 500;
* number, OTP, month and clock fields passed a value that is not the canonical form the
  rest of the code compares by equality or sends to the engine.

`ingest.normalize_phone` already folds any script's digits to ASCII for raw phone input;
these fields take a value that must ALREADY be canonical, so they refuse instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from apps.api.compliance.caller_ref import CallerRefError, _checked
from apps.api.healer.routes import FallbackPhoneIn
from apps.api.tenancy.business_profile import BusinessContactIn
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[1]

TELUGU = "".join(chr(0x0C66 + int(d)) for d in "876543210")
DEVANAGARI = "".join(chr(0x0966 + int(d)) for d in "876543210")


@pytest.mark.parametrize("digits", [TELUGU, DEVANAGARI], ids=["telugu", "devanagari"])
def test_a_handover_contact_in_another_scripts_digits_is_refused_not_a_500(digits: str) -> None:
    with pytest.raises(ValidationError):
        BusinessContactIn(label="Front desk", phone_e164="+919" + digits)
    # The ASCII number is still accepted.
    assert BusinessContactIn(label="Front desk", phone_e164="+919876543210").phone_e164


@pytest.mark.parametrize("digits", [TELUGU, DEVANAGARI], ids=["telugu", "devanagari"])
def test_a_forwarding_phone_in_another_scripts_digits_is_refused(digits: str) -> None:
    with pytest.raises(ValidationError):
        FallbackPhoneIn(phone_e164="+919" + digits)
    assert FallbackPhoneIn(phone_e164="+919876543210").phone_e164 == "+919876543210"


def test_a_caller_ref_refuses_a_number_that_is_not_ascii_e164() -> None:
    with pytest.raises(CallerRefError):
        _checked("+919" + TELUGU)
    assert _checked("+919876543210") == "+919876543210"


def _pattern_strings() -> list[tuple[str, int, str]]:
    """Every string literal passed as `pattern=` to a call in apps/api."""
    found: list[tuple[str, int, str]] = []
    for path in (REPO / "apps" / "api").rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "pattern"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    found.append((str(path.relative_to(REPO)), node.lineno, kw.value.value))
    return found


def test_no_request_field_pattern_reads_backslash_d() -> None:
    """A request pattern spells ASCII digits `[0-9]`: `\\d` admits every script's digits."""
    patterns = _pattern_strings()
    assert patterns, "the scan found no pattern= arguments at all"
    offenders = [f"{p}:{line} {pat}" for p, line, pat in patterns if re.search(r"\\d", pat)]
    assert offenders == []
