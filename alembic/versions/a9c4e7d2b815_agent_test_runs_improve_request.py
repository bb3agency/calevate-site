"""agent_test_runs: "Improve my agent" runs as a job, and says when it is working or why it failed (D-748)

The proposal returns the whole script and does not fit the 15 s a route allows each model leg,
so the route now queues the existing improve job and the screen polls. Two additive nullable
columns: when the owner asked (the screen shows "working out fixes" until a proposal newer than
it arrives), and the owner-facing sentence when it could not be made. The table's FORCEd RLS
policy (f7c3a9e15d26) covers the new columns; no policy changes.

Revision ID: a9c4e7d2b815
Revises: f8c3a1d9e4b2
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e7d2b815"
down_revision: str | None = "f8c3a1d9e4b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_test_runs"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        TABLE, sa.Column("improve_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("improve_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "improve_note")
    op.drop_column(TABLE, "improve_requested_at")
