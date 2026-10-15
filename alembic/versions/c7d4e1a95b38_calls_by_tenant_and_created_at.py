"""calls are found by tenant and creation time (D-787)

Revision ID: c7d4e1a95b38
Revises: a6e2c9f41d83
Create Date: 2026-10-15 12:30:00.000000

`ix_calls_tenant_created` on `calls (tenant_id, created_at DESC)`.

Three reads filter one tenant's calls by `created_at` and had no index to do it with, so
each scanned every call the tenant ever made: the attention queue's failed calls
(`crm/attention.py`, read by the header bell on every console page and polled), the
Performance tab's three aggregates (`crm/performance.py`), and the healer's health window
(`healer/health.py`). `ix_calls_tenant_started` does not serve them: `started_at` is a
different column, NULL until a call is dialled.

Measured on 60,000 calls of one tenant (EXPLAIN ANALYZE as the app role, under RLS): the
failed-calls read 11.4 ms -> 0.42 ms, the Performance 7-day count 13.3 ms -> 0.16 ms.

`CONCURRENTLY`, in `autocommit_block()`, because `calls` is written by every live call and
a plain `CREATE INDEX` holds a SHARE lock that blocks those writes for the whole build.
An interrupted build leaves an INVALID index (`runbooks/deploy-failed.md` has the
`pg_index WHERE NOT indisvalid` query); `IF NOT EXISTS` makes the re-run safe once it is
dropped.
"""

from __future__ import annotations

from alembic import op

revision = "c7d4e1a95b38"
down_revision = "a6e2c9f41d83"
branch_labels = None
depends_on = None

_INDEX = "ix_calls_tenant_created"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON calls (tenant_id, created_at DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
