"""Razorpay wire hardening (this slice): the callback signature, the extra webhook events
(order.paid / payment.failed / refund.processed), and the refund flow end to end.

The verified facts these exercise (razorpay.com is egress-blocked here; WebSearch 2026-08-24
corroborated each across independent secondaries — see `billing/payments.py`):

* the CALLBACK signature is `HMAC-SHA256(order_id + "|" + payment_id)` keyed with the
  KEY SECRET, a different scheme and secret from the webhook (which keys HMAC-SHA256 of the
  raw body with the WEBHOOK SECRET under `X-Razorpay-Signature`);
* `order.paid` carries `payload.payment.entity` and means the same "money arrived" as
  `payment.captured`, deduped on the same payment id;
* `refund.processed` carries `payload.refund.entity.{id,payment_id,amount,notes,...}`, amount
  in integer paise, and is recorded as a compensating (negative) ledger entry;
* the refund API is `POST /v1/payments/{id}/refund`, amount in paise, `speed`, and an
  `X-Refund-Idempotency` header.

No test here reaches the real API: the webhook goes through a local ASGI app, and the
order/refund adapter through `httpx.MockTransport`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.credit_packs import pack_by_id
from apps.api.billing.payment_routes import (
    CheckoutCallbackIn,
    RefundIn,
    confirm_topup_callback,
    issue_tenant_refund,
    webhook_router,
)
from apps.api.billing.payments import RazorpayOrders
from apps.api.billing.service import get_balance
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

WEBHOOK_SECRET = "whsec_razorpay_events_test"
KEY_ID = "rzp_test_events"
KEY_SECRET = "rzp_secret_events"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that can verify webhooks AND create orders/refunds (all four values)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(webhook_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _sign(body: dict[str, Any], secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {payments.SIGNATURE_HEADER: signature, "Content-Type": "application/json"}


def _payment_id(tag: str) -> str:
    return f"pay_{tag}_{uuid.uuid4().hex[:12]}"


def _refund_id(tag: str) -> str:
    return f"rfnd_{tag}_{uuid.uuid4().hex[:12]}"


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Refund Clinic",
        slug=f"rf-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    return tenant_id


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


async def _fund(tenant_id: UUID, *, payment_id: str, amount_inr: str) -> None:
    """Put a real top-up on the wallet so a refund has something to compensate."""
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal(amount_inr),
        currency="INR",
    )
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(session, payment=payment)


def _payment_envelope(
    *, payment_id: str, tenant_id: UUID | None, amount: Any = 250000, event: str = "order.paid"
) -> dict[str, Any]:
    notes = {} if tenant_id is None else {payments.NOTES_TENANT_KEY: str(tenant_id)}
    entity = {
        "id": payment_id,
        "order_id": "order_x",
        "amount": amount,
        "currency": "INR",
        "status": "captured",
        "notes": notes,
    }
    return {"event": event, "payload": {"payment": {"entity": entity}}}


def _refund_envelope(
    *,
    refund_id: str,
    payment_id: str,
    tenant_id: UUID | None,
    amount: Any = 250000,
    status: str = "processed",
) -> dict[str, Any]:
    notes = {} if tenant_id is None else {payments.NOTES_TENANT_KEY: str(tenant_id)}
    entity = {
        "id": refund_id,
        "payment_id": payment_id,
        "amount": amount,
        "currency": "INR",
        "status": status,
        "notes": notes,
    }
    return {"event": "refund.processed", "payload": {"refund": {"entity": entity}}}


# ============================================================================
# The callback signature (order_id|payment_id, key_secret) — a UNIT
# ============================================================================


def _checkout_signature(order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
    return hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def test_the_checkout_signature_verifies_the_order_pipe_payment_with_the_key_secret() -> None:
    sig = _checkout_signature("order_9", "pay_9")
    assert payments.verify_checkout_signature(
        key_secret=KEY_SECRET, order_id="order_9", payment_id="pay_9", signature=sig
    )
    # Reversed concatenation, missing pipe, wrong secret, absent signature: all rejected.
    assert not payments.verify_checkout_signature(
        key_secret=KEY_SECRET,
        order_id="pay_9",
        payment_id="order_9",
        signature=sig,
    )
    assert not payments.verify_checkout_signature(
        key_secret="rzp_secret_other", order_id="order_9", payment_id="pay_9", signature=sig
    )
    assert not payments.verify_checkout_signature(
        key_secret=KEY_SECRET, order_id="order_9", payment_id="pay_9", signature=None
    )


async def test_the_callback_route_accepts_a_genuine_signature_but_credits_nothing() -> None:
    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=await _tenant(),
        role="owner",
        impersonating=False,
    )
    sig = _checkout_signature("order_cb", "pay_cb")
    out = await confirm_topup_callback(
        CheckoutCallbackIn(
            razorpay_order_id="order_cb", razorpay_payment_id="pay_cb", razorpay_signature=sig
        ),
        principal,
    )
    assert out.verified is True
    assert out.payment_id == "pay_cb"
    assert out.credit_pending is True, "the webhook, not the callback, moves the money"
    assert await _ledger(principal.tenant_id) == [], "the callback writes no ledger row"


async def test_the_callback_route_rejects_a_forged_signature() -> None:
    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=await _tenant(),
        role="owner",
        impersonating=False,
    )
    with pytest.raises(ProblemError) as raised:
        await confirm_topup_callback(
            CheckoutCallbackIn(
                razorpay_order_id="order_cb",
                razorpay_payment_id="pay_cb",
                razorpay_signature="deadbeef",
            ),
            principal,
        )
    assert raised.value.code == "payment_signature_invalid"


# ============================================================================
# order.paid — credits like payment.captured, deduped on the payment id
# ============================================================================


async def test_order_paid_credits_the_wallet() -> None:
    tenant_id = await _tenant()
    raw, headers = _sign(_payment_envelope(payment_id=_payment_id("OP"), tenant_id=tenant_id))
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "credited"
    assert body["amount_inr"] == "2500.00"
    entries = await _ledger(tenant_id)
    assert [(r[0], r[1]) for r in entries] == [("topup", Decimal("2500.0000"))]


async def test_payment_captured_then_order_paid_for_one_payment_credits_once() -> None:
    """Both events carry the same payment id; the ledger ref collapses them to one row."""
    tenant_id = await _tenant()
    pid = _payment_id("BOTH")
    captured_raw, captured_headers = _sign(
        _payment_envelope(payment_id=pid, tenant_id=tenant_id, event="payment.captured")
    )
    paid_raw, paid_headers = _sign(
        _payment_envelope(payment_id=pid, tenant_id=tenant_id, event="order.paid")
    )
    async with _client() as http:
        first = await http.post(
            "/hooks/v1/razorpay", content=captured_raw, headers=captured_headers
        )
        second = await http.post("/hooks/v1/razorpay", content=paid_raw, headers=paid_headers)
    assert first.json()["status"] == "credited"
    assert second.json()["status"] == "duplicate", "one payment, one credit, across two events"
    assert len([r for r in await _ledger(tenant_id) if r[0] == "topup"]) == 1


# ============================================================================
# The alarm on money that verified and did not land
# ============================================================================


def _route_alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The codes the alert path wrote on this route. `alert()` emits ONE
    `log.error("alert", ...)` per firing and the CODE is the contract — the sentence
    beside it is prose an operator edits."""
    return [
        str(record.__dict__.get("code"))
        for record in caplog.records
        if record.message == "alert" and record.__dict__.get("failure_stage") == "ROUTE_HANDLER"
    ]


