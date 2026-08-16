"""What the PART 6 adversarial pass broke, pinned so it stays closed.

Everything here is driven the way an attacker would drive it — over HTTP, with valid
credentials of the wrong kind, or with a header spelled a way nobody's client spells it.
Each test names the property it defends rather than the code path it walks.

  1. **IDOR over every `{id}` route in the client path space**, with a NEIGHBOUR's real
     object ids and a valid token. `tests/rls_sweep_test.py` proves the policies exist and
     `tests/realm_boundary_test.py` drives the mutating routes with *invented* uuids; this
     drives them with ids that really do name a row, in another tenant, so a handler that
     read the row before checking the tenant would answer 200 here and nowhere else.

  2. **One credential is one rate-limit bucket.** The per-caller dimension keyed on the
     RAW `Authorization` header, so the same session respelled — case, extra spaces —
     was several callers, unboundedly many with padding.

  3. **A slow JWKS endpoint must not stop the process.** `PyJWKClient` fetches over
     `urllib`, synchronously; called from the event loop it stalls every other request,
     and an anonymous caller can force one fetch per request by varying a `kid`.

  4. **The body cap counts bodies that declare no length.** `Transfer-Encoding: chunked`
     walked past a `Content-Length`-only check, and the edge's own ceiling is 25 MiB.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant, and nothing asserts a global count.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import jwt
import pytest
from apps.api.admin import service as admin_service
from apps.api.core import auth as auth_module
from apps.api.core import ratelimit
from apps.api.core.context import bearer_token
from apps.api.core.ratelimit import LimitProfile
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


def _client(peer: str | None = None) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer or _address(), 12345)),
        base_url="http://api",
    )


def _address() -> str:
    """A CALL-unique documentation address (RFC 3849). Unique per call so no two tests
    and no two runs share a limiter bucket."""
    return f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Adversarial Clinic",
        slug=f"adv-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_member(tenant_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """A real `users` row with a real owner membership. Returns (user_id, dev token)."""
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return user_id, f"dev:client:{clerk_id}"


# --- 1. IDOR ------------------------------------------------------------------------


async def _seed_one_of_everything(tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    """One real row of each kind a `{...}` client route addresses.

    Written straight to the tables under the TENANT's own session rather than through the
    API: several of these have their own creation rules (a campaign needs a compliance
    gate, a KB source needs a published agent) and this test is about the READ side. The
    session is `tenant_session`, so every insert is itself subject to the policy under
    test — a row that landed with the wrong `tenant_id` would be refused here rather than
    quietly making the sweep vacuous.
    """
    ids: dict[str, str] = {"user_id": str(user_id)}
    async with tenant_session(tenant_id) as s:
        agent_id = (
            await s.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
            )
        ).scalar_one()
        ids["agent_id"] = str(agent_id)

        rows: tuple[tuple[str, str, str, dict[str, object]], ...] = (
            (
                "lead_id",
                "leads",
                "(id, tenant_id, agent_id, phone_e164, source) "
                "VALUES (:i, :t, :a, '+919000000001', 'manual')",
                {},
            ),
            (
                "call_id",
                "calls",
                "(id, tenant_id, agent_id, engine_call_id, direction, status) "
                "VALUES (:i, :t, :a, :engine_call, 'outbound', 'completed')",
                {"engine_call": f"eng-{uuid.uuid4().hex[:10]}"},
            ),
            (
                "campaign_id",
                "campaigns",
                "(id, tenant_id, agent_id, name, classification) "
                "VALUES (:i, :t, :a, 'Adversarial campaign', 'service')",
                {},
            ),
            (
                "view_id",
                "lead_saved_views",
                "(id, tenant_id, user_id, name) VALUES (:i, :t, :u, 'Adversarial view')",
                {},
            ),
            (
                "entry_id",
                "dnc_list",
                "(id, tenant_id, phone_e164, scope) VALUES (:i, :t, '+919000000002', 'tenant')",
                {},
            ),
            (
                "webhook_id",
                "inbound_webhooks",
                "(id, tenant_id, source, secret_ref) VALUES (:i, :t, 'website_form', :ref)",
                {"ref": f"secret/{uuid.uuid4().hex[:8]}"},
            ),
            (
                "endpoint_id",
                "outbound_webhooks",
                "(id, tenant_id, kind, events, url) "
                "VALUES (:i, :t, 'webhook', ARRAY['lead.created'], 'https://crm.example/hook')",
                {},
            ),
            (
                "source_id",
                "kb_sources",
                "(id, tenant_id, agent_id, kind, name) "
                "VALUES (:i, :t, :a, 'text', 'Adversarial kb')",
                {},
            ),
            (
                "invitation_id",
                "invitations",
                "(id, tenant_id, email, role, token_hash) VALUES (:i, :t, :email, 'staff', :hash)",
                {"email": f"inv-{uuid.uuid4().hex[:6]}@example.com", "hash": uuid.uuid4().hex},
            ),
        )
        for key, table, clause, extra in rows:
            row_id = uuid.uuid4()
            await s.execute(
                text(f"INSERT INTO {table} {clause}"),
                {"i": row_id, "t": tenant_id, "a": agent_id, "u": user_id, **extra},
            )
            ids[key] = str(row_id)
    return ids


#: (method, template, body). The body is the SMALLEST one that passes validation, because
#: a 422 would mean the sweep never reached the tenant check — see the assertion below.
_IDOR_ROUTES: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("GET", "/v1/agents/{agent_id}", {}),
    ("GET", "/v1/agents/{agent_id}/engine-state", {}),
    ("GET", "/v1/agents/{agent_id}/experiment", {}),
    ("GET", "/v1/agents/{agent_id}/pending", {}),
    ("GET", "/v1/calls/{call_id}", {}),
    ("GET", "/v1/calls/{call_id}/callback", {}),
    ("POST", "/v1/calls/{call_id}/callback", {}),
    ("GET", "/v1/calls/{call_id}/recording", {}),
    ("GET", "/v1/calls/{call_id}/transcript/raw", {}),
    ("GET", "/v1/campaigns/{campaign_id}", {}),
    (
        "POST",
        "/v1/campaigns/{campaign_id}/consent-provenance",
        {"source": "existing_customer", "collected_at": "2026-01-01T00:00:00+00:00"},
    ),
    ("POST", "/v1/campaigns/{campaign_id}/launch", {}),
    ("GET", "/v1/campaigns/{campaign_id}/launch-check", {}),
    ("POST", "/v1/campaigns/{campaign_id}/pause", {}),
    ("POST", "/v1/campaigns/{campaign_id}/recurrence", {"days": [1], "at": "10:00"}),
    ("POST", "/v1/campaigns/{campaign_id}/resume", {}),
    ("POST", "/v1/campaigns/{campaign_id}/schedule", {"start_at": "2027-01-01T10:00:00+05:30"}),
    ("DELETE", "/v1/campaigns/{campaign_id}/schedule", {}),
    ("DELETE", "/v1/dnc/{entry_id}", {}),
    ("DELETE", "/v1/integrations/endpoints/{endpoint_id}", {}),
    ("DELETE", "/v1/invitations/{invitation_id}", {}),
    ("DELETE", "/v1/lead-sources/{webhook_id}", {}),
    ("POST", "/v1/lead-sources/{webhook_id}/enable", {}),
    ("POST", "/v1/lead-sources/{webhook_id}/meta/redrive", {}),
    ("POST", "/v1/lead-sources/{webhook_id}/meta/setup", {}),
    ("POST", "/v1/lead-sources/{webhook_id}/rotate-secret", {}),
    ("POST", "/v1/lead-sources/{webhook_id}/test", {"payload": {"name": "x"}}),
    ("PATCH", "/v1/leads/views/{view_id}", {}),
    ("DELETE", "/v1/leads/views/{view_id}", {}),
    ("GET", "/v1/leads/{lead_id}", {}),
    ("PATCH", "/v1/leads/{lead_id}", {}),
    ("GET", "/v1/leads/{lead_id}/timeline", {}),
    ("PATCH", "/v1/members/{user_id}", {"role": "staff", "expected_role": "owner"}),
    ("DELETE", "/v1/members/{user_id}", {}),
)


async def test_a_neighbours_object_id_is_not_found_and_never_forbidden() -> None:
    """Every `{id}` route in the client path space, driven with tenant A's REAL ids and
    tenant B's valid session.

    TWO PROPERTIES, and the second is the one worth having:

      - nothing answers 2xx. That is the security claim.
      - every refusal is **404**, not 403. That is the claim about WHERE the guarantee
        lives. A 403 would mean a Python `if` compared two tenant ids and refused — which
        works until somebody refactors the comparison out. A 404 means the row was not
        visible to the statement at all, i.e. the policy in the database did it, and no
        handler had to remember anything. It is also the honest answer: "that id is not
        yours" and "there is no such id" are the same fact from inside a tenant, and
        distinguishing them would publish the existence of a neighbour's rows.

    A 422 fails too, and deliberately: it means body validation answered before the tenant
    check, so the route was never actually exercised for the property under test.
    """
    org_a, org_b = await _make_org(), await _make_org()
    tenant_a = uuid.UUID(str(org_a["id"]))
    user_a, _token_a = await _make_member(tenant_a)
    _user_b, token_b = await _make_member(uuid.UUID(str(org_b["id"])))
    ids = await _seed_one_of_everything(tenant_a, user_a)

    headers = {"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])}
    offenders: list[str] = []
    async with _client() as http:
        for method, template, body in _IDOR_ROUTES:
            path = template
            for key, value in ids.items():
                path = path.replace("{" + key + "}", value)
            assert "{" not in path, f"{template}: the sweep has no id for this parameter"
            response = await http.request(method, path, headers=headers, json=body)
            payload = response.json() if response.content else {}
            code = (
                str(payload.get("type", "")).rsplit("/", 1)[-1]
                if isinstance(payload, dict)
                else "<ok>"
            )
            if response.status_code != 404 or code != "not_found":
                offenders.append(f"{method} {template} -> {response.status_code} {code}")

    assert not offenders, (
        "a neighbouring tenant's session reached these with real ids, or was refused by "
        f"something other than the row simply not being there: {offenders}"
    )


async def test_the_idor_sweep_is_driving_routes_that_exist() -> None:
    """Non-vacuity. Every template above must still be a mounted route: a renamed path
    would otherwise turn each 404 into a routing 404 and the sweep into a green no-op."""
    from apps.api.core.rbac import iter_api_routes

    mounted = {(method, route.path) for route in iter_api_routes(app) for method in route.methods}
    missing = [f"{m} {t}" for m, t, _ in _IDOR_ROUTES if (m, t) not in mounted]
    assert not missing, f"the sweep addresses routes that no longer exist: {missing}"
    assert len(_IDOR_ROUTES) >= 30, f"only {len(_IDOR_ROUTES)} routes swept"


# --- 2. one credential, one bucket ---------------------------------------------------


@pytest.fixture
def tight_client_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`client_api` turned down to a number a test can reach, on an hour-long window so
    no wall-clock boundary can fall mid-test (the reason `rate_limit_behaviour_test`
    widens rather than narrows). The profile NAME is unchanged, so this exercises the
    real Redis key layout."""
    monkeypatch.setitem(
        ratelimit.PROFILES,
        "client_api",
        LimitProfile("client_api", per_client=3, per_tenant=900, window_s=3600),
    )
    yield


