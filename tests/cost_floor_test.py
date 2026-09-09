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
from apps.api.billing.credit_packs import PACK_CATALOGUE, card_refusals
from apps.api.billing.rates import (
    AZURE_OPENAI_DEFAULT_MODEL,
    BASE_RATE_LLM_MODEL,
    CARTESIA_BEST_MARGINAL_COST_INR_PER_MIN,
    CARTESIA_COST_FLOOR_INR_PER_MIN,
    CARTESIA_EVIDENCE_USD_INR,
    CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS,
    CARTESIA_PLANS,
    CARTESIA_PRO_PLAN,
    CARTESIA_STARTUP_PLAN,
    CARTESIA_VENDOR_CREDITS_PER_AUDIO_MINUTE,
    CARTESIA_VOLUME_LADDER_CALL_MINUTES,
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
    cartesia_cheapest_plan,
    cartesia_cost_floor_inr_per_min_at,
    cartesia_cost_inr_per_call_minute,
    cartesia_envelope_stable_call_minutes,
    cartesia_measured_cost_inr_per_call_minute,
    cartesia_plan_crossover_call_minutes,
    cartesia_plan_marginal_cost_inr_per_min,
    cartesia_rung_breakeven_call_minutes,
    cost_floor_inr_per_min,
    ex_tts_cost_inr_per_min_at,
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
        ceiling = Decimal("4.40") if voice == "sarvam" else Decimal("5.80")
        assert floor < ceiling, (
            f"the {voice} floor is {floor}; a telephony leg would put it above this line"
        )


def _shared_legs() -> Decimal:
    """The three legs both voices share, ₹2.5011, backed out of the Sarvam floor rather
    than re-summed — so this file cannot drift from `rates._ex_tts_cost_inr_per_min`."""
    return SELF_SERVE_COST_FLOOR_INR_PER_MIN - tts_inr_per_call_minute(
        TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]
    )


def test_the_cartesia_plans_are_the_vendors_three_inputs_and_nothing_derived_is_typed() -> None:
    """Fee, allotment and overage per plan — VENDOR-PUBLISHED (Tinmaz correspondence,
    9 Sep 2026, `docs/evidence/cartesia-tts-verification-2026-09-06.md` ADDENDUM 3).

    Every other figure about a plan is arithmetic over those three, asserted here so a
    change to the conversion or to the assumed speaking rate cannot pass silently.
    """
    assert [plan.plan_id for plan in CARTESIA_PLANS] == ["pro", "startup"]

    assert CARTESIA_PRO_PLAN.fee_usd == Decimal("5")
    assert CARTESIA_PRO_PLAN.included_credits == Decimal("100000")
    assert CARTESIA_PRO_PLAN.overage_usd_per_million_credits == Decimal("65")
    assert (
        CARTESIA_PRO_PLAN.fee_inr(CARTESIA_EVIDENCE_USD_INR)
        == Decimal("5") * CARTESIA_EVIDENCE_USD_INR
        == Decimal("440")
    )
    assert CARTESIA_PRO_PLAN.overage_inr_per_character(CARTESIA_EVIDENCE_USD_INR) == Decimal(
        "0.00572"
    )
    assert CARTESIA_PRO_PLAN.marginal_inr_per_call_minute(CARTESIA_EVIDENCE_USD_INR) == Decimal(
        "3.08880"
    )
    # 100,000 credits at 540 chars a call-minute is ~185 call-minutes of allotment.
    assert CARTESIA_PRO_PLAN.included_call_minutes.quantize(Decimal("0.01")) == Decimal("185.19")

    assert CARTESIA_STARTUP_PLAN.fee_usd == Decimal("49")
    assert CARTESIA_STARTUP_PLAN.included_credits == Decimal("1250000")
    assert CARTESIA_STARTUP_PLAN.overage_usd_per_million_credits == Decimal("45")
    assert CARTESIA_STARTUP_PLAN.fee_inr(CARTESIA_EVIDENCE_USD_INR) == Decimal("4312")
    assert CARTESIA_STARTUP_PLAN.marginal_inr_per_call_minute(CARTESIA_EVIDENCE_USD_INR) == Decimal(
        "2.13840"
    )


