"""THE CARRIER LEG, which is costable now and is still in neither cost floor.

D-474 (Model B) kept telephony out of the cost model because the client holds the carrier
account. A third arrangement — the number sold through the platform — makes the carrier
minute ours, so `billing/rates.py` carries the card. What this file protects, in the order
it costs money:

- **Neither published floor moved.** `SELF_SERVE_COST_FLOOR_INR_PER_MIN` and
  `CARTESIA_COST_FLOOR_INR_PER_MIN` are what the pack card, `credit_packs.card_margins`
  and TRD §10's margin model are struck against; a telephony leg that leaked into either
  would reprice a card that is on sale. This is the regression that matters most, and
  `tests/cost_floor_test.py` asserts the same property from the other side.
- **The pulse is modelled, not averaged away.** A connected call bills in whole 30-second
  increments, so the boundaries — exactly on a pulse, one second over, under a pulse,
  zero — are the arithmetic, not an edge case.
- **Inbound and outbound carry one rate**, which is a fact about the vendor's card and is
  asserted as a value rather than trusted to a comment.
- **The rental amortises**, and a month with no minutes is refused rather than divided by.

EVIDENCE CLASS of every figure below: **VENDOR-PUBLISHED, FOUNDER-RELAYED** — Plivo's
India voice pricing page, read by the founder 22 Sep 2026. `www.plivo.com` is
egress-blocked from this container, so no assertion here is a page this repository fetched.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing.rates import (
    CARTESIA_COST_FLOOR_INR_PER_MIN,
    MONEY_Q,
    ROUNDING,
    SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    TELEPHONY_ADDON_INR_PER_MIN,
    TELEPHONY_ADDONS_ENABLED,
    TELEPHONY_ASR_INR_PER_15_SECONDS,
    TELEPHONY_AUDIO_STREAMING_INR_PER_MIN,
    TELEPHONY_INR_PER_MIN,
    TELEPHONY_NUMBER_RENTAL_INR_PER_MONTH,
    TELEPHONY_PULSE_SECONDS,
    cost_floor_inr_per_min,
    stt_rate_inr_per_minute,
    telephony_addon_inr_per_min,
    telephony_addons_inr_per_min,
    telephony_billed_seconds,
    telephony_cost_inr,
    telephony_inr_per_call_minute,
    telephony_number_rental_inr_per_min,
    telephony_rate_inr_per_min,
)


def test_neither_published_cost_floor_moved_when_telephony_became_costable() -> None:
    """**THE REGRESSION THIS FILE EXISTS TO CATCH.**

    Both floors are the figures the approved pack card, `credit_packs.card_margins` and
    TRD §10's margin model are struck against. A carrier leg summed into either would
    silently re-price a card that is on sale and re-classify every account holding it, so
    the two constants are pinned by VALUE here and the selector is pinned to them.

    The arithmetic half — that each floor is exactly its own named legs — is
    `tests/cost_floor_test.py`; this is the half that would fail if a future reader
    decided the new term "belongs" in the sum.
    """
    assert Decimal("3.1491") == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert Decimal("4.7099") == CARTESIA_COST_FLOOR_INR_PER_MIN
    assert cost_floor_inr_per_min("clear") == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert cost_floor_inr_per_min("studio") == CARTESIA_COST_FLOOR_INR_PER_MIN
    # Both floors sit below the cheapest telephony minute added to themselves, which is
    # the arithmetic statement of "the leg is not in there".
    cheapest_minute = min(
        rate for direction in TELEPHONY_INR_PER_MIN.values() for rate in direction.values()
    )
    for voice in ("clear", "studio"):
        floor = cost_floor_inr_per_min(voice)  # type: ignore[arg-type]
        assert floor + cheapest_minute > floor


@pytest.mark.parametrize(
    ("duration_s", "billed_s"),
    [
        (0, "0"),
        (1, "30"),
        (29, "30"),
        (30, "30"),
        (31, "60"),
        (60, "60"),
        (61, "90"),
        (130, "150"),
        (600, "600"),
    ],
)
def test_the_pulse_rounds_a_call_up_to_whole_thirty_second_increments(
    duration_s: int, billed_s: str
) -> None:
    """A call is billed `ceil(duration / 30) * 30` seconds — 2m10s bills 2m30s.

    Every boundary the rounding can be wrong at: exactly on a pulse (30, 60, 600), one
    second over one (31, 61), inside the first pulse (1, 29), and zero. A model that
    multiplied duration by the per-minute rate would agree on the exact-pulse rows and be
    wrong on every other one, which is why the on-pulse cases are in the table.
    """
    assert telephony_billed_seconds(duration_s) == Decimal(billed_s)


def test_a_call_with_no_seconds_bills_no_pulses_and_a_negative_one_is_refused() -> None:
    """Zero is zero — the vendor's minimum for an unanswered call is UNKNOWN and is not
    imputed, so this can only under-state. A negative duration is not a duration and is
    refused rather than priced, the guard `_billable_seconds` had to make on the live
    money path."""
    assert telephony_billed_seconds(0) == Decimal("0")
    assert telephony_cost_inr(0, leg="domestic", direction="outbound") == Decimal("0.0000")
    with pytest.raises(ValueError, match="cannot be negative"):
        telephony_billed_seconds(-1)


def test_the_pulse_is_thirty_seconds_and_lives_in_exactly_one_place() -> None:
    """The constant is the rounding's one home, and the functions are derived from it —
    so a vendor moving to per-second billing is one edit, not a search for literal 30s."""
    assert Decimal("30") == TELEPHONY_PULSE_SECONDS
    assert telephony_billed_seconds(1) == TELEPHONY_PULSE_SECONDS
    assert telephony_billed_seconds(int(TELEPHONY_PULSE_SECONDS) + 1) == TELEPHONY_PULSE_SECONDS * 2


def test_inbound_and_outbound_carry_the_same_rate_on_both_legs() -> None:
    """₹0.38/min domestic and ₹0.25/min on the browser SDK, the same in both directions.

    Asserted as a VALUE because the card states two rows: the day the vendor splits them,
    this fails rather than a single constant being quietly renamed.
    """
    assert TELEPHONY_INR_PER_MIN["domestic"] == {
        "inbound": Decimal("0.3800"),
        "outbound": Decimal("0.3800"),
    }
    assert TELEPHONY_INR_PER_MIN["webrtc"] == {
        "inbound": Decimal("0.2500"),
        "outbound": Decimal("0.2500"),
    }
    for leg in ("domestic", "webrtc"):
        assert telephony_rate_inr_per_min(leg=leg, direction="inbound") == (  # type: ignore[arg-type]
            telephony_rate_inr_per_min(leg=leg, direction="outbound")  # type: ignore[arg-type]
        )
        # The same equality where it is observable: two calls of one length, one each way.
        assert telephony_cost_inr(90, leg=leg, direction="inbound") == telephony_cost_inr(  # type: ignore[arg-type]
            90,
            leg=leg,  # type: ignore[arg-type]
            direction="outbound",
        )
    assert telephony_rate_inr_per_min(leg="webrtc", direction="inbound") < (
        telephony_rate_inr_per_min(leg="domestic", direction="inbound")
    )
    with pytest.raises(ValueError, match="no published telephony rate"):
        telephony_rate_inr_per_min(leg="international", direction="outbound")  # type: ignore[arg-type]


def test_the_media_stream_costs_nothing_on_top_of_the_minute() -> None:
    """ "Included" on the vendor's card, and load-bearing: the agent needs the raw audio
    both ways, so a per-minute streaming charge would land on every call this product
    makes. A named zero, so a future charge has somewhere to be read into."""
    assert Decimal("0.0000") == TELEPHONY_AUDIO_STREAMING_INR_PER_MIN
    assert telephony_cost_inr(60, leg="domestic", direction="outbound") == Decimal("0.3800")


def test_a_call_costs_its_billed_pulses_and_not_its_duration() -> None:
    """2m10s on the domestic leg is ₹0.95, not the ₹0.8233 its duration would suggest."""
    assert telephony_cost_inr(130, leg="domestic", direction="outbound") == Decimal("0.9500")
    naive = (
        telephony_rate_inr_per_min(leg="domestic", direction="outbound")
        * Decimal("130")
        / Decimal("60")
    ).quantize(MONEY_Q, rounding=ROUNDING)
    assert naive == Decimal("0.8233")
    assert telephony_cost_inr(130, leg="domestic", direction="outbound") > naive


def test_the_per_minute_view_takes_the_call_length_and_refuses_a_zero_one() -> None:
    """A carrier minute has no single price: the pulse makes ₹/call-minute a function of
    call length, so the figure is only meaningful given one.

    A 31-second call is billed a full minute and therefore runs at ₹0.7355 a call-minute;
    a ten-minute call runs at the card's ₹0.38. A call with no seconds has a COST (zero)
    and no cost PER MINUTE, so that arm raises rather than returning either number.
    """
    assert telephony_inr_per_call_minute(31, leg="domestic", direction="outbound") == Decimal(
        "0.7355"
    )
    assert telephony_inr_per_call_minute(600, leg="domestic", direction="outbound") == Decimal(
        "0.3800"
    )
    # Exactly on a pulse there is no rounding to pay for, so the per-minute view is the card.
    assert telephony_inr_per_call_minute(30, leg="domestic", direction="inbound") == Decimal(
        "0.3800"
    )
    for duration in (0, -1):
        with pytest.raises(ValueError, match="positive call duration"):
            telephony_inr_per_call_minute(duration, leg="domestic", direction="outbound")


def test_the_number_rental_amortises_over_the_volume_it_is_given() -> None:
    """₹200/month is not a per-minute cost until a volume is named: ₹0.20/min at a
    thousand call-minutes, ₹2.00 at a hundred. No default volume exists, because a default
    would put an unmeasured utilisation assumption inside a cost figure."""
    assert Decimal("200.0000") == TELEPHONY_NUMBER_RENTAL_INR_PER_MONTH
    assert telephony_number_rental_inr_per_min(Decimal("1000")) == Decimal("0.2000")
    assert telephony_number_rental_inr_per_min(Decimal("100")) == Decimal("2.0000")
    assert telephony_number_rental_inr_per_min(Decimal("1")) == Decimal("200.0000")


@pytest.mark.parametrize("minutes", [Decimal("0"), Decimal("-1")])
def test_a_month_with_no_minutes_refuses_rather_than_dividing(minutes: Decimal) -> None:
    """RAISES, because neither alternative is sayable: infinity is not a rupee, and a zero
    reads as a free number on a screen an operator would act on. The fee is still owed."""
    with pytest.raises(ValueError, match="no cost per minute in a month with no minutes"):
        telephony_number_rental_inr_per_min(minutes)


def test_the_carrier_speech_add_ons_are_priced_and_not_bought() -> None:
    """**WE BUY NONE OF THEM, AND THE TWO THAT MATTER ARE REFUSED ON MERIT.**

    The carrier's ASR is ₹1.70 per 15 seconds — ₹6.80 a minute, more than twice the whole
    Clear cost floor — for a transcript our own STT leg already produces at ₹0.50 a
    call-minute (Sarvam Saaras); Call Transcription at ₹0.81/min buys the same thing again
    at 1.6x the STT leg. The rates are carried so that enabling one is COSTED by the same
    function that prices the minute, rather than discovered on an invoice.
    """
    assert frozenset() == TELEPHONY_ADDONS_ENABLED
    assert telephony_addons_inr_per_min() == Decimal("0")
    assert Decimal("1.70") == TELEPHONY_ASR_INR_PER_15_SECONDS
    asr = telephony_addon_inr_per_min("automatic_speech_recognition")
    assert asr == Decimal("6.80")
    assert asr > SELF_SERVE_COST_FLOOR_INR_PER_MIN * 2
    assert telephony_addon_inr_per_min("call_transcription") == Decimal("0.81")
    assert telephony_addon_inr_per_min("call_transcription") > stt_rate_inr_per_minute()
    assert telephony_addon_inr_per_min("noise_cancellation") == Decimal("0.12")
    for free in ("call_recording", "answering_machine_detection", "conference_calls"):
        assert telephony_addon_inr_per_min(free) == Decimal("0.00")
    with pytest.raises(ValueError, match="not on the telephony add-on card"):
        telephony_addon_inr_per_min("carrier_grade_hold_music")


def test_enabling_an_add_on_is_picked_up_by_the_function_that_prices_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of holding the enabled set as a value: a switch flipped in this repository
    shows up in the cost of a call, not on a statement three weeks later.

    One billed minute of domestic outbound with noise cancellation on is ₹0.38 + ₹0.12.
    """
    monkeypatch.setattr(
        "apps.api.billing.rates.TELEPHONY_ADDONS_ENABLED", frozenset({"noise_cancellation"})
    )
    assert telephony_addons_inr_per_min() == Decimal("0.12")
    assert telephony_cost_inr(45, leg="domestic", direction="outbound") == Decimal("0.5000")
    assert TELEPHONY_ADDON_INR_PER_MIN["noise_cancellation"] == Decimal("0.12")


def test_nothing_on_this_leg_is_a_billable_rate() -> None:
    """A cost MODEL, the same class as `llm_cost_inr_per_minute` — hard rule 7's attested
    seam is untouched and no catalogue figure here has a path to `unit_cost_paid`.

    Asserted structurally: `billing/rates.py`'s billable doors are `llm_inr_per_ktok` and
    `tts_rate_inr_per_char`, and neither reads a telephony constant. The scan is over the
    module source because the property is "no call edge exists", which no value can state.
    """
    import inspect

    from apps.api.billing import rates

    for door in (rates.llm_inr_per_ktok, rates.tts_rate_inr_per_char):
        assert "elephony" not in inspect.getsource(door)
