"""owner daily summary switch; call_speed_scan() for the fleet's weekly reply speed (D-944)

Revision ID: f7b3e9a1c254
Revises: d941a2c7e5b3
Create Date: 2026-10-30 12:00:00.000000

* `organizations.owner_digest_enabled`: the owner's opt-in to a once-a-day summary by email
  and, where their WhatsApp opt-in is on file, WhatsApp. False for every existing account:
  nobody is sent a new message they did not ask for.
* `organizations.owner_digest_sent_on`: the IST day the last summary was claimed for. The
  daily job claims the day with a compare-and-set before sending, so a retried or doubled
  tick never sends a second summary, and releases the claim when nothing was delivered.
* `call_speed_scan(since)`: every client's calls since `since`, one row each, with the
  call's language, status, length and answer-time median and p90 (whether it connected is
  decided in Python from `crm/performance.DIAL_ONLY_STATUSES`, its one definition). The
  `call_reply_scan` pattern (d3f8b2c6a417): a SECURITY INVOKER loop entering each tenant
  under its own `app.tenant_id`, called from an `admin_session()`, so no session holds a
  cross-tenant view. Rows rather than aggregates because percentiles do not merge across
  tenants. Answered share needs the calls that did not connect, which `call_reply_scan`
  (completed calls only) does not return, hence a second function rather than a changed one.

`organizations` already carries its policy; two columns add none. Both are catalog-only
changes (a constant default). Downgrade drops the function and both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b3e9a1c254"
down_revision: str | None = "d941a2c7e5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "call_speed_scan"

_SCAN_SQL = f"""
CREATE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    started_at timestamptz,
    language text,
    status text,
    duration_s integer,
    answer_median double precision,
    answer_p90 double precision,
    test_call boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, c.started_at,
                   COALESCE(c.summary_language, a.language_primary)::text,
                   c.status::text,
                   c.duration_s,
                   (c.engine_quality ->> 'answer_ms_median')::float8,
                   (c.engine_quality ->> 'answer_ms_p90')::float8,
                   (c.trial_call OR c.paid_test_call)
              FROM calls c
              LEFT JOIN agents a ON a.id = c.agent_id
             WHERE c.started_at >= since;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column(
            "owner_digest_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column("organizations", sa.Column("owner_digest_sent_on", sa.Date(), nullable=True))
    op.execute(_SCAN_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.drop_column("organizations", "owner_digest_sent_on")
    op.drop_column("organizations", "owner_digest_enabled")
