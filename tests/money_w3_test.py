"""Money edges closed in the wiring wave (17 Nov 2026): repeat refunds after the first one
processed, and the PLAUSIBLE ledger edges proved here before they were fixed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import payments
from apps.api.billing.credit_expiry import expire_lot
from apps.api.billing.disputes import apply_dispute_event
from apps.api.billing.service import (
    LOW_BALANCE_JOB,
    get_balance,
    purchase_lot_of_entry,
    record_entry,
    remove_credit_from_lots,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
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


# --- a failed refund someone else made -----------------------------------------------------


async def test_a_failed_dashboard_refund_does_not_release_a_claim_whose_answer_was_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A console refund whose provider answer never reached us is an unbound live claim: it
    may have moved money. A failed refund of the same payment and amount made from the
    provider's dashboard (no notes of ours) is not that refund, so reconciliation must not
    release the claim; releasing it would let the same rupees be refunded again."""
    from apps.api.billing import reconciliation
    from apps.api.billing.razorpay_api import ProviderPayment, ProviderRefundRow
    from tests.razorpay_payments_e2e_test import FakeApi

    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    claim = await _claim(tenant_id, payment_id, "400.00", "1000.00")
    assert claim.claimed
    fake = FakeApi(
        payments=[
            ProviderPayment(
                payment_id=payment_id,
                status="captured",
                amount_paise=100000,
                currency="INR",
                order_id=None,
                method="upi",
                international=False,
                token_id=None,
                customer_id=None,
                notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
                error_code=None,
                created_at=0,
                captured=True,
            )
        ],
        refunds=[
            ProviderRefundRow(
                refund_id=_id("rfnd"),
                payment_id=payment_id,
                amount_paise=40000,
                currency="INR",
                status="failed",
                notes={},
            )
        ],
    )
    monkeypatch.setattr(reconciliation, "razorpay_api", lambda: fake)
    monkeypatch.setattr(reconciliation, "alert", lambda *a, **k: None)

    report = await reconciliation.reconcile()

    assert report.refunds_failed_late == []
    async with tenant_session(tenant_id) as session:
        held = await payments.claimed_refund_total_inr(
            session, tenant_id=tenant_id, payment_id=payment_id
        )
    assert held == Decimal("400.00"), "the console's refund may have moved money"


# --- disputes against a lot ----------------------------------------------------------------


async def _lot_of(tenant_id: UUID, payment_id: str) -> tuple[Decimal, Decimal]:
    """(credits_total, credits_remaining) of the lot a payment opened."""
    async with tenant_session(tenant_id) as session:
        entry = await payments.find_topup(session, tenant_id=tenant_id, ref=payment_id)
        assert entry is not None
        total, remaining = (
            await session.execute(
                text(
                    "SELECT credits_total, credits_remaining FROM credit_lots "
                    "WHERE ledger_entry_id = :e"
                ),
                {"e": entry.entry_id},
            )
        ).one()
    return Decimal(str(total)), Decimal(str(remaining))


async def _dispute_event(tenant_id: UUID, payment_id: str, status: str, amount: int) -> str:
    event = {"open": "payment.dispute.created", "won": "payment.dispute.won"}[status]
    async with tenant_session(tenant_id) as session:
        return await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event=event,
            dispute=_dispute(payment_id, status, amount=amount),
        )


async def test_a_won_dispute_gives_credit_back_to_the_lots_it_was_taken_from() -> None:
    """A hold met partly from a later purchase's lot (the disputed purchase was part spent)
    must give that part back to that lot on release, at that lot's rates, and leave the
    disputed purchase's lot at what it was sold as."""
    tenant_id = await _tenant()
    first, second = _id("pay"), _id("pay")
    await _fund(tenant_id, first, "1000.00")
    await _fund(tenant_id, second, "1000.00")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("-700"), reason="usage", ref=_id("call")
        )
        await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=None, amount_inr=Decimal("700")
        )
    assert await _lot_of(tenant_id, first) == (Decimal("1000.0000"), Decimal("300.0000"))

    assert await _dispute_event(tenant_id, first, "open", 100000) == "held"
    assert await _dispute_event(tenant_id, first, "won", 100000) == "released"

    assert await _lot_of(tenant_id, first) == (Decimal("1000.0000"), Decimal("300.0000"))
    assert await _lot_of(tenant_id, second) == (Decimal("1000.0000"), Decimal("1000.0000"))
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("1300")


async def test_a_won_dispute_smaller_than_its_lot_undoes_the_restatement_exactly() -> None:
    """A hold smaller than the purchase restates its lot down (total 1000 -> 100, the 300
    left floored to 0) and meets the 600 shortfall from the next lot. The release puts the
    total back to 1000, the 300 back on that lot and the 600 back on the next one."""
    tenant_id = await _tenant()
    first, second = _id("pay"), _id("pay")
    await _fund(tenant_id, first, "1000.00")
    await _fund(tenant_id, second, "1000.00")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("-700"), reason="usage", ref=_id("call")
        )
        await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=None, amount_inr=Decimal("700")
        )

    assert await _dispute_event(tenant_id, first, "open", 90000) == "held"
    assert await _lot_of(tenant_id, first) == (Decimal("100.0000"), Decimal("0.0000"))
    assert await _lot_of(tenant_id, second) == (Decimal("1000.0000"), Decimal("400.0000"))
    assert await _dispute_event(tenant_id, first, "won", 90000) == "released"

    assert await _lot_of(tenant_id, first) == (Decimal("1000.0000"), Decimal("300.0000"))
    assert await _lot_of(tenant_id, second) == (Decimal("1000.0000"), Decimal("1000.0000"))


# --- the lapsed-credit give-back pair --------------------------------------------------------


async def _low_balance_jobs(tenant_id: UUID) -> int:
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"job": LOW_BALANCE_JOB, "tid": str(tenant_id)},
            )
        ).scalar()
    return int(found or 0)


async def test_a_hold_met_from_lapsed_credit_sends_no_empty_wallet_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lapse already took the credit and told the client their wallet was empty. A
    dispute hold on that purchase is met from the lapsed credit: a +X give-back and the -X
    hold, net nothing. The pair must not tell the client a second time."""
    from tests.refund_lapsed_credit_2026_11_10_test import _bought_with_expiry

    tenant_id = await _tenant()
    payment_id = _id("pay")
    _bought_with_expiry(monkeypatch, lapsed=True)
    await _fund(tenant_id, payment_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        entry = await payments.find_topup(session, tenant_id=tenant_id, ref=payment_id)
        assert entry is not None
        lot = await purchase_lot_of_entry(
            session, tenant_id=tenant_id, ledger_entry_id=entry.entry_id
        )
        assert lot is not None
        expired = await expire_lot(
            session, tenant_id=tenant_id, lot_id=lot.lot_id, now=datetime.now(UTC)
        )
    assert expired is not None
    told = await _low_balance_jobs(tenant_id)

    assert await _dispute_event(tenant_id, payment_id, "open", 40000) == "held"

    assert await _low_balance_jobs(tenant_id) == told
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("0")