async def test_a_verified_payment_we_cannot_attribute_raises_an_alarm(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A payment taken OUTSIDE our checkout (a payment link, a dashboard payment) carries
    no `notes.calevate_tenant_id`. The signature verified, so the money is real — and
    before this alarm the only trace was a 4xx in an access log while the provider retried
    into the same wall and the client watched an unmoved balance."""
    raw, headers = _sign(_payment_envelope(payment_id=_payment_id("NONOTE"), tenant_id=None))
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("payment_tenant_unresolved")
    assert "razorpay_money_unapplied" in _route_alerts(caplog)


async def test_a_payload_shape_we_cannot_read_raises_the_same_alarm(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The FIRST live payment's most likely failure: our reading of their payload paths is
    wrong. It must be loud, because nothing else on this path is."""
    raw, headers = _sign({"event": "payment.captured", "payload": {"payment": {}}})
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 422, response.text
    assert "razorpay_money_unapplied" in _route_alerts(caplog)


async def test_an_unknown_tenant_alarms_once_and_not_twice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`razorpay_unknown_tenant` alerts where it is raised, with a sharper sentence than
    the general guard could carry, so the guard must not fire a second alarm for the one
    delivery."""
    raw, headers = _sign(_payment_envelope(payment_id=_payment_id("GHOST"), tenant_id=uuid.uuid4()))
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 404, response.text
    assert _route_alerts(caplog) == ["razorpay_unknown_tenant"]


async def test_a_credited_payment_raises_no_alarm(caplog: pytest.LogCaptureFixture) -> None:
    tenant_id = await _tenant()
    raw, headers = _sign(_payment_envelope(payment_id=_payment_id("QUIET"), tenant_id=tenant_id))
    with caplog.at_level("ERROR"):
        async with _client() as http:
            response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "credited"
    assert _route_alerts(caplog) == []


# ============================================================================
# payment.failed — acked, moves no money
# ============================================================================


async def test_payment_failed_is_acked_and_credits_nothing() -> None:
    tenant_id = await _tenant()
    envelope = _payment_envelope(
        payment_id=_payment_id("FAIL"), tenant_id=tenant_id, event="payment.failed"
    )
    envelope["payload"]["payment"]["entity"]["error_code"] = "BAD_REQUEST_ERROR"
    raw, headers = _sign(envelope)
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert await _ledger(tenant_id) == [], "a failed payment writes no ledger row"


# ============================================================================
# refund.processed — a compensating (negative) ledger entry, idempotent
# ============================================================================


async def test_refund_processed_debits_the_wallet_as_a_compensating_entry() -> None:
    tenant_id = await _tenant()
    pid = _payment_id("RF")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    rid = _refund_id("RF")
    raw, headers = _sign(_refund_envelope(refund_id=rid, payment_id=pid, tenant_id=tenant_id))
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "refunded"
    assert body["balance_inr"] == "0.00", "the refund took the top-up back off the wallet"
    entries = await _ledger(tenant_id)
    assert ("refund", Decimal("-2500.0000"), rid) in entries
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("0")


async def test_the_same_refund_delivered_twice_debits_once() -> None:
    tenant_id = await _tenant()
    pid = _payment_id("RFDUP")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    rid = _refund_id("RFDUP")
    raw, headers = _sign(_refund_envelope(refund_id=rid, payment_id=pid, tenant_id=tenant_id))
    async with _client() as http:
        first = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        replay = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert first.json()["status"] == "refunded"
    assert replay.json()["status"] == "duplicate"
    assert len([r for r in await _ledger(tenant_id) if r[0] == "refund"]) == 1


async def test_a_partial_refund_debits_only_that_much() -> None:
    tenant_id = await _tenant()
    pid = _payment_id("PART")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    rid = _refund_id("PART")
    raw, headers = _sign(
        _refund_envelope(refund_id=rid, payment_id=pid, tenant_id=tenant_id, amount=100000)
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "refunded"
    assert response.json()["balance_inr"] == "1500.00", "2500 minus a 1000 partial refund"


async def test_a_refund_without_tenant_notes_is_unattributable() -> None:
    raw, headers = _sign(
        _refund_envelope(refund_id=_refund_id("NOTEN"), payment_id="pay_x", tenant_id=None)
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 422
    assert response.json()["type"].endswith("/payment_tenant_unresolved")


async def test_a_refund_with_a_bad_signature_credits_nothing() -> None:
    tenant_id = await _tenant()
    raw, headers = _sign(
        _refund_envelope(refund_id=_refund_id("FORGE"), payment_id="p", tenant_id=tenant_id),
        secret="whsec_wrong",
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 401
    assert await _ledger(tenant_id) == []


# ============================================================================
# extract_refund — the payload contract, in one place
# ============================================================================


def test_extract_refund_reads_the_documented_shape() -> None:
    tenant = uuid.uuid4()
    event = payments.extract_refund(
        _refund_envelope(refund_id="rfnd_1", payment_id="pay_1", tenant_id=tenant, amount=99900)
    )
    assert event.refund_id == "rfnd_1"
    assert event.payment_id == "pay_1"
    assert event.tenant_id == tenant
    assert event.amount_inr == Decimal("999.00")


@pytest.mark.parametrize(
    "envelope",
    [
        {"event": "refund.processed", "payload": {}},
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "r"}}}},
    ],
)
def test_extract_refund_refuses_a_shape_it_cannot_read(envelope: dict[str, Any]) -> None:
    with pytest.raises(ProblemError) as raised:
        payments.extract_refund(envelope)
    assert raised.value.code in {"refund_payload_unrecognized", "payment_currency_unsupported"}


def test_a_float_refund_amount_is_refused_rather_than_rounded() -> None:
    with pytest.raises(ProblemError) as raised:
        payments.extract_refund(
            _refund_envelope(refund_id="r", payment_id="p", tenant_id=uuid.uuid4(), amount=99900.0)
        )
    assert raised.value.code == "payment_amount_unrecognized"


# ============================================================================
# The refund adapter — the request their docs describe, over MockTransport
# ============================================================================


def _refund_adapter(responder: Any) -> tuple[RazorpayOrders, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request)

    adapter = RazorpayOrders(
        key_id=KEY_ID,
        key_secret=KEY_SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url=payments.BASE_URL),
    )
    return adapter, seen


async def test_the_refund_request_is_the_shape_their_docs_describe() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"id": "rfnd_OK", "amount": body["amount"], "status": "processed"}
        )

    adapter, seen = _refund_adapter(responder)
    refund = await adapter.create_refund(
        payment_id="pay_42",
        amount_inr=Decimal("2500.10"),
        notes={payments.NOTES_TENANT_KEY: "t"},
        idempotency_key="rfnd_key_0123456789",
    )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.razorpay.com/v1/payments/pay_42/refund"
    assert request.headers[payments.REFUND_IDEMPOTENCY_HEADER] == "rfnd_key_0123456789"
    body = json.loads(request.content)
    assert body["amount"] == 250010, "integer paise, never a rupee float"
    assert body["speed"] == payments.REFUND_SPEED
    assert body["notes"][payments.NOTES_TENANT_KEY] == "t"
    assert refund.refund_id == "rfnd_OK"
    assert refund.amount_paise == 250010
    assert refund.is_processed is True


async def test_the_refund_idempotency_key_is_derived_and_fits_the_vendor_rule() -> None:
    a = payments.refund_idempotency_key(payment_id="pay_1", amount_inr=Decimal("2500"))
    b = payments.refund_idempotency_key(payment_id="pay_1", amount_inr=Decimal("2500.00"))
    assert a == b, "same refund derives one key regardless of digit form"
    assert len(a) >= 10 and a.replace("_", "").isalnum()
    other = payments.refund_idempotency_key(payment_id="pay_2", amount_inr=Decimal("2500"))
    assert other != a


@pytest.mark.parametrize(
    ("responder", "code"),
    [
        (
            lambda _r: httpx.Response(400, json={"error": {"description": "prose"}}),
            "refund_rejected",
        ),
        (lambda _r: httpx.Response(200, json={}), "refund_unreadable"),
        (
            lambda _r: httpx.Response(
                200, json={"id": "rfnd_X", "amount": 999, "status": "processed"}
            ),
            "refund_amount_mismatch",
        ),
    ],
    ids=["rejected", "unreadable", "amount-mismatch"],
)
async def test_a_bad_refund_answer_becomes_our_problem_code(responder: Any, code: str) -> None:
    adapter, _seen = _refund_adapter(responder)
    with pytest.raises(ProblemError) as raised:
        await adapter.create_refund(
            payment_id="pay_1",
            amount_inr=Decimal("500.00"),
            notes={},
            idempotency_key="rfnd_key_0123456789",
        )
    assert raised.value.code == code


# ============================================================================
# The refund route — provider call then compensating entry, idempotent
# ============================================================================


def _admin() -> Principal:
    return Principal(
        realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin", impersonating=False
    )


def _install_refund(monkeypatch: pytest.MonkeyPatch, responder: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def orders() -> RazorpayOrders:
        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return responder(request)

        return RazorpayOrders(
            key_id=KEY_ID,
            key_secret=KEY_SECRET,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(handle), base_url=payments.BASE_URL
            ),
        )

    # `issue_refund` lives in `payments` and calls `payments.razorpay_orders`, so the patch
    # must land there — patching `payment_routes.razorpay_orders` would miss it.
    monkeypatch.setattr(payments, "razorpay_orders", orders)
    return seen


def _refund_ok(refund_id: str = "rfnd_ROUTE", status: str = "processed") -> Any:
    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"id": refund_id, "amount": body["amount"], "status": status}
        )

    return responder


async def test_the_refund_route_records_a_processed_refund_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("ROUTE")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_ok())

    out = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="client asked"), _request(), _admin()
    )
    assert out.recorded is True
    assert out.amount_inr == Decimal("2500.00")
    assert out.balance_inr == Decimal("0.00")
    assert out.processing_days == payments.REFUND_PROCESSING_DAYS
    assert ("refund", Decimal("-2500.0000"), "rfnd_ROUTE") in await _ledger(tenant_id)


async def test_the_refund_route_is_idempotent_on_a_second_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("ROUTE2")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_ok(refund_id="rfnd_ONCE"))

    first = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="x"), _request(), _admin()
    )
    second = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="x"), _request(), _admin()
    )
    assert first.recorded is True
    assert second.recorded is False, "the same refund id credits the wallet only once"
    assert len([r for r in await _ledger(tenant_id) if r[0] == "refund"]) == 1


async def test_the_refund_route_refuses_more_than_the_payment_brought_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("OVER")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    seen = _install_refund(monkeypatch, _refund_ok())

    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("3000.00"), reason="x"),
            _request(),
            _admin(),
        )
    assert raised.value.code == "refund_exceeds_payment"
    assert seen == [], "a refusal must never reach the provider"


async def test_the_refund_route_404s_a_payment_with_no_top_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    seen = _install_refund(monkeypatch, _refund_ok())
    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id, RefundIn(payment_id="pay_unknown", reason="x"), _request(), _admin()
        )
    assert raised.value.code == "not_found"
    assert seen == []


async def test_a_pending_refund_waits_for_the_webhook_to_record_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-processed refund status means the money has not moved yet, so no ledger entry
    is written on the API response — the `refund.processed` webhook writes it later."""
    tenant_id = await _tenant()
    pid = _payment_id("PEND")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_ok(refund_id="rfnd_PEND", status="pending"))

    out = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="x"), _request(), _admin()
    )
    assert out.recorded is False
    assert out.balance_inr is None
    assert [r for r in await _ledger(tenant_id) if r[0] == "refund"] == []


