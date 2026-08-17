"""Entering a tenant needs a GRANT, and the grant is bound to what it authorises.

D-22 / SECURITY-COMPLIANCE §5. The spec is "session start + every page view
audit-logged". The read half shipped first (`tests/impersonation_audit_test.py`); this
file is about the half that did not: `admin.impersonation_started` was written by an
endpoint that minted nothing and that the console never called, so the row was simply
absent for every real session and the permission named after the act did not gate it.

What is asserted here, in the order a reviewer should read it:

  1. the THREE-WAY REFUSAL — absent, expired, wrong tenant — plus the two the design
     also needs: malformed, and another operator's;
  2. the REPLAY, stated as its own test: a grant minted for one client, presented
     against another, is refused. That is the property that makes this better than the
     header it replaces rather than merely more ceremonious;
  3. `admin.impersonation_started` is written once per GRANT, not per request;
  4. D-22's read-only rule still holds under a perfectly valid grant;
  5. revocation mid-grant: losing the permission refuses a grant that has not expired.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant, and nothing asserts a global row count.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from apps.api.admin import service as admin_service
from apps.api.core import impersonation as grant_module
from apps.api.core.errors import ProblemError
from apps.api.core.impersonation import (
    ACTOR_CLAIM,
    GRANT_ALGORITHM,
    GRANT_AUDIENCE,
    GRANT_TTL,
    mint_grant,
)
from apps.api.core.rbac import ROLE_PERMISSIONS
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

GRANT_PATH = "/v1/admin/impersonation-grants"
STARTED_ACTION = "admin.impersonation_started"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> tuple[uuid.UUID, str]:
    """(admin_users.id, dev bearer token). Same idiom as the other admin suites."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return admin_id, f"dev:admin:{admin_id}"


