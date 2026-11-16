"""The first run drafts the owner's first work, not an agent's script (Phase 3b, founder 16 Nov 2026)

Revision ID: e2a7c9d4b6f1
Revises: d8b2f5a7c3e1
Create Date: 2026-11-16 18:00:00.000000

"What first?" makes an inbound line or a campaign for the first agent, and Pip writes its
script. The run keeps which one it made, so a reload lands on the same draft and its test call
rings that draft's own engine agent:

* `first_runs.line_id`: the inbound line "Answer my calls" drafted;
* `first_runs.campaign_id`: the campaign "Call people" drafted.

Both nullable, `ON DELETE SET NULL` as `first_runs.agent_id` is. `first_runs` already carries
FORCEd RLS; adding columns changes no policy. `downgrade()` drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2a7c9d4b6f1"
down_revision: str | None = "d8b2f5a7c3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "first_runs"


def upgrade() -> None:
    op.add_column(
        RUNS,
        sa.Column(
            "line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inbound_lines.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        RUNS,
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(RUNS, "campaign_id")
    op.drop_column(RUNS, "line_id")
