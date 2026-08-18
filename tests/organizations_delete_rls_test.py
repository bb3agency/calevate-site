"""A tenant session cannot hard-DELETE its own `organizations` row (D-207).

`organizations`' `tenant_isolation` policy is `FOR ALL` with a permissive `USING` that
admits the session's own id and a `WITH CHECK` that says the same thing — and **`WITH
CHECK` is not consulted on DELETE**. That is the third time this exact PostgreSQL fact has
cost this schema a rule: `e4f2a86b13d7` on `dnc_list` DELETE, `e7b45c19a308` on `dnc_list`
UPDATE, and now the tenancy anchor itself. `USING` alone decided, and it admitted the row.

WHAT IS AT STAKE, and it is not "one row". Every tenant-scoped table carries `tenant_id
REFERENCES organizations(id) ON DELETE RESTRICT`; that row is what makes "this data
belongs to somebody" a fact the database enforces. FLOWS §9 makes offboarding a workflow,
`ck_organizations_deleted_implies_churned` guards the soft delete, and `db/registry.py`
calls `tenant_erasure_requests` "the only thing in this product that writes
`organizations.deleted_at`". A hard DELETE is not a faster version of any of that.

WHY THIS FILE RATHER THAN `rls_sweep_test.py`. That sweep asks "can tenant A touch tenant
B's rows", and this is a tenant touching its OWN row — outside every probe there by
construction, which is why five audit passes over this schema walked past it.

MIGRATION `d1b8f30c94a7` adds `organizations_delete_admin_only`, RESTRICTIVE FOR DELETE,
`USING (current_setting('app.admin', true) = 'on')`. The tests below pin both halves: a
tenant session removes nothing, and an admin session still can — because a policy that
also broke the platform's only legitimate remover would just be a different defect.

RED WITHOUT THE MIGRATION: `test_a_tenant_session_cannot_delete_its_own_organization`
and `test_a_tenant_session_cannot_delete_its_own_organization_by_a_bare_predicate` both
report `DELETE 1`. The three controls stay green either way, so the red is the subject
rather than the harness.

CONCURRENCY: every test mints its own childless organization through the owner connection
and removes it itself, so this file asserts nothing about global counts and runs beside
the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.core.settings import Settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _owner_url() -> str:
    url = Settings().alembic_database_url
    assert url, "ALEMBIC_DATABASE_URL required: minting a childless organization bypasses RLS"
    return url


async def _owner_execute(sql: str, params: dict[str, object]) -> int:
    """Ground truth, on the owner connection — the one that is not subject to the policy
    under test. Asking the attacker's session whether its own row is still there would let
    a successful DELETE answer "no rows, all clear" and read as a pass."""
    engine = create_async_engine(_owner_url())
    try:
        async with engine.begin() as conn:
            return int((await conn.execute(text(sql), params)).rowcount)
    finally:
        await engine.dispose()


async def _exists(tenant_id: uuid.UUID) -> bool:
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM organizations WHERE id = :id"), {"id": tenant_id}
                )
            ).first()
    finally:
        await engine.dispose()
    return row is not None


@pytest.fixture
async def childless_org() -> AsyncIterator[uuid.UUID]:
    """An organization with NO children.

    `admin_service.create_organization` is the way this repo mints one, and it is the
    wrong tool here: it also creates an agent, an extraction schema and retention
    policies, all behind `ON DELETE RESTRICT`, so the foreign keys would refuse the DELETE
    and the test would pass without the policy existing. The hole is only observable on a
    row nothing points at — which is exactly the row a mistyped prospect leaves behind.
    """
    tenant_id = uuid7()
    await _owner_execute(
        "INSERT INTO organizations (id, name, slug, status, plan_tier, created_at, "
        "updated_at) VALUES (:id, 'Delete Probe', :slug, 'active', 'managed', now(), now())",
        {"id": tenant_id, "slug": f"del-probe-{uuid.uuid4().hex[:8]}"},
    )
    try:
        yield tenant_id
    finally:
        await _owner_execute("DELETE FROM organizations WHERE id = :id", {"id": tenant_id})


async def test_a_tenant_session_cannot_delete_its_own_organization(
    childless_org: uuid.UUID,
) -> None:
    """THE HOLE. Red before `d1b8f30c94a7`: `rowcount == 1` and the row was gone."""
    async with tenant_session(childless_org) as session:
        removed = await session.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": childless_org}
        )
        assert removed.rowcount == 0, (
            "a tenant session deleted its own organizations row — the tenancy anchor every "
            "tenant table's FK points at"
        )
    assert await _exists(childless_org)


async def test_a_tenant_session_cannot_delete_its_own_organization_by_a_bare_predicate(
    childless_org: uuid.UUID,
) -> None:
    """The same attack without naming the id, because `WHERE id = :id` is not the shape a
    mistake takes. `DELETE FROM organizations` with no predicate at all is filtered by
    the policy to the rows the session may see — which, before the migration, was its own.
    """
    async with tenant_session(childless_org) as session:
        removed = await session.execute(text("DELETE FROM organizations"))
        assert removed.rowcount == 0, "an unqualified DELETE removed the session's own row"
    assert await _exists(childless_org)


async def test_an_untenanted_session_cannot_delete_an_organization(
    childless_org: uuid.UUID,
) -> None:
    """Control, and a real property: a session carrying no GUC at all sees zero rows on
    every tenant table (fail closed), so it cannot reach this one either."""
    async with untenanted_session() as session:
        removed = await session.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": childless_org}
        )
        assert removed.rowcount == 0
    assert await _exists(childless_org)


async def test_an_admin_session_can_still_delete_a_childless_organization() -> None:
    """The half that must NOT break. `admin_session` is the platform's only legitimate
    remover — a mistyped prospect that never got children — and a restrictive policy that
    caught it too would be a different defect wearing this one's clothes.

    This test mints and destroys its own row rather than using the fixture, because the
    fixture's teardown would then be deleting a row that is already gone.
    """
    tenant_id = uuid7()
    await _owner_execute(
        "INSERT INTO organizations (id, name, slug, status, plan_tier, created_at, "
        "updated_at) VALUES (:id, 'Delete Probe', :slug, 'active', 'managed', now(), now())",
        {"id": tenant_id, "slug": f"del-probe-{uuid.uuid4().hex[:8]}"},
    )
    async with admin_session() as session:
        removed = await session.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": tenant_id}
        )
        assert removed.rowcount == 1
    assert not await _exists(tenant_id)


async def test_a_tenant_session_can_still_read_and_soft_delete_its_own_organization(
    childless_org: uuid.UUID,
) -> None:
    """The other half that must not break: the restrictive policy is `FOR DELETE`, so
    SELECT and UPDATE are untouched. The soft delete is the lifecycle this repo actually
    has, and `ck_organizations_deleted_implies_churned` is why `status` moves with it.
    """
    async with tenant_session(childless_org) as session:
        name = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :id"), {"id": childless_org}
            )
        ).scalar()
        assert name == "Delete Probe"
        updated = await session.execute(
            text("UPDATE organizations SET status = 'churned', deleted_at = now() WHERE id = :id"),
            {"id": childless_org},
        )
        assert updated.rowcount == 1
