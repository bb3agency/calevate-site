"""The first thirty seconds of a new identity's life (D-124).

Clerk mints a session the instant an account exists and sends the browser straight back
to us; `user.created` travels to our Svix endpoint out of band. So both routes that take
a verified identity with NO membership — `POST /v1/auth/signup` and
`POST /v1/invitations/accept` — are routinely reached before the mirror row exists, and
both used to answer `401 "This account is not provisioned."`. A browser reads 401 as
"sign in again", and signing in again mints another valid token and reproduces it: a loop
with no exit and no sentence.

What is pinned here, in the order it costs a customer:

- **The race is reconciled, not refused.** With Clerk's Backend API reachable, a founder
  who beats the webhook gets their workspace and an invitee gets their membership, on the
  FIRST request.
- **The reconciled row is Clerk's, not the caller's.** `users.email` is what binds an
  invitation to its recipient, so the address must come from Clerk's record of the
  subject. A caller cannot influence it, and an invitation for someone else stays refused
  after a reconcile.
- **The fallback is transient and retryable, never 401** — with `Retry-After`, which is
  what `apps/web/src/lib/api/client.ts` waits on.
- **Permanent things stay permanent.** A deactivated account is 401 and is never
  reconciled; a subject Clerk says does not exist is 401, not an endless 503.
- **The admin realm is never reconciled**: `admin_users` is an ops allowlist, and
  minting one would be privilege escalation.
- **Reconciling confers IDENTITY, never ACCESS.** A reconciled user with no membership
  sees zero tenants.
- **It is idempotent both ways**: two concurrent reconciles make one row (with the
  interleave PROVEN, not assumed), and the webhook landing afterwards updates that row.

SEAMS. Tests that drive HTTP stub `clerk_identity.fetch_clerk_user`, because configuring
a Clerk secret would disable the `dev:client:` token the suite authenticates with
(`core/auth._verify_dev_token`). The adapter itself is therefore covered separately
against a real `httpx` stack over `MockTransport` (`test_fetch_clerk_user_*`), and
`test_resolve_mirrored_user_reconciles_over_real_http` drives the whole resolution with
nothing of ours replaced — so no assertion here rests on a stub standing in for the
thing it is about.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx
import pytest
from apps.api.core import clerk_identity
from apps.api.core.clerk_identity import (
    MIRROR_PENDING_CODE,
    ClerkUserLookup,
    fetch_clerk_user,
    resolve_mirrored_user,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant

CLERK_SECRET = "sk_test_identity_mirror"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"identity-mirror-test-key").decode()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


@pytest.fixture(autouse=True)
def _signup_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-11's kill switch defaults OFF; every test here is about the identity race."""
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)


def _unmirrored() -> str:
    """A Clerk subject our database has never heard of — the state the webhook has not
    reached yet. 96 bits, so no fixture can collide into a passing test."""
    return f"user_{uuid.uuid4().hex[:12]}"


def _clerk_user(clerk_id: str, email: str) -> dict[str, Any]:
    """Clerk's User object, which is byte-for-byte the shape its `user.created` webhook
    carries — that identity is what lets one mirror function serve the push and the pull
    (`core/clerk_identity.mirror_clerk_user`)."""
    return {
        "id": clerk_id,
        "first_name": "Ravi",
        "last_name": "Kumar",
        "primary_email_address_id": "idn_primary",
        "email_addresses": [
            {"id": "idn_other", "email_address": f"other-{email}"},
            {"id": "idn_primary", "email_address": email},
        ],
    }


def _stub_clerk(monkeypatch: pytest.MonkeyPatch, lookup: ClerkUserLookup | Exception) -> list[str]:
    """Replace the Clerk ADAPTER and record every subject it was asked about.

    The returned list is how "was Clerk consulted at all?" becomes assertable — the
    deactivated-account and admin-realm tests are about a call that must NOT happen, and
    a test that only checks the status code would pass while the reconcile ran.
    """
    asked: list[str] = []

    async def _fake(clerk_user_id: str) -> ClerkUserLookup:
        asked.append(clerk_user_id)
        if isinstance(lookup, Exception):
            raise lookup
        return lookup

    monkeypatch.setattr(clerk_identity, "fetch_clerk_user", _fake)
    return asked


