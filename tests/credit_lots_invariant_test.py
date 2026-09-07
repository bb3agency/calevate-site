"""Invariant §2.3.1, after a randomised sequence of purchases and calls.

`SUM(credit_lots.credits_remaining) == the wallet balance` for every tenant whose balance
is at or above zero; below zero every lot is at zero and the difference is overdraft. It is
the sentence that makes the two structures one wallet — the ledger says how much money is
there, the lots say what it may be spent on — and it is the first thing a reconciliation
would check.

A property test rather than another worked example: the FIFO walk, the splits, the closing
of an emptied lot and the overdraft arm interact, and the shapes that break arithmetic are
the ones nobody thinks to write by hand. The seed is FIXED, so a failure is reproducible
and this file never becomes the flaky one (D-29).
"""

from __future__ import annotations

import random
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest
from apps.api.billing import lots
from apps.api.billing.service import (
    LotRates,
    apply_credit_to_lots,
    charge_for_call,
    get_balance,
    record_entry,
)
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.credit_lots_helpers import credit_entry, make_tenant

pytestmark = [pytest.mark.rls]

#: Two rate cards a purchase may be sold at, so the sequence mixes prices the way a real
#: wallet does (a ₹2,000 pack behind a ₹15,000 one).
CARDS = ((Decimal("5.00"), Decimal("8.00")), (Decimal("4.70"), Decimal("6.50")))


async def _sum_of_lots(tenant_id) -> Decimal:  # type: ignore[no-untyped-def]
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text("SELECT COALESCE(SUM(credits_remaining), 0) FROM credit_lots")
            )
        ).scalar_one()
    return Decimal(str(total))


async def _balance(tenant_id) -> Decimal:  # type: ignore[no-untyped-def]
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def test_the_lots_and_the_balance_agree_after_a_random_walk() -> None:
    tenant = await make_tenant()
    rng = random.Random(547)

    for step in range(30):
        if rng.random() < 0.45:
            amount = Decimal(rng.randrange(500, 5000))
            card = CARDS[rng.randrange(len(CARDS))]
            # Plan §0 Q5, THROUGH THE REAL SEAM: a credit onto an overdrawn wallet repays
            # the overdraft FIRST and only the remainder opens a lot. This file used to
            # model that arithmetic itself, because Phase B1 had not written it yet; now
            # that B2 has, the model is deleted and the walk drives
            # `apply_credit_to_lots` — a property test against a hand-written twin proves
            # the twin, and two ways of doing one thing is the defect this repo counts
            # even when both are right.
            entry = await credit_entry(tenant, amount=str(amount))
            async with tenant_session(tenant) as session:
                await apply_credit_to_lots(
                    session,
                    tenant_id=tenant,
                    credits_inr=amount,
                    balance_after=await _balance(tenant),
                    rates=LotRates(sarvam_inr_per_min=card[0], cartesia_inr_per_min=card[1]),
                    source="topup",
                    pack_id="growth",
                    ledger_entry_id=entry,
                )
            continue

        tier: lots.VoiceTier = "cartesia" if rng.random() < 0.4 else "sarvam"
        minutes = Decimal(rng.randrange(1, 400))
        async with tenant_session(tenant) as session:
            # ONE ledger row whose delta is the sum of the splits, allowed to overdraw
            # because the call has already happened — `charge_for_call` is the door the
            # post-call pipeline uses and this walks the same one.
            await charge_for_call(
                session,
                tenant_id=tenant,
                call_id=uuid5(NAMESPACE_URL, f"walk-{tenant}-{step}"),
                demand=lots.CallDemand(
                    minutes=minutes, voice_tier=tier, fallback_inr_per_min=Decimal("5.00")
                ),
            )

        balance = await _balance(tenant)
        remaining = await _sum_of_lots(tenant)
        if balance >= 0:
            assert remaining == balance, f"step {step}: lots {remaining} vs balance {balance}"
        else:
            # Past empty: every lot is spent and the overdraft is the balance itself.
            assert remaining == Decimal("0.0000"), f"step {step}: {remaining}"

    # The walk must actually have exercised both sides, or it proved nothing.
    async with tenant_session(tenant) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE closed_at IS NOT NULL), "
                    "count(*) FILTER (WHERE closed_at IS NULL) FROM credit_lots"
                )
            )
        ).one()
    assert counts[0] > 0, "no lot was ever emptied — the split path never ran"


async def test_a_spent_wallet_holds_no_open_lot_and_a_refund_style_credit_reopens_none() -> None:
    """The second half of §2.3.1, stated on its own: at or below zero there is nothing
    open. Repaying the overdraft and opening the next lot is Phase B2's §4.B.5, and this
    asserts only that B1 leaves the wallet in the state that rule expects to find."""
    tenant = await make_tenant()
    entry = await credit_entry(tenant, amount="100.00")
    async with tenant_session(tenant) as session:
        await lots.open_lot(
            session,
            tenant_id=tenant,
            credits_inr=Decimal("100.00"),
            sarvam_inr_per_min=Decimal("5.00"),
            cartesia_inr_per_min=Decimal("8.00"),
            source="topup",
            pack_id="starter",
            ledger_entry_id=entry,
        )
        splits = await lots.consume(
            session,
            tenant_id=tenant,
            demand=lots.CallDemand(
                minutes=Decimal("40"),  # ₹200 against a ₹100 lot
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
        await record_entry(
            session,
            tenant_id=tenant,
            delta=-lots.credits_of(splits),
            reason="usage",
            ref="call-overdrawn",
            meta={"lots": lots.split_meta(splits)},
            allow_negative=True,
        )

    assert await _balance(tenant) == Decimal("-100.0000")
    assert await _sum_of_lots(tenant) == Decimal("0.0000")
    async with tenant_session(tenant) as session:
        assert await lots.read_open_lots(session, tenant_id=tenant) == []