def test_one_session_is_one_credential_however_the_header_is_typed() -> None:
    """The parser, at the unit. Five spellings, one token."""
    token = "dev:client:user_abc"
    spellings = (
        f"Bearer {token}",
        f"bearer {token}",
        f"BEARER {token}",
        f"Bearer  {token}",
        f"Bearer {token}   ",
    )
    assert {bearer_token(value) for value in spellings} == {token}
    # And what is NOT a bearer credential says so, rather than becoming one.
    assert bearer_token(None) is None
    assert bearer_token("") is None
    assert bearer_token("Bearer") is None
    assert bearer_token("Bearer    ") is None
    assert bearer_token("Basic dXNlcjpwYXNz") is None
    assert bearer_token("Bearer dev:client:a\x00b") is None


async def test_one_credential_cannot_multiply_its_own_rate_limit_budget(
    tight_client_api: None,
) -> None:
    """THE DEFECT, over HTTP: spend the budget, then keep going by respelling the header.

    Each respelling authenticates identically — the control is that the first four
    requests came back 200 and the fifth 429, so the session is real and the limit is
    real — and each used to land in its own Redis bucket, because the key was a hash of
    the raw header rather than of the credential. Padding with spaces makes that
    unbounded, which is why the last spelling is the padded one.
    """
    org = await _make_org()
    _user_id, token = await _make_member(uuid.UUID(str(org["id"])))
    slug = {"X-Org-Slug": str(org["slug"])}

    async with _client() as http:
        spent = [
            (await http.get("/v1/agents", headers={"Authorization": f"Bearer {token}", **slug}))
            for _ in range(4)
        ]
        codes = [r.status_code for r in spent]
        assert codes == [200, 200, 200, 429], (
            f"the control: this session works and this limit bites — {codes}"
        )
        respellings = [
            f"bearer {token}",
            f"BEARER {token}",
            f"Bearer  {token}",
            f"Bearer {token} ",
        ]
        after = [
            (await http.get("/v1/agents", headers={"Authorization": value, **slug})).status_code
            for value in respellings
        ]

    assert after == [429, 429, 429, 429], (
        f"one session bought {after.count(200)} extra budgets by retyping its own header"
    )


