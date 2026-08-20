"""The order-creation adapter (D-98): the paise boundary, the request, and the click.

Five properties, in five sections, because they fail for five different reasons:

1. **The conversion to the provider's unit is exact or it refuses.** Hard rule 7 in the
   outbound direction. `inr_to_paise` is the single most dangerous line in the
   integration, so every assertion here compares EXACT DIGIT STRINGS or exact integers —
   a rupee amount compared as a float would make the test complicit in the bug.
2. **The request we would send is the one their own SDK describes**, built from a pinned
   version path, and every unhappy answer becomes OUR problem code rather than vendor
   prose. Exercised through `httpx.MockTransport`: **no test in this file may reach the
   real Razorpay API, and the adapter has no path that would let one** — the transport is
   injected and a missing injection is a construction error, not a live call.
3. **The adapter owns exactly the client it built.** `razorpay_orders()` injects nothing,
   so the un-injected lifetime is the one production runs: the client is constructed from
   the pinned host and budget and closed on every exit, while a client the caller passed
   in is left open. Exercised by substituting `httpx.AsyncClient` with one whose transport
   is a mock, which is what keeps that path off the network too.
4. **A credential is built the right way round.** The public key id and the private secret
   are both opaque `rzp_…` strings, so swapping them type-checks and reads fine and shows
   up only as a 401 from an account nobody here can call. The wire header is the assertion.
5. **A second click creates no second order.** The key is derived by us (`topup_receipt`)
   and served by `reliability.claim_idempotency`, so the property to assert is the
   observable one: two calls, one order id, one provider request.

CONCURRENCY: every test mints its own tenant and mutates only the process settings object
through `monkeypatch`, which pytest restores per test.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payment_routes
from apps.api.billing.payment_routes import TopUpIntentIn, create_topup_intent
from apps.api.billing.payments import (
    API_VERSION_PATH,
    BASE_URL,
    INTENT_REPLAY_WINDOW,
    NO_API_SECRET_REASON,
    NOTES_TENANT_KEY,
    ORDER_TIMEOUT_S,
    ORDERS_PATH,
    PROVIDER,
    RECEIPT_MAX_LEN,
    USER_AGENT,
    RazorpayOrders,
    inr_to_paise,
    paise_to_inr,
    payment_capability,
    razorpay_api_secret,
    razorpay_orders,
    topup_receipt,
)
from apps.api.billing.service import to_paise
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from sqlalchemy import text

# Test values. They name no real account and no request in this file leaves the process.
TEST_KEY_ID = "rzp_test_orderslice"
TEST_KEY_SECRET = "rzp_secret_orderslice"

# What a stand-in Razorpay is: a function from the request we sent to the answer it gives
# (or an `httpx.HTTPError` it raises). Named because both fixtures below take one.
_Responder = Callable[[httpx.Request], httpx.Response]


def _payments_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that can take payments AND create orders.

    ALL FOUR VALUES ARE SET ON `Settings`, including the API secret. This helper used to
    monkeypatch `payments.razorpay_api_secret` itself, on the stated grounds that "the
    `razorpay_key_secret` field does not exist on `Settings` yet" — it did, from the same
    commit that wrote the sentence. Patching the accessor rather than the field meant the
    accessor's own body was never executed by any test that needed a secret, so the one
    line that turns configuration into a credential was untested: an accessor returning
    the wrong field, or returning `""` rather than None, would have passed this file.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", TEST_KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_orderslice")
    monkeypatch.setattr(settings, "razorpay_key_secret", TEST_KEY_SECRET)


async def _prepaid_tenant() -> tuple[UUID, Principal]:
    created = await admin_service.create_organization(
        name="Order Clinic",
        slug=f"order-{uuid.uuid4().hex[:8]}",
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
    return tenant_id, Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


class _Recorder:
    """A stand-in for Razorpay that records what we sent and answers what we tell it to."""

    def __init__(self, responder: _Responder) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def orders(self) -> RazorpayOrders:
        transport = httpx.MockTransport(self.handle)
        return RazorpayOrders(
            key_id=TEST_KEY_ID,
            key_secret=TEST_KEY_SECRET,
            client=httpx.AsyncClient(transport=transport, base_url=BASE_URL),
        )


def _ok(order_id: str = "order_TESTONLY0001") -> _Responder:
    """An order response echoing what we sent — the shape their docs describe. It is a
    FIXTURE OF OUR READING, not evidence: nobody here has seen a real one."""

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": order_id,
                "entity": "order",
                "amount": body["amount"],
                "currency": body["currency"],
                "receipt": body["receipt"],
                "status": "created",
            },
        )

    return responder


def _boom(_request: httpx.Request) -> httpx.Response:
    """The transport failing before any response exists — a DNS answer we never got, a
    TLS handshake that stalled, an egress proxy refusing the host (which is this
    environment's actual behaviour for razorpay.com)."""
    raise httpx.ConnectTimeout("no route")


def _install(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    """Point the route at the recorder. Patched on `payment_routes` because that is the
    name the route resolves at call time."""
    monkeypatch.setattr(payment_routes, "razorpay_orders", recorder.orders)


# ============================================================================
# 1. The paise boundary — exact, or refused
# ============================================================================


@pytest.mark.parametrize(
    ("rupees", "paise"),
    [
        # The docstring's dangerous number: `2500.10` is unrepresentable in binary
        # floating point, and 250010 is the only correct answer.
        ("2500.10", 250010),
        ("2500.1", 250010),  # digit FORM must not change the answer
        ("2500.100", 250010),
        ("0.01", 1),  # one paisa, the smallest unit that exists
        ("100.00", 10000),  # the floor of a top-up
        ("100000.00", 10000000),  # the ceiling
        ("1E+3", 100000),  # exponent notation is still an exact Decimal
        ("0.10", 10),
        ("99999.99", 9999999),
    ],
)
def test_a_rupee_amount_becomes_an_exact_integer_count_of_paise(rupees: str, paise: int) -> None:
    """The property: the integer is exactly right, for every digit form of the same
    number. Compared as an INTEGER against a literal, never against arithmetic that
    could carry the same error the code carries."""
    assert inr_to_paise(Decimal(rupees)) == paise


@pytest.mark.parametrize("rupees", ["2500.105", "0.001", "100.0000001", "1.5E-3"])
def test_an_amount_finer_than_a_paisa_is_refused_and_never_rounded(rupees: str) -> None:
    """THE property this function exists for. Rounding ₹2,500.105 to ₹2,500.10 silently
    is how a paise-level dispute starts; refusing it is a decision the caller can see."""
    with pytest.raises(ProblemError) as raised:
        inr_to_paise(Decimal(rupees))
    assert raised.value.code == "topup_amount_unrepresentable"


@pytest.mark.parametrize("amount", [2500.10, 0.01, 1.0])
def test_a_float_is_refused_rather_than_converted(amount: float) -> None:
    """A float has already lost the money by the time we see it: `Decimal(2500.10)` is
    2500.0999999999999090505298227071762084960937500. Refusing is the only answer that
    does not launder the error."""
    with pytest.raises(ProblemError) as raised:
        inr_to_paise(amount)  # type: ignore[arg-type]
    assert raised.value.code == "topup_amount_unrepresentable"


@pytest.mark.parametrize("rupees", ["0", "0.00", "-1.00", "-0.01"])
def test_a_non_positive_amount_is_refused(rupees: str) -> None:
    """A refund is a compensating entry somebody decides on (hard rule 4), never a
    negative order handed to a payment provider."""
    with pytest.raises(ProblemError) as raised:
        inr_to_paise(Decimal(rupees))
    assert raised.value.code == "topup_amount_unrepresentable"


@pytest.mark.parametrize(
    "rupees", ["100.00", "2500.10", "0.01", "99999.99", "100000.00", "7.05", "1234.56"]
)
def test_paise_and_rupees_round_trip_without_losing_a_paisa(rupees: str) -> None:
    """The two conversions are inverses. If they ever disagree, one deployment credits a
    different number from the one it charged.

    Two assertions because they are two claims. The VALUE must come back unchanged; the
    printed FORM must be the canonical two-decimal one, which is `to_paise`'s job and not
    this pair's — `paise_to_inr(250010)` is `Decimal("2500.1")`, numerically identical and
    a different string, and a ledger row or an invoice line reaches the client through
    `to_paise` in every case. Asserting the digit string AFTER that step is asserting what
    a client actually reads.
    """
    paise = inr_to_paise(Decimal(rupees))
    assert paise_to_inr(paise) == Decimal(rupees), "not one paisa moved"
    assert str(to_paise(paise_to_inr(paise))) == rupees, "and it prints as the client reads it"


# ============================================================================
# 2. The request, and every way the vendor can answer badly
# ============================================================================


async def test_the_order_request_is_the_shape_their_own_sdk_describes() -> None:
    """READ AT SOURCE: `POST {V1}/orders`, HTTP Basic, JSON body of amount/currency/
    receipt/notes, amount in whole paise. The property is the REQUEST — this is the one
    thing about the vendor we can assert without an account."""
    recorder = _Recorder(_ok())
    order = await recorder.orders().create_order(
        amount_inr=Decimal("2500.10"),
        receipt="clv_deadbeef",
        notes={NOTES_TENANT_KEY: "11111111-1111-1111-1111-111111111111"},
    )

    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.razorpay.com/v1/orders", "the version is pinned"
    expected = base64.b64encode(f"{TEST_KEY_ID}:{TEST_KEY_SECRET}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    body = json.loads(request.content)
    assert body["amount"] == 250010, "an integer count of paise, never a rupee float"
    assert body["currency"] == "INR"
    assert body["receipt"] == "clv_deadbeef"
    assert body["notes"][NOTES_TENANT_KEY] == "11111111-1111-1111-1111-111111111111"
    assert "payment_capture" not in body, "auto-capture is the account's decision, not ours"
    assert order.order_id == "order_TESTONLY0001"
    assert order.amount_paise == 250010


async def test_the_body_carries_no_float_anywhere() -> None:
    """A JSON float in the amount would be the whole bug, wearing the right value. The
    assertion is on the TYPE as serialized, because `250010.0 == 250010` is True and
    would let the defect through."""
    recorder = _Recorder(_ok())
    await recorder.orders().create_order(amount_inr=Decimal("2500.10"), receipt="clv_x", notes={})
    raw = recorder.requests[0].content.decode()
    body = json.loads(raw)
    assert isinstance(body["amount"], int) and not isinstance(body["amount"], bool)
    assert "250010.0" not in raw and "2500.1" not in raw


@pytest.mark.parametrize("status", [400, 401, 429, 500, 502])
async def test_a_refusal_becomes_our_problem_code_and_never_vendor_prose(status: int) -> None:
    """Errors are part of the interface. The client gets a code they can act on; the
    vendor's description of their own internals never crosses into our response."""
    recorder = _Recorder(
        lambda _r: httpx.Response(status, json={"error": {"description": "internal vendor prose"}})
    )
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_provider_rejected"
    assert "vendor prose" not in raised.value.detail


async def test_an_unreachable_provider_is_a_dependency_failure_not_a_fabricated_order() -> None:
    recorder = _Recorder(_boom)
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_provider_unreachable"


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": 42}, {"order": {"id": "x"}}])
async def test_a_response_with_no_readable_order_id_refuses_rather_than_invents(
    payload: dict[str, Any],
) -> None:
    """The response shape is UNVERIFIED. Being wrong must be loud: a fabricated id would
    be handed to a checkout that rejects it, and the client would believe they had paid."""
    recorder = _Recorder(lambda _r: httpx.Response(200, json=payload))
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_order_unreadable"


async def test_an_order_priced_differently_by_the_provider_is_refused() -> None:
    """A mismatch is a MONEY fact and stops everything; the client is told nothing was
    charged. (An absent `amount` is only a shape fact — the next test — and must not
    take the integration down.)"""
    recorder = _Recorder(lambda _r: httpx.Response(200, json={"id": "order_X", "amount": 999}))
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_order_amount_mismatch"


async def test_an_absent_amount_echo_does_not_take_the_integration_down() -> None:
    """The asymmetry is deliberate and it is the interesting half: refusing on an ABSENT
    field would make a working integration depend on a field name nobody here has
    confirmed, while tolerating a MISMATCHED one would let a wrong amount through."""
    recorder = _Recorder(lambda _r: httpx.Response(200, json={"id": "order_X"}))
    order = await recorder.orders().create_order(
        amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
    )
    assert order.order_id == "order_X"
    assert order.amount_paise == 50000, "our own conversion remains the authority"


class _SelfBuiltClients:
    """Watches the client the adapter builds for ITSELF, when none was injected.

    `create_order` has two client lifetimes and only one of them is exercised by
    `_Recorder`: the injected client, which the caller owns and the adapter must leave
    open. The other — no client passed, so the adapter constructs one per call and is the
    only thing that can close it — is the lifetime PRODUCTION uses, because
    `razorpay_orders()` never injects. This substitutes `httpx.AsyncClient` in the module
    the adapter constructs through, keeps every constructor kwarg it was given, and hands
    back a real client whose transport is a mock, so **no request leaves the process** on
    the very path that would otherwise open a real connection pool to api.razorpay.com.
    """

    def __init__(self, responder: _Responder) -> None:
        self.kwargs: list[dict[str, Any]] = []
        self.clients: list[httpx.AsyncClient] = []
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = httpx.AsyncClient

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            self.kwargs.append(kwargs)
            client = real(transport=httpx.MockTransport(self._handle), **kwargs)
            self.clients.append(client)
            return client

        monkeypatch.setattr(httpx, "AsyncClient", factory)


# ============================================================================
# 3. The client the adapter builds for itself — the lifetime production uses
# ============================================================================


@pytest.mark.parametrize(
    ("responder", "expected_code"),
    [
        (_ok("order_OWNED0001"), None),
        (lambda _r: httpx.Response(500, json={}), "payment_provider_rejected"),
        (_boom, "payment_provider_unreachable"),
    ],
    ids=["success", "rejected", "unreachable"],
)
async def test_a_client_the_adapter_built_itself_is_always_closed(
    monkeypatch: pytest.MonkeyPatch, responder: Any, expected_code: str | None
) -> None:
    """PROPERTY: when `create_order` builds its own client it closes it on EVERY exit —
    the success, the vendor's refusal, and the transport failure — and it never closes a
    client the caller injected.

    What breaks if this stops holding: `razorpay_orders()` injects nothing, so every
    order created in production goes down this path. A client that is not closed leaks
    its connection pool and its sockets per request; leaking it only on the ERROR exits
    (the classic shape of this bug — a close on the happy line instead of a `finally`)
    means the leak appears exactly when the provider is having a bad day and we are
    retrying hardest, which is the worst moment to run a process out of file descriptors.
    Asserted on the observable `is_closed`, not on a call count, so a close that raised
    would still read as unclosed.
    """
    watcher = _SelfBuiltClients(responder)
    watcher.install(monkeypatch)
    orders = RazorpayOrders(key_id=TEST_KEY_ID, key_secret=TEST_KEY_SECRET)

    if expected_code is None:
        order = await orders.create_order(
            amount_inr=Decimal("2500.10"), receipt="clv_owned", notes={}
        )
        assert order.order_id == "order_OWNED0001"
        assert order.amount_paise == 250010
    else:
        with pytest.raises(ProblemError) as raised:
            await orders.create_order(amount_inr=Decimal("2500.10"), receipt="clv_owned", notes={})
        assert raised.value.code == expected_code

    assert len(watcher.clients) == 1, "one order, one client"
    assert watcher.clients[0].is_closed is True, "the adapter owns it, so the adapter closes it"


async def test_an_injected_client_is_left_open_for_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PROPERTY: the adapter closes only what it built. A caller that passed a client in
    still holds a usable one afterwards.

    What breaks if this stops holding: `finally: await client.aclose()` without the
    ownership test would close a pooled client belonging to the caller, and the SECOND
    order on that client would fail with a closed-client error that points at the caller,
    not at us. The test asserts a second order succeeds on the same client — the
    observable answer, rather than the absence of a close call.
    """
    watcher = _SelfBuiltClients(_ok("order_INJECTED01"))
    watcher.install(monkeypatch)
    injected = httpx.AsyncClient(base_url=BASE_URL)
    orders = RazorpayOrders(key_id=TEST_KEY_ID, key_secret=TEST_KEY_SECRET, client=injected)

    first = await orders.create_order(amount_inr=Decimal("100.00"), receipt="clv_a", notes={})
    second = await orders.create_order(amount_inr=Decimal("100.00"), receipt="clv_b", notes={})

    assert first.order_id == second.order_id == "order_INJECTED01"
    assert injected.is_closed is False, "the caller's client survives its own request"
    await injected.aclose()


async def test_the_self_built_client_carries_the_pinned_host_budget_and_our_own_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PROPERTY: the client the adapter builds is configured from the pinned constants —
    `BASE_URL`, `ORDER_TIMEOUT_S`, JSON content type — and identifies as US.

    What breaks if this stops holding: a missing timeout makes httpx's default (or none)
    the budget for a call sitting inside a client request, so a payment provider having a
    slow minute becomes a browser hang with no explanation instead of our
    `payment_provider_unreachable`. And impersonating `Razorpay-Python/<version>` — the
    User-Agent their own SDK sends — would make their support answer a question about a
    client library we do not run.
    """
    watcher = _SelfBuiltClients(_ok())
    watcher.install(monkeypatch)
    await RazorpayOrders(key_id=TEST_KEY_ID, key_secret=TEST_KEY_SECRET).create_order(
        amount_inr=Decimal("100.00"), receipt="clv_cfg", notes={}
    )

    kwargs = watcher.kwargs[0]
    assert kwargs["base_url"] == BASE_URL == "https://api.razorpay.com"
    assert kwargs["timeout"] == ORDER_TIMEOUT_S
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["User-Agent"] == USER_AGENT
    assert "Razorpay-Python" not in kwargs["headers"]["User-Agent"], "we do not impersonate them"
    assert str(watcher.requests[0].url) == f"{BASE_URL}{API_VERSION_PATH}{ORDERS_PATH}"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"<html><body>502 Bad Gateway</body></html>", "text/html"),
        (b"", "application/json"),
        (b"{'id': 'order_X'}", "application/json"),
        (b"order_TRUNCATED", "application/json"),
    ],
    ids=["html-error-page", "empty-body", "not-json-quotes", "bare-text"],
)
async def test_a_200_that_is_not_json_refuses_rather_than_raising_a_decode_error(
    content: bytes, content_type: str
) -> None:
    """PROPERTY: a 2xx whose body cannot be parsed is `payment_order_unreadable` — one of
    OUR codes, raised deliberately — never a `JSONDecodeError` escaping the adapter.

    What breaks if this stops holding: an interposed proxy, a WAF or a load balancer
    answering 200 with an HTML error page is exactly the failure this environment already
    has (the egress proxy refuses razorpay.com), and it is not hypothetical for a
    deployment behind a corporate network. Without the `except ValueError` the caller
    gets a raw decode error, which reaches the client as a 500 with no remediation and no
    problem code — and, worse, an operator reading it looks for a bug in our JSON rather
    than at the box that rewrote the response. The empty-body case is the same defect at
    zero length: `httpx.Response.json()` on `b""` raises, it does not return None.
    """
    recorder = _Recorder(
        lambda _r: httpx.Response(200, content=content, headers={"Content-Type": content_type})
    )
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_order_unreadable"
    assert "JSON" not in raised.value.detail and "json" not in raised.value.detail


