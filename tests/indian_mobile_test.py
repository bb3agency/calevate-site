"""One rule for "an Indian mobile", and a captured mobile is never flagged as not one.

The 26 Nov 2026 campaign call showed "This doesn't look like an Indian mobile number" under
+91 80198 57559, an 8-series mobile. The rule (ten digits opening 6-9) accepted it; what
flagged it was the shape the reading stored: a phone field typed as a number kept
`918019857559`, and a number with words or another figure beside it had every digit of the
answer joined into one string.
"""

from __future__ import annotations

import pytest
from apps.api.healer.routes import FallbackPhoneIn
from apps.api.ingest.service import normalize_phone as ingest_normalize
from calevate_shared.extraction import (
    PHONE_NEEDS_REVIEW,
    ExtractionField,
    ExtractionSchemaSpec,
    captured_phone,
    validate_extraction,
)
from calevate_shared.extraction import normalize_phone as extraction_normalize
from calevate_shared.indian_mobile import (
    INDIAN_MOBILE_E164_PATTERN,
    MOBILE_LEADING_DIGITS,
    is_indian_mobile,
    is_indian_mobile_e164,
)
from pydantic import ValidationError

THE_NUMBER = "+918019857559"

MOBILES = ["+916000000000", "+917000000000", THE_NUMBER, "+919999999999"]
NOT_MOBILES = [
    "+915999999999",  # a 5 opening is no mobile level
    "+910999999999",  # a trunk zero where the number starts
    "+911140000000",  # a Delhi landline
    "+91801985755",  # nine digits
    "+9180198575590",  # eleven digits
    "+448019857559",  # another country
    "918019857559",  # no plus
    "+91 80198 57559",  # not normalised
    # Arabic-Indic digits are not the stored form.
    "+91" + "".join(chr(0x0660 + int(d)) for d in "8019857559"),
]


@pytest.mark.parametrize("number", MOBILES)
def test_every_mobile_level_is_a_mobile(number: str) -> None:
    assert is_indian_mobile_e164(number)
    assert is_indian_mobile(number[3:])


@pytest.mark.parametrize("number", NOT_MOBILES)
def test_what_is_not_a_mobile_is_refused(number: str) -> None:
    assert not is_indian_mobile_e164(number)


def test_the_pattern_and_the_function_are_one_rule() -> None:
    import re

    pattern = re.compile(INDIAN_MOBILE_E164_PATTERN)
    for number in MOBILES + NOT_MOBILES:
        assert bool(pattern.match(number)) == is_indian_mobile_e164(number), number
    assert MOBILE_LEADING_DIGITS == "6789"


@pytest.mark.parametrize(
    "typed", ["+91 80198 57559", "80198 57559", "080198 57559", "91 80198 57559", "8019857559"]
)
def test_the_three_normalisers_agree_on_the_number(typed: str) -> None:
    assert ingest_normalize(typed) == THE_NUMBER
    assert extraction_normalize(typed) == THE_NUMBER
    assert captured_phone(typed) == THE_NUMBER


def test_the_fallback_phone_takes_an_8_series_mobile_and_refuses_a_5() -> None:
    assert FallbackPhoneIn(phone_e164=THE_NUMBER).phone_e164 == THE_NUMBER
    with pytest.raises(ValidationError):
        FallbackPhoneIn(phone_e164="+915999999999")


_TEXT = ExtractionField(key="other_number", label="Other number", type="text")
_NUMBER = ExtractionField(key="mobile", label="Mobile", type="number")


def _read(field: ExtractionField, value: object) -> tuple[object, str | None]:
    outcome = validate_extraction(ExtractionSchemaSpec(fields=[field]), {field.key: value})
    return outcome.data.get(field.key), outcome.needs_review.get(field.key)


@pytest.mark.parametrize("value", ["+91 80198 57559", "80198-57559", "080198 57559"])
def test_a_written_mobile_is_stored_canonical_and_not_flagged(value: str) -> None:
    assert _read(_TEXT, value) == (THE_NUMBER, None)


@pytest.mark.parametrize(
    "value", [8019857559, 918019857559, "8019857559", "+91 80198 57559", "080198 57559"]
)
def test_a_mobile_in_a_number_typed_phone_field_is_a_phone_not_a_quantity(value: object) -> None:
    assert _read(_NUMBER, value) == (THE_NUMBER, None)


@pytest.mark.parametrize(
    "value",
    [
        "80198 57559, call after 6 pm",
        "+91 80198 57559 (WhatsApp)",
        "number is 8019857559 - ask for the 2nd floor",
    ],
)
def test_a_mobile_with_words_and_figures_beside_it_is_the_mobile(value: str) -> None:
    assert _read(_TEXT, value) == (THE_NUMBER, None)


def test_two_mobiles_in_one_answer_are_kept_for_the_owner_to_choose() -> None:
    stored, note = _read(_TEXT, "8019857559 or 9876543210")
    assert stored not in (THE_NUMBER, "+919876543210")
    assert note == PHONE_NEEDS_REVIEW


@pytest.mark.parametrize("value", ["1234567890", "5019857559", "040 2345 6789", "80198 5755"])
def test_what_is_not_a_mobile_is_still_flagged(value: str) -> None:
    stored, note = _read(_TEXT, value)
    assert stored is not None
    assert note == PHONE_NEEDS_REVIEW


def test_a_quantity_in_a_number_field_that_is_no_phone_is_still_a_number() -> None:
    field = ExtractionField(key="budget", label="Budget", type="number")
    assert _read(field, "5000000000") == (5000000000, None)