# --- 3. the JWKS fetch is not on the event loop --------------------------------------


_SLOW_JWKS_S = 1.0


class _SlowJwks:
    """Stands in for `PyJWKClient` with a JWKS endpoint that takes a second.

    A BLOCKING sleep, because that is exactly what `urllib.request.urlopen` is: the point
    of the test is that a synchronous call in this position stops the loop, and an
    `await asyncio.sleep` here would be testing a different function.
    """

    def __init__(self) -> None:
        self.calls = 0

    def get_signing_key_from_jwt(self, token: str) -> object:
        self.calls += 1
        time.sleep(_SLOW_JWKS_S)
        # What an unknown `kid` really ends in, so `verify_token`'s dependency branch is
        # the one that runs and the request finishes as a 503 rather than an exception.
        raise jwt.exceptions.PyJWKClientConnectionError("slow endpoint")


async def test_a_slow_jwks_endpoint_does_not_stop_every_other_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An anonymous caller with an unknown `kid` must not be able to stall the process.

    `PyJWKClient.get_signing_key` refetches the whole key set whenever the `kid` is not
    in it, and a failed lookup is never memoised — so one fetch per request is a thing a
    stranger can ask for, and `/healthz*` carries no limit profile at all. Called on the
    loop, one second of JWKS latency is one second in which this process serves nobody.

    MEASURED AS "did the loop keep running", not as elapsed wall time: the counter below
    is iterations of a 10ms sleep completed WHILE the request is in flight. Blocked, that
    is 0 or 1; free, it is dozens. A ratio, so a slow CI box moves both sides together.
    """
    slow = _SlowJwks()
    monkeypatch.setattr(auth_module, "_jwk_client", lambda realm: slow)
    # Clerk "configured", so `_verify_dev_token` declines and the JWKS path is reached.
    configured = get_settings().model_copy(
        update={"clerk_client_secret_key": "sk_test_x", "clerk_admin_secret_key": "sk_test_y"}
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: configured)
    unknown_kid = jwt.encode(
        {"sub": "x"}, "k" * 32, algorithm="HS256", headers={"kid": "no-such-key"}
    )

    ticks = 0
    stop = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    async with _client() as http:
        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.05)  # let the heartbeat settle before we start counting
        ticks = 0
        response = await http.get("/v1/agents", headers={"Authorization": f"Bearer {unknown_kid}"})
        during = ticks
        stop.set()
        await beat

    assert slow.calls == 1, f"the JWKS path was not exercised ({slow.calls} calls)"
    assert response.status_code == 502, response.text
    assert response.json()["type"].endswith("/auth_provider_unavailable"), response.text
    assert during >= 10, (
        f"the event loop completed {during} ticks during a {_SLOW_JWKS_S}s JWKS fetch — "
        "it was blocked, so every other in-flight request was stalled with it"
    )


def test_the_jwks_client_does_not_hold_a_thread_for_pyjwts_default_half_minute() -> None:
    """The other half: off the loop is not free, it is a worker thread. PyJWKClient's
    default timeout is 30s, which is 30s of a thread per hostile request."""
    assert auth_module.JWKS_FETCH_TIMEOUT_S <= 10.0
    auth_module._jwk_clients.pop("client", None)
    settings = get_settings().model_copy(update={"clerk_client_secret_key": "sk_test_x"})
    original = auth_module.get_settings
    auth_module.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        assert auth_module._jwk_client("client").timeout == auth_module.JWKS_FETCH_TIMEOUT_S
    finally:
        auth_module.get_settings = original  # type: ignore[assignment]
        auth_module._jwk_clients.pop("client", None)


# --- 4. the body cap counts what it cannot be told ----------------------------------


async def test_an_oversized_body_is_refused_whether_or_not_it_declares_its_length() -> None:
    """`Content-Length` is optional on the wire; the cap must not be.

    Both halves are driven in one test so the assertion is a DIFFERENCE rather than a
    status code: the declared request is the control, and it was already refused. The
    chunked one is the same bytes with one header changed, and it used to be buffered
    whole by `await request.json()` — nginx's `client_max_body_size` on the api vhost is
    25m (`infra/nginx/calevate.conf.template`), so the edge was not the backstop that
    argument assumed.

    `/v1/auth/signup` is the target because it is unauthenticated: the caller who can do
    this needs no account, which is what makes the memory the interesting part.
    """
    payload = b"x" * (5 * 1024 * 1024)
    assert len(payload) > 2 * 1024 * 1024, "the body must actually exceed MAX_BODY_BYTES"

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(payload), 65536):
            yield payload[start : start + 65536]

    async with _client() as http:
        declared = await http.post(
            "/v1/auth/signup", content=payload, headers={"Content-Type": "application/json"}
        )
        chunked = await http.post(
            "/v1/auth/signup", content=chunks(), headers={"Content-Type": "application/json"}
        )
        # The control on the OTHER side: an ordinary small body still reaches the handler.
        small = await http.post("/v1/auth/signup", json={})

    assert declared.status_code == 413, declared.text
    assert chunked.status_code == 413, (
        f"a chunked body of {len(payload)} bytes was accepted: {chunked.status_code}"
    )
    for name, response in (("declared", declared), ("chunked", chunked)):
        assert response.json()["type"].endswith("/payload_too_large"), f"{name}: {response.text}"
    assert small.status_code not in (413, 500), (
        f"the cap now refuses ordinary requests too: {small.status_code} {small.text}"
    )
