"""Per-tenant feature flags (SURFACES §1) — the properties that make them a mechanism.

CLAUDE.md fixes the shape ("Feature flags via plain config rows, not a flag SaaS") and
SURFACES §1 asks for the surface. What has to hold for that to be worth building:

1. **Resolution order**, in both directions, INCLUDING the absent-row case. A tenant with
   no row resolves to the platform default, no row is required to exist for any tenant,
   and a stored row wins over the default for exactly the tenant it belongs to.
2. **Hard rule 1.** Cross-tenant zero rows — through the admin route, on the raw
   RLS-scoped session, AND through `resolve_flags` itself, so a resolver that filtered in
   Python, or one that leaked its per-request memo between tenants, still fails.
3. **The cache is the request.** Repeat reads inside one session cost ONE query; a write
   on that session invalidates it; and a flip is visible to the very next session, with no
   TTL to wait out.
4. **Permissions.** Read is `org:read` (non-mutating, so D-22's read-only impersonation
   can still see a client's configuration); write is `admin:tenants`, admin realm — a
   client-realm token is refused whatever its role.
5. **Audit follows a REAL change.** A flip writes one `audit_log` entry; restating the
   position on file writes none, and moves no row.
6. **The registry is the vocabulary.** Setting a flag this build does not declare is
   refused; clearing one is allowed, because that is the retirement path.

Concurrency note: this repo's tests share one Postgres. Every case below is scoped to a
run-unique tenant; nothing asserts a global row count.

Run: uv run pytest -q tests/feature_flags_test.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.flags.registry import FLAGS, assert_flag_registry_wellformed
from apps.api.flags.service import clear_flag, flag_enabled, resolve_flags, set_flag
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

pytestmark = [pytest.mark.rls]

# The one flag this build declares. Named once so a future rename fails here loudly
# rather than leaving the suite passing against a flag that no longer exists.
FLAG = "call_timing_breakdown"
UNDECLARED = "flag_no_release_declares"


def _path(tenant_id: Any, flag: str | None = None) -> str:
    base = f"/v1/admin/tenants/{tenant_id}/feature-flags"
    return base if flag is None else f"{base}/{flag}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> tuple[str, uuid.UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


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


async def _tenant() -> dict[str, Any]:
    return await admin_service.create_organization(
        name="Flag Motors",
        slug=f"flag-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _set_via_route(
    tenant_id: Any,
    *,
    enabled: bool | None,
    reason: str = "Beta trial agreed with the client on ticket 4471.",
    flag: str = FLAG,
    token: str | None = None,
) -> Any:
    """Flip a flag the way an operator does: admin realm, tenant in the path, audited."""
    if token is None:
        token, _ = await _make_admin()
    async with _client() as http:
        return await http.put(
            _path(tenant_id, flag),
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": enabled, "reason": reason},
        )


def _item(body: dict[str, Any], flag: str = FLAG) -> dict[str, Any]:
    found = [entry for entry in body["items"] if entry["flag"] == flag]
    assert found, f"{flag} missing from {[e['flag'] for e in body['items']]}"
    return found[0]


# ------------------------------------------------------------------- resolution order


async def test_a_tenant_with_no_row_gets_the_platform_default() -> None:
    """THE case that must not require a row: a tenant nobody has ever configured.

    Nothing seeds `tenant_feature_flags` — not onboarding, not the migration — so a
    resolver that needed a row would answer wrongly for every tenant on the platform.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM tenant_feature_flags WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        ).scalar()
        assert rows == 0, "the fixture must not have written a row"

        resolved = await resolve_flags(session, tenant_id=tenant_id)
        assert set(resolved) == set(FLAGS), "every declared flag resolves, row or no row"
        for name, spec in FLAGS.items():
            assert resolved[name].enabled is spec.default
            assert resolved[name].source == "platform_default"
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is FLAGS[FLAG].default