async def _make_org() -> dict[str, Any]:
    return await admin_service.create_organization(
        name="Grant Clinic",
        slug=f"gr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


def _headers(token: str, slug: str, grant: str | None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-Impersonate-Org": slug}
    if grant is not None:
        headers["X-Impersonation-Grant"] = grant
    return headers


async def _mint_over_http(http: AsyncClient, token: str, slug: str) -> str:
    """Mint through the ROUTE, not the helper — this is the console's path."""
    response = await http.post(
        GRANT_PATH, headers={"Authorization": f"Bearer {token}"}, json={"slug": slug}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == slug
    return str(body["grant"])


async def view_as_headers(http: AsyncClient, token: str, slug: str, **extra: str) -> dict[str, str]:
    """Headers for one D-22 view-as request: the operator's token, the tenant it
    addresses, and the grant that authorises it.

    IMPORTED BY THE OTHER SUITES rather than copied into them, and the reason matters
    for what those suites assert: most of them exercise D-22's READ-ONLY rule by making
    a mutation while impersonating and requiring 403. Without a real grant those tests
    would still be green — for the wrong reason, refused before the rule they exist to
    pin was ever reached. Minting here keeps every one of them honest.
    """
    grant = await _mint_over_http(http, token, slug)
    return {
        "Authorization": f"Bearer {token}",
        "X-Impersonate-Org": slug,
        "X-Impersonation-Grant": grant,
        **extra,
    }


async def _started_rows(tenant_id: uuid.UUID) -> list[Any]:
    """`admin.impersonation_started` entries for ONE tenant, oldest first.

    `audit_log` is not tenant-RLS'd (the hash chain is global), so this reads under the
    untenanted session and filters by tenant itself — same as the read-path suite.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, tenant_id, object_type, object_id, ip, at "
                    "FROM audit_log WHERE action = :action AND tenant_id = :tid "
                    "ORDER BY at ASC, id ASC"
                ),
                {"action": STARTED_ACTION, "tid": tenant_id},
            )
        ).all()


# ---------------------------------------------------------------- the happy path


async def test_a_minted_grant_opens_the_tenant() -> None:
    """The control has to work, or every refusal below is asserting a broken feature."""
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        grant = await _mint_over_http(http, token, str(org["slug"]))
        response = await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), grant))

    assert response.status_code == 200, response.text


# ------------------------------------------------------------ the refusal paths


async def test_the_bare_header_no_longer_reaches_a_tenant() -> None:
    """REFUSAL ONE: absent.

    This is the defect, stated as the test that passed before the fix and must fail
    after it. `apps/web/src/lib/api/admin.ts` sent exactly this — an admin token plus
    the slug — and the API let it in, which is why `admin.impersonation_started` was
    missing for every session that ever happened.

    Fails CLOSED: refused, not silently downgraded to a plain admin session (which
    would have answered 200 with the operator's own empty scope) and not upgraded.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        response = await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), None))

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["type"].endswith("/impersonation_grant_required"), body
    assert body["kind"] == "permission"
    assert body["remediation"], "a refusal an operator meets must say what to do next"


async def test_an_expired_grant_is_refused() -> None:
    """REFUSAL TWO: expired.

    Minted through the real function with the clock moved, so the expiry being enforced
    is the token's own `exp` and not a second opinion computed somewhere else.

    Its own machine code, because it is the one refusal with a silent remedy: the
    console re-mints and retries rather than showing the operator anything.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    stale = datetime.now(UTC) - GRANT_TTL - timedelta(minutes=1)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(grant_module, "datetime", _FrozenClock(stale))
        expired, _ = mint_grant(tenant_id=uuid.UUID(str(org["id"])), admin_id=admin_id)

    async with _client() as http:
        response = await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), expired))

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/impersonation_grant_expired")


async def test_a_grant_for_one_client_is_refused_against_another() -> None:
    """REFUSAL THREE, and THE REPLAY THIS DESIGN EXISTS TO PREVENT.

    An operator legitimately opens client A, keeps the grant, and points it at client
    B. If this passed, the grant would be strictly WORSE than the bare header it
    replaced: same access, plus an air of authorisation, plus a start row naming the
    wrong tenant.

    Asserted from BOTH sides — B's data is not reachable with A's grant, and A's still
    is with A's — so a refusal that came from something incidental (a broken org, a
    bad slug) could not pass this test.
    """
    _admin_id, token = await _make_admin()
    tenant_a = await _make_org()
    tenant_b = await _make_org()

    async with _client() as http:
        grant_a = await _mint_over_http(http, token, str(tenant_a["slug"]))
        replayed = await http.get(
            "/v1/agents", headers=_headers(token, str(tenant_b["slug"]), grant_a)
        )
        honest = await http.get(
            "/v1/agents", headers=_headers(token, str(tenant_a["slug"]), grant_a)
        )

    assert replayed.status_code == 403, replayed.text
    assert replayed.json()["type"].endswith("/impersonation_grant_tenant_mismatch")
    assert honest.status_code == 200, "the same grant must still open the tenant it names"

    # And nothing was recorded against B: a refused entry must not leave a start row
    # implying authority over an account the operator was never granted.
    assert await _started_rows(uuid.UUID(str(tenant_b["id"]))) == []


async def test_a_forged_grant_is_refused() -> None:
    """The signature is load-bearing, so it is asserted rather than assumed.

    Signed with a plausible-but-wrong key and otherwise perfectly shaped: right
    audience, right claims, in date. Only the key is wrong.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    now = int(datetime.now(UTC).timestamp())
    forged = jwt.encode(
        {
            "aud": GRANT_AUDIENCE,
            "sub": str(org["id"]),
            ACTOR_CLAIM: {"sub": str(admin_id)},
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 900,
        },
        "not-the-signing-key",
        algorithm=GRANT_ALGORITHM,
    )

    async with _client() as http:
        response = await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), forged))

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/impersonation_grant_invalid")


