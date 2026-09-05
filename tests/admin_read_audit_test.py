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

The MUTATIONS have their own walk at the bottom of this file, added later and for the
same reason the read walk's second half exists: nothing asked whether every admin write
leaves a row, and the writes are what a regulator or a client dispute actually reads the
ledger for.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant, and nothing asserts a global row count.
"""

from __future__ import annotations

import textwrap
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
        # ANY path parameter, not only `{tenant_id}`/`{org_id}`.
        #
        # THE TENANT IS NOT ALWAYS IN THE PATH, and that was the blind spot: a route can
        # take some OTHER id and resolve the tenant from the row it names.
        # `GET /v1/admin/qa-samples/{sample_id}` is exactly that — it reads one client's
        # sampled call, and the narrower filter skipped it entirely, so the guard could not
        # have noticed if its audit row were ever removed. It writes one today
        # (`qa_sample.read`, in the same transaction as the read), which is why widening
        # this costs nothing now; the point is that the NEXT such route is seen.
        if "{" not in route.path:
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
        # EITHER helper counts. `record_admin_tenant_read` is the coalescing one most
        # admin reads use; a route disclosing a single named object writes a specific
        # `write_audit` action instead (`qa_sample.read`), which is a better ledger entry
        # for that case, not a weaker one. What the ledger needs is a row, not a spelling.
        if "record_admin_tenant_read" not in source and "write_audit" not in source:
            missing.append(name)

    assert seen, "found no per-tenant admin GET routes — this walk sees nothing"
    assert not missing, (
        "these admin-realm GETs read one client's tenant-scoped rows and leave no "
        f"audit row (SEC-COMP §5, D-482 L-1): {missing}. Call "
        "`record_admin_tenant_read` inside the route's transaction — or `write_audit` "
        "with an action naming what was disclosed — or record in _NOT_A_PER_TENANT_READ "
        "why the route reads nothing of the client's."
    )


def _reaches_write_audit(endpoint: Any, *, depth: int = 2) -> bool:
    """Does this handler write an audit row — itself, or through what it calls?

    ONE HOP IS NOT ENOUGH and that is why this is a walk rather than a substring test on
    the handler. Six of these routes are correct and would have been named by a
    handler-only check: `POST /v1/admin/operators` and its three siblings delegate to
    `authn/operators.py`, and the two `/v1/ops/config/{key}` routes call a module-local
    `_audit` helper. A guard that reported those as defects would be trained past on its
    first run, which is worse than no guard.

    So: read the handler's source, and if `write_audit` is not in it, resolve every NAME
    it calls against its own module's globals and read those too, to `depth` levels. Two
    is deliberate — it reaches `route -> _audit -> write_audit` and `route ->
    service.change_operator_role -> write_audit` — and going deeper would start following
    the whole call graph and answering "somewhere below here, something audits", which is
    a different and much weaker claim.

    A handler that hides the write further down than that is not silently allowed: it is
    reported, and the fix is either to bring the call up or to say so in
    `_NOT_AN_AUDITED_MUTATION` with the ground.
    """
    import ast
    import inspect

    try:
        source = inspect.getsource(endpoint)
    except OSError:  # pragma: no cover — source is always on disk here
        return True
    if "write_audit" in source:
        return True
    if depth <= 0:
        return False

    namespace = getattr(endpoint, "__globals__", {})
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:  # pragma: no cover — the source came from the interpreter
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # `_audit(...)` and `service.change_operator_role(...)` — the two spellings a
        # route in this tree actually uses.
        if isinstance(func, ast.Name):
            target = namespace.get(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            target = getattr(namespace.get(func.value.id), func.attr, None)
        else:
            continue
        # OURS ONLY. Following a call into SQLAlchemy or httpx would turn this into a
        # crawl of the dependency tree; the helper an audited route reaches is either in
        # the route's own module (`config_routes._audit`) or elsewhere under `apps.`
        # (`authn.operators.change_operator_role`).
        if not callable(target):
            continue
        module = getattr(target, "__module__", "") or ""
        if not module.startswith(("apps.", "packages.")) and module != getattr(
            endpoint, "__module__", None
        ):
            continue
        if _reaches_write_audit(target, depth=depth - 1):
            return True
    return False


#: Admin-realm MUTATIONS that deliberately write no `audit_log` row, with the reason.
#: EMPTY, and it should stay that way: an operator act on the platform or on a client that
#: leaves no row is the state SEC-COMP §5 exists to forbid. An entry here is a claim that
#: the route changes nothing anybody could later be asked to account for.
_NOT_AN_AUDITED_MUTATION: dict[str, str] = {}


def test_every_admin_realm_mutation_writes_an_audit_row() -> None:
    """The MUTATING half of the walk above, which had no walk at all.

    `test_every_direct_per_tenant_admin_read_records_one` closes the "other direction" for
    admin READS: is every per-tenant read in the audited set? Nothing asked the same
    question of the writes — and the writes are the ones a regulator, a client dispute or
    an incident actually reads the ledger for. Every one of the ~57 admin-realm and
    ops-realm mutations DOES write a row today, which is why this walk costs nothing to
    add now; the point is the fifty-eighth, added on a Friday by somebody who copied a
    route that happened not to need one.

    Static, like its sibling: driving 57 mutations against real objects would be a
    different (and much slower) test, and what is being pinned here is the WIRING — that
    the handler contains the call — not what the row says. `tests/platform_audit_test.py`,
    `tests/billing_audit_test.py`, `tests/engine_audit_test.py` and the per-feature suites
    own the contents.

    Derived from the live app, so the set can only fall behind the routes for as long as
    it takes CI to run.
    """
    from apps.api.core.rbac import iter_api_routes

    missing: list[str] = []
    seen = 0
    for route in iter_api_routes(app):
        if not route.path.startswith(("/v1/admin/", "/v1/ops/")):
            continue
        methods = sorted(
            m for m in (route.methods or []) if m in {"POST", "PUT", "PATCH", "DELETE"}
        )
        if not methods:
            continue
        seen += 1
        name = f"{methods[0]} {route.path}"
        if name in _NOT_AN_AUDITED_MUTATION:
            continue
        if not _reaches_write_audit(route.endpoint):
            missing.append(name)

    assert seen > 40, f"found {seen} admin-realm mutations — this walk has stopped seeing them"
    assert not missing, (
        "these admin-realm mutations change a client's or the platform's state and leave "
        f"no audit row (SEC-COMP §5): {missing}. Call `write_audit` in the route's own "
        "transaction — or record in _NOT_AN_AUDITED_MUTATION why the route changes "
        "nothing anybody could be asked to account for."
    )


def test_the_mutation_walk_can_actually_see_a_missing_audit_row() -> None:
    """The negative control, because a walk that cannot fail is a green tick on nothing.

    `_reaches_write_audit` is the whole judgement, so it is driven directly rather than by
    mounting a route: three handlers, one auditing inline, one auditing through a helper
    (the shape six real routes take, and the shape a handler-only substring test would
    have wrongly condemned), and one auditing nowhere.
    """

    async def audits_inline() -> None:
        await write_audit()  # type: ignore[call-arg]  # noqa: F821 - never called

    async def _helper() -> None:
        await write_audit()  # type: ignore[call-arg]  # noqa: F821 - never called

    async def audits_through_a_helper() -> None:
        await _helper()

    async def audits_nowhere() -> None:
        return None

    # The helper has to be reachable through the handler's module globals, which is how
    # `config_routes._audit` and `operators.change_operator_role` are reached in the app.
    # Removed again in the `finally`: these are THIS module's globals, and a stray `_helper`
    # left in them is a name the next reader has to account for.
    globals()["_helper"] = _helper
    try:
        assert _reaches_write_audit(audits_inline)
        assert _reaches_write_audit(audits_through_a_helper)
        assert not _reaches_write_audit(audits_nowhere)
    finally:
        del globals()["_helper"]
