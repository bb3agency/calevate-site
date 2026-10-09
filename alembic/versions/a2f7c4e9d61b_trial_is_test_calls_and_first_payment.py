"""A free trial is outbound test calls; the first payment unlocks the account (D-697)

Revision ID: a2f7c4e9d61b
Revises: c5e9a2d71b48
Create Date: 2026-10-09 20:00:00.000000

1. `tenant_trials.free_minutes`: the test-call minutes an operator gives a trial, beside its
   days. NULL on a trial opened before D-697, which has no minutes cap.
2. `calls.trial_call`: a free-trial test call, placed from the shared trial number. A
   partial index on `(tenant_id, created_at) WHERE trial_call` serves the daily cap, the
   minutes count and the line count.
3. `organizations.first_paid_at` / `first_paid_via`: when, and how, the account first paid.
   Written once by `billing/first_payment.record_first_payment`. A CHECK keeps the two
   together and the source in its vocabulary.
4. `trial_lines_in_use(horizon)`: how many trial test calls are live platform-wide. Every
   trial call rings from ONE shared number, and a number is lent to one agent at a time
   (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/phone-numbers/
   update-phone-number.md:144-145`), so a trial call holds the line until it ends. SECURITY
   INVOKER, one statement per tenant, restoring the entry `app.tenant_id`: the construction
   `carrier_lines_in_use` (a6d3b9f52e18) uses, for its reason (`calls` is FORCE-RLS'd).
   Unlike that function it reads the tenant list with `app.tenant_id` cleared: the trial
   dial asks from inside a tenant session, where `engine_agent_routes` shows only the
   caller's own rows (its read arm is `app.tenant_id IS NULL`).

BACKFILL. Every account that has a top-up on its ledger is marked paid from its first one
(`wallet_topup` for a gateway payment, `manual_topup` otherwise). Every other account that
already has a voice workspace row or a trial row is marked `before_d697`: it was set up
under the earlier rules (a workspace at creation, D-693; a trial with full calling, D-536),
and this migration does not take away what it already has. Run inside the `NO FORCE` /
`FORCE` bracket `a4f7d20c81be` documents, one statement per table.

DOWNGRADE drops the function, the index and the five columns. It loses each account's first
payment instant (recomputable from `credit_ledger` for top-ups), each trial's minutes and
which calls were trial calls.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2f7c4e9d61b"
down_revision: str | None = "c5e9a2d71b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "trial_lines_in_use"

_FIRST_PAID_VIA = "'wallet_topup', 'manual_topup', 'before_d697'"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(horizon interval)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    tenants uuid[];
    t uuid;
    in_use integer := 0;
    here integer;
BEGIN
    -- The tenant list is read UNTENANTED: inside a tenant session `engine_agent_routes`
    -- shows only that tenant's rows (its read arm is `app.tenant_id IS NULL`), and a trial
    -- call must see every other trial account's live call.
    PERFORM set_config('app.tenant_id', '', true);
    SELECT coalesce(array_agg(DISTINCT r.tenant_id ORDER BY r.tenant_id), '{{}}')
      INTO tenants FROM engine_agent_routes r;
    FOREACH t IN ARRAY tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT count(*) INTO here
          FROM calls c
         WHERE c.tenant_id = t
           AND c.trial_call
           AND c.status IN ('queued', 'ringing', 'in_progress')
           AND c.created_at > now() - horizon;
        in_use := in_use + here;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
    RETURN in_use;
END;
$$
"""

_BACKFILL_TOPUPS = """
UPDATE organizations o
   SET first_paid_at = t.paid_at,
       first_paid_via = CASE WHEN t.source = 'razorpay' THEN 'wallet_topup'
                             ELSE 'manual_topup' END
  FROM (
        SELECT DISTINCT ON (tenant_id) tenant_id, created_at AS paid_at,
               meta ->> 'source' AS source
          FROM credit_ledger
         WHERE reason = 'topup' AND delta > 0
         ORDER BY tenant_id, created_at, id
       ) t
 WHERE o.id = t.tenant_id AND o.first_paid_at IS NULL
"""

_BACKFILL_EARLIER_RULES = """
UPDATE organizations o
   SET first_paid_at = now(), first_paid_via = 'before_d697'
 WHERE o.first_paid_at IS NULL
   AND (EXISTS (SELECT 1 FROM tenant_engine_workspaces w WHERE w.tenant_id = o.id)
        OR EXISTS (SELECT 1 FROM tenant_trials tt WHERE tt.tenant_id = o.id))
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("tenant_trials", sa.Column("free_minutes", sa.Integer(), nullable=True))
    op.execute(
        "ALTER TABLE tenant_trials ADD CONSTRAINT ck_tenant_trials_free_minutes_range "
        "CHECK (free_minutes IS NULL OR (free_minutes >= 1 AND free_minutes <= 1000))"
    )
    op.add_column(
        "calls",
        sa.Column("trial_call", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_calls_trial_recent",
        "calls",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("trial_call"),
    )
    op.add_column(
        "organizations",
        sa.Column("first_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("first_paid_via", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT ck_organizations_first_paid_via_enum "
        f"CHECK (first_paid_via IS NULL OR first_paid_via IN ({_FIRST_PAID_VIA}))"
    )
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT ck_organizations_first_paid_together "
        "CHECK ((first_paid_at IS NULL) = (first_paid_via IS NULL))"
    )
    op.execute(_FUNCTION_SQL)

    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_ledger NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_engine_workspaces NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_trials NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_BACKFILL_TOPUPS)
        op.execute(_BACKFILL_EARLIER_RULES)
    finally:
        op.execute("ALTER TABLE tenant_trials FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE tenant_engine_workspaces FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(interval)")
    op.execute("ALTER TABLE organizations DROP CONSTRAINT ck_organizations_first_paid_together")
    op.execute("ALTER TABLE organizations DROP CONSTRAINT ck_organizations_first_paid_via_enum")
    op.drop_column("organizations", "first_paid_via")
    op.drop_column("organizations", "first_paid_at")
    op.drop_index("ix_calls_trial_recent", table_name="calls")
    op.drop_column("calls", "trial_call")
    op.execute("ALTER TABLE tenant_trials DROP CONSTRAINT ck_tenant_trials_free_minutes_range")
    op.drop_column("tenant_trials", "free_minutes")
