"""The campaign script as it was before Pip last rewrote it (founder, 17 Nov 2026)

Revision ID: b2d7f4a9c6e1
Revises: a9c4e2f7b1d3
Create Date: 2026-11-17 14:00:00.000000

`campaigns.script_before_pip` / `script_before_pip_at`: a copy of the saved script taken each
time Pip is asked to write or rewrite it, so the owner can switch back
(`campaigns/workspace.restore_before_pip`). `campaigns` already carries FORCEd RLS, so the
columns inherit it. Additive; `downgrade()` drops both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d7f4a9c6e1"
down_revision: str | None = "a9c4e2f7b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("script_before_pip", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "campaigns", sa.Column("script_before_pip_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("campaigns", "script_before_pip_at")
    op.drop_column("campaigns", "script_before_pip")
