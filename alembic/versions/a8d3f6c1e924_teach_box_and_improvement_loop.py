"""teach box and improvement loop: kb_facts, kb_teachings, agent_rule_proposals,
agent_test_cases (founder decisions 9 and 11, 10 Oct 2026)

Revision ID: a8d3f6c1e924
Revises: f7c3a9e15d26
Create Date: 2026-10-10 23:30:00.000000

Four new tenant tables, each with FORCEd RLS in this migration (hard rule 1); the
cross-tenant zero-rows proof is `tests/teach_loop_test.py`. The quick facts move into
`kb_facts` in revision `c2f7e8a4d1b6`, which also gives a fact its question and order.

DOWNGRADE drops all four tables, and with them every taught fact and saved test case. A
knowledge source already compiled from the facts stays in `kb_sources`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8d3f6c1e924"
down_revision: str | None = "f7c3a9e15d26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_TABLES = ("kb_teachings", "kb_facts", "agent_rule_proposals", "agent_test_cases")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _tenant(table: str) -> list[sa.Column | sa.ForeignKeyConstraint]:
    return [
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{table}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
    ]


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.create_table(
        "kb_teachings",
        sa.Column("id", sa.UUID(), nullable=False),
        *_tenant("kb_teachings"),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("gap_id", sa.UUID(), nullable=True),
        sa.Column("input_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("words", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("disclosure", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "input_kind IN ('text', 'photo', 'file', 'voice')",
            name=op.f("ck_kb_teachings_input_kind_enum"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'reading', 'heard', 'sorting', 'ready', 'saved', "
            "'discarded', 'failed')",
            name=op.f("ck_kb_teachings_status_enum"),
        ),
        sa.CheckConstraint(
            "items IS NULL OR jsonb_typeof(items) = 'array'",
            name=op.f("ck_kb_teachings_items_is_array"),
        ),
        sa.CheckConstraint(
            "words IS NULL OR char_length(words) <= 8000",
            name=op.f("ck_kb_teachings_words_length"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_kb_teachings_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gap_id"],
            ["knowledge_gaps.id"],
            name=op.f("fk_kb_teachings_gap_id_knowledge_gaps"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_teachings")),
    )
    op.create_index(op.f("ix_kb_teachings_tenant_id"), "kb_teachings", ["tenant_id"])

    op.create_table(
        "kb_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        *_tenant("kb_facts"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("origin", sa.Text(), server_default="taught", nullable=False),
        sa.Column("teaching_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "origin IN ('taught', 'quick_fact', 'call_gap')",
            name=op.f("ck_kb_facts_origin_enum"),
        ),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 500", name=op.f("ck_kb_facts_text_length")
        ),
        sa.ForeignKeyConstraint(
            ["teaching_id"],
            ["kb_teachings.id"],
            name=op.f("fk_kb_facts_teaching_id_kb_teachings"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_facts")),
    )
    op.create_index(op.f("ix_kb_facts_tenant_id"), "kb_facts", ["tenant_id"])

    op.create_table(
        "agent_rule_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        *_tenant("agent_rule_proposals"),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("teaching_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'dismissed')",
            name=op.f("ck_agent_rule_proposals_status_enum"),
        ),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 500",
            name=op.f("ck_agent_rule_proposals_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_rule_proposals_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teaching_id"],
            ["kb_teachings.id"],
            name=op.f("fk_agent_rule_proposals_teaching_id_kb_teachings"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_rule_proposals")),
    )
    op.create_index(
        op.f("ix_agent_rule_proposals_agent_id"), "agent_rule_proposals", ["agent_id"]
    )

    op.create_table(
        "agent_test_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        *_tenant("agent_test_cases"),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("source_call_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("caller_lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="idle", nullable=False),
        sa.Column("last_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_prompt_version", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('idle', 'queued', 'running')",
            name=op.f("ck_agent_test_cases_status_enum"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(caller_lines) = 'array' "
            "AND jsonb_array_length(caller_lines) BETWEEN 1 AND 6",
            name=op.f("ck_agent_test_cases_caller_lines_shape"),
        ),
        sa.CheckConstraint(
            "last_result IS NULL OR jsonb_typeof(last_result) = 'array'",
            name=op.f("ck_agent_test_cases_last_result_is_array"),
        ),
        sa.CheckConstraint(
            "char_length(expected) BETWEEN 1 AND 600",
            name=op.f("ck_agent_test_cases_expected_length"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_test_cases_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            name=op.f("fk_agent_test_cases_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_test_cases")),
    )
    op.create_index(op.f("ix_agent_test_cases_agent_id"), "agent_test_cases", ["agent_id"])

    for table in _TABLES:
        _isolate(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f("ix_agent_test_cases_agent_id"), table_name="agent_test_cases")
    op.drop_table("agent_test_cases")
    op.drop_index(op.f("ix_agent_rule_proposals_agent_id"), table_name="agent_rule_proposals")
    op.drop_table("agent_rule_proposals")
    op.drop_index(op.f("ix_kb_facts_tenant_id"), table_name="kb_facts")
    op.drop_table("kb_facts")
    op.drop_index(op.f("ix_kb_teachings_tenant_id"), table_name="kb_teachings")
    op.drop_table("kb_teachings")
