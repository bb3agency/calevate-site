"""A call records the carrier it was placed or answered on (D-663)

Revision ID: f5c2a8e41d07
Revises: d4a7b2c91e30
Create Date: 2026-10-02 00:00:00.000000

`calls.carrier` is the carrier that holds this call's leg: `vobiz` or `plivo`
(`calevate_shared.carrier.CARRIERS`). Hanging a call up, reading its call record and
counting the lines it occupies all have to address the carrier that actually carries it,
and `Settings.carrier` is a live switch: reading the switch at hang-up time sends the
request to whichever carrier the switch names NOW, which is the wrong account for every
call placed before it moved.

Nullable, and existing rows stay NULL. A row written before this revision has no recorded
carrier and none is invented for it; readers fall back to the switch for those, which is
what every reader did before this column existed.

`ix_calls_carrier_live` serves `carrier_lines_in_use()` (next revision): a per-tenant count
of calls in a live status on one carrier (and inbound rows not yet stamped with one). Partial
over the three live statuses, so it holds only the handful of calls in flight.

RLS is unchanged: `calls` already carries its FORCEd tenant policy and no policy reads the
column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5c2a8e41d07"
down_revision: str | None = "d4a7b2c91e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_calls_carrier_enum"
_INDEX = "ix_calls_carrier_live"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("carrier", sa.Text(), nullable=True))
    # NOT VALID then VALIDATE: the column is new and all-NULL, so validation is a scan that
    # cannot fail, and it runs under SHARE UPDATE EXCLUSIVE rather than ACCESS EXCLUSIVE.
    op.execute(
        f"ALTER TABLE calls ADD CONSTRAINT {_CHECK} "
        "CHECK (carrier IS NULL OR carrier IN ('vobiz', 'plivo')) NOT VALID"
    )
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {_CHECK}")
    op.execute(
        f"CREATE INDEX {_INDEX} ON calls (tenant_id, carrier, created_at) "
        "WHERE status IN ('queued', 'ringing', 'in_progress')"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("calls", "carrier")
