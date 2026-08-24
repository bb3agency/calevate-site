"""credit_ledger gains a 'bonus' reason for prepaid credit packs

Revision ID: c3a9f1e6b820
Revises: f4b1e9a2c7d0
Create Date: 2026-08-24

Prepaid credit packs (`apps/api/billing/credit_packs.py`) grant BONUS credits on top of the
paid credits — a promotional grant we fund, not money a bank moved. It needs its own ledger
`reason` because everything that treats a row as part of a bank transfer keys on
`reason = 'topup'` (`service.PAYMENT_REF_SQL`, `recorded_payments`,
`scripts/reconcile_credit_ledger.py`): a bonus folded into `topup` would make the wallet
claim a transfer credited more than the bank actually moved, and reconciliation would stop
balancing without saying so. A bonus is not a `usage`, an operator `adjustment`, or a
`refund` either, so `bonus` is the correct fifth value.

TWO SCHEMA CHANGES, and why each is shaped the way it is
-------------------------------------------------------
1. **The reason CHECK grows to admit 'bonus'.** `ck_credit_ledger_reason_enum`
   (migration f170dbce6f47) is the DB-side guard that `models.CREDIT_REASONS` is real, so
   the tuple and the constraint move together. The ALTER validates existing rows and takes a
   brief ACCESS EXCLUSIVE lock, bounded by `lock_timeout` (hard rule 8).

2. **A dedicated partial unique index makes the bonus idempotent on its payment id.**
   `ux_credit_ledger_tenant_reason_ref` (migration f9c2b41a8e57) deliberately covers only
   `reason IN ('topup','usage','adjustment')` and carries a grandfather cutoff for the
   pre-fix duplicate residue on those reasons. `bonus` is a brand-new reason with ZERO
   existing rows, so it has no residue and needs no cutoff — and rebuilding that carefully
   argued index to fold `bonus` in would be a heavier, riskier change than a clean new index
   for exactly the property we want: at most one bonus per (tenant, payment id). So this adds
   `ux_credit_ledger_bonus_ref (tenant_id, ref) WHERE reason='bonus' AND ref IS NOT NULL`,
   the same shape and the same argument the incumbent index makes, scoped to the one reason.
   Built CONCURRENTLY (outside the migration transaction) because `credit_ledger` is on the
   money write path and a plain build would hold a SHARE lock blocking every credit write —
   the trade f9c2b41a8e57 spells out.

RLS: no new table, so no new policy — `credit_ledger` already carries the FORCEd
`tenant_isolation` policy (migration 05bba2f3c19c / f170dbce6f47) and both a CHECK and an
index inherit the table's protection.

DOWNGRADE narrows the reason set again, and is safe ONLY before any 'bonus' row is written
— which is the state at deploy and in every CI run (base→head→base on a fresh database). A
`bonus` row already on the ledger would make the narrowed CHECK fail to validate, exactly as
hard rule 8's two-step deprecation anticipates: the reverse is a schema reversal, not a data
deletion (hard rule 4 forbids deleting the row). The pre-migration code runs correctly
against the post-downgrade schema, which is the sense in which this is reversible.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a9f1e6b820"
down_revision: str | None = "f4b1e9a2c7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_credit_ledger_reason_enum"
REASONS_WITH_BONUS = "('topup', 'usage', 'adjustment', 'refund', 'bonus')"
REASONS_WITHOUT_BONUS = "('topup', 'usage', 'adjustment', 'refund')"

BONUS_INDEX = "ux_credit_ledger_bonus_ref"
CREATE_BONUS_INDEX = (
    f"CREATE UNIQUE INDEX CONCURRENTLY {BONUS_INDEX} ON credit_ledger (tenant_id, ref) "
    "WHERE reason = 'bonus' AND ref IS NOT NULL"
)
DROP_BONUS_INDEX = f"DROP INDEX IF EXISTS {BONUS_INDEX}"


def _swap_reason_check(reasons: str) -> None:
    """Replace the reason CHECK with one admitting exactly `reasons`. Bounded by
    `lock_timeout` because the ADD validates every existing row under ACCESS EXCLUSIVE."""
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE credit_ledger DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE credit_ledger ADD CONSTRAINT {CONSTRAINT} CHECK (reason IN {reasons})"
    )


def upgrade() -> None:
    _swap_reason_check(REASONS_WITH_BONUS)
    # Outside the migration's transaction: CONCURRENTLY cannot run inside one, and a plain
    # build would hold a SHARE lock blocking every credit write for the length of the build.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE_BONUS_INDEX)


def downgrade() -> None:
    # Drop the index first (autocommit, IF EXISTS so it cleans up a failed CONCURRENTLY
    # build too), then narrow the CHECK. See the module docstring: narrowing is safe only
    # before any 'bonus' row exists — the deploy-time and CI state.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute(DROP_BONUS_INDEX)
    _swap_reason_check(REASONS_WITHOUT_BONUS)
