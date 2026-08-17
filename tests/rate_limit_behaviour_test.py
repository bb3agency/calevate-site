"""What the limiter DOES, on the live app (plan Part 3, items a-c).

The census next door proves every route is covered by a named profile. This one proves
the profiles isolate the things they claim to isolate, because a limit that fires on the
wrong bucket is worse than no limit — it is an outage with an explanation attached.

Four properties, each of which was untrue before this slice:

1. **Two callers do not share a bucket.** They did: the unauthenticated fallback keyed on
   the socket peer, which behind nginx is one address for the whole internet.
2. **One tenant's users share a tenant bucket, and a neighbour is untouched.** There was
   no tenant dimension at all — the ordinary Indian SMB, several staff behind one NAT,
   was rate-limited as if it were one abusive caller.
3. **A lead-intake flood does not 429 the payment webhook.** All five `/hooks` routes
   shared one profile.
4. **The tenant budget is spent once per request**, not once per dependency that happens
   to resolve a principal.

Every subject here is run-unique (a fresh tenant, a fresh address, a fresh `webhook_id`)
because the suite shares one Redis with other work and a fixed-window counter has a
memory: a hardcoded bucket would inherit whatever the last run left in it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from apps.api.admin import service as admin_service
from apps.api.core import middleware, ratelimit
from apps.api.core.ratelimit import LimitProfile
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

#: An hour, so no window boundary can fall inside a test. See the `tight` fixture.
_WINDOW_S = 3600


def _address() -> str:
    """A CALL-unique documentation address (RFC 3849's `2001:db8::/32`).

    IPv6, and not RFC 5737's `198.51.100.0/24`, for a reason this file learned the hard
    way: a /24 has 254 addresses, the windows below are an hour long, and the suite runs
    many times an hour — so a "quiet neighbour" address would eventually inherit an
    earlier run's count and 429 for a reason the test is not about. The documentation
    prefix is unroutable in both families; only the size differs.
    """
    return f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"


def _trusted_peer() -> str:
    """A call-unique address inside `TRUSTED_PROXY_CIDRS` — i.e. what our own nginx looks
    like to the container, without two tests (or two runs) sharing one bucket."""
    raw = uuid.uuid4().int
    return f"127.{raw % 254 + 1}.{raw // 254 % 254 + 1}.{raw // 64516 % 254 + 1}"


def _client(peer: str | None = None) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer or _address(), 12345)),
        base_url="http://api",
    )


@pytest.fixture
def tight(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Turn the profiles under test down to numbers a test can reach.

    The PROFILE NAMES are unchanged, deliberately: the name is the Redis key namespace,
    so patching the numbers exercises the real key layout rather than a parallel one.

    THE WINDOW IS WIDENED, NOT NARROWED, and that is what makes these tests deterministic.
    A fixed window resets on a wall-clock boundary, so with the production 60s window a
    boundary landing between the second and third request of a flood silently resets the
    counter and the flood is not refused — a test that fails for a reason that is not the
    code. An hour-long window cannot roll mid-test; every subject is call-unique, so
    nothing carries over between tests or runs either.
    """
    monkeypatch.setitem(
        ratelimit.PROFILES,
        "client_api",
        LimitProfile("client_api", per_client=3, per_tenant=2, window_s=_WINDOW_S),
    )
    monkeypatch.setitem(
        ratelimit.PROFILES,
        "webhook_ingest",
        LimitProfile(
            "webhook_ingest",
            per_client=1000,
            per_tenant=2,
            window_s=_WINDOW_S,
            tenant_from_last_path_segment=True,
        ),
    )
    yield


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Rate Limit Clinic",
        slug=f"rl-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_member(tenant_id: uuid.UUID) -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
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
    return f"dev:client:{user_id}"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- 1. the per-caller dimension ----------------------------------------------------


async def test_one_address_flooding_does_not_refuse_another(tight: None) -> None:
    """Unauthenticated on purpose: the caller dimension is what an anonymous request is
    keyed on, and it is the dimension that was broken. 401 is the healthy answer here —
    what matters is that it is not 429."""
    noisy, quiet = _address(), _address()
    async with _client(noisy) as http:
        for _ in range(4):
            last = await http.get("/v1/agents")
    assert last.status_code == 429, last.text
    assert last.headers.get("Retry-After")

    async with _client(quiet) as http:
        neighbour = await http.get("/v1/agents")
    assert neighbour.status_code == 401, "a neighbour's address inherited the flood"


async def test_a_stranger_cannot_buy_a_fresh_bucket_by_inventing_a_credential(
    tight: None,
) -> None:
    """THE HALF D-131 NAMED AND LEFT: pre-auth, nothing can tell a credential from a guess.

    The per-caller bucket keys on the bearer token when there is one, so `Bearer <random>`
    on every request minted a brand-new bucket every time and an anonymous caller opted
    out of this dimension entirely — while every honest anonymous caller stayed inside it,
    and while each crafted token drove one JWKS refetch in `core.auth._signing_key_for`.

    The rule is now that presenting a credential never buys more room than presenting
    none, so a rotating flood is refused at exactly the ceiling an unauthenticated flood
    from the same address meets. `per_client=3` here, and the fourth request is refused
    whether or not it carries an `Authorization` header.
    """
    async with _client(_trusted_peer()) as http:
        edge = {"CF-Connecting-IP": _address()}
        for _ in range(4):
            last = await http.get(
                "/v1/agents",
                headers={**edge, "Authorization": f"Bearer {uuid.uuid4().hex}"},
            )
    assert last.status_code == 429, (
        f"a rotating bearer token minted an unlimited number of buckets: {last.status_code}"
    )
    assert last.headers.get("Retry-After")


async def test_an_office_behind_one_address_is_not_throttled_for_being_several_people(
    tight: None,
) -> None:
    """The control on the fix above, and the reason MINTING is charged and not requests.

    Two staff on two sessions behind one NAT — the ordinary Indian SMB, and the case the
    tenant dimension exists for. Six requests, `per_client=3`: each session spends its own
    three, and the shared address pays TWO units, one per session created, so nothing is
    refused. Charge the address per REQUEST instead — the obvious alternative — and the
    fourth request here is a 429 for a caller that did nothing wrong. That is what this
    test fails on; the status of the individual calls is not its business (an unverified
    token is refused by the verifier, and which refusal depends on how Clerk is
    configured), only that none of them is a rate limit.
    """
    one, two = uuid.uuid4().hex, uuid.uuid4().hex
    async with _client(_trusted_peer()) as http:
        edge = {"CF-Connecting-IP": _address()}
        codes = [
            (
                await http.get("/v1/agents", headers={**edge, "Authorization": f"Bearer {token}"})
            ).status_code
            for _ in range(3)
            for token in (one, two)
        ]
    assert 429 not in codes, f"a shared address was throttled for holding two sessions: {codes}"


async def test_two_callers_behind_the_same_edge_are_told_apart(tight: None) -> None:
    """THE DEFECT, at the limiter rather than at the signup quota.

    Every real request arrives from one socket peer — our nginx — so keying the
    unauthenticated fallback on that peer put the entire internet in one bucket: the
    declared 240/min was a platform-wide ceiling for anonymous traffic, and one caller
    could spend it. Both clients below have the IDENTICAL peer and differ only in the
    address the edge vouched for, which is the shape the old code could not see.
    """
    noisy, quiet = _address(), _address()
    async with _client(_trusted_peer()) as http:
        for _ in range(4):
            last = await http.get("/v1/agents", headers={"CF-Connecting-IP": noisy})
        assert last.status_code == 429, last.text
        neighbour = await http.get("/v1/agents", headers={"CF-Connecting-IP": quiet})
    assert neighbour.status_code == 401, "one caller spent every caller's budget"


# --- 2. the per-tenant dimension ----------------------------------------------------


async def test_a_tenants_users_share_a_tenant_budget_and_a_neighbour_does_not(
    tight: None,
) -> None:
    """`per_tenant=2` with `per_client=3`: the third request from the tenant is refused
    even though no single caller has reached its own limit, which is the whole point of
    the dimension — and tenant B, one HTTP hop later, is unaffected."""
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    first = await _make_member(tenant_id)
    second = await _make_member(tenant_id)
    neighbour_org = await _make_org()
    neighbour = await _make_member(uuid.UUID(str(neighbour_org["id"])))

    async with _client() as http:
        one = await http.get("/v1/agents", headers=_auth(first))
        two = await http.get("/v1/agents", headers=_auth(second))
        three = await http.get("/v1/agents", headers=_auth(first))
        other_tenant = await http.get("/v1/agents", headers=_auth(neighbour))

    assert one.status_code == 200, one.text
    assert two.status_code == 200, two.text
    assert three.status_code == 429, three.text
    assert three.json()["type"].endswith("/rate_limited")
    assert other_tenant.status_code == 200, "the neighbour tenant paid for someone else's traffic"


async def test_the_tenant_budget_is_spent_once_per_request_not_once_per_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /v1/agents` resolves a principal TWICE — once through `Depends(Session)` →
    `tenant_of` → `current_any`, and once inside `requires("agents:read")`, which calls
    the dependency directly rather than through `Depends` and so misses FastAPI's
    per-request cache.

    With a budget of one, an uncharged-once implementation refuses the FIRST request.
    That is the signature this test exists for: a limiter whose effective ceiling depends
    on which dependencies a route happens to declare does not mean what it says.
    """
    monkeypatch.setitem(
        ratelimit.PROFILES,
        "client_api",
        LimitProfile("client_api", per_client=50, per_tenant=1, window_s=_WINDOW_S),
    )
    org = await _make_org()
    token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        first = await http.get("/v1/agents", headers=_auth(token))
        second = await http.get("/v1/agents", headers=_auth(token))

    assert first.status_code == 200, "the request was charged more than once"
    assert second.status_code == 429, second.text


# --- 3. the /hooks split ------------------------------------------------------------


async def test_a_lead_intake_flood_does_not_refuse_the_payment_webhook(tight: None) -> None:
    """The finding this profile split exists for. The three refusals are the ingest
    surface's own; the payment callback and the identity mirror are on their own buckets,
    and a second lead source is on its own too.

    The status codes of the surviving calls are deliberately NOT asserted to be any one
    value — an unsigned payment callback is refused by its own verifier, an unknown lead
    source is a 404, and neither is this test's business. The assertion is that it is not
    429. (The refusal also lands BEFORE routing, which is the point of doing it in
    middleware: a flood of garbage `webhook_id`s must cost us a Redis INCR, not a route
    match and a body parse.)
    """
    flooded = str(uuid.uuid4())
    quiet_source = str(uuid.uuid4())
    async with _client() as http:
        for _ in range(3):
            last = await http.post(f"/hooks/v1/ingest/{flooded}", json={"name": "x"})
        assert last.status_code == 429, last.text

        payment = await http.post("/hooks/v1/razorpay", json={})
        identity = await http.post("/hooks/v1/clerk", json={})
        other_source = await http.post(f"/hooks/v1/ingest/{quiet_source}", json={"name": "x"})

    assert payment.status_code != 429, "a lead flood 429'd the payment webhook"
    assert identity.status_code != 429, "a lead flood 429'd the identity mirror"
    assert other_source.status_code != 429, "one lead source 429'd another"


# --- 4. the failure policy ----------------------------------------------------------


async def test_an_edge_that_stopped_vouching_for_callers_alerts_rather_than_degrading_quietly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trusted peer with no `CF-Connecting-IP` outside `local` means nginx stopped
    setting it, or something reached the container without passing nginx.

    Nothing fails when that happens — the request still serves, `audit_log.ip` just goes
    NULL and every anonymous caller quietly shares one bucket — which is exactly why it
    has to alert. The receiver already alerts on the identical condition
    (`webhook_source_rejected`, detail "client ip not established"); this is the API half
    of one incident, not a second one.
    """
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        middleware,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )
    monkeypatch.setattr(get_settings(), "app_env", "staging")
    async with _client(_trusted_peer()) as http:
        answered = await http.get("/v1/agents")

    assert answered.status_code == 401, "the degraded path must still serve the request"
    assert ("ROUTE_HANDLER", "client_ip_unresolved") in fired


def _broken_redis() -> None:
    raise ConnectionError("redis is down")


async def test_the_limiter_fails_open_when_redis_is_gone(
    tight: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limiter outage must never 500 or 429 the platform: the edge's `limit_req` zones
    are still standing, and Redis is not a system of record here."""
    monkeypatch.setattr(ratelimit, "get_redis", _broken_redis)
    async with _client() as http:
        for _ in range(6):
            last = await http.get("/v1/agents")
    assert last.status_code == 401, last.text


async def test_the_signup_quota_fails_closed_when_the_same_redis_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one deliberate exception, and the reason `consume` takes a policy rather than
    being copied: nothing but Redis bounds an unattended tenant factory, so losing it
    means the endpoint is unavailable, not unguarded.

    503 rather than 429, because the caller hit no limit — sending them away for an hour
    over our outage would be a lie with a `Retry-After` on it. This behaviour was
    documented and untested before the two limiters became one; it is the branch a
    refactor could silently flip.
    """
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)
    monkeypatch.setattr(ratelimit, "get_redis", _broken_redis)
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with _client() as http:
        refused = await http.post(
            "/v1/auth/signup",
            headers={"Authorization": f"Bearer dev:client:{user_id}"},
            json={
                "business_name": "Sunrise Dental",
                "slug": f"rl-{uuid.uuid4().hex[:8]}",
                "vertical_template": "clinic",
                "language": "te-IN",
            },
        )
    assert refused.status_code == 503, refused.text
    assert refused.json()["type"].endswith("/signup_unavailable")
    assert refused.headers.get("Retry-After") == "60"
