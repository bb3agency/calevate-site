"""Money edges closed in the wiring wave (17 Nov 2026): repeat refunds after the first one
processed, and the PLAUSIBLE ledger edges proved here before they were fixed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import payments
from apps.api.billing.disputes import apply_dispute_event
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from tests.razorpay_payments_e2e_test import (  # noqa: F401 (autouse fixture)
    _configured,
    _dispute,
    _fund,
    _id,
    _tenant,
)

pytestmark = [pytest.mark.rls]


async def _claim(tenant_id: UUID, payment_id: str, amount: str, total: str) -> payments.RefundClaim:
    async with tenant_session(tenant_id) as session:
        entry = await payments.find_topup(session, tenant_id=tenant_id, ref=payment_id)
        assert entry is not None
        return await payments.claim_refund(
            session,
            tenant_id=tenant_id,
            payment_id=payment_id,
            amount_inr=Decimal(amount),
            payment_total_inr=Decimal(total),
            topup_entry_id=entry.entry_id,
        )


async def _processed(tenant_id: UUID, payment_id: str, claim: payments.RefundClaim, amount: str) -> None:
    """The provider answered with a refund id and the refund then processed (webhook)."""
    refund_id = _id("rfnd")
    async with tenant_session(tenant_id) as session:
        await payments.bind_refund_claim(
            session, tenant_id=tenant_id, refund_key=claim.refund_key, refund_id=refund_id
        )
    async with tenant_session(tenant_id) as session:
        await payments.credit_refund(
            session,
            refund=payments.RefundEvent(
                refund_id=refund_id,
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount),
                currency="INR",
            ),
        )


# --- repeat refunds (lead decision 17 Nov 2026) ------------------------------------------


async def test_a_repeat_refund_before_the_first_processed_is_a_replay() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "2500.00")
    first = await _claim(tenant_id, payment_id, "1000.00", "2500.00")
    again = await _claim(tenant_id, payment_id, "1000.00", "2500.00")
    assert first.claimed and not again.claimed
    assert again.refund_key == first.refund_key


async def test_a_repeat_refund_after_the_first_processed_is_a_new_refund() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "2500.00")
    first = await _claim(tenant_id, payment_id, "1000.00", "2500.00")
    await _processed(tenant_id, payment_id, first, "1000.00")

    second = await _claim(tenant_id, payment_id, "1000.00", "2500.00")

    assert second.claimed, "a processed refund is not a live claim to collapse onto"
    assert second.refund_key != first.refund_key, "the provider must see a new refund"
    async with tenant_session(tenant_id) as session:
        claimed = await payments.committed_refund_total_inr(
            session, tenant_id=tenant_id, payment_id=payment_id
        )
    assert claimed == Decimal("2000.00")


async def test_a_new_refund_after_one_processed_is_held_to_the_payment_ceiling() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    first = await _claim(tenant_id, payment_id, "600.00", "1000.00")
    await _processed(tenant_id, payment_id, first, "600.00")

    with pytest.raises(ProblemError) as refused:
        await _claim(tenant_id, payment_id, "600.00", "1000.00")
    assert refused.value.code == "refund_exceeds_payment"


async def test_a_new_refund_after_one_processed_is_refused_while_disputed() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "2500.00")
    first = await _claim(tenant_id, payment_id, "500.00", "2500.00")
    await _processed(tenant_id, payment_id, first, "500.00")
    async with tenant_session(tenant_id) as session:
        await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_dispute(payment_id, "open"),
        )

    with pytest.raises(ProblemError) as refused:
        await _claim(tenant_id, payment_id, "500.00", "2500.00")
    assert refused.value.code == "refund_payment_disputed"
