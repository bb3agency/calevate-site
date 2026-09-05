"""prepaid is the default motion; every existing account moves to it

Revision ID: a8d3f61c04e7
Revises: f1c9e0a73b46
Create Date: 2026-09-03

D-521, which supersedes D-34 on which motion an account is born into. Three statements:
`prepaid` joins the `plan_tier` enum, the column's server default moves `managed` ->
`prepaid`, and **every organisation still on `managed` is moved to `prepaid`**.

═══════════════════════════════════════════════════════════════════════════════════════
READ THIS FIRST: WHAT THIS MIGRATION DOES TO A LIVE ACCOUNT, IN ONE PARAGRAPH
═══════════════════════════════════════════════════════════════════════════════════════
A `managed` account dials without a wallet — `compliance.service.credits_exhausted`
returns False for it, so a zero balance stops nothing. The moment this UPDATE commits,
that same account is `prepaid`, and if its `credit_ledger` is empty or its balance is
<= 0 then **every outbound dial is refused `no_credits` at the next tick**: the campaign
dispatch loop, the "call this lead" button and the requested-callback webhook all stop
until somebody tops it up. **Inbound answering is NOT affected, by construction and not
by luck** — `check_dispatch` refuses an inbound-only agent with `agent_inbound_only`
before it asks any money question, and no inbound path calls `credits_exhausted` at all
(`tests/credits_test.py` pins it). A clinic's phone still rings.

THE THREE OPTIONS, AND WHY THIS ONE
-----------------------------------
1. **Seed an opening balance for accounts that have none. REFUSED, and it is the one
   option that is not merely unwise but forbidden.** `credit_ledger` is append-only
   (hard rule 4): whatever this migration wrote would be permanent, would be the
   document a client reconciles their top-ups against, and would flow into
   `billing/attribution.py` and the margin panel as revenue. Every available `reason`
   is a lie about a fact — `topup` says money arrived and none did, `adjustment` says
   an operator decided something they were never asked — and inventing a fourth would
   be inventing money to paper over a decision (hard rule 7). Money a client did not
   pay is not a migration's to grant. If the founder wants an account to start with a
   balance, that is an operator writing an adjustment with their name on it, after this
   runs, knowing what it costs.
2. **Move only accounts that already hold a balance, and leave the rest.** Rejected: it
   is the option that fails silently. The accounts it leaves behind are exactly the ones
   nobody would notice — invoiced, uncapped, dialling on a motion the product no longer
   offers — and "an operator will convert them deliberately" is the sentence that leaves
   half a migration behind for ever. D-521's decision 2 is that existing accounts move.
3. **Move everyone and accept the stop. CHOSEN.** The stop is loud, immediate, reversible
   in one operator action per client, and it is the correct state: an account with no
   credit and no retainer should not be dialling on somebody else's money. The reversal
   is `POST /v1/admin/tenants/{tenant_id}/plan-tier` with `plan_tier: "managed"`
   (`admin:tenants`, audited) — added in the same change as this migration precisely so
   that the answer to "this client really is invoiced" is a click rather than an UPDATE
   typed into psql at speed.

WHAT IS KNOWN ABOUT WHO THIS HITS, AND WHAT IS NOT
--------------------------------------------------
Measured, not assumed: on the database this revision was written against
(`calevate_wt5`, migrated base->head and seeded), `SELECT plan_tier, count(*) FROM
organizations GROUP BY 1` returns **zero rows** — there is no organisation at all, so
the UPDATE moves nothing there. **UNKNOWN — the author of this revision cannot reach the
production database from the container it was written in**, so "the only accounts are
the founder's own test tenants" is REPORTED (founder, 3 Sep 2026) and is not verified
here. That is why this migration COUNTS AND LOGS rather than assuming: it prints how
many rows it moved and how many of those have no positive credit balance, so the operator
running the deploy reads the size of the consequence from the migration's own output
instead of from a claim. If that second number is not one the founder expects, the answer
is to stop and set those tenants back to `managed` — the account keeps dialling and the
data is unharmed either way.

WHY THE DEFAULT AND THE BACKFILL ARE ONE REVISION rather than a two-step: they are one
decision, and a deployment that took the new default without the backfill would be a
platform where the tier an account is on depends on the week it was created — the exact
drift that makes a later "why is this client invoiced?" unanswerable.

THE RLS BRACKET is not optional and is not decoration. `organizations` is FORCE ROW LEVEL
SECURITY (hard rule 1), which subjects the table OWNER to `tenant_isolation`, and that
policy is fail-closed on an unset `app.tenant_id`. Without the bracket this UPDATE matches
ZERO rows, reports success and advances the revision — the failure mode
`tests/migration_rls_bracket_test.py` exists for, which has shipped twice in this repo.
It is written one statement per table and restored in a `finally`, per that test's rules.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d3f61c04e7"
down_revision: str | None = "f1c9e0a73b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The constraint `e7b45c19a308` installed, and the two tuples it has held. SPELLED OUT
#: rather than imported from `tenancy.models.PLAN_TIERS`, for that revision's own stated
#: reason: a migration records the statement that RAN, and a later edit to that tuple must
#: not retroactively change what this revision is documented to have installed.
#: `tests/orm_schema_fidelity_test.py` keeps the model and the database honest instead.
PLAN_TIER_CHECK = "ck_organizations_plan_tier_enum"
TIERS_BEFORE = "('managed', 'self_serve', 'trial')"
TIERS_AFTER = "('managed', 'prepaid', 'self_serve', 'trial')"

OLD_DEFAULT = "managed"
NEW_DEFAULT = "prepaid"

#: `e7b45c19a308`'s measurement applies unchanged: both `ALTER TABLE` forms below take
#: AccessExclusiveLock on `organizations`, the busiest table in the schema, and the hazard
#: is lock ACQUISITION queueing behind an idle-in-transaction session rather than the scan.
#: A timeout turns an outage into a failed migration the operator retries.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"

#: The move itself. Predicated on the OLD value, so it is idempotent — a second run
#: matches nothing — and so it can never touch an account an operator has since put back
#: on `managed` for a reason (it will, if run again, and that is why this revision runs
#: once; see `downgrade` for the same asymmetry stated from the other side).
_FLIP = f"UPDATE organizations SET plan_tier = '{NEW_DEFAULT}' WHERE plan_tier = '{OLD_DEFAULT}'"

#: How many accounts cannot dial outbound until they are topped up, counted AFTER the flip:
#: every live tenant that is `prepaid` and has no positive balance on the newest
#: `credit_ledger` row. On this revision that set IS the set just moved — `prepaid` did not
#: exist a statement ago — which is why the count is taken here rather than from the
#: UPDATE's own row count, whose rows say nothing about whose wallet is empty.
#: This is the number the operator needs, and it is the reason `credit_ledger` is inside
#: the bracket as well — it is FORCE-RLS too, and the READ side of a statement is filtered
#: by the policy on the table being READ (`tests/migration_rls_bracket_test.READ_SIDE`).
#: `balance_after` of the newest entry is the same definition of "the balance"
#: `billing.service._newest_balance` uses; an account with no entries at all has none.
_STOPPED_COUNT = f"""
SELECT count(*) FROM organizations o
WHERE o.deleted_at IS NULL
  AND o.plan_tier = '{NEW_DEFAULT}'
  AND COALESCE((
        SELECT l.balance_after FROM credit_ledger l
        WHERE l.tenant_id = o.id
        ORDER BY l.occurred_at DESC, l.id DESC LIMIT 1
      ), 0) <= 0
