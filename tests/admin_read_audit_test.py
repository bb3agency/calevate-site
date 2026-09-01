"""A DIRECT admin read of one client's data leaves a row. D-482 L-1 / SEC-COMP §5.

SEC-COMP §5 claims "audit_log on all admin reads", and until this slice that was true
only for the impersonated path (`tests/impersonation_audit_test.py`): an operator who
opened a client's margin card, intake sheet or spend board DIRECTLY — admin realm,
tenant in the path, no `X-Impersonate-Org` — read the same data and left nothing. The
founder's call on D-482's one open item was to audit them, so `record_admin_tenant_read`
(core/auth.py) now writes `admin.tenant_read`, coalesced per (admin, tenant) per window
exactly like `admin.impersonation_read`, and each per-tenant admin GET calls it inside
its own transaction.

Unlike the impersonated row, this one IS per-route wiring — there is no single choke
point a direct read must pass, because `requires(..., realm="admin")` resolves no tenant.
So the surface walk below is the regression net: every audited route is driven once and
must leave its own row.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant, and nothing asserts a global row count.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.admin import service as admin_service
from apps.api.core import auth as auth_module
from apps.api.core.auth import ADMIN_TENANT_READ_ACTION
from apps.api.core.redis import get_redis
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> tuple[uuid.UUID, str]:
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
        name="Direct Read Audit Clinic",
        slug=f"dra-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _read_rows(tenant_id: uuid.UUID) -> list[Any]:
    """Direct-read entries for ONE tenant, oldest first (audit_log is not tenant-RLS'd)."""
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, tenant_id, action, object_type, "
                    "object_id, ip, at, entry_hash FROM audit_log "
                    "WHERE action = :action AND tenant_id = :tid ORDER BY at ASC, id ASC"
                ),
                {"action": ADMIN_TENANT_READ_ACTION, "tid": tenant_id},
            )
        ).all()


