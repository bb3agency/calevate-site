"""platform_model_prices — operator-attested vendor prices, effective-dated, append-only

Revision ID: c7f1a9e34b62
Revises: f2c74b81a9d3
Create Date: 2026-08-23 00:00:00.000000

PLATFORM-CONFIG §5. The founder configures every vendor credential in the ops panel and,
for the two declared-but-unpriced legs (OpenAI direct and Google Gemini, D-456), the
AUTHORITATIVE billing price too — read off their own vendor console or invoice and typed
in. Hard rule 7 has no REPORTED tier: `calevate_shared.engine.LlmModelSpec` refuses to
make a model selectable on an unverified price, and every OpenAI/Google pricing page is
egress-blocked from this deployment, so an attested first-party figure is the only price
those legs can ever carry. This table is where it lives.

## Config, not a secret

No ciphertext, no envelope, nothing encrypted. A price must be auditable and revertible —
an operator has to SEE what it is set to and correct a wrong one — which is the opposite
of `platform_secrets`' write-only credential. It carries no PII and no credential; the
only sensitive thing about it is that it reaches `unit_cost_paid`, and that is served by
visibility, not by hiding it.

## Append-only AND effective-dated — one property

The primary key is `(model, effective_from)`. A correction is a NEW ROW with a later
`effective_from`, never an edit, so `ops.model_pricing.attested_model_prices(at=…)` can
answer "which price was live when THIS month's minutes ran" a year later — a re-rendered
invoice is re-derivable rather than re-priced by whatever changed since. That is the same
guarantee `billing/plans.py`'s effective-dated plans give, arrived at with the simpler
"greatest effective_from <= t" resolution rather than a half-open valid-time window,
because a price has no natural `effective_to`: the next attestation IS its end.

It joins the hard-rule-4 family (`db/registry.APPEND_ONLY_TABLES`) with the SHARED blanket
trigger, `calevate_forbid_mutation` — not `platform_secrets`' column-permitting variant.
`platform_secrets` needs an exception because a KEK rewrap must re-wrap historical DEKs in
place; this table needs no such thing, so EVERY column is immutable once written and the
strongest trigger applies with no carve-out. TRUNCATE is covered by the shared
`calevate_forbid_truncate` (migration a2e9f31c605d), and BOTH triggers are `ENABLE ALWAYS`
so `SET session_replication_role = replica` cannot switch them off — the standing
requirement `check_ledger_immutability` verifies for every ledger.

## Not tenant-scoped

One account, one Azure/OpenAI/Google subscription, one price per model at an instant —
there is no tenant whose row this could be, so no `tenant_id`. Registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason; the RLS sweep's
rule 7a REQUIRES a `platform_*` table to appear there.

## No config-version sentinel trigger, deliberately

`platform_settings` and `platform_secrets` bump `platform_config_version` so every process
re-reads its `Settings` snapshot. This table is NOT a `Settings` field — nothing here flows
through `apply_platform_overrides`, and the reader (`attested_model_prices`) queries the
database directly at render time. Bumping the sentinel would force a fleet-wide config
re-read for a change no `Settings` snapshot reflects, so it is omitted.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched, and the two trigger FUNCTIONS already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, which destroys the attested price history. It is
recoverable only by re-attesting from the vendor invoices — the same irreversibility
`platform_secrets`' downgrade carries, and for the same reason: the evidence lives off
this database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7f1a9e34b62"
down_revision: str | None = "f2c74b81a9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_model_prices",
        # OUR model identifier — a key of `calevate_shared.engine.LLM_MODELS`. Text, not an
        # enum, so a price read back for a historical invoice resolves even for a model the
        # allow-list no longer carries.
        sa.Column("model", sa.Text(), nullable=False),
        # The instant this price becomes authoritative. Part of the PK, so a correction is a
        # DISTINCT instant rather than a silent second row.
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # USD per MILLION tokens, the unit `calevate_shared.engine.LlmPrice` publishes and
        # `billing/rates.py` converts from. NUMERIC(12,6): a per-Mtok dollar figure needs
        # the vendor's precision, and INR conversion happens downstream at a named FX rate.
        sa.Column("input_usd_per_mtok", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_usd_per_mtok", sa.Numeric(12, 6), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The operator's stated evidence — required, because it is what makes this an
        # attestation rather than a guess.
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_model_prices_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "model", "effective_from", name=op.f("pk_platform_model_prices")
        ),
        # STRICTLY POSITIVE, checked at the database and not only at the API (a NUMERIC
        # column is reachable by any writer with the untenanted role). Zero is refused for
        # the reason `billing/rates.LlmPriceAttestation.__post_init__` refuses it: an
        # attested ₹0 bills every minute on this model at nothing and looks exactly like a
        # working leg, which is the one metering failure nobody investigates. A genuinely
        # free leg is a decision-log entry and a code path, never a zero typed into a price
        # box that the whole billing chain then trusts.
        sa.CheckConstraint(
            "input_usd_per_mtok > 0 AND output_usd_per_mtok > 0",
            name=op.f("ck_platform_model_prices_positive"),
        ),
    )
    # The resolution query — "the price for this model with the greatest effective_from at
    # or before instant T" — walks this index rather than scanning the model's history.
    op.create_index(
        "ix_platform_model_prices_model",
        "platform_model_prices",
        ["model", sa.text("effective_from DESC")],
    )

    # Append-only, with the SHARED blanket trigger (05bba2f3c19c): every column immutable,
    # every UPDATE and DELETE refused. No rewrap exception — this table never needs one.
    op.execute(
        "CREATE TRIGGER platform_model_prices_append_only "
        "BEFORE UPDATE OR DELETE ON platform_model_prices "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    # TRUNCATE is statement-level and a row trigger never sees it (a2e9f31c605d): the shared
    # `calevate_forbid_truncate` closes the verb that empties a ledger fastest.
    op.execute(
        "CREATE TRIGGER platform_model_prices_forbid_truncate "
        "BEFORE TRUNCATE ON platform_model_prices "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ENABLE ALWAYS on both, so `SET session_replication_role = replica` cannot switch the
    # immutability off with no DDL and no schema diff — the standing requirement
    # `check_ledger_immutability` verifies for every append-only table.
    op.execute(
        "ALTER TABLE platform_model_prices "
        "ENABLE ALWAYS TRIGGER platform_model_prices_append_only"
    )
    op.execute(
        "ALTER TABLE platform_model_prices "
        "ENABLE ALWAYS TRIGGER platform_model_prices_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_model_prices_forbid_truncate ON platform_model_prices"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS platform_model_prices_append_only ON platform_model_prices"
    )
    op.drop_index("ix_platform_model_prices_model", table_name="platform_model_prices")
    op.drop_table("platform_model_prices")
