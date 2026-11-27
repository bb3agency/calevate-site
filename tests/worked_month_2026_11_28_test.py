"""The all-in worked month on the rate card (W9.1) and minutes per pack (W9.2).

Every expected figure is computed here from `PACK_CATALOGUE` and the inputs passed in,
never typed, so a change to the card moves the expectation with it.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal

from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack, pack_talk_time_minutes
from apps.api.billing.payment_routes import (
    REGISTERED_BUYER_GST_NOTE,
    WORKED_MONTH_MINUTES,
    WORKED_MONTH_NUMBERS,
    worked_month_out,
)
from apps.api.billing.rates import VOICE_TIERS, VoiceTier
from apps.api.billing.service import to_paise
from apps.api.main import app
from httpx import ASGITransport, AsyncClient


def _covering(voice: VoiceTier) -> CreditPack:
    by_size = sorted(PACK_CATALOGUE, key=lambda pack: pack.total_credits)
    return next(
        (p for p in by_size if pack_talk_time_minutes(p, voice=voice) >= WORKED_MONTH_MINUTES),
        by_size[-1],
    )


def test_a_month_is_talk_plus_one_number_plus_the_fee_to_the_paisa() -> None:
    number = Decimal("399.00")
    fee = Decimal("250.00")
    month = worked_month_out(
        PACK_CATALOGUE, offered=VOICE_TIERS, number_inr=number, platform_fee_inr=fee
    )
    assert month is not None
    assert month.minutes == WORKED_MONTH_MINUTES
    assert month.registered_buyer_note == REGISTERED_BUYER_GST_NOTE
    assert [row.voice for row in month.voices] == list(VOICE_TIERS)
    for row in month.voices:
        pack = _covering(row.voice)
        talk = to_paise(pack.inr_per_min(row.voice) * WORKED_MONTH_MINUTES)
        total = to_paise(talk + number * WORKED_MONTH_NUMBERS + fee)
        assert row.pack_id == pack.pack_id
        assert row.talk_inr == talk
        assert row.total_inr == total
        assert row.all_in_inr_per_min == to_paise(total / WORKED_MONTH_MINUTES)
        assert row.total_inr.as_tuple().exponent == -2


def test_without_an_attested_number_price_there_is_no_all_in_total() -> None:
    month = worked_month_out(
        PACK_CATALOGUE, offered=VOICE_TIERS, number_inr=None, platform_fee_inr=None
    )
    assert month is not None
    for row in month.voices:
        assert row.talk_inr > 0
        assert row.total_inr is None
        assert row.all_in_inr_per_min is None


def test_a_voice_not_on_offer_is_not_priced_as_a_month() -> None:
    month = worked_month_out(
        PACK_CATALOGUE, offered=("clear",), number_inr=None, platform_fee_inr=None
    )
    assert month is not None
    assert [row.voice for row in month.voices] == ["clear"]
    assert (
        worked_month_out(PACK_CATALOGUE, offered=(), number_inr=None, platform_fee_inr=None) is None
    )


def test_the_month_is_priced_at_the_pack_that_covers_it_not_the_cheapest_rung() -> None:
    small = CreditPack(
        pack_id="small",
        amount_inr=Decimal("1000"),
        clear_inr_per_min=Decimal("5.00"),
        studio_inr_per_min=Decimal("7.00"),
    )
    covers = CreditPack(
        pack_id="covers",
        amount_inr=Decimal("20000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("6.00"),
    )
    big = CreditPack(
        pack_id="big",
        amount_inr=Decimal("90000"),
        clear_inr_per_min=Decimal("3.00"),
        studio_inr_per_min=Decimal("5.00"),
    )
    month = worked_month_out(
        (big, small, covers), offered=("clear",), number_inr=None, platform_fee_inr=None
    )
    assert month is not None
    assert month.voices[0].pack_id == "covers"
    assert month.voices[0].talk_inr == to_paise(Decimal("4.00") * WORKED_MONTH_MINUTES)


async def test_the_public_card_carries_the_month_and_every_pack_states_floored_minutes() -> None:
    address = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(address, 4321)), base_url="http://api"
    ) as http:
        response = await http.get("/v1/public/rate-card")
    assert response.status_code == 200, response.text
    body = response.json()
    month = body["worked_month"]
    assert month["minutes"] == WORKED_MONTH_MINUTES
    for row in month["voices"]:
        # Money is a string on the wire (hard rule 7).
        assert isinstance(row["talk_inr"], str)
        assert isinstance(row["inr_per_min"], str)
    for pack in body["packs"]:
        for voice in VOICE_TIERS:
            rate = Decimal(pack[f"{voice}_inr_per_min"])
            bought = Decimal(pack["total_credits"])
            assert pack[f"{voice}_minutes"] == int(
                (bought / rate).quantize(Decimal(1), rounding=ROUND_DOWN)
            )
