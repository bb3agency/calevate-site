"""outbox messages carry a consume deadline and the revision that queued them

Revision ID: f5a9c3e1d7b2
Revises: e3b8d1f6a924
Create Date: 2026-11-05 18:00:00.000000

Two nullable columns on `outbox_messages` (no tenant data, no policy: the table has none by
design, `db/registry`).

- `consume_by`: a published message whose run never succeeded used to be invisible, its
  payload already scrubbed (L5-03). The payload is now kept until the run succeeds, and a
  message past this deadline with no `consumed_at` is alarmed and re-published
  (`reliability/service.sweep_unconsumed_outbox`). Rows published before this revision keep
  NULL: their payload is gone, so there is nothing to re-publish.
- `min_revision`: a migration that queues work stamps its own revision, and only a
  dispatcher whose image contains that revision claims the row, so the old release still
  running between migrate and swap cannot run the new message with old code (L5-04).

Reversible: `downgrade()` drops the index and both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a9c3e1d7b2"
down_revision: str | None = "e3b8d1f6a924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("outbox_messages", sa.Column("consume_by", sa.DateTime(timezone=True)))
    op.add_column("outbox_messages", sa.Column("min_revision", sa.Text()))
    # The sweep's predicate exactly, so it reads the few live rows and never the 90 days of
    # consumed history the prune keeps.
    op.create_index(
        "ix_outbox_unconsumed",
        "outbox_messages",
        ["consume_by"],
        postgresql_where=sa.text(
            "status = 'published' AND consumed_at IS NULL AND consume_by IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_outbox_unconsumed", table_name="outbox_messages")
    op.drop_column("outbox_messages", "min_revision")
    op.drop_column("outbox_messages", "consume_by")
