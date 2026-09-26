"""Money arriving on an OVERDRAWN wallet is recorded, whichever writer carries it.

`record_entry` refuses an entry that leaves the balance below zero. It applied that to
every delta, so a CREDIT that shrank the debt without clearing it was refused as
`insufficient_credits` — the accounting layer declining to record money that had already
arrived. The operator top-up and restatement routes each opted out with
`allow_negative=True`; the Razorpay capture did not, so a client whose wallet a long call
had driven to -₹500 who then paid ₹100 at checkout was debited by the bank and credited
nothing: the webhook answered 422, `razorpay_money_unapplied` fired, and every provider
retry hit the same refusal.

The guard exists for DEBITS. A positive delta cannot make a balance worse, so the fix is
in `record_entry` itself rather than in a fourth caller remembering a flag.

Run: uv run pytest -q tests/overdrawn_wallet_credit_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.lots import CallDemand, read_open_lots
from apps.api.billing.service import (
    LotRates,
    get_balance,
    record_entry,
    record_usage_from_lots,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _overdrawn_tenant(*, arrears_inr: str) -> UUID:
    """A self-serve wallet driven below zero by a completed call, as production does it."""
    created = await admin_service.create_organization(
        name="Overdrawn Clinic",
        slug=f"ovd-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    rates = LotRates(Decimal("5.00"), Decimal("8.00"))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref=f"call:{uuid.uuid4()}",
            demand=CallDemand(
                minutes=Decimal(arrears_inr) / rates.clear_inr_per_min,
                voice_tier="clear",
                fallback_rates=rates,
            ),
            allow_negative=True,
        )
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == -Decimal(arrears_inr)
    return tenant_id


async def test_a_checkout_payment_smaller_than_the_arrears_is_credited() -> None:
    tenant_id = await _overdrawn_tenant(arrears_inr="500.00")
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"

    async with tenant_session(tenant_id) as session:
        result = await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal("100.00"),
                currency="INR",
                pack_id=None,
            ),
        )

    assert result.recorded is True
    # The debt shrank by exactly what was paid; nothing was invented and nothing lost.
    assert result.balance.amount_inr == Decimal("-400.00")
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("-400.00")
        # Every rupee repaid arrears, so no lot opened (plan §0 Q5), and the invariant
        # `SUM(credits_remaining) == balance when non-negative` has nothing to disagree on.
        assert await read_open_lots(session, tenant_id=tenant_id) == []
        # The payment is findable by its id, so a provider retry dedupes on it.
        found = await payments.find_topup(session, tenant_id=tenant_id, ref=payment_id)
    assert found is not None and found.amount_inr == Decimal("100.00")


async def test_a_replayed_capture_on_an_overdrawn_wallet_credits_once() -> None:
    tenant_id = await _overdrawn_tenant(arrears_inr="500.00")
    payment = payments.CapturedPayment(
        payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        amount_inr=Decimal("100.00"),
        currency="INR",
        pack_id=None,
    )
    for _ in range(2):
        async with tenant_session(tenant_id) as session:
            await payments.credit_captured_payment(session, payment=payment)

    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("-400.00")


async def test_a_credit_that_leaves_the_wallet_negative_is_recorded_by_default() -> None:
    """The unit of the fix: no caller has to remember a flag to record incoming money."""
    tenant_id = await _overdrawn_tenant(arrears_inr="300.00")
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("50"), reason="grant", ref="g-1"
        )
    assert balance.amount_inr == Decimal("-250.00")


async def test_a_debit_that_overdraws_is_still_refused_by_default() -> None:
    """The half of the guard that was always right, pinned beside the half that was not."""
    tenant_id = await _overdrawn_tenant(arrears_inr="300.00")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await record_entry(session, tenant_id=tenant_id, delta=Decimal("-1"), reason="usage")
    assert raised.value.code == "insufficient_credits"
