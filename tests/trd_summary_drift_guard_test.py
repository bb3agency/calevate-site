"""`check_docs_drift` §4f/§4g: TRD §10's SUMMARY cannot contradict §10.1's rate card.

WHY THIS FILE EXISTS. §4b has diffed §10.1's TABLE against the biller's constants for a
while, and it was green on the day TRD §10's own summary paragraph — the first per-minute
figure any reader meets — priced the Cartesia voice at ₹1.8628/min on a basis §10.1 had
already retired, and pointed at two `billing/rates.py` symbols that do not exist. The
summary is PROSE, so §4b never read it.

A guard over prose is only worth having if it survives prose being edited. So the tests
below are in two halves, and the second half is the one that matters: the first pins that
the check goes RED on the real defect, and the second pins that it stays GREEN across
rewordings that change no price — a reordered leg list, a reworded parenthetical, extra
symbol citations, a model name that looks like a decimal.
"""

from __future__ import annotations

from decimal import Decimal

from scripts.check_docs_drift import (
    TRD,
    doc_summary_tts_segment,
    doc_tts_per_minute_bands,
    rates_citation_drift,
    rates_module_names,
    tts_summary_drift,
)

TRD_TEXT = TRD.read_text(encoding="utf-8")


# --- the card the summary is judged against ------------------------------------------


def test_the_per_call_minute_column_parses_to_both_rungs() -> None:
    """§4f is only as good as its right-hand side, and that side is a table cell."""
    assert doc_tts_per_minute_bands(TRD_TEXT) == {
        "bulbul-v3": (Decimal("1.08"), Decimal("1.62")),
        "sonic-3.5": (Decimal("2.06"), Decimal("3.09")),
    }


def test_the_cartesia_rows_own_correction_note_is_not_read_as_the_current_band() -> None:
    """The trap this check was written around.

    §10.1's Cartesia row carries its RETIRED band (₹1.24-1.86) inside a correction note in
    its FIRST cell. A pattern that scanned the whole row would read the retired figures as
    current and then certify a summary quoting them.
    """
    band = doc_tts_per_minute_bands(TRD_TEXT)["sonic-3.5"]
    assert band == (Decimal("2.06"), Decimal("3.09"))
    assert Decimal("1.24") not in band
    assert Decimal("1.86") not in band


def test_the_summary_and_the_card_agree_today() -> None:
    assert tts_summary_drift(TRD_TEXT) == []
    assert rates_citation_drift(TRD_TEXT) == []


# --- half one: it goes red on the real defect ----------------------------------------

#: The §10 summary's TTS leg EXACTLY as it read before 10 Sep 2026, retired price and
#: nonexistent symbol included. Not a synthetic example — this is the defect.
_STALE_LEG = """**TTS 1.08–1.62 on the Sarvam
voice (Bulbul v3, billed per character) or 1.8628 on the Cartesia voice (Sonic 3.5 — a
MONTHLY PLAN spread over the platform-wide break-even minute count,
`billing/rates.py::cartesia_plan_inr_per_call_minute`; D-547 made the voice a per-agent
choice, so this leg now has two values and the call decides which)**"""


def _with_leg(leg: str) -> str:
    """TRD text with §10's summary TTS leg replaced by `leg`."""
    current = doc_summary_tts_segment(TRD_TEXT)
    assert current is not None
    return TRD_TEXT.replace(current, f" {leg}\n", 1)


def test_the_retired_price_fails_and_names_both_sides() -> None:
    failures = tts_summary_drift(_with_leg(_STALE_LEG))
    assert failures, "the pre-fix summary must not pass"
    assert any("1.8628" in line for line in failures), failures
    # And the other direction: a rung on the card that the summary no longer quotes.
    assert any("2.06" in line and "does not quote" in line for line in failures), failures


