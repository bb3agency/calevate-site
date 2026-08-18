"""Session fixation, driven over HTTP against a live session (D-330).

THE HTTP-LEVEL TWIN of `tests/authn_cookie_prefix_test.py`, and the two are deliberately
separate rather than merged. That file asserts the property on `read_token` itself: pure
arithmetic over a synthetic `Request`, touching no database, which is what lets it state
the shared-database discipline its docstring states. This file asserts the same property
where an attacker actually stands — a real `Set-Cookie` name on a real request to the real
ASGI app, carrying a real, MFA-complete, live session token. A unit test that passed while
a middleware or a dependency read the cookie by some other route would be a green light
over a live hole, so the boundary gets its own coverage at the boundary.

The defect: `read_token` tried the `__Host-` name and then the stripped one, on every
request, whatever scheme it arrived on. `__Host-` stops a sibling host OVERWRITING the
prefixed cookie; it says nothing about the bare name, which any host under
`*.calevate.tech` may set with `Domain=.calevate.tech`. So a not-yet-signed-in visitor
could be silently placed inside the attacker's tenant, and sign-out could not undo it —
`delete_cookie` expires a host-only cookie, and a `Domain=`-scoped one is a different
cookie to the browser.

Found twice, independently: as D-198 by the authn pass and again here by a red-team pass
that had branched before the fix landed. Both files survive the merge because both
assertions are worth having.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn.cookies import cookie_name
from apps.api.authn.sessions import issue_session
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.requests import Request

pytestmark = [pytest.mark.rls]

#: The two realms, and the route on each that answers "who is this session".
SESSION_ROUTE = {"admin": "/v1/auth/admin/session", "client": "/v1/auth/client/session"}


def _client(*, tls: bool) -> AsyncClient:
    """A caller whose requests look like production (`https`) or like a laptop (`http`).

    The peer is a CALL-unique documentation address (RFC 3849) so no two runs share a
    limiter bucket.
    """
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    scheme = "https" if tls else "http"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)),
        base_url=f"{scheme}://api.calevate.tech",
    )


@pytest_asyncio.fixture
async def subjects() -> AsyncIterator[dict[str, uuid.UUID]]:
    """One live subject per realm: an `admin_users` row and a `users` row with a
    membership, because the client realm resolves a membership on every request."""
    from apps.api.admin import service as admin_service

    admin_id, user_id = uuid.uuid4(), uuid.uuid4()
    org = await admin_service.create_organization(
        name="Prefix Clinic",
        slug=f"prefix-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(org["id"]))
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, email, name, role, "
                "created_at, updated_at) VALUES (:id, NULL, :email, 'Prefix Probe', "
                "'superadmin', now(), now())"
            ),
            {"id": admin_id, "email": f"prefix-{admin_id.hex[:10]}@calevate-test.example"},
        )
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
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                "updated_at) VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    try:
        yield {"admin": admin_id, "client": user_id}
    finally:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = ANY(:s)"),
                {"s": [admin_id, user_id]},
            )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})


async def _token(realm: str, subject_id: uuid.UUID) -> str:
    """A live session for this realm. The admin realm needs `mfa_verified_at` stamped, or
    every request is refused for the OTHER reason and the test would prove nothing."""
    async with credential_session() as session:
        issued = await issue_session(session, realm=realm, subject_id=subject_id)
        if realm == "admin":
            await session.execute(
                text("UPDATE auth_sessions SET mfa_verified_at = now() WHERE id = :i"),
                {"i": issued.session_id},
            )
    return issued.token


# ═══════════════ the attack ═══════════════


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_a_tls_request_does_not_accept_the_unprefixed_cookie_alias(
    realm: str, subjects: dict[str, uuid.UUID]
) -> None:
    """THE FIXATION HOLE. 200 before the fix, 401 after — both realms, because both
    consoles sit under one registrable domain and the alias existed on both."""
    token = await _token(realm, subjects[realm])
    bare = cookie_name(realm, secure=False)
    assert not bare.startswith("__Host-"), "the alias under test must be the stripped name"

    async with _client(tls=True) as http:
        response = await http.get(SESSION_ROUTE[realm], headers={"cookie": f"{bare}={token}"})

    assert response.status_code == 401, response.text


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_a_terminating_proxy_counts_as_tls_for_the_same_refusal(
    realm: str, subjects: dict[str, uuid.UUID]
) -> None:
    """The production shape: nginx terminates TLS and the app sees `http` plus
    `X-Forwarded-Proto`. `_is_secure` already reads that header to decide which name to
    SET, and the read side must agree — otherwise the fix closes the hole only on
    deployments that do not exist."""
    token = await _token(realm, subjects[realm])
    bare = cookie_name(realm, secure=False)

    async with _client(tls=False) as http:
        response = await http.get(
            SESSION_ROUTE[realm],
            headers={"cookie": f"{bare}={token}", "x-forwarded-proto": "https"},
        )

    assert response.status_code == 401, response.text


async def test_a_planted_alias_does_not_become_the_victims_session(
    subjects: dict[str, uuid.UUID],
) -> None:
    """The attack end to end, in the order it actually happens.

    The victim's browser carries BOTH cookies — the attacker's, planted from a sibling
    host under the bare name, and the victim's own, set by us under `__Host-`. The
    refusal above is not enough on its own: what matters is which subject the request
    resolves as, and a fix that merely REORDERED the two names would look identical to
    the assertions above while still handing the account over on the request before the
    victim signs in.
    """
    attacker = await _token("admin", subjects["admin"])
    victim_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, email, name, role, "
                "created_at, updated_at) VALUES (:id, NULL, :email, 'Prefix Victim', "
                "'operator', now(), now())"
            ),
            {"id": victim_id, "email": f"victim-{victim_id.hex[:10]}@calevate-test.example"},
        )
    try:
        victim = await _token("admin", victim_id)
        async with _client(tls=True) as http:
            both = await http.get(
                SESSION_ROUTE["admin"],
                headers={
                    "cookie": (
                        f"{cookie_name('admin', secure=False)}={attacker}; "
                        f"{cookie_name('admin', secure=True)}={victim}"
                    )
                },
            )
            alone = await http.get(
                SESSION_ROUTE["admin"],
                headers={"cookie": f"{cookie_name('admin', secure=False)}={attacker}"},
            )
        assert both.status_code == 200, both.text
        assert both.json()["subject_id"] == str(victim_id)
        # Before the victim ever signs in there is no `__Host-` cookie to win, and this
        # is the request that used to hand them the attacker's account.
        assert alone.status_code == 401, alone.text
    finally:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = :s"), {"s": victim_id}
            )
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": victim_id})


# ═══════════════ the controls, without which the fix could be a blanket break ═══════════════


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_the_prefixed_name_still_authenticates_over_tls(
    realm: str, subjects: dict[str, uuid.UUID]
) -> None:
    """The name production actually sets. If this went red the "fix" would be an outage."""
    token = await _token(realm, subjects[realm])

    async with _client(tls=True) as http:
        response = await http.get(
            SESSION_ROUTE[realm], headers={"cookie": f"{cookie_name(realm, secure=True)}={token}"}
        )

    assert response.status_code == 200, response.text
    assert response.json()["subject_id"] == str(subjects[realm])


@pytest.mark.parametrize("realm", ["admin", "client"])
async def test_the_stripped_name_still_works_on_a_cleartext_request(
    realm: str, subjects: dict[str, uuid.UUID]
) -> None:
    """Local development, deliberately untouched: browsers reject a `__Host-` cookie over
    plain HTTP, so the stripped name is the only credential a laptop console can hold."""
    token = await _token(realm, subjects[realm])

    async with _client(tls=False) as http:
        response = await http.get(
            SESSION_ROUTE[realm], headers={"cookie": f"{cookie_name(realm, secure=False)}={token}"}
        )

    assert response.status_code == 200, response.text


def _request(*, scheme: str, cookie: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/auth/admin/session",
            "raw_path": b"/v1/auth/admin/session",
            "query_string": b"",
            "headers": [(b"host", b"api.calevate.tech"), (b"cookie", cookie.encode())],
            "scheme": scheme,
            "server": ("api.calevate.tech", 443 if scheme == "https" else 80),
            "client": ("203.0.113.9", 5000),
            "root_path": "",
        }
    )
