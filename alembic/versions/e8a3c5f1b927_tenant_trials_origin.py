"""tenant_trials.origin: the account's birth trial, or a gift an operator gave

Revision ID: e8a3c5f1b927
Revises: d4b9e2a7c3f1
Create Date: 2026-11-23

Only a gift trial waives a month's plan fee and platform fee (founder, 23 Nov 2026). Nothing
recorded how a trial began except `started_by`, an FK to `admin_users` that goes NULL when
the operator's row is removed, so it cannot carry the distinction on its own.

BACKFILL. A trial is `operator` when `started_by` is set (no birth trial writes it), or when
its `trial.started` audit row was written by an admin actor more than a minute after the
account was created: an account invited by an operator is born with its trial in the same
transaction, under the same admin actor, so the account's age is what tells the two apart.
Everything else is `signup`.

RLS is unchanged: a column on a table that already has its policy. Reversible: the
downgrade drops the constraint and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a3c5f1b927"
down_revision: str | None = "d4b9e2a7c3f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE tenant_trials t SET origin = 'operator'
WHERE t.started_by IS NOT NULL
   OR EXISTS (
        SELECT 1 FROM audit_log a JOIN organizations o ON o.id = t.tenant_id
        WHERE a.action = 'trial.started' AND a.object_type = 'tenant_trials'
          AND a.object_id = CAST(t.id AS text) AND a.actor_type = 'admin'
          AND t.started_at > o.created_at + interval '1 minute'
   )
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "tenant_trials",
        sa.Column("origin", sa.Text(), server_default=sa.text("'signup'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_tenant_trials_origin_enum"),
        "tenant_trials",
        "origin IN ('signup', 'operator')",
    )
    # Migrations run as the OWNER, which FORCEd RLS binds and which has no `app.tenant_id`
    # here, so without the bracket the backfill would match zero rows and report success.
    # It lifts RLS for the owner only, and FORCE is back before the transaction commits
    # (the `d3b71c9a5e08` bracket).
    op.execute("ALTER TABLE tenant_trials NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute(_BACKFILL)
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_trials FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_tenant_trials_origin_enum"), "tenant_trials", type_="check")
    op.drop_column("tenant_trials", "origin")
