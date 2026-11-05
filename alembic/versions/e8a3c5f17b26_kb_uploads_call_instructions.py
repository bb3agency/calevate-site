"""a text upload keeps its call instructions apart from its facts, and says which reading made it

Revision ID: e8a3c5f17b26
Revises: a7d3e9c1f570
Create Date: 2026-11-05 12:00:00.000000

`call_instructions`: what a Markdown guide tells the agent to DO on a call ("ask whether now is
a good time"), read out of the file by `kb/structured_text.py` and kept off the knowledge the
engine searches, for the owner to put into a call script. A JSON list of
`{"section": str | null, "text": str}`; NULL for an upload read before this column or with
nothing of the kind.

`text_parser`: the `structured_text.PARSER_VERSION` that read a text upload, so the sweep
re-reads one read by an older version (NULL: read before there was a version).

Both are columns of `kb_uploads`, whose FORCEd tenant policy already covers them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a3c5f17b26"
down_revision: str | None = "a7d3e9c1f570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "kb_uploads",
        sa.Column("call_instructions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("kb_uploads", sa.Column("text_parser", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_kb_uploads_call_instructions_is_array"),
        "kb_uploads",
        "call_instructions IS NULL OR jsonb_typeof(call_instructions) = 'array'",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_kb_uploads_call_instructions_is_array"), "kb_uploads", type_="check"
    )
    op.drop_column("kb_uploads", "text_parser")
    op.drop_column("kb_uploads", "call_instructions")
