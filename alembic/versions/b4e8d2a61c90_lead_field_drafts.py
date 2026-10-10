"""a custom business's one AI draft of its lead fields (founder decision 15)

Revision ID: b4e8d2a61c90
Revises: e5a1d706c3f2
Create Date: 2026-10-10 18:00:00.000000

Every lead now carries a fixed core (`calevate_shared.lead_fields`, composed in on read and
never stored) plus the business's own fields. For a business that fits no known type, those
fields are drafted ONCE by AI from what the platform knows about it, and are the client's to
edit from then on.

`lead_field_drafts` holds that one draft per client: `UNIQUE(tenant_id)` is the "never
again" rule, so a second draft has no row to live in. A failed draft produced nothing and
the same row moves back to `queued` when asked again. Tenant data (the client's own
business details turned into field definitions), so it carries `tenant_id` and the FORCEd
`tenant_isolation` policy (hard rule 1).

No existing row is touched: agents' stored fields stay exactly as they are, and the core is
added by the readers. Downgrade drops the table and its policy; nothing else depends on it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4e8d2a61c90"
down_revision: str | None = "e5a1d706c3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "lead_field_drafts"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            "fields IS NULL OR jsonb_typeof(fields) = 'array'",
            name=op.f(f"ck_{TABLE}_fields_is_array"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_lead_field_drafts_tenant"),
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
