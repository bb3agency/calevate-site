"""The migrations that retire a stored console row remove that row and nothing else:
`f3c9a1d5e7b2` (`actions_callback_base_url`, D-642) and `b7e4c2d9f1a3`
(`thinnest_reply_languages`, D-830).

Run as the owner role in a transaction that is always rolled back, because the table is
platform-wide and shared with the rest of the suite.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import Settings
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
KEPT = "engine_actions_base_url"
#: (revision, the key it retires, a value such a row held).
RETIREMENTS = (
    ("f3c9a1d5e7b2", "actions_callback_base_url", "https://hooks.example.test"),
    ("b7e4c2d9f1a3", "thinnest_reply_languages", True),
)


def _upgrade(conn: Connection, revision: str) -> None:
    migration = next((REPO_ROOT / "alembic" / "versions").glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_retire_{revision}", migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The real `op` proxy bound to this connection, so the migration runs exactly as it
    # shipped, including `migration_offline.is_offline`, which reads the migration context.
    with Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def _keys(conn: Connection, retired: str) -> set[str]:
    rows = conn.execute(
        text("SELECT key FROM platform_settings WHERE key IN (:a, :b)"), {"a": retired, "b": KEPT}
    )
    return {str(row[0]) for row in rows}


@pytest.mark.parametrize(("revision", "retired", "value"), RETIREMENTS)
async def test_the_migration_removes_the_retired_row_keeps_the_rest_and_can_run_twice(
    revision: str, retired: str, value: object
) -> None:
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the migration runs as the owner"
    engine = create_async_engine(owner_url)
    admin_id = uuid.uuid4()

    def scenario(conn: Connection) -> list[set[str]]:
        conn.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Config Owner', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
        for key, stored in ((retired, value), (KEPT, "https://hooks.example.test")):
            conn.execute(
                text(
                    "INSERT INTO platform_settings (key, value, updated_by) "
                    "VALUES (:k, CAST(:v AS jsonb), :by) ON CONFLICT (key) DO NOTHING"
                ),
                {"k": key, "v": json.dumps(stored), "by": admin_id},
            )
        seen = [_keys(conn, retired)]
        _upgrade(conn, revision)
        seen.append(_keys(conn, retired))
        _upgrade(conn, revision)
        seen.append(_keys(conn, retired))
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

    assert seen == [{retired, KEPT}, {KEPT}, {KEPT}]
