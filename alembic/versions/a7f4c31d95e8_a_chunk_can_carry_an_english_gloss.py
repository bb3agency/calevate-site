"""a chunk can carry an english gloss

Revision ID: a7f4c31d95e8
Revises: d4a9c17e6b02
Create Date: 2026-09-01 00:00:00.000000

Three nullable/defaulted columns on `kb_documents`, so that an approved Telugu-script chunk
can carry a short ENGLISH rendering beside its original text:

* `gloss`        — the English rendering. NULL when there is none.
* `gloss_state`  — `pending` / `ready` / `not_needed`, from `kb/gloss.GLOSS_STATES`.
* `gloss_model`  — which model wrote it, for provenance. NULL when no model did.

--------------------------------------------------------------------------------
WHY THIS SHIPS NOW AND NOT WHEN THE PROVIDER IS CHOSEN
--------------------------------------------------------------------------------
`docs/evidence/telugu-embedding-quality.md` measured retrieval on this repo's own seeded
verticals (n=24): a Tenglish question — the form Sarvam's Saaras STT actually returns —
scored recall@1 **0.250** against a Telugu-script corpus, where the English control on the
same facts scored 0.958. Storing the fact in English as well took that cell to **0.750**.
The gloss is written ONCE per chunk at ingestion, so adding it later means re-ingesting
every client's knowledge base. There are no clients yet. That is the entire timing argument.

It is also provider-independent, which is what lets it precede the D-28 bake-off: this is
our own stored TEXT, in our own table, with no embedding, no vector, no index shape and no
vendor. Whichever store wins, the English rendering is the thing that gets given to it.

--------------------------------------------------------------------------------
WHY THREE STATES AND NOT `gloss IS NULL`
--------------------------------------------------------------------------------
"No gloss" has two causes that must not be confused. A chunk nobody has processed yet, and
an ENGLISH chunk that was processed and correctly needs nothing. A sweep keyed on
`gloss IS NULL` would re-select every English chunk on every tick, forever, re-paying a
model call to arrive at the same "no". `gloss_state` is the idempotency key of
`workers/kb_gloss.py`, which is why it is a column and not an inference.

`server_default='pending'` therefore applies to existing rows as well, and that is correct
rather than incidental: a row written before this migration has not been looked at either,
and the sweep is exactly what should look at it. The CHECK constraint renders
`GLOSS_STATES` verbatim, the shape `kb_sources.status` and `retention_worklist.reason`
already use — a closed vocabulary that keeps the table self-describing.

--------------------------------------------------------------------------------
THE PARTIAL INDEX
--------------------------------------------------------------------------------
The sweep's only query is "chunks of this tenant still pending". Once the fleet is glossed
that predicate matches nothing, and a partial index is the difference between a catalogue
lookup and a full scan of every chunk every tick. Partial on `gloss_state = 'pending'` so
the index SHRINKS to empty as the work completes rather than growing with the table —
the opposite of the lifecycle a plain index on this column would have.

--------------------------------------------------------------------------------
RLS
--------------------------------------------------------------------------------
No new table, so no new policy. `kb_documents` is in `db/registry.TENANT_TABLES` and
already carries its FORCEd `tenant_isolation` policy; a column is not a separate security
object and inherits the table's protection. Asserted rather than assumed —
`tests/kb_gloss_rls_test.py` writes and reads `gloss` as a second tenant and requires zero
rows in both directions.

`kb_documents` is NOT in `APPEND_ONLY_TABLES` (`kb/service._remember_engine_kb_ref` already
UPDATEs `meta` on it), so the worker's UPDATE of `gloss`/`gloss_state` needs no exception
and touches no ledger trigger.

--------------------------------------------------------------------------------
LOCKING
--------------------------------------------------------------------------------
Nullable columns and a non-volatile constant DEFAULT are both catalog-only since PG11: no
table rewrite, no scan, brief ACCESS EXCLUSIVE on the catalog row. The CHECK is added with
the column, so it is validated against zero pre-existing rows of the new column rather than
scanned in. `lock_timeout` bounds the wait so a queued request cannot park in front of every
other session (hard rule 8). Reversible: `downgrade` drops the index and the three columns,
which is lossless in the only sense that matters — every byte dropped is DERIVED from
`content`, which the downgrade does not touch, so re-running the sweep reconstructs it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from apps.api.kb.gloss import GLOSS_PENDING, GLOSS_STATES

revision: str = "a7f4c31d95e8"
down_revision: str | None = "d4a9c17e6b02"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "kb_documents"
INDEX = "ix_kb_documents_gloss_pending"
CHECK_NAME = "ck_kb_documents_gloss_state_enum"
# Rendered from the application-side constant rather than spelled a second time in
# SQL — a migration whose constant and whose constraint can disagree documents a schema
# it did not create. `a7c31e05b8d4` is the precedent, and `tests/kb_gloss_test.py`
# asserts `GLOSS_STATES` against the LIVE catalog rather than against this line.
CHECK_SQL = "gloss_state IN (" + ", ".join(f"'{s}'" for s in GLOSS_STATES) + ")"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("gloss", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("gloss_model", sa.Text(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "gloss_state",
            sa.String(),
            nullable=False,
            server_default=GLOSS_PENDING,
        ),
    )
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, CHECK_SQL)
    op.create_index(
        INDEX,
        TABLE,
        ["tenant_id"],
        postgresql_where=sa.text(f"gloss_state = '{GLOSS_PENDING}'"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.drop_column(TABLE, "gloss_state")
    op.drop_column(TABLE, "gloss_model")
    op.drop_column(TABLE, "gloss")
