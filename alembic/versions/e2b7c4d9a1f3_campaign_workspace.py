"""A campaign owns its main task, materials and script; the agent is the voice (D-992)

Revision ID: e2b7c4d9a1f3
Revises: d7f3a9c1e5b2
Create Date: 2026-11-15 12:00:00.000000

* `campaigns.main_task`: what the campaign should achieve, in the owner's words.
* `campaigns.script`: the campaign's own call script (a `CallScript` as JSON), put live on the
  campaign's agent at Start.
* `campaigns.script_proposal`: Pip's pending draft of that script.
* `campaigns.script_live_version`: the agent script version the last Start put live.
* `campaign_materials`: the documents, links and notes a campaign works from, including notes
  learned from its own calls. Tenant data, FORCEd RLS in this migration (hard rule 1).

All additive. `downgrade()` drops the table and the four columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2b7c4d9a1f3"
down_revision: str | None = "d7f3a9c1e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MATERIALS = "campaign_materials"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
_KINDS = ("file", "link", "note")
_SOURCES = ("owner", "call")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("main_task", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("script", postgresql.JSONB(), nullable=True))
    op.add_column("campaigns", sa.Column("script_proposal", postgresql.JSONB(), nullable=True))
    op.add_column("campaigns", sa.Column("script_live_version", sa.Integer(), nullable=True))

    op.create_table(
        MATERIALS,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="owner"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "kb_upload_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("kb_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(_in("kind", _KINDS), name=op.f(f"ck_{MATERIALS}_kind_enum")),
        sa.CheckConstraint(_in("source", _SOURCES), name=op.f(f"ck_{MATERIALS}_source_enum")),
    )
    op.create_index(f"ix_{MATERIALS}_tenant_id", MATERIALS, ["tenant_id"])
    op.create_index(f"ix_{MATERIALS}_campaign", MATERIALS, ["campaign_id", "created_at"])
    op.execute(f"ALTER TABLE {MATERIALS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {MATERIALS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {MATERIALS} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(MATERIALS)
    op.drop_column("campaigns", "script_live_version")
    op.drop_column("campaigns", "script_proposal")
    op.drop_column("campaigns", "script")
    op.drop_column("campaigns", "main_task")