async def test_a_tenant_override_beats_the_platform_default() -> None:
    """The other half of the order, and the one the sabotage check breaks."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()
    assert FLAGS[FLAG].default is False, "this test's premise is that the default is off"

    async with tenant_session(tenant_id) as session:
        await set_flag(
            session,
            tenant_id=tenant_id,
            flag=FLAG,
            enabled=True,
            reason="Debugging a latency complaint with this client.",
            set_by_admin_id=admin_id,
        )
    async with tenant_session(tenant_id) as session:
        resolved = await resolve_flags(session, tenant_id=tenant_id)
        assert resolved[FLAG].enabled is True, "the tenant's override must win"
        assert resolved[FLAG].source == "tenant_override"
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is True


async def test_clearing_an_override_returns_the_tenant_to_the_default() -> None:
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()

    async with tenant_session(tenant_id) as session:
        await set_flag(
            session,
            tenant_id=tenant_id,
            flag=FLAG,
            enabled=True,
            reason="Beta trial for this client.",
            set_by_admin_id=admin_id,
        )
    async with tenant_session(tenant_id) as session:
        change = await clear_flag(session, tenant_id=tenant_id, flag=FLAG)
        assert change.changed is True
        assert change.before.source == "tenant_override"
        assert change.after.source == "platform_default"
    async with tenant_session(tenant_id) as session:
        resolved = await resolve_flags(session, tenant_id=tenant_id)
        assert resolved[FLAG].enabled is FLAGS[FLAG].default
        assert resolved[FLAG].source == "platform_default"


async def test_an_override_equal_to_the_default_is_still_an_override() -> None:
    """`source` is a fact of its own, not something derivable from `enabled`.

    A tenant pinned to the value the platform happens to default to today is NOT the same
    as a tenant with no row: the next change to the default reaches one and not the other,
    and an operator has to be able to see which they are looking at.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()
    async with tenant_session(tenant_id) as session:
        await set_flag(
            session,
            tenant_id=tenant_id,
            flag=FLAG,
            enabled=FLAGS[FLAG].default,
            reason="Pinned off while their beta is paused.",
            set_by_admin_id=admin_id,
        )
    async with tenant_session(tenant_id) as session:
        resolved = await resolve_flags(session, tenant_id=tenant_id)
        assert resolved[FLAG].enabled is FLAGS[FLAG].default
        assert resolved[FLAG].source == "tenant_override"


async def test_a_row_for_an_undeclared_flag_changes_nothing() -> None:
    """The retirement path: a release stops declaring a flag, its rows stop being read.

    Written directly rather than through the route, because the route refuses to SET an
    undeclared flag — which is the point. This is the state a PREVIOUS release leaves
    behind, and the resolver must ignore it rather than obey a switch no code reads.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_feature_flags (id, tenant_id, flag, enabled, reason, "
                "  set_by_admin_id, created_at, updated_at) "
                "VALUES (:id, :tid, :flag, true, 'left over from an older release', "
                "  :admin, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "flag": UNDECLARED, "admin": admin_id},
        )
    async with tenant_session(tenant_id) as session:
        resolved = await resolve_flags(session, tenant_id=tenant_id)
        assert UNDECLARED not in resolved, "an undeclared row must not become a flag"
        assert set(resolved) == set(FLAGS)


# ---------------------------------------------------------------- the cache is the request


async def test_repeat_reads_in_one_session_cost_one_query() -> None:
    """The whole caching story, asserted rather than asserted-about.

    Ten flag reads inside one request must issue ONE select against
    `tenant_feature_flags`. The memo lives on `Session.info`, so its lifetime is the
    session's — which in this repo is the request's transaction.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    seen: list[str] = []

    async with tenant_session(tenant_id) as session:
        sync_session = session.sync_session

        def _record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            del conn, cursor, args
            if "tenant_feature_flags" in statement:
                seen.append(statement)

        event.listen(sync_session.bind, "before_cursor_execute", _record)
        try:
            for _ in range(10):
                await flag_enabled(session, tenant_id=tenant_id, flag=FLAG)
        finally:
            event.remove(sync_session.bind, "before_cursor_execute", _record)

    assert len(seen) == 1, f"expected one read of the table, saw {len(seen)}"


async def test_a_write_invalidates_the_memo_within_the_same_request() -> None:
    """A read-back after a write on the SAME session must not serve the stale memo.

    This is the only window the per-request memo could be wrong in, so the writer clears
    it rather than leaving that to the caller.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()

    async with tenant_session(tenant_id) as session:
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is False
        await set_flag(
            session,
            tenant_id=tenant_id,
            flag=FLAG,
            enabled=True,
            reason="Turned on mid-request by the operator's own call.",
            set_by_admin_id=admin_id,
        )
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is True
        await clear_flag(session, tenant_id=tenant_id, flag=FLAG)
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is False


async def test_a_flip_is_visible_to_the_very_next_request() -> None:
    """No TTL to wait out: the flag this repo built takes effect NOW, not in 15 seconds.

    Written through the route (a real request, its own transaction) and read on a fresh
    session, which is exactly the sequence a cross-request cache would break.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))

    response = await _set_via_route(org["id"], enabled=True)
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is True

    response = await _set_via_route(org["id"], enabled=None, reason="Trial over.")
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        assert await flag_enabled(session, tenant_id=tenant_id, flag=FLAG) is False


