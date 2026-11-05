"""The ops console's per-minute rate rows say which rate a client is sold (D-681).

The rung comes from `billing/engine_minutes.CLIENT_RUNG_OF_RATE_KEY`, so the panel cannot
disagree with the debit about what is on sale.
"""

from __future__ import annotations

import pytest
from apps.api.billing import engine_minutes
from apps.api.billing.engine_minutes import CARRIER_RATE_KEY, ENGINE_RATE_KEYS
from apps.api.billing.payment_routes import voice_tier_not_offered
from apps.api.ops.engine_minute_routes import _row


def test_the_band_set_as_clear_is_sold_as_clear_and_the_own_voice_minute_as_studio() -> None:
    """D-688: the band `thinnest_clear_voice_band` names (Studio by default, D-792) is Clear,
    a voice of our own key is Studio, and no other band is sold."""
    sold = {key: _row("thinnest", key, None).sold_as for key in ENGINE_RATE_KEYS}
    assert sold == {
        "platform": None,
        "standard": None,
        "premium": None,
        "studio": "Clear",
        "byok_voice": "Studio",
        # Sold only while our own model is switched on (D-764), off by default.
        "byok_llm_voice": None,
    }


def test_an_unattested_row_is_not_billable_whatever_it_is_sold_as() -> None:
    row = _row("thinnest", "premium", None)
    assert row.billable is False
    assert row.inr_per_min is None


def test_each_row_states_the_step_the_meter_bills_it_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The panel's "billed in N-second steps" comes from the meter's own constants, so a
    changed pulse or carrier block moves the sentence with the debit (G8-3)."""
    monkeypatch.setitem(engine_minutes.PULSE_SECONDS, "thinnest", 60)
    monkeypatch.setitem(engine_minutes.CARRIER_BLOCK_SECONDS, "thinnest", 15)
    assert _row("thinnest", "studio", None).billed_in_seconds == 60
    assert _row("thinnest", CARRIER_RATE_KEY, None).billed_in_seconds == 15


def test_the_rate_card_holds_back_studio_on_thinnest_and_clear_elsewhere() -> None:
    thinnest = voice_tier_not_offered("thinnest", studio_ready=False)
    other = voice_tier_not_offered("fake", studio_ready=False)
    assert thinnest is not None and thinnest[0] == "studio"
    assert other is not None and other[0] == "clear"
    for _tier, notice in (thinnest, other):
        # The rate card is public and client-facing (D-679): no provider is named.
        for vendor in ("Thinnest", "Cartesia", "Sarvam"):
            assert vendor.lower() not in notice.lower()