@pytest.mark.parametrize(
    "payload", [[{"id": "order_X"}], "order_X", 42, None], ids=["list", "string", "number", "null"]
)
async def test_a_json_body_that_is_not_an_object_refuses_rather_than_invents(payload: Any) -> None:
    """PROPERTY: valid JSON of the wrong SHAPE is refused too. The response contract is
    UNVERIFIED, so `body.get("id")` is only ever reached behind an `isinstance(dict)`
    test; a list or a bare string must produce the same authored refusal as no id at all.

    What breaks if this stops holding: `AttributeError: 'list' object has no attribute
    'get'` — a 500 instead of a refusal, on a shape nobody here has confirmed we will
    never see.
    """
    recorder = _Recorder(lambda _r: httpx.Response(200, json=payload))
    with pytest.raises(ProblemError) as raised:
        await recorder.orders().create_order(
            amount_inr=Decimal("500.00"), receipt="clv_x", notes={}
        )
    assert raised.value.code == "payment_order_unreadable"


# ============================================================================
# 4. Building the adapter from settings — the credential seam
# ============================================================================


async def test_the_adapter_is_built_with_the_secret_as_the_password_not_the_key_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PROPERTY: `razorpay_orders()` authenticates as `Basic base64(key_id:key_secret)`,
    reading the public half from `settings.razorpay_key_id` and the private half through
    the ONE accessor (`razorpay_api_secret`) — in that order, not swapped, and never the
    key id used for both.

    What breaks if this stops holding: the two credentials are both opaque `rzp_…`
    strings, so swapping them, or passing the publishable key twice, type-checks, reads
    fine, and fails only as an opaque 401 from a live account nobody here can call. That
    is the defect class this whole module was built to make visible before a deployment
    finds it. Asserted on the wire header, which is the only place the difference shows.
    """
    _payments_configured(monkeypatch)
    watcher = _SelfBuiltClients(_ok("order_FROMSETTINGS"))
    watcher.install(monkeypatch)

    order = await razorpay_orders().create_order(
        amount_inr=Decimal("2500.10"), receipt="clv_settings", notes={NOTES_TENANT_KEY: "t"}
    )

    assert order.order_id == "order_FROMSETTINGS"
    expected = base64.b64encode(f"{TEST_KEY_ID}:{TEST_KEY_SECRET}".encode()).decode()
    assert watcher.requests[0].headers["authorization"] == f"Basic {expected}"
    assert TEST_KEY_SECRET not in str(watcher.requests[0].url), "the secret rides in the header"


async def test_a_blank_secret_is_an_unset_secret_not_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RAZORPAY_KEY_SECRET=""` is an operator who meant to unset it — a half-finished
    edit, a templated env file with an empty placeholder — and `razorpay_api_secret()`
    collapses it to None for that reason.

    What breaks without the collapse: the empty string is truthy enough for the
    capability's `is not None` check, so `creates_orders` reports True, the adapter is
    built, and `Basic base64(key_id:)` goes to a live payment provider. The answer comes
    back as an opaque 401 that reads like a vendor outage rather than like the
    configuration mistake it is. This pins the one line that turns configuration into a
    credential; it was previously unexercised, because the tests patched the accessor
    itself rather than the field it reads.
    """
    _payments_configured(monkeypatch)
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", "")

    assert razorpay_api_secret() is None
    capability = payment_capability()
    assert capability.available is True, "a webhook can still credit a wallet"
    assert capability.creates_orders is False
    assert capability.orders_reason == NO_API_SECRET_REASON
    with pytest.raises(AssertionError):
        razorpay_orders()


