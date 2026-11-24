"""Pip's weekly summary of each account's week, for the account-wide Improve page

Revision ID: f2a7c4e9b1d6
Revises: e5b9c3a7d1f4
Create Date: 2026-11-25 12:00:00.000000

`weekly_summaries`: one row per tenant per IST week (the Monday it began), holding the short
paragraph Pip wrote and the counts it was written from (`campaigns/weekly_summary`,
`workers/weekly_summary`). The unique key on (tenant, week) is the job's idempotency: a second
run of the same week finds the row and writes nothing.

Tenant data, FORCEd RLS in this migration (hard rule 1). Nothing is backfilled: the first row
of each account is written by the next weekly run.

REVERSIBILITY. `downgrade()` drops the table; no other table reads it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a7c4e9b1d6"
down_revision: str | None = "e5b9c3a7d1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "weekly_summaries"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
SUMMARY_MAX = 1200


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("figures", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "tenant_id", "week_start", name="uq_weekly_summaries_tenant_id_week_start"
        ),
        sa.CheckConstraint(f"length(summary) <= {SUMMARY_MAX}", name="summary_short"),
    )
    op.create_index("ix_weekly_summaries_tenant_id", TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index("ix_weekly_summaries_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
