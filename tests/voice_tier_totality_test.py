"""Every per-tier money accessor is TOTAL, and an unknown rung RAISES.

WHY THIS FILE EXISTS. `billing/lots.OpenLot.rate_for` and `service.LotRates.rate_for` were
written as `if tier == VALUE: clear` followed by an unconditional `return studio`. That is
not a lookup, it is a lookup plus a silent default — and the default was the DEARER rung.
Any token that was not exactly the value rung, a stale spelling or a rung a later build had
renamed, resolved to the premium rate: no exception, no zero, a higher bill written to an
append-only ledger where the remedy is a compensating entry rather than an edit. D-630's
rename produced such a token and made it visible; the hole predates it.

THE PROPERTY, NOT THE INSTANCES. Asserting that those two functions raise would pass while
the next accessor is written the same way, so this drives EVERY per-tier money accessor in
the tree through one parametrised clause and requires each to refuse. A new one that
defaults instead of raising fails here, whichever direction it defaults in.

⚠ **THE DIRECTION IS WHY THIS IS NOT A STYLE POINT.** A default to the CHEAPER rung
undercharges and costs us; a default to the DEARER rung overcharges a client. Both are
wrong, and only one of them is discovered by a client. `voices.voice_tier()` is the one
place a fallback IS correct and it goes to the cheaper rung, for a reason its own docstring
argues: an agent with an id this build does not recognise is not evidence of the dearer
tier. That asymmetry is asserted at the bottom of this file so nobody "fixes" it to match.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from apps.api.agents.voices import voice_tier
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.lots import OpenLot
from apps.api.billing.rates import (
    PREMIUM_VOICE_TIER,
    VALUE_VOICE_TIER,
    VOICE_TIERS,
    cost_floor_inr_per_min,
)
from apps.api.billing.service import LotRates

#: Tokens that are NOT rungs of this build. `sarvam` and `cartesia` are the real hazard:
#: they were the rung names until 19 Sep 2026, so they are exactly what a stale caller, an
#: old row or a half-migrated client sends — and `cartesia` is additionally a live PROVIDER
#: name, which is how the two vocabularies got confused in the first place.
_NOT_TIERS = ("sarvam", "cartesia", "gnani", "premium", "", "CLEAR")


def _open_lot(clear: str, studio: str) -> OpenLot:
    """A lot whose two rates differ enough that a wrong answer cannot look right."""
    now = datetime.now(UTC)
    return OpenLot(
        lot_id=uuid4(),
        tenant_id=uuid4(),
        source="topup",
        pack_id="starter",
        override_of_pack_id=None,
        credits_total=Decimal("1000"),
        credits_remaining=Decimal("1000"),
        clear_inr_per_min=Decimal(clear),
        studio_inr_per_min=Decimal(studio),
        opened_at=now,
        closed_at=None,
    )


@pytest.mark.parametrize("token", _NOT_TIERS)
def test_a_lot_refuses_to_price_a_rung_it_does_not_have(token: str) -> None:
    """THE DEFECT, as it was: `rate_for("sarvam")` answered ₹7.00 on a ₹5.00 Clear lot."""
    lot = _open_lot("5.0000", "7.0000")
    with pytest.raises(ValueError, match="not a voice tier"):
        lot.rate_for(token)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", _NOT_TIERS)
def test_the_fallback_rates_refuse_a_rung_they_do_not_have(token: str) -> None:
    """`LotRates` is what prices a call when the wallet has no open lot, so the same
    default would overcharge exactly the accounts with nothing bought yet."""
    rates = LotRates(clear_inr_per_min=Decimal("5.0000"), studio_inr_per_min=Decimal("8.0000"))
    with pytest.raises(ValueError, match="not a voice tier"):
        rates.rate_for(token)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", _NOT_TIERS)
def test_a_pack_refuses_to_price_a_rung_it_does_not_have(token: str) -> None:
    """The card's accessor has raised since it was written; this holds it to that."""
    for pack in PACK_CATALOGUE:
        with pytest.raises(ValueError, match="not a voice tier"):
            pack.inr_per_min(token)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", _NOT_TIERS)
def test_the_cost_floor_refuses_a_rung_it_does_not_have(token: str) -> None:
    """A floor that defaulted would judge a rate against the wrong rung's cost, which is
    how a card sells a minute below what it costs and the guard still says yes."""
    with pytest.raises(ValueError, match="no cost floor"):
        cost_floor_inr_per_min(token)  # type: ignore[arg-type]


def test_every_real_rung_is_priced_by_every_accessor() -> None:
    """The other half: refusing everything would pass all of the above.

    Both rungs resolve, and to DIFFERENT figures — a total function that returned the same
    number for both would satisfy every refusal clause above and price every call wrong.
    """
    lot = _open_lot("5.0000", "7.0000")
    rates = LotRates(clear_inr_per_min=Decimal("5.0000"), studio_inr_per_min=Decimal("8.0000"))
    assert {lot.rate_for(t) for t in VOICE_TIERS} == {Decimal("5.0000"), Decimal("7.0000")}
    assert {rates.rate_for(t) for t in VOICE_TIERS} == {Decimal("5.0000"), Decimal("8.0000")}
    assert len({cost_floor_inr_per_min(t) for t in VOICE_TIERS}) == len(VOICE_TIERS)
    for pack in PACK_CATALOGUE:
        assert pack.inr_per_min(VALUE_VOICE_TIER) < pack.inr_per_min(PREMIUM_VOICE_TIER)


def test_an_unknown_voice_id_still_falls_to_the_cheaper_rung_and_that_is_deliberate() -> None:
    """THE ONE PLACE A DEFAULT IS CORRECT, asserted so nobody makes it symmetric.

    `voice_tier()` maps an agent's stored voice ID to a rung. An id this build does not
    recognise — a voice retired since, a row written before the catalogue existed — is NOT
    evidence that the agent is on the dearer rung, and raising there would refuse to bill a
    call that really happened. So it answers the VALUE rung: the error direction that costs
    us rather than the client. Every accessor above raises; this one does not, and the
    difference is which way being wrong hurts.
    """
    assert voice_tier(None) == VALUE_VOICE_TIER
    assert voice_tier("bulbul:v3") == VALUE_VOICE_TIER
    assert voice_tier("a-voice-nobody-has-heard-of") == VALUE_VOICE_TIER
    assert voice_tier("sonic-3.5:anything") == PREMIUM_VOICE_TIER