@pytest.mark.parametrize("missing", ["key_id", "secret"])
async def test_building_the_adapter_without_the_capabilitys_credentials_never_yields_a_caller(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """PROPERTY: `razorpay_orders()` refuses to hand back an adapter when either half of
    the credential is absent. It raises instead — and the capability seam, not this
    function, is what a caller is supposed to ask first.

    What breaks if this stops holding: `None` reaching `httpx`'s `auth=` tuple sends an
    UNAUTHENTICATED (or half-authenticated) request to a payment provider, which is both
    a request we cannot explain and a 401 that looks like a vendor outage. The refusal
    keeps `creates_orders is False` meaning exactly one thing: no order call happens.
    """
    _payments_configured(monkeypatch)
    if missing == "key_id":
        monkeypatch.setattr(get_settings(), "razorpay_key_id", None)
    else:
        monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)

    assert payment_capability().creates_orders is False, "the seam already said no"
    with pytest.raises(AssertionError):
        razorpay_orders()


# ============================================================================
# 5. The click, twice
# ============================================================================


def test_the_receipt_is_derived_from_the_request_and_fits_the_vendors_limit() -> None:
    """Content-addressed over (tenant, amount, window) — D-87's device. Two properties:
    the same request derives the same key regardless of digit form, and the key survives
    a vendor that truncates at 40 characters."""
    tenant = UUID("11111111-1111-1111-1111-111111111111")
    at = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)

    first = topup_receipt(tenant_id=tenant, amount_inr=Decimal("2000"), at=at)
    same_amount_other_form = topup_receipt(tenant_id=tenant, amount_inr=Decimal("2000.00"), at=at)
    assert first == same_amount_other_form, "2000 and 2000.00 are one payment, not two"
    assert len(first) <= RECEIPT_MAX_LEN
    assert first.startswith("clv_")

    other_tenant = topup_receipt(
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"), amount_inr=Decimal("2000"), at=at
    )
    assert other_tenant != first, "two tenants must never share a key"
    other_amount = topup_receipt(tenant_id=tenant, amount_inr=Decimal("2500"), at=at)
    assert other_amount != first