# ------------------------------------------------------------------------- hard rule 1


async def test_tenant_b_sees_none_of_tenant_as_flags() -> None:
    """Cross-tenant zero rows — three ways, so no single defect can hide.

    Through the ADMIN ROUTE (B's screen shows B's answer), on the RAW RLS-scoped session
    (an endpoint that filtered in Python would still fail), and through `resolve_flags`
    itself with A's tenant id passed on B's session (a resolver whose per-request memo was
    not keyed by tenant would leak here even though no policy was involved).
    """
    org_a = await _tenant()
    org_b = await _tenant()
    tenant_a = uuid.UUID(str(org_a["id"]))
    tenant_b = uuid.UUID(str(org_b["id"]))
    assert (await _set_via_route(org_a["id"], enabled=True)).status_code == 200

    token, _ = await _make_admin()
    async with _client() as http:
        response = await http.get(_path(org_b["id"]), headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    item = _item(response.json())
    assert item["override"] is None, "tenant B must not inherit tenant A's override"
    assert item["source"] == "platform_default"
    assert item["enabled"] is False

    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM tenant_feature_flags WHERE tenant_id = :tid"),
                {"tid": tenant_a},
            )
        ).scalar()
        assert rows == 0, "RLS must hide tenant A's rows from tenant B's session"

        # Read A's flags FIRST on B's session — RLS returns nothing — then B's own. A memo
        # that was not keyed by tenant would serve the first answer to the second call.
        leaked = await resolve_flags(session, tenant_id=tenant_a)
        assert leaked[FLAG].source == "platform_default"
        mine = await resolve_flags(session, tenant_id=tenant_b)
        assert mine[FLAG].source == "platform_default"

    # And the direction the memo could actually leak in: A's OWN session, which can see
    # A's override, then asked about B. RLS answers zero rows for B, so B must come back
    # at the platform default — a memo not keyed by tenant would hand back A's answer
    # without any policy having been crossed.
    async with tenant_session(tenant_a) as session:
        theirs = await resolve_flags(session, tenant_id=tenant_a)
        assert theirs[FLAG].enabled is True, "the fixture's premise: A is overridden on"
        assert theirs[FLAG].source == "tenant_override"

        other = await resolve_flags(session, tenant_id=tenant_b)
        assert other[FLAG].source == "platform_default", "B must not inherit A's memo"
        assert other[FLAG].enabled is False


async def test_an_untenanted_session_sees_no_flags_at_all() -> None:
    """Policies fail CLOSED: no GUC means zero rows, never all rows."""
    org = await _tenant()
    assert (await _set_via_route(org["id"], enabled=True)).status_code == 200
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM tenant_feature_flags WHERE tenant_id = :tid"),
                {"tid": org["id"]},
            )
        ).scalar()
    assert rows == 0


# ------------------------------------------------------------------------- permissions


async def test_a_client_token_cannot_read_or_write_flags() -> None:
    """Admin realm only, in both directions. A flag is OUR decision about a client, not a
    document the client holds — unlike their KYC record or their campaign review."""
    org = await _tenant()
    headers = {
        "Authorization": f"Bearer {await _make_member(uuid.UUID(str(org['id'])), 'owner')}",
        "X-Org-Slug": str(org["slug"]),
    }
    async with _client() as http:
        read = await http.get(_path(org["id"]), headers=headers)
        write = await http.put(
            _path(org["id"], FLAG), headers=headers, json={"enabled": True, "reason": "please"}
        )
    assert read.status_code in (401, 403), read.text
    assert write.status_code in (401, 403), write.text


