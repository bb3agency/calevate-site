"""Campaign Improve: one-press best hours, Pip's switch for them, the opening test's result

Revision ID: e5b9c3a7d1f4
Revises: e7c3a9f15b42
Create Date: 2026-11-24 18:00:00.000000

Three columns on `campaigns` (`campaigns/improve.py`):

* `best_hours_auto`: Pip may narrow the calling hours to the best block once enough is
  measured. Off by default, so nothing moves a campaign's hours until its owner says so.
* `best_hours_applied`: the block the calling hours were narrowed to, by whom, when, and
  the hours before, so the change can be undone. NULL when nothing is applied.
* `opening_test_result`: the opening test's decision (which opening won, the chance and the
  counts it was decided on, the opening it replaced). NULL while no test has been decided.

The smarter retry spacing needs no column: it is the `spread` key of `retry_policy`.

NO NEW TABLE, SO NO NEW POLICY: `campaigns` keeps its FORCEd `tenant_isolation`.
Reversible: `downgrade()` drops the CHECKs and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b9c3a7d1f4"
down_revision: str | None = "e7c3a9f15b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OBJECT_COLUMNS = ("best_hours_applied", "opening_test_result")


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("best_hours_auto", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column in _OBJECT_COLUMNS:
        op.add_column("campaigns", sa.Column(column, postgresql.JSONB()))
        op.create_check_constraint(
            op.f(f"ck_campaigns_{column}_object"),
            "campaigns",
            f"{column} IS NULL OR jsonb_typeof({column}) = 'object'",
        )


def downgrade() -> None:
    for column in reversed(_OBJECT_COLUMNS):
        op.drop_constraint(op.f(f"ck_campaigns_{column}_object"), "campaigns", type_="check")
        op.drop_column("campaigns", column)
    op.drop_column("campaigns", "best_hours_auto")
