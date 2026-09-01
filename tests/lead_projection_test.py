"""What a lead contributes to the caller-chunk store, and what it must never contribute.

The projection is a pure function precisely so these are assertions rather than prose, and
every one of them is a data-protection decision as much as a retrieval one: an embedding of
a caller's words is a copy of those words, so a field that appears here is a field this
product copied into a second store that erasure then has to reach.
"""

from __future__ import annotations

from apps.api.crm.lead_projection import (
    LEAD_SUBJECT_KIND,
    project_field,
    project_lead,
)
from apps.api.kb.service import MAX_CHUNK_CHARS
from calevate_shared.extraction import ExtractionField


def _field(key: str, label: str, type_: str = "text", **kw: object) -> ExtractionField:
    return ExtractionField.model_validate({"key": key, "label": label, "type": type_, **kw})


_REQUIREMENT = _field("requirement", "Requirement")
_LOCALITY = _field("locality", "Preferred locality")


def test_a_lead_contributes_its_labelled_text_and_enum_fields() -> None:
    """The whole point: the words a person would search, under the label that gives them
    meaning. "Gachibowli" is a token; "Preferred locality: Gachibowli" is a fact."""
    fields = [
        _REQUIREMENT,
        _LOCALITY,
        _field("timeline", "Timeline", "enum", enum_values=["this month", "next quarter"]),
    ]
    projection = project_lead(
        fields,
        {
            "requirement": "looking for a 3BHK with a balcony",
            "locality": "Gachibowli",
            "timeline": "this month",
        },
    )
    assert len(projection.chunks) == 1
    assert projection.chunks[0].text == (
        "Requirement: looking for a 3BHK with a balcony\n"
        "Preferred locality: Gachibowli\n"
        "Timeline: this month"
    )
    assert projection.chunks[0].keys == ("requirement", "locality", "timeline")
    assert projection.chunks[0].idx == 0


def test_a_phone_field_is_never_projected_however_it_is_declared() -> None:
    """An identifier, not a search key — and the Leads screen already matches numbers
    exactly. The hint is the schema's own (`is_phone_field` reads key, label and reason),
    so a client who names the field "alt" and explains it in `reason` is still covered."""
    for field in (
        _field("alternate_number", "Alternate number"),
        _field("alt", "Alt", reason="their whatsapp number for follow-up"),
        _field("contact", "Best contact"),
    ):
        assert project_field(field, "9876543210") is None


def test_numbers_dates_and_booleans_are_left_to_the_filters() -> None:
    """Excluded by TYPE. An embedding of "42" is close to every other number in the corpus
    and crowds a real answer out of the top-k, and these are exactly the fields the Leads
    screen already filters on exactly."""
    assert project_field(_field("budget", "Budget in lakhs", "number"), 80) is None
    assert project_field(_field("visit_on", "Visit date", "date"), "2026-09-04") is None
    assert project_field(_field("has_loan", "Loan approved", "bool"), True) is None
    # And the value's own truthiness is not what excludes it: a False bool is refused for
    # being a bool, not for looking empty.
    assert project_field(_field("has_loan", "Loan approved", "bool"), False) is None


def test_an_erased_lead_projects_to_nothing() -> None:
    """`data = '{}'::jsonb` IS the erased state of a lead — no row is deleted, so no
    cascade fires. A re-projection racing an erasure must not put the sentence back."""
    assert project_lead([_REQUIREMENT, _LOCALITY], {}).chunks == ()
    assert project_lead([_REQUIREMENT, _LOCALITY], None).chunks == ()
    # A blank or whitespace value is the same nothing, one field at a time.
    assert project_lead([_REQUIREMENT], {"requirement": "   "}).chunks == ()


def test_a_data_key_the_schema_cannot_name_is_dropped_and_counted() -> None:
    """`crm/columns.resolve`'s rule for a stale reference, and it is the safe direction
    here for a second reason: an unnamed key could be a phone field from a schema the
    client has since edited, and a guessed label cannot apply the phone exclusion."""
    projection = project_lead(
        [_REQUIREMENT], {"requirement": "3BHK", "old_alt_number": "9876543210"}
    )
    assert projection.chunks[0].text == "Requirement: 3BHK"
    assert projection.unknown_keys == ("old_alt_number",)
    assert "9876543210" not in projection.chunks[0].text


def test_fields_are_projected_in_schema_order_not_payload_order() -> None:
    """The client chose the order on their own Leads table, so two leads captured under
    one schema chunk the same way and a dict's insertion order never moves a boundary."""
    payload = {"locality": "Kondapur", "requirement": "2BHK"}
    assert project_lead([_REQUIREMENT, _LOCALITY], payload).chunks[0].keys == (
        "requirement",
        "locality",
    )


def test_a_large_payload_packs_into_capped_chunks_and_loses_no_field() -> None:
    """One vector holds one idea, so a forty-field lead is several chunks — and every
    field it had is in exactly one of them."""
    fields = [_field(f"f{i}", f"Field {i}") for i in range(40)]
    payload = {f"f{i}": "x" * 200 for i in range(40)}
    projection = project_lead(fields, payload)
    assert len(projection.chunks) > 1
    # The stub-tail merge is the one place the cap may be exceeded, and it is bounded.
    assert all(len(chunk.text) <= MAX_CHUNK_CHARS + 80 + 1 for chunk in projection.chunks)
    assert [chunk.idx for chunk in projection.chunks] == list(range(len(projection.chunks)))
    seen = [key for chunk in projection.chunks for key in chunk.keys]
    assert seen == [f"f{i}" for i in range(40)]


def test_the_subject_kind_is_the_retention_category() -> None:
    """One vocabulary, not two: these rows expire on the tenant's `lead` policy clock
    (`workers/retention.DERIVED_COPIES`), and the store's `subject_kind` is the same word
    so a reader cannot hold them apart."""
    assert LEAD_SUBJECT_KIND == "lead"