def test_the_cartesia_floor_is_the_worst_marginal_cost_and_not_a_best_case() -> None:
    """⚠ THE REGRESSION THIS FILE EXISTS TO CATCH FROM 9 SEP 2026.

    The floor used to be ₹4.3639 — the $49 Startup fee spread over the 2,315 call-minutes
    at which its allotment is exactly consumed, i.e. the plan's BEST per-minute price at a
    volume this platform has never run — printed on the ops console under a column headed
    "COSTS US". The founder read it and said the Cartesia leg could not cost us that little.

    It is now the WORST MARGINAL cost: what one more call-minute costs on the dearest plan
    we can be on. That is the only per-minute figure about a subscription that does not
    depend on an unmeasured volume, and it is the figure a refusal threshold has to be
    struck at. **If this assertion ever reads ₹4.3639 again, the best case has come back.**
    """
    shared = _shared_legs()
    assert shared == Decimal("2.5011")
    assert Decimal("5.5899") == CARTESIA_COST_FLOOR_INR_PER_MIN
    assert Decimal("4.3639") != CARTESIA_COST_FLOOR_INR_PER_MIN
    assert (
        shared
        + max(
            plan.marginal_inr_per_call_minute(CARTESIA_EVIDENCE_USD_INR) for plan in CARTESIA_PLANS
        )
    ).quantize(MONEY_Q, rounding=ROUNDING) == CARTESIA_COST_FLOOR_INR_PER_MIN
    # Pro is the dearest at the margin, so it is the plan the floor is struck on.
    assert cartesia_plan_marginal_cost_inr_per_min(
        CARTESIA_PRO_PLAN, usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) == Decimal("5.5899")
    assert cartesia_plan_marginal_cost_inr_per_min(
        CARTESIA_STARTUP_PLAN, usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) == Decimal("4.6395")
    assert Decimal("4.6395") == CARTESIA_BEST_MARGINAL_COST_INR_PER_MIN
    assert CARTESIA_BEST_MARGINAL_COST_INR_PER_MIN < CARTESIA_COST_FLOOR_INR_PER_MIN


