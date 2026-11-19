"""when a draft line's test holder was last published

A draft line's test call is rung through an engine agent of its own (D-1018, D-1020), retired
once it has sat unused for an hour (`workers/campaign_engine_agents.TEST_HOLDER_IDLE`). Its
route's `updated_at` cannot say when it was last used: the drift sweeps, the webhook check,
the business-facts publish and the rate-key refresh all rewrite it, so with a small fleet the
holder never aged out. `inbound_lines.engine_agent_at` is written only by a test-holder
publish, which every test call through the line makes first, as `campaigns.engine_agent_at`
is for a campaign.

The table already has its FORCEd tenant policy; a new column on it needs no new one.
Additive and nullable; `downgrade()` drops it.

Revision ID: d7e2a4c9f1b6
Revises: f1d6b3a8c2e4
Create Date: 2026-11-19 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e2a4c9f1b6"
down_revision: str | None = "f1d6b3a8c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "inbound_lines", sa.Column("engine_agent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("inbound_lines", "engine_agent_at")
