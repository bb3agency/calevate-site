"""The monthly platform fee's edges (D-707) that `platform_fee_test.py` does not walk.

1. **Paying a fee online**: the order route refuses an unknown, paid or unpayable fee,
   hands back a bank-transfer receipt when this deployment cannot create orders, creates
   exactly one order per fee however often it is asked, and lets a client retry after
   the provider failed.
2. **The webhook's fee branch**: a fee payment whose order no fee carries alarms and
   records nothing; the reconciliation path (no envelope) settles once and reads a
   repeat of the same payment as a duplicate, not as a second payment.
3. **The operator's panel**: the read is audited, withdrawing a waiver that is not there
   writes nothing, and recording a fee twice audits it once.
4. **The money guards in `platform_fee`**: no fee of zero, no payment of the wrong amount,
   an account whose trial ended unpaid stays exempt.

CONCURRENCY: every case mints its own tenant.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import payment_events, platform_fee_routes
from apps.api.billing.payment_objects import PLATFORM_FEE, record_route, route_for
from apps.api.billing.payments import (
    NOTES_TENANT_KEY,
    CapturedPayment,
    PaymentCapability,
    ProviderOrder,
    inr_to_paise,
)
from apps.api.billing.platform_fee import (
    NOTES_CHARGE_KEY,
    attach_order,
    exemption_of,
    issue_charge,
    list_charges,
    read_charge,
    record_payment,
)
from apps.api.billing.platform_fee_routes import fee_receipt
from apps.api.core.auth import ADMIN_TENANT_READ_ACTION
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.platform_fee_test import FEE, _admin, _audit, _http, _issue, _owner, _tenant

pytestmark = [pytest.mark.rls]

KEY_ID = "rzp_test_fee_edges"


@pytest.fixture(autouse=True)
def _fee_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "platform_fee_enabled", True)
    monkeypatch.setattr(settings, "platform_fee_inr", FEE)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)


class _Orders:
    """Stands in for the Razorpay order adapter; counts what it was asked to create."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def create_order(
        self, *, amount_inr: Decimal, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder:
        self.calls.append({"amount_inr": amount_inr, "receipt": receipt, "notes": notes})
        if self.fail:
            raise ProblemError(
                kind="dependency",
                code="payment_provider_unavailable",
                title="Payment provider unavailable",
                detail="The order could not be created.",
            )
        return ProviderOrder(
            order_id=f"order_{uuid.uuid4().hex[:14]}",
            receipt=receipt,
            amount_paise=inr_to_paise(amount_inr),
        )


def _capability(monkeypatch: pytest.MonkeyPatch, capability: PaymentCapability) -> None:
    monkeypatch.setattr(platform_fee_routes, "payment_capability", lambda: capability)


def _orders(monkeypatch: pytest.MonkeyPatch, orders: _Orders) -> None:
    monkeypatch.setattr(platform_fee_routes, "razorpay_orders", lambda: orders)


CREATES_ORDERS = PaymentCapability(available=True, provider="razorpay", creates_orders=True)


async def _open_order(tenant_id: UUID, charge_id: UUID, token: str) -> Any:
    async with _http() as http:
        return await http.post(
            f"/v1/billing/platform-fee/{charge_id}/order",
            headers={"Authorization": f"Bearer {token}"},
        )


def _code(response: Any) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _payments(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM monthly_fee_payments WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar()
            or 0
        )


# --- paying a fee online ----------------------------------------------------------------


async def test_an_unknown_fee_has_no_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _capability(monkeypatch, CREATES_ORDERS)
    tenant_id = await _tenant()
    response = await _open_order(tenant_id, uuid.uuid4(), await _owner(tenant_id))
    assert response.status_code == 404, response.text


