"""fx_rate_observations — the pulled USD/INR rate, platform-wide, append-only

Revision ID: b6f21d9c4e07
Revises: a9d4e70c31b8
Create Date: 2026-08-27 00:00:00.000000

Every vendor on the cost side of this product bills in dollars and every figure it
records is rupees. The conversion has ONE home (`engine/bolna.py::_cost`) and until now
ONE input: `Settings.usd_inr_rate`, a number an operator typed and a restart applied.
This table is where the PUBLISHED rate lives — pulled every five minutes by
`apps/workers/fx_pull.py` from a named reference-rate source — so that a call's cost is
converted at what the rate actually was rather than at what somebody last remembered to
type. The configured value keeps its job as the FALLBACK, used when this table has
nothing fresh (`core/fx.MAX_QUOTE_AGE`).

## Append-only, and this one is not a formality

It joins the hard-rule-4 family (`db/registry.APPEND_ONLY_TABLES`) with the SHARED
blanket trigger `calevate_forbid_mutation`, plus the shared `calevate_forbid_truncate`,
both `ENABLE ALWAYS` so `SET session_replication_role = replica` cannot switch them off —
the standing requirement `check_ledger_immutability` verifies for every ledger.

The reason is `usage_events`: a ledger row carries `meta.fx_rate`, the rate the call was
costed at, and the only thing that makes that number checkable a year later is a history
of observations nobody can edit. A mutable rate table would let today's correction
rewrite the input to a bill that was rendered and paid last quarter — which is not a
correction, it is a rewrite of the evidence. A wrong observation is superseded by a new
one; the old row stays, and `latest_observation`'s `ORDER BY as_of DESC, seq
DESC` is what makes the newer one win.

## Not tenant-scoped, and it must not be reachable through a tenant path

There is one exchange rate for the whole platform at an instant — no tenant whose row
this could be — so no `tenant_id` and no `tenant_isolation` policy, registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason (the RLS sweep's
rule 7a). Nothing tenant-facing reads this table: the conversion reads a value from
memory (`core/fx.py`), the console reads it through `platform:config` in the admin realm,
and no client-realm route names it. A decorative `tenant_id` was rejected for
`platform_settings`' reason — it would make the table LOOK tenant-scoped to every
column-driven sweep and invite a policy that lets one client's session see it.

## Why the RATE is inside the idempotency key

`observation_key` is `source|base|quote|as_of|rate` and UNIQUE. Without the rate the key
would be "one row per source per publication date", and a provider that CORRECTS a rate
it has already published for that date — which reference-rate administrators do — would
be silently swallowed as a duplicate. The correction is the one observation that must
never be lost. With the rate in the key, a five-minute poll of a once-a-day publication
still inserts exactly once (287 no-ops), and a correction is a second row that wins on
`seq`.

## The CHECK constraints

`rate > 0` is the floor `Settings.usd_inr_rate`'s field bound already carries for its
stated reason — a zero makes every vendor minute free and nobody notices until the month
closes — and the upper bound is the same two-orders-of-magnitude band. They are enforced
at the DATABASE as well as in `ops/fx_rates._check_plausible` because a NUMERIC column is
reachable by any writer holding the untenanted role, and the application guard is the one
that can be bypassed by psql at 3am. `base_currency <> quote_currency` refuses the
identity row: a stored `USD/USD = 1` would satisfy every reader and convert every dollar
to one rupee.

## No config-version sentinel trigger, deliberately

`platform_settings` bumps `platform_config_version` so every process re-reads its
`Settings` snapshot. This table is NOT a `Settings` field — nothing here flows through
`apply_platform_overrides` — and it is written every five minutes, so bumping the
sentinel would force a fleet-wide re-read of 50 config rows 288 times a day for a change
no `Settings` snapshot reflects. `ops/fx_rates.start_fx_refresher` polls this table
directly on its own interval instead.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing
existing is touched.

**Downgrade** drops the table. What is lost is the observation history — the evidence
behind `usage_events.meta.fx_rate` on rows already written. The ledger rows themselves
are untouched and still carry the rate they used, so no bill becomes unexplainable; what
becomes unavailable is the second copy that proves where that rate came from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6f21d9c4e07"
down_revision: str | None = "a9d4e70c31b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "fx_rate_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # THE ORDER WE LEARNED THINGS, and it is not `observed_at`. Two observations can
        # share a publication date — a provider CORRECTS a rate it already published — and
        # `observed_at` defaults to `now()`, which in Postgres is TRANSACTION start time,
        # so two rows written in one transaction carry the same instant and
        # `ORDER BY observed_at DESC` picks between them arbitrarily. Then the correction
        # loses to the figure it corrects at random, which is a wrong rate reaching money
        # through a tie nobody would think to look for. An identity column is monotonic by
        # construction and needs no clock at all. (`clock_timestamp()` was the alternative;
        # it narrows the window to microseconds rather than closing it, and this table's
        # whole job is to be the thing a disputed number is resolved against.)
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        # The PAIR, as columns. A direction that is only implied by the module a reader
        # happens to be in is the assumption `CostBreakdown.currency_stated` exists to
        # stop being made twice.
        sa.Column("base_currency", sa.Text(), nullable=False),
        sa.Column("quote_currency", sa.Text(), nullable=False),
        # Units of quote per ONE unit of base. NUMERIC(12,6), never a float (hard rule 7):
        # a reference rate is quoted to four decimals and the two spare digits cost
        # nothing, while a float would make the stored number differ from the published
        # one in exactly the digits an auditor compares.
        sa.Column("rate", sa.Numeric(12, 6), nullable=False),
        # The date the SOURCE stamped. Not the fetch instant — see `observed_at`.
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("observation_key", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rate_observations")),
        sa.UniqueConstraint("observation_key", name=op.f("uq_fx_rate_observations_key")),
        sa.CheckConstraint(
            "rate > 0 AND rate <= 1000", name=op.f("ck_fx_rate_observations_plausible")
        ),
        sa.CheckConstraint(
            "base_currency <> quote_currency", name=op.f("ck_fx_rate_observations_pair")
        ),
    )
    # The one query the read path runs — "the newest publication for this pair" — walks
    # this index rather than scanning a table that gains up to 288 rows a day.
    op.create_index(
        "ix_fx_rate_observations_pair",
        "fx_rate_observations",
        ["base_currency", "quote_currency", sa.text("as_of DESC"), sa.text("seq DESC")],
    )

    op.execute(
        "CREATE TRIGGER fx_rate_observations_append_only "
        "BEFORE UPDATE OR DELETE ON fx_rate_observations "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER fx_rate_observations_forbid_truncate "
        "BEFORE TRUNCATE ON fx_rate_observations "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE fx_rate_observations "
        "ENABLE ALWAYS TRIGGER fx_rate_observations_append_only"
    )
    op.execute(
        "ALTER TABLE fx_rate_observations "
        "ENABLE ALWAYS TRIGGER fx_rate_observations_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS fx_rate_observations_forbid_truncate ON fx_rate_observations"
    )
    op.execute("DROP TRIGGER IF EXISTS fx_rate_observations_append_only ON fx_rate_observations")
    op.drop_index("ix_fx_rate_observations_pair", table_name="fx_rate_observations")
    op.drop_table("fx_rate_observations")