def test_the_key_expires_so_a_genuine_second_topup_is_not_collapsed_forever() -> None:
    """The stated COST of the window, asserted so it cannot silently grow: the same
    tenant asking for the same amount after `INTENT_REPLAY_WINDOW` gets a new key — a
    client who paid ₹2,000 today must be able to pay ₹2,000 again."""
    tenant = UUID("11111111-1111-1111-1111-111111111111")
    at = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    later = at + INTENT_REPLAY_WINDOW * 2

    assert topup_receipt(tenant_id=tenant, amount_inr=Decimal("2000"), at=at) != topup_receipt(
        tenant_id=tenant, amount_inr=Decimal("2000"), at=later
    )


async def test_clicking_twice_creates_one_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE property of this slice's idempotency. Two identical intents, one provider
    request, one order id — and the money is compared as an exact digit string."""
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()
    recorder = _Recorder(_ok("order_ONCE0001"))
    _install(monkeypatch, recorder)

    first = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2500.10")), principal)
    second = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2500.10")), principal)

    assert len(recorder.requests) == 1, "a second click must not reach the provider"
    assert first.provider_order_id == "order_ONCE0001"
    assert second.provider_order_id == first.provider_order_id
    assert second.receipt == first.receipt
    assert str(second.amount_inr) == "2500.10", "rupees survive the replay as exact digits"
    assert second.amount_paise == 250010
    assert second.provider_order_pending is False


async def test_a_second_click_from_another_owner_of_the_same_tenant_replays_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope is the TENANT, not the person. A top-up belongs to the organization's
    wallet, so two owners submitting the same amount want one order, not one each."""
    _payments_configured(monkeypatch)
    tenant_id, owner = await _prepaid_tenant()
    other_owner = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )
    recorder = _Recorder(_ok("order_SHARED001"))
    _install(monkeypatch, recorder)

    first = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("1000.00")), owner)
    second = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("1000.00")), other_owner)

    assert len(recorder.requests) == 1
    assert second.provider_order_id == first.provider_order_id