async def test_without_the_api_secret_a_refund_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("NOSEC")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)

    def never(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("no refund may be attempted without the API secret")

    _install_refund(monkeypatch, never)
    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id, RefundIn(payment_id=pid, reason="x"), _request(), _admin()
        )
    assert raised.value.code == "payments_not_configured"
    assert [r for r in await _ledger(tenant_id) if r[0] == "refund"] == []


async def test_with_no_provider_at_all_issue_refund_refuses_before_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment with NO payment provider (not merely no API secret) cannot refund at
    all: `issue_refund` refuses on `capability.available` — a different arm and a different
    reason from the missing-secret degradation above (payments.py:1289-1290)."""
    tenant_id = await _tenant()
    monkeypatch.setattr(get_settings(), "payment_provider", None)

    def never(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("an unconfigured deployment must never reach the provider")

    _install_refund(monkeypatch, never)
    with pytest.raises(ProblemError) as raised:
        await payments.issue_refund(
            tenant_id=tenant_id, payment_id="pay_x", amount_inr=Decimal("100.00")
        )
    assert raised.value.code == "payments_not_configured"


# ============================================================================
# The callback route — degradation when a secret is missing (a UNIT each)
# ============================================================================


async def test_the_callback_refuses_when_no_provider_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No provider at all ⇒ the callback cannot be verified and refuses, rather than
    waving a browser-supplied "payment succeeded" through (payment_routes.py:479-480)."""
    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=await _tenant(),
        role="owner",
        impersonating=False,
    )
    monkeypatch.setattr(get_settings(), "payment_provider", None)
    with pytest.raises(ProblemError) as raised:
        await confirm_topup_callback(
            CheckoutCallbackIn(
                razorpay_order_id="order_cb",
                razorpay_payment_id="pay_cb",
                razorpay_signature="whatever",
            ),
            principal,
        )
    assert raised.value.code == "payments_not_configured"


