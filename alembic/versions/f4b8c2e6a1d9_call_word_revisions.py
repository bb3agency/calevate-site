"""call_word_revisions: the founder edits the words the call checks listen for

Revision ID: f4b8c2e6a1d9
Revises: d3a9f5c1e7b4
Create Date: 2026-11-06 00:00:00.000000

G-C2. The words the call checks listen for (`calevate_shared/call_words.json`) become
editable on Ops > Call words. Each save is a row here; the newest row per `entry_key` is
layered over the file, and a NULL `value` puts the shipped entry back.

Platform-scoped (the words belong to no tenant, so no `tenant_id` and no policy) and
append-only with the shared `calevate_forbid_mutation` and `calevate_forbid_truncate`
triggers, `ENABLE ALWAYS`, for `spoken_style_revisions`' reason: the history is the record of
who changed which list, and a change is a new row rather than an edit.

Locking: one `CREATE TABLE`, one index, two triggers on the new table; nothing existing is
touched. Downgrade drops the table and loses the edit history; every process falls back to
the shipped file at its next refresh.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4b8c2e6a1d9"
down_revision: str | None = "d3a9f5c1e7b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "call_word_revisions"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        _TABLE,
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(note) <= 300", name=op.f("ck_call_word_revisions_note_length")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.id"],
            name=op.f("fk_call_word_revisions_created_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_call_word_revisions")),
    )
    op.create_index(
        "ix_call_word_revisions_entry", _TABLE, ["entry_key", sa.text("seq DESC")]
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_append_only BEFORE UPDATE OR DELETE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_forbid_truncate BEFORE TRUNCATE ON {_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_append_only")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_forbid_truncate ON {_TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_append_only ON {_TABLE}")
    op.drop_index("ix_call_word_revisions_entry", table_name=_TABLE)
    op.drop_table(_TABLE)