async def test_a_different_amount_is_a_different_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()
    ids = iter(["order_A0001", "order_B0001"])

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"id": next(ids), "amount": body["amount"]})

    recorder = _Recorder(responder)
    _install(monkeypatch, recorder)

    first = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("1000.00")), principal)
    second = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2000.00")), principal)

    assert len(recorder.requests) == 2
    assert first.provider_order_id != second.provider_order_id


async def test_a_failed_order_leaves_the_key_free_for_the_clients_own_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed attempt that kept the claim would refuse the client's next click as
    "already in flight" for ten minutes. The property is the retry succeeding, which is
    only possible if the claim was marked failed rather than left processing."""
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()
    answers = iter([httpx.Response(500, json={}), None])

    def responder(request: httpx.Request) -> httpx.Response:
        answer = next(answers)
        if answer is not None:
            return answer
        body = json.loads(request.content)
        return httpx.Response(200, json={"id": "order_RETRY001", "amount": body["amount"]})

    recorder = _Recorder(responder)
    _install(monkeypatch, recorder)

    with pytest.raises(ProblemError) as raised:
        await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("1500.00")), principal)
    assert raised.value.code == "payment_provider_rejected"

    retry = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("1500.00")), principal)
    assert retry.provider_order_id == "order_RETRY001"
    assert len(recorder.requests) == 2


async def test_without_the_api_secret_no_order_is_attempted_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state of EVERY deployment today. The property is negative and it is the one
    that matters: not merely that `provider_order_id` is null, but that the provider was
    never contacted — a deployment with no credential must not discover that at the
    vendor boundary."""
    _payments_configured(monkeypatch)
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)
    _tenant_id, principal = await _prepaid_tenant()

    def never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made without the API secret")

    recorder = _Recorder(never)
    _install(monkeypatch, recorder)

    intent = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2500.00")), principal)

    assert recorder.requests == []
    assert intent.provider_order_id is None
    assert intent.provider_order_pending is True
    assert payment_capability().creates_orders is False
    # The receipt is still real and still derived, so the bank-transfer path in
    # runbooks/topup-payments.md §3 has a reference to quote.
    assert intent.receipt.startswith("clv_")
    assert str(intent.amount_inr) == "2500.00"


