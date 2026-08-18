"""Two rules the schema wrote down and the database never enforced (D-192)

Revision ID: e7b45c19a308
Revises: c7a1e93d40b8
Create Date: 2026-08-18 00:00:00.000000

Two unrelated tables, one fault: a rule stated in the repo and absent from `pg_catalog`,
where nothing looks. `check_metadata_columns` judges COLUMNS only and argues that scope
well; `compare_metadata` does not diff CHECK constraints or policies at all. Both of these
sat in the gap between those two facts.

═══════════════════════════════════════════════════════════════════════════════════════
PART 1 — `dnc_list`: a tenant could RE-TENANT a global suppression
═══════════════════════════════════════════════════════════════════════════════════════

THE HOLE, and it is the same compliance hole `e4f2a86b13d7` closed for DELETE, reached by
a different verb. That migration's docstring says, in its own words:

    "UPDATE was already safe and was checked rather than assumed: the same statement with
    `SET source = 'hijacked'` returns *new row violates row-level security policy*,
    because the NEW row fails `WITH CHECK`. Only DELETE was open."

The check was real and the conclusion was wrong, because the probe only tried an UPDATE
that LEFT THE ROW GLOBAL. `SET source = 'hijacked'` keeps `tenant_id IS NULL` and
`scope = 'global'`, which fails the permissive `WITH CHECK` for a session that carries an
`app.tenant_id` — so the refusal that was observed was real, and it says nothing about the
update that MOVES the row. `a1c8e40f27b9`'s `USING` admits `tenant_id IS NULL`, so a tenant
session may select a global row for update; the `WITH CHECK` then only asks whether the NEW
row is a legitimate row for this tenant. `SET tenant_id = <me>, scope = 'tenant'` satisfies
it exactly. Measured before writing this, as `calevate_app` against a scratch database
migrated from base to head:

    SET LOCAL app.tenant_id = '0190...000a';
    DELETE FROM dnc_list WHERE phone_e164 = '+919999000001' AND tenant_id IS NULL;
    -- DELETE 0        <- e4f2a86b13d7 doing its job
    UPDATE dnc_list SET tenant_id = '0190...000a', scope = 'tenant'
     WHERE phone_e164 = '+919999000001' AND tenant_id IS NULL;
    -- UPDATE 1        <- the row is now the attacker's
    DELETE FROM dnc_list WHERE phone_e164 = '+919999000001';
    -- DELETE 1        <- and a row you own may be deleted

Net effect: any tenant session can lift a platform-wide suppression — a regulator or TSP
instruction naming a number, or our own permanent refusal (DATA-MODEL §6) — for every
other client on the platform, in two statements. `remove_entry`'s `dnc_global_entry`
refusal is an APPLICATION check on one route; hard rule 1 is explicit that RLS is the
enforcement, which is the whole argument `e4f2a86b13d7` already made.

WHY NOTHING CAUGHT IT. `tests/rls_sweep_test.py` sweeps cross-TENANT mutation — tenant A
aiming at tenant B's rows. A global row belongs to no tenant, so `tenant_id IS NULL` is
outside every probe in that file by construction, and `dnc_list` is the only table in this
schema whose `USING` mentions `tenant_id IS NULL` (confirmed against `pg_policy`). The
behavioural pin that does exist, `dnc_test.py::
test_a_global_suppression_is_visible_to_a_tenant_and_not_removable`, asserts the ROUTE's
422 — which is the application check, not the table's.

THE FIX, and why it is shaped like its predecessor. A RESTRICTIVE policy is ANDed with the
permissive ones (PostgreSQL 16 §5.8: multiple policies "are combined using either OR (for
permissive policies ...) or using AND (for restrictive policies)"), and scoping it `FOR
UPDATE` subtracts exactly the verb that was over-permitted while leaving SELECT — the one
clause that MUST admit global rows, or a nationally suppressed number keeps getting dialled
— untouched. `WITH CHECK` is deliberately omitted: for a policy that can carry both,
PostgreSQL applies `USING` to the rows an UPDATE may select AND, "if no WITH CHECK
expression is defined, then the USING expression will be used for both purposes"
(PG16 CREATE POLICY). One expression is what makes "the rule for may-this-session-write-
this-row does not differ by verb" true by construction rather than by two texts agreeing.

The predicate is character-for-character `e4f2a86b13d7`'s, which is character-for-character
`a1c8e40f27b9`'s `WITH CHECK`. Three copies of one sentence is worse than one shared
constant, and this is the reason it stays a copy: a migration is a historical record of the
statement that ran, so importing the predicate from a module would let a later edit
retroactively change what an applied migration is documented to have done.

NOTHING IN THE APPLICATION UPDATES THIS TABLE. `grep -rn "UPDATE dnc_list" apps/` returns
nothing; `dnc.py` inserts and deletes only. So this policy refuses no path that exists, and
the ops path it must not refuse — an untenanted session, second branch — is the same one
`add_global_numbers` and `remove_global_entry` already run under.

═══════════════════════════════════════════════════════════════════════════════════════
PART 2 — `organizations.plan_tier`: the ENUM in the model, absent from the table
═══════════════════════════════════════════════════════════════════════════════════════

`apps/api/tenancy/models.Organization` has declared

    CheckConstraint(f"plan_tier IN {PLAN_TIERS!r}", name="plan_tier_enum")

since D-39, and `f170dbce6f47` — the migration that ADDED the column — added it as a bare
`sa.String()` with a server default and no constraint. The model's `CheckConstraint` is a
DDL instruction; SQLAlchemy never evaluates it client-side, so declaring it and not
migrating it means the rule exists nowhere that can refuse a row. Measured against a
database migrated base -> head:

    INSERT INTO organizations (..., plan_tier, ...) VALUES (..., 'enterprise_platinum', ...);
    -- INSERT 0 1

DATA-MODEL §2 spells the column `plan_tier ENUM[managed,self_serve,trial]` and §10 makes
"CHECK constraints mirror Pydantic enums" a migration rule. Every other enum column in this
schema has its `ck_*_enum` — `organizations.status`, `platform_state.load_shed_mode`,
`kyc_records.status`, `retention_policies.action`, twenty more. This one column was missed,
and no guard in the repo asks the question: `compare_metadata` does not report CHECK
constraints, so an ORM-declared check that was never migrated is invisible to
`check_metadata_columns` in both directions.

WHAT IT WOULD COST. `plan_tier` is not decoration — DATA-MODEL §2 calls it "which MOTION
this org belongs to ... it decides whether credits gate dispatch (compliance gate) and
whether the self-serve screens render". `admin/holds.py` selects the first-campaign-review
population with `plan_tier = ANY(:tiers)`, so a tenant carrying an unrecognised tier is
silently OUTSIDE R-11's manual hold rather than visibly wrong — a compliance control that
fails towards not applying.

NO PATH WRITES A BAD VALUE TODAY, and that is the point rather than an objection. The two
callers of `create_organization` are the admin route (which passes no tier at all, so
`DEFAULT_PLAN_TIER`) and `tenancy/signup.py` (whose `SelfServeTier` is a `Literal`). The
parameter itself is a plain `str | None`, so the guarantee currently rests on both callers
staying careful — which is exactly the argument `e4f2a86b13d7` made about `remove_entry`'s
application check, one part of this migration ago.

SAFE TO APPLY, verified rather than assumed: `SELECT plan_tier, count(*) FROM organizations
GROUP BY 1` on the development database returns only `managed`, `self_serve` and `trial`
(27392 / 3988 / 27), so `ADD CONSTRAINT` validates against real rows rather than being
declared `NOT VALID`. A deployment holding a value outside the enum should fix the row —
the constraint refusing to install is the correct outcome, not something to route around.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7b45c19a308"
down_revision: str | None = "c7a1e93d40b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "dnc_list_update_scope"

# The same sentence as `dnc_list_delete_scope` and as the FOR ALL policy's WITH CHECK, on
# purpose (see the docstring): a tenant may touch only its own tenant-scoped row, and a
# global row may be touched only by a session that carries no tenant at all.
UPDATE_USING = """
    (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND scope = 'tenant'
    )
    OR (
        tenant_id IS NULL
        AND scope = 'global'
        AND NULLIF(current_setting('app.tenant_id', true), '') IS NULL
    )