async def _forget_the_window(admin_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Simulate the coalescing window elapsing, without sleeping through it."""
    await get_redis().delete(f"calevate:adminread:seen:{admin_id}:{tenant_id}")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_one_direct_admin_read_leaves_one_row() -> None:
    """The guarantee on the plainest per-tenant read: ONE row, carrying exactly the four
    fields SEC-COMP §5 names (actor=admin_user, tenant, at, ip), chained."""
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/margin", headers=_auth(token))
    assert response.status_code == 200, response.text

    rows = await _read_rows(tenant_id)
    assert len(rows) == 1, f"a direct admin read left {len(rows)} audit rows, expected 1"
    actor_type, actor_id, row_tenant, _action, object_type, object_id, ip, at, entry_hash = rows[0]
    assert actor_type == "admin"
    assert uuid.UUID(str(actor_id)) == admin_id
    assert uuid.UUID(str(row_tenant)) == tenant_id
    assert at is not None and at.tzinfo is not None, "timestamptz, not a naive instant"
    assert ip, "the row must carry the caller's address"
    assert object_type == "organization" and uuid.UUID(str(object_id)) == tenant_id
    assert entry_hash, "the row must be linked into the tamper-evident chain (§7)"


async def test_reads_coalesce_within_the_window_and_record_after_it() -> None:
    """The volume rule, both halves: a second read inside the window writes nothing,
    and the first read after the window always records."""
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        headers = _auth(token)
        first = await http.get(f"/v1/admin/tenants/{tenant_id}/margin", headers=headers)
        second = await http.get(f"/v1/admin/tenants/{tenant_id}/commercial-terms", headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        assert len(await _read_rows(tenant_id)) == 1, "two reads in one window must coalesce"

        await _forget_the_window(admin_id, tenant_id)
        third = await http.get(f"/v1/admin/tenants/{tenant_id}", headers=headers)
        assert third.status_code == 200, third.text
    assert len(await _read_rows(tenant_id)) == 2, "a read after the window must record"


async def test_every_audited_surface_leaves_its_own_row() -> None:
    """The regression net for per-route wiring: each direct per-tenant read surface
    is driven once (window forgotten between them) and must leave its own row."""
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    surfaces = (
        f"/v1/admin/tenants/{tenant_id}",
        f"/v1/admin/tenants/{tenant_id}/invitations",
        f"/v1/admin/tenants/{tenant_id}/margin",
        f"/v1/admin/tenants/{tenant_id}/commercial-terms",
        f"/v1/admin/tenants/{tenant_id}/invoice",
        f"/v1/admin/tenants/{tenant_id}/credits",
        f"/v1/admin/tenants/{tenant_id}/spend",
        f"/v1/admin/tenants/{tenant_id}/feature-flags",
        f"/v1/admin/tenants/{tenant_id}/erasure",
        f"/v1/admin/organizations/{tenant_id}/llm-defaults",
    )
    async with _client() as http:
        headers = _auth(token)
        for path in surfaces:
            await _forget_the_window(admin_id, tenant_id)
            response = await http.get(path, headers=headers)
            assert response.status_code == 200, f"{path}: {response.text}"

    rows = await _read_rows(tenant_id)
    assert len(rows) == len(surfaces), (
        f"{len(surfaces)} direct reads produced {len(rows)} rows — "
        "a per-tenant admin read surface lost its audit call"
    )


async def test_redis_outage_fails_towards_recording(monkeypatch: Any) -> None:
    """The dedupe is a cache, never a gate: with Redis unable to answer, the read is
    still recorded (noise over silence — same direction as the impersonated row)."""

    class _Down:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(auth_module, "get_redis", lambda: _Down())
    _admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        response = await http.get(f"/v1/admin/tenants/{tenant_id}/margin", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert len(await _read_rows(tenant_id)) == 1


#: Admin-realm routes that take a tenant in the PATH and deliberately write no
#: `admin.tenant_read` row, with the reason. The bar is that the route does not read one
#: client's tenant-scoped rows — otherwise the entry is an exemption for exactly the case
#: SEC-COMP §5 asks the ledger to hold.
_NOT_A_PER_TENANT_READ: dict[str, str] = {}


def test_every_direct_per_tenant_admin_read_records_one() -> None:
    """The half the surface walk above cannot see, and the one that went stale.

    `test_every_audited_surface_leaves_its_own_row` is a HAND-WRITTEN list checked in one
    direction only: every path in it must leave a row. Nothing asked the other direction —
    is every per-tenant admin read in the list? So a route added afterwards reads a
    client's rows and leaves nothing, the count is unchanged, and the suite stays green.
    That is the same defect shape `adversarial_pass_test::
    test_every_id_route_in_the_client_space_is_swept` exists for, applied to the ledger
    instead of to IDOR.

    Derived from the live app, so the list can only fall behind the routes for as long as
    it takes CI to run.
    """
    import inspect

    from apps.api.core.rbac import iter_api_routes

    missing: list[str] = []
    seen = 0
    for route in iter_api_routes(app):
        if not route.path.startswith(("/v1/admin/", "/v1/ops/")):
            continue
        if "{tenant_id}" not in route.path and "{org_id}" not in route.path:
            continue
        methods = sorted(m for m in (route.methods or []) if m in {"GET"})
        if not methods:
            continue
        seen += 1
        name = f"{methods[0]} {route.path}"
        if name in _NOT_A_PER_TENANT_READ:
            continue
        try:
            source = inspect.getsource(route.endpoint)
        except OSError:  # pragma: no cover — source is always on disk here
            continue
        if "record_admin_tenant_read" not in source:
            missing.append(name)

    assert seen, "found no per-tenant admin GET routes — this walk sees nothing"
    assert not missing, (
        "these admin-realm GETs read one client's tenant-scoped rows and leave no "
        f"`admin.tenant_read` row (SEC-COMP §5, D-482 L-1): {missing}. Call "
        "`record_admin_tenant_read` inside the route's transaction, or record in "
        "_NOT_A_PER_TENANT_READ why the route reads nothing of the client's."
    )
