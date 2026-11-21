"""agents.purpose: each agent is for selling or for helping customers

Revision ID: c3f8a1d6e274
Revises: bd9b4b153d5a
Create Date: 2026-11-21

A support agent never moves a lead to `interested` on the caller's tone alone, and an account
whose agents are all support reads "callers" where it read "leads" (founder, 21 Nov 2026).
Every existing agent is backfilled `sales` by the server default, so nothing already live
changes; a new agent takes its purpose from the business at creation
(`lifecycle.create_agent`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f8a1d6e274"
down_revision: str | None = "bd9b4b153d5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents",
        sa.Column("purpose", sa.String(), nullable=False, server_default=sa.text("'sales'")),
    )
    op.create_check_constraint(
        op.f("ck_agents_purpose_enum"), "agents", "purpose IN ('sales', 'support')"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_agents_purpose_enum"), "agents", type_="check")
    op.drop_column("agents", "purpose")
