"""A campaign's opening test records when it began (25 Nov 2026)

Revision ID: b8d4f0a2e3c5
Revises: a7c3e9f1d2b4
Create Date: 2026-11-25 10:10:00.000000

`campaigns.opening_test_started_at`: set when a new second opening is saved, and only calls
placed since count toward the test (`campaigns/learning.opening_results`). A contact's
`opening_variant` is fixed by its id, so a new test after a finished one would otherwise count
the earlier test's calls under the same labels. Recording the start rather than clearing the
labels keeps each contact row as the dialler wrote it.

NULL on every existing row: a test begun before this column counts every call, as it did.
NO NEW TABLE, SO NO NEW POLICY. Reversible: `downgrade()` drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f0a2e3c5"
down_revision: str | None = "a7c3e9f1d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "campaigns",
        sa.Column("opening_test_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("campaigns", "opening_test_started_at")