async def test_the_write_needs_admin_tenants_and_the_read_does_not() -> None:
    """Checked against `core/rbac.py`'s role table, not guessed.

    `admin:tenants` is the permission every other per-tenant admin mutation carries, and
    both admin roles hold it — so this asserts the ROUTE's declaration rather than
    re-deriving the role table. The read's permission is `org:read`, which is NOT in
    `MUTATING_PERMISSIONS`: D-22 forbids gating a GET on a permission read-only
    impersonation refuses, and `tests/route_shape_test.py` enforces that repo-wide.
    """
    from apps.api.core.rbac import MUTATING_PERMISSIONS, ROLE_PERMISSIONS, iter_api_routes

    declared = {
        (route.path, frozenset(route.methods or ())): (route.openapi_extra or {}).get(
            "x-calevate-permission"
        )
        for route in iter_api_routes(app)
        if route.path.startswith("/v1/admin/tenants/{tenant_id}/feature-flags")
    }
    read = declared[("/v1/admin/tenants/{tenant_id}/feature-flags", frozenset({"GET"}))]
    write = declared[("/v1/admin/tenants/{tenant_id}/feature-flags/{flag}", frozenset({"PUT"}))]

    assert write == "admin:tenants"
    assert write in MUTATING_PERMISSIONS
    assert read == "org:read"
    assert read not in MUTATING_PERMISSIONS, "a GET on a mutating permission is invisible to D-22"
    for role in ("operator", "superadmin"):
        assert "admin:tenants" in ROLE_PERMISSIONS[role]
        assert "org:read" in ROLE_PERMISSIONS[role]


async def test_the_write_takes_no_step_up_header() -> None:
    """A DECISION, pinned so removing it is deliberate (`flags/routes.py` argues it).

    Step-up is reserved for actions a replayed live session must not be able to perform:
    the big red switch, a cap RAISE, raw-transcript access. The neighbouring per-tenant
    compliance writes — releasing an account for outbound dialling, recording a KYC
    verification — take none, and a flag is a smaller act than either. If a flag ever
    needs one, it is gating something that should not be a flag.
    """
    org = await _tenant()
    token, _ = await _make_admin()
    async with _client() as http:
        response = await http.put(
            _path(org["id"], FLAG),
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True, "reason": "No confirmation header sent, on purpose."},
        )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------------------ audit


async def _audit_rows(tenant_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_id FROM audit_log WHERE tenant_id = :tid "
                    "AND action LIKE 'feature_flag.%' ORDER BY at"
                ),
                {"tid": tenant_id},
            )
        ).all()
    return [(str(row[0]), row[1]) for row in rows]


async def test_a_real_change_is_audited_and_a_no_op_is_not() -> None:
    """Audit follows a real change, never a button press.

    The convention `admin.record_commercial_terms`, `approve_kb` and
    `integrations.deactivate_endpoint` share: `audit_log` answers "who changed this
    client's behaviour", and a row per submission makes that question harder to answer.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))

    first = await _set_via_route(org["id"], enabled=True, reason="Beta trial, ticket 4471.")
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert first.json()["before"] == {"enabled": False, "source": "platform_default"}
    assert first.json()["after"] == {"enabled": True, "source": "tenant_override"}
    assert await _audit_rows(tenant_id) == [("feature_flag.set", FLAG)]

    again = await _set_via_route(org["id"], enabled=True, reason="Beta trial, ticket 4471.")
    assert again.status_code == 200, again.text
    assert again.json()["changed"] is False, "restating the position on file changes nothing"
    assert await _audit_rows(tenant_id) == [("feature_flag.set", FLAG)], "no audit for a no-op"

    cleared = await _set_via_route(org["id"], enabled=None, reason="Trial finished.")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["changed"] is True
    assert await _audit_rows(tenant_id) == [
        ("feature_flag.set", FLAG),
        ("feature_flag.cleared", FLAG),
    ]

    twice = await _set_via_route(org["id"], enabled=None, reason="Already cleared.")
    assert twice.status_code == 200, twice.text
    assert twice.json()["changed"] is False
    assert len(await _audit_rows(tenant_id)) == 2, "clearing an absent override is a no-op"


async def test_a_no_op_does_not_move_the_row() -> None:
    """`changed: false` means the ROW did not move either — `updated_at` is what the
    console renders as "set", and a restated position must not re-date it."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    reason = "Beta trial agreed with the client on ticket 4471."
    assert (await _set_via_route(org["id"], enabled=True, reason=reason)).status_code == 200

    async def _stamp() -> Any:
        async with tenant_session(tenant_id) as session:
            return (
                await session.execute(
                    text(
                        "SELECT updated_at FROM tenant_feature_flags "
                        "WHERE tenant_id = :tid AND flag = :flag"
                    ),
                    {"tid": tenant_id, "flag": FLAG},
                )
            ).scalar_one()

    before = await _stamp()
    assert (await _set_via_route(org["id"], enabled=True, reason=reason)).status_code == 200
    assert await _stamp() == before


