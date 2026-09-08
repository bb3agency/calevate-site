"""platform_tts_plan_fees — the operator-attested MONTHLY voice-plan fee, append-only

Revision ID: b7d4e91a0c58
Revises: a3c62f8b4d19
Create Date: 2026-09-08 00:00:00.000000

D-547 / PLAN-CREDIT-LOTS-AND-VOICE-TIERS §4.D.3. `platform_tts_prices` (e1d75c2b8a43)
answers "what does one CHARACTER cost", which is what a usage row needs. It cannot answer
"what did the vendor BILL US this month", and those are different numbers on purpose: a
Cartesia plan is a committed monthly spend for a character allotment, so the fee is paid
whether or not the allotment is spoken. The difference between the two — plan spend against
what our own meter attributed to calls — is the unused allotment, and it is the only
figure that says whether the plan is the right size. Nothing in this tree could publish it
before this table, because nothing recorded the fee.

## Why not a column on `platform_tts_prices`

That table is keyed `(provider, effective_from)` and holds a RATE that applies from an
instant until the next attestation supersedes it — deliberately not per month, so a rate
attested in July still prices an October call. A plan FEE is the opposite shape: it belongs
to exactly one month and says nothing about any other. Folding them together would give one
table two keys and a nullable figure in each row, and a reader would have to be told which
rows mean which. It is the same *act* (an operator reads their own invoice and puts their
name to a number), so it keeps the same PROVENANCE columns and the same append-only rule —
a second shape would have been inventing one.

## Why `month` is TEXT and not a date

It is an IST BILLING month (`billing/plans.ist_billing_month`), the same `YYYY-MM` string
`usage_events` is grouped by and every billing surface names. A `date` would have to be a
convention about which day stands for the month, and the CHECK below is what a date column
would buy anyway.

## Append-only, effective-dated, platform-scoped

`platform_tts_prices`' three properties for its three reasons. `effective_from` is in the
PK beside `month` so a CORRECTION is a later attestation for the SAME month rather than an
edit: re-rendering September next year resolves the figure that was live then, and the
history of what we believed we were billed survives. There is one vendor account for the
whole deployment, so no `tenant_id` — registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`
with that as the written reason.

⚠ **UNKNOWN, and not resolved here: whether the vendor's own character count agrees with
ours** (OPERATIONS §2 gate 51). `usage_events.qty` on a `tts_kchars` row is counted from
OUR transcript and from nothing the vendor says, so "attributed" and "billed" are two
independent measurements. This table records the second one; it does not reconcile them,
and the spend board publishes both rather than a reconciled figure.

⚠ **UNKNOWN: the vendor's OVERAGE rate past the allotment** (plan ADDENDUM 1, unknown #3).
The fee recorded here is what the invoice says, so a month that ran into overage records
the larger figure and needs no separate rate; the per-character ATTESTATION next door still
prices only characters INSIDE the allotment. No overage number is invented in either place.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched; both trigger functions already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, which destroys the attested plan-fee history — recoverable
only by re-attesting from the vendor invoices, exactly as `platform_tts_prices`' downgrade
is. No usage row is touched: this table has never been an input to `unit_cost_paid`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e91a0c58"
down_revision: str | None = "a3c62f8b4d19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "platform_tts_plan_fees",
        # OUR voice-tier vocabulary — text, not an enum, for `platform_tts_prices
        # .provider`'s reason: a fee read back for a historical month must resolve even
        # for a provider the catalogue no longer offers.
        sa.Column("provider", sa.Text(), nullable=False),
        # The IST billing month the invoice covers, `YYYY-MM`.
        sa.Column("month", sa.Text(), nullable=False),
        # The instant this attestation becomes authoritative FOR THAT MONTH. In the PK, so
        # a correction is a DISTINCT instant rather than a silent second row.
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # RUPEES for the whole month. NUMERIC(12,2): an invoice is quoted to the paisa and
        # there is nothing to divide here — the division by the allotment is the OTHER
        # table's figure.
        sa.Column("plan_inr", sa.Numeric(12, 2), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The operator's stated evidence — required, because it is what makes this an
        # attestation rather than a guess. The invoice number and the plan go here.
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_tts_plan_fees_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "provider", "month", "effective_from", name=op.f("pk_platform_tts_plan_fees")
        ),
        # STRICTLY POSITIVE at the database, not only at the API. An attested ₹0 is
        # indistinguishable on the spend board from "the vendor billed us nothing", which
        # is the one reading of a missing attestation that flatters us — the board renders
        # an absent month as ABSENT for exactly that reason, and a stored zero would
        # defeat it.
        sa.CheckConstraint("plan_inr > 0", name=op.f("ck_platform_tts_plan_fees_positive")),
        # The month is an IST billing month and the spend board joins on it as a string.
        # A row spelled `2026-9` would simply never match and would read as "nobody
        # attested September" — silent, and wrong in the flattering direction.
        sa.CheckConstraint(
            "month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
            name=op.f("ck_platform_tts_plan_fees_month_shape"),
        ),
    )
    # The resolution query — "this provider's fee for this month with the greatest
    # effective_from at or before instant T" — walks this index rather than scanning.
    op.create_index(
        "ix_platform_tts_plan_fees_provider_month",
        "platform_tts_plan_fees",
        ["provider", "month", sa.text("effective_from DESC")],
    )
    op.execute(
        "CREATE TRIGGER platform_tts_plan_fees_append_only "
        "BEFORE UPDATE OR DELETE ON platform_tts_plan_fees "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER platform_tts_plan_fees_forbid_truncate "
        "BEFORE TRUNCATE ON platform_tts_plan_fees "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE platform_tts_plan_fees "
        "ENABLE ALWAYS TRIGGER platform_tts_plan_fees_append_only"
    )
    op.execute(
        "ALTER TABLE platform_tts_plan_fees "
        "ENABLE ALWAYS TRIGGER platform_tts_plan_fees_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_tts_plan_fees_forbid_truncate "
        "ON platform_tts_plan_fees"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS platform_tts_plan_fees_append_only ON platform_tts_plan_fees"
    )
    op.drop_index(
        "ix_platform_tts_plan_fees_provider_month", table_name="platform_tts_plan_fees"
    )
    op.drop_table("platform_tts_plan_fees")
