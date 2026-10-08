"""The ops console's per-minute rate rows say which rate a client is sold (D-681).

The rung comes from `billing/engine_minutes.CLIENT_RUNG_OF_RATE_KEY`, so the panel cannot
disagree with the debit about what is on sale.
"""

from __future__ import annotations

from apps.api.billing.engine_minutes import ENGINE_RATE_KEYS
from apps.api.billing.payment_routes import voice_tier_not_offered
from apps.api.ops.engine_minute_routes import _row


def test_the_studio_band_is_sold_as_clear_and_the_own_voice_minute_as_studio() -> None:
    """D-687: the engine's Studio band is Clear, a voice of our own key is Studio."""
    sold = {key: _row("thinnest", key, None).sold_as for key in ENGINE_RATE_KEYS}
    assert sold == {
        "platform": None,
        "standard": None,
        "premium": None,
        "studio": "Clear",
        "byok_voice": "Studio",
    }


def test_an_unattested_row_is_not_billable_whatever_it_is_sold_as() -> None:
    row = _row("thinnest", "premium", None)
    assert row.billable is False
    assert row.inr_per_min is None


def test_the_rate_card_holds_back_studio_on_thinnest_and_clear_elsewhere() -> None:
    thinnest = voice_tier_not_offered("thinnest")
    pipecat = voice_tier_not_offered("pipecat")
    assert thinnest is not None and thinnest[0] == "studio"
    assert pipecat is not None and pipecat[0] == "clear"
    for _tier, notice in (thinnest, pipecat):
        # The rate card is public and client-facing (D-679): no provider is named.
        for vendor in ("Thinnest", "Gnani", "Cartesia", "Pipecat", "Vobiz", "Sarvam"):
            assert vendor.lower() not in notice.lower()
