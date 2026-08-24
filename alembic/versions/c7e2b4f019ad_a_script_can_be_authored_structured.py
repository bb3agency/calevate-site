"""a script can be authored structured

Revision ID: c7e2b4f019ad
Revises: f4b1e9a2c7d0
Create Date: 2026-08-24 00:00:00.000000

One nullable JSONB column on `prompt_versions`: `structured_script`, the authored
structured form of a script (opening line, ordered steps, FAQ, end-call rules, merge
variables — `calevate_shared.call_script.CallScript`). It sits BESIDE `body`, which stays
the compiled system prompt every downstream reader already consumes:
`agents/service._load_agent` joins `pv.body` into the `AgentConfig`, `compose_engine_prompt`
wraps it, the git mirror diffs it. Nothing downstream changes, because the compiled body
is still the source of truth for what the engine runs; `structured_script` is the authored
form the builder round-trips through the compiler to PRODUCE that body.

--------------------------------------------------------------------------------
WHY A COLUMN AND NOT A NEW TABLE
--------------------------------------------------------------------------------
A script's structured form is one-to-one with the prompt version it compiled to — same
lifetime, same immutability, same tenant, same rollback semantics — so it is an attribute
of the version, not an entity of its own. A separate table would need its own FK, its own
RLS policy, and a join on every read, to model a relationship that is already "these two
values were written together and never change". `compiled_t0_context` is the precedent:
the T0 compiler's build artifact lives as a column on this same row for the same reason
(D-39, migration 2faa301dc488).

--------------------------------------------------------------------------------
NULL MEANS "FREEFORM", AND THAT IS THE MIGRATION
--------------------------------------------------------------------------------
Every existing row is NULL after this migration and stays NULL — there is NO backfill, by
design. A NULL `structured_script` means "this version was authored as freeform text", and
`CallScript.from_freeform(body)` represents it losslessly as a single raw-mode script when
the builder loads it. So nothing is lost and nothing is rewritten: an old prompt round-trips
to exactly its own `body`. Backfilling every historical row with a synthesised raw-mode
JSON blob would write thousands of rows that say nothing the `body` does not already say,
on an APPEND-ONLY table where a write cannot later be corrected — the NULL sentinel is the
honest "authored before this existed", the same shape `live_prompt_id`'s NULL took for
"no divergence" (a4e7b2c95d18).

This also sidesteps the append-only trigger cleanly: `prompt_versions` is in
`registry.APPEND_ONLY_TABLES`, so no UPDATE may touch an existing row. A pure ADD COLUMN is
DDL, not a row UPDATE, and with no backfill there is no UPDATE to attempt against the
trigger at all. New rows stamp `structured_script` at INSERT alongside `body`
(`agents/prompts.insert_prompt_version`), which is the only write this column ever sees.

--------------------------------------------------------------------------------
RLS
--------------------------------------------------------------------------------
No new table, so no new policy: `prompt_versions` already carries its FORCEd
`tenant_isolation` policy and a column is not a separate security object, so the new column
inherits the table's protection. Asserted rather than assumed:
`tests/structured_script_rls_test.py` reads and writes `structured_script` as a second
tenant and requires zero rows.

--------------------------------------------------------------------------------
LOCKING
--------------------------------------------------------------------------------
A nullable column with no default is catalog-only since PG11: no table rewrite, no scan,
brief ACCESS EXCLUSIVE for the catalog row only. `lock_timeout` bounds the wait so a
queued request cannot park in front of every other session (hard rule 8). `prompt_versions`
is on the publish path, which is the reason for the bound.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------
Drops the column. What is lost is only the authored structured form; every `body` is
untouched, so every agent still publishes exactly the prompt it published before, and the
pre-migration code (which reads `body` and never mentions `structured_script`) runs
correctly against the post-downgrade schema. Nothing is two-step-deprecated because nothing
that was being read is being removed — the column is new.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e2b4f019ad"
down_revision: str | None = "f4b1e9a2c7d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "prompt_versions"
COLUMN = "structured_script"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column(COLUMN, postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(TABLE, COLUMN)
