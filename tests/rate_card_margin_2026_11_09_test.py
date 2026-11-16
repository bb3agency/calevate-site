"""The ops rate card's cost, margin and break-even columns on the engine production runs.

Founder, 9 Nov 2026: "these calculations still seem to be wrong". On ThinnestAI the card's
"next minute" column was struck at ThinnestAI's minute, but the "cost this month" and
"break-even" columns were struck at the base engine's legs (a $0.01/min platform fee, Sarvam
speech-to-text and gpt-4o-mini, plus Sarvam's per-character voice for Clear), at the assumed
540 characters a minute and with no gateway fee, and the month's plan fee was spread over a
month that was a third over. Every expected figure below is worked by hand in the comment
beside it, from these inputs:

* ThinnestAI own-voice minute ₹1.50 (our model off), Clear on the ₹2.50 Studio band;
* wallet top-up fee 2.36%, payment gateway fee 2.36% of the sale;
* ₹95 to the dollar; 600 agent characters a call-minute;
* Cartesia Pro $5 a month for 100,000 characters, then $65 per million (₹0.006175 a
  character); Startup $49 for 1,250,000, then $45 per million (₹0.004275).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing import credit_packs
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.rates import (
    FloorInputs,
    SpeakingRateBasis,
    clear_cost_floor_at,
    studio_breakeven_call_minutes,
    studio_cost_inr_per_min_at_volume,
    studio_minute_inr_per_min,
)
from apps.api.billing.tts_volume import CartesiaVolume
from apps.api.core.fx import UsdInrRate
from apps.api.ops import config_routes

#: 00:00 IST on 10 Nov 2026: nine of November's thirty days are over.
_NINE_DAYS_IN = datetime(2026, 11, 9, 18, 30, tzinfo=UTC)
_FX = UsdInrRate(rate=Decimal("95"), source="test", as_of=None, basis="published")


def _inputs() -> FloorInputs:
    return FloorInputs(
        speaking_rate=SpeakingRateBasis(
            chars_per_call_minute=Decimal("600"),
            measured=True,
            calls=40,
            minimum_calls=20,
            window="2026-10..2026-11",
        ),
        usd_inr=Decimal("95"),
        usd_inr_source="test",
        wallet_fee=Decimal("0.0236"),
        gateway_fee=Decimal("0.0236"),
    )


@pytest.fixture
def _on_thinnest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credit_packs, "deployment_engine", lambda: "thinnest")


def _studio_month(
    minutes: str = "24", characters: str = "14400", attested: str | None = None
) -> config_routes._StudioMonth:
    return config_routes._studio_month(
        CartesiaVolume(
            month="2026-11", characters=Decimal(characters), call_minutes=Decimal(minutes)
        ),
        now=_NINE_DAYS_IN,
        engine="thinnest",
        inputs=_inputs(),
        own_model_prompt_tokens=None,
        attested_bill_inr=None if attested is None else Decimal(attested),
    )


def _cells(studio: config_routes._StudioMonth) -> dict[str, config_routes.RateCardCellOut]:
    cells = config_routes._cells_out(
        PACK_CATALOGUE,
        studio=studio,
        clear=clear_cost_floor_at(_inputs().speaking_rate),
        own_model_prompt_tokens=None,
        inputs=_inputs(),
    )
    starter = [cell for cell in cells if cell.pack_id == "starter"]
    return {cell.voice_tier: cell for cell in starter}


def test_the_studio_minute_on_thinnest_is_their_minute_with_the_wallet_fee() -> None:
    # ₹1.50 x 1.0236 = ₹1.5354. Not the base engine's ₹1.6911 of Bolna-era legs.
    assert studio_minute_inr_per_min(engine="thinnest", inputs=_inputs()) == Decimal("1.53540")


def test_the_month_in_progress_is_projected_to_a_whole_month() -> None:
    studio = _studio_month()
    # 24 minutes in 9 of 30 days -> 80 minutes; 14,400 characters -> 48,000.
    assert studio.projected_call_minutes == Decimal("80")
    assert studio.projected_characters == Decimal("48000")


def test_the_first_hours_of_a_month_project_from_one_day() -> None:
    pace = config_routes._month_pace(datetime(2026, 10, 31, 20, 30, tzinfo=UTC))  # 02:00 IST
    assert pace.elapsed_days == Decimal("1")
    assert pace.month_days == 30


@pytest.mark.usefixtures("_on_thinnest")
def test_the_next_minute_and_the_margin_on_it() -> None:
    cells = _cells(_studio_month())
    # Clear: ₹2.50 x 1.0236 + ₹4.50 x 0.0236 = ₹2.5590 + ₹0.1062 = ₹2.6652;
    # (4.50 - 2.6652) / 4.50 = 40.77%.
    assert cells["clear"].cost_floor_inr_per_min == "2.6652"
    assert cells["clear"].gross_margin_pct == "40.77"
    # Studio: ₹1.5354 + ₹0.006175 x 600 + ₹6.00 x 0.0236 = ₹1.5354 + ₹3.7050 + ₹0.1416
    # = ₹5.3820; (6.00 - 5.3820) / 6.00 = 10.30%.
    assert cells["studio"].cost_floor_inr_per_min == "5.3820"
    assert cells["studio"].gross_margin_pct == "10.30"
    assert cells["studio"].below_target is True


@pytest.mark.usefixtures("_on_thinnest")
def test_clear_has_no_monthly_fee_so_its_average_minute_is_its_next_minute() -> None:
    clear = _cells(_studio_month())["clear"]
    assert clear.cost_inr_per_min_at_volume == clear.cost_floor_inr_per_min == "2.6652"
    assert clear.gross_margin_pct_at_volume == "40.77"
    assert clear.breakeven_call_minutes is None


@pytest.mark.usefixtures("_on_thinnest")
def test_studio_at_this_months_pace_spreads_the_plan_fee_over_the_projected_month() -> None:
    studio = _cells(_studio_month())["studio"]
    # ₹1.5354 + ₹0.1416 + Pro's ₹475 over 80 projected minutes (48,000 characters, inside
    # the allotment) = ₹1.6770 + ₹5.9375 = ₹7.6145; (6.00 - 7.6145) / 6.00 = -26.91%.
    # Spread over the 24 minutes so far it would have read ₹21.4687 (-257.81%).
    assert studio.cost_inr_per_min_at_volume == "7.6145"
    assert studio.gross_margin_pct_at_volume == "-26.91"
    assert studio.below_floor_at_volume is True


@pytest.mark.usefixtures("_on_thinnest")
def test_the_operators_recorded_invoice_replaces_the_list_price() -> None:
    studio = _cells(_studio_month(attested="520.00"))["studio"]
    # ₹1.6770 + ₹520 / 80 = ₹1.6770 + ₹6.5000.
    assert studio.cost_inr_per_min_at_volume == "8.1770"


@pytest.mark.usefixtures("_on_thinnest")
def test_the_break_even_is_the_plan_fee_over_what_each_minute_leaves() -> None:
    studio = _cells(_studio_month())["studio"]
    # ₹475 / (₹6.00 - ₹1.6770) = 109.88, so 110 minutes a month. Past Pro's 100,000
    # characters (166.7 minutes) each minute costs ₹1.6770 + ₹3.7050 = ₹5.3820 < ₹6.00, and
    # Startup never costs more than Pro once it is the cheaper plan, so 110 holds for good.
    assert studio.breakeven_call_minutes == "110"
    assert studio_breakeven_call_minutes(
        Decimal("6.00"),
        minute_inr=Decimal("1.6770"),
        chars_per_call_minute=Decimal("600"),
        usd_inr=Decimal("95"),
    ) == Decimal("110")


def test_a_rate_that_no_volume_rescues_has_no_break_even() -> None:
    # The cheapest a minute can ever be: ₹1.6770 + Startup's ₹0.004275 x 600 = ₹4.2420.
    assert (
        studio_breakeven_call_minutes(
            Decimal("4.2420"),
            minute_inr=Decimal("1.6770"),
            chars_per_call_minute=Decimal("600"),
            usd_inr=Decimal("95"),
        )
        is None
    )


def test_a_month_with_no_minutes_has_no_average_minute() -> None:
    assert (
        studio_cost_inr_per_min_at_volume(
            call_minutes=Decimal("0"),
            characters=Decimal("0"),
            minute_inr=Decimal("1.6770"),
            usd_inr=Decimal("95"),
        )
        is None
    )


def test_the_volume_block_is_struck_on_the_same_engine_as_the_cells() -> None:
    volume = CartesiaVolume(
        month="2026-11", characters=Decimal("14400"), call_minutes=Decimal("24")
    )
    out = config_routes._cartesia_volume_out(volume, fx=_FX, studio=_studio_month())
    assert out.month_days_elapsed == "9.00"
    assert out.month_days == 30
    assert out.projected_call_minutes == "80"
    assert out.plan_bill_inr == "475.0000"
    assert out.plan_bill_attested is False
    assert out.plan_id == "pro"
    # Before the gateway fee: ₹1.5354 + ₹5.9375.
    assert out.cost_inr_per_min == "7.4729"
    # ₹1.5354 + ₹3.7050 once Pro's characters are used; ₹1.5354 + ₹2.5650 on Startup.
    assert out.floor_inr_per_min == "5.2404"
    assert out.best_marginal_cost_inr_per_min == "4.1004"
    # On ThinnestAI the write path refuses below the live floor itself (D-840).
    assert out.refusal_floor_inr_per_min == "5.2404"
    assert out.refusal_floor_frozen is False
    assert out.modelled_chars_per_call_minute == "600"
    # 100 minutes on Pro: ₹1.5354 + (₹475 + 0 overage on 60,000 characters) / 100.
    assert out.ladder[0].call_minutes == "100"
    assert out.ladder[0].cost_inr_per_min == "6.2854"


def test_a_ladder_row_refuses_a_volume_that_is_not_positive() -> None:
    with pytest.raises(ValueError, match="a ladder volume must be positive"):
        _studio_month().at_volume(Decimal(0))


def test_a_thinnest_studio_minute_is_struck_only_at_its_inputs() -> None:
    from apps.api.billing import rates

    with pytest.raises(ValueError, match="none were passed"):
        rates.studio_minute_inr_per_min(engine="thinnest", inputs=None)


def test_a_breakeven_refuses_a_speaking_rate_that_is_not_positive() -> None:
    from apps.api.billing import rates

    with pytest.raises(ValueError, match="a speaking rate must be positive"):
        rates.studio_breakeven_call_minutes(
            Decimal("6"),
            minute_inr=Decimal("1.5"),
            chars_per_call_minute=Decimal(0),
            usd_inr=Decimal("95"),
        )
