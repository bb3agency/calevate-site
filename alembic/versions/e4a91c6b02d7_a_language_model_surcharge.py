"""a language model surcharge

Revision ID: e4a91c6b02d7
Revises: b7d2f10c93ae
Create Date: 2026-08-22 11:40:00.000000

ONE nullable column on `plans`, in `overage_rate_value`'s exact shape and for the exactly
parallel reason (D-455).

--------------------------------------------------------------------------------
WHAT IT IS FOR
--------------------------------------------------------------------------------

`b7d2f10c93ae` (D-454) made the in-call language model a CLIENT's choice, resolved
`agents.llm_model` -> `organizations.default_llm_model` -> the platform's own. The two
allow-listed models are not close on cost: `gpt-4.1-mini` is 2.7x `gpt-4o-mini` on both
token legs (`calevate_shared.engine.AZURE_LIST_PRICE_USD_PER_MTOK`). Billing could not
express that at all — `plans` has no model column, and both client-price functions
(`rates.prepaid_billed_inr`, `service.priced_overage`) price MINUTES at the plan's rate
and take no model. So a client could move their whole account onto the dearer model and
their bill moved by exactly ₹0.00; the difference was margin we gave away, silently, on
a control we had just built for them.

**A SURCHARGE, NOT A SECOND RATE.** The plan's per-minute rate stays the base and this
ADDS to it for the minutes that ran on an upgraded model. That is what makes the column
safe to add to a live database: the base-rate model (`rates.BASE_RATE_LLM_MODEL`) is free
of charge by construction, and a NULL surcharge reproduces today's arithmetic on every
existing plan, to the paisa. Nothing is re-priced by this migration.

**NULL means "this plan quotes no model surcharge" — every upgraded minute is billed at
`overage_rate` exactly as it is today.** It is NOT "the surcharge is zero": a plan that
gives the better model away for nothing is a decision somebody made, and a plan that has
never been asked the question is not. Same distinction, same column shape and the same
refusal to invent a number as `overage_rate_value` — what goes in it is a FOUNDER
DECISION, and this migration owes the founder somewhere to put it, not the number.

**WHY A PLANS COLUMN AND NOT A LEDGER ROW.** An invoice here is a DERIVED statement
(`billing/invoice.py` persists nothing) and a month is priced by the plan row in effect at
`billing/plans.py::month_pricing_instant`. A surcharge appended to `usage_events` at
metering time would freeze the rate in force on the night of the call, so a re-rendered
statement would mix one month's minutes with two different surcharges — and correcting a
mis-set surcharge would take a compensating row per call rather than one dated plan row.
Effective dating already solves this exactly once on this table; a second mechanism beside
it would be the drift this repository refuses. The MODEL a call ran is still a ledger fact
and still stamped there (`usage_events.meta.llm_model` / `llm_model_source`, D-454) — what
the plan supplies is the PRICE of that fact, which is the same division of labour
`meta.tts_tier` and `overage_rate_value` already have.

--------------------------------------------------------------------------------
CONSTRAINT
--------------------------------------------------------------------------------

One CHECK, admitting NULL EXPLICITLY (`IS NULL OR ...`) rather than relying on a CHECK
that returns NULL passing — written so the sentinel reads as deliberate. Added NOT VALID
(a brief ACCESS EXCLUSIVE for the catalog row, no scan) and VALIDATEd separately under
SHARE UPDATE EXCLUSIVE, which blocks neither readers nor writers. Every pre-existing row
is NULL and satisfies it trivially; the scan is for the catalog's benefit, so the planner
and future ADD CONSTRAINT checks are not left stepping around a NOT VALID constraint.

**ZERO IS LEGAL AND NEGATIVE IS NOT.** A negative surcharge would be a DISCOUNT for
choosing the expensive model, which is not a price anybody means to quote — it is a typo
that would read as one, and it would let a model choice reduce a bill below the plan's own
rate. `ck_plans_overage_rate_value_nonnegative` makes the identical call one column over.

`lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE request cannot park in front
of every other session (hard rule 8).

**No backfill and no FORCE bracket.** Nothing is UPDATEd: the column is new and NULL is
the value that reproduces today's behaviour exactly.

**RLS.** No new table, so no new policy: `plans` already carries its FORCEd
`tenant_isolation` policy (05bba2f3c19c) and a column is not a separate security object.
Asserted rather than assumed — `tests/llm_model_surcharge_test.py` reads and writes this
column as a second tenant and requires zero rows.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the constraint and then the column, reverse order of creation. What is lost is what
only this column holds: a plan reverts to charging one price per minute whatever model
ran, which is the pre-migration price and therefore a LOOSENING on the money side — named
here rather than buried, because after a downgrade a client on the dearer model is billed
as if they were on the base one. The code that ran before this revision runs correctly
against the post-downgrade schema, which is the sense hard rule 8 means by reversible.
Nothing is two-step-deprecated because nothing is removed: the column is new.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a91c6b02d7"
down_revision: str | None = "b7d2f10c93ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "plans"
COLUMN = "llm_model_surcharge"
CK_SURCHARGE = "ck_plans_llm_model_surcharge_nonnegative"

# Mirrors nothing in Python on purpose — a migration is a snapshot of the schema on the
# day it ran, and importing today's constants would rewrite history the next time somebody
# widens the range (the rule `a4e7b2c95d18` and `b1d5c8e73f04` both state).
_SURCHARGE_SQL = f"{COLUMN} IS NULL OR {COLUMN} >= 0"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Nullable with no default: catalog-only since PG11, no rewrite, no scan.
    # NUMERIC(12,4) is the `MONEY` precision every rupee column on this table already
    # uses (billing/models.py) — a rate stored at a different precision than the rate
    # beside it is a rounding argument waiting to happen (hard rule 7).
    op.add_column(TABLE, sa.Column(COLUMN, sa.Numeric(12, 4), nullable=True))
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_SURCHARGE} CHECK ({_SURCHARGE_SQL}) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_SURCHARGE}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_SURCHARGE}")
    op.drop_column(TABLE, COLUMN)
