"""agent_test_runs, and the script builder's autosaved draft on agents (D-714)

Revision ID: f7c3a9e15d26
Revises: c4e8a1f7d290
Create Date: 2026-10-10 21:00:00.000000

One row per run of the scenario set (`agents/test_conversations.py`): what the agent said
to each scripted caller line and which tools it used, through the engine's sandboxed test
chat. A new tenant table, so RLS ships here (hard rule 1); the cross-tenant zero-rows proof
is `tests/agent_intelligence_test.py`. No caller data is involved.

`agents.script_draft` / `script_draft_saved_at`: the builder's autosaved working copy, kept
without a version until the owner puts it live. Nullable additions to a table that already
carries its RLS policy; no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7c3a9e15d26"
down_revision: str | None = "c4e8a1f7d290"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_test_runs"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    # `ALTER TABLE agents` below takes a brief exclusive lock on a hot table: fail fast
    # rather than queue in front of every writer.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f(f"ck_{TABLE}_status_enum"),
        ),
        sa.CheckConstraint(
            "results IS NULL OR jsonb_typeof(results) = 'array'",
            name=op.f(f"ck_{TABLE}_results_is_array"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{TABLE}_agent_id_agents"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f(f"ix_{TABLE}_agent_id"), TABLE, ["agent_id"])
    op.add_column("agents", sa.Column("script_draft", postgresql.JSONB(), nullable=True))
    op.add_column(
        "agents", sa.Column("script_draft_saved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.drop_column("agents", "script_draft_saved_at")
    op.drop_column("agents", "script_draft")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index(op.f(f"ix_{TABLE}_agent_id"), table_name=TABLE)
    op.drop_table(TABLE)
