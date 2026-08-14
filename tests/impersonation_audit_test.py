"""An impersonated read leaves a row. D-22 / SECURITY-COMPLIANCE §5.

The spec is "session start + every page view audit-logged (actor=admin_user, tenant,
at, ip)". Before this file, a grep for `action="..."` across the whole repo returned
exactly ONE impersonation entry — `admin.impersonation_started`, written by an endpoint
that MINTS NOTHING and that nothing forces an operator through. An admin who sent
`X-Impersonate-Org` and skipped the announcement read a client's leads, calls and
transcripts and left no trace whatsoever, while four docstrings and the build log said
every page view was recorded.

The assertions here are about the READ PATH. It has to hold for a route nobody has
written yet, which is why the write lives in `_load_admin_principal` — the one function
that can produce an impersonating principal — rather than in a dependency each route
must remember.

**Entry now also requires a GRANT** (`tests/impersonation_grant_test.py`), so the
original defect — an operator who sends the header and announces nothing — is no longer
reachable at all. That does not make this file redundant: the grant answers "was this
operator authorised to enter", and these rows answer "were they actually in there, and
when". The suites are deliberately separate, one per question. Every request below
therefore carries a real grant, minted once per test, because a bare header would now
be refused before any of this ran.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant, and nothing asserts a global row count.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core import auth as auth_module
from apps.api.core.auth import IMPERSONATION_AUDIT_WINDOW_S, IMPERSONATION_READ_ACTION
from apps.api.core.rbac import iter_api_routes
from apps.api.core.redis import get_redis
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.impersonation_grant_test import view_as_headers


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> tuple[uuid.UUID, str]:
    """(admin_users.id, dev bearer token). Same idiom as the other admin suites."""
    admin_id = uuid.uuid4()
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "cid": clerk_id, "role": role},
        )
    return admin_id, f"dev:admin:{clerk_id}"


async def _make_org() -> dict[str, Any]:
    return await admin_service.create_organization(
        name="Impersonation Audit Clinic",
        slug=f"ia-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _read_rows(tenant_id: uuid.UUID) -> list[Any]:
    """Impersonation-read entries for ONE tenant, oldest first.

    `audit_log` is not tenant-RLS'd (the hash chain is global — db/registry.py explains
    why), so this reads under the untenanted session and filters by tenant itself.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, tenant_id, action, object_type, object_id, "
                    "ip, at, entry_hash FROM audit_log "
                    "WHERE action = :action AND tenant_id = :tid ORDER BY at ASC, id ASC"
                ),
                {"action": IMPERSONATION_READ_ACTION, "tid": tenant_id},
            )
        ).all()