async def _mirror_row(clerk_id: str) -> tuple[uuid.UUID, str, str | None] | None:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT id, email, name FROM users WHERE clerk_user_id = :c"),
                {"c": clerk_id},
            )
        ).first()
    return None if row is None else (uuid.UUID(str(row[0])), str(row[1]), row[2])


def _signup_body() -> dict[str, Any]:
    return {
        "business_name": "Sunrise Dental",
        "slug": f"mir-{uuid.uuid4().hex[:8]}",
        "vertical_template": "clinic",
        "language": "te-IN",
    }


# --- the two races, reconciled ------------------------------------------------


async def test_signup_before_the_mirror_lands_reconciles_instead_of_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A founder who clicks straight through from Clerk's signup gets a workspace."""
    clerk_id = _unmirrored()
    email = f"founder-{uuid.uuid4().hex[:8]}@clinic.example"
    asked = _stub_clerk(monkeypatch, ClerkUserLookup("found", _clerk_user(clerk_id, email)))
    assert await _mirror_row(clerk_id) is None, "the premise: no mirror row exists yet"

    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup",
            headers={"Authorization": f"Bearer dev:client:{clerk_id}"},
            json=_signup_body(),
        )

    assert response.status_code == 201, response.text
    assert asked == [clerk_id]
    mirrored = await _mirror_row(clerk_id)
    assert mirrored is not None, "the reconcile wrote the row the webhook was going to"
    assert mirrored[1] == email, "the address is CLERK's, on the primary id"
    assert mirrored[2] == "Ravi Kumar"

    # And the membership points at the reconciled user, not at some second row.
    tenant_id = uuid.UUID(response.json()["tenant_id"])
    async with tenant_session(tenant_id) as session:
        owner = (
            await session.execute(
                text("SELECT user_id, role FROM memberships WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).all()
    assert [(uuid.UUID(str(r[0])), r[1]) for r in owner] == [(mirrored[0], "owner")]


async def test_invite_accept_before_the_mirror_lands_reconciles_instead_of_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A colleague who follows the emailed link straight out of Clerk's signup joins."""
    tenant_id, slug, owner_token = await _make_tenant("owner")
    address = f"colleague-{uuid.uuid4().hex[:8]}@clinic.example"
    clerk_id = _unmirrored()
    asked = _stub_clerk(monkeypatch, ClerkUserLookup("found", _clerk_user(clerk_id, address)))

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": address, "role": "staff"},
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        assert created.status_code == 201, created.text
        accepted = await http.post(
            "/v1/invitations/accept",
            headers={"Authorization": f"Bearer dev:client:{clerk_id}"},
            json={"token": created.json()["token"]},
        )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["slug"] == slug
    assert accepted.json()["role"] == "staff"
    assert asked == [clerk_id]

    mirrored = await _mirror_row(clerk_id)
    assert mirrored is not None
    async with tenant_session(tenant_id) as session:
        roles = (
            await session.execute(
                text("SELECT role FROM memberships WHERE tenant_id = :t AND user_id = :u"),
                {"t": tenant_id, "u": mirrored[0]},
            )
        ).all()
    assert [r[0] for r in roles] == ["staff"]


async def test_a_reconciled_identity_cannot_redeem_someone_elses_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE SECURITY PROPERTY that decided the design.

    `accept_invitation` binds the invitation to `users.email`, so if the reconcile took
    the address from anywhere the caller controls — a session-token claim, a request
    field — a stranger could mint a matching mirror row and redeem a colleague's key.
    It takes it from Clerk's record of the subject, so the binding still refuses.
    """
    _tenant_id, slug, owner_token = await _make_tenant("owner")
    invited = f"invited-{uuid.uuid4().hex[:8]}@clinic.example"
    stranger = _unmirrored()
    _stub_clerk(
        monkeypatch,
        ClerkUserLookup(
            "found", _clerk_user(stranger, f"stranger-{uuid.uuid4().hex[:8]}@x.example")
        ),
    )

    async with _client() as http:
        created = await http.post(
            "/v1/invitations",
            json={"email": invited, "role": "staff"},
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        refused = await http.post(
            "/v1/invitations/accept",
            headers={"Authorization": f"Bearer dev:client:{stranger}"},
            json={"token": created.json()["token"]},
        )

    assert refused.status_code == 403, refused.text
    assert refused.json()["type"].endswith("/invitation_wrong_recipient")


async def test_reconciling_confers_identity_and_never_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reconciled user is a user, not a member. Hard rule 1 in the auth path: the row
    the reconcile writes is global (`users`), and it must open no tenant."""
    tenant_id, slug, _owner = await _make_tenant("owner")
    newcomer = _unmirrored()
    _stub_clerk(
        monkeypatch,
        ClerkUserLookup("found", _clerk_user(newcomer, f"nobody-{uuid.uuid4().hex[:8]}@x.example")),
    )

    async with _client() as http:
        refused = await http.get(
            "/v1/dashboard",
            headers={"Authorization": f"Bearer dev:client:{newcomer}", "X-Org-Slug": slug},
        )

    assert refused.status_code == 403, refused.text
    mirrored = await _mirror_row(newcomer)
    assert mirrored is not None, "identity was reconciled"
    async with tenant_session(tenant_id) as session:
        memberships = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": mirrored[0]}
            )
        ).scalar()
    assert memberships == 0, "zero rows: reconciling opened no tenant"


# --- the fallback, and what stays permanent -----------------------------------


async def test_when_clerk_cannot_be_asked_the_refusal_is_transient_not_401() -> None:
    """NOTHING IS STUBBED HERE. No Clerk secret is configured in the test environment, so
    the real `fetch_clerk_user` answers `unavailable` and the real ladder runs — which is
    what proves `current_identity` is wired to this module at all."""
    clerk_id = _unmirrored()
    assert not get_settings().clerk_client_secret_key, "the premise of this test"

    async with _client() as http:
        response = await http.post(
            "/v1/invitations/accept",
            headers={"Authorization": f"Bearer dev:client:{clerk_id}"},
            json={"token": "a" * 40},
        )

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"].endswith(f"/{MIRROR_PENDING_CODE}")
    assert body["kind"] == "transient"
    assert body["retryable"] is True, "the browser decides to wait on this field"
    assert response.headers["retry-after"] == "2"
    assert "sign" in body["remediation"].lower(), "it must say NOT to sign in again"
    assert await _mirror_row(clerk_id) is None, "a refused attempt writes nothing"


async def test_clerk_saying_the_subject_does_not_exist_is_a_permanent_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a race: retrying cannot conjure a user Clerk has no record of, so answering
    503 would be an infinite wait wearing a retry policy."""
    ghost = _unmirrored()
    asked = _stub_clerk(monkeypatch, ClerkUserLookup("absent"))

    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup",
            headers={"Authorization": f"Bearer dev:client:{ghost}"},
            json=_signup_body(),
        )

    assert response.status_code == 401, response.text
    assert asked == [ghost]
    assert await _mirror_row(ghost) is None


async def test_a_deactivated_account_is_401_and_clerk_is_never_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revocation property. `mirror_clerk_user` never clears `deactivated_at`, but
    the stronger guarantee is that we do not even go and look: a revoked account must not
    be one upstream round trip away from a row that reads as live."""
    clerk_id = _unmirrored()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, deactivated_at, "
                "created_at, updated_at) VALUES (:i, :c, :e, now(), now(), now())"
            ),
            {"i": uuid.uuid4(), "c": clerk_id, "e": f"{clerk_id}@example.com"},
        )
    asked = _stub_clerk(monkeypatch, ClerkUserLookup("found", _clerk_user(clerk_id, "x@y.example")))

    async with _client() as http:
        response = await http.post(
            "/v1/auth/signup",
            headers={"Authorization": f"Bearer dev:client:{clerk_id}"},
            json=_signup_body(),
        )

    assert response.status_code == 401, response.text
    assert "deactivated" in response.json()["detail"].lower()
    assert asked == [], "a revoked account must not reach the reconcile at all"


