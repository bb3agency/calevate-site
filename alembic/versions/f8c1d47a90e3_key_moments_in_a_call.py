"""key moments in a call — the timestamps a client jumps to instead of re-listening

Revision ID: f8c1d47a90e3
Revises: c4b70e928a1f
Create Date: 2026-08-16 10:20:00.000000

A column on `call_extractions`, not a table of its own, and the choice is worth stating
because "add a table" is the reflex.

Moments are 1:1 with a call, and `call_extractions` already enforces exactly that —
`UNIQUE (tenant_id, call_id)`, added by `d3b71c9a5e08` for the same reason. Hanging them
here means they inherit the row's FORCEd `tenant_isolation` policy (hard rule 1 is
satisfied by construction rather than by a second policy somebody has to write correctly),
they are erased by the sweep that already erases the extraction, and they are read by a
query that is already being made. A `call_moments` table would need its own policy, its
own cross-tenant zero-rows test, its own erasure arm and its own retention clock — four
new places to get one guarantee wrong, for data that cannot outlive the row it hangs off.

WHAT THE COLUMN HOLDS. A JSON array; each element is

    {"at_ms": int, "kind": str, "label": str, "label_redacted": str, "source": str}

`kind` and `source` are closed sets defined in `apps/workers/moments.py` — not a CHECK
constraint, deliberately. A CHECK on JSONB array elements is a per-element subquery that
Postgres cannot use an index for, it fires on every write of the whole array, and its
failure message names a constraint rather than the field that was wrong. The set is
enforced where it is authored (a `Literal`, checked by mypy) and where it is read (the
response model, checked by Pydantic), which is the same two-sided pattern
`extraction_schemas.fields` already uses for the same shape of data.

NULL vs `[]` IS A REAL DISTINCTION and the column is nullable to keep it. NULL means
nobody has looked for moments in this call — every row that existed before this migration,
and every call whose extraction predates the feature. `[]` means we looked and the call
had none. The screen hides the panel for both, but an operator asking "why has this call
no key points" needs to know which, and a NOT NULL DEFAULT '[]' would erase the question
permanently on the day it was added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8c1d47a90e3"
down_revision: str | None = "c4b70e928a1f"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "call_extractions",
        sa.Column("moments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    # Reversible exactly, and losing the markers on the way down is correct rather than
    # unfortunate: they are DERIVED from the transcript and the extraction, both of which
    # survive, so a re-upgrade plus a re-run of the pipeline reconstructs them. Nothing
    # here is a record of something that happened (hard rule 4's concern) — it is an index
    # into something that is still on disk.
    op.drop_column("call_extractions", "moments")
