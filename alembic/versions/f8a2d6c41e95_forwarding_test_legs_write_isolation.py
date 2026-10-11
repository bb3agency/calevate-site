"""forwarding_test_legs: one client cannot rewrite another's test legs

Revision ID: f8a2d6c41e95
Revises: e5b1c8d42a07
Create Date: 2026-10-11 18:30:00.000000

`forwarding_test_legs` (D-746) is in `RLS_EXEMPT_TENANT_COLUMNS` because the shared trial line
must count every client's live legs, and it was created with no row-level security at all.
The exemption argues a READ; with no policy, any session (tenant A's, or one with no tenant)
could UPDATE, re-tenant or DELETE tenant B's legs. `tests/rls_sweep_test.py` measured exactly
that once the table held a row of another tenant.

The fix is `engine_agent_routes`' two-policy shape (c4b70e928a1f) without its untenanted
write arm, which b8e2d47f0c19 later removed there: the platform-wide count keeps a
`FOR SELECT USING (true)` policy, and every write is `tenant_isolation`, own tenant only.
Every writer already knows the leg's tenant and now writes inside `tenant_session`
(`forwarding/testing.py`); the erasure DELETE already ran in the tenant's own session.

Locking: `ALTER TABLE ... ROW LEVEL SECURITY` and `CREATE POLICY` take ACCESS EXCLUSIVE briefly
and touch no rows; `lock_timeout` bounds the wait. Downgrade restores the policy-less table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8a2d6c41e95"
down_revision: str | None = "e5b1c8d42a07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "forwarding_test_legs"
READ_POLICY = "forwarding_test_legs_global_read"
WRITE_POLICY = "tenant_isolation"

# Spelled out here rather than imported: a migration is a snapshot of the schema on its day.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {READ_POLICY} ON {TABLE} FOR SELECT USING (true)")
    op.execute(
        f"CREATE POLICY {WRITE_POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {WRITE_POLICY} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