async def test_the_callback_refuses_when_the_key_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider + key id + webhook secret present (so `capability.available` is True) but
    no KEY SECRET: there is no way to verify a callback, so it refuses rather than accepting
    an unverifiable success from the browser (payment_routes.py:481-485)."""
    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=await _tenant(),
        role="owner",
        impersonating=False,
    )
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)
    with pytest.raises(ProblemError) as raised:
        await confirm_topup_callback(
            CheckoutCallbackIn(
                razorpay_order_id="order_cb",
                razorpay_payment_id="pay_cb",
                razorpay_signature="whatever",
            ),
            principal,
        )
    assert raised.value.code == "payments_not_configured"


# ============================================================================
# refund.processed — an unknown tenant is real money we cannot attribute (404)
# ============================================================================


async def test_a_refund_for_an_unknown_tenant_404s_and_writes_nothing() -> None:
    """A valid-UUID tenant in the notes that names no organization is a 404, not a silent
    ack: the money is real and must reach a human, not nobody's wallet
    (payment_routes.py:656-658)."""
    ghost = uuid.uuid4()
    raw, headers = _sign(
        _refund_envelope(refund_id=_refund_id("GHOST"), payment_id="pay_g", tenant_id=ghost)
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 404
    assert response.json()["type"].endswith("/not_found")


# ============================================================================
# The refund route — money-shape edge cases (a UNIT each)
# ============================================================================


def test_a_float_refund_amount_is_refused_at_the_boundary() -> None:
    """`amount_inr` is Decimal-or-string on the wire; a float is refused by the validator
    before any handler runs (payment_routes.py:711-713)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        RefundIn(payment_id="pay_1", amount_inr=25.0, reason="x")  # type: ignore[arg-type]
    assert "float" in str(raised.value)


