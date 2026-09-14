"""That the language declaration is internally consistent, and that the one distinction it
exists to hold — understood vs answerable — cannot be flattened by a later edit.

EVERY ASSERTION HERE IS A PROPERTY, NOT A COPY. A test that restates
`calevate_shared.languages._ROWS` as a literal passes whatever the table says, including
the two edits that actually cost a call: a language given a TTS code it does not have,
and a vendor wire code quietly normalised to its BCP-47 tag. So the intersection is
re-derived from `support()` rather than read off `conversational`, and the anomaly ledger
is compared against a set computed from the rows.

The three languages the product SELLS today (`agents/languages.py::Language`) are pinned by
name, because that is a promise a client can read on the marketing site and not an
internal invariant — if one of them ever stops being conversational, the failure belongs
here and not on a call.
"""

from __future__ import annotations

import dataclasses
import re
import typing

import pytest
from calevate_shared.languages import (
    KNOWN_WIRE_CODE_ANOMALIES,
    LANGUAGES,
    STT_LANGUAGES_PIPECAT_CANNOT_LABEL,
    UNVERIFIED_VENDOR_LEGS,
    VERIFIED_VENDOR_LEGS,
    Language,
    LanguageId,
    SpeechLeg,
    SpeechVendor,
    comprehension_only_languages,
    conversational_languages,
    find_language,
    get_language,
)

ALL: tuple[Language, ...] = tuple(LANGUAGES.values())

#: BCP-47 as this product uses it: an ISO 639 primary subtag (2-3 lowercase letters) and
#: an ISO 3166-1 region (2 uppercase letters), per RFC 5646 §2.1's case conventions. The
#: shape is checked rather than the spelling of any one tag, so a new row is covered.
_BCP47 = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")


def _supported(leg: SpeechLeg) -> set[LanguageId]:
    """The ids some VERIFIED vendor supports on that leg — derived from `support()`,
    never from the convenience properties the test is trying to check."""
    return {
        row.id
        for row in ALL
        for vendor, vendor_leg in VERIFIED_VENDOR_LEGS
        if vendor_leg == leg and row.support(vendor, leg) == "supported"
    }


def test_the_declaration_is_not_empty_and_has_both_kinds_in_it() -> None:
    assert ALL, "an empty language table would make every property below vacuously true"
    assert conversational_languages(), "a product with no conversational language sells nothing"
    assert comprehension_only_languages(), (
        "the comprehension-only set being empty would mean the STT and TTS legs agree — "
        "they do not, and a table that says they do has lost the distinction"
    )


def test_every_row_is_reachable_by_its_own_id() -> None:
    assert list(LANGUAGES) == [row.id for row in ALL]
    assert len({row.id for row in ALL}) == len(ALL), "duplicate LanguageId"
    assert len({row.bcp47 for row in ALL}) == len(ALL), "two languages claiming one tag"


def test_every_declared_language_id_has_a_row() -> None:
    """The `LanguageId` union and the table are one list written twice; this is the arm
    that keeps them the same list."""
    assert set(typing.get_args(LanguageId)) == set(LANGUAGES)


def test_codes_are_well_formed_bcp47() -> None:
    for row in ALL:
        assert _BCP47.match(row.bcp47), f"{row.id}: {row.bcp47!r} is not a well-formed BCP-47 tag"
        assert row.bcp47.endswith("-IN"), (
            f"{row.id}: this is the Indian-regional-language declaration; {row.bcp47!r} names "
            "another region"
        )


def test_vendor_wire_codes_are_well_formed_too() -> None:
    """A vendor may spell a code differently from BCP-47 (Odia does), but a code that is
    not even tag-SHAPED is a typo, and a typo here is a 400 on the first call."""
    for row in ALL:
        for (vendor, leg), code in row.codes.items():
            assert _BCP47.match(code), f"{row.id} {vendor}/{leg}: {code!r} is not tag-shaped"


def test_conversational_is_exactly_the_intersection_of_the_two_legs() -> None:
    """THE LOAD-BEARING ONE. Re-derived from `support()` on both sides."""
    understood = _supported("stt")
    answerable = _supported("tts")
    assert {row.id for row in conversational_languages()} == understood & answerable


def test_no_language_is_conversational_without_both_legs() -> None:
    for row in ALL:
        if row.conversational:
            assert row.understood and row.answerable, f"{row.id} claims conversational on one leg"
        else:
            assert not (row.understood and row.answerable), (
                f"{row.id} has both legs but is not offered — a language we can hold a call "
                "in must not be hidden by accident"
            )


def test_comprehension_only_is_the_remainder_and_overlaps_nothing() -> None:
    conversational = {row.id for row in conversational_languages()}
    comprehension = {row.id for row in comprehension_only_languages()}
    assert conversational.isdisjoint(comprehension)
    assert conversational | comprehension == _supported("stt")


def test_nothing_can_be_spoken_that_cannot_be_heard() -> None:
    """A TTS-only row would be an agent that talks at a caller it cannot understand. If a
    vendor ever ships one, this fails and somebody decides what it means — rather than it
    landing silently in the conversational set."""
    assert _supported("tts") <= _supported("stt")


