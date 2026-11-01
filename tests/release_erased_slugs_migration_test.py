"""Migration c4e9a2d71f58 (D-954): every organization already erased gives up its slug, a
slug renamed by hand beforehand is left alone, and the downgrade restores the trigger that
refuses every slug change.

Run against the migrated database in one transaction that is rolled back, the way
`tests/follow_ups_migration_test.py` exercises its revision."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import get_settings
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

STEM = "c4e9a2d71f58_release_erased_slugs"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as(connection: Connection, tenant: UUID) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


def _org(connection: Connection, *, slug: str, erased: bool) -> UUID:
    org_id = uuid.uuid4()
    _as(connection, org_id)
    connection.execute(
        text(
            "INSERT INTO organizations (id, name, slug, status, deleted_at, created_at, "
            "updated_at) VALUES (:id, 'Rytu Khata', :slug, :status, "
            "CASE WHEN :erased THEN now() END, now(), now())"
        ),
        {"id": org_id, "slug": slug, "status": "churned" if erased else "active", "erased": erased},
    )
    return org_id


def _slug(connection: Connection, tenant: UUID) -> str:
    _as(connection, tenant)
    return str(
        connection.execute(
            text("SELECT slug FROM organizations WHERE id = :id"), {"id": tenant}
        ).scalar_one()
    )


def test_erased_organizations_release_their_slugs_and_the_downgrade_locks_them_again() -> None:
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    tag = uuid.uuid4().hex[:8]
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    erased = _org(connection, slug=f"rytu-{tag}", erased=True)
                    live = _org(connection, slug=f"live-{tag}", erased=False)
                    by_hand = _org(connection, slug=f"erased-{tag}", erased=True)

                    _as(connection, erased)
                    with (
                        pytest.raises(DBAPIError, match="immutable"),
                        connection.begin_nested(),
                    ):
                        connection.execute(
                            text(
                                "UPDATE organizations SET slug = 'erased-' || "
                                "replace(id::text, '-', '') WHERE id = :id"
                            ),
                            {"id": erased},
                        )

                    revision.upgrade()
                    assert _slug(connection, erased) == f"erased-{erased.hex}"
                    assert _slug(connection, live) == f"live-{tag}"
                    assert _slug(connection, by_hand) == f"erased-{tag}", (
                        "a rename run by hand before the migration is left as it is"
                    )
                    # The released address is free for a new account.
                    _org(connection, slug=f"rytu-{tag}", erased=False)
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
