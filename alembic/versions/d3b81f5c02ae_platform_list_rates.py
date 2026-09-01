"""platform_list_rates — the self-serve list price, effective-dated and append-only

Revision ID: d3b81f5c02ae
Revises: a7f4c31d95e8
Create Date: 2026-09-01 00:00:00.000000

D-492. `Settings.self_serve_inr_per_min` is ONE number with no history: `platform_settings`
is keyed by `key` and an operator's change OVERWRITES the row. So every reader of it
answered "what does a minute cost" with today's answer, including the two readers whose
question was "what did a minute cost in the month I am rendering":

* `billing/service.py::calling_revenue_inr` priced a CLOSED month's minutes at the live
  setting, so a prepaid client's paid-and-settled statement (and the admin margin panel
  beside it) was re-priced by every later rate move — 14.83 min printed ₹88.98 and then
  ₹133.47 once the rate went 6 -> 9, for a month already debited off the wallet at ₹6;
* `workers/pipeline.py` debited a LATE-SETTLING call at the live setting while the
  `llm_surcharge` in the same expression was already resolved at `month_pricing_instant`
  (the fix at `pipeline.py` covered only the `plans` read). A call that settles after the
  IST month rolls — the reconciliation poller's window, or an ARQ retry ladder crossing
  midnight on the 1st — was charged at NEXT month's price.

This table is where that number acquires a valid time, so a month can be re-rendered at
the terms that were in force rather than at the terms in force now.

## The shape is `platform_model_prices`', deliberately, not a second mechanism

Same family, same resolution rule, same trigger pair: PK `(rate_key, effective_from)`,
resolution is "the row for this key with the greatest `effective_from <= T`", a correction
is a NEW row. A list rate has no natural `effective_to` — the next row IS its end — which
is why this is the `platform_model_prices` shape and not `plans`' half-open valid-time
window (`billing/plans.py` argues that window at length; it exists there because a plan can
END without a successor, and a published price cannot).

`rate_key` is text and part of the PK for the reason `platform_model_prices.model` is: a
figure read back for a historical statement must resolve even for a key the current build
no longer carries. Today there is exactly one key, `self_serve_inr_per_min` — the name of
the `Settings` field it dates — and `billing/list_rates.py` is the only reader and writer.

## NUMERIC(12,4), matching `usage_events.unit_cost_paid`

Hard rule 7. The scale is `billing/rates.MONEY_Q`'s, which is the scale
`prepaid_billed_inr` already quantizes a wallet debit at, so a rate stored here and a debit
computed from it round in the same place. No float appears on this path.

## Not tenant-scoped

One published list price for the whole self-serve motion at an instant — a MANAGED client's
price is their `plans` row, not this — so there is no tenant whose row this could be and it
carries no `tenant_id`. Registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as
the written reason (the RLS sweep's rule 7a REQUIRES a `platform_*` table to appear there).

## Append-only, with the SHARED blanket trigger

It joins the hard-rule-4 family with `calevate_forbid_mutation`, not `platform_secrets`'
column-permitting variant: nothing here ever needs an in-place edit, and a price history
somebody can edit after a statement was rendered from it is not evidence of anything.
TRUNCATE is closed by the shared `calevate_forbid_truncate` (a2e9f31c605d), and BOTH
triggers are `ENABLE ALWAYS` so `SET session_replication_role = replica` cannot switch them
off — the standing requirement `check_ledger_immutability` verifies for every ledger.

## No config-version sentinel bump, deliberately

`platform_settings` bumps `platform_config_version` so every process re-reads its `Settings`
snapshot. This table is NOT a `Settings` field: nothing here flows through
`apply_platform_overrides`, and the reader queries the database at render time. It is
WRITTEN in the same transaction as the `platform_settings` row it dates
(`ops/config_routes.py`), and that write bumps the sentinel already.

## NO BACKFILL, AND THAT IS THE HONEST ANSWER (hard rule 11)

The table ships EMPTY. Nobody recorded when the self-serve price last moved, so there is no
history to write down; seeding a row dated at the beginning of time with today's figure
would assert that today's price was in force in every past month, which is a claim nobody
here can make. `billing/list_rates.self_serve_rate_at` therefore falls back to
`Settings.self_serve_inr_per_min` when no row covers the instant asked about — the current
rate is genuinely the only rate we know for those months — and says so at the call site.
History accrues from the first ops-console price change after this lands.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched and the two trigger FUNCTIONS already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, which destroys the recorded rate history; every reader then
falls back to the live setting, which is exactly the defect this migration exists for. It
is reversible in the schema sense (the chain re-runs cleanly), not in the evidential one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3b81f5c02ae"
down_revision: str | None = "a7f4c31d95e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_list_rates",
        # WHICH published rate this row dates. The name of the `Settings` field it mirrors,
        # so the two cannot be related by guesswork; text and not an enum so a rate read
        # back for a historical statement resolves for a key this build no longer carries.
        sa.Column("rate_key", sa.Text(), nullable=False),
        # The instant this figure becomes the published rate. Part of the PK, so a
        # correction is a DISTINCT instant rather than a silent second row.
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # INR, at `billing/rates.MONEY_Q`'s scale — the storage precision of
        # `usage_events.unit_cost_paid`, so a rate and a debit derived from it round in one
        # place. NUMERIC, never a float (hard rule 7).
        sa.Column("inr_amount", sa.Numeric(12, 4), nullable=False),
        # The operator whose console write published it — every row here was typed by a
        # person, so NOT NULL, referencing `admin_users` exactly as
        # `platform_model_prices.attested_by` and `platform_settings.updated_by` do.
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # WHY the price moved, in the operator's words — the `reason` they already have to
        # give the ops console to change the setting. Required: a rate change with no
        # stated ground is the one a future reader cannot audit.
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_list_rates_recorded_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "rate_key", "effective_from", name=op.f("pk_platform_list_rates")
        ),
        # STRICTLY POSITIVE, at the database and not only at the API, for the reason
        # `ck_platform_model_prices_positive` gives: a NUMERIC column is reachable by any
        # writer holding the untenanted role, and a published rate of ₹0 prices every
        # self-serve minute at nothing while looking exactly like a working motion. The
        # `Settings` field carries the same exclusive floor (`gt=0`), so this refuses
        # nothing the console would have accepted.
        sa.CheckConstraint("inr_amount > 0", name=op.f("ck_platform_list_rates_positive")),
    )
    # The resolution query — "this key's rate with the greatest effective_from at or before
    # instant T" — walks this index rather than scanning the key's history.
    op.create_index(
        "ix_platform_list_rates_key",
        "platform_list_rates",
        ["rate_key", sa.text("effective_from DESC")],
    )

    # Append-only, blanket trigger (05bba2f3c19c): every column immutable, every UPDATE and
    # DELETE refused. No rewrap exception — this table never needs one.
    op.execute(
        "CREATE TRIGGER platform_list_rates_append_only "
        "BEFORE UPDATE OR DELETE ON platform_list_rates "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    # TRUNCATE is statement-level and a row trigger never sees it (a2e9f31c605d).
    op.execute(
        "CREATE TRIGGER platform_list_rates_forbid_truncate "
        "BEFORE TRUNCATE ON platform_list_rates "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ENABLE ALWAYS on both, so `SET session_replication_role = replica` cannot switch the
    # immutability off with no DDL and no schema diff.
    op.execute(
        "ALTER TABLE platform_list_rates ENABLE ALWAYS TRIGGER platform_list_rates_append_only"
    )
    op.execute(
        "ALTER TABLE platform_list_rates "
        "ENABLE ALWAYS TRIGGER platform_list_rates_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_list_rates_forbid_truncate ON platform_list_rates"
    )
    op.execute("DROP TRIGGER IF EXISTS platform_list_rates_append_only ON platform_list_rates")
    op.drop_index("ix_platform_list_rates_key", table_name="platform_list_rates")
    op.drop_table("platform_list_rates")
