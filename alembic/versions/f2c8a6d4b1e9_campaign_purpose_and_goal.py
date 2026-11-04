"""campaigns: purpose and goal; calls: whether the call reached the campaign's goal

Revision ID: f2c8a6d4b1e9
Revises: b7e3d9a2c5f1
Create Date: 2026-11-04 12:00:00.000000

Three nullable columns:

* `campaigns.purpose` — why the campaign calls these people, in the business's words, at most
  90 characters on one line.
* `campaigns.goal` — what a good call ends with, at most 50 characters on one line. With the
  purpose it rides every dial as the call's reason, which the engine cuts at 150 characters
  (`apps/api/campaigns/brief.py`), so the two limits are set to fit it uncut.
* `calls.goal_reached` — `yes` / `no` / `unclear`, the post-call reading's verdict on a call
  placed for a campaign with a goal; NULL when there was no goal or no reading.

`campaigns` and `calls` already carry FORCEd row-level security on `tenant_id`; columns add
no policy. No backfill: an existing campaign has no purpose or goal, and its calls were never
judged. The CHECKs are added NOT VALID then validated, under `lock_timeout`. Downgrade drops
the constraints and the columns, losing what was typed and the verdicts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c8a6d4b1e9"
down_revision: str | None = "b7e3d9a2c5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "campaigns",
        "ck_campaigns_purpose_line",
        "purpose IS NULL OR (char_length(purpose) BETWEEN 3 AND 90 "
        "AND purpose = btrim(purpose) AND purpose !~ '[\\r\\n]')",
    ),
    (
        "campaigns",
        "ck_campaigns_goal_line",
        "goal IS NULL OR (char_length(goal) BETWEEN 3 AND 50 "
        "AND goal = btrim(goal) AND goal !~ '[\\r\\n]')",
    ),
    (
        "calls",
        "ck_calls_goal_reached_enum",
        "goal_reached IS NULL OR goal_reached IN ('yes', 'no', 'unclear')",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("goal", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("goal_reached", sa.String(), nullable=True))
    for table, name, check in _CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check}) NOT VALID")
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, name, _check in reversed(_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.drop_column("calls", "goal_reached")
    op.drop_column("campaigns", "goal")
    op.drop_column("campaigns", "purpose")
