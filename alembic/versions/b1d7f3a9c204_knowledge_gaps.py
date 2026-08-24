"""knowledge gaps — the questions an agent could not answer, rolled up per topic

Revision ID: b1d7f3a9c204
Revises: f4b1e9a2c7d0
Create Date: 2026-08-24 09:00:00.000000

Two tables, and the split is `call_engine_latency`'s (samples vs aggregate):
`knowledge_gap_occurrences` is one row per (call, topic) — the provenance — and
`knowledge_gaps` is the per-(agent, topic) roll-up the dashboard reads. The aggregate is a
pure function of the occurrences, recomputed under a row lock (`insights/service.py`), so a
re-processed call replaces its own occurrence rows and nothing is double-counted.

Both carry `tenant_id` and get the STANDARD FORCEd `tenant_isolation` policy in THIS
migration (hard rule 1, DATA-MODEL §1). Both are TENANT data derived from a client's own
calls, and the quote columns hold REDACTED text only (hard rule 6) — the detector is handed
`transcript_turns.text_redacted`, never the raw turn.

NEITHER IS APPEND-ONLY. Both hold derived data (re-derivable from the transcript we still
hold); the aggregate is a running tally the client mutates via dismiss/teach. The immutable
trail of those mutations is `audit_log`, where every other client mutation records itself —
so `downgrade` drops both cleanly, losing only an index that a re-run of the pipeline
rebuilds (the same argument the key-moments migration makes).

The occurrence's `call_id` is `ON DELETE CASCADE` — an index into a transcript must not
outlive the call it points at, so a DPDP erasure or offboarding that removes the call takes
the occurrence with it. `agent_id`/`tenant_id` stay `RESTRICT` like every other tenant
table. `knowledge_gaps.resolved_by` is `SET NULL` (a person can leave; the decision stays)
and there is deliberately no FK from `kb_source_id` to `kb_sources` — the KB module owns
that table and a hard FK would couple this table's lifetime to another module's.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1d7f3a9c204"
down_revision: str | None = "f4b1e9a2c7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("knowledge_gaps", "knowledge_gap_occurrences")


def upgrade() -> None:
    op.create_table(
        "knowledge_gap_occurrences",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("topic_key", sa.Text(), nullable=False),
        sa.Column("topic_label", sa.Text(), nullable=False),
        sa.Column("question_redacted", sa.Text(), nullable=False),
        sa.Column("answer_redacted", sa.Text(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "signal IN ('dont_know', 'deferred_channel', 'unanswered_question')",
            name=op.f("ck_knowledge_gap_occurrences_signal_enum"),
        ),
        sa.CheckConstraint("hit_count >= 1", name=op.f("ck_knowledge_gap_occurrences_hit_count_positive")),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"],
            name=op.f("fk_knowledge_gap_occurrences_agent_id_agents"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"],
            name=op.f("fk_knowledge_gap_occurrences_call_id_calls"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_knowledge_gap_occurrences_tenant_id_organizations"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_gap_occurrences")),
        sa.UniqueConstraint(
            "tenant_id", "call_id", "topic_key",
            name=op.f("uq_knowledge_gap_occurrences_tenant_id_call_id_topic_key"),
        ),
    )
    op.create_index(
        op.f("ix_knowledge_gap_occurrences_agent_id"), "knowledge_gap_occurrences", ["agent_id"]
    )
    op.create_index(
        op.f("ix_knowledge_gap_occurrences_call_id"), "knowledge_gap_occurrences", ["call_id"]
    )
    op.create_index(
        op.f("ix_knowledge_gap_occurrences_tenant_id"), "knowledge_gap_occurrences", ["tenant_id"]
    )

    op.create_table(
        "knowledge_gaps",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("topic_key", sa.Text(), nullable=False),
        sa.Column("topic_label", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("example_question_redacted", sa.Text(), nullable=False),
        sa.Column("example_answer_redacted", sa.Text(), nullable=False),
        sa.Column("top_signal", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kb_source_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'taught', 'dismissed')",
            name=op.f("ck_knowledge_gaps_status_enum"),
        ),
        sa.CheckConstraint(
            "top_signal IN ('dont_know', 'deferred_channel', 'unanswered_question')",
            name=op.f("ck_knowledge_gaps_top_signal_enum"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"],
            name=op.f("fk_knowledge_gaps_agent_id_agents"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"],
            name=op.f("fk_knowledge_gaps_resolved_by_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_knowledge_gaps_tenant_id_organizations"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_gaps")),
        sa.UniqueConstraint(
            "tenant_id", "agent_id", "topic_key",
            name=op.f("uq_knowledge_gaps_tenant_id_agent_id_topic_key"),
        ),
    )
    op.create_index(op.f("ix_knowledge_gaps_agent_id"), "knowledge_gaps", ["agent_id"])
    op.create_index(op.f("ix_knowledge_gaps_tenant_id"), "knowledge_gaps", ["tenant_id"])

    # Standard tenant policy (DATA-MODEL §1) + FORCE so the owner role is subject to it.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ("
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f("ix_knowledge_gaps_tenant_id"), table_name="knowledge_gaps")
    op.drop_index(op.f("ix_knowledge_gaps_agent_id"), table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
    op.drop_index(
        op.f("ix_knowledge_gap_occurrences_tenant_id"), table_name="knowledge_gap_occurrences"
    )
    op.drop_index(
        op.f("ix_knowledge_gap_occurrences_call_id"), table_name="knowledge_gap_occurrences"
    )
    op.drop_index(
        op.f("ix_knowledge_gap_occurrences_agent_id"), table_name="knowledge_gap_occurrences"
    )
    op.drop_table("knowledge_gap_occurrences")
