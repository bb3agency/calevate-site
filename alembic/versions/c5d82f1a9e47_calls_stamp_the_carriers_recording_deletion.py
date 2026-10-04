"""A call records when our recording copy landed and when the carrier's copy was deleted

Revision ID: c5d82f1a9e47
Revises: b3e9c4a71f20
Create Date: 2026-10-03 12:00:00.000000

Founder, 3 Oct 2026: Vobiz's copy of a call recording is deleted one day after ours is saved
(`apps/workers/carrier_recordings.expire_carrier_recording`).

* `calls.recording_copied_at` is when `copy_carrier_recording` stored our copy. The one-day
  clock starts here rather than at the hangup, so a copy that took a day of retries still
  leaves the carrier's copy in place for a day after ours exists. NULL on rows copied before
  this revision; the sweep falls back to `updated_at` for those.
* `calls.carrier_recording_deleted_at` is when the carrier confirmed the deletion (or
  answered that the recording was already gone). It is the sweep's "done" mark and what the
  48-hour overdue alarm watches.

`ix_calls_carrier_recording_undeleted` serves the sweep: copied recordings whose carrier copy
is not yet deleted, which is at most a day or two of calls at any moment.

Both nullable, no backfill. RLS is unchanged: `calls` already carries its FORCEd tenant
policy and no policy reads these columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d82f1a9e47"
down_revision: str | None = "b3e9c4a71f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_calls_carrier_recording_undeleted"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls", sa.Column("recording_copied_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "calls",
        sa.Column("carrier_recording_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        f"CREATE INDEX {_INDEX} ON calls (tenant_id, created_at) "
        "WHERE carrier_recording_id IS NOT NULL AND recording_url IS NOT NULL "
        "AND carrier_recording_deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.drop_column("calls", "carrier_recording_deleted_at")
    op.drop_column("calls", "recording_copied_at")
