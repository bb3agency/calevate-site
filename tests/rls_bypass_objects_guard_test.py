"""Rule 9 of `scripts/check_rls_coverage`: nothing reads a guarded table past its policies.

Rules 1-8 prove each TABLE isolates. A view runs with its owner's privileges unless it is
`security_invoker`; migrations run as the owner role, which is a superuser here and so
bypasses RLS even under FORCE; and default privileges grant the app role SELECT on every
new relation. So one reporting view in a migration reads every tenant's rows for every
tenant session, while every table still passes rules 1-8. These tests build each shape
inside a transaction on the owner's connection, show the bypass as the app role, read the
catalogue from the same transaction, and roll everything back.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from apps.api.core.settings import get_settings
from scripts import check_rls_coverage
from sqlalchemy import Connection, create_engine, text

APP_ROLE = "calevate_app"


@pytest.fixture
def owner() -> Iterator[Connection]:
    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                yield conn
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


#: Rule 9's own findings, told apart from the registry-drift findings the probe table
#: itself raises (it is, deliberately, in no registry).
RULE_NINE_MARKERS = ("security_invoker", "MATERIALIZED VIEW", "SECURITY DEFINER")


def _rule_nine(conn: Connection) -> list[str]:
    failures = check_rls_coverage.evaluate(check_rls_coverage.read_state(conn))
    return [f for f in failures if any(marker in f for marker in RULE_NINE_MARKERS)]


def _tenants_seen(conn: Connection, relation: str) -> int:
    """How many tenants `relation` shows to the APP role scoped to one tenant."""
    conn.execute(text("SAVEPOINT as_app"))
    conn.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
    conn.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": "01a0dbf3-0000-7000-8000-000000000001"},
    )
    seen = conn.execute(text(f"SELECT count(DISTINCT tenant_id) FROM {relation}")).scalar_one()
    conn.execute(text("ROLLBACK TO SAVEPOINT as_app"))
    return int(seen)


def _seed_two_tenants(conn: Connection) -> None:
    """Two tenants with one row each in a policied table, so a bypass has something to
    show. Everything rolls back with the fixture's transaction."""
    for suffix in ("1", "2"):
        tenant = f"01a0dbf3-0000-7000-8000-00000000000{suffix}"
        conn.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
            {"id": tenant, "n": f"Probe {suffix}", "s": f"rlsprobe-{suffix}"},
        )
        conn.execute(
            text("INSERT INTO rlsprobe_rows (tenant_id) VALUES (:id)"),
            {"id": tenant},
        )


