"""Negative controls for `scripts/check_metadata_columns`.

The guardrail is green against the repo as it stands, which proves nothing on its own —
`return []` is also green. These tests take the REAL live schema and hand the check a
DOCTORED model set that differs from it by exactly one column, in each direction, and
assert it is named. If the check stops looking at real columns, these go red.

The doctored metadata contains ONE table rather than a copy of all 57. That is
deliberate and not a shortcut: `compare_metadata` reports every absent table as a
`remove_table` op, and the check filters to `add_column`/`remove_column`, so the missing
tables are invisible to it — which is itself worth pinning, since a check that widened
its op set would start reporting 56 phantom failures here.
"""

from __future__ import annotations

import pytest
from apps.api.db.registry import Base
from scripts import check_metadata_columns
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text

#: A table with a column P4.3 actually caught, so the fixture stays tied to the finding.
TABLE = "campaigns"
COLUMN = "dnc_scrubbed_at"


@pytest.fixture(scope="module")
def url() -> str:
    """The migrated database, or a skip — the whole point is comparing against the real
    `pg_catalog`, so a stand-in would test nothing."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    resolved = (settings.alembic_database_url or settings.database_url).replace(
        "+asyncpg", "+psycopg"
    )
    engine = create_engine(resolved)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - local machines without docker
        pytest.skip(f"no database: {type(exc).__name__}: {exc}")
    finally:
        engine.dispose()
    return resolved


def _one_table(*, drop: str | None = None, add: str | None = None) -> MetaData:
    """The real table, rebuilt from public API, minus `drop` and plus `add`.

    Rebuilt rather than `to_metadata()`-copied because both ways of mutating a copied
    `Table` in place go through private members, and a doctored copy of the SHARED
    `Base.metadata` would leak a missing column into every other test in the process.
    Types are carried over verbatim; foreign keys and indexes are not, because the check
    judges neither.
    """
    real = Base.metadata.tables[TABLE]
    doctored = MetaData()
    columns = [
        Column(column.name, column.type, primary_key=column.primary_key, nullable=column.nullable)
        for column in real.columns
        if column.name != drop
    ]
    if add is not None:
        columns.append(Column(add, Integer(), nullable=True))
    Table(real.name, doctored, *columns)
    return doctored


def test_the_repo_as_it_stands_is_clean(url: str) -> None:
    """Wiring: the check is pointed at the real models and the real schema. This is the
    assertion the eight P4.3 columns each broke."""
    assert check_metadata_columns.column_differences(url) == []


def test_a_live_column_no_model_declares_is_reported(url: str) -> None:
    """The direction with eight instances and no guard: the database has it, the models
    do not, and `--autogenerate` would propose dropping it."""
    failures = check_metadata_columns.column_differences(url, _one_table(drop=COLUMN))
    assert [f for f in failures if f.startswith(f"{TABLE}.{COLUMN}:")], failures
    assert "DROPPING" in " ".join(failures)


def test_a_model_column_the_database_lacks_is_reported(url: str) -> None:
    """The other direction: a migration written and not applied, or not written at all."""
    invented = "column_no_migration_ever_added"
    failures = check_metadata_columns.column_differences(url, _one_table(add=invented))
    assert [f for f in failures if f.startswith(f"{TABLE}.{invented}:")], failures


def test_an_unmigrated_database_is_refused_rather_than_reported_clean() -> None:
    """D-176: the vacuous pass this check used to have, pinned in both halves.

    `sqlite://` is a database with nothing in it — every table the models declare is
    absent. `compare_metadata` reports each of those as ONE `add_table` op rather than one
    `add_column` per column, so the COLUMN verdict is empty and the check printed
    `METADATA COLUMNS: OK (61 tables agree in both directions)` against a schema it had
    never seen. Both assertions matter: the first is why a refusal is needed at all, and
    the second is the refusal seeing every one of them.

    No Postgres, deliberately: an empty in-memory database is exactly the input, and a test
    that skipped without one would be a negative control nobody ever runs.
    """
    entries = check_metadata_columns.compare_entries("sqlite://")

    assert check_metadata_columns.column_failures(entries) == []
    assert check_metadata_columns.absent_model_tables(entries) == sorted(Base.metadata.tables)


def test_absent_tables_are_not_reported_as_column_failures(url: str) -> None:
    """The scope pin: 56 of 57 tables are missing from the doctored metadata and the
    check says nothing about them. A widened op set would fail here before it reached CI
    and got switched off."""
    failures = check_metadata_columns.column_differences(url, _one_table())
    assert failures == []
