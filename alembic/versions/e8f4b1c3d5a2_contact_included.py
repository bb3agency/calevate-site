"""Per-person "include in this campaign" switch (founder, 16 Nov 2026)

Revision ID: e8f4b1c3d5a2
Revises: e2a7c9d4b6f1
Create Date: 2026-11-16 18:00:00.000000

`campaign_contacts.included`: only people switched on are dialled. Everyone already on a
campaign stays on (default true). `campaign_contacts` already carries FORCEd RLS on
`tenant_id`, so the column inherits it. Additive; `downgrade()` drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f4b1c3d5a2"
down_revision: str | None = "e2a7c9d4b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_contacts",
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("campaign_contacts", "included")
