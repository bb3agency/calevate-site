"""the refund ceiling that was released before the money moved

Revision ID: c4b8e91d7a05
Revises: a4f7d20c81be
Create Date: 2026-09-02 00:00:00.000000

`refund_intents` — one row per refund this platform has committed to ASKING the provider
for, written and COMMITTED before the ask.

--------------------------------------------------------------------------------
THE DEFECT
--------------------------------------------------------------------------------

`billing/payment_routes.py::issue_tenant_refund` bounds the refunds of one payment by
the payment: "₹2,000 and then ₹1,000 against a ₹2,500 top-up" must not both go through,
because the second returns ₹500 the client never paid and `credit_ledger` is append-only
(hard rule 4) — the compensating entries cannot be taken back.

The check read `credit_ledger` for the refunds already recorded, inside a
`tenant_session`, with `lock_tenant_credits` held (`find_topup` takes it). Then the
`async with` block ended. `pg_advisory_xact_lock` is released by COMMIT, so the lock — and
the snapshot — were gone BEFORE `issue_refund` called the provider. Two operators acting
at the same moment both read "nothing refunded yet", both passed the ceiling, and both
issued a provider refund. The route's own comment said the check was "the check half of a
check-then-write, and the write it guards is a provider call that cannot be undone",
which described the intent and not the code: the SEQUENTIAL case was closed and the
CONCURRENT one was open.

--------------------------------------------------------------------------------
WHY A TABLE, AND WHY NOT ONE OF THE THINGS THAT ALREADY EXIST
--------------------------------------------------------------------------------

The critical section spans a network call, so neither house primitive reaches it:

* an advisory XACT lock cannot be held across the provider request — BACKEND-PATTERNS §5
  says so in as many words, and `payments.issue_refund`'s docstring repeats it. An 8s
  vendor timeout (`ORDER_TIMEOUT_S`) would otherwise hold every wallet write for that
  tenant, including the post-call meter's;
* a Redis mutex is what §5 rejects for exactly this table's neighbours: a TTL-bounded
  lease silently outlives the section it is protecting, and this section's length is the
  vendor's to decide;
* `credit_ledger` cannot hold the claim, because the fact being claimed is not a money
  movement yet. There is nothing to key it on either: the ledger entry's `ref` is the
  provider's refund id, which is the answer to the call we have not made;
* `idempotency_records` dedupes ONE request replayed. It cannot bound a SUM across two
  different requests, which is the whole invariant.

So the claim is its own durable fact, taken under `lock_tenant_credits` in a transaction
that COMMITS before the provider is called, and the ceiling is measured against claims
instead of settlements. The loser of a race blocks on `ux_refund_intents_tenant_key` or
on the advisory lock, re-reads, and is refused with `refund_exceeds_payment` — before any
money moves.

`refund_key` is `payments.refund_idempotency_key(payment_id, amount)`, the exact string
handed to the provider, so our unique index and the vendor's idempotency collapse the
same set of requests. A second click on one refund is one row here and one refund there,
which is what lets the route go on treating a repeat of an already-claimed amount as a
replay rather than as a breach of the ceiling.

--------------------------------------------------------------------------------
NOT APPEND-ONLY, AND THAT IS THE POINT
--------------------------------------------------------------------------------

It must never join `db/registry.APPEND_ONLY_TABLES`. A claim whose provider call then
FAILED has to be released, or one transient 502 permanently shrinks what a client can be
refunded — money withheld by an outage. `payments.release_refund_claim` is that DELETE and
is the only writer that removes a row, in the same shape `outbox_messages` and
`webhook_inbox_events` release a claim they could not honour (BACKEND-PATTERNS §4).

RLS: `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1,
and a cross-tenant zero-rows test ships with it (hard rule 1).

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the table. What that destroys is stated rather than implied: the record of refunds
CLAIMED, which for any refund the provider has already processed is also recorded on
`credit_ledger` and is recoverable from there. What is lost is the claim for a refund
issued at the provider and not yet processed — a window of hours — after which the ceiling
would again be measured against settlements alone. Nothing here creates a function or a
trigger, so there is no `DuplicateFunction` on re-upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4b8e91d7a05"
down_revision: str | None = "a4f7d20c81be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON refund_intents USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "refund_intents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # The provider payment — the same value a `topup` row carries as its `ref`.
        sa.Column("payment_ref", sa.Text(), nullable=False),
        # `payments.refund_idempotency_key(payment_id, amount)`, stored rather than
        # re-derived so the unique index is over the exact string the provider was given.
        sa.Column("refund_key", sa.Text(), nullable=False),
        # INR at the ledger's own storage scale (hard rule 7: NUMERIC, never a float), so
        # a claim and the compensating entry it becomes are the same number.
        sa.Column("amount_inr", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_inr > 0", name=op.f("ck_refund_intents_amount_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_refund_intents_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_intents")),
    )
    # THE claim: one row per (tenant, provider idempotency key). A re-click, a retried
    # request and two concurrent identical asks are one row, so a replay can never add to
    # the total the ceiling is measured against.
    op.create_index(
        "ux_refund_intents_tenant_key", "refund_intents", ["tenant_id", "refund_key"], unique=True
    )
    # The ceiling's own read: everything claimed against one payment.
    op.create_index(
        "ix_refund_intents_tenant_payment",
        "refund_intents",
        ["tenant_id", "payment_ref"],
        unique=False,
    )
    op.execute("ALTER TABLE refund_intents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refund_intents FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON refund_intents")
    op.drop_index("ix_refund_intents_tenant_payment", table_name="refund_intents")
    op.drop_index("ux_refund_intents_tenant_key", table_name="refund_intents")
    op.drop_table("refund_intents")
