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


async def test_a_payment_refunded_without_ever_being_captured_credits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authorized payment never captured is auto-refunded (capture-settings): `refunded`
    with `captured: false` took no money, so the wallet is not credited for it."""
    from dataclasses import replace

    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    returned = replace(
        _payment(order_id, "refunded", age=timedelta(days=3, hours=1)), captured=False
    )
    fake.by_order[order_id] = [returned]

    await auto_recharge.expire_unanswered(tenant_id)

    assert await _topups(tenant_id, returned.payment_id) == []
    status, _ = await _status(tenant_id, charge_id)
    assert status != "captured"


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


async def test_an_old_charge_found_captured_on_a_recharge_route_is_closed_by_the_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An order recorded as an auto-recharge is closed inside `apply_captured`, so the
    sweep does not settle it a second time; either way it ends captured and credited once."""
    from apps.api.billing.payment_objects import AUTO_RECHARGE, record_route

    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=AUTO_RECHARGE,
            amount_inr=Decimal("2000"),
        )
    captured = _payment(order_id, "captured", age=timedelta(days=2))
    fake.by_order[order_id] = [captured]

    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    assert await _status(tenant_id, charge_id) == ("captured", None)
    assert await _topups(tenant_id, captured.payment_id) == [Decimal("2000.0000")]


async def test_a_charge_still_holding_its_claim_is_failed_without_asking_razorpay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A charge whose order was never created still carries its `claim:` placeholder: there
    is no order to read, so three days on it is failed as unanswered."""
    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id = await _pending_charge_with_order(
        tenant_id, order_id=f"claim:{_id('x')}", age=timedelta(days=3, hours=1)
    )

    async def _never(order_id: str) -> list[ProviderPayment]:
        raise AssertionError("a claim placeholder is not a Razorpay order")

    monkeypatch.setattr(fake, "order_payments", _never)
    assert await auto_recharge.expire_unanswered(tenant_id) == 1
    assert await _status(tenant_id, charge_id) == ("failed", "no_answer")


async def test_a_capture_that_cannot_be_credited_stays_pending_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id, fake = await _recharging_tenant(monkeypatch)
    charge_id, order_id = await _pending_charge(
        tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW + timedelta(hours=2)
    )
    captured = _payment(order_id, "captured", age=timedelta(days=2))
    fake.by_order[order_id] = [captured]

    async def _refused(*_: Any, **__: Any) -> None:
        raise ProblemError(
            kind="conflict", code="payment_tenant_mismatch", title="x", detail="x", remediation="x"
        )

    alarms: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(auto_recharge, "_credit_late_capture", _refused)
    monkeypatch.setattr(auto_recharge, "alert", lambda _src, name, **kw: alarms.append((name, kw)))

    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    assert (await _status(tenant_id, charge_id))[0] == "pending"
    assert [name for name, _ in alarms] == ["auto_recharge_capture_unplaced"]
    assert alarms[0][1]["payment_id"] == captured.payment_id
    assert alarms[0][1]["refusal"] == "payment_tenant_mismatch"


async def _pending_charge_with_order(tenant_id: UUID, *, order_id: str, age: timedelta) -> UUID:
    import uuid

    charge_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO auto_recharge_charges (id, tenant_id, order_id, amount_inr, status, "
                "created_at) VALUES (:id, :t, :o, 2000, 'pending', :at)"
            ),
            {"id": charge_id, "t": tenant_id, "o": order_id, "at": datetime.now(UTC) - age},
        )
    return charge_id
