"""agents.caller_has_screen: the caller follows the agent's steps on a screen (D-906)

Revision ID: e7c2a9b4d158
Revises: d8f3a6c1e924
Create Date: 2026-10-27

The owner's switch for a guided-setup or support agent: the composed prompt lets the agent name
on-screen labels, give one step a turn and spell a web address. Off for every existing agent,
so no prompt changes until an owner turns it on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c2a9b4d158"
down_revision: str | None = "d8f3a6c1e924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents",
        sa.Column(
            "caller_has_screen", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "caller_has_screen")