async def test_a_corrected_reason_is_a_real_change() -> None:
    """Re-sending the same value with a better reason must not be swallowed as a no-op:
    dropping it would discard the operator's correction silently."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    assert (await _set_via_route(org["id"], enabled=True, reason="ticket 4471")).status_code == 200
    corrected = await _set_via_route(
        org["id"], enabled=True, reason="Ticket 4471 — latency complaint, agreed with the client."
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["changed"] is True
    assert len(await _audit_rows(tenant_id)) == 2


# ------------------------------------------------------- the registry is the vocabulary


async def test_setting_an_undeclared_flag_is_refused_and_clearing_one_is_not() -> None:
    """The asymmetry that keeps the retirement path reachable from the product.

    Setting a flag nothing declares creates a row nothing will ever read — a typo made
    permanent. Clearing one is how a previous release's leftovers are removed, and
    refusing it would leave psql as the only way out.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    _, admin_id = await _make_admin()

    refused = await _set_via_route(org["id"], enabled=True, flag=UNDECLARED)
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/feature_flag_unknown")

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_feature_flags (id, tenant_id, flag, enabled, reason, "
                "  set_by_admin_id, created_at, updated_at) "
                "VALUES (:id, :tid, :flag, true, 'left over from an older release', "
                "  :admin, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "flag": UNDECLARED, "admin": admin_id},
        )

    token, _ = await _make_admin()
    async with _client() as http:
        listed = await http.get(_path(org["id"]), headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    leftover = _item(listed.json(), UNDECLARED)
    assert leftover["declared"] is False, "the console must show what it cannot explain"
    assert leftover["enabled"] is False, "a flag no code reads does nothing"

    cleared = await _set_via_route(org["id"], enabled=None, flag=UNDECLARED, reason="Retired.")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["changed"] is True


def _assert_wellformed_against(registry: dict[str, Any]) -> None:
    """Run the BOOT assertion over a substituted registry.

    Monkeypatching the module global rather than passing an argument, because the
    production call site takes none — a function with a test-only parameter would be a
    second code path, and the thing under test is the one `main.py` runs at import.
    """
    from apps.api.flags import registry as registry_module

    original = registry_module.FLAGS
    registry_module.FLAGS = registry  # type: ignore[misc]
    try:
        assert_flag_registry_wellformed()
    finally:
        registry_module.FLAGS = original  # type: ignore[misc]


async def test_a_malformed_flag_name_never_reaches_the_database() -> None:
    """The path segment is validated against the same pattern the DB CHECK enforces, so a
    junk name is a 422 naming the rule rather than a constraint violation as a 500."""
    org = await _tenant()
    token, _ = await _make_admin()
    async with _client() as http:
        response = await http.put(
            _path(org["id"], "Not-A-Flag"),
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": None, "reason": "Attempted with a malformed name."},
        )
    assert response.status_code == 422, response.text


async def test_the_registry_agrees_with_its_own_type() -> None:
    """The boot assertion, run as a test too: `main.py` calls it at import, so a broken
    registry already fails everything — this names the failure."""
    assert_flag_registry_wellformed()


def test_the_declared_flag_set_is_pinned() -> None:
    """Adding a flag costs a visible diff in a TEST as well as in the registry.

    The same pin `KNOWN_A11Y_EXEMPTIONS` and `RLS_EXEMPT_TENANT_COLUMNS` carry, and for a
    sharper reason: `flags/registry.py` forbids a flag that gates a compliance control,
    and a rule enforced only by a comment is enforced by whoever remembers to read it.
    This is the line a reviewer sees when somebody adds one.
    """
    assert sorted(FLAGS) == ["call_timing_breakdown"]


def test_an_unconsumed_flag_must_say_what_would_consume_it() -> None:
    """A switch an operator can flip that does nothing, with no statement of what would
    change that, is a leftover wearing a mechanism.

    `consumed_by: None` is legal and stays legal — landing a flag before the feature it
    gates is deliberate. What is not legal is landing it with no closer named: CLAUDE.md
    says a deferral is a statement of what closes it or it is not a deferral, and the one
    flag this repo declares sat unconsumed with its description promising numbers that a
    migration had already dropped.
    """
    from dataclasses import replace

    from apps.api.flags.registry import FlagRegistryError

    for name, spec in FLAGS.items():
        if spec.consumed_by is None:
            assert spec.blocked_by and len(spec.blocked_by.strip()) >= 20, (
                f"flag {name!r} is read by nothing and does not say what would change that"
            )

    stripped = {name: replace(spec, blocked_by=None) for name, spec in FLAGS.items()}
    if any(spec.consumed_by is None for spec in FLAGS.values()):
        with pytest.raises(FlagRegistryError, match="does not"):
            _assert_wellformed_against(stripped)


def test_a_flag_may_not_claim_a_consumer_and_a_blocker_at_once() -> None:
    """A blocker is what stands between the flag and a consumer. Once one exists the
    sentence is stale, and a stale blocker is how an operator concludes a live switch
    does nothing."""
    from dataclasses import replace

    from apps.api.flags.registry import FlagRegistryError

    contradictory = {
        name: replace(
            spec, consumed_by="apps.api.flags.service", blocked_by="something outstanding"
        )
        for name, spec in FLAGS.items()
    }
    with pytest.raises(FlagRegistryError, match="both a consumer"):
        _assert_wellformed_against(contradictory)


def test_no_declared_flag_claims_a_consumer_it_does_not_have() -> None:
    """`consumed_by` is rendered beside the switch, so it must be true.

    A flag whose `consumed_by` names a module that cannot be imported would tell an
    operator that flipping it does something, when nothing reads it.
    """
    import importlib

    for name, spec in FLAGS.items():
        if spec.consumed_by is None:
            continue
        try:
            importlib.import_module(spec.consumed_by)
        except ImportError as exc:  # pragma: no cover - only on a bad declaration
            raise AssertionError(
                f"flag {name!r} says {spec.consumed_by} reads it, and that module does not "
                "import. The console renders this claim to an operator."
            ) from exc


# ---------------------------------------------------------------------------- refusals


async def test_a_mistyped_tenant_is_a_404_not_a_cheerful_nothing() -> None:
    """A 200 saying "nothing changed" for a uuid that names no client reads as "already
    set" to the operator who meant a different one."""
    token, _ = await _make_admin()
    missing = uuid.uuid4()
    async with _client() as http:
        read = await http.get(_path(missing), headers={"Authorization": f"Bearer {token}"})
        write = await http.put(
            _path(missing, FLAG),
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True, "reason": "Meant for a different client."},
        )
    assert read.status_code == 404, read.text
    assert write.status_code == 404, write.text


