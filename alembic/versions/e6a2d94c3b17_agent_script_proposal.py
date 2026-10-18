"""an agent's script proposal that Pip prepared, waiting on the Script page for review

Revision ID: e6a2d94c3b17
Revises: c8a3f5e19b62
Create Date: 2026-10-18 21:00:00.000000

D-820 (founder, 18 Oct 2026: Pip is the one AI assistant). `agents.script_proposal` holds the
one script change Pip prepared for an agent (`agents/script_proposals.py`): requested, being
drafted by the worker, ready for review, or failed with a note. The owner keeps it part by
part into the draft or discards it on the Script page; either way the column goes back to
NULL. A nullable addition to a table that already carries its RLS policy; no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6a2d94c3b17"
down_revision: str | None = "c8a3f5e19b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A brief exclusive lock on a hot table: fail fast rather than queue in front of writers.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agents", sa.Column("script_proposal", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("agents", "script_proposal")
