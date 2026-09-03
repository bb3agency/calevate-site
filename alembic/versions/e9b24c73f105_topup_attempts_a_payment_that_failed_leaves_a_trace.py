"""topup_attempts + wallet_alerts — a payment that failed leaves a trace, and a
warning is sent once per empty-wallet episode

Revision ID: e9b24c73f105
Revises: b7e35c2f81da
Create Date: 2026-09-02

WHY THIS TABLE EXISTS
---------------------
Until now a self-serve top-up left NO durable record until money arrived. The intent
route minted a receipt and (on a deployment holding the API secret) a provider order,
and the only row written anywhere was the `credit_ledger` entry the captured-payment
webhook appends. Everything in between was invisible:

* a client whose card was declined saw the failure once, in the payment window, and then
  nothing — the screen they came back to looked exactly like a screen they had never
  touched;
* a client who closed the tab mid-payment had no way to tell "still settling" from
  "nothing happened";
* nobody could answer "how many top-ups were attempted on this account this week" for a
  client on a support call, because the answer only ever recorded the successes.

`idempotency_records` is NOT that record and was considered first: its `scope_key` is an
HMAC fingerprint with no `tenant_id` column (so it carries no RLS policy and cannot be
read back per tenant), and it expires in about 24 hours. A record a client must consult
within a day, of a payment that may take longer than that to settle, is not a record.

WHAT IT IS NOT
--------------
**It is not a ledger and it is not money.** The wallet is `credit_ledger` and nothing
here ever becomes a balance: `status` is a description of a PAYMENT ATTEMPT at the
provider, and the only thing that credits a wallet is still the signed webhook. That is
why this table is UPDATEd in place and is deliberately absent from
`registry.APPEND_ONLY_TABLES` — hard rule 4 protects the assertions that add up to a
balance, and an attempt's status is not one of them. The append-only row for a captured
payment already exists, one table over, keyed on the provider's payment id.

So a lost UPDATE here costs a client a slightly stale word on a screen; it can never
cost or double a rupee. That asymmetry is the whole reason this is a separate table
rather than columns bolted onto the ledger.

STATUS IS A THREE-VALUE VOCABULARY, and the CHECK is the guard
---------------------------------------------------------------
`created` — an order exists (or a reference was minted); nothing has been heard since.
`captured` — the provider told us the payment succeeded; the wallet has been credited by
the same webhook delivery, in the same transaction.
`failed` — the provider told us the attempt failed. No money moved.

There is deliberately no `pending` and no `cancelled`. "Pending" is `created` plus the
passage of time, and putting a clock into a stored status means a row that is wrong
whenever nothing has run recently; the screen decides how old is old. "Cancelled" would
be the browser's word for closing a window, and the browser is not a source of truth
about a payment (`payment_routes.py`).

IDEMPOTENCY
-----------
`ux_topup_attempts_tenant_receipt` is the key. The receipt is derived server-side by
`payments.topup_receipt` from (tenant, amount, a 15-minute window), which is the SAME key
the intent route claims its idempotency under — so a double click that produces one order
also produces one attempt row, by construction rather than by a read-then-write.

`ix_topup_attempts_tenant_order` is the webhook's read: a captured or failed event names
an order id, and this is how it finds the attempt to mark. It is NOT unique — a
deployment that could not create an order writes `NULL` there, and many NULLs are not a
conflict in Postgres, but relying on that is a subtlety a reader should not have to know.
The uniqueness that matters is on the receipt.

RLS
---
`tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1, and a
cross-tenant zero-rows test ships with it (hard rule 1). Every writer runs inside
`tenant_session`, including the webhook, which resolves the tenant from the order notes
before it touches anything durable.

DOWNGRADE drops the policy, the indexes and the table, in that order — a real reverse,
and safe at any time because nothing else references this table and no balance is derived
from it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b24c73f105"
down_revision: str | None = "d8f31a7c2409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON topup_attempts USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "topup_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # OUR reference, minted by `payments.topup_receipt`. The client sees this one, and
        # it is what a bank transfer quotes on the deployments that cannot take a card.
        sa.Column("receipt", sa.Text(), nullable=False),
        # The provider's order id, NULL on a deployment that holds no API secret
        # (`payment_capability().creates_orders` is False and nothing was created).
        sa.Column("provider_order_id", sa.Text(), nullable=True),
        # The provider's payment id, once one exists. Written by the webhook, so it is the
        # same string the `credit_ledger` top-up carries as its `ref` — which is what lets
        # a screen put an attempt and the credit it became beside each other without
        # either of them having to know about the other's table.
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        # INR at the ledger's own storage scale (hard rule 7: NUMERIC, never a float).
        sa.Column("amount_inr", sa.Numeric(12, 4), nullable=False),
        # The catalogue pack this attempt priced, or NULL for a free-form amount.
        sa.Column("pack_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
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
        sa.CheckConstraint("amount_inr > 0", name=op.f("ck_topup_attempts_amount_positive")),
        sa.CheckConstraint(
            "status IN ('created', 'captured', 'failed')",
            name=op.f("ck_topup_attempts_status_enum"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_topup_attempts_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topup_attempts")),
    )
    # ONE attempt per receipt. The receipt is derived, not client-supplied, so this is the
    # same once-ness the intent route's idempotency claim already has — held by the
    # database rather than by both writers remembering.
    op.create_index(
        "ux_topup_attempts_tenant_receipt",
        "topup_attempts",
        ["tenant_id", "receipt"],
        unique=True,
    )
    # The webhook's lookup: an event names an order id.
    op.create_index(
        "ix_topup_attempts_tenant_order",
        "topup_attempts",
        ["tenant_id", "provider_order_id"],
        unique=False,
    )
    # The screen's read — the newest attempts for one tenant. Expression index because the
    # DESC is the point: without it the plan sorts a tenant's whole history to answer a
    # LIMIT 10, exactly as `ix_credit_ledger_tenant_recent` exists to avoid.
    op.execute(
        "CREATE INDEX ix_topup_attempts_tenant_recent ON topup_attempts "
        "(tenant_id, created_at DESC, id DESC)"
    )
    op.execute("ALTER TABLE topup_attempts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE topup_attempts FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON topup_attempts")
    op.execute("DROP INDEX IF EXISTS ix_topup_attempts_tenant_recent")
    op.drop_index("ix_topup_attempts_tenant_order", table_name="topup_attempts")
    op.drop_index("ux_topup_attempts_tenant_receipt", table_name="topup_attempts")
    op.drop_table("topup_attempts")
