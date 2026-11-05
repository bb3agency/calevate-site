"""calls: who acts on the next step, and why the campaign goal verdict is what it is

Revision ID: a9d3f6c2b7e4
Revises: a7d3e9c1f570
Create Date: 2026-11-05 12:00:00.000000

Two nullable columns on `calls`:

* `next_step_by` — `business` / `caller` / `nobody`: who must act on `calls.next_step`, as
  the post-call reading judged it. "Needs you" is derived only from a step the business
  must take (`crm/outcomes.derive_outcome`). NULL for a call read before it was asked,
  which keeps the older reading that a written step is the business's.
* `goal_reason` — one English sentence, redacted, saying why `calls.goal_reached` is what it
  is. Prose about the conversation, so it lives and is erased on the transcript's clock
  beside `next_step` (`workers/retention`).

`calls` already carries FORCEd row-level security on `tenant_id`; columns add no policy. No
backfill: older calls were never asked either question. The CHECK is added NOT VALID then
validated, under `lock_timeout`. Downgrade drops the constraint and the columns, losing
those readings.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d3f6c2b7e4"
down_revision: str | None = "a7d3e9c1f570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_calls_next_step_by_enum"
_CHECK = "next_step_by IS NULL OR next_step_by IN ('business', 'caller', 'nobody')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("next_step_by", sa.String(), nullable=True))
    op.add_column("calls", sa.Column("goal_reason", sa.Text(), nullable=True))
    op.execute(f"ALTER TABLE calls ADD CONSTRAINT {_CHECK_NAME} CHECK ({_CHECK}) NOT VALID")
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {_CHECK_NAME}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.drop_column("calls", "goal_reason")
    op.drop_column("calls", "next_step_by")
