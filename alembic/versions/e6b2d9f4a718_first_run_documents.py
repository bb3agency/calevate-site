"""the documents a new owner adds on the first run's brief step (D-918)

The owner can add up to three files beside (or instead of) typing the brief. Each one is an
ordinary knowledge upload (`POST /v1/kb/uploads`, `kb_uploads`): same formats, limits, review
and OCR metering, and part of what every agent knows (D-689). `first_runs.document_ids` only
records which uploads are this run's documents, so the question and script writers can read
their text.

An id array on the one row rather than a join table: the row is already tenant-scoped with a
FORCEd policy, the list holds three ids at most, and every read joins `kb_uploads` under RLS,
so an id whose upload was removed on the knowledge screen simply stops counting. A join table
with a foreign key would cascade that removal too, at the price of a new tenant table, its
policy and its registries for a three-item list.

Downgrade drops the column: the uploads stay in the knowledge base, only the record of which
ones the first run used is lost.

Revision ID: e6b2d9f4a718
Revises: d4a7c3e91f26
Create Date: 2026-10-28 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e6b2d9f4a718"
down_revision: str | None = "d4a7c3e91f26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "first_runs"
#: `first_run/models.MAX_DOCUMENTS`, spelled here because a migration must not import
#: application code that will change after it.
_MAX_DOCUMENTS = 3


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        TABLE,
        sa.Column(
            "document_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_document_ids_bounded"),
        TABLE,
        f"cardinality(document_ids) <= {_MAX_DOCUMENTS}",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(f"ck_{TABLE}_document_ids_bounded"), TABLE, type_="check")
    op.drop_column(TABLE, "document_ids")
