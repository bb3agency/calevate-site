"""Guardrail: every tenant table has FORCEd RLS (hard rule 1; ENGINEERING-PRACTICES §2).

Checks the LIVE database after migrations:
1. every table with a tenant_id column either has a FORCEd tenant_isolation policy
   or is explicitly listed in RLS_EXEMPT_TENANT_COLUMNS with a reason;
2. every append-only ledger has its immutability trigger;
3. the registry's TENANT_TABLES stays in sync with reality (a new tenant table
   missing from the registry fails here, not in production).

Run: uv run python -m scripts.check_rls_coverage   (needs migrated DB; owner URL)
"""

import os
import sys
from pathlib import Path

from apps.api.db.registry import (
    APPEND_ONLY_TABLES,
    RLS_EXEMPT_TENANT_COLUMNS,
    TENANT_TABLES,
    Base,
)
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    failures: list[str] = []

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c "
                "JOIN pg_tables t ON t.tablename = c.table_name AND t.schemaname = 'public' "
                "WHERE c.column_name = 'tenant_id' AND c.table_schema = 'public'"
            )
        )
        tenant_col_tables = {r[0] for r in rows}

        policies = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_policy p ON p.polrelid = c.oid "
                    "WHERE p.polname = 'tenant_isolation'"
                )
            )
        }

        triggers = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT event_object_table FROM information_schema.triggers "
                    "WHERE trigger_name LIKE '%_append_only'"
                )
            )
        }

    # 1. Every tenant_id table is policied or exempt-with-reason.
    for table in sorted(tenant_col_tables):
        if table in RLS_EXEMPT_TENANT_COLUMNS:
            continue
        if table not in policies:
            failures.append(f"{table}: has tenant_id but NO tenant_isolation policy")
        else:
            enabled, forced = policies[table]
            if not (enabled and forced):
                failures.append(
                    f"{table}: RLS not ENABLEd+FORCEd (enabled={enabled}, forced={forced})"
                )

    # organizations (tenant root, policy on id) must be covered too.
    if "organizations" not in policies:
        failures.append("organizations: tenant root missing its tenant_isolation policy")

    # 2. Registry drift, both directions.
    expected = set(TENANT_TABLES)
    actual = tenant_col_tables - set(RLS_EXEMPT_TENANT_COLUMNS)
    if expected != actual:
        failures.append(
            f"registry drift: TENANT_TABLES vs live schema — "
            f"only-in-registry={sorted(expected - actual)}, only-in-db={sorted(actual - expected)}"
        )
    model_tables = set(Base.metadata.tables)
    unknown = actual - model_tables
    if unknown:
        failures.append(f"tables in DB not in model metadata: {sorted(unknown)}")

    # 3. Append-only triggers present.
    for table in APPEND_ONLY_TABLES:
        if table not in triggers:
            failures.append(f"{table}: append-only immutability trigger missing")

    if failures:
        print("RLS COVERAGE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"RLS COVERAGE: OK ({len(tenant_col_tables)} tenant-column tables, "
        f"{len(policies)} policied, {len(RLS_EXEMPT_TENANT_COLUMNS)} exempt-with-reason, "
        f"{len(APPEND_ONLY_TABLES)} append-only triggers)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
