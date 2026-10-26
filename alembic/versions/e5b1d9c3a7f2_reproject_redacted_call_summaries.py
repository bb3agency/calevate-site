"""re-project call summaries now that their projection is redacted

Revision ID: e5b1d9c3a7f2
Revises: c8a4e2f7b913
Create Date: 2026-10-26 14:00:00.000000

`calls.summary` is stored unredacted, and until `retrieval/call_projection.project_summary`
redacted it, every `call_summary` row in `caller_chunks` was built from the raw text: its
`tsv` holds the lexemes of any number a caller dictated and its vector was bought on it.
The discovery statement re-projects a call only when no row of that kind exists or the
call changed after it, so a code fix alone leaves those rows as they are.

Deleting the live summary rows is the re-projection: the next sweep finds each call
without one and writes it again from the redacted text. They are a derived copy with no
content of their own. Tombstoned rows (`scrubbed_at` set by an erasure or retention) are
kept, because deleting a tombstone is what would let an erased call be projected again.

The raw rows cannot be restored and must not be. The downgrade runs the same delete, so
the code running after it rebuilds the summary rows under its own projection rule rather
than holding rows whose `content_sha256` that code would never have written.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5b1d9c3a7f2"
down_revision: str | None = "c8a4e2f7b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_live_summary_projections() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The FORCE bracket: `caller_chunks` is FORCE-RLS'd, so the migration role sees no rows
    # without it.
    op.execute("ALTER TABLE caller_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM caller_chunks WHERE subject_kind = 'call_summary' AND scrubbed_at IS NULL"
    )
    op.execute("ALTER TABLE caller_chunks FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _drop_live_summary_projections()


def downgrade() -> None:
    _drop_live_summary_projections()
