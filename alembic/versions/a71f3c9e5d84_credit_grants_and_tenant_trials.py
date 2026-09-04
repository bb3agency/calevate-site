"""credit_ledger gains a 'grant' reason, and tenant_trials arrives

Revision ID: a71f3c9e5d84
Revises: c4a91e60d7b3
Create Date: 2026-09-04

Two features that both live on the money leg, in one revision because they ship together
and because a client on a trial and a client holding granted credit are the two ways this
platform can carry an account it is not being paid for. Nothing here moves a rupee; both
halves are schema.

--------------------------------------------------------------------------------
1. `grant` — CREDIT THE FOUNDER GAVE, OUT OF NOTHING (D-535)
--------------------------------------------------------------------------------
`billing/models.CREDIT_REASONS` argues at length why this is a sixth reason rather than a
sixth meaning for `topup`, `adjustment` or `bonus`. The schema consequences are the two
the `bonus` revision (c3a9f1e6b820) established for exactly this shape, and they are
copied deliberately rather than re-invented:

* **The reason CHECK grows.** `ck_credit_ledger_reason_enum` is the DB-side guard that
  `CREDIT_REASONS` is real, so the tuple and the constraint move in one edit. The ALTER
  validates every existing row under a brief ACCESS EXCLUSIVE lock, bounded by
  `lock_timeout` (hard rule 8).
* **A dedicated partial unique index makes a grant idempotent on its reference.**
  `ux_credit_ledger_tenant_reason_ref` (f9c2b41a8e57) covers only
  `('topup','usage','adjustment')` and carries a grandfather cutoff for a duplicate
  residue hard rule 4 forbids deleting. `grant` is brand new and has ZERO rows, so it has
  no residue, needs no cutoff, and rebuilding that carefully argued index would be a
  heavier and riskier change than a clean index for the one property wanted: at most one
  grant per (tenant, operator-supplied reference). Built CONCURRENTLY, outside the
  migration transaction, because `credit_ledger` is on the money write path and a plain
  build holds a SHARE lock that blocks every credit write for its duration.

--------------------------------------------------------------------------------
2. `tenant_trials` — N DAYS ON US (D-536)
--------------------------------------------------------------------------------
One row per trial. It is a STATE table, not a ledger: the row is UPDATEd once from
`active` to a terminal status and is never summed into a balance, so it is deliberately
NOT in `db/registry.APPEND_ONLY_TABLES` and carries no immutability trigger — the same
reading `topup_attempts` gets, and for the same reason (`billing/models.TenantTrial`).
What a trial COSTS is still recorded where money facts live: `usage_events` meters every
minute with our real `unit_cost_paid` throughout, which is the only reason anybody can
say what a trial cost us. What a trial does NOT do is debit `credit_ledger`.

RLS ships in this migration, not after it (hard rule 1): the table carries `tenant_id`,
gets ENABLE + FORCE and the DATA-MODEL §1 `tenant_isolation` policy, and is declared in
`db/registry.TENANT_TABLES` so `scripts/check_rls_coverage.py` holds it. The FK is
`ondelete="RESTRICT"` like every other tenant-scoped table here — an organisation row is
never hard-deleted (erasure is `deleted_at`, `compliance/tenant_erasure.py`).

Four CHECKs, each of which is a rule that must survive a script as well as a route:
`status` in the enum; `days` between 1 and 365 (THE ONLY BOUND THIS ARRANGEMENT HAS —
the founder was shown the unbounded-liability argument and chose days with no spend
ceiling, so the days are bounded in the schema as well as at the boundary); `ends_at >
started_at`; and `(status = 'active') = (ended_at IS NULL)`, which keeps "open" a single
fact — a row reading `expired` with a NULL `ended_at` is one the erasure sweep would
schedule from a NULL and skip for ever.

`ux_tenant_trials_active` is partial-unique on `tenant_id WHERE status = 'active'`: at
most one open trial per client, as a database fact rather than a reader's `if`, because
two operators starting a trial at the same moment would otherwise both read "none open"
and both insert, leaving the account with two end dates. Built inside the transaction —
the table is empty by construction here, so there is nothing to lock.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------
Drops `tenant_trials` (its policy and indexes go with it) and narrows the reason CHECK.
Narrowing is safe only before any `grant` row exists — the state at deploy and in every
CI run (base→head→base on a fresh database). A `grant` row already on the ledger makes
the narrowed CHECK fail to validate, exactly as hard rule 8's two-step deprecation
anticipates: the reverse is a schema reversal, never a data deletion (hard rule 4 forbids
deleting the row). Pre-migration code runs correctly against the post-downgrade schema,
which is the sense in which this is reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71f3c9e5d84"
down_revision: str | None = "c4a91e60d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_credit_ledger_reason_enum"
REASONS_WITH_GRANT = "('topup', 'usage', 'adjustment', 'refund', 'bonus', 'grant')"
REASONS_WITHOUT_GRANT = "('topup', 'usage', 'adjustment', 'refund', 'bonus')"

GRANT_INDEX = "ux_credit_ledger_grant_ref"
CREATE_GRANT_INDEX = (
    f"CREATE UNIQUE INDEX CONCURRENTLY {GRANT_INDEX} ON credit_ledger (tenant_id, ref) "
    "WHERE reason = 'grant' AND ref IS NOT NULL"
)
DROP_GRANT_INDEX = f"DROP INDEX IF EXISTS {GRANT_INDEX}"

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once carried the GUC returns
# '' when it is unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON tenant_trials USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def _swap_reason_check(reasons: str) -> None:
    """Replace the reason CHECK with one admitting exactly `reasons`. Bounded by
    `lock_timeout` because the ADD validates every existing row under ACCESS EXCLUSIVE."""
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE credit_ledger DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE credit_ledger ADD CONSTRAINT {CONSTRAINT} CHECK (reason IN {reasons})"
    )


def upgrade() -> None:
    _swap_reason_check(REASONS_WITH_GRANT)

    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "tenant_trials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("erase_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erasure_filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'converted', 'expired', 'stopped')",
            name=op.f("ck_tenant_trials_status_enum"),
        ),
        sa.CheckConstraint("days >= 1 AND days <= 365", name=op.f("ck_tenant_trials_days_range")),
        sa.CheckConstraint("ends_at > started_at", name=op.f("ck_tenant_trials_ends_after_start")),
        sa.CheckConstraint(
            "(status = 'active') = (ended_at IS NULL)",
            name=op.f("ck_tenant_trials_ended_iff_not_active"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_tenant_trials_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["started_by"],
            ["users.id"],
            name=op.f("fk_tenant_trials_started_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_trials")),
    )
    op.create_index(
        "ux_tenant_trials_active",
        "tenant_trials",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    # Expression index: autogenerate cannot diff one, so THIS revision is the source of
    # truth for its existence (the note `ix_credit_ledger_tenant_recent` carries).
    op.execute(
        "CREATE INDEX ix_tenant_trials_tenant_recent ON tenant_trials "
        "(tenant_id, started_at DESC, id DESC)"
    )
    op.execute("ALTER TABLE tenant_trials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_trials FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    # Outside the migration's transaction: CONCURRENTLY cannot run inside one, and a plain
    # build would hold a SHARE lock blocking every credit write for the length of the build.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE_GRANT_INDEX)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        # IF EXISTS so a failed CONCURRENTLY build's invalid index is cleaned up too.
        op.execute(DROP_GRANT_INDEX)
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table("tenant_trials")
    _swap_reason_check(REASONS_WITHOUT_GRANT)