async def test_the_refund_route_refuses_a_non_positive_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero or negative refund amount is refused before the provider is called
    (payment_routes.py:772-773)."""
    tenant_id = await _tenant()
    pid = _payment_id("ZERO")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")

    def never(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("a non-positive refund must never reach the provider")

    seen = _install_refund(monkeypatch, never)
    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("0.00"), reason="x"),
            _request(),
            _admin(),
        )
    assert raised.value.code == "invalid_refund_amount"
    assert seen == []
    assert [r for r in await _ledger(tenant_id) if r[0] == "refund"] == []


# ============================================================================
# create_refund — a 200 that is not JSON is unreadable, never fabricated
# ============================================================================


async def test_a_non_json_200_refund_answer_is_unreadable() -> None:
    """A 200 whose body will not parse leaves `body = None` (payments.py:891-892) and the
    refund is refused rather than recorded against a fabricated id."""

    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<<not json>>")

    adapter, _seen = _refund_adapter(responder)
    with pytest.raises(ProblemError) as raised:
        await adapter.create_refund(
            payment_id="pay_1",
            amount_inr=Decimal("500.00"),
            notes={},
            idempotency_key="rfnd_key_0123456789",
        )
    assert raised.value.code == "refund_unreadable"


# ============================================================================
# extract_refund — the remaining refusal arms, each hit precisely
# ============================================================================


@pytest.mark.parametrize(
    ("envelope", "code"),
    [
        # non-dict envelope: 1137->1143
        (None, "refund_payload_unrecognized"),
        # dict envelope, non-dict payload: 1139->1143
        ({"event": "refund.processed"}, "refund_payload_unrecognized"),
        # entity present but no id: 1152
        (
            {"payload": {"refund": {"entity": {"payment_id": "p", "currency": "INR"}}}},
            "refund_payload_unrecognized",
        ),
        # entity with id + payment_id but a non-INR currency: 1168
        (
            {"payload": {"refund": {"entity": {"id": "r", "payment_id": "p", "currency": "USD"}}}},
            "payment_currency_unsupported",
        ),
    ],
    ids=["non-dict-envelope", "non-dict-payload", "no-refund-id", "wrong-currency"],
)
def test_extract_refund_names_each_refusal_precisely(envelope: Any, code: str) -> None:
    with pytest.raises(ProblemError) as raised:
        payments.extract_refund(envelope)
    assert raised.value.code == code


# ============================================================================
# credit_refund — one refund id, two amounts, is a doctored replay (conflict)
# ============================================================================


async def test_the_same_refund_id_at_a_different_amount_is_a_conflict() -> None:
    """The ledger `ref` is the guarantee: a refund already recorded, arriving again at a
    DIFFERENT amount, is refused rather than absorbed (payments.py:1223-1225)."""
    tenant_id = await _tenant()
    pid = _payment_id("CONF")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    rid = _refund_id("CONF")
    first = payments.RefundEvent(
        refund_id=rid,
        payment_id=pid,
        tenant_id=tenant_id,
        amount_inr=Decimal("1000.00"),
        currency="INR",
    )
    doctored = payments.RefundEvent(
        refund_id=rid,
        payment_id=pid,
        tenant_id=tenant_id,
        amount_inr=Decimal("2000.00"),
        currency="INR",
    )
    async with tenant_session(tenant_id) as session:
        recorded = await payments.credit_refund(session, refund=first)
    assert recorded.recorded is True
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await payments.credit_refund(session, refund=doctored)
    assert raised.value.code == "refund_amount_conflict"
    # Only the original compensating entry exists — the conflict wrote nothing.
    assert len([r for r in await _ledger(tenant_id) if r[0] == "refund"]) == 1


# ============================================================================
# failed_payment_summary — best-effort, a shape it cannot read yields {}
# ============================================================================


@pytest.mark.parametrize(
    "envelope",
    [
        None,  # non-dict envelope: 1314->1320
        {"payload": "not-a-dict"},  # non-dict payload: 1316->1320
        {"payload": {"payment": "not-a-dict"}},  # non-dict payment entity: 1318->1320
    ],
    ids=["non-dict-envelope", "non-dict-payload", "non-dict-payment"],
)
def test_failed_payment_summary_is_empty_for_a_shape_it_cannot_read(envelope: Any) -> None:
    assert payments.failed_payment_summary(envelope) == {}


# ============================================================================
# What a refund may take back: the payment, in AGGREGATE, and the bonus it bought
# ============================================================================
#
# Two holes on the money path, both found by asking the edge-case question the round was
# for — can this system charge for something it did not do?
#
# 1. `refund_exceeds_payment` was a PER-REQUEST ceiling. Two partial refunds each inside
#    the payment can sum to more than it, and each writes its own compensating debit.
# 2. A pack payment grants paid credits AND a bonus we fund. Reversing only the paid leg
#    leaves the bonus on the wallet — free talk time, repeatable at will.


def _refund_by_amount(prefix: str = "rfnd_AMT") -> Any:
    """A provider stub whose refund id is derived from the amount, so two DIFFERENT
    partial refunds of one payment get two different ids — which is what makes the
    aggregate question askable at all. The vendor's own idempotency key is derived the
    same way (`refund_idempotency_key`), so identical amounts do collapse onto one id."""

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": f"{prefix}_{body['amount']}",
                "amount": body["amount"],
                "status": "processed",
            },
        )

    return responder


async def _fund_pack(tenant_id: UUID, *, payment_id: str, pack_id: str) -> None:
    """A pack purchase: paid credits plus the bonus, exactly as the webhook credits one."""
    pack = pack_by_id(pack_id)
    assert pack is not None
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=pack.amount_inr,
        currency="INR",
        pack_id=pack_id,
    )
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(session, payment=payment)


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def test_partial_refunds_may_not_exceed_the_payment_in_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """₹2,000 then ₹1,000 against a ₹2,500 payment: each is inside the payment on its own,
    and together they refund ₹500 the client never paid."""
    tenant_id = await _tenant()
    pid = _payment_id("AGG")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    seen = _install_refund(monkeypatch, _refund_by_amount())

    first = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2000.00"), reason="partial"),
        _request(),
        _admin(),
    )
    assert first.recorded is True
    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("1000.00"), reason="again"),
            _request(),
            _admin(),
        )
    assert raised.value.code == "refund_exceeds_payment"
    assert len(seen) == 1, "a refusal must never reach the provider"
    assert await _balance(tenant_id) == Decimal("500.0000")


async def test_the_remaining_part_of_a_payment_is_still_refundable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The aggregate ceiling bounds the total and nothing more: ₹2,000 then ₹500 is
    exactly the payment and must go through."""
    tenant_id = await _tenant()
    pid = _payment_id("AGGOK")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_by_amount())

    await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2000.00"), reason="partial"),
        _request(),
        _admin(),
    )
    rest = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("500.00"), reason="the rest"),
        _request(),
        _admin(),
    )
    assert rest.recorded is True
    assert await _balance(tenant_id) == Decimal("0.0000")


