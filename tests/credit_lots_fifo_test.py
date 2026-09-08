"""A debit is drawn from the OLDEST lot first, and splits when one runs out (D-547).

Invariant §2.3.2, which is the whole reason lots exist: two purchases at two prices are
spent in the order they were bought, and each part of one call is priced at ITS lot's rate
for the voice the agent spoke in. The numbers here are chosen to divide exactly, so a
failure is a failure of the FIFO walk and never of rounding.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import lots
from apps.api.billing.service import LotRates
from apps.api.db.session import tenant_session
from tests.credit_lots_helpers import GROWTH, PLUS, add_lot, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]


async def _consume_call(
    tenant_id: UUID, *, minutes: str, tier: lots.VoiceTier = "sarvam", fallback: str = "5.00"
) -> list[lots.LotSplit]:
    async with tenant_session(tenant_id) as session:
        return await lots.consume(
            session,
            tenant_id=tenant_id,
            demand=lots.CallDemand(
                minutes=Decimal(minutes),
                voice_tier=tier,
                fallback_rates=LotRates(Decimal(fallback), Decimal(fallback)),
            ),
        )


async def test_the_oldest_lot_pays_first_and_the_newer_one_is_untouched() -> None:
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)  # 20 Sarvam minutes at ₹5.00
    await add_lot(tenant, credits_inr="470.00", rates=PLUS)  # 100 minutes at ₹4.70

    splits = await _consume_call(tenant, minutes="10")

    assert len(splits) == 1
    only = splits[0]
    assert isinstance(only, lots.CallSplit)
    assert only.credits == Decimal("50.0000")
    assert only.inr_per_min == Decimal("5.0000")
    rows = await lot_rows(tenant)
    assert [row["credits_remaining"] for row in rows] == [Decimal("50.0000"), Decimal("470.0000")]
    assert [row["closed_at"] for row in rows] == [None, None]


async def test_a_debit_splits_across_two_lots_at_two_different_rates() -> None:
    """The founder's sentence, as arithmetic: 20 minutes at ₹5.00 then 10 at ₹4.70."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)
    await add_lot(tenant, credits_inr="470.00", rates=PLUS)

    splits = await _consume_call(tenant, minutes="30")

    assert [split.credits for split in splits] == [Decimal("100.0000"), Decimal("47.0000")]
    assert [split.inr_per_min for split in splits] == [Decimal("5.0000"), Decimal("4.7000")]
    assert [split.minutes for split in splits] == [Decimal("20.0000"), Decimal("10")]
    assert lots.credits_of(splits) == Decimal("147.0000")
    rows = await lot_rows(tenant)
    # The exhausted lot CLOSES; the newer one carries the remainder and stays open.
    assert rows[0]["credits_remaining"] == Decimal("0.0000")
    assert rows[0]["closed_at"] is not None
    assert rows[1]["credits_remaining"] == Decimal("423.0000")
    assert rows[1]["closed_at"] is None


async def test_the_cartesia_rate_prices_a_cartesia_call_out_of_the_same_lot() -> None:
    """Invariant §2.3.2's other half: the tier chooses which of the lot's two rates
    applies, and the lot is the same lot."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="700.00", rates=GROWTH)

    splits = await _consume_call(tenant, minutes="10", tier="cartesia")

    assert splits[0].credits == Decimal("70.0000")
    assert isinstance(splits[0], lots.CallSplit)
    assert splits[0].voice_tier == "cartesia"


async def test_a_dashboard_ai_debit_takes_face_value_with_no_rate_at_all() -> None:
    """Plan §4.B.7: the AI quota buys rupees of assistance, not minutes of talk time."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)
    await add_lot(tenant, credits_inr="100.00", rates=PLUS)

    async with tenant_session(tenant) as session:
        splits = await lots.consume(
            session, tenant_id=tenant, demand=lots.AiAssistDemand(credits=Decimal("150.00"))
        )

    assert [split.credits for split in splits] == [Decimal("100.0000"), Decimal("50.0000")]
    assert all(isinstance(split, lots.AiAssistSplit) for split in splits)
    assert [row["credits_remaining"] for row in await lot_rows(tenant)] == [
        Decimal("0.0000"),
        Decimal("50.0000"),
    ]


async def test_runway_is_summed_lot_by_lot_at_each_lot_s_own_rate() -> None:
    """Plan §0 Q7. One balance divided by one rate would say 121.27 Sarvam minutes; the
    truth is 20 + 100."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)
    await add_lot(tenant, credits_inr="470.00", rates=PLUS)

    async with tenant_session(tenant) as session:
        answer = await lots.runway(session, tenant_id=tenant)

    assert answer["sarvam_minutes"] == Decimal("120.0000")
    # 100/7 + 470/6.50 = 14.2857 + 72.3076, floored at the ledger scale.
    assert answer["cartesia_minutes"] == Decimal("86.5934")


async def test_a_wallet_with_no_lots_has_no_runway_and_reports_zero() -> None:
    tenant = await make_tenant()
    async with tenant_session(tenant) as session:
        assert await lots.runway(session, tenant_id=tenant) == {
            "sarvam_minutes": Decimal("0.0000"),
            "cartesia_minutes": Decimal("0.0000"),
        }
