"""Razorpay end to end (D-699): mode guard, our order record, event-id dedupe, payment
states, refund failure, disputes, mandates, auto-recharge, reconciliation, the refund
ceiling on unspent credit and the forfeiture shown on closure.

Every wire shape exercised here is the one Razorpay documents (cited in the modules). No
test reaches Razorpay: the webhook goes through a local ASGI app and the adapter through
`httpx.MockTransport` or a fake.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import auto_recharge, payments, reconciliation
from apps.api.billing.dispute_hold import dispute_hold_active
from apps.api.billing.disputes import DisputeFacts, apply_dispute_event
from apps.api.billing.payment_objects import record_route, route_for
from apps.api.billing.payment_routes import unspent_credit_of_payment, webhook_router
from apps.api.billing.razorpay_api import (
    MANDATE_MAX_DEBIT_INR,
    ProviderPayment,
    ProviderRefundRow,
    RazorpayApi,
)
from apps.api.billing.service import get_balance, remove_credit_from_lots
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

WEBHOOK_SECRET = "whsec_e2e_test"
KEY_ID = "rzp_test_e2e"
KEY_SECRET = "rzp_secret_e2e"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(settings, "razorpay_mode", None)


def _client() -> AsyncClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(webhook_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _sign(body: dict[str, Any], *, event_id: str | None = None) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = {
        payments.SIGNATURE_HEADER: hmac.new(
            WEBHOOK_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    if event_id:
        headers[payments.EVENT_ID_HEADER] = event_id
    return raw, headers


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="E2E Clinic",
        slug=f"e2e-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _ledger(tenant_id: UUID) -> list[tuple[str, Decimal, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref FROM credit_ledger WHERE tenant_id = :t "
                    "ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), r[2]) for r in rows]


def _payment(
    *,
    payment_id: str,
    order_id: str,
    amount: int,
    notes: Any,
    event: str = "payment.captured",
    status: str = "captured",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity = {
        "id": payment_id,
        "entity": "payment",
        "amount": amount,
        "currency": "INR",
        "status": status,
        "order_id": order_id,
        "international": False,
        "notes": notes,
        **(extra or {}),
    }
    return {"entity": "event", "event": event, "payload": {"payment": {"entity": entity}}}


async def _fund(tenant_id: UUID, payment_id: str, amount: str) -> None:
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount),
                currency="INR",
            ),
        )


# --- the mode guard ------------------------------------------------------------------


def test_a_key_from_the_other_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_mode", "live")
    assert payments.payment_mode_problem() == payments.MODE_MISMATCH_REASON
    capability = payments.payment_capability()
    assert capability.available is False
    assert capability.reason == payments.MODE_MISMATCH_REASON


def test_production_refuses_test_mode_and_an_unset_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "razorpay_mode", "test")
    assert payments.payment_mode_problem() == payments.TEST_MODE_IN_PRODUCTION_REASON
    monkeypatch.setattr(settings, "razorpay_mode", None)
    assert payments.payment_mode_problem() == payments.TEST_MODE_IN_PRODUCTION_REASON
    monkeypatch.setattr(settings, "razorpay_mode", "live")
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_live_e2e")
    assert payments.payment_mode_problem() is None


def test_matching_test_mode_is_usable_off_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "razorpay_mode", "test")
    assert payments.payment_mode_problem() is None
    assert payments.payment_capability().available is True


def test_the_dashboard_event_list_covers_every_handled_event() -> None:
    events = set(payments.SUBSCRIBED_EVENTS)
    assert events >= payments.CREDIT_EVENTS
    assert events >= payments.TOKEN_EVENTS
    assert events >= payments.DISPUTE_EVENTS
    assert {"payment.authorized", "payment.failed", "refund.processed", "refund.failed"} <= events


# --- extraction ----------------------------------------------------------------------


def test_empty_notes_arrive_as_an_array_and_the_order_notes_carry_the_tenant() -> None:
    tenant_id = uuid.uuid4()
    envelope = _payment(payment_id="pay_A", order_id="order_A", amount=10000, notes=[])
    envelope["event"] = "order.paid"
    envelope["payload"]["order"] = {
        "entity": {"id": "order_A", "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)}}
    }
    payment = payments.extract_captured_payment(envelope)
    assert payment.tenant_id == tenant_id
    assert payment.order_id == "order_A"
    assert payment.amount_inr == Decimal("100")


def test_the_tenant_hint_from_our_order_record_is_used_when_no_notes_name_one() -> None:
    tenant_id = uuid.uuid4()
    envelope = _payment(payment_id="pay_B", order_id="order_B", amount=10000, notes=[])
    with pytest.raises(ProblemError) as refused:
        payments.extract_captured_payment(envelope)
    assert refused.value.code == "payment_tenant_unresolved"
    assert payments.extract_captured_payment(envelope, tenant_hint=tenant_id).tenant_id == tenant_id


# --- our order record ----------------------------------------------------------------


async def test_a_payment_that_disagrees_with_our_order_amount_credits_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = await _tenant()
    order_id, payment_id = _id("order"), _id("pay")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose="topup",
            amount_inr=Decimal("500.00"),
        )
    raw, headers = _sign(
        _payment(
            payment_id=payment_id,
            order_id=order_id,
            amount=5000,
            notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
        )
    )
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("payment_order_mismatch")
    assert await _ledger(tenant_id) == []
    assert any(r.__dict__.get("code") == "razorpay_money_unapplied" for r in caplog.records)


async def test_a_payment_with_no_notes_is_credited_to_the_tenant_of_our_order() -> None:
    tenant_id = await _tenant()
    order_id, payment_id = _id("order"), _id("pay")
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose="topup",
            amount_inr=Decimal("250.00"),
        )
    route = await route_for(order_id)
    assert route is not None and route.tenant_id == tenant_id and route.amount_paise == 25000
    raw, headers = _sign(_payment(payment_id=payment_id, order_id=order_id, amount=25000, notes=[]))
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "credited"
    assert await _ledger(tenant_id) == [("topup", Decimal("250.0000"), payment_id)]


async def test_one_event_id_delivered_twice_is_one_event() -> None:
    tenant_id = await _tenant()
    payment_id, event_id = _id("pay"), _id("evt")
    body = _payment(
        payment_id=payment_id,
        order_id=_id("order"),
        amount=10000,
        notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
    )
    raw, headers = _sign(body, event_id=event_id)
    async with _client() as http:
        first = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        second = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert first.json()["status"] == "credited"
    assert second.json()["status"] == "duplicate"
    assert len(await _ledger(tenant_id)) == 1


async def test_payment_authorized_moves_the_attempt_to_verifying_and_credits_nothing() -> None:
    from apps.api.billing.wallet import record_attempt

    tenant_id = await _tenant()
    order_id = _id("order")
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt=_id("clv"),
            amount_inr=Decimal("100.00"),
            provider_order_id=order_id,
            pack_id=None,
        )
    raw, headers = _sign(
        _payment(
            payment_id=_id("pay"),
            order_id=order_id,
            amount=10000,
            notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
            event="payment.authorized",
            status="authorized",
        )
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "authorized"
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM topup_attempts WHERE provider_order_id = :o"),
                {"o": order_id},
            )
        ).scalar()
    assert status == "authorized"
    assert await _ledger(tenant_id) == []


async def test_an_international_payment_is_credited_and_alarmed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = await _tenant()
    raw, headers = _sign(
        _payment(
            payment_id=_id("pay"),
            order_id=_id("order"),
            amount=10000,
            notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
            extra={"international": True},
        )
    )
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "credited"
    assert any(r.__dict__.get("code") == "razorpay_international_payment" for r in caplog.records)


# --- refunds -------------------------------------------------------------------------


async def test_refund_failed_releases_the_claim_and_moves_no_money(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        claim = await payments.claim_refund(
            session,
            tenant_id=tenant_id,
            payment_id=payment_id,
            amount_inr=Decimal("400.00"),
            payment_total_inr=Decimal("1000.00"),
        )
    assert claim.claimed
    body = {
        "event": "refund.failed",
        "payload": {
            "refund": {
                "entity": {
                    "id": _id("rfnd"),
                    "payment_id": payment_id,
                    "amount": 40000,
                    "currency": "INR",
                    "status": "failed",
                    "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                }
            }
        },
    }
    raw, headers = _sign(body)
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "refund_failed"
    async with tenant_session(tenant_id) as session:
        left = await payments.claimed_refund_total_inr(
            session, tenant_id=tenant_id, payment_id=payment_id
        )
    assert left == Decimal("0")
    assert [r[0] for r in await _ledger(tenant_id)] == ["topup"]
    assert any(r.__dict__.get("code") == "razorpay_refund_failed" for r in caplog.records)


async def test_a_409_from_the_refund_api_is_in_progress_and_keeps_the_claim() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "BAD_REQUEST_ERROR"}})

    api = payments.RazorpayOrders(
        key_id=KEY_ID,
        key_secret=KEY_SECRET,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://api.razorpay.com"
        ),
    )
    with pytest.raises(ProblemError) as raised:
        await api.create_refund(
            payment_id="pay_x", amount_inr=Decimal("10.00"), notes={}, idempotency_key="rfnd_" * 3
        )
    assert raised.value.code == "refund_in_progress"
    assert "refund_in_progress" in payments.REFUND_MAY_HAVE_MOVED_CODES


async def test_the_refundable_amount_is_the_unspent_credit_of_that_payment() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        entry = await payments.find_topup(session, tenant_id=tenant_id, ref=payment_id)
        assert entry is not None
        assert await unspent_credit_of_payment(
            session, tenant_id=tenant_id, payment_id=payment_id, entry_id=entry.entry_id
        ) == Decimal("1000.00")
        await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=None, amount_inr=Decimal("300.00")
        )
        assert await unspent_credit_of_payment(
            session, tenant_id=tenant_id, payment_id=payment_id, entry_id=entry.entry_id
        ) == Decimal("700.00")


# --- disputes ------------------------------------------------------------------------


def _dispute(payment_id: str, status: str, amount: int = 40000) -> DisputeFacts:
    return DisputeFacts(
        dispute_id=f"disp_{payment_id}",
        payment_id=payment_id,
        amount_inr=Decimal(amount) / 100,
        status=status,
        phase="chargeback",
        reason_code="chargeback",
        respond_by=datetime.now(UTC) + timedelta(days=7),
    )


async def test_a_dispute_holds_the_credit_pauses_outbound_and_a_win_releases_it() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        outcome = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_dispute(payment_id, "open"),
        )
        assert outcome == "held"
        assert await dispute_hold_active(session, tenant_id=tenant_id)
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("600")
    async with tenant_session(tenant_id) as session:
        again = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.under_review",
            dispute=_dispute(payment_id, "under_review"),
        )
        assert again == "recorded", "the hold is placed once"
    async with tenant_session(tenant_id) as session:
        won = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.won",
            dispute=_dispute(payment_id, "won"),
        )
        assert won == "released"
        assert not await dispute_hold_active(session, tenant_id=tenant_id)
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("1000")
    reasons = [(r[0], r[1]) for r in await _ledger(tenant_id)]
    assert reasons == [
        ("topup", Decimal("1000.0000")),
        ("adjustment", Decimal("-400.0000")),
        ("adjustment", Decimal("400.0000")),
    ]


async def test_a_lost_dispute_keeps_the_hold() -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.created",
            dispute=_dispute(payment_id, "open"),
        )
    async with tenant_session(tenant_id) as session:
        lost = await apply_dispute_event(
            session,
            tenant_id=tenant_id,
            event="payment.dispute.lost",
            dispute=_dispute(payment_id, "lost"),
        )
        assert lost == "recorded"
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("600")
        assert not await dispute_hold_active(session, tenant_id=tenant_id)


async def test_the_dispute_webhook_resolves_the_tenant_and_alarms(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = await _tenant()
    payment_id = _id("pay")
    await _fund(tenant_id, payment_id, "1000.00")
    body = _payment(
        payment_id=payment_id,
        order_id=_id("order"),
        amount=100000,
        notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
        event="payment.dispute.created",
    )
    body["payload"]["dispute"] = {
        "entity": {
            "id": f"disp_{payment_id}",
            "payment_id": payment_id,
            "amount": 39000,
            "currency": "INR",
            "status": "open",
            "phase": "chargeback",
            "respond_by": 1890000000,
        }
    }
    raw, headers = _sign(body)
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "dispute"
    assert any(r.__dict__.get("code") == "payment_dispute_opened" for r in caplog.records)
    async with tenant_session(tenant_id) as session:
        assert await dispute_hold_active(session, tenant_id=tenant_id)


# --- mandates and auto-recharge ------------------------------------------------------


async def _member_with_phone(tenant_id: UUID) -> UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, phone, created_at, updated_at) "
                "VALUES (:id, :email, '+919900000000', now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
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


async def _confirmed_mandate(tenant_id: UUID, *, enabled: bool = True) -> str:
    user_id = await _member_with_phone(tenant_id)
    token_id = _id("token")
    async with tenant_session(tenant_id) as session:
        await record_route(session, tenant_id=tenant_id, object_id=token_id, kind="token")
        await session.execute(
            text(
                "INSERT INTO auto_recharge_settings (id, tenant_id, enabled, threshold_inr, "
                "amount_inr, monthly_cap_inr, customer_id, token_id, mandate_method, "
                "mandate_status, mandate_max_inr, authorised_by) VALUES (:id, :tid, :en, 500, "
                "2000, 4000, 'cust_e2e', :tok, 'upi', 'confirmed', 2000, :uid)"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "en": enabled, "tok": token_id, "uid": user_id},
        )
    return token_id


@dataclass
class FakeApi:
    orders: list[dict[str, Any]] = field(default_factory=list)
    recurring: list[dict[str, Any]] = field(default_factory=list)
    fail_recurring: bool = False
    payments: list[ProviderPayment] = field(default_factory=list)
    refunds: list[ProviderRefundRow] = field(default_factory=list)

    async def create_charge_order(self, **kwargs: Any) -> str:
        order_id = _id("order")
        self.orders.append({"id": order_id, **kwargs})
        return order_id

    async def create_recurring_payment(self, **kwargs: Any) -> str:
        if self.fail_recurring:
            raise ProblemError(
                kind="dependency",
                code="payment_provider_rejected",
                title="x",
                detail="x",
                remediation="x",
            )
        self.recurring.append(kwargs)
        return _id("pay")

    async def list_payments(self, **_: Any) -> list[ProviderPayment]:
        return self.payments

    async def list_refunds(self, **_: Any) -> list[ProviderRefundRow]:
        return self.refunds

    async def list_settlements(self, **_: Any) -> list[Any]:
        return []


async def test_auto_recharge_cannot_be_switched_on_without_a_confirmed_mandate() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await auto_recharge.save_auto_recharge(
                session,
                tenant_id=tenant_id,
                enabled=True,
                threshold_inr=Decimal("500.00"),
                amount_inr=Decimal("2000.00"),
                monthly_cap_inr=Decimal("6000.00"),
                actor_user_id=None,
            )
    assert refused.value.code == "auto_recharge_needs_mandate"


async def test_a_recharge_above_the_unattended_limit_is_refused() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await auto_recharge.save_auto_recharge(
                session,
                tenant_id=tenant_id,
                enabled=False,
                threshold_inr=Decimal("500.00"),
                amount_inr=MANDATE_MAX_DEBIT_INR + 1,
                monthly_cap_inr=Decimal("90000.00"),
                actor_user_id=None,
            )
    assert refused.value.code == "auto_recharge_invalid"


async def test_one_recharge_in_flight_then_capture_credits_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _confirmed_mandate(tenant_id)
    fake = FakeApi()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)

    assert await auto_recharge.maybe_start_recharge(tenant_id) == "started"
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "in_flight"
    assert len(fake.recurring) == 1
    assert fake.recurring[0]["token_id"].startswith("token_")
    assert fake.recurring[0]["amount_inr"] == Decimal("2000.0000")

    order_id = fake.orders[0]["id"]
    payment_id = _id("pay")
    raw, headers = _sign(
        _payment(
            payment_id=payment_id,
            order_id=order_id,
            amount=200000,
            notes={payments.NOTES_TENANT_KEY: str(tenant_id)},
        )
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "credited"
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM auto_recharge_charges WHERE order_id = :o"),
                {"o": order_id},
            )
        ).scalar()
    assert status == "captured"
    # The wallet is now above the threshold.
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "above_threshold"


async def test_the_monthly_cap_is_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant()
    await _confirmed_mandate(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO auto_recharge_charges (id, tenant_id, order_id, amount_inr, status, "
                "settled_at) VALUES (:id, :tid, :o, 3000, 'captured', now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "o": _id("order")},
        )
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: FakeApi())
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "monthly_cap_reached"


async def test_repeated_failures_switch_auto_recharge_off(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant()
    await _confirmed_mandate(tenant_id)
    monkeypatch.setattr(get_settings(), "auto_recharge_max_failures", 2)
    fake = FakeApi(fail_recurring=True)
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "failed"
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "failed"
    assert await auto_recharge.maybe_start_recharge(tenant_id) == "off"
    async with tenant_session(tenant_id) as session:
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
        notices = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :j "
                    "AND payload->>'tenant_id' = :t AND payload->>'kind' = 'auto_recharge_disabled'"
                ),
                {"j": auto_recharge.PAYMENT_NOTICE_JOB, "t": str(tenant_id)},
            )
        ).scalar()
    assert state.enabled is False
    assert state.disabled_reason is not None
    assert notices == 1


async def test_token_events_move_the_mandate_and_a_cancel_switches_it_off() -> None:
    tenant_id = await _tenant()
    token_id = await _confirmed_mandate(tenant_id)
    body = {
        "event": "token.cancelled",
        "payload": {
            "token": {"entity": {"id": token_id, "recurring_details": {"status": "cancelled"}}}
        },
    }
    raw, headers = _sign(body)
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "mandate"
    async with tenant_session(tenant_id) as session:
        state = await auto_recharge.read_auto_recharge(session, tenant_id=tenant_id)
    assert state.mandate_status == "cancelled"
    assert state.enabled is False


async def test_the_mandate_order_asks_for_a_capped_as_presented_token() -> None:
    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "order_mandate"})

    api = RazorpayApi(
        key_id=KEY_ID,
        key_secret=KEY_SECRET,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://api.razorpay.com"
        ),
    )
    order_id = await api.create_mandate_order(
        customer_id="cust_1",
        method="upi",
        max_debit_inr=Decimal("2000.00"),
        expire_at=2_000_000_000,
        receipt="clvm_1",
        notes={},
    )
    assert order_id == "order_mandate"
    assert seen[0]["token"] == {
        "max_amount": 200000,
        "expire_at": 2_000_000_000,
        "frequency": "as_presented",
    }
    assert seen[0]["method"] == "upi" and seen[0]["customer_id"] == "cust_1"
    with pytest.raises(ProblemError):
        await api.create_mandate_order(
            customer_id="cust_1",
            method="card",
            max_debit_inr=Decimal("15000.01"),
            expire_at=2_000_000_000,
            receipt="clvm_2",
            notes={},
        )


async def test_the_recurring_payment_answer_is_read_from_razorpay_payment_id() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/payments/create/recurring"
        assert body["recurring"] is True and body["token"] == "token_1"
        return httpx.Response(200, json={"razorpay_payment_id": "pay_rec"})

    api = RazorpayApi(
        key_id=KEY_ID,
        key_secret=KEY_SECRET,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://api.razorpay.com"
        ),
    )
    assert (
        await api.create_recurring_payment(
            email="a@example.com",
            contact="+919900000000",
            amount_inr=Decimal("100.00"),
            order_id="order_1",
            customer_id="cust_1",
            token_id="token_1",
            notes={},
        )
        == "pay_rec"
    )


# --- reconciliation ------------------------------------------------------------------


async def test_reconciliation_credits_a_lost_webhook_and_flags_the_unexplained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    lost = _id("pay")
    stray = _id("pay")
    now = int(datetime.now(UTC).timestamp())

    def _p(pid: str, notes: dict[str, str]) -> ProviderPayment:
        return ProviderPayment(
            payment_id=pid,
            status="captured",
            amount_paise=15000,
            currency="INR",
            order_id=None,
            method="upi",
            international=False,
            token_id=None,
            customer_id=None,
            notes=notes,
            error_code=None,
            created_at=now,
        )

    fake = FakeApi(payments=[_p(lost, {payments.NOTES_TENANT_KEY: str(tenant_id)}), _p(stray, {})])
    monkeypatch.setattr(reconciliation, "razorpay_api", lambda: fake)
    report = await reconciliation.reconcile()
    assert lost in report.credited_late
    assert f"unattributed:{stray}" in report.unexplained
    assert await _ledger(tenant_id) == [("topup", Decimal("150.0000"), lost)]
    again = await reconciliation.reconcile()
    assert again.credited_late == [], "a second pass finds it on the ledger"


# --- closure -------------------------------------------------------------------------


async def test_the_closure_screen_shows_the_credit_that_would_be_forfeited() -> None:
    from apps.api.admin.closure_routes import _forfeitable

    tenant_id = await _tenant()
    await _fund(tenant_id, _id("pay"), "750.00")
    async with tenant_session(tenant_id) as session:
        assert await _forfeitable(session, tenant_id) == Decimal("750.00")