async def test_a_full_refund_of_a_pack_takes_the_bonus_back_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pack grants paid credits plus a bonus we fund. Reversing the purchase reverses
    both, or the wallet keeps talk time nobody paid for."""
    tenant_id = await _tenant()
    pid = _payment_id("PACK")
    pack = pack_by_id("growth")
    assert pack is not None and pack.bonus_credits > 0
    await _fund_pack(tenant_id, payment_id=pid, pack_id="growth")
    assert await _balance(tenant_id) == pack.total_credits
    _install_refund(monkeypatch, _refund_by_amount("rfnd_PACK"))

    out = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="client asked"), _request(), _admin()
    )
    assert out.amount_inr == pack.amount_inr
    assert await _balance(tenant_id) == Decimal("0.0000"), "the bonus went back with the purchase"


async def test_a_partial_refund_of_a_pack_takes_back_that_share_of_the_bonus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half the purchase back, half the bonus back — and the second half later, once,
    with the two clawbacks summing to exactly the bonus granted."""
    tenant_id = await _tenant()
    pid = _payment_id("PACKHALF")
    pack = pack_by_id("growth")
    assert pack is not None
    await _fund_pack(tenant_id, payment_id=pid, pack_id="growth")
    _install_refund(monkeypatch, _refund_by_amount("rfnd_HALF"))

    # UNEVEN halves on purpose: the provider's idempotency key is derived from
    # (payment_id, amount), so two refunds of the SAME amount are one refund.
    part = Decimal("1000.00")
    await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=part, reason="part"),
        _request(),
        _admin(),
    )
    after_part = await _balance(tenant_id)
    assert after_part < pack.total_credits - part, "the bonus moved too, not only the paid leg"

    await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=pack.amount_inr - part, reason="the rest"),
        _request(),
        _admin(),
    )
    assert await _balance(tenant_id) == Decimal("0.0000"), (
        "the clawbacks sum to exactly the bonus granted, with no rounding residue"
    )