"""


#: Part 2. Spelled out rather than imported from `tenancy.models.PLAN_TIERS` for the same
#: reason the policy predicate above is a copy: a migration records the statement that RAN,
#: and a later edit to that tuple must not retroactively change what this revision is
#: documented to have installed. `tests/orm_schema_fidelity_test.py` is what keeps the two
#: from drifting apart in silence.
PLAN_TIER_CHECK = "ck_organizations_plan_tier_enum"
PLAN_TIERS_SQL = "('managed', 'self_serve', 'trial')"

# BOTH STATEMENTS BELOW TAKE AccessExclusiveLock, AND THIS LINE IS WHY THE MIGRATION HAS ONE
# (it was learned the expensive way, on a shared development database mid-review).
#
# Measured on PostgreSQL 16.15 via `pg_locks` inside an explicit transaction:
#
#     ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)              AccessExclusiveLock
#     ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID    AccessExclusiveLock
#     ALTER TABLE ... VALIDATE CONSTRAINT ...                     ShareUpdateExclusiveLock
#
# The hazard is NOT the table scan — `organizations` is small and the scan is microseconds.
# It is LOCK ACQUISITION. An AccessExclusive request queues behind any open transaction
# holding even AccessShare (an ordinary SELECT), and once queued it blocks every request
# behind IT. One session left `idle in transaction` on `organizations` therefore turns a
# millisecond of DDL into a full stop for every reader of the busiest table in the schema:
# observed live, eleven statements piled up behind this ALTER, including `SELECT plan_tier
# FROM organizations WHERE id = $1` — the compliance gate's own read.
#
# `lock_timeout` converts that outage into a failed migration the operator retries. It is
# LOCAL, so it reverts with this migration's transaction (`alembic/env.py` sets
# `transaction_per_migration=True`, so that boundary is exactly this revision).
#
# REJECTED: the NOT VALID / VALIDATE split. It is the right answer for a large table, and it
# buys nothing here for two reasons. The AccessExclusive window it shrinks is the SCAN, and
# the scan is not what hurt; and inside one transaction the lock taken by NOT VALID is held
# until COMMIT anyway, so the split only pays off across an `autocommit_block()` — which
# would trade atomicity (a half-applied revision alembic never stamps, so the retry fails on
# "constraint already exists") for a scan this table does not notice.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(
        f"CREATE POLICY {POLICY} ON dnc_list AS RESTRICTIVE FOR UPDATE USING ({UPDATE_USING})"
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {PLAN_TIER_CHECK} "
        f"CHECK (plan_tier IN {PLAN_TIERS_SQL})"
    )


def downgrade() -> None:
    # Reversible, and the reversal genuinely restores the prior behaviour — including both
    # holes — for the same reason `e4f2a86b13d7`'s downgrade does: a deployment running
    # `c7a1e93d40b8`'s schema is a deployment with these defects, and a downgrade that
    # refused would be a downgrade that lies about which schema it produced.
    #
    # Same lock bound as `upgrade`, and for the same reason: DROP CONSTRAINT and DROP POLICY
    # both take AccessExclusiveLock, and a downgrade runs on a live database under exactly
    # the conditions that make a lock queue expensive — an incident.
    op.execute(LOCK_TIMEOUT)
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT {PLAN_TIER_CHECK}")
    op.execute(f"DROP POLICY {POLICY} ON dnc_list")