async def test_the_admin_realm_is_never_reconciled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`admin_users` is an ops-managed allowlist, not a Clerk mirror. Backfilling one
    would turn 'can sign in to the admin Clerk application' into 'is an operator'."""
    operator = _unmirrored()
    asked = _stub_clerk(
        monkeypatch, ClerkUserLookup("found", _clerk_user(operator, "op@x.example"))
    )

    async with _client() as http:
        response = await http.get(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer dev:admin:{operator}"},
        )

    assert response.status_code == 403, response.text
    assert asked == [], "the admin path must not consult Clerk's user directory"
    async with untenanted_session() as session:
        admins = (
            await session.execute(
                text("SELECT count(*) FROM admin_users WHERE clerk_user_id = :c"), {"c": operator}
            )
        ).scalar()
    assert admins == 0, "no operator was minted"


# --- idempotency: the webhook lands anyway, and two callers arrive at once -----


async def test_the_webhook_landing_after_a_reconcile_updates_the_same_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reliability requirement. Both paths write through ONE upsert keyed on
    `clerk_user_id`, so the push cannot produce a second identity for the same subject —
    which would leave the membership the reconcile created pointing at an orphan."""
    clerk_id = _unmirrored()
    first = f"first-{uuid.uuid4().hex[:8]}@clinic.example"
    _stub_clerk(monkeypatch, ClerkUserLookup("found", _clerk_user(clerk_id, first)))
    monkeypatch.setattr(get_settings(), "clerk_webhook_secret", WEBHOOK_SECRET)

    reconciled = await resolve_mirrored_user(clerk_id)

    # …and now Clerk's `user.created` arrives, late, with an updated address.
    later = f"later-{uuid.uuid4().hex[:8]}@clinic.example"
    body = json.dumps({"type": "user.created", "data": _clerk_user(clerk_id, later)}).encode()
    svix_id, ts = f"msg_{uuid.uuid4().hex[:10]}", str(int(time.time()))
    key = base64.b64decode(WEBHOOK_SECRET.removeprefix("whsec_"))
    signature = base64.b64encode(
        hmac.new(key, f"{svix_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()

    async with _client() as http:
        delivered = await http.post(
            "/hooks/v1/clerk",
            content=body,
            headers={
                "svix-id": svix_id,
                "svix-timestamp": ts,
                "svix-signature": f"v1,{signature}",
                "content-type": "application/json",
            },
        )

    assert delivered.status_code == 202, delivered.text
    assert delivered.json()["status"] == "mirrored"
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT id, email FROM users WHERE clerk_user_id = :c"), {"c": clerk_id}
            )
        ).all()
    assert len(rows) == 1, "one subject, one row — the upsert, not a second insert"
    assert uuid.UUID(str(rows[0][0])) == reconciled, "the id the membership points at survives"
    assert rows[0][1] == later, "and the late event still updates it"


