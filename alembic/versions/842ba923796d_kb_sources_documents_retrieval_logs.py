"""kb_sources, kb_documents, kb_retrieval_logs — the approval workflow

Revision ID: 842ba923796d
Revises: b57e2f9c4a13
Create Date: 2026-08-10

What this migration deliberately does NOT create: `kb_chunks`, its `vector(1024)`
column and its HNSW index. D-28 moved retrieval to a managed API service and made
those tables CONTINGENCY, built only if the bake-off fails — and D-33 keeps v1 in-call
retrieval on the engine's built-in KB, which is not a BYOK slot at all.

What stays ours whichever provider wins is exactly what is here: the source, its
versions, the preview chunks, and the approval gate. Provider-side document and
namespace ids land in `kb_documents.meta`, which is also what lets a DPDP erasure
prove it removed both copies.

All three tables carry `tenant_id` and get the standard FORCEd RLS policy — the
knowledge a client publishes is their content, and the retrieval log is a record of
what their callers asked.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '842ba923796d'
down_revision: str | None = 'b57e2f9c4a13'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('kb_sources',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('uri', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), server_default='uploaded', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('submitted_by', sa.UUID(), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('file', 'url', 'text', 'call_corpus')", name=op.f('ck_kb_sources_kind_enum')),
    sa.CheckConstraint("status IN ('uploaded', 'parsed', 'pending_approval', 'approved', 'rejected', 'archived')", name=op.f('ck_kb_sources_status_enum')),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_kb_sources_agent_id_agents'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_kb_sources_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_sources')),
    sa.UniqueConstraint('agent_id', 'name', 'version', name=op.f('uq_kb_sources_agent_id_name_version'))
    )
    op.create_index(op.f('ix_kb_sources_agent_id'), 'kb_sources', ['agent_id'], unique=False)
    op.create_index(op.f('ix_kb_sources_tenant_id'), 'kb_sources', ['tenant_id'], unique=False)
    op.create_table('kb_documents',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['kb_sources.id'], name=op.f('fk_kb_documents_source_id_kb_sources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_kb_documents_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_documents')),
    sa.UniqueConstraint('source_id', 'idx', name=op.f('uq_kb_documents_source_id_idx'))
    )
    op.create_index(op.f('ix_kb_documents_source_id'), 'kb_documents', ['source_id'], unique=False)
    op.create_index(op.f('ix_kb_documents_tenant_id'), 'kb_documents', ['tenant_id'], unique=False)
    op.create_table('kb_retrieval_logs',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('call_id', sa.UUID(), nullable=True),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('tier', sa.String(), nullable=False),
    sa.Column('top_score', sa.Float(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("tier IN ('t0','t1','t2','t3','t4')", name=op.f('ck_kb_retrieval_logs_tier_enum')),
    sa.ForeignKeyConstraint(['call_id'], ['calls.id'], name=op.f('fk_kb_retrieval_logs_call_id_calls'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_kb_retrieval_logs_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_retrieval_logs'))
    )
    op.create_index(op.f('ix_kb_retrieval_logs_tenant_id'), 'kb_retrieval_logs', ['tenant_id'], unique=False)

    # Standard tenant policy (DATA-MODEL §1) + FORCE so the owner role is subject to it.
    for table in ("kb_sources", "kb_documents", "kb_retrieval_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ("
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in ("kb_retrieval_logs", "kb_documents", "kb_sources"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f('ix_kb_retrieval_logs_tenant_id'), table_name='kb_retrieval_logs')
    op.drop_table('kb_retrieval_logs')
    op.drop_index(op.f('ix_kb_documents_tenant_id'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_source_id'), table_name='kb_documents')
    op.drop_table('kb_documents')
    op.drop_index(op.f('ix_kb_sources_tenant_id'), table_name='kb_sources')
    op.drop_index(op.f('ix_kb_sources_agent_id'), table_name='kb_sources')
    op.drop_table('kb_sources')
