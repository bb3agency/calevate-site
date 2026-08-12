"""campaigns, campaign_contacts, dlt_templates (DATA-MODEL §6)

Revision ID: e16c96e68bc5
Revises: d41f88a2c6e9
Create Date: 2026-08-11

The bulk-outbound tables, with the two properties the flow depends on:

- All three are tenant tables with the standard FORCEd RLS policy — a campaign is a
  client's contact list, which is exactly the data RLS exists to fence.
- `campaign_contacts` has UNIQUE(campaign_id, phone_e164): the dedupe the CSV upload
  promises is a constraint, not a loop that can race with itself.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e16c96e68bc5'
down_revision: str | None = 'd41f88a2c6e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('dlt_templates',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(), server_default='voice', nullable=False),
    sa.Column('classification', sa.String(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('dlt_ref', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), server_default='draft', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("classification IN ('promotional', 'transactional', 'service')", name=op.f('ck_dlt_templates_classification_enum')),
    sa.CheckConstraint("kind = 'voice'", name=op.f('ck_dlt_templates_kind_enum')),
    sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name=op.f('ck_dlt_templates_status_enum')),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_dlt_templates_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dlt_templates'))
    )
    op.create_index(op.f('ix_dlt_templates_tenant_id'), 'dlt_templates', ['tenant_id'], unique=False)
    op.create_table('campaigns',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('classification', sa.String(), nullable=False),
    sa.Column('number_id', sa.UUID(), nullable=True),
    sa.Column('dlt_template_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(), server_default='draft', nullable=False),
    sa.Column('schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('concurrency', sa.Integer(), server_default='3', nullable=False),
    sa.Column('retry_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('calling_hours', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('engine_campaign_ref', sa.Text(), nullable=True),
    sa.Column('launched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("classification IN ('promotional', 'transactional', 'service')", name=op.f('ck_campaigns_classification_enum')),
    sa.CheckConstraint("status IN ('draft', 'scheduled', 'running', 'paused', 'completed', 'cancelled')", name=op.f('ck_campaigns_status_enum')),
    sa.CheckConstraint('concurrency BETWEEN 1 AND 10', name=op.f('ck_campaigns_concurrency_range')),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_campaigns_agent_id_agents'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dlt_template_id'], ['dlt_templates.id'], name=op.f('fk_campaigns_dlt_template_id_dlt_templates'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['number_id'], ['phone_numbers.id'], name=op.f('fk_campaigns_number_id_phone_numbers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_campaigns_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaigns'))
    )
    op.create_index(op.f('ix_campaigns_tenant_id'), 'campaigns', ['tenant_id'], unique=False)
    op.create_table('campaign_contacts',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('campaign_id', sa.UUID(), nullable=False),
    sa.Column('phone_e164', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('custom', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_call_id', sa.UUID(), nullable=True),
    sa.Column('dedupe_hash', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'dialing', 'connected', 'no_answer', 'failed', 'dnc_blocked', 'completed')", name=op.f('ck_campaign_contacts_status_enum')),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_campaign_contacts_campaign_id_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['last_call_id'], ['calls.id'], name=op.f('fk_campaign_contacts_last_call_id_calls'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_campaign_contacts_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaign_contacts')),
    sa.UniqueConstraint('campaign_id', 'phone_e164', name=op.f('uq_campaign_contacts_campaign_id_phone_e164'))
    )
    op.create_index(op.f('ix_campaign_contacts_campaign_id'), 'campaign_contacts', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_contacts_tenant_id'), 'campaign_contacts', ['tenant_id'], unique=False)
    op.drop_index(op.f('ix_credit_ledger_tenant_recent'), table_name='credit_ledger')

    for table in ("campaigns", "campaign_contacts", "dlt_templates"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ("
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # The dispatcher's claim query: due pending contacts per campaign, oldest first.
    op.create_index(
        "ix_campaign_contacts_due",
        "campaign_contacts",
        ["campaign_id", "status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_contacts_due", table_name="campaign_contacts")
    for table in ("dlt_templates", "campaign_contacts", "campaigns"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.create_index(op.f('ix_credit_ledger_tenant_recent'), 'credit_ledger', ['tenant_id', sa.literal_column('occurred_at DESC')], unique=False)
    op.drop_index(op.f('ix_campaign_contacts_tenant_id'), table_name='campaign_contacts')
    op.drop_index(op.f('ix_campaign_contacts_campaign_id'), table_name='campaign_contacts')
    op.drop_table('campaign_contacts')
    op.drop_index(op.f('ix_campaigns_tenant_id'), table_name='campaigns')
    op.drop_table('campaigns')
    op.drop_index(op.f('ix_dlt_templates_tenant_id'), table_name='dlt_templates')
    op.drop_table('dlt_templates')
