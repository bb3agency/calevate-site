"""dnc_list with an asymmetric RLS policy

Revision ID: 17a91a69dee9
Revises: fa06ed03b49d
Create Date: 2026-08-10

The DNC list is the one tenant table whose policy is NOT the standard
`tenant_id = current_setting(...)` form, and the asymmetry is the point:

- **READ** must include global entries (`tenant_id IS NULL`). A nationally suppressed
  number that a tenant cannot see is a number that tenant keeps dialling — the exact
  TRAI exposure the list exists to prevent.
- **WRITE** must NOT. If WITH CHECK were derived from USING (the default), any tenant
  could insert a `tenant_id IS NULL` row and suppress a number for every other client
  on the platform.

So USING and WITH CHECK are written separately, and creating a global entry is simply
not a tenant-reachable operation. Populating global/national DND entries is an
operator path that does not exist yet (national DND sync is M2 with campaigns); until
it does, the `global` scope is read-only in practice, which is the safe direction.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '17a91a69dee9'
down_revision: str | None = 'fa06ed03b49d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('dnc_list',
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('phone_e164', sa.Text(), nullable=False),
    sa.Column('scope', sa.String(), server_default='tenant', nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(scope = 'global' AND tenant_id IS NULL) OR (scope = 'tenant' AND tenant_id IS NOT NULL)", name=op.f('ck_dnc_list_scope_matches_tenant')),
    sa.CheckConstraint("scope IN ('global', 'tenant')", name=op.f('ck_dnc_list_scope_enum')),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_dnc_list_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dnc_list')),
    sa.UniqueConstraint('tenant_id', 'phone_e164', name=op.f('uq_dnc_list_tenant_id_phone_e164'))
    )
    op.create_index(op.f('ix_dnc_list_phone_e164'), 'dnc_list', ['phone_e164'], unique=False)
    op.create_index(op.f('ix_dnc_list_tenant_id'), 'dnc_list', ['tenant_id'], unique=False)
    op.drop_index(op.f('ix_engine_agent_routes_tenant'), table_name='engine_agent_routes')


    # RLS: FORCE so even the table owner is subject to it (hard rule 1's pattern).
    op.execute("ALTER TABLE dnc_list ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dnc_list FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON dnc_list
            USING (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND scope = 'tenant'
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dnc_list")
    op.create_index(op.f('ix_engine_agent_routes_tenant'), 'engine_agent_routes', ['tenant_id', 'agent_id'], unique=False)
    op.drop_index(op.f('ix_dnc_list_tenant_id'), table_name='dnc_list')
    op.drop_index(op.f('ix_dnc_list_phone_e164'), table_name='dnc_list')
    op.drop_table('dnc_list')
