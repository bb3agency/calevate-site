"""credit_ledger + organizations.plan_tier (D-39: schema for scale)

Revision ID: f170dbce6f47
Revises: 842ba923796d
Create Date: 2026-08-10

D-39's rule of thumb: **anything that would require a migration or a re-meter later is
built now; anything that is only a screen is built when a user needs it.** The
self-serve top-up UI is M2 (D-34); these two pieces of schema are M1, because D-12
already established that metering is not retrofittable and D-34 established that a
self-serve org must be the SAME `organizations` row as a managed one.

`credit_ledger` is append-only like the other ledgers (hard rule 4): a refund is a new
entry, never an edit. `balance_after` is denormalized deliberately — a running balance
summed from `delta` makes every pre-dispatch check a full-table aggregate, and one bad
row silently shifts every balance after it. Storing it makes each entry a self-contained
assertion that can be checked against its predecessor.

`plan_tier` defaults to `managed`, which is client #1's path, so existing rows need no
backfill and nothing changes behaviour today.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f170dbce6f47'
down_revision: str | None = '842ba923796d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('credit_ledger',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('delta', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('ref', sa.Text(), nullable=True),
    sa.Column('balance_after', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("reason IN ('topup', 'usage', 'adjustment', 'refund')", name=op.f('ck_credit_ledger_reason_enum')),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_credit_ledger_tenant_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_ledger'))
    )
    op.create_index(op.f('ix_credit_ledger_tenant_id'), 'credit_ledger', ['tenant_id'], unique=False)
    op.add_column('organizations', sa.Column('plan_tier', sa.String(), server_default='managed', nullable=False))

    # Tenant isolation (DATA-MODEL §1) + FORCE so the owner role is subject to it.
    op.execute("ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON credit_ledger USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # Append-only (hard rule 4), reusing the function migration 05bba2f3c19c created.
    op.execute(
        "CREATE TRIGGER credit_ledger_append_only "
        "BEFORE UPDATE OR DELETE ON credit_ledger "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )

    # The balance read on every pre-dispatch check: newest entry per tenant.
    op.create_index(
        "ix_credit_ledger_tenant_recent",
        "credit_ledger",
        ["tenant_id", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS credit_ledger_append_only ON credit_ledger")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON credit_ledger")
    op.drop_index("ix_credit_ledger_tenant_recent", table_name="credit_ledger")
    op.drop_column('organizations', 'plan_tier')
    op.drop_index(op.f('ix_credit_ledger_tenant_id'), table_name='credit_ledger')
    op.drop_table('credit_ledger')
