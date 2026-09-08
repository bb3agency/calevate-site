"""platform_list_rate_cancellations — withdrawing a scheduled card, without an UPDATE

Revision ID: e4a17c93d5b2
Revises: d1a7f39c50be
Create Date: 2026-09-08 00:00:00.000000

D-550. The credit-pack card became operator-editable and EFFECTIVE-DATED: a card is
recorded today and takes effect at least thirty days later (`billing/list_rates.
CARD_NOTICE_DAYS`), so a client's next top-up is priced at a rate they were told about a
month before it moved. That leaves one act with nowhere to go — an operator who records a
card and then thinks better of it, before anybody has been priced at it.

## Why this is a table and not an UPDATE, and not a DELETE

`platform_list_rates` is in `db/registry.APPEND_ONLY_TABLES` and carries the blanket
`calevate_forbid_mutation` trigger with no carve-out (d3b81f5c02ae argues it: a rate row
somebody could edit would silently re-price a month a client has already paid for out of
their wallet). Hard rule 4 has no exception for a change of mind, and it should not: what an
operator scheduled, and the fact that they withdrew it, are both things an auditor asks
about after a pricing mistake. A DELETE answers neither.

## Why not "re-record the old card one microsecond later"

That is the shape a pure append-only store suggests, and it leaves a hole. The rate table's
primary key is `(rate_key, effective_from)`, so the restoring card cannot share the
withdrawn card's instant — it has to land at least one microsecond after it. For that
microsecond `billing/list_rates.card_at` answers the card that was supposed never to take
effect, and a purchase landing inside the window freezes rates nobody approved onto a lot,
permanently (`credit_lots` is why the freeze is permanent, and is also the reason the whole
feature is safe). A window too small to hit on purpose is not a window that may be written
down as safe on a money path.

So a cancellation is its own fact: one row naming the INSTANT that is withdrawn. Every
resolution query in `billing/list_rates.py` carries a `NOT EXISTS` against this table
(`_NOT_CANCELLED`), so a withdrawn card prices nothing at any instant, with no window.

## Shape

`effective_from` is the PRIMARY KEY — a card IS an instant (twelve rate rows share one), so
withdrawing the same card twice is `ON CONFLICT DO NOTHING` rather than a second row, which
is what makes a double-clicked Cancel a no-op. There is deliberately NO foreign key to
`platform_list_rates`: that table's key is `(rate_key, effective_from)` and a cancellation
is not about one key, it is about all of them at that instant. `billing/list_rates.
card_is_scheduled` is what refuses an instant that names no card, with a sentence.

`cancelled_by` references `admin_users` exactly as `platform_list_rates.recorded_by` does:
every row here was typed by a person. `reason` is NOT NULL for the reason the rate table's
`source_note` is — a withdrawal with no stated ground is the one a future reader cannot
audit.

## Append-only itself, with the same two triggers

A cancellation that could be un-recorded is a cancellation that proves nothing: the
withdrawn card would spring back into force, retroactively, on every reader at once.
Registered in `db/registry.APPEND_ONLY_TABLES` so `check_ledger_immutability` verifies the
trigger, and in `RLS_EXEMPT_TENANT_COLUMNS` with its reason (platform-scoped, one card for
the whole self-serve motion, no tenant whose row this could be).

**Locking.** One `CREATE TABLE` and two triggers on it. Nothing existing is touched; both
trigger functions already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, which un-withdraws every cancelled card — the rows in
`platform_list_rates` are still there and every reader would resolve them again. Reversible
in the schema sense, not in the pricing one; the same asymmetry d3b81f5c02ae records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4a17c93d5b2"
down_revision: str | None = "d1a7f39c50be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_list_rate_cancellations",
        # WHICH card was withdrawn. A card is twelve `platform_list_rates` rows sharing one
        # `effective_from`, so the instant names it exactly, and being the PK makes a
        # repeated Cancel a no-op instead of a second row.
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=False),
        # WHY, in the operator's words. Required for `platform_list_rates.source_note`'s
        # reason: a pricing act with no stated ground cannot be audited afterwards.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_list_rate_cancellations_cancelled_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "effective_from", name=op.f("pk_platform_list_rate_cancellations")
        ),
    )

    # Append-only, blanket trigger (05bba2f3c19c): a withdrawal that could be un-recorded
    # would spring the cancelled card back into force on every reader at once.
    op.execute(
        "CREATE TRIGGER platform_list_rate_cancellations_append_only "
        "BEFORE UPDATE OR DELETE ON platform_list_rate_cancellations "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    # TRUNCATE is statement-level and a row trigger never sees it (a2e9f31c605d).
    op.execute(
        "CREATE TRIGGER platform_list_rate_cancellations_forbid_truncate "
        "BEFORE TRUNCATE ON platform_list_rate_cancellations "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ENABLE ALWAYS on both, so `SET session_replication_role = replica` cannot switch the
    # immutability off with no DDL and no schema diff.
    op.execute(
        "ALTER TABLE platform_list_rate_cancellations "
        "ENABLE ALWAYS TRIGGER platform_list_rate_cancellations_append_only"
    )
    op.execute(
        "ALTER TABLE platform_list_rate_cancellations "
        "ENABLE ALWAYS TRIGGER platform_list_rate_cancellations_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_list_rate_cancellations_forbid_truncate "
        "ON platform_list_rate_cancellations"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS platform_list_rate_cancellations_append_only "
        "ON platform_list_rate_cancellations"
    )
    op.drop_table("platform_list_rate_cancellations")
