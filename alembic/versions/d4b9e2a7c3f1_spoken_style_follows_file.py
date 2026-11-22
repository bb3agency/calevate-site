"""An approval of a spoken-style entry's file words follows the file (D-1032)

Revision ID: d4b9e2a7c3f1
Revises: f3b8d2a6c1e4
Create Date: 2026-11-23 01:30:00.000000

* `spoken_style_revisions.follows_file`: true on an approval of words nobody edited. The
  file's current value is then in force (`calevate_shared.spoken_style.in_force`) and
  `value` keeps the text that was approved, so the approval lapses when the file changes.
  Before this, approving copied the file's words into the revision, and publishing froze
  that copy over every later correction to the file.
* Compensating rows (the table is append-only, hard rule 4): for each entry whose
  revisions are ALL plain approvals by the audit log, one new revision with the same value,
  approved, `follows_file = true`. An entry with any edit, addition or retirement keeps its
  revisions as they are: those words are the reviewer's own. The rows sit after the latest
  publication, so they reach agents when the language is next published.

`downgrade()` drops the column; the compensating rows then read as approvals of the text
they carry, which is what the rows before them already said.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b9e2a7c3f1"
down_revision: str | None = "f3b8d2a6c1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "spoken_style_revisions"

_COMPENSATE = """
INSERT INTO spoken_style_revisions
    (language, kind, entry_key, value, approved, created_by, follows_file)
SELECT l.language, l.kind, l.entry_key, l.value, true, l.created_by, true
FROM (
    SELECT DISTINCT ON (language, kind, entry_key) *
    FROM spoken_style_revisions
    ORDER BY language, kind, entry_key, seq DESC
) l
WHERE l.approved AND l.value IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM spoken_style_revisions r
    LEFT JOIN audit_log a
      ON a.object_type = 'spoken_style_revisions' AND a.object_id = r.seq::text
    WHERE r.language = l.language AND r.kind = l.kind AND r.entry_key = l.entry_key
      AND (a.action IS NULL OR a.action <> 'platform.spoken_style_approve')
  )
ORDER BY l.seq
"""


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("follows_file", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(_COMPENSATE)


def downgrade() -> None:
    op.drop_column(TABLE, "follows_file")
