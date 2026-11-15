"""Every client has one company training, the same for every agent (founder, 16 Nov 2026)

Revision ID: c6a4f2e8d1b7
Revises: b3d8e1f6a2c9
Create Date: 2026-11-16 12:00:00.000000

* `company_trainings`: one row per client. The owner's overview in their own words, the
  training every agent of the client is given (composed into each agent's script by
  `agents/company_training.with_training`), Pip's pending draft of it, and a version that
  moves on every save.
* `company_training_materials`: the documents, links and notes the training is written
  from. A file is a knowledge upload (`kb_upload_id`), so agents can also look it up.

Both are tenant data with FORCEd RLS in this migration (hard rule 1). All additive;
`downgrade()` drops both tables.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6a4f2e8d1b7"
down_revision: str | None = "b3d8e1f6a2c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRAININGS = "company_trainings"
MATERIALS = "company_training_materials"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: FROZEN COPY, not an import: a migration keeps meaning what it meant on the day it ran.
_KINDS = ("file", "link", "note")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    ]


def _tenant() -> sa.Column[object]:
    return sa.Column(
        "tenant_id",
        sa.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {table} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TRAININGS,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("training", sa.Text(), nullable=True),
        sa.Column("proposal", postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", name=op.f(f"uq_{TRAININGS}_tenant_id")),
    )
    _isolate(TRAININGS)

    op.create_table(
        MATERIALS,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("kind", sa.String(8), nullable=False),
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
        *_timestamps(),
        sa.CheckConstraint(_in("kind", _KINDS), name=op.f(f"ck_{MATERIALS}_kind_enum")),
    )
    op.create_index(f"ix_{MATERIALS}_tenant_id", MATERIALS, ["tenant_id", "created_at"])
    _isolate(MATERIALS)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(MATERIALS)
    op.drop_table(TRAININGS)
