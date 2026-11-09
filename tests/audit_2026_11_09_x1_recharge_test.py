"""Backend audit round 4, lane X1-03 (9 Nov 2026): an auto-recharge charge leaves `pending`
only on Razorpay's final answer, so a late authorisation cannot land beside a second debit.

Vendor facts (Razorpay LLM docs, read 9 Nov 2026): a payment with no bank answer in 10
minutes is "marked as Failed due to timeout" and Razorpay "polls the bank at various
intervals for 3 days" (`payments/payments/late-authorisation.md`); payments authorized within
3 days are auto-captured by default (`payments/payments/capture-settings.md`); a charge
order's attempts are `GET /v1/orders/:id/payments` (`api/orders/fetch-payments.md`).
The provider is a fake throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import auto_recharge
from apps.api.billing.razorpay_api import ProviderPayment
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.auto_recharge_flow_test import _id, _mandate, _member, _pending_charge, _tenant

pytestmark = [pytest.mark.rls]


def _payment(order_id: str, status: str, *, age: timedelta, amount_paise: int = 200000) -> Any:
    return ProviderPayment(
        payment_id=_id("pay"),
        status=status,
        amount_paise=amount_paise,
        currency="INR",
        order_id=order_id,
        method="upi",
        international=False,
        token_id=None,
        customer_id=None,
        notes={},
        error_code="BAD_REQUEST_ERROR" if status == "failed" else None,
        created_at=int((datetime.now(UTC) - age).timestamp()),
    )


@dataclass
class FakeRazorpay:
    by_order: dict[str, list[ProviderPayment]] = field(default_factory=dict)
    orders: list[str] = field(default_factory=list)
    recurring: list[dict[str, Any]] = field(default_factory=list)

    async def order_payments(self, order_id: str) -> list[ProviderPayment]:
        return self.by_order.get(order_id, [])

    async def create_charge_order(self, **_: Any) -> str:
        order_id = _id("order")
        self.orders.append(order_id)
        return order_id

    async def create_recurring_payment(self, **kwargs: Any) -> str:
        self.recurring.append(kwargs)
        return _id("pay")


async def _status(tenant_id: UUID, charge_id: UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, failure_code FROM auto_recharge_charges WHERE id = :c"),
                {"c": charge_id},
            )
        ).one()
    return str(row[0]), row[1]


async def _topups(tenant_id: UUID, payment_id: str) -> list[Decimal]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT delta FROM credit_ledger WHERE reason = 'topup' AND ref = :r"),
            {"r": payment_id},
        )
        return [Decimal(str(d)) for d in rows.scalars()]


async def _recharging_tenant(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, FakeRazorpay]:
    tenant_id = await _tenant()
    payer = await _member(tenant_id)
    await _mandate(tenant_id, enabled=True, payer=payer)
    fake = FakeRazorpay()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    return tenant_id, fake


async def test_a_failed_payment_webhook_does_not_free_the_slot_for_a_second_debit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(tenant_id)

    async with tenant_session(tenant_id) as session:
        await auto_recharge.settle_charge(
            session,
            tenant_id=tenant_id,
            order_id=order_id,
            payment_id=_id("pay"),
            captured=False,
            failure_code="BAD_REQUEST_ERROR",
        )

    assert await _status(tenant_id, charge_id) == ("pending", "BAD_REQUEST_ERROR")
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "in_flight"
    assert fake.recurring == [], "a payment the bank may still authorise is not debited again"


@pytest.mark.parametrize(
    ("status", "age"),
    [
        ("authorized", timedelta(days=3, hours=1)),
        ("created", timedelta(days=3, hours=1)),
        ("failed", timedelta(days=1)),
    ],
)
async def test_an_old_charge_whose_payment_can_still_capture_stays_pending(
    monkeypatch: pytest.MonkeyPatch, status: str, age: timedelta
) -> None:
    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    fake.by_order[order_id] = [_payment(order_id, status, age=age)]

    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    assert (await _status(tenant_id, charge_id))[0] == "pending"
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "in_flight"
    assert fake.recurring == []


async def test_an_old_charge_found_captured_is_credited_once_and_counts_against_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    captured = _payment(order_id, "captured", age=timedelta(days=2))
    fake.by_order[order_id] = [_payment(order_id, "failed", age=timedelta(days=3)), captured]

    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    assert await auto_recharge.expire_unanswered(tenant_id) == 0

    assert await _status(tenant_id, charge_id) == ("captured", None)
    assert await _topups(tenant_id, captured.payment_id) == [Decimal("2000.0000")]
    async with tenant_session(tenant_id) as session:
        spent = await auto_recharge._month_spent(session, tenant_id, at=datetime.now(UTC))
    assert spent == Decimal("2000")


async def test_an_old_charge_whose_payments_all_failed_past_late_authorisation_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    fake.by_order[order_id] = [_payment(order_id, "failed", age=timedelta(days=3, hours=1))]

    assert await auto_recharge.expire_unanswered(tenant_id) == 1
    assert await _status(tenant_id, charge_id) == ("failed", "BAD_REQUEST_ERROR")


async def test_a_provider_that_cannot_be_read_leaves_the_charge_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, _ = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )

    async def _down(order_id: str) -> list[ProviderPayment]:
        raise ProblemError(
            kind="dependency",
            code="payment_provider_unreachable",
            title="x",
            detail="x",
            remediation="x",
        )

    monkeypatch.setattr(fake, "order_payments", _down)
    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    assert (await _status(tenant_id, charge_id))[0] == "pending"
