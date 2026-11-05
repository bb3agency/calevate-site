"""business copy records the prompt version it was written under

Revision ID: b9d4e1a7c352
Revises: e8b3d6a1f427
Create Date: 2026-11-05 12:00:00.000000

Prompt version 4 of the business copy (D-827) adds each business's capability profile, which
the client screens and the agents' plans read. The version was only inside the opaque
`inputs_hash`, so a copy written under an older prompt was rewritten only when the 15-day
check next reached it. `prompt_version` lets the worker find every copy behind the current
prompt and re-judge it at once. Existing rows stay NULL, meaning "older than recorded".

Additive and nullable: code from before this revision never reads the column. Downgrade
drops it; the copies themselves are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9d4e1a7c352"
down_revision: str | None = "e8b3d6a1f427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "business_copies"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("prompt_version", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_prompt_version_positive"),
        TABLE,
        "prompt_version IS NULL OR prompt_version > 0",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(f"ck_{TABLE}_prompt_version_positive"), TABLE, type_="check")
    op.drop_column(TABLE, "prompt_version")
