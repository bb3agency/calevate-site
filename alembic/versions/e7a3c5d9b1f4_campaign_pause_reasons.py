"""campaigns: why an automatic pause happened, and the complaint review (D-773)

Revision ID: e7a3c5d9b1f4
Revises: d3f8b2c6a417
Create Date: 2026-10-14 18:00:00.000000

Two nullable columns on `campaigns`:

* `auto_pause_reason` names the automatic pauses that have no marker of their own:
  `complaint_spike`, `out_of_credit`, `spend_cap`. Maintenance and the healer already
  record theirs (`paused_by_maintenance_id`, `paused_by_heal_id`). NULL is a pause a
  person made, or no pause.
* `complaint_reviewed_at` is when the client confirmed they reviewed the opt-outs behind a
  complaint-spike pause. Resume is refused until it is set, and the spike window restarts
  from it.

`campaigns` already carries FORCEd row-level security on `tenant_id`; columns add no
policy. No backfill: every existing pause reads as a person's pause. The CHECK is added
NOT VALID then validated, under `lock_timeout`. Downgrade drops the constraint and both
columns, losing only the reason of current pauses and pending review confirmations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3c5d9b1f4"
down_revision: str | None = "d3f8b2c6a417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_CHECK = "ck_campaigns_auto_pause_reason_enum"
_REASONS = "('complaint_spike', 'out_of_credit', 'spend_cap')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("auto_pause_reason", sa.String(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column("complaint_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        f"ALTER TABLE campaigns ADD CONSTRAINT {_CHECK} CHECK "
        f"(auto_pause_reason IS NULL OR auto_pause_reason IN {_REASONS}) NOT VALID"
    )
    op.execute(f"ALTER TABLE campaigns VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("campaigns", "complaint_reviewed_at")
    op.drop_column("campaigns", "auto_pause_reason")