async def test_the_capability_route_answers_from_the_same_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rendering hint, and it must agree with the route behind it — that is the whole
    point of one selector. Asserted in both directions of the order half."""
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()

    with_secret = await payment_routes.read_topup_capability(principal)
    assert with_secret.online_payments_available is True
    assert with_secret.provider_orders_available is True

    monkeypatch.setattr(get_settings(), "razorpay_key_secret", None)
    without = await payment_routes.read_topup_capability(principal)
    assert without.online_payments_available is True, "a webhook can still credit a wallet"
    assert without.provider_orders_available is False

    monkeypatch.setattr(get_settings(), "payment_provider", None)
    unconfigured = await payment_routes.read_topup_capability(principal)
    assert unconfigured.online_payments_available is False
    assert unconfigured.provider_orders_available is False


async def test_the_capability_answer_never_leaks_which_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`reason` is OUR configuration state. A client cannot act on "no_webhook_secret"
    and naming our missing secret is an internals leak (user-safe messages)."""
    _payments_configured(monkeypatch)
    monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", None)
    _tenant_id, principal = await _prepaid_tenant()

    answer = await payment_routes.read_topup_capability(principal)
    assert answer.model_dump() == {
        "online_payments_available": False,
        "provider_orders_available": False,
    }


async def test_a_refused_intent_creates_no_order_and_no_ledger_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An amount outside the band is refused BEFORE the seam, the claim and the network —
    cheap-before-dear, and nothing is written on the way out."""
    _payments_configured(monkeypatch)
    tenant_id, principal = await _prepaid_tenant()

    def never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("a refused amount must never reach the provider")

    recorder = _Recorder(never)
    _install(monkeypatch, recorder)

    with pytest.raises(ProblemError) as raised:
        await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("99.99")), principal)
    assert raised.value.code == "topup_amount_out_of_range"
    assert recorder.requests == []

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert rows == 0
