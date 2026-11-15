"""A campaign overrides its agent's default settings; the agent holds only defaults (D-994)

Revision ID: a7e2c9f4d1b8
Revises: f3c8d1a6b2e4
Create Date: 2026-11-15 21:00:00.000000

* `campaigns.settings_overrides`: the agent settings this campaign sets for its own calls
  (language, speaking speed, longest call, silence handling, filler lines, background sound),
  each key present only when overridden.
* `campaigns.agent_held_at`: when this campaign last put its script on its agent (Start,
  Schedule, Test call). The campaign that holds an agent most recently is the one whose
  overrides that agent's published settings carry.

Additive. `downgrade()` drops both columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7e2c9f4d1b8"
down_revision: str | None = "f3c8d1a6b2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("settings_overrides", postgresql.JSONB(), nullable=True))
    op.add_column(
        "campaigns", sa.Column("agent_held_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("campaigns", "agent_held_at")
    op.drop_column("campaigns", "settings_overrides")
