"""copilot_notes: what Pip noticed in an account and said on its own (D-936)

Revision ID: e5b9d3f7a248
Revises: d9e2b4f7a160
Create Date: 2026-10-29 16:00:00.000000

One row per episode of something Pip's hourly detectors noticed (`copilot/notes.py`): a hot
lead nobody called back, credit forecast to run out, one unanswered question asked again and
again, a good week. Tenant data, so the table ships with FORCEd `tenant_isolation` here (hard
rule 1); the cross-tenant zero-rows proof is `tests/pip_notes_test.py`. The payload holds ids
and counts only. No DML, so no NO FORCE / FORCE bracket. Reversible: `downgrade()` drops the
policy, the indexes and the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b9d3f7a248"
down_revision: str | None = "d9e2b4f7a160"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "copilot_notes"
_KINDS = "'hot_lead_waiting', 'balance_runway', 'knowledge_gap_repeat', 'good_week'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("episode_key", sa.String(length=96), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", sa.UUID(), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            ["dismissed_by"],
            ["users.id"],
            name=op.f(f"fk_{TABLE}_dismissed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name=op.f(f"ck_{TABLE}_kind_enum")),
        sa.CheckConstraint(
            "length(subject) BETWEEN 1 AND 64", name=op.f(f"ck_{TABLE}_subject_length")
        ),
        sa.CheckConstraint(
            "length(episode_key) BETWEEN 1 AND 96", name=op.f(f"ck_{TABLE}_episode_key_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f(f"ck_{TABLE}_payload_is_object")
        ),
        sa.UniqueConstraint(
            "tenant_id", "kind", "episode_key", name=op.f(f"uq_{TABLE}_tenant_id_kind_episode_key")
        ),
    )
    # One open note per (kind, subject): the dedupe the detectors' INSERT ... ON CONFLICT uses.
    op.create_index(
        "uq_copilot_notes_open_subject",
        TABLE,
        ["tenant_id", "kind", "subject"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    # The panel's read (newest first) and the daily cap's count (created today).
    op.create_index("ix_copilot_notes_tenant_recent", TABLE, ["tenant_id", "created_at"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_copilot_notes_tenant_recent", table_name=TABLE)
    op.drop_index("uq_copilot_notes_open_subject", table_name=TABLE)
    op.drop_table(TABLE)
