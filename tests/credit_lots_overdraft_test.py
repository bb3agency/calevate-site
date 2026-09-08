"""What a debit bigger than the wallet costs, and at whose rate (D-547, plan §0 Q5).

The wallet already goes negative on a call — the call has happened, refusing to record it
would hide a real cost — so the only open question is the PRICE of the minutes past the
last credit. Q5's answer is the rate of the lot that ran out, and a wallet with no lots at
all falls back to the rate the caller passes, because a minute that reaches this code
unpriced is a minute nobody can invoice.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing import lots
from apps.api.billing.service import LotRates
from apps.api.db.session import tenant_session
from tests.credit_lots_helpers import GROWTH, PLUS, add_lot, lot_rows, make_tenant

pytestmark = [pytest.mark.rls]


async def test_minutes_past_the_last_lot_are_priced_at_that_lot_s_rate() -> None:
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)  # 20 minutes at ₹5.00
    await add_lot(tenant, credits_inr="47.00", rates=PLUS)  # 10 minutes at ₹4.70

    async with tenant_session(tenant) as session:
        splits = await lots.consume(
            session,
            tenant_id=tenant,
            demand=lots.CallDemand(
                minutes=Decimal("35"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("99.00"), Decimal("99.00")),
            ),
        )

    assert [split.credits for split in splits] == [
        Decimal("100.0000"),
        Decimal("47.0000"),
        Decimal("23.5000"),
    ]
    overdraft = splits[-1]
    assert isinstance(overdraft, lots.CallSplit)
    # The LAST LOT's rate, never the fallback and never the first lot's.
    assert overdraft.inr_per_min == Decimal("4.7000")
    assert overdraft.minutes == Decimal("5.0000")
    assert overdraft.lot_id is None
    assert all(row["closed_at"] is not None for row in await lot_rows(tenant))


async def test_a_wallet_with_no_lots_at_all_is_priced_at_the_caller_s_fallback() -> None:
    """A wallet already in overdraft has nothing to read a rate off, so the caller's rate
    is the only answer that exists. It is a required argument for exactly this case."""
    tenant = await make_tenant()

    async with tenant_session(tenant) as session:
        splits = await lots.consume(
            session,
            tenant_id=tenant,
            demand=lots.CallDemand(
                minutes=Decimal("4"),
                voice_tier="cartesia",
                fallback_rates=LotRates(Decimal("8.00"), Decimal("8.00")),
            ),
        )

    assert len(splits) == 1
    only = splits[0]
    assert isinstance(only, lots.CallSplit)
    assert only.lot_id is None
    assert only.credits == Decimal("32.0000")
    assert only.inr_per_min == Decimal("8.0000")
    assert only.voice_tier == "cartesia"


async def test_a_dashboard_ai_debit_overdraws_at_face_value_and_names_no_lot() -> None:
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="20.00", rates=GROWTH)

    async with tenant_session(tenant) as session:
        splits = await lots.consume(
            session, tenant_id=tenant, demand=lots.AiAssistDemand(credits=Decimal("50.00"))
        )

    assert [split.credits for split in splits] == [Decimal("20.0000"), Decimal("30.0000")]
    assert splits[-1].lot_id is None
    assert lots.credits_of(splits) == Decimal("50.0000")


async def test_a_call_that_exactly_empties_the_last_lot_takes_no_overdraft() -> None:
    """The boundary between "covered" and "overdrawn" is exact, not approximate: 20
    minutes at ₹5.00 is ₹100.00 and the wallet owes nothing more."""
    tenant = await make_tenant()
    await add_lot(tenant, credits_inr="100.00", rates=GROWTH)

    async with tenant_session(tenant) as session:
        splits = await lots.consume(
            session,
            tenant_id=tenant,
            demand=lots.CallDemand(
                minutes=Decimal("20"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("5.00")),
            ),
        )

    assert len(splits) == 1
    assert splits[0].credits == Decimal("100.0000")
    rows = await lot_rows(tenant)
    assert rows[0]["credits_remaining"] == Decimal("0.0000")
    assert rows[0]["closed_at"] is not None
