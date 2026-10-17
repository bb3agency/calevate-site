"""the developer workspace's call retention is recorded

Revision ID: c5f6e1202331
Revises: 61a3b8e4e312
Create Date: 2026-10-18 10:00:00.000000

D-809 (founder, 18 Oct 2026).

`platform_state`: what our developer workspace last confirmed from `GET /workspace`, written
by the hourly retention sweep (`workers/engine_retention`), the same three facts
`tenant_engine_workspaces` holds for a client workspace (D-798):

* `developer_retention_days` — its `callRetentionDays`, the day count after which the
  platform deletes a call's recording and transcript;
* `developer_retention_plan_days` — its `planRetentionDays`, the most the plan allows;
* `developer_retention_checked_at` — when that answer was read.

All NULL until the first sweep after deploy; `workers/recording_watch` then falls back to the
shortest plan window. RLS is unchanged: `platform_state` has none.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f6e1202331"
down_revision: str | None = "61a3b8e4e312"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_state"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_TABLE, sa.Column("developer_retention_days", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("developer_retention_plan_days", sa.Integer(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("developer_retention_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(_TABLE, "developer_retention_checked_at")
    op.drop_column(_TABLE, "developer_retention_plan_days")
    op.drop_column(_TABLE, "developer_retention_days")
