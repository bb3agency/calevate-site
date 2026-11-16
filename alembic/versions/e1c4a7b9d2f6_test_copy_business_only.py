"""A test copy records whether it holds "Just the business"

Revision ID: e1c4a7b9d2f6
Revises: d8b2f5a7c3e1
Create Date: 2026-11-16 18:00:00.000000

The agent page's Try it tries an agent on "just the business" (founder, 16 Nov 2026): the
company training and knowledge with no job's script, through the agent's developer-workspace
test copy (`agents/business_only`). The same copy still carries a campaign's test call on a
paying account with no number of its own, as the agent with that campaign's script. A
knowledge attach re-sends the whole agent, so it must know which of the two the copy was last
published as; `business_only` says so. Every existing copy was published as the agent, hence
the default.

`agent_test_copies` already has FORCEd RLS; a column changes nothing there.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1c4a7b9d2f6"
down_revision: str | None = "d8b2f5a7c3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_test_copies",
        sa.Column("business_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_test_copies", "business_only")
