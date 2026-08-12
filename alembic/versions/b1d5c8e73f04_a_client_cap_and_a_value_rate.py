"""a client cap and a value rate

Revision ID: b1d5c8e73f04
Revises: a4e7b2c95d18
Create Date: 2026-08-12 14:10:00.000000

Three nullable columns on `plans`, all three meaning "nothing changes for anyone who
already has a plan". They ship together because they are one slice — self-serve billing
needs a rate the tier ladder can express and a cap the spender can pull.

--------------------------------------------------------------------------------
1. `overage_rate_value` — the second rung the rate card already has
--------------------------------------------------------------------------------

`apps/api/billing/rates.py` resolves every metered call to a `premium` or `value` TTS
tier and stamps it into `usage_events.meta` (`tts_tier`, `tts_tier_source`, `tts_voice`).
D-36 makes the ladder real on the COST side — Bulbul v3 at ₹30/10k chars, v2 at ₹15 —
and D-35 records that v2 is live at half the v3 rate, which is exactly the lever TRD
§10.1 says builds a value/premium ladder. Billing could not express it: `plans` has one
`overage_rate` and no way to quote a second.

**NULL means "this plan quotes no separate value rate — bill everything at
`overage_rate`".** Every existing plan row is NULL after this migration, so no client's
bill moves by a paisa; `tests/value_tier_rate_test.py` pins that equivalence rather than
asserting it in prose.

**No number is invented here, and that is the point.** TRD §10.1's bands are explicitly
unmeasured — the 360–540 TTS chars per call-minute assumption is a pilot measurement
(gate 12) and the engine platform fee is UNVERIFIED (gate 12 again) — so deriving a
retail value rate from them would put a made-up price in a column that reads back later
as a commitment. What the schema owes the founder is somewhere to put the number they
decide; it does not owe them the decision.

--------------------------------------------------------------------------------
2 + 3. `client_cap_min` / `client_cap_spend` — the client's own stop button
--------------------------------------------------------------------------------

`hard_cap_min` / `hard_cap_spend` are ADMIN-owned and there has never been a client
surface for either. SURFACES §2b:89 puts "spend against cap" on the client's plan panel
and D-34's R-11 lists per-account spend caps among the non-negotiable mitigations that
ship with the self-serve motion. Two things are true at once: a control the spender can
raise at will is not a control, and a limit on their own money they cannot lower is not
their account. Two columns, and the EFFECTIVE cap is the stricter of the pair:

    effective_cap_min   = LEAST(hard_cap_min,   client_cap_min)
    effective_cap_spend = LEAST(hard_cap_spend, client_cap_spend)

NULL on either side means "no constraint from this side", which is `LEAST`'s own
semantics. `apps/api/billing/caps.py` holds that expression once, and both the meter
(`workers/pipeline.py`) and the client route read it from there, so they cannot end up
capping against different arithmetic. The full argument — including what happens when a
client sets a cap BELOW what they have already spent — lives in that module's docstring;
it is a product decision, not a schema one.

**Zero is a legal value, on purpose.** `client_cap_min = 0` is "stop my outbound calling
now", which is the emergency the control exists for. The CHECK is `>= 0` rather than
`> 0` for that reason, and NEGATIVE is refused because a negative ceiling is not a
stricter cap, it is a typo that would read as one.

--------------------------------------------------------------------------------
CONSTRAINTS
--------------------------------------------------------------------------------

Two CHECKs, both admitting NULL EXPLICITLY (`IS NULL OR …`) rather than relying on a
CHECK that returns NULL passing — writing it so it accidentally admits NULL is how the
next reader mistakes the sentinel for an oversight. Both are added NOT VALID (a brief
ACCESS EXCLUSIVE for the catalog row, no scan) and VALIDATEd separately under SHARE
UPDATE EXCLUSIVE, which blocks neither readers nor writers. Every pre-existing row is
NULL on all three columns and satisfies both trivially; the scan is for the catalog's
benefit, so the constraints are not left NOT VALID and therefore skipped by the planner
and by future ADD CONSTRAINT checks.

`lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE request cannot park in
front of every other session (hard rule 8).

**No backfill, and no FORCE bracket.** Nothing is UPDATEd: the three columns are new and
NULL is the value that reproduces today's behaviour exactly. The `NO FORCE`/`FORCE`
dance that `a4e7b2c95d18` and `d3b71c9a5e08` need is for migrations that write rows
through a FORCEd policy with no `app.tenant_id` GUC set; this one writes none.

**RLS.** No new table, so no new policy: `plans` already carries its FORCEd
`tenant_isolation` policy (05bba2f3c19c) and all three columns inherit the table's
protection — a column is not a separate security object. That is asserted rather than
assumed: `tests/client_spend_cap_test.py::test_a_second_tenant_can_neither_read_nor_
write_another_tenants_caps` reads and writes all three columns as another tenant and
requires zero rows.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the constraints and then the columns, reverse order of creation. What is lost is
what only these columns hold: a plan reverts to quoting a single overage rate (a
WIDENING on the money side only in the sense that the value rung stops being cheaper —
it is the pre-migration price, which is the price every current client is on), and every
client-imposed cap disappears, leaving the admin ceiling in force. Losing a client cap
is a LOOSENING, so it is named here rather than buried: after a downgrade a tenant the
client had stopped can dial again up to the admin's ceiling. The code that ran before
this revision runs correctly against the post-downgrade schema, which is the sense hard
rule 8 means by reversible. Nothing is two-step-deprecated because nothing is removed:
all three columns are new.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1d5c8e73f04"
down_revision: str | None = "a4e7b2c95d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "plans"

CK_VALUE_RATE = "ck_plans_overage_rate_value_nonnegative"
CK_CLIENT_CAPS = "ck_plans_client_caps_nonnegative"

# Mirrors nothing in Python on purpose — a migration is a snapshot of the schema on the
# day it ran, and importing today's constants would rewrite history the next time
# somebody widens the range (the rule a4e7b2c95d18 states for the same reason).
_VALUE_RATE_SQL = "overage_rate_value IS NULL OR overage_rate_value >= 0"
_CLIENT_CAPS_SQL = (
    "(client_cap_min IS NULL OR client_cap_min >= 0) "
    "AND (client_cap_spend IS NULL OR client_cap_spend >= 0)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # All three are nullable with no default: catalog-only since PG11, no rewrite, no
    # scan. NUMERIC(12,4) is the `MONEY` precision every rupee column on this table
    # already uses (billing/models.py) — a rate stored at a different precision than
    # the rate beside it is a rounding argument waiting to happen (hard rule 7).
    op.add_column(TABLE, sa.Column("overage_rate_value", sa.Numeric(12, 4), nullable=True))
    op.add_column(TABLE, sa.Column("client_cap_min", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("client_cap_spend", sa.Numeric(12, 4), nullable=True))

    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_VALUE_RATE} CHECK ({_VALUE_RATE_SQL}) NOT VALID"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_CLIENT_CAPS} CHECK ({_CLIENT_CAPS_SQL}) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_VALUE_RATE}")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_CLIENT_CAPS}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_CLIENT_CAPS}")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_VALUE_RATE}")
    op.drop_column(TABLE, "client_cap_spend")
    op.drop_column(TABLE, "client_cap_min")
    op.drop_column(TABLE, "overage_rate_value")
