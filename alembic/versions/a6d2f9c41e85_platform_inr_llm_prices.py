"""platform_inr_llm_prices — an operator-attested rupee price for a platform LLM

Revision ID: a6d2f9c41e85
Revises: d9a4c2e7f150
Create Date: 2026-10-10 00:00:00.000000

Sarvam's `sarvam-105b` chat leg is priced per token (VENDOR-PUBLISHED,
https://www.sarvam.ai/api-pricing, read 10 Oct 2026: ₹29.28 input / ₹10.98 cached input /
₹73.20 output per 1M tokens), superseding D-36's "free". It answers the dashboard
assistant when the main model fails and runs the first post-call extraction pass, so every
one of those calls is spend. Hard rule 7 lets a price reach `unit_cost_paid` only from an
operator's attestation, and `platform_model_prices` cannot hold this one: it is USD per
Mtok by construction with two rungs, and Sarvam bills in RUPEES with a third, cached-input
rung. Converting a rupee invoice into dollars to fit that table would make our recorded
cost move with an exchange rate the invoice never saw.

## The shape is `platform_tts_prices`', deliberately

Append-only (the shared `calevate_forbid_mutation` / `calevate_forbid_truncate` triggers,
`ENABLE ALWAYS`), effective-dated (PK `(model, effective_from)`, a correction is a new
instant), platform-scoped (one Sarvam account for the deployment, so no `tenant_id`; listed
in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`). `cached_in_inr_per_mtok` is nullable for a
vendor that publishes no cached rung.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched.

**Downgrade** drops the table and with it the attested history; no usage row is touched,
because `unit_cost_paid` is already written on each row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6d2f9c41e85"
down_revision: str | None = "d9a4c2e7f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "platform_inr_llm_prices"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("in_inr_per_mtok", sa.Numeric(12, 6), nullable=False),
        sa.Column("cached_in_inr_per_mtok", sa.Numeric(12, 6), nullable=True),
        sa.Column("out_inr_per_mtok", sa.Numeric(12, 6), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_inr_llm_prices_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("model", "effective_from", name=op.f("pk_platform_inr_llm_prices")),
        sa.CheckConstraint(
            "in_inr_per_mtok > 0 AND out_inr_per_mtok > 0 "
            "AND (cached_in_inr_per_mtok IS NULL OR cached_in_inr_per_mtok > 0)",
            name=op.f("ck_platform_inr_llm_prices_positive"),
        ),
    )
    op.create_index(
        "ix_platform_inr_llm_prices_model",
        TABLE,
        ["model", sa.text("effective_from DESC")],
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_forbid_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_append_only")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_forbid_truncate ON {TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE}")
    op.drop_index("ix_platform_inr_llm_prices_model", table_name=TABLE)
    op.drop_table(TABLE)
