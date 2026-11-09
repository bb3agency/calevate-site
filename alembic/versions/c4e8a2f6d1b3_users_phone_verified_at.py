"""A person's own mobile number can later be confirmed: users.phone_verified_at (D-976)

Revision ID: c4e8a2f6d1b3
Revises: e8b4c1d7a2f6
Create Date: 2026-11-09 12:00:00.000000

A signed-in person now adds or changes the mobile number on their own login with no code
(D-976). The confirmation step comes later, by a WhatsApp code from Calevate's own account.
This column is where that step will record its proof, so it can be added without a second
reshaping of `users`: it stays NULL for every typed number, and the write that changes a
number clears it.

Nullable with no default and no backfill: no number held today has been confirmed, and an
`ADD COLUMN` with no default is a catalogue-only change.

DOWNGRADE drops the column. Nothing reads it, so nothing is lost but NULLs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f6d1b3"
down_revision: str | None = "e8b4c1d7a2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "phone_verified_at")
