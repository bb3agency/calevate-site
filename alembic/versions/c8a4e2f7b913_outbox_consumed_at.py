"""an outbox message records when a worker run of it succeeded

Revision ID: c8a4e2f7b913
Revises: b3e7c9a15d24
Create Date: 2026-10-26 11:00:00.000000

`dispatch_outbox` enqueues and then marks the row published; when that mark does not
commit, a later tick re-enqueues the message under the same job id, and arq's dedupe of
that id lasts only for the job's `keep_result` window (five minutes, or none for auth
email). `consumed_at` is written by the consumer once a run succeeds and checked before
the next run of the same message, so the side effect is not repeated however long the
re-publish took.

Nullable, no default, no backfill: a NULL means "no run recorded", which is what every
existing row would say. No RLS change — `outbox_messages` is platform machinery with no
`tenant_id` (`db/registry`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a4e2f7b913"
down_revision: str | None = "b3e7c9a15d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "outbox_messages", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("outbox_messages", "consumed_at")