async def test_a_paid_fee_is_not_payable_again(monkeypatch: pytest.MonkeyPatch) -> None:
    orders = _Orders()
    _capability(monkeypatch, CREATES_ORDERS)
    _orders(monkeypatch, orders)
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
        assert charge is not None
        await record_payment(
            session,
            tenant_id=tenant_id,
            charge=charge,
            amount_inr=FEE,
            method="manual",
            payment_ref=f"UTR{uuid.uuid4().hex[:12]}",
            paid_at=datetime.now(UTC),
        )
    response = await _open_order(tenant_id, charge_id, await _owner(tenant_id))
    assert response.status_code == 422, response.text
    assert _code(response) == "platform_fee_not_payable"
    assert orders.calls == [], "no order is opened for a fee that is settled"


async def test_no_online_payment_means_no_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _capability(monkeypatch, PaymentCapability(available=False, reason="no_provider"))
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    response = await _open_order(tenant_id, charge_id, await _owner(tenant_id))
    assert response.status_code == 503, response.text
    assert _code(response) == "payments_not_configured"


async def test_without_an_api_secret_the_fee_is_paid_by_transfer_quoting_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = _Orders()
    _capability(
        monkeypatch, PaymentCapability(available=True, provider="razorpay", creates_orders=False)
    )
    _orders(monkeypatch, orders)
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    response = await _open_order(tenant_id, charge_id, await _owner(tenant_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_order_id"] is None and body["provider_order_pending"] is True
    assert body["receipt"] == fee_receipt(charge_id)
    assert len(body["receipt"]) <= 40, "Razorpay caps a receipt at 40 characters"
    assert body["amount_inr"] == "1999.00" and body["amount_paise"] == 199900
    assert body["key_id"] == KEY_ID
    assert orders.calls == []


async def test_one_fee_opens_one_order_however_often_it_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = _Orders()
    _capability(monkeypatch, CREATES_ORDERS)
    _orders(monkeypatch, orders)
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    token = await _owner(tenant_id)

    first = await _open_order(tenant_id, charge_id, token)
    assert first.status_code == 200, first.text
    order_id = first.json()["provider_order_id"]
    assert order_id is not None and first.json()["provider_order_pending"] is False
    assert orders.calls == [
        {
            "amount_inr": Decimal("1999.00"),
            "receipt": fee_receipt(charge_id),
            "notes": first.json()["notes"],
        }
    ]
    assert first.json()["notes"] == {
        NOTES_TENANT_KEY: str(tenant_id),
        NOTES_CHARGE_KEY: str(charge_id),
    }

    # The order is OURS on record: the webhook can tell it pays a fee, for this tenant.
    route = await route_for(order_id)
    assert route is not None
    assert route.tenant_id == tenant_id and route.purpose == PLATFORM_FEE
    assert route.amount_paise == 199900
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
    assert charge is not None and charge.provider_order_id == order_id

    again = await _open_order(tenant_id, charge_id, token)
    assert again.json()["provider_order_id"] == order_id
    assert len(orders.calls) == 1, "a second click is handed the same order"


async def test_a_request_that_read_the_fee_before_the_order_landed_replays_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two owners click at once: B reads the fee before A's order is attached, and claims
    the idempotency key after A completed it. B must be handed A's order, never open a
    second one for the same fee."""
    orders = _Orders()
    _capability(monkeypatch, CREATES_ORDERS)
    _orders(monkeypatch, orders)
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    token = await _owner(tenant_id)
    first = await _open_order(tenant_id, charge_id, token)
    assert first.status_code == 200, first.text

    real_read = read_charge

    async def stale_read(session: Any, *, tenant_id: UUID, charge_id: UUID) -> Any:
        charge = await real_read(session, tenant_id=tenant_id, charge_id=charge_id)
        assert charge is not None
        return dataclasses.replace(charge, provider_order_id=None)

    monkeypatch.setattr(platform_fee_routes, "read_charge", stale_read)
    raced = await _open_order(tenant_id, charge_id, token)
    assert raced.status_code == 200, raced.text
    assert raced.json() == first.json()
    assert len(orders.calls) == 1


async def test_a_provider_failure_releases_the_fee_for_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _Orders(fail=True)
    _capability(monkeypatch, CREATES_ORDERS)
    _orders(monkeypatch, failing)
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    token = await _owner(tenant_id)

    failed = await _open_order(tenant_id, charge_id, token)
    assert failed.status_code == 503, failed.text
    assert _code(failed) == "payment_provider_unavailable"
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
    assert charge is not None and charge.provider_order_id is None

    working = _Orders()
    _orders(monkeypatch, working)
    retried = await _open_order(tenant_id, charge_id, token)
    assert retried.status_code == 200, retried.text
    assert retried.json()["provider_order_id"] is not None
    assert len(working.calls) == 1, "the failed attempt must not own the key"


# --- the webhook's fee branch -----------------------------------------------------------


def _fee_payment(tenant_id: UUID, order_id: str, payment_id: str) -> CapturedPayment:
    return CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=FEE,
        currency="INR",
        order_id=order_id,
    )


async def _fee_order(tenant_id: UUID, *, charge_id: UUID | None) -> str:
    order_id = f"order_{uuid.uuid4().hex[:14]}"
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=PLATFORM_FEE,
            amount_inr=FEE,
        )
        if charge_id is not None:
            await attach_order(session, tenant_id=tenant_id, charge_id=charge_id, order_id=order_id)
    return order_id


async def test_a_fee_payment_no_fee_carries_alarms_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms: list[str] = []
    monkeypatch.setattr(payment_events, "alert", lambda _s, code, **_kw: alarms.append(code))
    tenant_id = await _tenant()
    await _issue(tenant_id, at=datetime.now(UTC))
    order_id = await _fee_order(tenant_id, charge_id=None)

    with pytest.raises(ProblemError) as refused:
        await payment_events.apply_captured(
            None,
            event="payment.captured",
            event_id=None,
            payment=_fee_payment(tenant_id, order_id, f"pay_{uuid.uuid4().hex[:14]}"),
            route=await route_for(order_id),
        )
    assert refused.value.code == "platform_fee_unmatched"
    assert alarms == ["platform_fee_payment_unmatched"]
    assert await _payments(tenant_id) == 0


async def test_reconciliation_settles_a_fee_once_and_a_repeat_is_not_a_second_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms: list[str] = []
    monkeypatch.setattr(payment_events, "alert", lambda _s, code, **_kw: alarms.append(code))
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    order_id = await _fee_order(tenant_id, charge_id=charge_id)
    payment = _fee_payment(tenant_id, order_id, f"pay_{uuid.uuid4().hex[:14]}")
    route = await route_for(order_id)

    first = await payment_events.apply_captured(
        None, event="payment.captured", event_id=None, payment=payment, route=route
    )
    repeat = await payment_events.apply_captured(
        None, event="payment.captured", event_id=None, payment=payment, route=route
    )
    assert first.status == "fee_paid" and first.amount_inr == Decimal("1999.00")
    assert repeat.status == "duplicate"
    assert alarms == [], "the same payment seen twice is not money received twice"
    assert await _payments(tenant_id) == 1
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
    assert charge is not None and charge.paid and charge.payment_method == "razorpay"


# --- the operator's panel ---------------------------------------------------------------


async def test_the_operator_read_shows_the_fee_and_is_audited() -> None:
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    async with _http() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/platform-fee",
            headers={"Authorization": f"Bearer {await _admin('operator')}"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True and body["amount_inr"] == "1999.00"
    assert body["exemption"] is None and body["waiver"] is None
    assert body["outbound_paused"] is False
    assert [c["id"] for c in body["charges"]] == [str(charge_id)]
    assert body["charges"][0]["status"] == "due"
    assert await _audit(tenant_id, ADMIN_TENANT_READ_ACTION) == 1


async def test_withdrawing_a_waiver_that_is_not_there_writes_nothing() -> None:
    tenant_id = await _tenant()
    async with _http() as http:
        response = await http.delete(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/waiver",
            headers={"Authorization": f"Bearer {await _admin('operator')}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["waiver"] is None
    assert await _audit(tenant_id, "tenant.platform_fee_waiver_withdrawn") == 0


async def _record_manually(tenant_id: UUID, charge_id: UUID, reference: str, token: str) -> Any:
    async with _http() as http:
        return await http.post(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/{charge_id}/payments",
            json={"reference": reference},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": f"record_fee_payment:{tenant_id}:{charge_id}",
            },
        )


async def test_recording_an_unknown_fee_is_not_found_and_a_second_record_audits_once() -> None:
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    token = await _admin("operator")
    reference = f"UTR{uuid.uuid4().hex[:12]}"

    unknown = await _record_manually(tenant_id, uuid.uuid4(), reference, token)
    assert unknown.status_code == 404, unknown.text

    first = await _record_manually(tenant_id, charge_id, reference, token)
    second = await _record_manually(tenant_id, charge_id, reference, token)
    assert first.json() == {"charge_id": str(charge_id), "recorded": True, "status": "paid"}
    assert second.status_code == 200, second.text
    assert second.json() == {"charge_id": str(charge_id), "recorded": False, "status": "paid"}
    assert await _audit(tenant_id, "tenant.platform_fee_paid_manually") == 1
    assert await _payments(tenant_id) == 1


async def test_a_reference_that_settled_another_fee_is_refused_not_reported_paid() -> None:
    """The reference index is unique across every tenant. A transfer reference already
    used for one client's fee must not read as "already paid" on another's: that fee is
    still owed, and a 200 would hide it."""
    first_tenant, second_tenant = await _tenant(), await _tenant()
    first_charge = await _issue(first_tenant, at=datetime.now(UTC))
    second_charge = await _issue(second_tenant, at=datetime.now(UTC))
    token = await _admin("operator")
    reference = f"UTR{uuid.uuid4().hex[:12]}"

    settled = await _record_manually(first_tenant, first_charge, reference, token)
    assert settled.json()["recorded"] is True, settled.text
    reused = await _record_manually(second_tenant, second_charge, reference, token)
    assert reused.status_code == 409, reused.text
    assert _code(reused) == "platform_fee_reference_used"
    assert await _payments(second_tenant) == 0
    assert await _audit(second_tenant, "tenant.platform_fee_paid_manually") == 0
    async with tenant_session(second_tenant) as session:
        charge = await read_charge(session, tenant_id=second_tenant, charge_id=second_charge)
    assert charge is not None and not charge.paid


# --- the money guards -------------------------------------------------------------------


async def test_a_fee_of_nothing_is_never_raised() -> None:
    tenant_id = await _tenant()
    for amount in (Decimal("0"), Decimal("-1.00")):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ValueError, match="positive"):
                await issue_charge(
                    session, tenant_id=tenant_id, amount_inr=amount, at=datetime.now(UTC)
                )
    async with tenant_session(tenant_id) as session:
        assert await list_charges(session, tenant_id=tenant_id) == []


async def test_a_payment_of_the_wrong_amount_is_refused_and_records_nothing() -> None:
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
        assert charge is not None
        with pytest.raises(ProblemError) as refused:
            await record_payment(
                session,
                tenant_id=tenant_id,
                charge=charge,
                amount_inr=FEE - Decimal("0.01"),
                method="manual",
                payment_ref="UTR-short",
                paid_at=datetime.now(UTC),
            )
    assert refused.value.code == "platform_fee_amount_mismatch"
    assert await _payments(tenant_id) == 0


async def test_an_account_whose_trial_ended_unpaid_stays_exempt() -> None:
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'prepaid' WHERE id = :t"), {"t": tenant_id}
        )
        assert await exemption_of(session, tenant_id=tenant_id, at=now) is None
        await session.execute(
            text(
                "INSERT INTO tenant_trials (id, tenant_id, days, started_at, ends_at, status, "
                "ended_at) VALUES (:id, :t, 14, :start, :ends, 'expired', :ends)"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "start": now - timedelta(days=20),
                "ends": now - timedelta(days=6),
            },
        )
        assert await exemption_of(session, tenant_id=tenant_id, at=now) == "trial"


async def test_an_account_that_does_not_exist_has_no_exemption() -> None:
    absent = uuid.uuid4()
    async with tenant_session(absent) as session:
        assert await exemption_of(session, tenant_id=absent, at=datetime.now(UTC)) is None