async def test_gibberish_in_the_header_is_a_refusal_not_a_crash() -> None:
    """A header is whatever the caller typed. The refusal is 403, never a 500."""
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        response = await http.get(
            "/v1/agents", headers=_headers(token, str(org["slug"]), "not.a.jwt")
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/impersonation_grant_invalid")


async def test_one_operators_grant_does_not_admit_another() -> None:
    """The actor binding, and it is not decoration.

    Without it, a grant that leaked out of one operator's browser would let a second
    admin enter the tenant — and the ledger would hold a start row naming the FIRST
    operator for a session the second one ran. The whole point of the start row is that
    it names who was let in.
    """
    _first_id, first_token = await _make_admin()
    _second_id, second_token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        grant = await _mint_over_http(http, first_token, str(org["slug"]))
        response = await http.get(
            "/v1/agents", headers=_headers(second_token, str(org["slug"]), grant)
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/impersonation_grant_actor_mismatch")


async def test_a_grant_minted_for_another_audience_is_refused() -> None:
    """Audience binding, asserted on a token we signed ourselves with the real key.

    This is the one forgery an attacker with any other HS256 token of ours could try,
    and the answer must not depend on the rest of the claims being wrong.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    now = int(datetime.now(UTC).timestamp())
    wrong_audience = jwt.encode(
        {
            "aud": "calevate:something-else",
            "sub": str(org["id"]),
            ACTOR_CLAIM: {"sub": str(admin_id)},
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 900,
        },
        grant_module._signing_key(),
        algorithm=GRANT_ALGORITHM,
    )

    async with _client() as http:
        response = await http.get(
            "/v1/agents", headers=_headers(token, str(org["slug"]), wrong_audience)
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/impersonation_grant_invalid")


# ------------------------------------------------------------- the session-start row


async def test_the_start_row_is_written_once_per_grant_and_not_per_request() -> None:
    """What `admin.impersonation_started` MEANS: authority was issued, once.

    It is not a page-view counter — that is `admin.impersonation_read`, coalesced per
    minute in `core/auth.py` — so a session that makes twelve reads is ONE start row and
    a second mint is a second one. Getting this wrong in either direction breaks the
    ledger: a row per request buries the trail in an INSERT-ONLY table, and a row per
    *session* that never appears is the defect this change exists to fix.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        grant = await _mint_over_http(http, token, str(org["slug"]))
        for _ in range(12):
            assert (
                await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), grant))
            ).status_code == 200

    rows = await _started_rows(tenant_id)
    assert len(rows) == 1, f"one grant and twelve reads wrote {len(rows)} start rows"
    actor_type, actor_id, row_tenant, object_type, object_id, ip, at = rows[0]
    # Exactly the fields SEC-COMP §5 names: actor=admin_user, tenant, at, ip.
    assert actor_type == "admin"
    assert uuid.UUID(str(actor_id)) == admin_id
    assert uuid.UUID(str(row_tenant)) == tenant_id
    assert object_type == "organization" and uuid.UUID(str(object_id)) == tenant_id
    assert ip, "the row must carry the caller's address"
    assert at is not None and at.tzinfo is not None, "timestamptz, not a naive instant"

    async with _client() as http:
        await _mint_over_http(http, token, str(org["slug"]))
    assert len(await _started_rows(tenant_id)) == 2, "a second grant is a second session"


async def test_a_grant_nobody_uses_is_still_recorded() -> None:
    """The start row means "authority was ISSUED", not "data was read".

    An operator who opens a client's page and closes it immediately has still been let
    into that account, and an investigator asking "who was given access to this client
    on the 14th" wants that answer. The read row deliberately does not carry it — it
    only exists once a request actually reaches the tenant.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        await _mint_over_http(http, token, str(org["slug"]))

    assert len(await _started_rows(uuid.UUID(str(org["id"])))) == 1


async def test_a_grant_cannot_be_minted_from_inside_another_account() -> None:
    """No chained delegation. RFC 8693 permits nesting `act`; we refuse it here.

    `admin:impersonate` is deliberately NOT a mutating permission (D-22 forbids gating
    a read on one), so `requires()` would have let this through — which is exactly why
    the refusal is written out in the route rather than inherited.
    """
    _admin_id, token = await _make_admin()
    inner = await _make_org()
    outer = await _make_org()

    async with _client() as http:
        grant = await _mint_over_http(http, token, str(inner["slug"]))
        response = await http.post(
            GRANT_PATH,
            headers=_headers(token, str(inner["slug"]), grant),
            json={"slug": str(outer["slug"])},
        )

    assert response.status_code == 403, response.text
    assert await _started_rows(uuid.UUID(str(outer["id"]))) == []


# ------------------------------------------------------- D-22's other half, unmoved


async def test_a_valid_grant_still_buys_no_mutation() -> None:
    """D-22 is READ-ONLY, and the grant does not soften it by one endpoint.

    The interesting direction: a grant is authority to LOOK, and somebody reading this
    change could reasonably expect it to also be authority to act. It is not. The
    refusal is `requires()` + `MUTATING_PERMISSIONS`, untouched by this work, and it is
    asserted under a grant that is valid in every respect so the 403 cannot be coming
    from the grant check instead.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        grant = await _mint_over_http(http, token, str(org["slug"]))
        headers = _headers(token, str(org["slug"]), grant)
        readable = await http.get("/v1/agents", headers=headers)
        # `kb:write` is in MUTATING_PERMISSIONS and the operator role holds it, so the
        # only thing that can refuse this is D-22 itself.
        mutation = await http.post(
            "/v1/kb/sources",
            headers=headers,
            json={
                "agent_id": str(org["agent_id"]),
                "name": "Should not exist",
                "body": "x" * 20,
                "kind": "text",
            },
        )

    assert readable.status_code == 200, "the grant must genuinely open the reads"
    assert mutation.status_code == 403, mutation.text
    assert "read-only" in mutation.json()["detail"].lower()


