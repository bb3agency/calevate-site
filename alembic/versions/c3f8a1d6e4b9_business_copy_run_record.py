"""business copy records who asked for the copy in use and why the last run failed

Revision ID: c3f8a1d6e4b9
Revises: c4e8a2f6d1b3
Create Date: 2026-11-09 12:00:00.000000

The admin console's Business examples panel showed the copy's write time beside
`last_trigger`, which is the LAST run's trigger, so a copy a client paid for read as "an
operator asked" once an operator's refresh had failed. And a run refused by our checks said
only "did not pass our checks": which part failed, and on what rule, was in a log line.

- `generated_trigger`: who asked for the run that wrote the copy in use. NULL for existing
  rows, which is the truth: it was not recorded.
- `last_problems`: the last run's problems as `path: rule` strings, never the answer's text
  (hard rule 6), a JSON array or NULL.

Additive and nullable: code from before this revision never reads either column. Downgrade
drops both; the copies themselves are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3f8a1d6e4b9"
down_revision: str | None = "c4e8a2f6d1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "business_copies"
#: Spelled out rather than imported: a migration is a snapshot.
TRIGGERS = ("signup", "refresh", "scheduled", "operator", "first_run")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("generated_trigger", sa.Text(), nullable=True))
    op.add_column(
        TABLE, sa.Column("last_problems", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_generated_trigger_enum"),
        TABLE,
        f"generated_trigger IS NULL OR generated_trigger IN {TRIGGERS!r}",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_last_problems_is_array"),
        TABLE,
        "last_problems IS NULL OR jsonb_typeof(last_problems) = 'array'",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(f"ck_{TABLE}_last_problems_is_array"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_generated_trigger_enum"), TABLE, type_="check")
    op.drop_column(TABLE, "last_problems")
    op.drop_column(TABLE, "generated_trigger")
