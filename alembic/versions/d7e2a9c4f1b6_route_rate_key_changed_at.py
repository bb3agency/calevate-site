"""when a vendor agent's rate key last changed

The meter bills a call on the voice the platform says spoke it only when the agent's voice
moved after the call began (D-987). It judged that from `engine_agent_routes.updated_at`,
which the drift, knowledge, facts and webhook sweeps also bump, so an ordinary call could be
re-keyed. `rate_key_changed_at` is set only where `engine_rate_key` takes a new value
(`billing/engine_minutes.record_engine_rate_key`). Nothing is backfilled: NULL means not known
to have changed, which the meter reads as not moved.

`engine_agent_routes` keeps its existing policies; a new column needs none.
Additive; `downgrade()` drops the column.

Revision ID: d7e2a9c4f1b6
Revises: c3a9f5e2b7d1
Create Date: 2026-11-19 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e2a9c4f1b6"
down_revision: str | None = "c3a9f5e2b7d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTES = "engine_agent_routes"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        _ROUTES, sa.Column("rate_key_changed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(_ROUTES, "rate_key_changed_at")
