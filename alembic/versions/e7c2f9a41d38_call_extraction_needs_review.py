"""call_extractions.needs_review — per-field, PII-free "confirm before acting" advisories

Revision ID: e7c2f9a41d38
Revises: d4a83f06c1e7
Create Date: 2026-08-28 00:00:00.000000

Lead-extraction quality round (P4). The extractor already records two per-field facts about
one call — the values it captured (`data`) and the fields it could not use at all
(`errors`, which drives `valid`). It had no way to say the third thing: a field it DID
capture but that a human should glance at before acting on. The first producer is a
dial-critical field — a phone whose captured value is not a standard Indian mobile, the
number an SMB will actually ring off this record — but the column is the general shape
(`validate_extraction` fills it, `ExtractionOutput.needs_review` carries it).

It is DELIBERATELY NOT folded into `errors`: `valid = not errors`, so a needs-review field
must not read as an invalid extraction — it is stored and usable, it just carries a
deterministic doubt. Same JSONB shape as `errors` (`{field_key: reason}`), nullable, and the
reason strings are PII-FREE by construction (the value they concern lives in `data`, and
hard rule 6 keeps digits out of anything that might be logged).

Nullable, no default: NULL is "this row predates the column / nobody computed it", `{}` is
"computed, nothing to flag" — the same distinction `moments` draws on the same table, and
the reason `_persist_extraction` writes NULL rather than `{}` when it has nothing to say.

`call_extractions` is tenant-scoped with FORCEd RLS already; adding a column touches no
policy. It is NOT append-only (the row is upserted once per call, `ON CONFLICT
(tenant_id, call_id)`), so there is no mutation trigger to teach about the new column.

**Locking.** One `ADD COLUMN` of a nullable column with no default — a catalog-only change
that takes no table rewrite and no row lock beyond the brief `ACCESS EXCLUSIVE` to edit the
catalog. `lock_timeout` bounds even that.

**Downgrade** drops the column, discarding any advisories computed since. Recoverable by
re-running extraction, which recomputes `needs_review` from `data` and the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c2f9a41d38"
down_revision: str | None = "d4a83f06c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "call_extractions",
        # JSONB to match `errors`/`data`/`moments` on this table, so one reader shape covers
        # every per-field map the row carries.
        sa.Column("needs_review", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("call_extractions", "needs_review")