async def test_a_reason_is_required_in_both_directions() -> None:
    """An override nobody can account for is the finding the column exists to avoid, and
    "why did we put them back on the default" is asked just as often."""
    org = await _tenant()
    token, _ = await _make_admin()
    async with _client() as http:
        for body in (
            {"enabled": True, "reason": "  "},
            {"enabled": None, "reason": "  "},
            {"enabled": True},
        ):
            response = await http.put(
                _path(org["id"], FLAG),
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            assert response.status_code == 422, (body, response.text)


async def test_the_read_names_who_set_it_and_why() -> None:
    """The paperwork an operator needs beside the switch, and the wiring `check_wiring`
    asks for: `reason`, `set_by_admin_id` and `updated_at` are all read by a surface."""
    org = await _tenant()
    token, admin_id = await _make_admin()
    reason = "Latency complaint on ticket 4471 — timings on for the week."
    assert (
        await _set_via_route(org["id"], enabled=True, reason=reason, token=token)
    ).status_code == 200

    async with _client() as http:
        response = await http.get(_path(org["id"]), headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    item = _item(response.json())
    assert item["reason"] == reason
    assert item["set_by_admin_id"] == str(admin_id)
    assert item["set_at"] is not None
    assert item["platform_default"] is False
    assert item["override"] is True
    assert item["declared"] is True
    # NOTHING READS THIS FLAG YET, and the console says so rather than implying otherwise.
    assert item["consumed_by"] is None