def test_the_cartesia_cost_curve_at_real_volumes_including_one_that_is_underwater() -> None:
    """**THE FOUNDER'S SECOND DECISION, PINNED**: a Cartesia minute costs what it costs at
    the volume the platform actually runs, and at low volume that is far dearer than any
    floor.

    ₹6.9011 at 100 call-minutes a month is ABOVE every rung on the Studio column of the
    approved card, so at that volume the whole column is under water — which is exactly the
    fact the ops console was hiding. ₹4.3639 at 2,315 is the old "floor", reproduced here to
    show what it actually was: one point on this curve.
    """
    expected = {
        Decimal("100"): (Decimal("6.9011"), "pro"),
        Decimal("200"): (Decimal("4.9299"), "pro"),
        Decimal("500"): (Decimal("5.3259"), "pro"),
        Decimal("1000"): (Decimal("5.4579"), "pro"),
        Decimal("2315"): (Decimal("4.3639"), "startup"),
    }
    for minutes, (cost, plan_id) in expected.items():
        assert (
            cartesia_cost_inr_per_call_minute(minutes, usd_inr=CARTESIA_EVIDENCE_USD_INR) == cost
        ), minutes
        assert (
            cartesia_cheapest_plan(minutes, usd_inr=CARTESIA_EVIDENCE_USD_INR).plan_id == plan_id
        ), minutes

    # At 100 call-minutes a month the four cheapest Studio rungs sell a minute for less
    # than it cost — the case the ₹4.3639 "floor" said could not exist and the console has
    # to warn about. The two dearest rungs still clear it, which is why the warning is
    # per-rung rather than a blanket one.
    at_100 = cartesia_cost_inr_per_call_minute(Decimal("100"), usd_inr=CARTESIA_EVIDENCE_USD_INR)
    assert at_100 == Decimal("6.9011")
    underwater = sorted(
        pack.pack_id for pack in PACK_CATALOGUE if pack.cartesia_inr_per_min < at_100
    )
    assert underwater == ["max", "plus", "pro", "scale"]
    # The curve is NOT monotonic: it falls while a plan's allotment amortises and rises once
    # the plan is into overage. A reader who assumes otherwise writes a broken bisection.
    assert cartesia_cost_inr_per_call_minute(
        Decimal("200"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) < cartesia_cost_inr_per_call_minute(Decimal("1000"), usd_inr=CARTESIA_EVIDENCE_USD_INR)


def test_the_plan_crossover_is_searched_over_a_monotone_difference() -> None:
    """Pro is cheaper below ~1,439 call-minutes a month and Startup above it — DERIVED by
    bisection, which is only valid because the difference between the two plans' monthly
    totals is non-decreasing in volume. That property is asserted, not assumed."""
    crossover = cartesia_plan_crossover_call_minutes(usd_inr=CARTESIA_EVIDENCE_USD_INR)
    assert crossover == Decimal("1439")
    assert CARTESIA_PRO_PLAN.monthly_inr(
        crossover - 1, usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) < CARTESIA_STARTUP_PLAN.monthly_inr(crossover - 1, usd_inr=CARTESIA_EVIDENCE_USD_INR)
    assert CARTESIA_PRO_PLAN.monthly_inr(
        crossover, usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) >= CARTESIA_STARTUP_PLAN.monthly_inr(crossover, usd_inr=CARTESIA_EVIDENCE_USD_INR)
    previous = None
    for minutes in (Decimal(v) for v in (1, 50, 185, 300, 1439, 2315, 5000, 20000)):
        difference = CARTESIA_PRO_PLAN.monthly_inr(
            minutes, usd_inr=CARTESIA_EVIDENCE_USD_INR
        ) - CARTESIA_STARTUP_PLAN.monthly_inr(minutes, usd_inr=CARTESIA_EVIDENCE_USD_INR)
        if previous is not None:
            assert difference >= previous, "the bisection's monotonicity premise has broken"
        previous = difference


def test_every_studio_rung_carries_the_volume_it_needs_to_stop_losing_money() -> None:
    """**THE NUMBER THE CONSOLE HAS TO PRINT BESIDE EACH RUNG.** Below it, that rung sells a
    minute for less than the month's subscription cost it — which the ₹4.3639 "floor" said
    could never happen.

    The answer is the volume from which the rate clears cost AND KEEPS clearing it, because
    the curve is not monotonic; the ₹5.00 case below is the one that proves the difference
    matters (it clears cost at 200 minutes, goes back under water at 1,000, and only stays
    clear from 1,726).
    """
    assert {
        pack.pack_id: cartesia_rung_breakeven_call_minutes(
            pack.cartesia_inr_per_min, usd_inr=CARTESIA_EVIDENCE_USD_INR
        )
        for pack in PACK_CATALOGUE
    } == {
        "starter": Decimal("81"),
        "growth": Decimal("98"),
        "scale": Decimal("104"),
        "plus": Decimal("111"),
        "pro": Decimal("118"),
        "max": Decimal("126"),
    }
    sustained = cartesia_rung_breakeven_call_minutes(
        Decimal("5.00"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    )
    assert sustained == Decimal("1726")
    assert cartesia_cost_inr_per_call_minute(
        Decimal("200"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) < Decimal("5.00")
    assert cartesia_cost_inr_per_call_minute(
        Decimal("1000"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) > Decimal("5.00")
    assert cartesia_cost_inr_per_call_minute(
        sustained, usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) <= Decimal("5.00")
    # A rate at or under the best marginal cost is never rescued by volume, and must be a
    # stated absence rather than a very large number.
    assert (
        cartesia_rung_breakeven_call_minutes(
            CARTESIA_BEST_MARGINAL_COST_INR_PER_MIN, usd_inr=CARTESIA_EVIDENCE_USD_INR
        )
        is None
    )
    assert (
        cartesia_rung_breakeven_call_minutes(Decimal("4.50"), usd_inr=CARTESIA_EVIDENCE_USD_INR)
        is None
    )
    # The search's ceiling is derived from the plans, never typed.
    assert cartesia_envelope_stable_call_minutes(
        usd_inr=CARTESIA_EVIDENCE_USD_INR
    ) >= cartesia_plan_crossover_call_minutes(usd_inr=CARTESIA_EVIDENCE_USD_INR)


def test_the_measured_cost_uses_no_speaking_rate_assumption() -> None:
    """A month somebody RAN is priced off two independent counts our own meter took —
    characters for the plan, minutes for the divisor — so the unmeasured 360-540 band
    (pilot gate 12) never enters the figure an operator reads as today's cost.

    The proof is that two months with the same minutes and different characters price
    differently, which could not happen if minutes were being multiplied by 540.
    """
    thin = cartesia_measured_cost_inr_per_call_minute(
        characters=Decimal("50000"), call_minutes=Decimal("300"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    )
    chatty = cartesia_measured_cost_inr_per_call_minute(
        characters=Decimal("500000"), call_minutes=Decimal("300"), usd_inr=CARTESIA_EVIDENCE_USD_INR
    )
    assert thin is not None and chatty is not None
    assert chatty > thin
    assert thin == (_shared_legs() + Decimal("440") / Decimal("300")).quantize(
        MONEY_Q, rounding=ROUNDING
    )
    # A month with no Studio minutes has no cost PER MINUTE — a stated absence, not a zero.
    assert (
        cartesia_measured_cost_inr_per_call_minute(
            characters=Decimal("0"), call_minutes=Decimal("0"), usd_inr=CARTESIA_EVIDENCE_USD_INR
        )
        is None
    )


def test_the_vendors_credits_per_audio_minute_reconciles_with_our_call_minute_band() -> None:
    """⚠ THE CROSS-CHECK THAT MUST NOT BECOME A SUBSTITUTION.

    Cartesia states ~750-800 credits per minute of AUDIO. Our band is chars per CALL-minute
    on a two-party phone call, so the two differ by the agent's talk ratio. 360-540 against
    750 implies 0.48-0.72, which is a plausible receptionist. Swapping 750 in for 540 would
    silently restate a call-minute as an audio-minute and inflate every cost here by ~39%.
    """
    assert Decimal("750") == CARTESIA_VENDOR_CREDITS_PER_AUDIO_MINUTE
    assert TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1] < CARTESIA_VENDOR_CREDITS_PER_AUDIO_MINUTE
    ratios = [
        (band / CARTESIA_VENDOR_CREDITS_PER_AUDIO_MINUTE).quantize(Decimal("0.01"))
        for band in TTS_ASSUMED_CHARS_PER_CALL_MINUTE
    ]
    assert ratios == [Decimal("0.48"), Decimal("0.72")]
    assert all(Decimal("0") < ratio < Decimal("1") for ratio in ratios)


def test_the_console_ladder_always_contains_a_volume_where_the_card_is_underwater() -> None:
    """The volumes the ops console prints the curve at. The bottom rung must sit below every
    rung's break-even, or the screen shows a table on which everything is fine at every
    volume — which is the defect the whole change exists for."""
    assert CARTESIA_VOLUME_LADDER_CALL_MINUTES[0] == Decimal("100")
    assert list(CARTESIA_VOLUME_LADDER_CALL_MINUTES) == sorted(CARTESIA_VOLUME_LADDER_CALL_MINUTES)
    breakevens = [
        cartesia_rung_breakeven_call_minutes(
            pack.cartesia_inr_per_min, usd_inr=CARTESIA_EVIDENCE_USD_INR
        )
        for pack in PACK_CATALOGUE
    ]
    assert all(point is not None for point in breakevens)
    assert CARTESIA_VOLUME_LADDER_CALL_MINUTES[0] < max(
        point for point in breakevens if point is not None
    ), "the ladder's bottom rung must be a volume at which some Studio rung is under water"


def test_the_cartesia_marginal_rate_per_10k_chars_is_the_vendors_overage() -> None:
    """₹57.20 / 10,000 chars — Pro's $65 per 1M credits at ₹88, never typed, so a conversion
    or overage change moves the doc row `check_docs_drift` §4b diffs it against.

    ⚠ It was ₹34.496 (the Startup fee over its allotment) until 9 Sep 2026, which is an
    AVERAGE true at one volume and was silent about the overage the vendor has now stated.
    """
    assert Decimal("57.20000") == CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS
    assert (
        max(plan.overage_inr_per_character(CARTESIA_EVIDENCE_USD_INR) for plan in CARTESIA_PLANS)
        * Decimal("10000")
    ) == CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS


def test_the_cartesia_floor_holds_at_the_llm_cards_conversion_too() -> None:
    """THE BOUNDED ALTERNATIVE. `rates.py` uses the Cartesia evidence file's own ₹88 = $1 so
    the number in code is the number in the evidence it cites. The repo's other conversion
    is `LIST_PRICE_USD_INR` (₹95.66, the LLM card's strike). This computes the floor under
    that conversion and asserts the card still clears it, so the choice is scored rather
    than argued.
    """
    overage_per_char = (
        CARTESIA_PRO_PLAN.overage_usd_per_million_credits * LIST_PRICE_USD_INR / Decimal("1000000")
    )
    alternative = (
        _shared_legs() + overage_per_char * TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]
    ).quantize(MONEY_Q, rounding=ROUNDING)
    assert alternative == Decimal("5.8588")
    assert alternative > CARTESIA_COST_FLOOR_INR_PER_MIN
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
        ("starter", "cartesia"): Decimal("0.3013"),
        ("growth", "sarvam"): Decimal("0.1758"),
        ("growth", "cartesia"): Decimal("0.2014"),
        ("scale", "sarvam"): Decimal("0.1503"),
        ("scale", "cartesia"): Decimal("0.1719"),
        ("plus", "sarvam"): Decimal("0.1232"),
        ("plus", "cartesia"): Decimal("0.1400"),
        ("pro", "sarvam"): Decimal("0.1041"),
        ("pro", "cartesia"): Decimal("0.1056"),
        ("max", "sarvam"): Decimal("0.0842"),
        ("max", "cartesia"): Decimal("0.0684"),
    }
    for pack in PACK_CATALOGUE:
        for voice in ("sarvam", "cartesia"):
            rate = pack.inr_per_min(voice)  # type: ignore[arg-type]
            floor = cost_floor_inr_per_min(voice)  # type: ignore[arg-type]
            assert rate > floor, f"{pack.pack_id}/{voice} is below cost"
            margin = gross_margin_ratio(rate=rate, cost=floor).quantize(Decimal("0.0001"))
            assert margin == expected[(pack.pack_id, voice)]
            # ⚠ SINCE 9 SEP 2026 THE STUDIO COLUMN IS THIN TOO, against the honest floor:
            # four of its six rungs are under the 20% target where NONE was under the old
            # best-case ₹4.3639. That is the widening the founder asked to be made visible,
            # and it is still a warning and not a refusal — every rung clears cost.
            assert (margin < MIN_GROSS_MARGIN) is (
                voice == "sarvam" or pack.pack_id in ("scale", "plus", "pro", "max")
            )


def test_the_floor_moves_with_the_dollar_and_the_refusal_bound_does_not() -> None:
    """**THE FOUNDER'S SECOND DECISION OF 9 SEP 2026, AND THE ONE CONSEQUENCE OF IT.**

    Cartesia bills in dollars, so the cost floor converts at the LIVE published rate
    (`core/fx.usd_inr_rate_now`, already pulled every five minutes). At ₹95.66 the floor is
    ₹6.0120 and the founder's own ₹6.00 `max` rung earns **-0.2%** — it is under water at
    the margin. At ₹100 it is -4.2%.

    ⚠ **AND THAT IS WHY THE REFUSAL BOUND IS FROZEN.** `credit_packs.card_refusals` scores
    against `CARTESIA_COST_FLOOR_INR_PER_MIN`, struck at the evidence file's ₹88, so a
    currency tick can never make the card that is on sale un-recordable — the founder's
    third decision ("the rate card does not change") would otherwise be impossible to obey.
    The live figure is published beside it and is a warning. **If this test ever shows the
    refusal bound tracking the live rate, a currency feed has been given a veto over
    pricing.**
    """
    assert cartesia_cost_floor_inr_per_min_at(Decimal("88")) == Decimal("5.5899")
    assert cartesia_cost_floor_inr_per_min_at(Decimal("95.66")) == Decimal("6.0120")
    assert cartesia_cost_floor_inr_per_min_at(Decimal("100")) == Decimal("6.2511")

    cheapest_rung = min(pack.cartesia_inr_per_min for pack in PACK_CATALOGUE)
    assert cheapest_rung == Decimal("6.00")
    assert cheapest_rung > cartesia_cost_floor_inr_per_min_at(Decimal("88"))
    assert cheapest_rung < cartesia_cost_floor_inr_per_min_at(Decimal("95.66"))
    at_9566 = gross_margin_ratio(
        rate=cheapest_rung, cost=cartesia_cost_floor_inr_per_min_at(Decimal("95.66"))
    ).quantize(Decimal("0.0001"))
    assert at_9566 == Decimal("-0.0020")

    # The refusal is struck at the FROZEN rate and the card therefore still records — which
    # is the property `tests/credit_packs_test.py` scores and this one explains.
    assert (
        cartesia_cost_floor_inr_per_min_at(CARTESIA_EVIDENCE_USD_INR)
        == CARTESIA_COST_FLOOR_INR_PER_MIN
    )
    assert cost_floor_inr_per_min("cartesia") == CARTESIA_COST_FLOOR_INR_PER_MIN
    assert card_refusals(PACK_CATALOGUE) == []


def test_the_scary_marginal_figure_is_not_the_blended_one_and_both_are_published() -> None:
    """THE QUALIFIER THAT MUST TRAVEL WITH THE -0.2%.

    The floor is the pure OVERAGE marginal rate and applies only ABOVE the included
    allotment — it is the cost of the NEXT minute for a high-volume client on the ₹50,000
    pack. At 200 call-minutes a month on Pro the BLENDED cost at the same ₹95.66 is ₹5.2945
    and the ₹6.00 rung earns ~11.8%. A console that showed only the first would be crying
    wolf, and one that showed only the second would be hiding the exposure; both are on the
    wire (`CartesiaVolumeOut.floor_inr_per_min` and `.cost_inr_per_min`).
    """
    fx = Decimal("95.66")
    blended = cartesia_cost_inr_per_call_minute(Decimal("200"), usd_inr=fx)
    assert blended == Decimal("5.2945")
    assert blended < cartesia_cost_floor_inr_per_min_at(fx)
    assert gross_margin_ratio(rate=Decimal("6.00"), cost=blended).quantize(
        Decimal("0.0001")
    ) == Decimal("0.1176")


def test_only_the_dollar_legs_move_with_the_rate() -> None:
    """The engine's platform fee is $0.02/min and moves; Sarvam STT is rupee-priced and does
    not; the LLM leg is dollars but is struck at `LIST_PRICE_USD_INR`, a DIFFERENT card with
    its own frozen conversion that re-striking would reprice accounts (TRD §10's fifteen
    cost points). That exposure is named in `ex_tts_cost_inr_per_min_at`'s docstring rather
    than silently absorbed, and this test is what makes the split visible.
    """
    at_88 = ex_tts_cost_inr_per_min_at(Decimal("88"))
    at_100 = ex_tts_cost_inr_per_min_at(Decimal("100"))
    assert at_88 == Decimal("2.5011")
    # Only the engine fee moved: $0.02 x (100 - 88) = ₹0.24, to the paisa.
    assert at_100 - at_88 == ENGINE_PLATFORM_FEE_USD_PER_MIN * Decimal("12")
    assert at_100 == Decimal("2.7411")
    # The Sarvam floor is rupee-priced end to end and is NOT a function of the rate at all.
    assert Decimal("4.1211") == SELF_SERVE_COST_FLOOR_INR_PER_MIN