async def test_two_concurrent_reconciles_produce_one_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REAL interleave, proven rather than hoped for.

    Two tabs finishing signup at once is the ordinary case, and a test that merely
    `gather`s two coroutines proves nothing: without an await point inside the vendor
    window each one runs to completion in turn, and a broken implementation passes. So
    the stubbed Clerk call BLOCKS on a barrier until BOTH callers are inside it, and the
    test asserts that fact before it asserts anything about the outcome. If the two
    calls were serialised the barrier would never release and this test would time out
    rather than pass.
    """
    clerk_id = _unmirrored()
    email = f"twins-{uuid.uuid4().hex[:8]}@clinic.example"
    inside: list[str] = []
    both_inside = asyncio.Event()

    async def _slow_clerk(subject: str) -> ClerkUserLookup:
        inside.append(subject)
        if len(inside) == 2:
            both_inside.set()
        # Waits for the OTHER coroutine to reach this same point. `wait_for` rather than
        # a bare `wait` so a serialised implementation fails loudly here instead of
        # hanging the suite.
        await asyncio.wait_for(both_inside.wait(), timeout=5)
        return ClerkUserLookup("found", _clerk_user(subject, email))

    monkeypatch.setattr(clerk_identity, "fetch_clerk_user", _slow_clerk)

    first, second = await asyncio.gather(
        resolve_mirrored_user(clerk_id), resolve_mirrored_user(clerk_id)
    )

    assert len(inside) == 2 and both_inside.is_set(), (
        "both callers were inside the Clerk window at the same time — without this the "
        "test would be measuring two sequential requests"
    )
    assert first == second, "both callers resolved to the SAME user"
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM users WHERE clerk_user_id = :c"), {"c": clerk_id}
            )
        ).scalar()
    assert count == 1, "the unique index collapsed the pair; no duplicate identity"


# --- the adapter, against a real httpx stack ----------------------------------


def _stub_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    """Give `httpx.AsyncClient` a `MockTransport` while leaving everything else real.

    The seam is the SOCKET, not our code: the URL, the `Authorization` header, the
    timeout and the status-code ladder are all exercised as written. Recording the
    requests is what lets the auth header be asserted — a reconcile that reached Clerk
    unauthenticated would 401 upstream and read to us as `unavailable`, which is exactly
    the silent misconfiguration a status-only assertion would miss.
    """
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        def _handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        return real(transport=httpx.MockTransport(_handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    monkeypatch.setattr(get_settings(), "clerk_client_secret_key", CLERK_SECRET)
    return seen


async def test_fetch_clerk_user_calls_the_documented_endpoint_with_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clerk_id = _unmirrored()
    payload = _clerk_user(clerk_id, "ravi@clinic.example")
    seen = _stub_transport(monkeypatch, lambda _r: httpx.Response(200, json=payload))

    lookup = await fetch_clerk_user(clerk_id)

    assert lookup.status == "found"
    assert lookup.user == payload
    assert str(seen[0].url) == f"https://api.clerk.com/v1/users/{clerk_id}"
    assert seen[0].headers["authorization"] == f"Bearer {CLERK_SECRET}"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(404, "absent"), (401, "unavailable"), (429, "unavailable"), (500, "unavailable")],
)
async def test_fetch_clerk_user_maps_upstream_status_to_permanence(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: str
) -> None:
    """Only 404 is `absent`. Reading a 401 (our key rotated) or a 500 as "no such user"
    would sign real customers out during a misconfiguration or someone else's outage."""
    _stub_transport(monkeypatch, lambda _r: httpx.Response(status, json={}))
    assert (await fetch_clerk_user(_unmirrored())).status == expected


