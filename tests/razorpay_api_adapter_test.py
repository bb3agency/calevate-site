"""`billing/razorpay_api.RazorpayApi`: every call's wire shape and every refusal.

The adapter is driven through `httpx.MockTransport` only; no test here reaches Razorpay.
Paths and bodies asserted below are the ones the module cites from Razorpay's docs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.billing import payments
from apps.api.billing import razorpay_api as module
from apps.api.billing.razorpay_api import (
    LIST_PAGE,
    RazorpayApi,
    normalize_payment,
    razorpay_api,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

KEY_ID = "rzp_test_adapter"
KEY_SECRET = "rzp_secret_adapter"

Responder = Callable[[httpx.Request], httpx.Response]


class Wire:
    def __init__(self, responder: Responder) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def api(self) -> RazorpayApi:
        return RazorpayApi(
            key_id=KEY_ID,
            key_secret=KEY_SECRET,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(self.handle), base_url="https://api.razorpay.com"
            ),
        )


def _json(request: httpx.Request) -> dict[str, Any]:
    body = json.loads(request.content)
    assert isinstance(body, dict)
    return body


# --- normalisation --------------------------------------------------------------------


def test_a_payment_entity_is_normalised_and_notes_keep_only_string_pairs() -> None:
    payment = normalize_payment(
        {
            "id": "pay_1",
            "status": "captured",
            "amount": 15000,
            "currency": "inr",
            "order_id": "order_1",
            "method": "upi",
            "international": True,
            "token_id": "token_1",
            "customer_id": "",
            "notes": {"tenant": "t1", "count": 3},
            "error_code": None,
            "created_at": 1_700_000_000,
        }
    )
    assert payment is not None
    assert payment.currency == "INR"
    assert payment.international is True
    assert payment.token_id == "token_1"
    assert payment.customer_id is None, "an empty string is not an id"
    assert payment.notes == {"tenant": "t1"}
    assert payment.created_at == 1_700_000_000


@pytest.mark.parametrize(
    "entity",
    [
        "not a dict",
        {"amount": 100, "currency": "INR"},
        {"id": "pay_1", "amount": True, "currency": "INR"},
        {"id": "pay_1", "amount": 100},
    ],
)
def test_an_entity_we_cannot_read_is_none(entity: Any) -> None:
    assert normalize_payment(entity) is None


def test_notes_sent_as_an_empty_array_become_an_empty_mapping() -> None:
    payment = normalize_payment({"id": "pay_1", "amount": 1, "currency": "INR", "notes": []})
    assert payment is not None
    assert payment.notes == {}
    assert payment.status == ""
    assert payment.created_at == 0


# --- the one transport ----------------------------------------------------------------


async def test_a_transport_failure_is_our_unreachable_refusal() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProblemError) as refused:
        await Wire(fail).api().fetch_payment("pay_1")
    assert refused.value.code == "payment_provider_unreachable"


async def test_a_vendor_error_status_is_our_rejection_and_its_prose_is_not_forwarded() -> None:
    wire = Wire(lambda _: httpx.Response(400, json={"error": {"description": "VENDOR PROSE"}}))
    with pytest.raises(ProblemError) as refused:
        await wire.api().accept_dispute("disp_1")
    assert refused.value.code == "payment_provider_rejected"
    assert "VENDOR PROSE" not in str(refused.value.detail)


async def test_a_body_that_is_not_json_is_unreadable() -> None:
    wire = Wire(lambda _: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ProblemError) as refused:
        await wire.api().create_customer(name="A", email="a@example.com", contact="+91", notes={})
    assert refused.value.code == "payment_provider_unreadable"


async def test_a_client_the_adapter_builds_for_itself_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        client = real(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "lost"})),
            **kwargs,
        )
        built.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    api = RazorpayApi(key_id=KEY_ID, key_secret=KEY_SECRET)
    assert await api.accept_dispute("disp_1") == "lost"
    assert len(built) == 1 and built[0].is_closed


# --- customers and recurring payments -------------------------------------------------


async def test_a_customer_is_created_reusing_an_existing_one_and_the_name_is_capped() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"id": " cust_1 "}))
    customer_id = await wire.api().create_customer(
        name="N" * 80, email="a@example.com", contact="+919900000000", notes={"t": "1"}
    )
    assert customer_id == "cust_1"
    request = wire.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/customers"
    assert request.headers["Content-Type"] == "application/json"
    body = _json(request)
    assert body["fail_existing"] == "0"
    assert len(body["name"]) == 50


async def test_an_answer_with_a_blank_id_is_unreadable() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"id": "  "}))
    with pytest.raises(ProblemError) as refused:
        await wire.api().create_customer(name="A", email="a@example.com", contact="+91", notes={})
    assert refused.value.code == "payment_provider_unreadable"


async def test_a_charge_order_captures_and_sends_no_notification_block() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"id": "order_c"}))
    order_id = await wire.api().create_charge_order(
        amount_inr=Decimal("2000.00"), receipt="clvr_1", notes={"a": "b"}
    )
    assert order_id == "order_c"
    body = _json(wire.requests[0])
    assert body["amount"] == 200000
    assert body["payment_capture"] is True
    assert "notification" not in body


async def test_a_recurring_payment_answer_without_a_payment_id_is_unreadable() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"razorpay_payment_id": ""}))
    with pytest.raises(ProblemError) as refused:
        await wire.api().create_recurring_payment(
            email="a@example.com",
            contact="+91",
            amount_inr=Decimal("1.00"),
            order_id="order_1",
            customer_id="cust_1",
            token_id="token_1",
            notes={},
        )
    assert refused.value.code == "payment_provider_unreadable"


@pytest.mark.parametrize(
    ("method", "verb", "path"),
    [
        ("upi", "PUT", "/v1/customers/cust_1/tokens/token_1/cancel"),
        ("card", "DELETE", "/v1/customers/cust_1/tokens/token_1"),
    ],
)
async def test_a_mandate_is_cancelled_the_way_its_method_documents(
    method: Any, verb: str, path: str
) -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"status": "cancellation_initiated"}))
    await wire.api().cancel_token(customer_id="cust_1", token_id="token_1", method=method)
    assert wire.requests[0].method == verb
    assert wire.requests[0].url.path == path
    assert "Content-Type" not in wire.requests[0].headers


async def test_token_status_reads_only_the_named_token() -> None:
    body = {
        "items": [
            "junk",
            {"id": "token_other", "recurring_details": {"status": "rejected"}},
            {"id": "token_1", "recurring_details": {"status": "confirmed"}, "vpa": "x@y"},
        ]
    }
    wire = Wire(lambda _: httpx.Response(200, json=body))
    assert await wire.api().token_status(customer_id="cust_1", token_id="token_1") == "confirmed"
    assert await wire.api().token_status(customer_id="cust_1", token_id="token_gone") is None


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{"id": "token_1", "recurring_details": "nope"}]},
        {"items": [{"id": "token_1", "recurring_details": {"status": 7}}]},
        {"items": "nope"},
        ["not", "an", "object"],
    ],
)
async def test_a_token_whose_status_we_cannot_read_is_none(body: Any) -> None:
    wire = Wire(lambda _: httpx.Response(200, json=body))
    assert await wire.api().token_status(customer_id="cust_1", token_id="token_1") is None


# --- reads ----------------------------------------------------------------------------


async def test_fetch_payment_normalises_and_refuses_an_unreadable_entity() -> None:
    wire = Wire(
        lambda _: httpx.Response(
            200, json={"id": "pay_1", "amount": 500, "currency": "INR", "status": "captured"}
        )
    )
    payment = await wire.api().fetch_payment("pay_1")
    assert payment.payment_id == "pay_1" and payment.amount_paise == 500
    assert wire.requests[0].url.path == "/v1/payments/pay_1"

    bad = Wire(lambda _: httpx.Response(200, json={"id": "pay_1"}))
    with pytest.raises(ProblemError) as refused:
        await bad.api().fetch_payment("pay_1")
    assert refused.value.code == "payment_provider_unreadable"


async def test_lists_page_with_skip_until_a_short_page() -> None:
    full = [{"id": f"pay_{i}", "amount": 100, "currency": "INR"} for i in range(LIST_PAGE)]
    tail = [{"id": "pay_last", "amount": 100, "currency": "INR"}, {"id": "broken"}]

    def respond(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json={"items": full if skip == 0 else tail})

    wire = Wire(respond)
    rows = await wire.api().list_payments(since=10, until=20)
    assert len(rows) == LIST_PAGE + 1, "the unreadable entity is dropped"
    assert [r.url.params["skip"] for r in wire.requests] == ["0", str(LIST_PAGE)]
    assert wire.requests[0].url.params["from"] == "10"
    assert wire.requests[0].url.params["to"] == "20"
    assert wire.requests[0].url.params["count"] == str(LIST_PAGE)


async def test_a_list_page_that_is_not_a_list_is_unreadable() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"items": None}))
    with pytest.raises(ProblemError) as refused:
        await wire.api().list_settlements(since=0, until=1)
    assert refused.value.code == "payment_provider_unreadable"


async def test_refund_rows_skip_what_they_cannot_read() -> None:
    items = [
        "junk",
        {"id": "rfnd_bad", "payment_id": "pay_1"},
        {
            "id": "rfnd_1",
            "payment_id": "pay_1",
            "amount": 2500,
            "currency": "inr",
            "status": "processed",
            "notes": {"k": "v"},
        },
        {"id": "rfnd_2", "payment_id": "pay_2", "amount": 100},
    ]
    wire = Wire(lambda _: httpx.Response(200, json={"items": items}))
    rows = await wire.api().list_refunds(since=0, until=1)
    assert [r.refund_id for r in rows] == ["rfnd_1", "rfnd_2"]
    assert rows[0].currency == "INR" and rows[0].notes == {"k": "v"}
    assert rows[1].currency == "" and rows[1].status == ""
    assert wire.requests[0].url.path == "/v1/refunds"


async def test_settlements_are_read_and_rows_without_an_id_skipped() -> None:
    items = [
        {"id": "setl_1", "amount": 9900, "status": "processed", "created_at": 5},
        {"id": "setl_2"},
        {"amount": 1},
        "junk",
    ]
    wire = Wire(lambda _: httpx.Response(200, json={"items": items}))
    rows = await wire.api().list_settlements(since=0, until=1)
    assert [(r.settlement_id, r.amount_paise, r.status, r.created_at) for r in rows] == [
        ("setl_1", 9900, "processed", 5),
        ("setl_2", 0, "", 0),
    ]


# --- disputes and documents -----------------------------------------------------------


async def test_accepting_a_dispute_returns_its_status_or_nothing() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"status": "lost"}))
    assert await wire.api().accept_dispute("disp_1") == "lost"
    assert wire.requests[0].url.path == "/v1/disputes/disp_1/accept"
    odd = Wire(lambda _: httpx.Response(200, json=["x"]))
    assert await odd.api().accept_dispute("disp_1") == ""


async def test_contesting_submits_the_evidence_with_a_capped_summary() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"status": "under_review"}))
    status = await wire.api().contest_dispute(
        "disp_1",
        summary="s" * 1500,
        amount_paise=40000,
        evidence={"billing_proof": ["doc_1"]},
    )
    assert status == "under_review"
    request = wire.requests[0]
    assert request.method == "PATCH" and request.url.path == "/v1/disputes/disp_1/contest"
    body = _json(request)
    assert body["action"] == "submit"
    assert body["billing_proof"] == ["doc_1"]
    assert len(body["summary"]) == 1000
    odd = Wire(lambda _: httpx.Response(200, json=[]))
    assert await odd.api().contest_dispute("d", summary="s", amount_paise=1, evidence={}) == ""


async def test_a_document_is_uploaded_as_dispute_evidence() -> None:
    wire = Wire(lambda _: httpx.Response(200, json={"id": "doc_1"}))
    doc_id = await wire.api().upload_document(
        filename="proof.pdf", content=b"%PDF-1.4", content_type="application/pdf"
    )
    assert doc_id == "doc_1"
    request = wire.requests[0]
    assert request.url.path == "/v1/documents"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b"dispute_evidence" in request.content and b"%PDF-1.4" in request.content


# --- the factory ----------------------------------------------------------------------


def _configure(monkeypatch: pytest.MonkeyPatch, *, secret: str | None) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_adapter")
    monkeypatch.setattr(settings, "razorpay_key_secret", secret)
    monkeypatch.setattr(settings, "razorpay_mode", None)


def test_the_factory_builds_the_adapter_when_orders_can_be_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, secret=KEY_SECRET)
    api = razorpay_api()
    assert isinstance(api, RazorpayApi)
    assert api._auth == (KEY_ID, KEY_SECRET)


def test_the_factory_refuses_without_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, secret=KEY_SECRET)
    monkeypatch.setattr(get_settings(), "payment_provider", None)
    with pytest.raises(ProblemError) as refused:
        razorpay_api()
    assert refused.value.code == payments.payments_not_configured(None).code


def test_the_factory_refuses_without_the_api_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, secret=None)
    assert module.payment_capability().available is True
    with pytest.raises(ProblemError) as refused:
        razorpay_api()
    assert refused.value.code == payments.payments_not_configured(None).code
