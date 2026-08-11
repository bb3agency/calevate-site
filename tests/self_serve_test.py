"""The self-serve motion's two missing halves (D-34 / D-39): the way IN and the way to PAY.

D-39 shipped the SCHEMA in M1 — `credit_ledger`, `organizations.plan_tier`,
`invitations` — so the SURFACE could land later without a migration. It never landed:
a self-serve tenant could only be born in the admin wizard and a wallet could only be
topped up by an operator keying a UTR. These tests pin the two new surfaces.

The properties worth protecting, in the order they cost money:

- **Signup produces a tenant that could take a call** — org + retention policies +
  agent with a non-null disclosure line + extraction schema + owner membership, in one
  go. A half-built tenant is worse than none, because the pipeline would process calls
  for it (admin/service.py's own argument, inherited by reusing that function).
- **Reserved and duplicate slugs are refused server-side.** There is no operator in
  this flow to catch a mistake, and the slug is immutable once set.
- **An unauthenticated tenant factory is a resource-exhaustion surface**, so the quota
  is asserted, not assumed.
- **A payment webhook is replayed by every provider.** The same payment id delivered
  twice — in the same envelope or a different one — credits exactly ONCE.
- **A bad signature credits nothing and leaves no row.**
- **Money is Decimal end to end**: a string on the wire in both directions, NUMERIC in
  the ledger, and a JSON float refused rather than quietly rounded (hard rule 7).

Neither router is mounted in `main.py` (the integrator owns that), so each test mounts
what it needs on a bare app with the real error handlers — which is also how the RBAC
boot assertion gets exercised against them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing import payments
from apps.api.billing.payment_routes import router as topup_router
from apps.api.billing.payment_routes import webhook_router
from apps.api.compliance.service import credits_exhausted
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy import signup as signup_service
from apps.api.tenancy.signup_routes import router as signup_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

WEBHOOK_SECRET = "whsec_razorpay_test_secret"


# --- harness ------------------------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(signup_router)
    application.include_router(topup_router)
    application.include_router(webhook_router)
    return application


def _client(ip: str | None = None) -> AsyncClient:
    """A client with its OWN source IP unless a test deliberately shares one.

    The signup quota has a per-IP window, and every test in this file would otherwise
    share the ASGI transport's default address — so a second run of the suite inside
    the same hour would start 429ing on tests that are not about the quota at all.
    """
    address = ip or f"198.51.100.{uuid.uuid4().int % 250 + 1}"
    transport = ASGITransport(app=_app(), client=(address, 12345))
    return AsyncClient(transport=transport, base_url="http://api")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signed_up_user() -> tuple[str, uuid.UUID]:
    """A Clerk-authenticated client-realm user with NO membership yet — exactly the
    state FLOWS §2 step 1 leaves a self-serve signup in."""
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:i, :c, :e, now(), now())"
            ),
            {"i": user_id, "c": clerk_id, "e": f"{clerk_id}@example.com"},
        )
    return f"dev:client:{clerk_id}", user_id


def _signup_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "business_name": "Sunrise Dental",
        "slug": f"sun-{uuid.uuid4().hex[:8]}",
        "vertical_template": "clinic",
        "language": "te-IN",
    }
    body.update(overrides)
    return body


async def _ledger(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str | None]]:
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


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both surfaces are OFF by default (R-11: self-serve is the sharp compliance
    edge, and an unconfigured payment receiver must fail closed). Every test that is
    not specifically about the switch runs with them on."""
    settings = get_settings()
    monkeypatch.setattr(settings, "self_serve_signup_enabled", True)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_localonly")


# --- signup -------------------------------------------------------------------


