"""platform_tts_volume: the fleet's monthly Studio minutes, as a counter

Revision ID: f7c2a94e18b3
Revises: e4a17c93d5b2
Create Date: 2026-09-09

**WHY A COUNTER AND NOT A QUERY (D-556).** Cartesia is billed as a monthly subscription
with an included allotment and an overage, so what a Studio minute COSTS us is a function
of how many the whole platform spoke that month. That figure is a cross-tenant sum of
`usage_events`, which FORCEs RLS: `admin_session` widens the policy on `organizations`
alone, so the sum is unanswerable in app code and reaching for the admin DB role to get it
would break hard rule 1.

The first build of this feature answered it by WALKING the client book — one tenant session
and two aggregates per account, the shape `billing/spend_routes.fleet_spend` already uses.
It is correct and it does not scale on a READ an ops console polls: measured on this
repository's own development database, **8,480 organizations**, the walk turned one
rate-card read into 8,480 session checkouts and stalled the test suite. A board an operator
opens deliberately can afford that shape; a screen that refreshes cannot.

So this is `platform_ai_spend`'s answer to the identical question, one vendor further down
the call. That table's own migration (`e1a7c93d5b02`) states the rule this one follows:
a platform-scoped counter, no `tenant_id`, no policy, moved in ONE statement by the meter
that writes the per-tenant rows, and **deliberately NOT in `APPEND_ONLY_TABLES`** — every
figure it holds is re-derivable from the `usage_events` rows that produced it, so an UPDATE
here is a counter incrementing rather than a ledger being rewritten.

**TWO INDEPENDENT COUNTS, NOT ONE FIGURE TIMES AN ASSUMPTION.** `characters` is what the
BYOK synthesizer actually spoke and `call_minutes` is what those calls actually billed.
Cartesia sells CREDITS, which are characters, so the plan is priced off the first and
divided by the second — and `TTS_ASSUMED_CHARS_PER_CALL_MINUTE` (360-540, unmeasured,
pilot gate 12) never enters the number an operator reads as today's cost. Deriving one from
the other would put the assumption back inside the measurement built to replace it.

**KEYED BY (month, provider)** even though `PLAN_BILLED_TTS_PROVIDERS` has one member
today. The month is the IST billing month, the same cut `billing/plans.ist_billing_month`
makes on the per-tenant rows, so this total and those totals close on one instant.

THE BACKFILL IS THE ONE THING A MIGRATION CAN DO THAT THE APPLICATION CANNOT: it runs as
the table OWNER, which is not subject to RLS, so the historical rows can be summed once
here. Without it every month already metered would read as zero — which on this screen
means "nobody has spoken a Studio minute", the flattering misreading the whole change
exists to remove.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7c2a94e18b3"
down_revision = "e4a17c93d5b2"
branch_labels = None
depends_on = None

TABLE = "platform_tts_volume"

#: The IST cut, spelled here as SQL because a migration cannot import the application.
#: `billing/plans.ist_billing_month` is the Python twin and `tests/cartesia_volume_test.py`
#: scores them against each other rather than trusting two spellings of one rule.
_IST_MONTH = "to_char(occurred_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM')"

#: Characters per unit of `usage_events.qty` on a `tts_kchars` row — `workers/pipeline
#: ._CHARS_PER_KCHAR` divides by it and every reader multiplies it back.
_CHARS_PER_KCHAR = "1000"

#: **`unit_type = 'tts_kchars'` IS THE PROVIDER DISCRIMINATOR, AND THERE IS NO OTHER.**
#: `workers/pipeline._tts_cost_row` writes it on the BYOK branch alone; a Sarvam call's
#: synthesizer cost is the engine's own reported leg figure on a `tts_chars` row at
#: `qty = 1`, carrying no character count at all. The MINUTES come from the `platform_min`
#: rows of the same calls, discriminated by the `voice_tier` the pipeline stamps on every
#: row of a call — counting them as `characters / 540` instead would put the unmeasured
#: speaking band back inside the measurement.
_BACKFILL = f"""
INSERT INTO {TABLE} (month, provider, characters, call_minutes, updated_at)
SELECT {_IST_MONTH} AS month,
       'cartesia' AS provider,
       COALESCE(SUM(qty) FILTER (WHERE unit_type = 'tts_kchars'), 0) * {_CHARS_PER_KCHAR},
       COALESCE(SUM(qty) FILTER (WHERE unit_type = 'platform_min'
                                   AND meta->>'voice_tier' = 'cartesia'), 0),
       now()
  FROM usage_events
 WHERE unit_type = 'tts_kchars'
    OR (unit_type = 'platform_min' AND meta->>'voice_tier' = 'cartesia')
 GROUP BY 1
HAVING COALESCE(SUM(qty) FILTER (WHERE unit_type = 'tts_kchars'), 0) > 0
    OR COALESCE(SUM(qty) FILTER (WHERE unit_type = 'platform_min'
                                   AND meta->>'voice_tier' = 'cartesia'), 0) > 0
ON CONFLICT (month, provider) DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        TABLE,
        # IST billing month, 'YYYY-MM'.
        sa.Column("month", sa.Text(), nullable=False),
        # The vendor's own name, so a second plan-billed vendor is a row and not a column.
        sa.Column("provider", sa.Text(), nullable=False),
        # Characters the fleet's agents spoke on this vendor's voices this month. NUMERIC
        # and not an integer because `usage_events.qty` is NUMERIC(14,4) and a kchar row
        # carries a fraction; rounding on the way in would lose characters we paid for.
        sa.Column("characters", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        # Call-minutes those same calls billed — an INDEPENDENT count, never derived.
        sa.Column("call_minutes", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("month", "provider", name=op.f(f"pk_{TABLE}")),
        # A volume that can go backwards is a cost figure that can be talked down by a bug,
        # in the direction that flatters us — the same reasoning
        # `ck_platform_ai_spend_non_negative` carries.
        sa.CheckConstraint(
            "characters >= 0 AND call_minutes >= 0", name=op.f(f"ck_{TABLE}_non_negative")
        ),
    )
    # NO RLS AND NO POLICY, deliberately: this table has no `tenant_id` and could not have
    # one — the allotment is bought once for the whole deployment. `db/registry
    # .RLS_EXEMPT_TENANT_COLUMNS` carries the written reason `check_rls_coverage` reads.
    op.execute(_BACKFILL)


def downgrade() -> None:
    # Nothing to preserve: every figure here is re-derivable from `usage_events`, which is
    # exactly why this is a counter and not a ledger. The upgrade's own backfill is the
    # recovery, and it is idempotent.
    op.drop_table(TABLE)
