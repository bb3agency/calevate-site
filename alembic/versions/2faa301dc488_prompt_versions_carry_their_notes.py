"""prompt versions carry their notes

Revision ID: 2faa301dc488
Revises: 2c8993164b46
Create Date: 2026-08-11 03:05:00.000000

The prompt rollback service needed somewhere to put "rollback to v3" and the
operator's one-line reason, and `prompt_versions` had no such column — the first
implementation parked notes in `compiled_t0_context`, which D-39 reserves for the
compiled T0 answer context. That parking spot is a collision waiting for the T0
compiler to ship and silently overwrite the audit trail of WHY each version exists.

`notes` is operator-facing metadata about the version; `compiled_t0_context` is a
build artifact OF the version. Different lifecycles, different columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2faa301dc488"
down_revision: str | None = "2c8993164b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("prompt_versions", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_versions", "notes")
