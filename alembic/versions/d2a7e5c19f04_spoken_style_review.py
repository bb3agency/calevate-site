"""spoken_style_revisions and spoken_style_publications: the founder's spoken-style review

Revision ID: d2a7e5c19f04
Revises: c4f7a2e9d1b6
Create Date: 2026-10-11 00:00:00.000000

D-744. The founder reviews the spoken-style table (`calevate_shared/spoken_style.json`) on
the admin screen Ops > Spoken style. Each approve, edit, add or retire is a row in
`spoken_style_revisions`; publishing a language is a row in `spoken_style_publications`
that takes every revision of that language up to `through_revision`. What prompts read is
the file with the latest publication's revisions layered over it.

Both tables are platform-scoped (how the platform speaks a language belongs to no tenant,
so no `tenant_id` and no policy) and append-only with the shared `calevate_forbid_mutation`
and `calevate_forbid_truncate` triggers, `ENABLE ALWAYS`: the history is the record of who
approved which words, and a change is a new revision rather than an edit.

Locking: two `CREATE TABLE`s, two indexes, four triggers on the new tables; nothing existing
is touched. Downgrade drops both tables and loses the review history; agents fall back to
the file's words at their next publish.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2a7e5c19f04"
down_revision: str | None = "c4f7a2e9d1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("spoken_style_revisions", "spoken_style_publications")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "spoken_style_revisions",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('register', 'swap', 'filler', 'number_rule', 'punctuation', "
            "'example', 'opening')",
            name=op.f("ck_spoken_style_revisions_kind_known"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.id"],
            name=op.f("fk_spoken_style_revisions_created_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_spoken_style_revisions")),
    )
    op.create_index(
        "ix_spoken_style_revisions_entry",
        "spoken_style_revisions",
        ["language", "kind", "entry_key", sa.text("seq DESC")],
    )
    op.create_table(
        "spoken_style_publications",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("through_revision", sa.BigInteger(), nullable=False),
        sa.Column("reviewer_name", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["admin_users.id"],
            name=op.f("fk_spoken_style_publications_published_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_spoken_style_publications")),
    )
    op.create_index(
        "ix_spoken_style_publications_language",
        "spoken_style_publications",
        ["language", sa.text("seq DESC")],
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_forbid_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_append_only")
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_index("ix_spoken_style_publications_language", table_name="spoken_style_publications")
    op.drop_table("spoken_style_publications")
    op.drop_index("ix_spoken_style_revisions_entry", table_name="spoken_style_revisions")
    op.drop_table("spoken_style_revisions")
