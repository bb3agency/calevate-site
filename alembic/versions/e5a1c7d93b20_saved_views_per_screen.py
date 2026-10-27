"""Saved views belong to a screen: the Leads table or the Calls log (D-893 L2)

Revision ID: e5a1c7d93b20
Revises: d7c2e9a4f6b1
Create Date: 2026-10-27 21:00:00.000000

`lead_saved_views` held the Leads table's views only. The Calls log now saves views too, in
the same table: same owner, same privacy, same per-person cap and the same tenant policy, so
a second table would have been a second copy of all four. `screen` says which screen a view
belongs to; every existing row is a Leads view and takes the default.

A name is unique per person PER SCREEN, so "Missed this week" may exist on both.

DOWNGRADE deletes the Calls views (the old table cannot say which screen a row belongs to),
then puts the old per-person name rule back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a1c7d93b20"
down_revision: str | None = "d7c2e9a4f6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "lead_saved_views",
        sa.Column("screen", sa.Text(), server_default=sa.text("'leads'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_lead_saved_views_screen_is_known"),
        "lead_saved_views",
        "screen IN ('leads', 'calls')",
    )
    op.drop_constraint(
        op.f("uq_lead_saved_views_tenant_user_name"), "lead_saved_views", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_lead_saved_views_tenant_user_screen_name"),
        "lead_saved_views",
        ["tenant_id", "user_id", "screen", "name"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DELETE FROM lead_saved_views WHERE screen <> 'leads'")
    op.drop_constraint(
        op.f("uq_lead_saved_views_tenant_user_screen_name"), "lead_saved_views", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_lead_saved_views_tenant_user_name"),
        "lead_saved_views",
        ["tenant_id", "user_id", "name"],
    )
    op.drop_constraint(
        op.f("ck_lead_saved_views_screen_is_known"), "lead_saved_views", type_="check"
    )
    op.drop_column("lead_saved_views", "screen")
