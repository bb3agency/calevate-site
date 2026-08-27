"""The STT leg has a rate constant, a cost function, and a drift check — the TTS half's
three parts, arriving on the leg that had none of them.

THE DEFECT THIS PINS. TTS is billed per CHARACTER and has had `TTS_INR_PER_10K_CHARS`,
`tts_cost_inr` and `scripts/check_docs_drift.py` §4b since the rate card was written. STT
is billed per unit of AUDIO TIME and had NONE of them: ₹30/hour lived in TRD §10.1 prose
and, blended with four other legs, inside `SELF_SERVE_COST_FLOOR_INR_PER_MIN`. A money
figure with one home and no check is D-103/D-105 exactly — Sarvam moves the price, the doc
changes, and nothing in code notices (or the reverse).

WHAT IS ASSERTED HERE and why each line is worth a test:

* the constant is NUMERIC and never a float (hard rule 7);
* exact values at round inputs, including the hour↔minute conversion, because the doc
  states the rate in both units and a lossy conversion is how the two spellings drift;
* a negative duration RAISES rather than pricing to a negative cost;
* zero is zero, which is not an error — a call that transcribed nothing costs nothing;
* the drift check moves in BOTH directions and fails on an empty reading.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import scripts.check_docs_drift as guard
from apps.api.billing import rates

# --- the rate card (TRD §10.1, VENDOR-PUBLISHED via the founder's dashboard reading) ---


def test_the_stt_rate_is_one_numeric_scalar() -> None:
    assert Decimal("30.0000") == rates.STT_INR_PER_HOUR
    assert isinstance(rates.STT_INR_PER_HOUR, Decimal)
    assert not isinstance(rates.STT_INR_PER_HOUR, float)


def test_the_two_spellings_of_the_rate_are_exactly_one_rate() -> None:
    """₹30/hour is ₹0.50/minute and ₹0.008333…/second, and the per-minute figure is
    DERIVED — there is no second constant that could disagree with the first."""
    assert rates.stt_rate_inr_per_minute() == Decimal("0.5")
    assert rates.stt_rate_inr_per_minute() * 60 == rates.STT_INR_PER_HOUR
    assert rates.stt_rate_inr_per_second() * 60 == rates.stt_rate_inr_per_minute()
    # Unquantized on purpose: the per-second rate has no exact 4-decimal rupee, and
    # rounding it here would round twice for every caller.
    assert rates.stt_rate_inr_per_second() != rates.stt_rate_inr_per_second().quantize(
        rates.MONEY_Q, rounding=rates.ROUNDING
    )


def test_stt_cost_takes_seconds_and_prices_round_inputs_exactly() -> None:
    """SECONDS, because that is the unit a call's duration exists in everywhere in this
    codebase (`duration_s`), so no caller has to divide by 60 first."""
    assert rates.stt_cost_inr(3600) == Decimal("30.0000")
    assert rates.stt_cost_inr(60) == Decimal("0.5000")
    assert rates.stt_cost_inr(600) == Decimal("5.0000")
    assert isinstance(rates.stt_cost_inr(60), Decimal)


def test_a_negative_duration_is_refused_rather_than_priced() -> None:
    """A negative duration would price to a NEGATIVE cost, which on a usage event is a
    credit issued by an arithmetic accident — the argument `tts_cost_inr` makes, and the
    one `workers/pipeline.py::_billable_seconds` had to make on the live money path."""
    with pytest.raises(ValueError, match="negative"):
        rates.stt_cost_inr(-1)
    with pytest.raises(ValueError):
        rates.stt_cost_inr(-3600)
    assert rates.stt_cost_inr(0) == Decimal("0.0000")


def test_the_stt_card_prices_no_diarization_rung() -> None:
    """₹45/hour is a real Sarvam rate and is deliberately NOT a constant: nothing in this
    repository enables diarization, and pricing a feature we do not turn on puts a figure
    in the margin model that no call can produce."""
    assert not [name for name in dir(rates) if "diariz" in name.lower()]


# --- the Sarvam chat card, which is NOT free (the correction) --------------------------


def test_the_sarvam_chat_leg_is_priced_and_is_not_zero() -> None:
    """D-36's "free per token" premise is withdrawn (founder's dashboard reading,
    27 Aug 2026). Every rung is NUMERIC and strictly positive — a zero here is what made
    the assist meters record nothing."""
    card = rates.SARVAM_LLM_INR_PER_MTOK
    assert set(card) == {"in", "cached_in", "out"}
    assert card["in"] == Decimal("29.28")
    assert card["cached_in"] == Decimal("10.98")
    assert card["out"] == Decimal("73.20")
    assert all(isinstance(v, Decimal) and not isinstance(v, float) for v in card.values())
    assert all(v > 0 for v in card.values())
    assert card["cached_in"] < card["in"] < card["out"]


def test_the_sarvam_reference_is_per_thousand_tokens_and_storable() -> None:
    """Per THOUSAND, the unit `usage_events` counts an LLM leg in, and quantized to what
    `unit_cost_paid` can store — a price the ledger cannot hold is one it cannot honour."""
    per_ktok = rates.sarvam_llm_reference_inr_per_ktok()
    assert per_ktok == {
        "in": Decimal("0.0293"),
        "cached_in": Decimal("0.0110"),
        "out": Decimal("0.0732"),
    }
    assert all(v == v.quantize(rates.MONEY_Q) for v in per_ktok.values())


def test_the_sarvam_card_has_no_path_to_a_bill() -> None:
    """Hard rule 7: `llm_inr_per_ktok` is the one door to `unit_cost_paid`, and this card
    is not behind it. The identifier is not in the offered catalogue either — Sarvam is the
    disclosed dashboard fallback, not a model a client may pick."""
    with pytest.raises(ValueError):
        rates.llm_inr_per_ktok(rates.SARVAM_PRICED_LLM)
    assert not rates.llm_price_is_billable(rates.SARVAM_PRICED_LLM)
    assert rates.SARVAM_PRICED_LLM not in rates.PRICED_LLM_MODELS


# --- §4d: the doc and the code state one rate ------------------------------------------


def _mutated(old: str, new: str) -> str:
    document = guard.TRD.read_text(encoding="utf-8")
    assert old in document, f"TRD no longer contains {old!r} — the mutation tests are stale"
    return document.replace(old, new)


def test_the_shipped_tree_has_no_stt_rate_drift() -> None:
    assert not guard.stt_rate_card_drift()
    # The reading is non-empty, which is the half a reworded table would break silently.
    assert guard.doc_stt_rates_per_hour()
    assert guard.doc_stt_rates_per_minute() == [Decimal("0.50")]


def test_a_moved_doc_rate_is_drift() -> None:
    offenders = guard.stt_rate_card_drift(_mutated("₹30 / hour", "₹36 / hour"))
    assert offenders and any("36" in line for line in offenders)


def test_a_doc_that_disagrees_with_itself_across_units_is_drift() -> None:
    """The cheapest version of this failure and the likeliest to survive review: each
    table reads fine alone."""
    offenders = guard.stt_rate_card_drift(_mutated("**₹0.50**", "**₹0.60**"))
    assert offenders and any("two units" in line for line in offenders)


def test_a_code_side_move_is_drift_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both directions. The doc is the spec, but a rate edited only in code is the same
    defect wearing the other hat."""
    monkeypatch.setattr(rates, "STT_INR_PER_HOUR", Decimal("36.0000"))
    offenders = guard.stt_rate_card_drift()
    assert offenders and any("STT_INR_PER_HOUR" in line for line in offenders)


def test_a_reading_that_finds_nothing_is_a_failure_not_a_pass() -> None:
    """`llm_cost_curve_drift`'s argument: a guard that cannot find its subject has not
    verified it, and a reworded table would otherwise leave the money unguarded while the
    gate still prints OK."""
    assert guard.stt_rate_card_drift("### 10.1 Stack cost, computed from published rates\n")
    dropped = _mutated("| STT — Saaras (STT+Translate) | ₹30/hr | **₹0.50** |", "")
    offenders = guard.stt_rate_card_drift(dropped)
    assert offenders and any("per-call-minute" in line for line in offenders)


def test_the_diarization_row_is_not_reconciled_against_the_saaras_rate() -> None:
    """₹45/hour is a different rate for a feature we do not enable. Scoring it would report
    drift on a document that is right."""
    document = guard.TRD.read_text(encoding="utf-8")
    assert "| STT with diarization | ₹45 / hour |" in document
    assert Decimal("45") not in guard.doc_stt_rates_per_hour(document)
    assert not guard.stt_rate_card_drift(document)
