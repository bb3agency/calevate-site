"""Vobiz beside Plivo: carrier applications may name it, and a number records its binding

Revision ID: d4a7b2c91e30
Revises: c5e8a1f47b92
Create Date: 2026-10-02 00:00:00.000000

D-662 makes the carrier a switch (`Settings.carrier`, `vobiz` | `plivo`). Two schema facts
follow, and both are additive.

1. `carrier_compliance_applications.carrier` admits `'vobiz'`. A tenant's approval is per
   carrier — the unique key is `(tenant_id, carrier)` — so a Vobiz application is a second
   row, never a rewrite of the Plivo one. `'plivo'` stays: rows exist under it and the
   switch can still select it. Dropping it is a later release's two-step (hard rule 8).
2. `phone_numbers.carrier_binding_id`: the carrier's id for what the number is attached to.
   On Vobiz that is the Application whose answer URL routes the number to an agent
   (`vobiz-findings/mirror/pages/applications/attach-number.md:9-60`). Nullable, because
   no number has been bound yet and none may be given an invented id.

3. Two indexes for the carrier callback and call-record jobs (`apps/workers/carrier_events.py`):
   `ix_calls_tenant_carrier_call_id`, the inbound lookup by the carrier's call id, and
   `ux_usage_events_carrier_cdr`, the database backstop for "one call record, one cost row"
   behind the job's own lock. Both are partial and match no row before this release, so
   they are built in place rather than CONCURRENTLY, as `c5e8a1f47b92` built its index.

RLS is unchanged: every table touched already carries FORCEd tenant policies and no policy
reads these columns.

LOCKING. The CHECK is dropped and re-created with a strict superset, so no row can fail
validation, but re-creating it takes ACCESS EXCLUSIVE and scans the table; `lock_timeout`
makes it fail fast rather than queue. Adding a nullable column with no default is a
catalogue-only change.

DOWNGRADE re-narrows the CHECK to `'plivo'` and drops the column. The CHECK half fails
loudly if a Vobiz application exists by then, which is correct: deleting a tenant's carrier
approval to make a constraint fit would lose a regulator-facing record.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7b2c91e30"
down_revision: str | None = "c5e8a1f47b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "carrier_compliance_applications"
_CHECK = "ck_carrier_compliance_applications_carrier_enum"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_CHECK}")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK} CHECK (carrier IN ('plivo', 'vobiz'))")
    op.add_column("phone_numbers", sa.Column("carrier_binding_id", sa.Text(), nullable=True))
    op.execute(
        "CREATE INDEX ix_calls_tenant_carrier_call_id ON calls (tenant_id, carrier_call_id) "
        "WHERE carrier_call_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_usage_events_carrier_cdr ON usage_events (tenant_id, call_id) "
        "WHERE call_id IS NOT NULL AND unit_type = 'other' "
        "AND meta->>'kind' = 'carrier_cdr'"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP INDEX IF EXISTS ux_usage_events_carrier_cdr")
    op.execute("DROP INDEX IF EXISTS ix_calls_tenant_carrier_call_id")
    op.drop_column("phone_numbers", "carrier_binding_id")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_CHECK}")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK} CHECK (carrier IN ('plivo'))")
