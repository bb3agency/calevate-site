"""lead_notes: what the team writes on a lead or one of its calls (W7.2)

Revision ID: b6d2f8a4c1e7
Revises: c7d3a9e5f218
Create Date: 2026-11-28

A person's free-text note on a lead, optionally written from one of its calls. The words live
here and not in `lead_events.payload`, whose erasure exemption rests on no producer writing
prose there; the timeline row a note writes names only this row's id. Both erasures and the
lead retention clock delete these rows (`apps/workers/retention.py`).

Tenant data, so the table ships with FORCEd `tenant_isolation` (hard rule 1); the cross-tenant
zero-rows proof is `tests/lead_notes_test.py`. No DML, so no NO FORCE / FORCE bracket.
Reversible: `downgrade()` drops the policy, the indexes and the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f8a4c1e7"
down_revision: str | Sequence[str] | None = "c7d3a9e5f218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "lead_notes"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f(f"fk_{TABLE}_lead_id_leads"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f(f"fk_{TABLE}_call_id_calls"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f(f"fk_{TABLE}_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 2000", name=op.f(f"ck_{TABLE}_body_length")
        ),
        sa.CheckConstraint("version >= 1", name=op.f(f"ck_{TABLE}_version_positive")),
    )
    op.create_index(op.f(f"ix_{TABLE}_tenant_id"), TABLE, ["tenant_id"])
    op.create_index("ix_lead_notes_lead_recent", TABLE, ["lead_id", "created_at"])
    op.create_index(
        "ix_lead_notes_call",
        TABLE,
        ["call_id"],
        postgresql_where=sa.text("call_id IS NOT NULL"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_lead_notes_call", table_name=TABLE)
    op.drop_index("ix_lead_notes_lead_recent", table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