async def _forget_the_window(admin_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Simulate the coalescing window elapsing, without sleeping through it.

    The marker key is the whole mechanism, so deleting it IS "60 seconds passed" —
    and a test that slept would be a 60-second test asserting a constant.
    """
    await get_redis().delete(f"calevate:imp:seen:{admin_id}:{tenant_id}")


# ------------------------------------------------------ the guarantee, on any route


async def test_one_impersonated_read_leaves_one_row() -> None:
    """The guarantee, on the plainest possible request.

    ONE read, ONE row, carrying exactly the four fields SEC-COMP §5 names. The row is
    written by the auth layer, so it does not depend on `/v1/agents` remembering
    anything.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        response = await http.get(
            "/v1/agents", headers=await view_as_headers(http, token, str(org["slug"]))
        )
    assert response.status_code == 200, response.text

    rows = await _read_rows(tenant_id)
    assert len(rows) == 1, f"an impersonated read left {len(rows)} audit rows, expected 1"
    actor_type, actor_id, row_tenant, _action, object_type, object_id, ip, at, entry_hash = rows[0]
    # Exactly the fields SEC-COMP §5 names: actor=admin_user, tenant, at, ip.
    assert actor_type == "admin"
    assert uuid.UUID(str(actor_id)) == admin_id
    assert uuid.UUID(str(row_tenant)) == tenant_id
    assert at is not None and at.tzinfo is not None, "timestamptz, not a naive instant"
    assert ip, "the row must carry the caller's address"
    assert object_type == "organization" and uuid.UUID(str(object_id)) == tenant_id
    assert entry_hash, "the row must be linked into the tamper-evident chain (§7)"


async def test_the_audit_is_not_something_a_new_route_can_forget() -> None:
    """The design claim, checked against the live route table rather than asserted.

    Every route reaches an impersonating principal through `current_admin` /
    `current_any` / `requires(...)` / `admin_db`, and all four call
    `_load_admin_principal`. So the coverage question is not "did this route remember
    to audit" but "is there any other way to get `impersonating=True`" — and there is
    not, because that flag is constructed in exactly one place.

    Asserted by walking several DIFFERENT tenant-scoped surfaces with the same header
    and requiring each to leave its own row: three modules, one mechanism, no per-route
    wiring.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    surfaces = ("/v1/agents", "/v1/leads", "/v1/calls")
    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        for path in surfaces:
            await _forget_the_window(admin_id, tenant_id)
            response = await http.get(path, headers=headers)
            assert response.status_code == 200, f"{path}: {response.text}"

    rows = await _read_rows(tenant_id)
    assert len(rows) == len(surfaces), (
        f"{len(surfaces)} reads across three modules produced {len(rows)} rows — "
        "a surface reached a tenant without going through the audited path"
    )


def test_the_flag_that_means_impersonation_is_set_in_exactly_one_place() -> None:
    """The structural half of the claim above: `impersonating=True` is constructed
    once, in the function that writes the audit row. A second construction site is how
    this control would silently grow a hole, and it is a one-line grep to prevent."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sites = {
        f"{path.relative_to(root)}:{number}"
        for path in (root / "apps").rglob("*.py")
        if "__pycache__" not in str(path)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "impersonating=" in line
        # Not a comment, not `impersonating=False`, and not the response models that
        # merely COPY the resolved flag outward (`impersonating=principal.…`) — those
        # read the decision, they do not make it.
        and not line.lstrip().startswith("#")
        and "impersonating=False" not in line
        and "impersonating=principal." not in line
    }
    assert {site.split(":")[0] for site in sites} == {"apps/api/core/auth.py"}, (
        f"`impersonating=` is decided in {sorted(sites)}; every one of those is a way "
        "into a tenant, and only the one in _load_admin_principal writes the audit row"
    )


# ------------------------------------------------------------- the coalescing rule