async def test_signup_creates_a_tenant_that_could_take_a_call() -> None:
    """The whole point of reusing `admin_service.create_organization`: a self-serve
    tenant is born as complete as a managed one, plus the owner membership and the
    plan tier that distinguish the motion (D-34: one product, two motions)."""
    token, user_id = await _signed_up_user()
    body = _signup_body()

    async with _client() as http:
        response = await http.post("/v1/auth/signup", headers=_headers(token), json=body)

    assert response.status_code == 201, response.text
    created = response.json()
    tenant_id = uuid.UUID(created["tenant_id"])
    assert created["slug"] == body["slug"]
    assert created["plan_tier"] == "self_serve"
    assert created["role"] == "owner"

    async with tenant_session(tenant_id) as session:
        org = (
            await session.execute(
                text("SELECT name, slug, status, plan_tier FROM organizations WHERE id = :t"),
                {"t": tenant_id},
            )
        ).first()
        agent = (
            await session.execute(
                text(
                    "SELECT id, disclosure_line, language_primary, extraction_schema_id, status "
                    "FROM agents WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
        schema_fields = (
            await session.execute(
                text("SELECT fields FROM extraction_schemas WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
        policies = (
            await session.execute(
                text("SELECT count(*) FROM retention_policies WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
        membership = (
            await session.execute(
                text("SELECT role FROM memberships WHERE tenant_id = :t AND user_id = :u"),
                {"t": tenant_id, "u": user_id},
            )
        ).scalar()

    assert org is not None and org[3] == "self_serve"
    assert org[2] == "onboarding"
    assert agent is not None, "a tenant with no agent cannot take a call"
    assert agent[1], "hard rule 5: the disclosure line is never null"
    assert agent[3] is not None, "the agent is wired to its extraction schema"
    assert schema_fields, "a tenant with no schema produces leads with no columns"
    assert int(policies or 0) >= 1, "SEC-COMP §1's retention floor applies from call one"
    assert membership == "owner"


async def test_a_new_self_serve_wallet_is_empty_so_the_gate_refuses_to_dial() -> None:
    """R-11 in one assertion: signup does not hand anyone a dialer. The compliance
    gate already refuses a self-serve tenant with an exhausted wallet — this proves
    the tier signup writes is the one the gate reads."""
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post("/v1/auth/signup", headers=_headers(token), json=_signup_body())
    tenant_id = uuid.UUID(response.json()["tenant_id"])

    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is True


async def test_a_reserved_slug_is_refused() -> None:
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup", headers=_headers(token), json=_signup_body(slug="dashboard")
        )
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/slug_reserved")


async def test_a_duplicate_slug_is_refused() -> None:
    first_token, _ = await _signed_up_user()
    second_token, _ = await _signed_up_user()
    body = _signup_body()

    async with _client() as http:
        first = await http.post("/v1/auth/signup", headers=_headers(first_token), json=body)
        clash = await http.post("/v1/auth/signup", headers=_headers(second_token), json=body)

    assert first.status_code == 201, first.text
    assert clash.status_code == 409, clash.text
    assert clash.json()["type"].endswith("/slug_taken")


async def test_a_malformed_slug_is_refused_by_shape() -> None:
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup", headers=_headers(token), json=_signup_body(slug="No Spaces Here")
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/invalid_slug")


async def test_a_slug_is_derived_from_the_business_name_when_none_is_given() -> None:
    token, _ = await _signed_up_user()
    name = f"Kiran Clinic {uuid.uuid4().hex[:6]}"
    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup",
            headers=_headers(token),
            json={"business_name": name, "vertical_template": "clinic", "language": "te-IN"},
        )
    assert response.status_code == 201, response.text
    assert response.json()["slug"] == signup_service.derive_slug(name)


async def test_signup_needs_a_verified_identity() -> None:
    """FLOWS §2: Clerk authenticates, our webhook mirrors the user, THEN the org-create
    step runs. An anonymous caller cannot mint a tenant, and neither can a token whose
    user was never mirrored into `users`."""
    async with _client() as http:
        anonymous = await http.post("/v1/auth/signup", json=_signup_body())
        unmirrored = await http.post(
            "/v1/auth/signup",
            headers=_headers(f"dev:client:user_{uuid.uuid4().hex[:12]}"),
            json=_signup_body(),
        )
    assert anonymous.status_code == 401, anonymous.text
    assert unmirrored.status_code == 401, unmirrored.text


async def test_the_signup_quota_stops_a_tenant_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """An endpoint that creates tenants for anyone with an account is a
    resource-exhaustion surface. The per-identity window is the control; here it is
    turned down to one so the refusal is observable."""
    monkeypatch.setattr(signup_service, "SIGNUPS_PER_USER_PER_HOUR", 1)
    token, user_id = await _signed_up_user()

    async with _client() as http:
        first = await http.post("/v1/auth/signup", headers=_headers(token), json=_signup_body())
        second = await http.post("/v1/auth/signup", headers=_headers(token), json=_signup_body())

    assert first.status_code == 201, first.text
    assert second.status_code == 429, second.text
    assert second.json()["type"].endswith("/rate_limited")
    assert second.headers.get("Retry-After")

    # The refusal happens before any DB work, so the caller still owns exactly the one
    # tenant the first call built. (`memberships` is tenant-scoped, so this count has
    # to be taken inside that tenant's RLS context — an untenanted session sees zero
    # rows by design, which would make this assertion pass for the wrong reason.)
    tenant_id = uuid.UUID(first.json()["tenant_id"])
    async with tenant_session(tenant_id) as session:
        owned = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()
    assert int(owned or 0) == 1, "the refused request created nothing"


async def test_the_quota_also_counts_by_source_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-account window alone is defeated by making more accounts, which is the
    cheap half of the attack. The address window is the other half."""
    monkeypatch.setattr(signup_service, "SIGNUPS_PER_IP_PER_HOUR", 1)
    first_token, _ = await _signed_up_user()
    second_token, _ = await _signed_up_user()
    address = f"203.0.113.{uuid.uuid4().int % 250 + 1}"

    async with _client(ip=address) as http:
        first = await http.post(
            "/v1/auth/signup", headers=_headers(first_token), json=_signup_body()
        )
        second = await http.post(
            "/v1/auth/signup", headers=_headers(second_token), json=_signup_body()
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 429, second.text


async def test_signup_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-11: self-serve + Indian telecom compliance is the sharp edge, so the motion
    ships with an off switch that does not need a deploy."""
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", False)
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post("/v1/auth/signup", headers=_headers(token), json=_signup_body())
    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/signup_disabled")


async def test_a_managed_tier_cannot_be_self_assigned() -> None:
    """The two motions share one `organizations` row and are told apart by the tier
    column. Letting the caller pick `managed` would let anyone claim the invoiced
    motion — the one with no wallet gate in front of it."""
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup", headers=_headers(token), json=_signup_body(plan_tier="managed")
        )
    assert response.status_code == 422, response.text


# --- razorpay top-ups ---------------------------------------------------------


def _envelope(
    *,
    payment_id: str,
    tenant_id: uuid.UUID | None,
    amount: Any = 250000,
    currency: str = "INR",
    event: str = "payment.captured",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    notes = {} if tenant_id is None else {payments.NOTES_TENANT_KEY: str(tenant_id)}
    entity: dict[str, Any] = {
        "id": payment_id,
        "amount": amount,
        "currency": currency,
        "status": "captured",
        "notes": notes,
    }
    body: dict[str, Any] = {"event": event, "payload": {"payment": {"entity": entity}}}
    if extra:
        body.update(extra)
    return body


def _payment_id(tag: str) -> str:
    """Unique per run. `webhook_inbox_events` is a durable, global dedupe table, so a
    hardcoded payment id would be claimed by the first run of this suite and answered
    "already seen with different content" by every run after it — the same property
    that makes the receiver safe in production."""
    return f"pay_{tag}_{uuid.uuid4().hex[:12]}"


def _sign(body: dict[str, Any], secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {payments.SIGNATURE_HEADER: signature, "Content-Type": "application/json"}


async def _self_serve_tenant() -> tuple[uuid.UUID, str]:
    token, _ = await _signed_up_user()
    async with _client() as http:
        response = await http.post("/v1/auth/signup", headers=_headers(token), json=_signup_body())
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["tenant_id"]), token


async def test_a_captured_payment_credits_the_wallet() -> None:
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("ABC123")
    raw, headers = _sign(_envelope(payment_id=payment_id, tenant_id=tenant_id))

    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "credited"
    # Money is a STRING on the wire in both directions — never a JSON float.
    assert body["amount_inr"] == "2500.00"
    assert body["balance_inr"] == "2500.00"
    assert isinstance(body["amount_inr"], str) and isinstance(body["balance_inr"], str)
    assert '"amount_inr":"2500.00"' in response.text, "serialized as a string, not a JSON number"

    entries = await _ledger(tenant_id)
    assert entries == [("topup", Decimal("2500.0000"), payment_id)]

    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is False


async def test_the_same_payment_id_delivered_twice_credits_once() -> None:
    """Every payment provider replays. Byte-identical retry AND a re-delivery whose
    envelope differs must both land on the one ledger row — the payment id is the
    permanent key, which is why the ledger's own `ref` is the arbiter."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("REPLAY")
    first_raw, first_headers = _sign(_envelope(payment_id=payment_id, tenant_id=tenant_id))
    # Same payment, different envelope: a provider redelivery carrying extra fields.
    second_raw, second_headers = _sign(
        _envelope(
            payment_id=payment_id,
            tenant_id=tenant_id,
            extra={"account_id": "acc_1", "created_at": 1770000000},
        )
    )

    async with _client() as http:
        first = await http.post("/hooks/v1/razorpay", content=first_raw, headers=first_headers)
        replay = await http.post("/hooks/v1/razorpay", content=first_raw, headers=first_headers)
        redelivered = await http.post(
            "/hooks/v1/razorpay", content=second_raw, headers=second_headers
        )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert redelivered.status_code == 200, redelivered.text
    assert first.json()["status"] == "credited"
    assert replay.json()["status"] == "duplicate"
    assert redelivered.json()["status"] == "duplicate"

    entries = await _ledger(tenant_id)
    assert len(entries) == 1, f"one payment, one ledger row, got {entries}"
    assert entries[0][1] == Decimal("2500.0000")


async def test_the_ledger_reference_is_the_arbiter_even_without_the_inbox() -> None:
    """The inbox is the first line and it expires; the ledger row does not. Called
    directly — as an ARQ retry or a manual replay would — the credit is still once."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("DIRECT")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal("999.00"),
        currency="INR",
    )

    async with tenant_session(tenant_id) as session:
        first = await payments.credit_captured_payment(session, payment=payment)
    async with tenant_session(tenant_id) as session:
        second = await payments.credit_captured_payment(session, payment=payment)

    assert first.recorded is True
    assert second.recorded is False
    assert second.entry_id == first.entry_id
    assert await _ledger(tenant_id) == [("topup", Decimal("999.0000"), payment_id)]


async def test_a_bad_signature_credits_nothing_and_leaves_no_row() -> None:
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("FORGED")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id), secret="whsec_wrong"
    )

    async with _client() as http:
        forged = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        unsigned = await http.post(
            "/hooks/v1/razorpay", content=raw, headers={"Content-Type": "application/json"}
        )

    assert forged.status_code == 401, forged.text
    assert unsigned.status_code == 401, unsigned.text
    assert await _ledger(tenant_id) == [], "an unverified payload never reaches the ledger"

    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events "
                    "WHERE provider = :p AND event_key LIKE :k"
                ),
                {"p": payments.PROVIDER, "k": f"%{payment_id}%"},
            )
        ).scalar()
    assert int(inbox or 0) == 0, "a refused request writes no durable trace of the event"


async def test_an_unconfigured_receiver_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No secret means no way to tell a payment from a forgery. Refusing every event
    is the only safe answer — the same choice the Clerk mirror makes."""
    tenant_id, _ = await _self_serve_tenant()
    monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", None)
    raw, headers = _sign(_envelope(payment_id=_payment_id("NOSECRET"), tenant_id=tenant_id))

    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 502, response.text
    assert response.json()["type"].endswith("/payments_not_configured")
    assert await _ledger(tenant_id) == []


async def test_a_float_amount_is_refused_rather_than_rounded() -> None:
    """Hard rule 7 at the boundary. A captured amount is an integer count of paise; a
    JSON float has already been through binary floating point by the time we see it,
    and ₹2500.10 that arrives as 250010.00000000003 is a dispute."""
    tenant_id, _ = await _self_serve_tenant()
    raw, headers = _sign(
        _envelope(payment_id=_payment_id("FLOAT"), tenant_id=tenant_id, amount=250010.0)
    )

    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/payment_amount_unrecognized")
    assert await _ledger(tenant_id) == []


async def test_paise_convert_to_rupees_exactly() -> None:
    assert payments.paise_to_inr(250000) == Decimal("2500.00")
    assert payments.paise_to_inr(1) == Decimal("0.01")
    assert payments.paise_to_inr(250010) == Decimal("2500.10")
    # A float is refused by name, not rounded — and `True` is an `int` in Python, so
    # the bool check in front of the int check is load-bearing.
    for bad in (2500.10, True, "250000", None):
        with pytest.raises(ProblemError) as refused:
            payments.paise_to_inr(bad)
        assert refused.value.code == "payment_amount_unrecognized"


async def test_a_payment_for_an_unknown_tenant_credits_nothing() -> None:
    missing = uuid.uuid4()
    raw, headers = _sign(_envelope(payment_id=_payment_id("NOWHERE"), tenant_id=missing))
    async with _client() as http:
        unknown = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    untagged_raw, untagged_headers = _sign(
        _envelope(payment_id=_payment_id("UNTAGGED"), tenant_id=None)
    )
    async with _client() as http:
        untagged = await http.post(
            "/hooks/v1/razorpay", content=untagged_raw, headers=untagged_headers
        )

    assert unknown.status_code == 404, unknown.text
    assert untagged.status_code == 422, untagged.text
    assert untagged.json()["type"].endswith("/payment_tenant_unresolved")


async def test_a_non_inr_payment_is_refused() -> None:
    """The ledger is INR (hard rule 7). Crediting a dollar amount as rupees would be a
    100x error in the client's favour and an invisible one in ours."""
    tenant_id, _ = await _self_serve_tenant()
    raw, headers = _sign(
        _envelope(payment_id=_payment_id("USD"), tenant_id=tenant_id, amount=5000, currency="USD")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/payment_currency_unsupported")
    assert await _ledger(tenant_id) == []


async def test_an_uninteresting_event_is_acknowledged_and_ignored() -> None:
    """Razorpay sends more than captures. Anything that is not a capture is ACKed so
    the provider stops retrying, and touches no money."""
    tenant_id, _ = await _self_serve_tenant()
    raw, headers = _sign(
        _envelope(payment_id=_payment_id("AUTH"), tenant_id=tenant_id, event="payment.authorized")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ignored"
    assert await _ledger(tenant_id) == []


async def test_a_credited_payment_carries_an_audit_row() -> None:
    tenant_id, _ = await _self_serve_tenant()
    raw, headers = _sign(_envelope(payment_id=_payment_id("AUDIT"), tenant_id=tenant_id))
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, actor_type, object_type, object_id FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'credit.topup'"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert len(rows) == 1, f"money moved once, so it is audited once: {rows}"
    assert rows[0][1] == "system", "the actor is the payment provider callback, not a person"
    assert rows[0][2] == "credit_ledger"
    assert rows[0][3] == response.json()["entry_id"]


# --- the order intent (the half of Razorpay that is ours) ---------------------


async def test_the_intent_prices_in_paise_and_names_the_tenant() -> None:
    tenant_id, _ = await _self_serve_tenant()
    owner = await _owner_token(tenant_id)

    async with _client() as http:
        response = await http.post(
            "/v1/billing/topups/intent", headers=_headers(owner), json={"amount_inr": "2500.00"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["amount_inr"] == "2500.00", "rupees are a string"
    assert body["amount_paise"] == 250000, "paise are an integer — the provider's unit"
    assert body["currency"] == "INR"
    # The tenant travels in the notes, which is what the webhook resolves it from.
    assert body["notes"][payments.NOTES_TENANT_KEY] == str(tenant_id)
    assert body["provider_order_id"] is None, (
        "server-side order creation is NOT implemented — see payments.py; the field "
        "exists so the honest answer is visible rather than fabricated"
    )


async def test_the_intent_refuses_a_float_and_an_absurd_amount() -> None:
    tenant_id, _ = await _self_serve_tenant()
    owner = await _owner_token(tenant_id)

    async with _client() as http:
        floated = await http.post(
            "/v1/billing/topups/intent", headers=_headers(owner), json={"amount_inr": 2500.10}
        )
        tiny = await http.post(
            "/v1/billing/topups/intent", headers=_headers(owner), json={"amount_inr": "1.00"}
        )

    assert floated.status_code == 422, floated.text
    assert floated.json()["fields"][0]["field"] == "amount_inr"
    assert tiny.status_code == 422, tiny.text
    assert tiny.json()["type"].endswith("/topup_amount_out_of_range")


async def test_the_intent_is_closed_to_anonymous_callers() -> None:
    async with _client() as http:
        response = await http.post("/v1/billing/topups/intent", json={"amount_inr": "2500.00"})
    assert response.status_code == 401, response.text


async def test_a_managed_client_is_invoiced_not_topped_up() -> None:
    """Credits gate the self-serve motion only (billing/service.py's own rule). A
    managed client paying into a wallet would be paying twice."""
    tenant_id, _ = await _self_serve_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :t"), {"t": tenant_id}
        )
    owner = await _owner_token(tenant_id)

    async with _client() as http:
        response = await http.post(
            "/v1/billing/topups/intent", headers=_headers(owner), json={"amount_inr": "2500.00"}
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/topup_not_available")


async def _owner_token(tenant_id: uuid.UUID) -> str:
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:i, :c, :e, now(), now())"
            ),
            {"i": user_id, "c": clerk_id, "e": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{clerk_id}"


# --- boot assertions ----------------------------------------------------------


async def test_every_route_declares_a_permission_or_is_public() -> None:
    """The assertion the integrator's `main.py` runs (BACKEND-PATTERNS §7), run here so
    a missing declaration fails in this module rather than at their mount.

    `/v1/auth/signup` and `/hooks/v1/razorpay` are on PUBLIC_PREFIXES by construction:
    no permission can gate a caller who has no organization yet, and none can gate a
    payment provider. Their locks are the quota + verified identity, and the HMAC.
    """
    application = FastAPI()
    application.include_router(signup_router)
    application.include_router(topup_router)
    application.include_router(webhook_router)
    assert_policy_registry_complete(application)
