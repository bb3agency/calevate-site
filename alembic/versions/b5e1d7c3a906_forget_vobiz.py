"""Forget Vobiz (D-950): drop what only our own carrier leg wrote, and its name from a CHECK

Revision ID: b5e1d7c3a906
Revises: e7b3c9d1a4f2
Create Date: 2026-11-01 20:00:00.000000

The founder dropped Vobiz for good on 1 Nov 2026 (D-950). Its runtime went with the Pipecat
engine (D-763); these are the schema objects that only that path wrote or read, which D-763
left for the next release under hard rule 8's two-step.

DROPPED, because no live code reads or writes them:

* `carrier_lines_in_use(text, interval, interval)` (a6d3b9f52e18): the owned carrier's line
  count. Nothing calls it, and it reads `calls.carrier`, so it goes first: a plpgsql body is
  not dependency-tracked and would otherwise outlive the column it selects.
* `calls.carrier` (f5c2a8e41d07), with `ck_calls_carrier_enum` and `ix_calls_carrier_live`.
* `calls.recording_copied_at` and `calls.carrier_recording_deleted_at` (c5d82f1a9e47, D-670),
  with `ix_calls_carrier_recording_undeleted`: the copy and one-day-expiry sweeps of the
  carrier's recordings.
* `phone_numbers.carrier_binding_id` (d4a7b2c91e30, D-662): the carrier's attachment id.

NARROWED: `ck_phone_numbers_provider_carrier` no longer admits `vobiz`. A row still holding
it becomes NULL first, which is what the column already means for a number held by no
provider this platform dials through (`agents.service.carrier_of_provider`); no code compares
the column with `vobiz`. The UPDATE is bracketed in NO FORCE ... FORCE because the policy is
fail-closed for the owner on an unset tenant (c8f5d1b74a30's bracket, for its reason).

KEPT, because live code still reads them:

* `calls.carrier_call_id` and `calls.carrier_recording_id`: both erasures quote them on the
  `telephony` processor-erasure task for calls placed before D-763.
* `carrier_compliance_applications`, whose `carrier` CHECK still admits `vobiz`: the account
  closure sweep reads it to decide whether to list the carrier-document prefix
  (`workers/retention._HAS_CARRIER_DOCUMENT_SQL`), and its `carrier` is NOT NULL, so a
  `vobiz` row has no value to become.

REVERSIBILITY. `downgrade()` recreates every object with its old shape, constraint, index and
function body, and widens the CHECK back. The values are not restored: the dropped columns
come back NULL, and a provider that was `vobiz` stays NULL. Take a `pg_dump` before upgrading
an environment whose rows matter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e1d7c3a906"
down_revision: str | None = "e7b3c9d1a4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINES_FUNCTION = "carrier_lines_in_use"
_CALLS_CARRIER_CHECK = "ck_calls_carrier_enum"
_CALLS_CARRIER_INDEX = "ix_calls_carrier_live"
_RECORDING_UNDELETED_INDEX = "ix_calls_carrier_recording_undeleted"
_PROVIDER_CHECK = "ck_phone_numbers_provider_carrier"
_PROVIDER_NARROWED = "provider IS NULL OR provider IN ('plivo', 'thinnest')"
_PROVIDER_WIDENED = "provider IS NULL OR provider IN ('vobiz', 'plivo', 'thinnest')"

#: a6d3b9f52e18's body, frozen here so the downgrade recreates exactly what it dropped.
_LINES_FUNCTION_SQL = f"""
CREATE FUNCTION {_LINES_FUNCTION}(
    p_carrier text,
    live_horizon interval,
    ring_horizon interval
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    in_use integer := 0;
    here integer;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT count(*) INTO here
          FROM calls c
         WHERE c.tenant_id = t
           AND (c.carrier = p_carrier OR (c.carrier IS NULL AND c.direction = 'inbound'))
           AND (
                (c.status IN ('ringing', 'in_progress')
                 AND c.created_at > now() - live_horizon)
             OR (c.status = 'queued' AND c.created_at > now() - ring_horizon)
           );
        in_use := in_use + here;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
    RETURN in_use;
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {_LINES_FUNCTION}(text, interval, interval)")

    op.execute(f"DROP INDEX IF EXISTS {_CALLS_CARRIER_INDEX}")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {_CALLS_CARRIER_CHECK}")
    op.drop_column("calls", "carrier")
    op.execute(f"DROP INDEX IF EXISTS {_RECORDING_UNDELETED_INDEX}")
    op.drop_column("calls", "carrier_recording_deleted_at")
    op.drop_column("calls", "recording_copied_at")

    op.drop_column("phone_numbers", "carrier_binding_id")
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE phone_numbers SET provider = NULL WHERE provider = 'vobiz'")
    op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS {_PROVIDER_CHECK}")
    op.execute(f"ALTER TABLE phone_numbers ADD CONSTRAINT {_PROVIDER_CHECK} CHECK ({_PROVIDER_NARROWED})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS {_PROVIDER_CHECK}")
    op.execute(f"ALTER TABLE phone_numbers ADD CONSTRAINT {_PROVIDER_CHECK} CHECK ({_PROVIDER_WIDENED})")
    op.add_column("phone_numbers", sa.Column("carrier_binding_id", sa.Text(), nullable=True))

    op.add_column(
        "calls", sa.Column("recording_copied_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "calls",
        sa.Column("carrier_recording_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        f"CREATE INDEX {_RECORDING_UNDELETED_INDEX} ON calls (tenant_id, created_at) "
        "WHERE carrier_recording_id IS NOT NULL AND recording_url IS NOT NULL "
        "AND carrier_recording_deleted_at IS NULL"
    )
    op.add_column("calls", sa.Column("carrier", sa.Text(), nullable=True))
    op.execute(
        f"ALTER TABLE calls ADD CONSTRAINT {_CALLS_CARRIER_CHECK} "
        "CHECK (carrier IS NULL OR carrier IN ('vobiz', 'plivo'))"
    )
    op.execute(
        f"CREATE INDEX {_CALLS_CARRIER_INDEX} ON calls (tenant_id, carrier, created_at) "
        "WHERE status IN ('queued', 'ringing', 'in_progress')"
    )

    op.execute(_LINES_FUNCTION_SQL)