# ============================================================================
# The refund ceiling under CONCURRENCY — the half the aggregate ceiling did not hold
# ============================================================================
#
# `test_partial_refunds_may_not_exceed_the_payment_in_aggregate` above proves the
# SEQUENTIAL case: the second request runs after the first has recorded its compensating
# entry, so a read of `credit_ledger` sees it. That was the whole of the ceiling, and it
# was checked inside a `tenant_session` while the provider was called AFTER that block
# ended — and `pg_advisory_xact_lock` is released by COMMIT. So two operators acting at
# the same moment both read "nothing refunded yet" and both reached the provider.
#
# The reproduction below does not need threads: it starts the second refund from INSIDE
# the first one's provider call, which is exactly the window the released lock left open —
# the first request's transaction has committed and its ledger entry does not exist yet.


async def test_a_second_refund_started_mid_flight_cannot_cross_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """₹2,000 and ₹1,000 against a ₹2,500 payment, the second issued while the first is
    still at the provider. Before the claim table both reached the wire and ₹500 the
    client never paid went back."""
    tenant_id = await _tenant()
    pid = _payment_id("RACE")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")

    inner: list[ProblemError] = []
    settled = _refund_by_amount("rfnd_RACE")

    async def racing(request: httpx.Request) -> httpx.Response:
        # ONE reentry only: the second refund's own provider call must not recurse.
        if not inner and len(seen) == 1:
            with pytest.raises(ProblemError) as raised:
                await issue_tenant_refund(
                    tenant_id,
                    RefundIn(payment_id=pid, amount_inr=Decimal("1000.00"), reason="concurrent"),
                    _request(),
                    _admin(),
                )
            inner.append(raised.value)
        return settled(request)

    seen = _install_refund(monkeypatch, racing)

    first = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2000.00"), reason="partial"),
        _request(),
        _admin(),
    )
    assert first.recorded is True
    assert [problem.code for problem in inner] == ["refund_exceeds_payment"]
    assert len(seen) == 1, "the concurrent refund must never reach the provider"
    assert await _balance(tenant_id) == Decimal("500.0000")


