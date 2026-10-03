"""A call records the carrier's id for its recording (D-668)

Revision ID: b3e9c4a71f20
Revises: e8b14d6a2c57
Create Date: 2026-10-03 00:00:00.000000

Vobiz records the call (founder, 3 Oct 2026) and reports the finished file by `RecordStop`
after the hangup (`vobiz-findings/mirror/pages/xml/record/stream-with-record.md:54-78`).
`calls.carrier_recording_id` is the carrier's opaque id for that recording. It is what the
copy job resolves to a download (`apps/workers/carrier_recordings.py`), what the overdue
alarm watches until our copy exists, and what an erasure quotes or deletes at the carrier
(`apps/workers/retention.py`). `calls.recording_url` stays OUR object key and nothing else.

Hard rule 6: the CHECK admits an id-shaped value only and refuses a bare digit run, the
rule `processor_erasure_tasks.vendor_refs` already enforces, so a phone number cannot be
stored here by mistake.

`ix_calls_recording_uncopied` serves the copy sweep: recordings reported and not yet copied,
which is a handful of rows at any moment.

Nullable, existing rows stay NULL. RLS is unchanged: `calls` already carries its FORCEd
tenant policy and no policy reads the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e9c4a71f20"
down_revision: str | None = "e8b14d6a2c57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_calls_carrier_recording_id_shape"
_INDEX = "ix_calls_recording_uncopied"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("carrier_recording_id", sa.Text(), nullable=True))
    op.execute(
        f"ALTER TABLE calls ADD CONSTRAINT {_CHECK} CHECK ("
        "carrier_recording_id IS NULL OR ("
        "carrier_recording_id ~ '^[A-Za-z0-9_-]{1,128}$' "
        "AND carrier_recording_id !~ '^[0-9]{7,}$')) NOT VALID"
    )
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {_CHECK}")
    op.execute(
        f"CREATE INDEX {_INDEX} ON calls (tenant_id, created_at) "
        "WHERE carrier_recording_id IS NOT NULL AND recording_url IS NULL"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("calls", "carrier_recording_id")
