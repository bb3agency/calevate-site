"""the numbers we bought, what they cost us, and when we gave them back

Revision ID: d1e58c7a94f2
Revises: a71f3c9e5d84
Create Date: 2026-09-04 00:00:00.000000

D-537. The founder adopted Model A on the inbound leg: Calevate buys an Indian DID
through the voice engine and the clinic forwards its own published number to it. Four
columns on `phone_numbers`, and each of them closes something that is a defect today.

**`engine_owned` — THE ONE COLUMN THAT SEPARATES THE TWO COMMERCIAL MODELS.** A number
the CLIENT holds on their own carrier account (Model B, unchanged and still half the
product) and a number WE bought from the engine are the same row today, and every path
that matters treats them differently: releasing at the vendor does nothing for the first
and stops a monthly charge for the second; deleting the agent must release the second and
must never touch the first; the rental is billed by their operator for the first and by
ours for the second. `false` is the safe default and is what every existing row gets,
because every existing row IS a client's own connection.

**`monthly_rental_usd` / `purchase_price_usd` — THE VENDOR'S OWN QUOTE, IN THE VENDOR'S
OWN CURRENCY, AND THAT IS DELIBERATE UNDER HARD RULE 7.** Rule 7 says money is NUMERIC INR
and never a float, and both of those are honoured: NUMERIC(12,4), and the INR figure is
`usage_events.unit_cost_paid` where it belongs. What these hold is the SOURCE figure the
rupee is derived from — Bolna prices in dollars and debits its wallet in dollars — and
storing a rupee here instead would freeze one exchange rate into a recurring charge that
is re-struck every month at a different one. So the dollars are the durable fact, the
rupees are the ledger's, and `billing/number_rental.py` is the single door between them.
NUMERIC, never float, in both columns: a binary fraction on the path to a ledger is the
defect rule 7 exists for, whatever currency it is in.

**`released_at` — A PAID ASSET MUST NOT BE ORPHANED AT A VENDOR.** Deleting the row would
lose the only evidence that we once paid for the number and when we stopped; keeping it
with no marker would make the monthly meter keep charging for a number we gave back. So
the release is recorded, the row survives (it is what an invoice query for a closed month
still needs), and the meter's own predicate reads this column.

WHY NOT A SEPARATE `bought_numbers` TABLE. The launch gate, the caller-ID resolver, the
inbound router and the DLT status all address `phone_numbers` and would each have needed
a union; and `e164` is globally UNIQUE there, which is the constraint that actually stops
one number being held twice. One table, four nullable columns, no new RLS surface — the
existing FORCEd `tenant_isolation` policy on `phone_numbers` covers every one of them.

REVERSIBLE (hard rule 8). The downgrade drops the four columns and nothing else; no data
outside them is touched, and the two-step deprecation rule does not bite because nothing
is being retired here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e58c7a94f2"
down_revision = "a71f3c9e5d84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        # NOT NULL with a server default rather than nullable-and-three-valued: "we do not
        # know who owns this number" is not a state any caller could act on, and a NULL
        # here would reach the release path as "maybe release it", which either orphans a
        # rental or deletes a client's own connection at a vendor that never held it.
        sa.Column(
            "engine_owned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("purchase_price_usd", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("monthly_rental_usd", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A number we bought, still held, and being billed for. The monthly meter walks
    # exactly this set once per IST month, and the reconciliation sweep walks it against
    # the vendor's own listing. Partial, because the overwhelming majority of rows are
    # client-owned connections this index must not carry.
    op.create_index(
        "ix_phone_numbers_engine_owned_live",
        "phone_numbers",
        ["tenant_id"],
        unique=False,
        postgresql_where=sa.text("engine_owned AND released_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_phone_numbers_engine_owned_live", table_name="phone_numbers")
    op.drop_column("phone_numbers", "released_at")
    op.drop_column("phone_numbers", "monthly_rental_usd")
    op.drop_column("phone_numbers", "purchase_price_usd")
    op.drop_column("phone_numbers", "engine_owned")
