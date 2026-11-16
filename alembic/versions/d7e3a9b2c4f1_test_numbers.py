"""Saved test numbers on the account (founder, 16 Nov 2026)

Revision ID: d7e3a9b2c4f1
Revises: c6a4f2e8d1b7
Create Date: 2026-11-16 14:00:00.000000

`organizations.test_numbers`: the E.164 numbers this account rings for test calls, offered
under every Test call form. `organizations` already carries FORCEd RLS on `id`, so the
column inherits it. Additive; `downgrade()` drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e3a9b2c4f1"
down_revision: str | None = "c6a4f2e8d1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "test_numbers",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "test_numbers")
