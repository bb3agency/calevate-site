"""Hard rule 6 for an artefact that gets committed to git forever.

TWO LAYERS, TESTED SEPARATELY, AND THE SEPARATION IS THE WHOLE POINT. `tests/
pilot_gates_test.py` asserts layer one — that gates never write a caller's number into a
result at all — against RAW result objects, before the scrubber has run. This file tests
layer two, the scrubber itself, on inputs that are deliberately dirty.

If both were tested through the scrubbed output, deleting layer one entirely would leave
every test green: the classic trap where a sabotage survives because a later guard caught
it. Which layer is doing the work has to be decidable, so each is measured where the
other one cannot help it.
"""

from __future__ import annotations

from scripts.pilot.redact import DIGIT_MASK, scrub, scrub_text


def test_an_e164_number_never_survives_serialization() -> None:
    """The exact shape this harness handles, asserted as a PROPERTY rather than as a
    marker.

    This docstring used to say the post-call pipeline's phone pattern "cannot match it —
    `\\b` never fires inside a continuous digit run", and treat that as the justification
    for the long-run sweep here. That was a true observation about a DEFECT, written down
    as though it were a design constraint: `_PHONE_RE`'s `\\b` sat after an optional `+91`,
    where it could never fire, so E.164 — the only form `leads.phone_e164` ever holds —
    passed the shared redactor untouched and reached hot-lead email in full.

    It is fixed, so the shared redactor now claims this string first and the mask is a
    phone mask rather than the generic digit mask. The sweep here is not thereby
    decorative: it is the second layer, and it is what catches a digit run the phone
    pattern is not meant to know about. Asserting the ABSENCE of the digits rather than
    the presence of one layer's marker is what lets either layer own the string without
    this test having an opinion about which.
    """
    cleaned, hits = scrub_text("dialled +919876543210 for the pilot")
    assert "9876543210" not in cleaned
    assert "919876543210" not in cleaned
    assert hits >= 1
    # The generic sweep still owns a digit run that is NOT phone-shaped, which is the
    # thing this module adds over the shared redactor.
    long_run, long_hits = scrub_text("execution 123456789012345 completed")
    assert DIGIT_MASK in long_run
    assert long_hits >= 1


def test_a_bare_indian_mobile_is_caught_by_the_shared_redactor() -> None:
    cleaned, hits = scrub_text("callback on 9876543210 please")
    assert "9876543210" not in cleaned
    assert hits >= 1


def test_transcript_text_with_spoken_digits_is_caught() -> None:
    """Callers read numbers out loud, in Telugu, and a pilot transcript lands in the
    artefact. `redact`'s spoken-digit normaliser is why this module reuses it instead of
    writing fresh regexes."""
    cleaned, hits = scrub_text("naa number tommidi enimidi edu aaru aidu naalugu")
    assert "tommidi enimidi edu aaru aidu naalugu" not in cleaned
    assert hits >= 1


def test_engine_ids_are_not_mistaken_for_phone_numbers() -> None:
    """An alarm that fires on healthy output is one nobody reads when it fires for real.
    The first run of this harness masked `fakeagent_ee4edcaa460007891e333f44` — nine
    digits in the middle of a hex id — and that false positive is what the lookarounds
    in `_LONG_DIGIT_RUN` exist to remove."""
    cleaned, hits = scrub_text("agent created (ref fakeagent_ee4edcaa460007891e333f44)")
    assert cleaned == "agent created (ref fakeagent_ee4edcaa460007891e333f44)"
    assert hits == 0


def test_an_iso_timestamp_survives_intact() -> None:
    cleaned, hits = scrub_text("generated_at 2026-08-13T09:41:22.512843+00:00")
    assert hits == 0
    assert "2026-08-13" in cleaned


def test_scrubbing_reaches_keys_as_well_as_values() -> None:
    """A gate that writes `{"+919876543210": "ok"}` has leaked exactly as much as one
    that writes it the other way round."""
    cleaned, hits = scrub({"+919876543210": "ok"})
    assert "9876543210" not in repr(cleaned)
    assert hits >= 1


def test_scrubbing_recurses_through_lists_and_nested_objects() -> None:
    artefact = {
        "gates": [
            {"checks": [{"detail": "compared against +919876543210"}]},
        ]
    }
    cleaned, hits = scrub(artefact)
    assert "9876543210" not in repr(cleaned)
    assert hits >= 1


def test_the_count_is_returned_because_a_hit_is_a_defect_report() -> None:
    """A non-zero count means layer one let something through. Swallowing it would mean
    quietly cleaning up after a gate that will do the same thing tomorrow."""
    _, clean_hits = scrub({"detail": "execution exec-abc123 recovered"})
    assert clean_hits == 0
    _, dirty_hits = scrub({"detail": "rang +919876543210"})
    assert dirty_hits >= 1


def test_non_string_scalars_pass_through_untouched() -> None:
    cleaned, hits = scrub({"deliveries": 2, "ok": True, "rate": 1.5, "absent": None})
    assert cleaned == {"deliveries": 2, "ok": True, "rate": 1.5, "absent": None}
    assert hits == 0
