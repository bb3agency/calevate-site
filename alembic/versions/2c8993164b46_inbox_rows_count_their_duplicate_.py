"""inbox rows count their duplicate arrivals

Revision ID: 2c8993164b46
Revises: efb47868ec59
Create Date: 2026-08-11 02:05:00.000000

The webhook activity view (SURFACES §2b integration DX) shows each inbound delivery as
accepted / deduplicated / rejected. "Deduplicated" was previously invisible: a retry
hit the (provider, event_key) conflict, returned `duplicate`, and left no trace — so a
client whose form vendor retried fifteen times saw one quiet row and concluded events
were vanishing. The counter makes the retries a fact on the row instead of a shrug.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c8993164b46"
down_revision: str | None = "efb47868ec59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhook_inbox_events",
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("webhook_inbox_events", "duplicate_count")