@pytest.fixture
def policied(owner: Connection) -> Connection:
    """A FORCE-RLS'd tenant table in the migrations' own shape, owned like theirs."""
    owner.execute(
        text("CREATE TABLE rlsprobe_rows (tenant_id uuid NOT NULL REFERENCES organizations(id))")
    )
    owner.execute(text("ALTER TABLE rlsprobe_rows ENABLE ROW LEVEL SECURITY"))
    owner.execute(text("ALTER TABLE rlsprobe_rows FORCE ROW LEVEL SECURITY"))
    owner.execute(
        text(
            "CREATE POLICY tenant_isolation ON rlsprobe_rows USING "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    )
    owner.execute(text(f"GRANT SELECT ON rlsprobe_rows TO {APP_ROLE}"))
    _seed_two_tenants(owner)
    return owner


def test_the_live_catalogue_has_no_bypassing_object() -> None:
    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    try:
        state = check_rls_coverage.fetch_state(engine)
    finally:
        engine.dispose()
    failures = check_rls_coverage.evaluate(state)
    assert not [f for f in failures if any(m in f for m in RULE_NINE_MARKERS)], failures


def test_an_owner_rights_view_over_a_policied_table_is_refused(policied: Connection) -> None:
    policied.execute(
        text("CREATE VIEW rlsprobe_totals AS SELECT tenant_id, 1 AS n FROM rlsprobe_rows")
    )
    policied.execute(text(f"GRANT SELECT ON rlsprobe_totals TO {APP_ROLE}"))

    assert _tenants_seen(policied, "rlsprobe_rows") == 1
    assert _tenants_seen(policied, "rlsprobe_totals") == 2, "the view did not bypass RLS"

    failures = _rule_nine(policied)
    assert any("rlsprobe_totals" in f and "security_invoker" in f for f in failures), failures


def test_a_security_invoker_view_is_accepted(policied: Connection) -> None:
    policied.execute(
        text(
            "CREATE VIEW rlsprobe_totals WITH (security_invoker = true) AS "
            "SELECT tenant_id, 1 AS n FROM rlsprobe_rows"
        )
    )
    policied.execute(text(f"GRANT SELECT ON rlsprobe_totals TO {APP_ROLE}"))

    assert _tenants_seen(policied, "rlsprobe_totals") == 1
    assert _rule_nine(policied) == []


def test_an_owner_rights_view_over_an_invoker_view_is_not_a_finding(
    policied: Connection,
) -> None:
    """The precision half of judging a view by its own base tables: an invoker view's base
    tables are checked as the QUERYING user even when an owner-rights view wraps it, so the
    pair isolates and refusing it would be a false alarm."""
    policied.execute(
        text(
            "CREATE VIEW rlsprobe_inner WITH (security_invoker = true) AS "
            "SELECT tenant_id FROM rlsprobe_rows"
        )
    )
    policied.execute(text("CREATE VIEW rlsprobe_outer AS SELECT tenant_id FROM rlsprobe_inner"))
    policied.execute(text(f"GRANT SELECT ON rlsprobe_outer TO {APP_ROLE}"))

    assert _tenants_seen(policied, "rlsprobe_outer") == 1
    assert _rule_nine(policied) == []


def test_an_owner_rights_view_is_reported_wherever_it_sits_in_a_chain(
    policied: Connection,
) -> None:
    policied.execute(text("CREATE VIEW rlsprobe_inner AS SELECT tenant_id FROM rlsprobe_rows"))
    policied.execute(
        text(
            "CREATE VIEW rlsprobe_outer WITH (security_invoker = true) AS "
            "SELECT tenant_id FROM rlsprobe_inner"
        )
    )
    policied.execute(text(f"GRANT SELECT ON rlsprobe_inner, rlsprobe_outer TO {APP_ROLE}"))

    assert _tenants_seen(policied, "rlsprobe_outer") == 2
    failures = _rule_nine(policied)
    assert any("rlsprobe_inner" in f for f in failures), failures


def test_a_materialized_view_over_a_policied_table_is_refused(policied: Connection) -> None:
    policied.execute(
        text("CREATE MATERIALIZED VIEW rlsprobe_snapshot AS SELECT tenant_id FROM rlsprobe_rows")
    )
    failures = _rule_nine(policied)
    assert any("rlsprobe_snapshot" in f and "MATERIALIZED" in f for f in failures), failures


def test_a_view_over_an_unguarded_table_is_not_a_finding(owner: Connection) -> None:
    """`reserved_slugs` is global and carries no policy; a view of it reaches nothing."""
    owner.execute(text("CREATE VIEW rlsprobe_slugs AS SELECT slug FROM reserved_slugs"))
    assert _rule_nine(owner) == []


def test_a_security_definer_owned_by_the_superuser_is_refused(policied: Connection) -> None:
    policied.execute(
        text(
            "CREATE FUNCTION rlsprobe_count() RETURNS bigint LANGUAGE sql SECURITY DEFINER "
            "AS 'SELECT count(DISTINCT tenant_id) FROM rlsprobe_rows'"
        )
    )
    policied.execute(text("SAVEPOINT as_app"))
    policied.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
    policied.execute(
        text("SELECT set_config('app.tenant_id', '01a0dbf3-0000-7000-8000-000000000001', true)")
    )
    assert policied.execute(text("SELECT rlsprobe_count()")).scalar_one() == 2
    policied.execute(text("ROLLBACK TO SAVEPOINT as_app"))

    failures = _rule_nine(policied)
    assert any("rlsprobe_count()" in f and "SECURITY DEFINER" in f for f in failures), failures


def test_a_security_invoker_function_is_not_a_finding(policied: Connection) -> None:
    policied.execute(
        text(
            "CREATE FUNCTION rlsprobe_count() RETURNS bigint LANGUAGE sql "
            "AS 'SELECT count(DISTINCT tenant_id) FROM rlsprobe_rows'"
        )
    )
    assert _rule_nine(policied) == []