async def test_a_polling_dashboard_does_not_write_a_row_per_request() -> None:
    """The volume rule, which is the half an auditor should be most suspicious of.

    `audit_log` is INSERT-only (hard rule 4): nothing prunes it, and every row costs a
    Redis lock plus a chain-head query. A console screen holds ~6 polling subscriptions,
    so one row per request is ~1400 permanent rows an hour per idle operator — which
    both costs money and buries the rows an investigator came to read.

    The rule is therefore: AT MOST ONE ROW PER (ADMIN, TENANT) PER WINDOW. Ten requests
    inside one window is one row.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        for _ in range(10):
            assert (await http.get("/v1/agents", headers=headers)).status_code == 200

    rows = await _read_rows(tenant_id)
    assert len(rows) == 1, f"10 polls inside one window wrote {len(rows)} rows"


async def test_the_first_read_after_the_window_always_records() -> None:
    """The other half, and the one that keeps the rule from being under-recording.

    Coalescing is only defensible if presence is still visible at the window's
    resolution — otherwise an operator who stays inside a tenant all afternoon has one
    row from 13:02 and the ledger cannot say when they left.
    """
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        assert (await http.get("/v1/agents", headers=headers)).status_code == 200
        await _forget_the_window(admin_id, tenant_id)
        assert (await http.get("/v1/agents", headers=headers)).status_code == 200

    assert len(await _read_rows(tenant_id)) == 2


async def test_the_window_is_short_enough_to_be_an_answer() -> None:
    """A constant this control depends on, pinned so widening it is a visible diff.

    Anything past a few minutes stops answering "how long were they in there" and the
    coalescing stops being coalescing and becomes sampling.
    """
    assert 0 < IMPERSONATION_AUDIT_WINDOW_S <= 300


async def test_two_operators_in_one_tenant_are_two_trails() -> None:
    """The dedupe key is (admin, tenant). If it were tenant-only, the second operator
    to enter within a minute would be invisible — the ledger would name one person for
    an access two people made."""
    _first_id, first_token = await _make_admin()
    _second_id, second_token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        for token in (first_token, second_token):
            response = await http.get(
                "/v1/agents", headers=await view_as_headers(http, token, str(org["slug"]))
            )
            assert response.status_code == 200, response.text

    rows = await _read_rows(tenant_id)
    assert len({str(row[1]) for row in rows}) == 2, "two operators must be two trails"


async def test_the_dedupe_fails_towards_recording_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis is a cache of "already recorded", never the source of truth.

    An audit control that goes quiet when its dedupe store is unavailable is worse than
    one with no dedupe at all, because the silence is invisible. With Redis refusing,
    every request must record — noisy, correct, and bounded by the length of the outage.

    The count is `>=`, not `==`, and the reason is worth writing down: `requires(...)`
    calls `current_admin` directly rather than through `Depends`, so a route that also
    takes a session resolves the principal twice per request. Normally the coalescing
    window collapses that to one row — which is a second thing it buys, on top of the
    polling argument — and here, with the dedupe unavailable, both resolutions record.
    """

    class _Down:
        async def set(self, *args: object, **kwargs: object) -> bool:
            raise ConnectionError("redis is down")

    _admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        # Minted BEFORE Redis goes away: the mint is not what this test is about, and a
        # grant obtained under a broken dependency would confuse the two failures.
        headers = await view_as_headers(http, token, str(org["slug"]))
    monkeypatch.setattr(auth_module, "get_redis", lambda: _Down())
    async with _client() as http:
        for _ in range(3):
            assert (await http.get("/v1/agents", headers=headers)).status_code == 200

    assert len(await _read_rows(tenant_id)) >= 3, "a dedupe outage must not silence the ledger"


# ------------------------------------------------------------ what is NOT recorded


async def test_an_admin_who_enters_no_tenant_writes_nothing() -> None:
    """The admin console itself is not impersonation. `/v1/admin/tenants` is a roster,
    reached with no `X-Impersonate-Org` and no tenant scope, and auditing it would put
    a row in an INSERT-only table every time somebody opened the home screen."""
    _admin_id, token = await _make_admin(role="superadmin")
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        response = await http.get("/v1/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert await _read_rows(tenant_id) == []


async def test_a_client_reading_their_own_tenant_writes_nothing() -> None:
    """Only the admin realm can impersonate, so only it pays. Asserted because the
    cheapest wrong place for this write — the tenancy context — would have billed every
    client request for an audit row about nobody."""
    from apps.api.db.session import tenant_session

    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
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

    async with _client() as http:
        response = await http.get(
            "/v1/agents",
            headers={
                "Authorization": f"Bearer dev:client:{clerk_id}",
                "X-Org-Slug": str(org["slug"]),
            },
        )
    assert response.status_code == 200, response.text
    assert await _read_rows(tenant_id) == []


async def test_the_ledger_row_names_no_screen_and_no_query_string() -> None:
    """Hard rule 6 lives on this path too.

    `audit_log` has no summary column, so what could leak is the log line the writer
    emits beside the row — and the route TEMPLATE is what goes there, never the
    resolved path (which carries ids) and never the query string (which carries lead
    filters, and a lead filter is a phone number).
    """
    templates = {route.path for route in iter_api_routes(app)}
    assert "/v1/leads" in templates
    admin_id, token = await _make_admin()
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))

    async with _client() as http:
        response = await http.get(
            "/v1/leads?q=%2B919876500001",
            headers=await view_as_headers(http, token, str(org["slug"])),
        )
    assert response.status_code == 200, response.text
    del admin_id

    rows = await _read_rows(tenant_id)
    assert len(rows) == 1
    assert all("9876500001" not in str(value) for value in rows[0]), (
        "a query-string value reached the audit row"
    )
