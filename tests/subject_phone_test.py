"""A data principal's number is accepted the way the form told them to type it.

THE DEFECT. `/v1/compliance/subject-export` and `/v1/compliance/deletion-requests` both
required strict E.164 while the data-rights form in front of them says "Ten digits, or the
full number starting with +", and every other phone surface in the product takes the number
as pasted. So the two endpoints that carry a person's DPDP §11 and §12 rights were the only
two that refused the instruction printed above their own input, with a 422 that named a
regular expression. A client relaying somebody's erasure request, on a screen about a legal
obligation, was told their input was invalid.

Run: uv run pytest tests/subject_phone_test.py -q
"""

from __future__ import annotations

import pytest
from apps.api.compliance.subject_phone import UNREADABLE, SubjectPhone
from pydantic import BaseModel, ValidationError


class _Model(BaseModel):
    phone: SubjectPhone


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("9876500111", "+919876500111"),
        ("+919876500111", "+919876500111"),
        ("919876500111", "+919876500111"),
        ("  98765 00111 ", "+919876500111"),
        ("+1 415 555 0132", "+14155550132"),
    ],
)
def test_the_forms_of_a_number_a_person_actually_types_all_arrive_as_e164(
    typed: str, stored: str
) -> None:
    """The handler still receives E.164 — normalising happens before it, not inside it.

    That is the whole security argument for these endpoints ("one phone number and
    nothing else") left intact: what reaches a query is the same value the old pattern
    would have admitted, for the inputs it admitted, plus the ones the form promised.
    """
    assert _Model(phone=typed).phone == stored


@pytest.mark.parametrize(
    "typed", ["", "98765", "not a number", "++919876500111", "+91+9876500111", "0123456789"]
)
def test_what_we_cannot_read_is_still_refused(typed: str) -> None:
    """Unweakened. `normalize_phone` refuses to guess a country and re-checks its output,
    so a `++91` or a number with no inferable country is a 422 exactly as before."""
    with pytest.raises(ValidationError):
        _Model(phone=typed)


def test_the_refusal_says_what_to_do_and_names_nothing_technical() -> None:
    """A person reads this on a screen about their legal rights. It may not name a
    pattern, a field or E.164 — it says what to type instead (GOV.UK's validation
    pattern, which `tests/plain_language_guard_test.py` cites as this repo's standard)."""
    lowered = UNREADABLE.lower()
    for leak in ("e.164", "pattern", "regex", "field", "invalid", "string"):
        assert leak not in lowered, f"{leak!r} is in a message a data principal reads"
    assert "ten digits" in lowered and "+" in UNREADABLE, "it must say what to type instead"


def test_both_data_rights_endpoints_use_the_one_door() -> None:
    """FAILS IF: a third data-rights endpoint grows its own phone pattern.

    The defect was two endpoints disagreeing with the rest of the product about what a
    phone number looks like. A second spelling is how that comes back.
    """
    from apps.api.compliance.deletion_routes import DeletionRequestIn
    from apps.api.compliance.export_routes import SubjectExportIn

    for model in (DeletionRequestIn, SubjectExportIn):
        assert model(phone="9876500111").phone == "+919876500111", (
            f"{model.__name__} does not accept the ten digits its own form asks for"
        )
