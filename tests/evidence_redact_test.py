"""Hard rule 6 for an artefact that is committed to the repository forever.

The scrubber `scripts/eval.py::write_evidence` runs as its second layer, tested here on
inputs that are deliberately dirty.
"""

from __future__ import annotations

from scripts.evidence_redact import DIGIT_MASK, scrub, scrub_text


def test_an_e164_number_never_survives_serialization() -> None:
    """E.164, asserted as a PROPERTY rather than as a marker.

    The shared redactor claims this string first; the long-run sweep is what catches a
    digit run the phone pattern is not meant to know about. Asserting the ABSENCE of the
    digits lets either layer own the string.
    """
    cleaned, hits = scrub_text("dialled +919876543210 for the report")
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
    """Callers read numbers out loud, in Telugu, and a transcript excerpt can land in an
    artefact. `redact`'s spoken-digit normaliser is why this module reuses it instead of
    writing fresh regexes."""
    cleaned, hits = scrub_text("naa number tommidi enimidi edu aaru aidu naalugu")
    assert "tommidi enimidi edu aaru aidu naalugu" not in cleaned
    assert hits >= 1


def test_engine_ids_are_not_mistaken_for_phone_numbers() -> None:
    """`fakeagent_ee4edcaa460007891e333f44` has nine digits inside a hex id; the
    lookarounds in `_LONG_DIGIT_RUN` exist so it is not masked."""
    cleaned, hits = scrub_text("agent created (ref fakeagent_ee4edcaa460007891e333f44)")
    assert cleaned == "agent created (ref fakeagent_ee4edcaa460007891e333f44)"
    assert hits == 0


def test_an_iso_timestamp_survives_intact() -> None:
    cleaned, hits = scrub_text("generated_at 2026-08-13T09:41:22.512843+00:00")
    assert hits == 0
    assert "2026-08-13" in cleaned


def test_scrubbing_reaches_keys_as_well_as_values() -> None:
    """A caller that writes `{"+919876543210": "ok"}` has leaked exactly as much as one
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
    """A non-zero count means the reporting path let something through, and the writer
    refuses rather than quietly cleaning up after it."""
    _, clean_hits = scrub({"detail": "execution exec-abc123 recovered"})
    assert clean_hits == 0
    _, dirty_hits = scrub({"detail": "rang +919876543210"})
    assert dirty_hits >= 1


def test_non_string_scalars_pass_through_untouched() -> None:
    cleaned, hits = scrub({"deliveries": 2, "ok": True, "rate": 1.5, "absent": None})
    assert cleaned == {"deliveries": 2, "ok": True, "rate": 1.5, "absent": None}
    assert hits == 0
