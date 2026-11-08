"""Migration a7d3e9c1b5f2: an agent waits at least 10 s before asking whether the caller is
still there (founder, 6 Nov 2026). Stored 5-9 values become 10, 0 and NULL are untouched, each
client whose live agent the raise reaches gets one live apply, and the CHECK refuses 9.

Run against the migrated database in one transaction that is rolled back, the way
`tests/release_erased_slugs_migration_test.py` exercises its revision."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import get_settings
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _make_live, _tenant

STEM = "a7d3e9c1b5f2_nudge_waits_at_least_ten_seconds"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as(connection: Connection, tenant: UUID) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


def _agent_wait(connection: Connection, tenant: UUID, agent: UUID) -> int | None:
    _as(connection, tenant)
    return connection.execute(
        text("SELECT nudge_after_seconds FROM agents WHERE id = :id"), {"id": agent}
    ).scalar_one()


def _runs(connection: Connection, tenant: UUID) -> list[list[str]]:
    rows = connection.execute(
        text(
            "SELECT reasons FROM live_apply_runs WHERE tenant_id = :t AND scope = 'tenant' "
            "AND reasons ? 'nudge_after_floor'"
        ),
        {"t": tenant},
    ).all()
    return [list(r[0]) for r in rows]


async def test_stored_waits_under_ten_seconds_are_raised_and_live_agents_republished() -> None:
    own_tenant, own_agent, _ = await _tenant()  # a live agent with its own 7 s
    acct_tenant, acct_agent, _ = await _tenant()  # a live agent inheriting the account's 6 s
    never_tenant, never_agent, _ = await _tenant()  # "never ask" and a draft agent at 8 s
    await _make_live(own_tenant, own_agent)
    await _make_live(acct_tenant, acct_agent)

    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    _as(connection, own_tenant)
                    connection.execute(
                        text("UPDATE agents SET nudge_after_seconds = 7 WHERE id = :id"),
                        {"id": own_agent},
                    )
                    _as(connection, acct_tenant)
                    connection.execute(
                        text(
                            "UPDATE organizations SET default_nudge_after_seconds = 6 "
                            "WHERE id = :id"
                        ),
                        {"id": acct_tenant},
                    )
                    _as(connection, never_tenant)
                    connection.execute(
                        text(
                            "UPDATE organizations SET default_nudge_after_seconds = 0 "
                            "WHERE id = :id"
                        ),
                        {"id": never_tenant},
                    )
                    connection.execute(
                        text("UPDATE agents SET nudge_after_seconds = 8 WHERE id = :id"),
                        {"id": never_agent},
                    )

                    revision.upgrade()

                    assert _agent_wait(connection, own_tenant, own_agent) == 10
                    assert _agent_wait(connection, acct_tenant, acct_agent) is None
                    _as(connection, acct_tenant)
                    assert (
                        connection.execute(
                            text(
                                "SELECT default_nudge_after_seconds FROM organizations "
                                "WHERE id = :id"
                            ),
                            {"id": acct_tenant},
                        ).scalar_one()
                        == 10
                    )
                    assert _agent_wait(connection, never_tenant, never_agent) == 10
                    _as(connection, never_tenant)
                    assert (
                        connection.execute(
                            text(
                                "SELECT default_nudge_after_seconds FROM organizations "
                                "WHERE id = :id"
                            ),
                            {"id": never_tenant},
                        ).scalar_one()
                        == 0
                    ), "never ask is a choice the floor leaves alone"

                    assert _runs(connection, own_tenant) == [["nudge_after_floor"]]
                    assert _runs(connection, acct_tenant) == [["nudge_after_floor"]]
                    assert _runs(connection, never_tenant) == [], "a draft agent has no call"

                    _as(connection, own_tenant)
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(
                            text("UPDATE agents SET nudge_after_seconds = 9 WHERE id = :id"),
                            {"id": own_agent},
                        )
                    _as(connection, acct_tenant)
                    with pytest.raises(IntegrityError), connection.begin_nested():
                        connection.execute(
                            text(
                                "UPDATE organizations SET default_nudge_after_seconds = 9 "
                                "WHERE id = :id"
                            ),
                            {"id": acct_tenant},
                        )

                    # Down again: the old range is back, and 10 stays (it is in it).
                    revision.downgrade()
                    _as(connection, own_tenant)
                    connection.execute(
                        text("UPDATE agents SET nudge_after_seconds = 5 WHERE id = :id"),
                        {"id": own_agent},
                    )
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
