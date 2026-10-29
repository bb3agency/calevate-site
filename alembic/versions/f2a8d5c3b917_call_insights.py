"""calls: the engine's call insights, redacted (D-940)

Revision ID: f2a8d5c3b917
Revises: e4b7c2a9d610
Create Date: 2026-10-30 10:30:00.000000

`calls.insights`: what the call came to as the voice platform read it once after the call
(`calevate_shared.events.CallInsights`, dumped): how it ended, the objections and issues the
customer named, why a no was a no, and the next step. The objection, issue and next-step
texts are the customer's words and are stored redacted. NULL when the platform did not read
the call. A CHECK keeps it an object holding an `outcome`.

A column on `calls` rather than a table of its own: one reading per call, written beside
`summary` and `next_step` by the same statement, and expired and erased by the statements
that already clear those (`workers/retention`), under the row-level security `calls` already
carries. A table would need its own policy and its own arm in every one of those paths.

ADD COLUMN without a default is a catalog change; the CHECK is added NOT VALID and then
validated under `lock_timeout`. Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a8d5c3b917"
down_revision: str | None = "e4b7c2a9d610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_calls_insights_shape"
_SHAPE = "insights IS NULL OR (jsonb_typeof(insights) = 'object' AND insights ? 'outcome')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls", sa.Column("insights", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.execute(f"ALTER TABLE calls ADD CONSTRAINT {CHECK} CHECK ({_SHAPE}) NOT VALID")
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT {CHECK}")
    op.drop_column("calls", "insights")
