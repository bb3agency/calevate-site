"""Pip writes the company training in the background and keeps the owner's edits (D-1034)

Revision ID: a7e3c9d2f5b1
Revises: d4b9e2a7c3f1
Create Date: 2026-11-23 12:00:00.000000

Three columns on `company_trainings` (already tenant data with FORCEd RLS):

* `pip_training`: the text Pip last saved. The live `training` differing from it is the
  owner's hand edits, which the next rewrite must carry.
* `owner_edits`: the owner's edits carried so far (`{"said": [...], "removed": [...]}`), so
  a fact the owner added stays theirs through every later rewrite, and a sentence they took
  out is not put back.
* `last_write`: when Pip last wrote the training and why, shown under How they speak.

All additive and nullable; `downgrade()` drops the three columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7e3c9d2f5b1"
down_revision: str | None = "d4b9e2a7c3f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "company_trainings"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("pip_training", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("owner_edits", postgresql.JSONB(), nullable=True))
    op.add_column(TABLE, sa.Column("last_write", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(TABLE, "last_write")
    op.drop_column(TABLE, "owner_edits")
    op.drop_column(TABLE, "pip_training")