"""


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    # The enum first: the UPDATE below writes a value the CHECK must already admit, and
    # inside one transaction the order is the only thing that decides which statement
    # fails.
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT {PLAN_TIER_CHECK}")
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {PLAN_TIER_CHECK} "
        f"CHECK (plan_tier IN {TIERS_AFTER})"
    )
    op.execute(f"ALTER TABLE organizations ALTER COLUMN plan_tier SET DEFAULT '{NEW_DEFAULT}'")

    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_ledger NO FORCE ROW LEVEL SECURITY")
    try:
        moved = op.get_bind().execute(sa.text(_FLIP)).rowcount
        stopped = op.get_bind().execute(sa.text(_STOPPED_COUNT)).scalar_one()
    finally:
        # RESTORED IN A `finally` for `b7e35c2f81da`'s reason: DDL is transactional here, so
        # a failure would roll the bracket back anyway — but a bracket that leans on the
        # transaction reads as if it need not be closed, and half a bracket is a tenancy
        # hole no RLS coverage check can see (`relrowsecurity` is still true; only FORCE
        # is gone).
        op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")

    # `print`, AND THE TWO OBVIOUS ALTERNATIVES WERE BOTH MEASURED AND REJECTED. This is
    # the sentence the person running the deploy has to read — the second number is a count
    # of businesses whose outbound calling has just stopped — so it must actually appear.
    #   * `op.get_context().impl.static_output(...)` asserts an output buffer that exists
    #     only in offline (`--sql`) mode: it would raise on every real deploy.
    #   * a `logging` call reaches nothing. `alembic/env.py` never calls `fileConfig`, so
    #     `alembic.ini`'s `[loggers]` section is inert and the root logger is unconfigured
    #     — verified here by running `alembic upgrade head` and getting ZERO output, not
    #     even alembic's own "Running upgrade" line.
    # stdout is what `scripts/vps-deploy.sh::run_migrations` captures (`compose --profile
    # migrate run --rm migrate`), so stdout is where this goes.
    print(  # noqa: T201 - the deploy log is this statement's only reader
        f"D-521: moved {moved} organisation(s) from '{OLD_DEFAULT}' to '{NEW_DEFAULT}'. "
        f"{stopped} prepaid account(s) now hold no calling credit and will be refused "
        "'no_credits' on every OUTBOUND dial until topped up (inbound is unaffected). "
        "Set a genuinely invoiced client back with POST /v1/admin/tenants/{id}/plan-tier."
    )


def downgrade() -> None:
    """Real, and honest about the one thing it cannot know.

    It puts every `prepaid` account back on `managed` and restores the three-member enum,
    which is the state `f1c9e0a73b46` produced. **It does NOT try to tell an account that
    was `managed` before this migration from one created `prepaid` afterwards**, because
    nothing recorded that — and it does not need to: `prepaid` is a value that did not
    exist below this revision, so on the way down every row carrying it must go somewhere,
    and `managed` is the only tier the older schema offers a wallet-less account. The
    direction of the error is the safe one: a downgraded deployment dials rather than
    stopping, which is what it did before D-521 anyway.

    The asymmetry with `upgrade` is deliberate and worth naming, because it is what a
    down-then-up walk produces: down moves ALL prepaid rows to managed, up then moves ALL
    managed rows to prepaid, so an account an operator had deliberately set to `managed`
    does not survive the round trip. That is a consequence of `plan_tier` holding no
    history, not something a migration can fix; the audit row written by the plan-tier
    route is where the operator's decision is actually recorded.
    """
    op.execute(LOCK_TIMEOUT)
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(f"UPDATE organizations SET plan_tier = '{OLD_DEFAULT}' WHERE plan_tier = '{NEW_DEFAULT}'")
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE organizations ALTER COLUMN plan_tier SET DEFAULT '{OLD_DEFAULT}'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT {PLAN_TIER_CHECK}")
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {PLAN_TIER_CHECK} "
        f"CHECK (plan_tier IN {TIERS_BEFORE})"
    )
