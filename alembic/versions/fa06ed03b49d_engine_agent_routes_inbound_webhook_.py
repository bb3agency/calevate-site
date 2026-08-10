"""engine_agent_routes: inbound webhook routing

Revision ID: fa06ed03b49d
Revises: 769a9152cb06
Create Date: 2026-08-10

The table that lets Hard Rule 1 stay absolute.

An engine webhook arrives carrying the VENDOR's agent id, no session and no tenant —
so resolving it to one of our tenants is inherently a cross-tenant read. `agents` is
FORCE-RLS'd and must remain so, and the alternatives (an RLS exemption on `agents`, or
running the resolver as the owner role) would open exactly the hole the whole tenancy
model depends on staying shut.

So the resolver gets its own deliberately global, deliberately boring table: two opaque
ids mapping to the (tenant_id, agent_id) pair. No PII, no call data, no transcript —
being global is a property of ROUTING, not a compromise of isolation. It is written by
the agent publish path in the same transaction that sets `agents.engine_agent_ref`, so
the two cannot disagree, and it is registered in RLS_EXEMPT_TENANT_COLUMNS with that
reason so the coverage guardrail keeps it honest.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'fa06ed03b49d'
down_revision: str | None = '769a9152cb06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('engine_agent_routes',
    sa.Column('engine', sa.Text(), nullable=False),
    sa.Column('engine_agent_ref', sa.Text(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    # (engine, engine_agent_ref) is the natural key: the same vendor id can exist on
    # two engines during a migration and must resolve independently.
    sa.PrimaryKeyConstraint('engine', 'engine_agent_ref', name=op.f('pk_engine_agent_routes')),
    )
    # Reverse lookup for offboarding and for the admin "which agent is this?" view.
    op.create_index(
        'ix_engine_agent_routes_tenant', 'engine_agent_routes', ['tenant_id', 'agent_id']
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index('ix_engine_agent_routes_tenant', table_name='engine_agent_routes')
    op.drop_table('engine_agent_routes')
