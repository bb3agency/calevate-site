"""`platform_ai_usage` is append-only AND lets `ON DELETE SET NULL` through (e5c9a2d71f38).

Migration `f2c81a4d05e7` declared `viewing_tenant_id` `ON DELETE SET NULL` and said why on
the column — *"an offboarded tenant must be deletable, and platform accounting outlives the
account it was about"* — then put the blanket `calevate_forbid_mutation` on the same table.
Postgres performs a `SET NULL` referential action as an ordinary UPDATE of the referencing
row, so the trigger fired on it and the organization delete failed with "platform_ai_usage
is append-only". The promise on the column and the guard twenty lines below it said
opposite things, and the guard won: one admin-copilot turn with a client on screen made
that client's row permanently undeletable.

The five tests below pin both halves of the fix, because a bounded exception is only worth
having if the bound is asserted: the referential action goes through and the money on the
row survives it, while an UPDATE, a DELETE and a laundered UPDATE (the price moved under
cover of clearing the tenant) are all still refused.

RED WITHOUT THE MIGRATION: `test_deleting_a_tenant_the_copilot_viewed_succeeds` raises
`ProgrammingError` and `test_the_money_on_the_row_survives_the_tenant_delete` cannot reach
its assertions. The other three stay green either way — they are the bound, not the
subject.

CONCURRENCY: every test mints its OWN childless organization on the owner connection and
its own ledger row, and asserts nothing about global counts, so this file runs beside the
rest of the suite on the shared Postgres. The ledger rows it writes are never removed —
`platform_ai_usage` is append-only and that is the point — so they are stamped with a
`system_actor` that names this file.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from apps.api.core.settings import Settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.rls]

ACTOR = "test:platform_ai_usage_tenant_delete"


def _owner_url() -> str:
    url = Settings().alembic_database_url
    assert url, "ALEMBIC_DATABASE_URL required: minting a childless organization bypasses RLS"
    return url


async def _owner(sql: str, params: dict[str, object]) -> None:
    engine = create_async_engine(_owner_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)
    finally:
        await engine.dispose()


async def _viewing_tenant(row_id: uuid.UUID) -> uuid.UUID | None:
    async with untenanted_session() as session:
        value = (
            await session.execute(
                text("SELECT viewing_tenant_id FROM platform_ai_usage WHERE id = :i"),
                {"i": row_id},
            )
        ).scalar()
    return None if value is None else uuid.UUID(str(value))


@pytest.fixture
async def childless_org() -> AsyncIterator[uuid.UUID]:
    """An organization nothing else points at.

    `admin_service.create_organization` also mints an agent, an extraction schema and
    retention policies, every one behind `ON DELETE RESTRICT` — so the foreign keys would
    refuse the DELETE and the test would pass without the fix. The hole is only observable
    on a row nothing else references, which is exactly the row a mistyped prospect leaves
    behind and the row an operator reaches for the delete button on.
    """
    tenant_id = uuid7()
    await _owner(
        "INSERT INTO organizations (id, name, slug, status, plan_tier, created_at, "
        "updated_at) VALUES (:id, 'AI Usage Probe', :slug, 'active', 'managed', now(), now())",
        {"id": tenant_id, "slug": f"ai-probe-{uuid.uuid4().hex[:8]}"},
    )
    yield tenant_id
    # Best effort: the passing case has already removed it, and a failing case must leave
    # the evidence rather than tidy it away.
    await _owner("DELETE FROM organizations WHERE id = :id", {"id": tenant_id})


async def _copilot_row(viewing: uuid.UUID | None) -> uuid.UUID:
    """One platform-ledger row, written the way `record_platform_ai_usage` writes them."""
    row_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_ai_usage (id, admin_user_id, system_actor, "
                "viewing_tenant_id, unit_type, qty, unit_cost_paid, ref, occurred_at, meta, "
                "created_at) VALUES (:id, NULL, :actor, :viewing, 'ai_assist_ktok_in', 1.5, "
                "0.0132, :ref, now(), CAST(:meta AS jsonb), now())"
            ),
            {
                "id": row_id,
                "actor": ACTOR,
                "viewing": viewing,
                "ref": f"assist:{uuid.uuid4()}",
                "meta": f'{{"kind": "dashboard_ai_assist", "viewing_tenant_id": "{viewing}"}}',
            },
        )
    return row_id


async def test_deleting_a_tenant_the_copilot_viewed_succeeds(childless_org: uuid.UUID) -> None:
    """THE SUBJECT. `ON DELETE SET NULL` is an UPDATE, and it must reach the row."""
    row_id = await _copilot_row(childless_org)
    assert await _viewing_tenant(row_id) == childless_org

    async with admin_session() as session:
        await session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": childless_org})

    assert await _viewing_tenant(row_id) is None, "the referential action cleared the column"


async def test_the_money_on_the_row_survives_the_tenant_delete(
    childless_org: uuid.UUID,
) -> None:
    """The exception clears ONE column. What the answer cost us is still on the ledger —
    which is the whole reason `SET NULL` was chosen over `CASCADE` (f2c81a4d05e7)."""
    row_id = await _copilot_row(childless_org)
    async with admin_session() as session:
        await session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": childless_org})
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT qty, unit_cost_paid, meta->>'viewing_tenant_id' "
                    "FROM platform_ai_usage WHERE id = :i"
                ),
                {"i": row_id},
            )
        ).first()
    assert row is not None
    assert Decimal(str(row[0])) == Decimal("1.5")
    assert Decimal(str(row[1])) == Decimal("0.0132")
    assert row[2] == str(childless_org), "meta still says which account it was about"


async def test_an_ordinary_update_is_still_refused() -> None:
    """THE BOUND. Nothing but the referential action gets through."""
    row_id = await _copilot_row(None)
    with pytest.raises(Exception, match="append-only"):
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE platform_ai_usage SET unit_cost_paid = 0 WHERE id = :i"),
                {"i": row_id},
            )


async def test_a_delete_is_still_refused() -> None:
    row_id = await _copilot_row(None)
    with pytest.raises(Exception, match="append-only"):
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_ai_usage WHERE id = :i"), {"i": row_id}
            )


async def test_clearing_the_tenant_may_not_smuggle_a_price_change(
    childless_org: uuid.UUID,
) -> None:
    """The bound that matters most, and the reason the permitted transition names every
    other column: an UPDATE that nulls `viewing_tenant_id` AND moves `unit_cost_paid` is
    not the referential action, and a trigger that only checked the one column would have
    made this the way to edit an append-only price."""
    row_id = await _copilot_row(childless_org)
    with pytest.raises(Exception, match="append-only"):
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_ai_usage SET viewing_tenant_id = NULL, "
                    "unit_cost_paid = 99 WHERE id = :i"
                ),
                {"i": row_id},
            )
    assert await _viewing_tenant(row_id) == childless_org
