"""`f3c9a1d5e7b2` retires the stored `actions_callback_base_url` row and nothing else.

Run as the owner role in a transaction that is always rolled back, because the table is
platform-wide and shared with the rest of the suite.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import Settings
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next((REPO_ROOT / "alembic" / "versions").glob("f3c9a1d5e7b2_*.py"))
RETIRED = "actions_callback_base_url"
KEPT = "engine_actions_base_url"


def _upgrade(conn: Connection) -> None:
    spec = importlib.util.spec_from_file_location("_retire_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The real `op` proxy bound to this connection, so the migration runs exactly as it
    # shipped, including `migration_offline.is_offline`, which reads the migration context.
    with Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def _keys(conn: Connection) -> set[str]:
    rows = conn.execute(
        text("SELECT key FROM platform_settings WHERE key IN (:a, :b)"), {"a": RETIRED, "b": KEPT}
    )
    return {str(row[0]) for row in rows}


async def test_the_migration_removes_the_retired_row_keeps_the_rest_and_can_run_twice() -> None:
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the migration runs as the owner"
    engine = create_async_engine(owner_url)
    admin_id = uuid.uuid4()
    url = json.dumps("https://hooks.example.test")

    def scenario(conn: Connection) -> list[set[str]]:
        conn.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Config Owner', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
        for key in (RETIRED, KEPT):
            conn.execute(
                text(
                    "INSERT INTO platform_settings (key, value, updated_by) "
                    "VALUES (:k, CAST(:v AS jsonb), :by) ON CONFLICT (key) DO NOTHING"
                ),
                {"k": key, "v": url, "by": admin_id},
            )
        seen = [_keys(conn)]
        _upgrade(conn)
        seen.append(_keys(conn))
        _upgrade(conn)
        seen.append(_keys(conn))
        return seen

    try:
        async with engine.connect() as conn:
            await conn.begin()
            try:
                seen: Any = await conn.run_sync(scenario)
            finally:
                await conn.rollback()
    finally:
        await engine.dispose()

    assert seen == [{RETIRED, KEPT}, {KEPT}, {KEPT}]