def test_the_nonexistent_symbol_fails_section_4g() -> None:
    failures = rates_citation_drift(_with_leg(_STALE_LEG))
    assert any("cartesia_plan_inr_per_call_minute" in line for line in failures), failures


def test_a_price_that_moves_in_the_card_alone_fails() -> None:
    """The commoner future defect: somebody reprices §10.1 and forgets the paragraph."""
    row = next(line for line in TRD_TEXT.splitlines() if line.startswith("| TTS — Cartesia"))
    repriced = TRD_TEXT.replace(row, row.replace("**₹2.06–3.09**", "**₹2.50–3.60**"), 1)
    assert repriced != TRD_TEXT
    assert doc_tts_per_minute_bands(repriced)["sonic-3.5"] == (
        Decimal("2.50"),
        Decimal("3.60"),
    )
    failures = tts_summary_drift(repriced)
    assert any("2.50" in line or "3.60" in line for line in failures), failures


# --- half two: it stays green when only the PROSE moves -------------------------------


def test_rewording_the_leg_changes_nothing() -> None:
    """Same four figures, entirely different sentence."""
    assert (
        tts_summary_drift(
            _with_leg(
                "**TTS: the Sarvam voice costs 1.08–1.62 and the Cartesia voice "
                "2.06–3.09, per agent since D-547**"
            )
        )
        == []
    )


def test_a_model_name_that_looks_like_a_price_is_not_read_as_one() -> None:
    """`Sonic 3.5` must never be read as ₹3.50, and `gpt-4.1-mini` never as ₹4.10."""
    assert (
        tts_summary_drift(
            _with_leg(
                "**TTS 1.08–1.62 (Bulbul v3) or 2.06–3.09 (Sonic 3.5, Sonic 3.5 again, "
                "D-547, TRD §10.1)**"
            )
        )
        == []
    )


def test_symbol_citations_are_never_read_as_prices() -> None:
    """A code span may carry any digits at all; §4g judges those, not §4f."""
    assert (
        tts_summary_drift(
            _with_leg(
                "**TTS 1.08–1.62 or 2.06–3.09 "
                "(`billing/rates.py::CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS`, "
                "`billing/rates.py::cartesia_cost_inr_per_call_minute`, "
                "`apps/api/billing/rates.py:1823`)**"
            )
        )
        == []
    )


def test_reordering_the_legs_changes_nothing() -> None:
    """The leg is found by the separator, not by position in the sentence."""
    reordered = TRD_TEXT.replace(
        "platform 1.5–2.0 (A-1) · STT 0.50 ·", "STT 0.50 · platform 1.5–2.0 (A-1) ·", 1
    )
    assert reordered != TRD_TEXT
    assert tts_summary_drift(reordered) == []


# --- the blind spots: a check that cannot see its subject must say so ------------------


def test_a_summary_this_check_cannot_find_is_a_failure_not_a_pass() -> None:
    blinded = TRD_TEXT.replace("Per-minute variable", "Per minute variable", 1)
    assert doc_summary_tts_segment(blinded) is None
    failures = tts_summary_drift(blinded)
    assert failures and "no TTS leg this check can find" in failures[0], failures


def test_a_card_this_check_cannot_read_is_a_failure_not_a_pass() -> None:
    blinded = TRD_TEXT.replace("### 10.1 Stack cost, computed from published rates", "### 10.1", 1)
    assert doc_tts_per_minute_bands(blinded) == {}
    failures = tts_summary_drift(blinded)
    assert failures and "no TTS band" in failures[0], failures


def test_the_symbol_registry_is_real() -> None:
    """§4g accepts a citation by ABSENCE from this set, so an empty set accepts anything."""
    names = rates_module_names()
    assert len(names) > 50
    assert {
        "TTS_INR_PER_10K_CHARS",
        "CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS",
        "cartesia_tts_inr_per_call_minute",
        "cartesia_cost_inr_per_call_minute",
    } <= names
    assert "cartesia_plan_inr_per_call_minute" not in names
