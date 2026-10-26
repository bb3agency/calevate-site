"""a PDF or a link holds a readable copy of its words, with its own reading state (D-893 L8)

Revision ID: f2b7d4e9a1c6
Revises: e5c1a9d3f720
Create Date: 2026-10-26 20:00:00.000000

A PDF and a link used to keep no text of ours: the ingest job skipped them, so their words
existed nowhere on our side and neither the client's reader nor Pip could open or search
them. The text now goes where every other upload's text goes (`kb_documents`, one row per
chunk, `meta.page` for a PDF page). These three columns say how that reading went, apart
from `ingest_status`: a PDF reaches the voice platform as its file whether or not its words
could be read, so "published" and "read" are separate facts and one column cannot hold both.

`read_state` is NULL for every kind the conversion lane reads (their `ingest_status` already
says it) and for a PDF or link not read yet. `read_detail` is a sentence written for the
client, never a key or a stack. `page_count` is the PDF's page count.

No RLS change: `kb_uploads`' tenant policy covers every column. No backfill: the rows are
re-read by `scripts/read_saved_files.py`, dry run first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b7d4e9a1c6"
down_revision: str | None = "e5c1a9d3f720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("kb_uploads", sa.Column("read_state", sa.Text(), nullable=True))
    op.add_column("kb_uploads", sa.Column("read_detail", sa.Text(), nullable=True))
    op.add_column("kb_uploads", sa.Column("page_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_kb_uploads_read_state"),
        "kb_uploads",
        "read_state IS NULL OR read_state IN ('reading', 'ready', 'failed')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_kb_uploads_read_state"), "kb_uploads", type_="check")
    op.drop_column("kb_uploads", "page_count")
    op.drop_column("kb_uploads", "read_detail")
    op.drop_column("kb_uploads", "read_state")
