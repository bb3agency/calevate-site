"""Auto-recharge (D-699) beyond the happy path `razorpay_payments_e2e_test` walks: the
defaults and the suggested threshold, every refusal on save, the mandate's whole life
(begin, confirm, token states, cancel), the sweep's own helpers and the client routes.

The provider is a fake throughout; no test reaches Razorpay.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import auto_recharge, auto_recharge_routes, payments
from apps.api.billing.payment_objects import MANDATE, record_route, route_for
from apps.api.billing.razorpay_api import MANDATE_MAX_DEBIT_INR, ProviderPayment
from apps.api.billing.service import get_balance
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

WEBHOOK_SECRET = "whsec_flow_test"
KEY_ID = "rzp_test_flow"
KEY_SECRET = "rzp_secret_flow"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(settings, "razorpay_mode", None)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Recharge Clinic",
        slug=f"ar-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _member(tenant_id: UUID, *, phone: str | None = "+919900000000") -> UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, phone, created_at, updated_at) "
                "VALUES (:id, :email, :phone, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "phone": phone},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return user_id


async def _mandate(
    tenant_id: UUID,
    *,
    status: str = "confirmed",
    enabled: bool = False,
    method: str = "upi",
    payer: UUID | None = None,
    token: bool = True,
) -> str:
    token_id = _id("token")
    async with tenant_session(tenant_id) as session:
        await record_route(session, tenant_id=tenant_id, object_id=token_id, kind="token")
        await session.execute(
            text(
                "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
                "amount_inr, monthly_cap_inr, customer_id, token_id, mandate_method, "
                "mandate_status, mandate_max_inr, authorised_by) VALUES (:id, :tid, :en, 500, "
                "2000, 4000, 'cust_flow', :tok, :method, :st, 2000, :uid)"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "en": enabled,
                "tok": token_id if token else None,
                "method": method,
                "st": status,
                "uid": payer,
            },
        )
    return token_id


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), {"t": tenant_id, **params})).scalar()


async def _notices(tenant_id: UUID, kind: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :j "
                        "AND payload->>'tenant_id' = :t AND payload->>'kind' = :k"
                    ),
                    {"j": auto_recharge.PAYMENT_NOTICE_JOB, "t": str(tenant_id), "k": kind},
                )
            ).scalar()
            or 0
        )


async def _audits(tenant_id: UUID, action: str) -> int:
    return int(
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = :a",
            a=action,
        )
        or 0
    )


@dataclass
class FakeApi:
    customers: list[dict[str, Any]] = field(default_factory=list)
    mandate_orders: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[dict[str, Any]] = field(default_factory=list)
    token_id: str | None = None
    token_state: str | None = None

    async def create_customer(self, **kwargs: Any) -> str:
        self.customers.append(kwargs)
        return _id("cust")

    async def create_mandate_order(self, **kwargs: Any) -> str:
        order_id = _id("order")
        self.mandate_orders.append({"id": order_id, **kwargs})
        return order_id

    async def fetch_payment(self, payment_id: str) -> ProviderPayment:
        return ProviderPayment(
            payment_id=payment_id,
            status="captured",
            amount_paise=100,
            currency="INR",
            order_id=None,
            method="upi",
            international=False,
            token_id=self.token_id,
            customer_id=None,
            notes={},
            error_code=None,
            created_at=0,
        )

    async def cancel_token(self, **kwargs: Any) -> None:
        self.cancelled.append(kwargs)

    async def token_status(self, **_: Any) -> str | None:
        return self.token_state


def _sign(order_id: str, payment_id: str) -> str:
    return hmac.new(
        KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


# --- reading and saving -----------------------------------------------------------------


async def test_a_tenant_with_no_settings_reads_the_defaults_and_a_usage_based_suggestion() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
    assert state.enabled is False
    assert state.mandate_status == "none"
    assert state.threshold_inr == auto_recharge.DEFAULT_THRESHOLD_INR
    assert state.pending_charge_inr is None
    assert state.suggested_threshold_inr is None, "no usage, no suggestion"

    # ₹1,400 of calling over the 14-day window is ₹100 a day; 1.5 days of it is ₹150,
    # rounded UP to the next ₹100.
    async with tenant_session(tenant_id) as session:
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) VALUES (gen_random_uuid(), :t, -1400, 'usage', :ref, "
                ":bal, now() - interval '2 days', now())"
            ),
            {"t": tenant_id, "ref": _id("usage"), "bal": balance - 1400},
        )
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
    assert state.suggested_threshold_inr == Decimal("200.00")


@pytest.mark.parametrize(
    ("threshold", "amount", "cap", "fragment"),
    [
        ("-1.00", "2000.00", "6000.00", "cannot be negative"),
        ("500.00", "2000.00", "1999.00", "at least one recharge"),
        ("500.00", "99.00", "6000.00", "between"),
    ],
)
async def test_an_invalid_setting_is_refused(
    threshold: str, amount: str, cap: str, fragment: str
) -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await auto_recharge.save_auto_recharge(
                session,
                tenant_id=tenant_id,
                enabled=False,
                threshold_inr=Decimal(threshold),
                amount_inr=Decimal(amount),
                monthly_cap_inr=Decimal(cap),
                actor_user_id=None,
            )
    assert refused.value.code == "auto_recharge_invalid"
    assert fragment in str(refused.value.detail)


async def test_switching_on_above_the_mandate_limit_is_refused_and_within_it_resets_failures() -> (
    None
):
    tenant_id = await _tenant()
    await _mandate(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE auto_recharge_settings SET consecutive_failures = 2, "
                "disabled_reason = 'off' WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
        with pytest.raises(ProblemError) as refused:
            await auto_recharge.save_auto_recharge(
                session,
                tenant_id=tenant_id,
                enabled=True,
                threshold_inr=Decimal("500.00"),
                amount_inr=Decimal("3000.00"),
                monthly_cap_inr=Decimal("6000.00"),
                actor_user_id=None,
            )
    assert refused.value.code == "auto_recharge_over_mandate"
    assert "2000.00" in str(refused.value.detail)

    actor = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        state = await auto_recharge.save_auto_recharge(
            session,
            tenant_id=tenant_id,
            enabled=True,
            threshold_inr=Decimal("700.00"),
            amount_inr=Decimal("1500.00"),
            monthly_cap_inr=Decimal("4500.00"),
            actor_user_id=actor,
            ip="203.0.113.9",
        )
    assert state.enabled is True
    assert state.amount_inr == Decimal("1500.00")
    assert state.threshold_inr == Decimal("700.00")
    assert state.consecutive_failures == 0
    assert state.disabled_reason is None
    assert state.mandate_max_inr == Decimal("2000.00")
    assert await _audits(tenant_id, "auto_recharge.settings") == 1


# --- the mandate --------------------------------------------------------------------------


async def test_a_per_payment_limit_outside_the_range_is_refused_before_the_provider() -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id)
    for limit in (Decimal("99.00"), MANDATE_MAX_DEBIT_INR + 1):
        with pytest.raises(ProblemError) as refused:
            await auto_recharge.begin_mandate(
                tenant_id=tenant_id, user_id=user_id, method="upi", max_debit_inr=limit
            )
        assert refused.value.code == "auto_recharge_invalid"


async def test_a_member_without_a_mobile_number_cannot_begin_a_mandate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id, phone=None)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    with pytest.raises(ProblemError) as refused:
        await auto_recharge.begin_mandate(
            tenant_id=tenant_id, user_id=user_id, method="upi", max_debit_inr=Decimal("2000.00")
        )
    assert refused.value.code == "auto_recharge_needs_contact"
    assert fake.customers == [], "nothing reaches the provider"


async def test_a_mandate_is_begun_confirmed_and_its_customer_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)

    checkout = await auto_recharge.begin_mandate(
        tenant_id=tenant_id, user_id=user_id, method="card", max_debit_inr=Decimal("1000.00")
    )
    assert checkout.key_id == KEY_ID
    assert checkout.amount_paise == 100
    assert checkout.notes == {
        payments.NOTES_TENANT_KEY: str(tenant_id),
        "calevate_purpose": MANDATE,
    }
    assert len(fake.customers) == 1
    assert fake.mandate_orders[0]["max_debit_inr"] == Decimal("1000.00")
    route = await route_for(checkout.order_id)
    assert route is not None and route.tenant_id == tenant_id
    async with tenant_session(tenant_id) as session:
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
    assert state.mandate_status == "pending" and state.mandate_method == "card"
    assert state.amount_inr == Decimal("1000.00"), "never above the per-payment limit"
    assert state.monthly_cap_inr == auto_recharge.DEFAULT_MONTHLY_CAP_INR
    assert await _audits(tenant_id, "auto_recharge.mandate_started") == 1

    again = await auto_recharge.begin_mandate(
        tenant_id=tenant_id, user_id=user_id, method="upi", max_debit_inr=Decimal("2000.00")
    )
    assert len(fake.customers) == 1, "the customer is reused"
    assert again.customer_id == checkout.customer_id

    payment_id = _id("pay")
    # The browser echoes a stale order id: refused, whatever the signature.
    with pytest.raises(ProblemError) as stale:
        await auto_recharge.confirm_mandate(
            tenant_id=tenant_id,
            order_id=checkout.order_id,
            payment_id=payment_id,
            signature=_sign(checkout.order_id, payment_id),
        )
    assert stale.value.code == "payment_signature_invalid"
    with pytest.raises(ProblemError) as forged:
        await auto_recharge.confirm_mandate(
            tenant_id=tenant_id, order_id=again.order_id, payment_id=payment_id, signature="0" * 64
        )
    assert forged.value.code == "payment_signature_invalid"

    fake.token_id = _id("token")
    state = await auto_recharge.confirm_mandate(
        tenant_id=tenant_id,
        order_id=again.order_id,
        payment_id=payment_id,
        signature=_sign(again.order_id, payment_id),
    )
    assert state.mandate_status == "pending", "usable only once the token is confirmed"
    stored = await _scalar(
        tenant_id, "SELECT token_id FROM auto_recharge_settings WHERE tenant_id = :t"
    )
    assert stored == fake.token_id
    token_route = await route_for(fake.token_id)
    assert token_route is not None and token_route.kind == "token"


async def test_a_confirmation_without_a_token_records_none(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    checkout = await auto_recharge.begin_mandate(
        tenant_id=tenant_id, user_id=user_id, method="upi", max_debit_inr=Decimal("2000.00")
    )
    payment_id = _id("pay")
    await auto_recharge.confirm_mandate(
        tenant_id=tenant_id,
        order_id=checkout.order_id,
        payment_id=payment_id,
        signature=_sign(checkout.order_id, payment_id),
    )
    assert (
        await _scalar(tenant_id, "SELECT token_id FROM auto_recharge_settings WHERE tenant_id = :t")
        is None
    )


async def test_a_confirmation_for_a_tenant_with_no_mandate_is_refused() -> None:
    tenant_id = await _tenant()
    with pytest.raises(ProblemError) as refused:
        await auto_recharge.confirm_mandate(
            tenant_id=tenant_id, order_id="order_x", payment_id="pay_x", signature="x"
        )
    assert refused.value.code == "payment_signature_invalid"


async def test_a_captured_authorisation_payment_keeps_its_token_only_for_our_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id)
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: FakeApi())
    checkout = await auto_recharge.begin_mandate(
        tenant_id=tenant_id, user_id=user_id, method="upi", max_debit_inr=Decimal("2000.00")
    )
    token_id = _id("token")
    async with tenant_session(tenant_id) as session:
        await auto_recharge.note_mandate_payment(
            session, tenant_id=tenant_id, order_id="order_other", token_id=token_id
        )
        await auto_recharge.note_mandate_payment(
            session, tenant_id=tenant_id, order_id=checkout.order_id, token_id=None
        )
    sql = "SELECT token_id FROM auto_recharge_settings WHERE tenant_id = :t"
    assert await _scalar(tenant_id, sql) is None
    async with tenant_session(tenant_id) as session:
        await auto_recharge.note_mandate_payment(
            session, tenant_id=tenant_id, order_id=checkout.order_id, token_id=token_id
        )
    assert await _scalar(tenant_id, sql) == token_id


async def test_token_states_move_the_mandate_and_notify_once_per_change() -> None:
    tenant_id = await _tenant()
    token_id = await _mandate(tenant_id, status="pending")
    async with tenant_session(tenant_id) as session:
        # `initiated` is our `pending`, which it already is: no change.
        assert not await auto_recharge.apply_token_status(
            session, tenant_id=tenant_id, token_id=token_id, status="initiated"
        )
        assert await auto_recharge.apply_token_status(
            session, tenant_id=tenant_id, token_id=token_id, status="confirmed"
        )
        assert not await auto_recharge.apply_token_status(
            session, tenant_id=tenant_id, token_id=token_id, status="confirmed"
        )
        assert await auto_recharge.apply_token_status(
            session, tenant_id=tenant_id, token_id=token_id, status="initiated"
        )
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
    assert state.mandate_status == "pending"
    assert await _notices(tenant_id, "mandate_confirmed") == 1
    assert await _notices(tenant_id, "mandate_ended") == 0, "pending is not an ending"
    assert await _audits(tenant_id, "auto_recharge.mandate_status") == 2
    assert auto_recharge.token_status_of_event("token.paused") == "paused"
    assert auto_recharge.token_status_of_event("payment.captured") is None


async def test_cancelling_with_no_token_only_switches_off_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _mandate(tenant_id, status="pending", token=False)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    state = await auto_recharge.cancel_mandate(tenant_id=tenant_id, actor_user_id=None)
    assert state.mandate_status == "none" and state.enabled is False
    assert fake.cancelled == []


async def test_cancelling_a_card_mandate_withdraws_it_at_the_provider_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    token_id = await _mandate(tenant_id, enabled=True, method="card")
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    actor = uuid.uuid4()
    state = await auto_recharge.cancel_mandate(tenant_id=tenant_id, actor_user_id=actor, ip=None)
    assert fake.cancelled == [{"customer_id": "cust_flow", "token_id": token_id, "method": "card"}]
    assert state.mandate_status == "cancelled" and state.enabled is False
    assert await _audits(tenant_id, "auto_recharge.mandate_cancelled") == 1


# --- the sweep ----------------------------------------------------------------------------


async def test_only_enabled_tenants_are_due() -> None:
    on, off = await _tenant(), await _tenant()
    await _mandate(on, enabled=True)
    await _mandate(off, enabled=False)
    due = await auto_recharge.due_tenants()
    assert on in due and off not in due


async def test_a_recharge_whose_approver_left_fails_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _mandate(tenant_id, enabled=True, payer=None)

    def _no_provider() -> Any:
        raise AssertionError("no provider call without an approver")

    monkeypatch.setattr(auto_recharge, "razorpay_api", _no_provider)
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "failed"
    code = await _scalar(
        tenant_id, "SELECT failure_code FROM auto_recharge_charges WHERE tenant_id = :t"
    )
    assert code == "auto_recharge_needs_contact"
    assert await _notices(tenant_id, "recharge_failed") == 1


async def _pending_charge(tenant_id: UUID, *, age: timedelta = timedelta()) -> tuple[UUID, str]:
    charge_id, order_id = uuid.uuid4(), _id("order")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO auto_recharge_charges (id, tenant_id, order_id, amount_inr, status, "
                "created_at) VALUES (:id, :t, :o, 2000, 'pending', :at)"
            ),
            {"id": charge_id, "t": tenant_id, "o": order_id, "at": datetime.now(UTC) - age},
        )
    return charge_id, order_id


async def test_a_charge_failed_twice_is_counted_once() -> None:
    tenant_id = await _tenant()
    await _mandate(tenant_id, enabled=True)
    charge_id, _ = await _pending_charge(tenant_id)
    for _ in range(2):
        async with tenant_session(tenant_id) as session:
            await auto_recharge._fail_charge(
                session, tenant_id=tenant_id, charge_id=charge_id, code=None
            )
    failures = await _scalar(
        tenant_id, "SELECT consecutive_failures FROM auto_recharge_settings WHERE tenant_id = :t"
    )
    assert failures == 1
    assert await _notices(tenant_id, "recharge_failed") == 1
    code = await _scalar(
        tenant_id, "SELECT failure_code FROM auto_recharge_charges WHERE id = :c", c=charge_id
    )
    assert code == "unknown"


async def test_settling_an_unknown_order_does_nothing_and_a_failed_one_fails_the_charge() -> None:
    tenant_id = await _tenant()
    await _mandate(tenant_id, enabled=True)
    charge_id, order_id = await _pending_charge(tenant_id)
    async with tenant_session(tenant_id) as session:
        await auto_recharge.settle_charge(
            session, tenant_id=tenant_id, order_id="order_nobody", payment_id=None, captured=True
        )
    assert await _notices(tenant_id, "recharge_captured") == 0
    async with tenant_session(tenant_id) as session:
        await auto_recharge.settle_charge(
            session,
            tenant_id=tenant_id,
            order_id=order_id,
            payment_id="pay_x",
            captured=False,
            failure_code="BAD_REQUEST_ERROR",
        )
    row = await _scalar(
        tenant_id,
        "SELECT status || ':' || failure_code FROM auto_recharge_charges WHERE id = :c",
        c=charge_id,
    )
    assert row == "failed:BAD_REQUEST_ERROR"
    assert await _notices(tenant_id, "recharge_failed") == 1


async def test_a_charge_left_unanswered_past_the_window_is_failed() -> None:
    tenant_id = await _tenant()
    await _mandate(tenant_id, enabled=True)
    old_id, _ = await _pending_charge(tenant_id, age=auto_recharge.CHARGE_ANSWER_WINDOW * 2)
    assert await auto_recharge.expire_unanswered(tenant_id) == 1
    assert await auto_recharge.expire_unanswered(tenant_id) == 0
    code = await _scalar(
        tenant_id, "SELECT failure_code FROM auto_recharge_charges WHERE id = :c", c=old_id
    )
    assert code == "no_answer"

    _fresh_id, _ = await _pending_charge(tenant_id)
    assert await auto_recharge.expire_unanswered(tenant_id) == 0


async def test_a_pending_mandate_is_refreshed_from_the_providers_token_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    token_id = await _mandate(tenant_id, status="pending")
    assert (tenant_id, "cust_flow", token_id) in await auto_recharge.pending_mandates()
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)

    for unchanged in (None, "initiated"):
        fake.token_state = unchanged
        assert await auto_recharge.refresh_pending_mandate(tenant_id, "cust_flow", token_id) == (
            unchanged
        )
    sql = "SELECT mandate_status FROM auto_recharge_settings WHERE tenant_id = :t"
    assert await _scalar(tenant_id, sql) == "pending"

    fake.token_state = "confirmed"
    assert await auto_recharge.refresh_pending_mandate(tenant_id, "cust_flow", token_id) == (
        "confirmed"
    )
    assert await _scalar(tenant_id, sql) == "confirmed"
    assert (tenant_id, "cust_flow", token_id) not in await auto_recharge.pending_mandates()


# --- the client routes ----------------------------------------------------------------------


def _principal(tenant_id: UUID, user_id: UUID | None = None) -> Principal:
    return Principal(
        realm="client",
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/v1/billing/auto-recharge",
            "headers": [],
            "query_string": b"",
            "client": ("203.0.113.7", 1234),
        }
    )


def test_money_never_crosses_the_wire_as_a_float() -> None:
    with pytest.raises(ValidationError, match="never as a float"):
        auto_recharge_routes.AutoRechargeIn.model_validate(
            {
                "enabled": False,
                "threshold_inr": 500.0,
                "amount_inr": "2000.00",
                "monthly_cap_inr": "6000.00",
            }
        )
    parsed = auto_recharge_routes.MandateIn.model_validate(
        {"method": "upi", "max_debit_inr": "2000.00"}
    )
    assert parsed.max_debit_inr == Decimal("2000.00")


async def test_the_routes_read_save_start_confirm_withdraw_and_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    user_id = await _member(tenant_id)
    principal = _principal(tenant_id, user_id)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)

    read = await auto_recharge_routes.read_settings(principal)
    assert read.mandate_status == "none" and read.mandate_method is None
    assert read.max_debit_inr == Decimal("15000.00")

    saved = await auto_recharge_routes.save_settings(
        auto_recharge_routes.AutoRechargeIn(
            enabled=False,
            threshold_inr=Decimal("600.00"),
            amount_inr=Decimal("2000.00"),
            monthly_cap_inr=Decimal("6000.00"),
        ),
        _request(),
        principal,
    )
    assert saved.threshold_inr == Decimal("600.00") and saved.enabled is False

    started = await auto_recharge_routes.start_mandate(
        auto_recharge_routes.MandateIn(method="upi", max_debit_inr=Decimal("2000.00")),
        _request(),
        principal,
    )
    assert started.key_id == KEY_ID and started.amount_paise == 100

    payment_id = _id("pay")
    fake.token_id = _id("token")
    confirmed = await auto_recharge_routes.confirm(
        auto_recharge_routes.MandateConfirmIn(
            razorpay_order_id=started.order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=_sign(started.order_id, payment_id),
        ),
        principal,
    )
    assert confirmed.mandate_method == "upi" and confirmed.mandate_status == "pending"

    await _pending_charge(tenant_id)
    charges = await auto_recharge_routes.read_charges(principal, limit=10)
    assert [(c.status, c.amount_inr) for c in charges] == [("pending", Decimal("2000.00"))]

    withdrawn = await auto_recharge_routes.withdraw(_request(), principal)
    assert withdrawn.mandate_status == "cancelled"
    assert fake.cancelled[0]["token_id"] == fake.token_id
