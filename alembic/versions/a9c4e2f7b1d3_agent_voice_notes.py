"""How an agent should sound, taught line by line (founder, 17 Nov 2026)

Revision ID: a9c4e2f7b1d3
Revises: f5c1a8d3e7b2
Create Date: 2026-11-17 12:00:00.000000

`agent_voice_notes`: the notes an owner wrote after hearing a line in the agent's voice
("slower", "say Rytu Khata as ..."), kept on the agent so every call it makes (its own, its
campaigns', its lines') follows them (`apps/api/agents/voice_notes.py`). A note is retired,
never deleted (`retired_at`). A tenant table, so FORCEd `tenant_isolation` in this migration
(hard rule 1); the cross-tenant zero-rows proof is `tests/agent_voice_notes_test.py`.
Reversible: the downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e2f7b1d3"
down_revision: str | None = "f5c1a8d3e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_voice_notes"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("language", sa.Text(), server_default="", nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(note) BETWEEN 1 AND 300", name=op.f("ck_agent_voice_notes_note_length")
        ),
        sa.CheckConstraint(
            "char_length(language) <= 10", name=op.f("ck_agent_voice_notes_language_length")
        ),
        sa.CheckConstraint(
            "char_length(source) <= 200", name=op.f("ck_agent_voice_notes_source_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_agent_voice_notes_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_voice_notes_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_voice_notes")),
    )
    op.create_index(op.f("ix_agent_voice_notes_tenant_id"), TABLE, ["tenant_id"])
    op.create_index("ix_agent_voice_notes_agent_active", TABLE, ["agent_id", "created_at"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_agent_voice_notes_agent_active", table_name=TABLE)
    op.drop_index(op.f("ix_agent_voice_notes_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
