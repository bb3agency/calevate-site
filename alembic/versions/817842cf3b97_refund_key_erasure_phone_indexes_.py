"""Three deferred schema changes the audits specified but did not implement.

Held back until the alembic chain settled — three migrations were in flight from parallel
agents and a fourth would have forked it. Each of the three below was specified by an
audit, and each was re-verified against the LIVE catalogue here rather than taken from the
report that named it.

1. `refund` HAD NO DATABASE BACKSTOP. `credit_ledger` carries two partial unique indexes —
   `ux_credit_ledger_tenant_reason_ref` over `topup`/`usage`/`adjustment`, and
   `ux_credit_ledger_bonus_ref` over `bonus`. Of the five reasons, `refund` is in neither.
   That would be harmless if refund rows were keyless, and they are not: `payments.
   credit_refund` writes the provider's refund id as `ref`, so the row is keyed and the
   key is unenforced. Nothing is loose today — `credit_refund` takes `lock_tenant_credits`
   before its `find_entry_by_ref` and is the sole writer — so this closes the future
   writer who forgets the lock, which is the entire reason the other two indexes exist.

   MODELLED ON THE BONUS INDEX, NOT THE FIRST ONE. `ux_credit_ledger_tenant_reason_ref`
   carries an `occurred_at >= ...` floor because it was added over rows that predated it;
   `refund` needs no such floor and inventing one would carry a date nothing justifies.

2. A DPDP ERASURE FOUND ITS SUBJECT'S CALLS BY SEQUENTIAL SCAN. `execute_deletion_request`
   selects `WHERE from_e164 = :phone OR to_e164 = :phone OR erased_subject_ref = :ref`.
   Only the third column was indexed (`ix_calls_erased_subject_ref`), and an OR needs an
   index on EVERY arm before Postgres will build a BitmapOr — with one arm unindexed it
   falls back to scanning `calls` whole. That is the one query in this repository with a
   statutory clock on it (DPDP §12), and it got slower with every call ever placed.

   PARTIAL, AND THE PREDICATE IS THE ERASURE'S OWN POSTCONDITION. Both columns are set to
   NULL when a subject is erased, so `IS NOT NULL` excludes exactly the rows a later
   erasure can never match again: the index holds live callers only and SHRINKS as
   erasures are discharged, which is the opposite of how an index on this table usually
   behaves.

3. `webhook_deliveries.endpoint_id` WAS `SET NULL` AND IS NOW `RESTRICT` (verified from
   `pg_constraint.confdeltype = 'n'`). The delivery screen scopes by this column THROUGH
   `outbound_webhooks`, the tenant-RLS'd parent — so a NULLed `endpoint_id` is not a tidy
   orphan, it is a delivery attempt that has left its tenant's visibility entirely.
   `SET NULL` turned "you cannot delete an endpoint that has delivery history" into
   "deleting it silently detaches that history", which is the weaker guarantee wearing the
   stronger one's clothes. The column stays NULLABLE: an inbound delivery has no endpoint.

REVERSIBLE. `downgrade` drops the three indexes and restores `SET NULL`; no data moves in
either direction, so nothing is lost by going back.

⚠ ONE DEPLOYMENT NOTE, OBSERVED RATHER THAN IMAGINED. `CREATE UNIQUE INDEX` fails if the
table already holds rows the key would forbid, and this migration was seen to fail exactly
that way during its own red-proof: with the index absent, two refunds sharing a
`(tenant_id, ref)` were inserted, and the re-upgrade then refused. That is the CORRECT
behaviour — a unique index must not be created over data that violates it, and silently
skipping would be worse — but it means an operator applying this to a database that has
already taken duplicate refund references gets a failed migration rather than a warning.
The fix in that case is to reconcile the duplicates first; do NOT weaken the index to make
it apply. Today no client is in production, so the situation cannot arise here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "817842cf3b97"
down_revision: str | None = "dc1aaeeeff02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_webhook_deliveries_endpoint_id_outbound_webhooks"


def upgrade() -> None:
    op.create_index(
        "ux_credit_ledger_refund_ref",
        "credit_ledger",
        ["tenant_id", "ref"],
        unique=True,
        postgresql_where=sa.text("reason = 'refund' AND ref IS NOT NULL"),
    )
    op.create_index(
        "ix_calls_from_e164",
        "calls",
        ["from_e164"],
        postgresql_where=sa.text("from_e164 IS NOT NULL"),
    )
    op.create_index(
        "ix_calls_to_e164",
        "calls",
        ["to_e164"],
        postgresql_where=sa.text("to_e164 IS NOT NULL"),
    )
    op.drop_constraint(_FK, "webhook_deliveries", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "webhook_deliveries",
        "outbound_webhooks",
        ["endpoint_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "webhook_deliveries", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "webhook_deliveries",
        "outbound_webhooks",
        ["endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("ix_calls_to_e164", table_name="calls")
    op.drop_index("ix_calls_from_e164", table_name="calls")
    op.drop_index("ux_credit_ledger_refund_ref", table_name="credit_ledger")
