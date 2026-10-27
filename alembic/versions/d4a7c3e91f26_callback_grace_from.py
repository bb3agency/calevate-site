"""scheduled_callbacks: where a held call-back's two hours start (D-914)

Revision ID: d4a7c3e91f26
Revises: b7e2d5a9c813
Create Date: 2026-10-28 12:00:00.000000

While its campaign is paused a call-back is held, not dialled (D-914). When the campaign
resumes, the call-back is dialled at the next moment the platform's and the campaign's
calling hours allow, even if the time the caller asked for passed during the pause. The
two-hour grace (`callbacks.service.GRACE`) then has to count from that moment, not from the
promised time, or `expire_stale` would end every released call-back as missed on the tick
that released it. Nothing on the row records that moment, and `requested_at` is what the
caller was told and never moves, so this adds `grace_from`: NULL for every call-back that
was never held, which keeps today's behaviour for all existing rows without a backfill.

The table already carries FORCEd row-level security; a column adds no policy. ADD COLUMN
without a default is a catalog change, and `lock_timeout` bounds the wait. Downgrade drops
the column; a held call-back then falls back to its promised time, which is the rule before
D-914.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c3e91f26"
down_revision: str | None = "b7e2d5a9c813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "scheduled_callbacks", sa.Column("grace_from", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("scheduled_callbacks", "grace_from")
