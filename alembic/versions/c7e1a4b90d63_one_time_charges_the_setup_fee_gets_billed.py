"""one_time_charges: the setup fee gets billed (D-63)

Revision ID: c7e1a4b90d63
Revises: c7e4b19d3f52
Create Date: 2026-08-14

`plans.setup_fee` has been a column nothing reads since the first migration
(05bba2f3c19c) — the onboarding fee was quoted in a message and collected out of band,
which `scripts/check_wiring.py::UNWIRED_BASELINE` recorded verbatim. This table is what
lets the invoice bill it.

WHY A TABLE AND NOT A FLAG ON `plans`
------------------------------------
An invoice in this product is a DERIVED statement (`apps/api/billing/invoice.py`),
recomputed from the ledgers every time it is rendered. So "the setup fee is charged on
the first invoice and never again" has to be a durable FACT the render re-reads, not a
side effect of the render. A boolean on `plans` would move with the plan row — a plan
change, or a re-onboarding, would present a fresh unbilled flag — and would be an UPDATE
on the path hard rule 4 keeps ledgers clear of.

`ux_one_time_charges_tenant_kind_ref` is the whole idempotency argument: the writer does
an unconditional `INSERT … ON CONFLICT DO NOTHING`, so two concurrent invoice
generations cannot both append (the second blocks on the index entry, then writes
nothing) and no `WHERE NOT EXISTS` read-then-write exists to lose a race
(BACKEND-PATTERNS §5). `ref` is part of the key so a reversal remains possible as a NEW
row with a negative amount under its own ref — hard rule 4's compensating entry — rather
than as an edit.

`billing_month` is stored rather than derived from `occurred_at`: the fee belongs to the
tenant's onboarding month, while `occurred_at` is the (possibly much later) moment that
month's statement was first rendered.

Reversible (hard rule 8): the table is new, nothing backfills, and `downgrade` drops it
whole — no client's bill changes on the day this lands, because a tenant is only charged
once an invoice for their onboarding month is rendered against a plan quoting a fee.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c7e1a4b90d63'
down_revision: str | None = 'c7e4b19d3f52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'one_time_charges',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('ref', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('billing_month', sa.Text(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('setup_fee')", name=op.f('ck_one_time_charges_kind_enum')),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], name=op.f('fk_one_time_charges_tenant_id_organizations'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_one_time_charges_plan_id_plans'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_one_time_charges')),
    )

    # ONCE, in the database. `ON CONFLICT (tenant_id, kind, ref) DO NOTHING` names this
    # index by its columns, so it is not optional decoration: without it the writer's
    # conflict target does not exist and every insert errors.
    op.create_index(
        'ux_one_time_charges_tenant_kind_ref',
        'one_time_charges',
        ['tenant_id', 'kind', 'ref'],
        unique=True,
    )
    # The invoice's read: one tenant, one billing month.
    op.create_index(
        'ix_one_time_charges_tenant_month', 'one_time_charges', ['tenant_id', 'billing_month']
    )

    # Tenant isolation (DATA-MODEL §1) + FORCE so the owner role is subject to it. No
    # WITH CHECK clause: for a FOR ALL policy Postgres reuses the USING expression as
    # the write check, so a session cannot insert a charge for a tenant it cannot read.
    op.execute("ALTER TABLE one_time_charges ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE one_time_charges FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON one_time_charges USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # Append-only (hard rule 4), reusing the function migration 05bba2f3c19c created.
    # A charge that was wrong is reversed by a second row, never rewritten.
    op.execute(
        "CREATE TRIGGER one_time_charges_append_only "
        "BEFORE UPDATE OR DELETE ON one_time_charges "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS one_time_charges_append_only ON one_time_charges")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON one_time_charges")
    op.drop_index('ix_one_time_charges_tenant_month', table_name='one_time_charges')
    op.drop_index('ux_one_time_charges_tenant_kind_ref', table_name='one_time_charges')
    op.drop_table('one_time_charges')