async def test_losing_the_permission_refuses_a_grant_that_has_not_expired() -> None:
    """REVOCATION MID-GRANT, which is the question a short-lived token usually answers
    badly.

    Here it does not have to: the grant is not a credential. Every request still carries
    the operator's own admin token and still re-reads `admin_users` (`core/auth.py::
    _load_admin_principal`), so authority is re-decided per request and the grant's TTL
    bounds nothing that matters. Revocation lag is ONE REQUEST, not one lifetime, which
    is why there is no denylist and no grants table.

    The same argument covers the sibling cases, each enforced by machinery that predates
    this change: a signed-out operator fails `verify_token` (401), and a deleted
    `admin_users` row fails the lookup above it (403).
    """
    _admin_id, token = await _make_admin(role="operator")
    org = await _make_org()

    async with _client() as http:
        grant = await _mint_over_http(http, token, str(org["slug"]))
        assert (
            await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), grant))
        ).status_code == 200

        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(
                ROLE_PERMISSIONS,
                "operator",
                frozenset(ROLE_PERMISSIONS["operator"] - {"admin:impersonate"}),
            )
            revoked = await http.get("/v1/agents", headers=_headers(token, str(org["slug"]), grant))

    assert revoked.status_code == 403, revoked.text
    # The PERMISSION refusal, not the grant one: the role check runs first on purpose,
    # so a revoked operator is refused for the reason that is actually true of them.
    assert revoked.json()["type"].endswith("/forbidden")


class _FrozenClock:
    """`datetime` with `now()` pinned, for minting a grant at another instant.

    A stub of the module's clock rather than of `mint_grant` itself: the point is that
    the token's own `exp` is what the verifier enforces, and stubbing the minter would
    have tested a hand-written token instead of a real one.
    """

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self, tz: Any = None) -> datetime:
        del tz
        return self._instant

    @staticmethod
    def fromtimestamp(value: float, tz: Any = None) -> datetime:
        return datetime.fromtimestamp(value, tz)


def test_a_configured_secret_below_the_hmac_key_size_is_refused_like_an_absent_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A weak key is not a warning to read later — it is the same condition as no key.

    RFC 7518 §3.2 requires an HMAC key at least the size of the hash output (32 bytes for
    HS256), and PyJWT only WARNS below it. Failing closed on an ABSENT secret while
    silently accepting a present-but-short one would leave the refusal guarding the
    easier half of one mistake: an operator who pastes a short string into the secrets
    manager gets a signing key that can be searched, and the only signal is a log line.

    Refused with the SAME code as absence (`impersonation_not_configured`) on purpose —
    to this module "no usable signing key" is one condition, and giving it two codes
    would invite a caller to handle one and not the other.
    """
    settings = grant_module.get_settings()

    class _Short:
        app_env = "production"
        impersonation_grant_secret = "too-short-for-hs256"  # 19 bytes

    monkeypatch.setattr(grant_module, "get_settings", lambda: _Short())
    with pytest.raises(ProblemError) as raised:
        grant_module.mint_grant(tenant_id=uuid.uuid4(), admin_id=uuid.uuid4())
    assert raised.value.code == "impersonation_not_configured"
    assert "32" in (raised.value.remediation or ""), "the refusal must name the requirement"

    # And the positive half, so this pins a THRESHOLD rather than a blanket refusal.
    class _LongEnough:
        app_env = "production"
        impersonation_grant_secret = "x" * 32

    monkeypatch.setattr(grant_module, "get_settings", lambda: _LongEnough())
    wire, grant = grant_module.mint_grant(tenant_id=uuid.uuid4(), admin_id=uuid.uuid4())
    assert wire and grant.grant_id
    assert settings is not None  # the real settings object was never mutated
