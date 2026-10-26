"""the guided questions' decisions and drafted answers (D-893 lane L5)

`teach_questions` holds one row per question an account was asked to answer (a knowledge-gap
topic key such as `pricing`): whether the owner answered or dismissed a question that no open
knowledge gap carries (a practice-caller or setup question), and the answer Pip drafted from
what the business already gave us, with the fingerprint of those inputs so the draft is
written again only when they change. The list itself is computed on every read
(`apps/api/teach/questions.py`).

Tenant data, so `tenant_id` and the FORCEd `tenant_isolation` policy ship here (hard rule 1);
the cross-tenant zero-rows proof is `tests/teach_questions_test.py`. Tenant erasure deletes
the rows (`workers/retention.execute_tenant_erasure`). Nothing here holds a caller's words:
the key is a topic, a draft is written from the business's own profile, facts, earlier
answers and files, and a dismissal reason is the owner's note.

Downgrade drops the table and its policy: settled practice and setup questions come back and
drafts are written again.

Revision ID: f2a6c8e1d5b9
Revises: e5c1a9d3f720
Create Date: 2026-10-26 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a6c8e1d5b9"
down_revision: str | None = "e5c1a9d3f720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "teach_questions"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

# `teach/models.py`'s tuples, spelled here because a migration must not import application
# code that will change after it.
_DRAFT_STATUSES = ("queued", "ready", "none")
_SOURCE_KINDS = ("profile", "fact", "answer", "file")
_SETTLED = ("answered", "dismissed")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("question_key", sa.Text(), nullable=False),
        sa.Column("inputs_hash", sa.Text(), nullable=True),
        sa.Column("draft_status", sa.Text(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=True),
        sa.Column("draft_source_kind", sa.Text(), nullable=True),
        sa.Column("draft_source_label", sa.Text(), nullable=True),
        sa.Column("settled", sa.Text(), nullable=True),
        sa.Column("settled_reason", sa.Text(), nullable=True),
        sa.Column("settled_by", sa.UUID(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(question_key) BETWEEN 1 AND 120",
            name=op.f(f"ck_{TABLE}_question_key_length"),
        ),
        sa.CheckConstraint(
            f"draft_status IS NULL OR draft_status IN {_DRAFT_STATUSES!r}",
            name=op.f(f"ck_{TABLE}_draft_status_enum"),
        ),
        sa.CheckConstraint(
            f"draft_source_kind IS NULL OR draft_source_kind IN {_SOURCE_KINDS!r}",
            name=op.f(f"ck_{TABLE}_draft_source_kind_enum"),
        ),
        sa.CheckConstraint(
            "(draft IS NULL) = (draft_source_kind IS NULL)",
            name=op.f(f"ck_{TABLE}_draft_has_source"),
        ),
        sa.CheckConstraint(
            "draft IS NULL OR char_length(draft) BETWEEN 1 AND 500",
            name=op.f(f"ck_{TABLE}_draft_length"),
        ),
        sa.CheckConstraint(
            "inputs_hash IS NULL OR inputs_hash ~ '^[0-9a-f]{64}$'",
            name=op.f(f"ck_{TABLE}_inputs_hash_hex"),
        ),
        sa.CheckConstraint(
            f"settled IS NULL OR settled IN {_SETTLED!r}", name=op.f(f"ck_{TABLE}_settled_enum")
        ),
        sa.CheckConstraint(
            "(settled IS NULL) = (settled_at IS NULL)", name=op.f(f"ck_{TABLE}_settled_pair")
        ),
        sa.CheckConstraint(
            "settled_reason IS NULL OR char_length(settled_reason) <= 300",
            name=op.f(f"ck_{TABLE}_settled_reason_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "question_key", name=op.f(f"uq_{TABLE}_tenant_id_question_key")
        ),
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
