"""a campaign can be archived and restored, by its client or by an operator (F-10)

Revision ID: c4a8e2f6b1d9
Revises: a9d3f6c2e8b1
Create Date: 2026-11-05 21:30:00.000000

Four nullable columns on `campaigns` (an existing tenant table; its FORCEd RLS policy is
unchanged and covers them): when it was archived, by whom, from which realm, and why (an
operator must say). The check keeps the four consistent: all empty, or an archive with a
realm, and a reason when the realm is admin.

No DML, so no NO FORCE / FORCE bracket. Reversible: `downgrade()` drops the check and the
columns, which loses only who archived what (the campaigns themselves stay).

Chained onto the integration head at the time of the lane E merge (a9d3f6c2e8b1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a8e2f6b1d9"
down_revision: str | None = "a9d3f6c2e8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("archived_by", sa.UUID(), nullable=True))
    op.add_column("campaigns", sa.Column("archived_by_realm", sa.String(), nullable=True))
    op.add_column("campaigns", sa.Column("archive_reason", sa.String(), nullable=True))
    op.create_check_constraint(
        op.f("ck_campaigns_archive_complete"),
        "campaigns",
        "(archived_at IS NULL AND archived_by_realm IS NULL AND archive_reason IS NULL) "
        "OR (archived_at IS NOT NULL AND archived_by_realm IN ('client', 'admin') "
        "AND (archived_by_realm = 'client' OR char_length(btrim(archive_reason)) >= 3))",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_campaigns_archive_complete"), "campaigns", type_="check")
    op.drop_column("campaigns", "archive_reason")
    op.drop_column("campaigns", "archived_by_realm")
    op.drop_column("campaigns", "archived_by")
    op.drop_column("campaigns", "archived_at")
