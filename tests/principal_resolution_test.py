"""One request, one principal — and therefore one D-22 ledger row.

`requires()` cannot go through `Depends`: the permission it enforces is a closure
argument, so the dependency FastAPI caches is `requires._dep` and not the resolver
inside it. A route carrying both `Depends(requires(...))` and `Depends(tenant_of)`
therefore reached the resolver through two callables and resolved a principal TWICE.
That is most tenant-scoped routes in this app.

D-131 measured the duplication, patched the one consequence it could see — the tenant
rate-limit charge, memoised on the scope — and recorded the cause in a docstring. The
cause had three more consequences, and the third is not a performance note:

1. The client realm re-ran `resolve_mirrored_user` (a query, and a call to Clerk's
   Backend API whenever the Svix mirror is behind) and the membership query.
2. The admin realm re-ran an entire `admin_session` transaction: the `admin_users`
   lookup, the tenant-directory lookup and `verify_grant`.
3. **The `admin.impersonation_read` row was written twice**, whenever the Redis dedupe
   marker could not answer. That marker is a cache and `_record_impersonated_read`
   deliberately fails TOWARDS recording, so a Redis outage turned every impersonated
   request into two identical page-view entries — same operator, same tenant, same
   grant, same instant — in an append-only ledger an investigator reads to answer "how
   long was this operator inside this client's data". Coalescing is what makes that
   ledger legible; duplicating it is the same defect from the other direction.

So the assertions below are about COUNTS, on the live app, through the real dependency
graph. Nothing here mocks the resolver away: each test wraps it and counts.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core import auth as auth_module
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.impersonation_audit_test import _make_admin, _make_org, _read_rows
from tests.impersonation_grant_test import view_as_headers

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_member(tenant_id: uuid.UUID) -> str:
    """A client-realm dev token for a fresh owner of `tenant_id`."""
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
    return f"dev:client:{clerk_id}"


def _counting(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    """Wrap `auth.<name>` so the test can count how often a request reaches it.

    The real function still runs — this counts the work, it does not replace it, so a
    route that is 200 here is 200 for the same reasons it is in production.
    """
    calls: list[int] = []
    original = getattr(auth_module, name)

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(auth_module, name, _wrapped)
    return calls


async def test_a_client_principal_is_resolved_once_however_many_dependencies_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /v1/agents` asks twice: `Session` → `db` → `tenant_of` → `current_any`, and
    `requires("agents:read")` directly. Both must find the same already-resolved answer.
    """
    calls = _counting(monkeypatch, "_load_client_principal")
    org = await _make_org()
    token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        response = await http.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert len(calls) == 1, (
        f"the membership query ran {len(calls)} times for one request — every dependency "
        "that asks who the caller is must reuse the first answer"
    )


async def test_an_admin_principal_is_resolved_once_however_many_dependencies_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admin realm pays more for the duplicate: a whole `admin_session` transaction,
    the `admin_users` lookup, the directory lookup and `verify_grant`."""
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        # Minted BEFORE the counter is installed: `view_as_headers` is itself an HTTP
        # request that resolves an admin principal, and counting it would make this test
        # pass or fail on how the fixture is built rather than on the request under test.
        headers = await view_as_headers(http, token, str(org["slug"]))
        calls = _counting(monkeypatch, "_load_admin_principal")
        response = await http.get("/v1/agents", headers=headers)

    assert response.status_code == 200, response.text
    assert len(calls) == 1, f"the admin directory was read {len(calls)} times for one request"


def _broken_redis() -> Any:
    raise ConnectionError("redis is down")


async def test_one_impersonated_request_is_one_ledger_row_even_with_the_dedupe_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CONSEQUENCE THAT IS NOT A PERFORMANCE NOTE.

    The coalescing marker is a Redis SETNX and `_record_impersonated_read` fails towards
    RECORDING when it cannot be reached — correct on its own terms: an audit control may
    degrade into noise, never into silence. Combined with a principal resolved twice, that
    correct choice produced two identical `admin.impersonation_read` entries for one
    request, in an append-only table, and D-22's whole readability argument is that one
    presence is one row.

    Only `core.auth`'s handle on Redis is broken here — `write_audit` does not use Redis
    at all, and the limiter has its own — so what this exercises is precisely the dedupe
    being unavailable and nothing else.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        # Minted with Redis intact, so the outage below covers exactly one request.
        headers = await view_as_headers(http, token, str(org["slug"]))
        monkeypatch.setattr(auth_module, "get_redis", _broken_redis)
        response = await http.get("/v1/agents", headers=headers)

    assert response.status_code == 200, response.text
    rows = await _read_rows(tenant_id)
    assert len(rows) == 1, (
        f"one impersonated request left {len(rows)} page-view rows; with the dedupe "
        "marker unavailable, every resolution of the principal writes one"
    )
