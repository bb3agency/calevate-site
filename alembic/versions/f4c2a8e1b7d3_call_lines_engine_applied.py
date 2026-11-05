"""organizations: the calls-at-once value the voice platform confirmed, and when

Revision ID: f4c2a8e1b7d3
Revises: f5a9c3e1d7b2
Create Date: 2026-11-05 20:00:00.000000

`organizations.call_lines` is what an operator chose; the client's own ThinnestAI workspace
enforces `allottedCallLines`, which the outbox job `sync_engine_call_lines` sets and reads
back. Until now nothing recorded that read-back, so a raise was announced to the client in
the same transaction that saved it, before the platform held it (audit finding A7-06).

- `call_lines_applied`: the value the platform read back, NULL until a sync succeeded.
- `call_lines_applied_at`: when it was read back.

`organizations` already carries FORCEd row-level security on `id`; a column adds no policy.
ADD COLUMN without a default is a catalog change; `lock_timeout` bounds the wait. No
backfill: an account whose value was set before this reads "not confirmed yet" until its next
sync or the daily sweep. Downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c2a8e1b7d3"
down_revision: str | None = "f5a9c3e1d7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("organizations", sa.Column("call_lines_applied", sa.Integer(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("call_lines_applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("organizations", "call_lines_applied_at")
    op.drop_column("organizations", "call_lines_applied")
