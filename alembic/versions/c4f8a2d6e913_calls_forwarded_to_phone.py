"""a call a number forward put through to a phone is marked on its row (D-835)

Revision ID: c4f8a2d6e913
Revises: e3a7c1d9b524
Create Date: 2026-10-20 10:00:00.000000

ThinnestAI never records a forwarded call: no agent takes it, Get Call shows `recording`
null and Get Recording answers `404` (snapshots/2026-10-19/pages/channels/phone-numbers.md:
577-579). Without a mark on the row the missing-recording watch (`workers/recording_watch`)
counted every forward as a recording we failed to copy, re-fetched it each sweep and alarmed,
and the client's call page could not say why there is no recording.

`calls.forwarded_to_phone` is set from the engine's `forwardedTo` when the pipeline writes the
row, and is never cleared. `calls` keeps its RLS policy; a column adds no policy.

Downgrade drops the column; the engine's call record still names the forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f8a2d6e913"
down_revision: str | None = "e3a7c1d9b524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls",
        sa.Column(
            "forwarded_to_phone", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("calls", "forwarded_to_phone")
