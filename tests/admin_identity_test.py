"""`GET /v1/admin/me` — the admin realm's own identity read.

The defect it closes: `/v1/me` resolves through `current_any`, which consults the ADMIN
realm only when `X-Impersonate-Org` is present (`core/auth.py`). A bare admin token
asking it is therefore verified as a CLIENT token and refused, so the console could only
learn its own role by impersonating some tenant — which needs a slug the cross-tenant
screens do not have, and spends `admin:impersonate` on a client nobody opened. The two
screens that could not do even that (the directory and ops) each derived their gate from
their own route's 403 instead.

What is asserted here is therefore not "the endpoint returns 200". It is:

1. **No header, no tenant.** The request that was impossible is the one that must work,
   and the answer must carry nothing that belongs to a client.
2. **The realms stay apart.** A client token is refused before any `admin_users` lookup
   happens — authentication, not authorization (TRD §11, D-37).
3. **The roles differ where the console's gates differ.** `operator` must not be told it
   holds `ops:manage`; that single difference is what the admin nav now renders.
4. **D-22's rule holds for this GET.** `tests/impersonation_reads_test.py` walks the
   whole route table for it; this file pins the one route the change adds, because
   getting the permission wrong here is the trap the task was written around.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.rbac import MUTATING_PERMISSIONS, ROLE_PERMISSIONS, iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ADMIN_ME = "/v1/admin/me"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """Same idiom as `admin_security_test._make_admin`."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Admin Identity Clinic",
        slug=f"ai-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def test_an_admin_token_with_no_impersonation_header_gets_its_own_identity() -> None:
    """THE request the console makes, and the one that was impossible.

    No `X-Impersonate-Org`, no `X-Org-Slug`, no tenant in the path — and the body carries
    no organization either, because an admin principal resolved this way has no tenant to
    report and a console that reads one has entered a client to ask about itself.
    """
    token = await _make_admin(role="operator")

    async with _client() as http:
        response = await http.get(ADMIN_ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["realm"] == "admin"
    assert body["role"] == "operator"
    assert uuid.UUID(body["user_id"]), "the admin_users id, so audit rows and this agree"
    assert body["permissions"] == sorted(ROLE_PERMISSIONS["operator"])
    # `extra="forbid"` on the way in; asserted on the way out too, because the field that
    # must never appear here is a tenant's.
    assert set(body) == {"realm", "user_id", "role", "permissions"}


async def test_a_client_token_is_refused_by_the_admin_identity() -> None:
    """The realms do not share session logic (TRD §11, D-37).

    An owner is a real, provisioned, permissioned human — with `org:read`, the very
    permission this route declares — and still cannot read it, because the refusal
    happens at `verify_token(..., "admin")` before any `admin_users` lookup. 401, not
    403: this is authentication failing, not authorization.
    """
    org = await _make_org()
    token = await _make_member(uuid.UUID(str(org["id"])), role="owner")

    async with _client() as http:
        response = await http.get(
            ADMIN_ME,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )

    assert response.status_code == 401, response.text
    assert response.json()["kind"] == "auth"


async def test_a_clerk_account_with_no_admin_row_is_refused() -> None:
    """Clerk says who; OUR `admin_users` says whether (D-37). A well-formed admin-realm
    token for somebody who was never provisioned is a 403, not an identity."""
    async with _client() as http:
        response = await http.get(
            ADMIN_ME, headers={"Authorization": f"Bearer dev:admin:{uuid.uuid4().hex}"}
        )

    assert response.status_code == 403, response.text
    assert response.json()["kind"] == "permission"


async def test_the_two_admin_roles_differ_exactly_where_the_console_gates() -> None:
    """`ops:manage` is superadmin-only (`core/rbac.py`), and `/admin/ops` is entirely
    built on it — every route that screen calls requires it.

    This is the fact the admin nav now renders: before this endpoint existed the console
    had no way to ask, so it offered the Operations entry to every admin role and an
    `operator` clicking it got a page that is nothing but a 403.
    """
    operator = await _make_admin(role="operator")
    superadmin = await _make_admin(role="superadmin")

    async with _client() as http:
        as_operator = await http.get(ADMIN_ME, headers={"Authorization": f"Bearer {operator}"})
        as_superadmin = await http.get(ADMIN_ME, headers={"Authorization": f"Bearer {superadmin}"})

    assert "ops:manage" not in as_operator.json()["permissions"]
    assert "ops:manage" in as_superadmin.json()["permissions"]
    # Both hold what the rest of the console needs, so the gate is about ops and nothing
    # else — a nav that hid more than one entry from an operator would be wrong.
    for response in (as_operator, as_superadmin):
        assert {"admin:tenants", "org:read"} <= set(response.json()["permissions"])


async def test_the_identity_read_is_not_gated_on_a_permission_impersonation_refuses() -> None:
    """D-22, on the route this change adds.

    `tests/impersonation_reads_test.py` asserts the rule over the whole table; this pins
    the instance, because `admin:tenants` is the permission a reader would reach for on
    an `/v1/admin/...` route and it is in `MUTATING_PERMISSIONS`. Gating an identity read
    on it would also mean a narrower admin role could discover its own limits only by
    collecting 403s.
    """
    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
        if route.methods == {"GET"}
    }
    assert declared[ADMIN_ME] == "org:read", declared.get(ADMIN_ME)
    assert declared[ADMIN_ME] not in MUTATING_PERMISSIONS


async def test_the_declared_permission_is_the_one_the_route_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declaration with no lock behind it reads as protected in the OpenAPI schema and
    in the generated TS client — the defect `/v1/me` itself carried once.

    Every shipped role holds `org:read`, so the only way to see the lock is to take it
    away, the technique `route_shape_test` uses for `/v1/me` and `authz_audit_test` for
    `admin:impersonate`.
    """
    token = await _make_admin(role="operator")

    async with _client() as http:
        allowed = await http.get(ADMIN_ME, headers={"Authorization": f"Bearer {token}"})
        monkeypatch.setitem(
            ROLE_PERMISSIONS, "operator", frozenset(ROLE_PERMISSIONS["operator"] - {"org:read"})
        )
        refused = await http.get(ADMIN_ME, headers={"Authorization": f"Bearer {token}"})

    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"