async def test_the_claim_is_committed_before_the_provider_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ceiling can only span the vendor call if the row it counts is already
    committed when the call is made — a read inside the request's own transaction is
    invisible to everyone else and gone by then."""
    tenant_id = await _tenant()
    pid = _payment_id("CLAIM")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")

    claimed: list[Decimal] = []
    settled = _refund_by_amount("rfnd_CLAIM")

    async def observing(request: httpx.Request) -> httpx.Response:
        async with tenant_session(tenant_id) as session:
            claimed.append(
                await payments.claimed_refund_total_inr(
                    session, tenant_id=tenant_id, payment_id=pid
                )
            )
        return settled(request)

    _install_refund(monkeypatch, observing)
    await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2000.00"), reason="partial"),
        _request(),
        _admin(),
    )
    assert claimed == [Decimal("2000.0000")]


async def test_a_refund_the_provider_refuses_releases_its_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No money moved, so nothing may go on being reserved: one vendor 500 must not
    permanently shrink what this client can be refunded."""
    tenant_id = await _tenant()
    pid = _payment_id("RELEASE")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"description": "provider is down"}})

    _install_refund(monkeypatch, broken)
    with pytest.raises(ProblemError):
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("2500.00"), reason="x"),
            _request(),
            _admin(),
        )
    async with tenant_session(tenant_id) as session:
        assert await payments.claimed_refund_total_inr(
            session, tenant_id=tenant_id, payment_id=pid
        ) == Decimal("0")

    # And the whole payment is still refundable once the provider is back.
    _install_refund(monkeypatch, _refund_by_amount("rfnd_RETRY"))
    out = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2500.00"), reason="retry"),
        _request(),
        _admin(),
    )
    assert out.recorded is True
    assert await _balance(tenant_id) == Decimal("0.0000")


async def test_a_second_click_on_one_refund_is_still_a_replay_and_not_a_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider's idempotency key is `(payment_id, amount)`, so the same amount asked
    twice can only collapse onto the refund that exists. It must stay the no-op it was
    and must not be refused as a breach of a ceiling it does not move."""
    tenant_id = await _tenant()
    pid = _payment_id("REPLAY")
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_by_amount("rfnd_REPLAY"))

    first = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2500.00"), reason="x"),
        _request(),
        _admin(),
    )
    second = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("2500.00"), reason="x"),
        _request(),
        _admin(),
    )
    assert first.recorded is True
    assert second.recorded is False
    async with tenant_session(tenant_id) as session:
        assert await payments.claimed_refund_total_inr(
            session, tenant_id=tenant_id, payment_id=pid
        ) == Decimal("2500.0000"), "a replay adds nothing to what the ceiling counts"


async def test_one_tenants_refund_claims_are_invisible_to_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 1's cross-tenant zero-rows test for `refund_intents`.

    It matters more here than the shape suggests: the ceiling is a SUM over this table,
    so a claim leaking across tenants would refuse a refund one client is owed because
    another client had already been refunded."""
    tenant_a = await _tenant()
    tenant_b = await _tenant()
    pid = _payment_id("RLS")
    await _fund(tenant_a, payment_id=pid, amount_inr="2500.00")
    _install_refund(monkeypatch, _refund_by_amount("rfnd_RLS"))
    await issue_tenant_refund(
        tenant_a,
        RefundIn(payment_id=pid, amount_inr=Decimal("2500.00"), reason="x"),
        _request(),
        _admin(),
    )

    async with tenant_session(tenant_a) as session:
        assert await payments.claimed_refund_total_inr(
            session, tenant_id=tenant_a, payment_id=pid
        ) == Decimal("2500.0000")
    async with tenant_session(tenant_b) as session:
        assert (await session.execute(text("SELECT count(*) FROM refund_intents"))).scalar() == 0, (
            "another tenant's claims must not be readable"
        )