def test_the_odia_spelling_discrepancy_is_captured_and_not_normalised() -> None:
    """The trap, asserted from both ends.

    First: the derived set of places a vendor code differs from the BCP-47 tag EQUALS the
    declared ledger — so normalising Odia away fails (the ledger would name a difference
    that no longer exists) and so does a new vendor quietly introducing its own spelling.
    """
    derived = {
        (vendor, leg, row.id): code
        for row in ALL
        for (vendor, leg), code in row.codes.items()
        if code != row.bcp47
    }
    assert derived == dict(KNOWN_WIRE_CODE_ANOMALIES)

    # Second, specifically: Odia is still carrying two different strings, on both legs.
    odia = get_language("odia")
    assert odia.bcp47 == "or-IN"
    for leg in typing.get_args(SpeechLeg):
        code = odia.wire_code("sarvam", leg)
        assert code is not None, "Odia is declared on both Sarvam legs"
        assert code != odia.bcp47, (
            "Odia's vendor code was made equal to its BCP-47 tag. Sarvam's own literals "
            "say 'od-IN' (sarvamai==0.1.28); smoothing that over sends a code the vendor "
            "does not accept."
        )


def test_the_languages_the_product_promises_today_are_conversational() -> None:
    """`agents/languages.py::Language` sells these three and the marketing site names
    them. Pinned by tag rather than by id, because the tag is what those surfaces carry —
    and by LITERAL tag rather than through `offered_language_tags()`, deliberately: this
    is the promise a client can read, so widening the offer must fail here and be
    re-argued, not pass because both sides moved. `tests/product_languages_test.py` holds
    the other direction (every surface derives from the offer)."""
    conversational = {row.bcp47 for row in conversational_languages()}
    for promised in ("te-IN", "hi-IN", "en-IN"):
        assert promised in conversational, f"{promised} is sold today and must stay answerable"


def test_telugu_leads_the_picker() -> None:
    """Telugu-first is a product position (BRD §1) and the order here is render order."""
    assert conversational_languages()[0].id == "telugu"


@pytest.mark.parametrize(("vendor", "leg"), sorted(UNVERIFIED_VENDOR_LEGS))
def test_an_unread_vendor_claims_nothing_either_way(vendor: SpeechVendor, leg: SpeechLeg) -> None:
    """`unverified` must never collapse into `supported` OR `unsupported`: the first would
    offer a language on a vendor nobody has checked, the second would print a ✗ we cannot
    justify to a client."""
    for row in ALL:
        assert row.support(vendor, leg) == "unverified"
        assert row.wire_code(vendor, leg) is None


def test_an_unverified_leg_cannot_widen_what_we_offer() -> None:
    """The safety property behind the three-valued enum, stated directly."""
    assert not (VERIFIED_VENDOR_LEGS & UNVERIFIED_VENDOR_LEGS)
    for row in ALL:
        legs_counted = {
            (vendor, leg)
            for vendor, leg in VERIFIED_VENDOR_LEGS
            if row.support(vendor, leg) == "supported"
        }
        assert legs_counted <= VERIFIED_VENDOR_LEGS


def test_the_pipecat_labelling_gap_never_costs_a_reply() -> None:
    """Every language the framework cannot label back to its own enum is one we could not
    answer anyway. If a CONVERSATIONAL language ever lands in that set, the gap stops
    being cosmetic and this fails."""
    comprehension = {row.id for row in comprehension_only_languages()}
    assert comprehension >= STT_LANGUAGES_PIPECAT_CANNOT_LABEL


def test_lookup_accepts_every_code_that_identifies_a_language() -> None:
    for row in ALL:
        assert find_language(row.id) is row
        assert find_language(row.bcp47) is row
        for code in row.codes.values():
            assert find_language(code) is row
    assert find_language("xx-IN") is None
    assert find_language("") is None


def test_both_odia_spellings_resolve_to_the_same_language() -> None:
    """The reason `find_language` takes vendor codes: a string off the wire does not carry
    which layer produced it."""
    assert find_language("or-IN") is find_language("od-IN") is get_language("odia")


def test_rows_are_immutable() -> None:
    """Frozen, because this is read by the picker, the publish path and the disclosure
    copy, and a shared mutable declaration is a tenancy bug waiting for a scope."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        get_language("telugu").bcp47 = "hi-IN"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        get_language("telugu").script.direction = "rtl"  # type: ignore[misc]


def test_display_fields_are_present_and_distinct() -> None:
    """They never reach a wire (the module docstring says why that matters), but a blank
    endonym is a picker row a caller's staff cannot read."""
    for row in ALL:
        assert row.endonym.strip(), f"{row.id} has no endonym"
        assert row.english_name.strip(), f"{row.id} has no English name"
        assert re.fullmatch(r"[A-Z][a-z]{3}", row.script.iso15924), (
            f"{row.id}: {row.script.iso15924!r} is not an ISO 15924 code"
        )
        assert row.script.direction in ("ltr", "rtl")
    assert len({row.endonym for row in ALL}) == len(ALL), "two rows sharing an endonym"


def test_right_to_left_languages_are_marked() -> None:
    """Urdu, Kashmiri and Sindhi are Perso-Arabic here; a transcript panel that does not
    know is unreadable rather than merely untidy. Asserted via the script, which is where
    the property lives."""
    rtl = {row.id for row in ALL if row.script.direction == "rtl"}
    assert rtl, "no RTL language is marked, yet Urdu is declared"
    for row in ALL:
        if row.script.iso15924 == "Arab":
            assert row.script.direction == "rtl", f"{row.id}: Perso-Arabic is written right-to-left"
