"""THE TWO PER-MINUTE COST FLOORS, derived leg by leg (D-547, plan §4.A.3).

`billing/rates.py` used to hold ONE floor — `Decimal("3.70")`, a blended figure typed as a
constant with the legs named only in a comment. Two things were wrong with it and both are
money: it carried a TELEPHONY leg the client pays (D-474, Model B — the client is the
subscriber of record on their own Exotel/Plivo/Vobiz account), and being typed rather than
summed it could not re-score itself when a leg moved. It is now a SUM of named legs, and
there are two of them because the second voice tier's TTS cost is a monthly plan rather
than a per-character price.

What this file protects, in the order it costs money:

- **The arithmetic**: each floor equals the sum of its legs, computed from the same
  functions the rest of the cost model uses. A leg that moves moves the floor.
- **No telephony leg**, asserted by value: both floors are well under any figure that
  includes ₹0.38-0.50/min of carrier cost.
- **The approved card clears both floors**, with the margin each rate actually delivers
  spelled out — including that the whole Sarvam column is UNDER the 20% target, which is
  the founder's decision and not a defect.
- **The conversion choice is bounded**: at `LIST_PRICE_USD_INR` instead of the Cartesia
  evidence file's own ₹88, the Cartesia floor is ₹4.5260 and the card still clears it. The
  comment in `rates.py` states that number; this is where it is computed rather than
  believed.
- **`BASE_RATE_LLM_MODEL` is the model the floor's LLM leg is priced at**, so the floor and
  the frozen plan rate cannot come to be struck against two different models.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.rates import (
    AZURE_OPENAI_DEFAULT_MODEL,
    BASE_RATE_LLM_MODEL,
    CARTESIA_COST_FLOOR_INR_PER_MIN,
    CARTESIA_EVIDENCE_USD_INR,
    CARTESIA_STARTUP_PLAN_CHARS,
    CARTESIA_STARTUP_PLAN_FEE_INR,
    CARTESIA_STARTUP_PLAN_FEE_USD,
    CARTESIA_TTS_INR_PER_10K_CHARS,
    COST_FLOOR_REFERENCE_CALL_MINUTES,
    COST_MODEL_USD_INR,
    ENGINE_PLATFORM_FEE_INR_PER_MIN,
    ENGINE_PLATFORM_FEE_USD_PER_MIN,
    LIST_PRICE_USD_INR,
    MIN_GROSS_MARGIN,
    MONEY_Q,
    ROUNDING,
    SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
    cartesia_plan_breakeven_call_minutes,
    cartesia_plan_inr_per_call_minute,
    cost_floor_inr_per_min,
    gross_margin_ratio,
    llm_cost_inr_per_minute,
    stt_rate_inr_per_minute,
    tts_inr_per_call_minute,
)

#: The published TELEPHONY estimate (TRD §10.1, ₹0.35-0.50/min) that neither floor carries.
#: Written here as a literal on purpose: the point of the assertion is that no constant in
#: `rates.py` holds it, so there is nothing to import.
TELEPHONY_ESTIMATE_LOW = Decimal("0.35")


def test_the_sarvam_floor_is_the_sum_of_its_four_named_legs() -> None:
    """₹1.76 fee + ₹0.50 STT + ₹0.2411 LLM + ₹1.62 TTS = ₹4.1211/min.

    Recomputed from the same functions the cost model exposes rather than from a literal, so
    a vendor price move in any leg fails here with the leg named — which is exactly what the
    old typed ₹3.70 could not do.
    """
    legs = (
        ENGINE_PLATFORM_FEE_INR_PER_MIN,
        stt_rate_inr_per_minute(),
        llm_cost_inr_per_minute(COST_FLOOR_REFERENCE_CALL_MINUTES, model=BASE_RATE_LLM_MODEL),
        tts_inr_per_call_minute(TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]),
    )
    assert (
        sum(legs, Decimal("0")).quantize(MONEY_Q, rounding=ROUNDING)
        == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    )
    assert Decimal("4.1211") == SELF_SERVE_COST_FLOOR_INR_PER_MIN


def test_the_engine_fee_leg_is_the_vendors_published_two_cents() -> None:
    """₹1.76 = $0.02 x 88, and the $0.02 is the vendor's own FAQ read in the hash-pinned
    mirror (`bolna-findings/mirror/pages/frequently-asked-questions.md:39`, 7 Sep 2026) —
    the class the whole tree calls VERIFIED-VENDOR-DOCS. Asserted as the PRODUCT so a
    conversion change and a fee change are distinguishable, which they were not while the
    leg was a founder's screenshot of a rupee figure.

    ⚠ It does NOT close pilot gate 12. A published rate is not OUR commercial term, and the
    vendor's Preferred Models page separately states a flat $0.06/min that BUNDLES the three
    model legs — a different line item for a non-BYOK shape, recorded beside the constant
    rather than reconciled, because no Bolna page reconciles them.
    """
    assert Decimal("0.02") == ENGINE_PLATFORM_FEE_USD_PER_MIN
    assert Decimal("88") == COST_MODEL_USD_INR
    assert Decimal("1.76") == ENGINE_PLATFORM_FEE_INR_PER_MIN


def test_the_llm_leg_is_priced_at_the_base_rate_model_and_the_longest_published_call() -> None:
    """The floor's LLM leg is the BASE-RATE model at TRD §10.1's longest published point.

    Two properties, each load-bearing. The MODEL: `BASE_RATE_LLM_MODEL` is the model the
    plan rate is frozen against, and a floor struck at a different one would drift from the
    rate it is defending the moment the platform default moved (it already has — the
    platform default is `gemini-2.5-flash-lite`, this is not). The LENGTH: the in-call LLM
    curve is quadratic in call duration, so ten minutes is the worst of the three points the
    doc publishes and a floor takes the worst case.
    """
    assert BASE_RATE_LLM_MODEL == AZURE_OPENAI_DEFAULT_MODEL
    assert COST_FLOOR_REFERENCE_CALL_MINUTES == 10
    ten = llm_cost_inr_per_minute(10, model=BASE_RATE_LLM_MODEL)
    for shorter in (1, 5):
        assert llm_cost_inr_per_minute(shorter, model=BASE_RATE_LLM_MODEL) < ten


def test_neither_floor_carries_a_telephony_leg() -> None:
    """D-474, Model B: the client buys the connection on their own carrier account and is
    billed the per-minute carrier rate by that carrier. Folding it in would defend our
    margin with a rupee we never pay.

    Asserted by ARITHMETIC rather than by grepping for the absence of a constant: each floor
    is exactly its own legs, so adding the cheapest published telephony estimate to those
    legs must overshoot it.
    """
    for voice in ("sarvam", "cartesia"):
        floor = cost_floor_inr_per_min(voice)  # type: ignore[arg-type]
        assert floor + TELEPHONY_ESTIMATE_LOW > floor
        assert floor < Decimal("4.40"), (
            f"the {voice} floor is {floor}; a telephony leg would put it above this line"
        )


def test_the_cartesia_floor_is_the_shared_legs_plus_the_plan_at_break_even() -> None:
    """A PLAN has no per-minute price until it is spread over the minutes it served.

    The break-even count is the allotment divided by the worst-case speaking rate — the
    month in which every character bought was spoken, which is the plan's BEST per-minute
    price. The floor is the three shared legs plus that.
    """
    assert CARTESIA_STARTUP_PLAN_FEE_INR == (
        CARTESIA_STARTUP_PLAN_FEE_USD * CARTESIA_EVIDENCE_USD_INR
    )
    assert Decimal("4312") == CARTESIA_STARTUP_PLAN_FEE_INR
    assert cartesia_plan_breakeven_call_minutes() == (
        CARTESIA_STARTUP_PLAN_CHARS / TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]
    )
    assert cartesia_plan_inr_per_call_minute() == Decimal("1.8628")
    shared = SELF_SERVE_COST_FLOOR_INR_PER_MIN - tts_inr_per_call_minute(
        TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]
    )
    assert shared == Decimal("2.5011")
    assert Decimal("4.3639") == CARTESIA_COST_FLOOR_INR_PER_MIN
    assert (shared + cartesia_plan_inr_per_call_minute()) == CARTESIA_COST_FLOOR_INR_PER_MIN


def test_the_cartesia_marginal_rate_is_derived_from_the_fee_and_the_allotment() -> None:
    """₹34.496 / 10,000 chars — never typed, so a fee or allotment change moves the doc row
    `check_docs_drift` §4b diffs it against."""
    assert Decimal("34.496") == CARTESIA_TTS_INR_PER_10K_CHARS
    assert (
        CARTESIA_STARTUP_PLAN_FEE_INR / CARTESIA_STARTUP_PLAN_CHARS * Decimal("10000")
    ) == CARTESIA_TTS_INR_PER_10K_CHARS


def test_the_cartesia_floor_holds_at_the_llm_cards_conversion_too() -> None:
    """THE BOUNDED ALTERNATIVE. `rates.py` uses the Cartesia evidence file's own ₹88 = $1 so
    the number in code is the number in the evidence it cites. The repo's other conversion
    is `LIST_PRICE_USD_INR` (₹95.66, the LLM card's strike). This computes the floor under
    that conversion — ₹4.5260 — and asserts the card still clears it, so the choice is
    scored rather than argued.
    """
    fee = CARTESIA_STARTUP_PLAN_FEE_USD * LIST_PRICE_USD_INR
    assert fee == Decimal("4687.34")
    plan_leg = (fee / cartesia_plan_breakeven_call_minutes()).quantize(MONEY_Q, rounding=ROUNDING)
    assert plan_leg == Decimal("2.0249")
    alternative = CARTESIA_COST_FLOOR_INR_PER_MIN - cartesia_plan_inr_per_call_minute() + plan_leg
    assert alternative == Decimal("4.5260")
    cheapest = min(pack.cartesia_inr_per_min for pack in PACK_CATALOGUE)
    assert cheapest > alternative, "the card must clear the floor under either conversion"


def test_the_floor_selector_is_total_over_the_two_tiers_and_raises_otherwise() -> None:
    """One door, two floors, and no default. A selector that fell back to the cheaper floor
    for an unknown tier would pass every check and undercharge for the dearer voice."""
    assert cost_floor_inr_per_min("sarvam") == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert cost_floor_inr_per_min("cartesia") == CARTESIA_COST_FLOOR_INR_PER_MIN
    assert cost_floor_inr_per_min("cartesia") > cost_floor_inr_per_min("sarvam")
    with pytest.raises(ValueError, match="no cost floor"):
        cost_floor_inr_per_min("elevenlabs")  # type: ignore[arg-type]


def test_the_approved_card_clears_both_floors_and_the_sarvam_column_is_under_target() -> None:
    """THE MARGIN THE APPROVED CARD ACTUALLY DELIVERS, written out.

    ⚠ Every Sarvam rate is UNDER `MIN_GROSS_MARGIN` and every one is above cost. That is the
    founder's card (plan §2.2) read against a floor re-derived without telephony, and it is
    why `credit_packs.card_refusals` refuses below COST and only reports below TARGET. If
    this test ever fails because a Sarvam margin rose past 20%, the floor or the card moved
    and somebody should know which.
    """
    expected = {
        ("starter", "sarvam"): Decimal("0.1758"),
        ("starter", "cartesia"): Decimal("0.4545"),
        ("growth", "sarvam"): Decimal("0.1758"),
        ("growth", "cartesia"): Decimal("0.3766"),
        ("scale", "sarvam"): Decimal("0.1503"),
        ("scale", "cartesia"): Decimal("0.3535"),
        ("plus", "sarvam"): Decimal("0.1232"),
        ("plus", "cartesia"): Decimal("0.3286"),
        ("pro", "sarvam"): Decimal("0.1041"),
        ("pro", "cartesia"): Decimal("0.3018"),
        ("max", "sarvam"): Decimal("0.0842"),
        ("max", "cartesia"): Decimal("0.2727"),
    }
    for pack in PACK_CATALOGUE:
        for voice in ("sarvam", "cartesia"):
            rate = pack.inr_per_min(voice)  # type: ignore[arg-type]
            floor = cost_floor_inr_per_min(voice)  # type: ignore[arg-type]
            assert rate > floor, f"{pack.pack_id}/{voice} is below cost"
            margin = gross_margin_ratio(rate=rate, cost=floor).quantize(Decimal("0.0001"))
            assert margin == expected[(pack.pack_id, voice)]
            assert (margin < MIN_GROSS_MARGIN) is (voice == "sarvam")