async def test_fetch_clerk_user_treats_a_transport_failure_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("clerk did not answer")

    _stub_transport(monkeypatch, _boom)
    assert (await fetch_clerk_user(_unmirrored())).status == "unavailable"


async def test_fetch_clerk_user_without_a_secret_is_unavailable_not_an_error() -> None:
    """A local build has no Clerk at all. That must fall through to the transient
    refusal, never 500 — the deployment being unconfigured is not the caller's fault."""
    assert not get_settings().clerk_client_secret_key
    assert (await fetch_clerk_user(_unmirrored())).status == "unavailable"


async def test_resolve_mirrored_user_reconciles_over_real_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole resolution with NOTHING of ours replaced — adapter, upsert and re-read.

    The route-level tests above stub `fetch_clerk_user` because a configured Clerk secret
    disables the dev token they authenticate with; this one closes that gap by driving
    `resolve_mirrored_user` directly with the secret set and only the socket faked.
    """
    clerk_id = _unmirrored()
    email = f"real-{uuid.uuid4().hex[:8]}@clinic.example"
    _stub_transport(monkeypatch, lambda _r: httpx.Response(200, json=_clerk_user(clerk_id, email)))

    user_id = await resolve_mirrored_user(clerk_id)

    mirrored = await _mirror_row(clerk_id)
    assert mirrored is not None
    assert mirrored[0] == user_id
    assert mirrored[1] == email


async def test_a_clerk_user_with_no_address_is_a_transient_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`users.email` is NOT NULL and is an authorization input, so a Clerk record we
    cannot represent must refuse rather than invent an address. Transient with an
    operator log line, because it is not the caller's authentication that is wrong."""
    clerk_id = _unmirrored()
    _stub_clerk(monkeypatch, ClerkUserLookup("found", {"id": clerk_id, "email_addresses": []}))

    with pytest.raises(ProblemError) as raised:
        await resolve_mirrored_user(clerk_id)

    assert raised.value.code == MIRROR_PENDING_CODE
    assert raised.value.status == 503
    assert await _mirror_row(clerk_id) is None
