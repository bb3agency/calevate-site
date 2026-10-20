"""platform_cost_attestations, and an expiry date on a credit lot

Revision ID: d8a4c2e7f150
Revises: c4e9a2f7b183
Create Date: 2026-10-20 23:00:00.000000

D-840 (founder, 20 Oct 2026).

`platform_cost_attestations` holds the cost inputs that are not a per-minute engine price but
still reach money: the voice platform's wallet top-up fee (a fraction added to every minute it
bills), the payment gateway's fee on a client's top-up (a fraction of what the client pays,
counted in the cost floor), and the monthly rent of a number rented in the voice platform's own
console (rupees a month). Each is effective-dated and attested by an operator, like
`platform_engine_minute_prices`; the subject names the unit (`billing/cost_attestations.py`).
Append-only with the shared triggers, `ENABLE ALWAYS`: an editable figure would re-price
minutes and rentals already metered against it. Platform-scoped (one engine account, one
gateway account), so no `tenant_id` and no policy.

The top-up fee was a code constant (2.36%, VENDOR-STATED in ThinnestAI's email of 12 Oct 2026)
until this revision; it is carried over as the first row, `attested_by` NULL and the note saying
where it came from, which is how `e5b1c8d42a07` carried the engine model bands over. Its
`effective_from` is the epoch, before any minute this platform has metered, so every minute
resolves the same fee it was metered at. The gateway fee and the number rent are NOT seeded:
nobody has read either off an invoice.

`credit_lots.expires_at` is when a lot's remaining credit lapses (credit packs expire 12 months
after purchase, stated at purchase). NULL for every existing lot and for every lot opened while
`Settings.credit_pack_expiry_months` is unset: credit bought under Terms that say it does not
expire never does. The lot-terms trigger freezes it like every column outside its allowlist.

Locking: one `CREATE TABLE`, two triggers, one seed row, one nullable `ADD COLUMN` (metadata
only). Downgrade drops the table, every figure attested since, and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8a4c2e7f150"
down_revision: str | None = "c4e9a2f7b183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_cost_attestations"

#: `billing/cost_attestations.COST_SUBJECTS`, frozen at this revision.
_SUBJECTS = ("thinnest_topup_fee", "razorpay_topup_fee", "thinnest_number_month")
#: The subjects that are a fraction of an amount rather than rupees.
_FRACTIONS = ("thinnest_topup_fee", "razorpay_topup_fee")

#: `billing/rates.THINNEST_TOPUP_FEE` as it stood when this revision replaced it.
_SEED_FEE = "0.023600"
_SEED_FROM = "1970-01-01T00:00:00+00:00"
_SEED_NOTE = (
    "Carried over from the code constant billing/rates.THINNEST_TOPUP_FEE: ThinnestAI email "
    "of 12 Oct 2026, 'Top-ups carry only the payment gateway's charge, 2.36% in INR, the same "
    "for everyone' (VENDOR-STATED)."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        _TABLE,
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(14, 6), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.CheckConstraint(f"subject IN {_SUBJECTS!r}", name=op.f(f"ck_{_TABLE}_subject_enum")),
        sa.CheckConstraint("value >= 0", name=op.f(f"ck_{_TABLE}_value_not_negative")),
        sa.CheckConstraint(
            f"subject NOT IN {_FRACTIONS!r} OR value < 1",
            name=op.f(f"ck_{_TABLE}_fraction_below_one"),
        ),
        sa.CheckConstraint(
            "length(btrim(source_note)) >= 3", name=op.f(f"ck_{_TABLE}_source_note")
        ),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f(f"fk_{_TABLE}_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("subject", "effective_from", name=op.f(f"pk_{_TABLE}")),
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_append_only BEFORE UPDATE OR DELETE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_forbid_truncate BEFORE TRUNCATE ON {_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_append_only")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_forbid_truncate")
    op.execute(
        sa.text(
            f"INSERT INTO {_TABLE} (subject, effective_from, value, source_note) "
            "VALUES ('thinnest_topup_fee', CAST(:ef AS timestamptz), CAST(:fee AS numeric), :note)"
        ).bindparams(ef=_SEED_FROM, fee=_SEED_FEE, note=_SEED_NOTE)
    )
    op.add_column(
        "credit_lots", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("credit_lots", "expires_at")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_forbid_truncate ON {_TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_append_only ON {_TABLE}")
    op.drop_table(_TABLE)
