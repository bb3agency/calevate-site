"""each client's business-tailored examples and suggestions, written by AI (D-827)

Founder, 19 Oct 2026 (rememory decision cf399a30): every client account gets its own
examples, placeholders, suggested script steps, caller-detail suggestions and example
questions, written by AI from the business's details and its real-call gaps, stored once and
refreshed on request or every 15 days when those inputs changed.

`business_copies` holds that one set per client: `UNIQUE(tenant_id)`. Everything in `generated`
is the AI's own text; nothing the client typed is stored here, so replacing it on a refresh
can never overwrite a client's words. The rest of the row is the run's bookkeeping: the
fingerprint of the inputs it was written from (`inputs_hash`, so the scheduled refresh can
skip an unchanged business), the claim that keeps two runs from overlapping (`running_since`),
why the last run stopped (`stop_reason`, a closed set) and what the copy in use cost
(`cost_inr`, NUMERIC, hard rule 7).

Tenant data, so `tenant_id` and the FORCEd `tenant_isolation` policy ship here (hard rule
1); the cross-tenant zero-rows proof is `tests/business_copy_test.py`. An account's erasure
deletes the row (`workers/retention.execute_tenant_erasure`).

Downgrade drops the table and its policy; the copy is lost and the screens fall back to the
per-trade examples.

Revision ID: e4b7c2d9a183
Revises: c7e2a9f4d3b1
Create Date: 2026-10-19 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4b7c2d9a183"
down_revision: str | None = "c7e2a9f4d3b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "business_copies"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `tenancy/business_copy.STOP_REASONS`, spelled here because a migration must not import
#: application code that will change after it.
_STOP_REASONS = (
    "allowance_used_up",
    "ai_paused",
    "inputs_unchanged",
    "provider_unavailable",
    "answer_unusable",
    "account_closed",
)
_TRIGGERS = ("signup", "refresh", "scheduled", "operator")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("generated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_inr", sa.Numeric(), nullable=True),
        sa.Column("absorbed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trigger", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "generated IS NULL OR jsonb_typeof(generated) = 'object'",
            name=op.f(f"ck_{TABLE}_generated_is_object"),
        ),
        sa.CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN {_STOP_REASONS!r}",
            name=op.f(f"ck_{TABLE}_stop_reason_enum"),
        ),
        sa.CheckConstraint(
            f"last_trigger IS NULL OR last_trigger IN {_TRIGGERS!r}",
            name=op.f(f"ck_{TABLE}_last_trigger_enum"),
        ),
        sa.CheckConstraint(
            "cost_inr IS NULL OR cost_inr >= 0", name=op.f(f"ck_{TABLE}_cost_not_negative")
        ),
        sa.CheckConstraint(
            "inputs_hash IS NULL OR inputs_hash ~ '^[0-9a-f]{64}$'",
            name=op.f(f"ck_{TABLE}_inputs_hash_hex"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_business_copies_tenant"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
