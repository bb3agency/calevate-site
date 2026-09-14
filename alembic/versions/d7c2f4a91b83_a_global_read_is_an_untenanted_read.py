"""a global read is an untenanted read, not everybody's read

Revision ID: d7c2f4a91b83
Revises: c7a41e8b52d9
Create Date: 2026-09-14 21:40:00.000000

Three `*_global_read` policies were `FOR SELECT USING (true)`. They are now
`FOR SELECT USING (<app.tenant_id> IS NULL)`.

--------------------------------------------------------------------------------
WHAT WAS WRONG, MEASURED
--------------------------------------------------------------------------------

Permissive policies are OR'd per command, so `USING (true)` on a SELECT policy makes the
table's `tenant_isolation` policy irrelevant to every read — by ANY session, not only by
the untenanted one the exemption was written for. Measured on a migrated database as
`calevate_app` (NOSUPERUSER NOBYPASSRLS), 14 Sep 2026: tenant B opens `tenant_session(B)`,
selects tenant A's row by its vendor reference, and gets `count = 1` on
`engine_agent_routes` and on `engine_kb_routes`. `pipecat_kb_objects` carries the same
expression and therefore the same property.

That is hard rule 1's cross-tenant zero-rows property failing on three tables. What leaks
is not call content — these tables hold ids — but it is a client's whole fleet: which
tenant owns which vendor agent object, which agent answers which vendor reference, and the
handle that addresses another client's knowledge object.

--------------------------------------------------------------------------------
WHY THE NARROWING COSTS NOTHING, WHICH IS THE WHOLE ARGUMENT
--------------------------------------------------------------------------------

Every sentence in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` justifying these three
exemptions justifies an UNTENANTED question, and only an untenanted question:

* `engine_agent_routes` — "an engine webhook arrives with only the VENDOR agent id and no
  session"; `claim_drift_batch`/`claim_kb_drift_batch`'s fleet-wide batch read.
* `engine_kb_routes` — "which objects on this account does no tenant of ours claim", the
  orphan sweep (`kb/orphans._claims`), which runs from `untenanted_session`.
* `pipecat_kb_objects` — `VoiceEngine.list_account_kb`, likewise untenanted, and likewise
  an account-level question no tenant session can ask.

None of them is a tenant-session question, and no reader in the tree is one. Every
tenant-session read of these three tables in `apps/` already carries `tenant_id = :tid` in
its own WHERE clause (`compliance/service.py`'s truthful-answer verdict says so in a
comment — "`tenant_id` is in the predicate anyway rather than being trusted to the
exemption" — and `workers/retention.py`'s two erasure-task reads do the same), or joins a
FORCE-RLS'd table that bounds it (`kb/service._ROUTE_JOIN` through `kb_sources`), or
reaches only its own rows by construction (`engine/pipecat.py::agent_kb`, keyed on the
agent's own vendor reference).

So the untenanted arm keeps every use it was bought for, each tenant keeps its own rows
through `tenant_isolation`, and the arm nobody argued for is gone.

--------------------------------------------------------------------------------
WHY THIS SPELLING AND NOT ANOTHER
--------------------------------------------------------------------------------

`NULLIF(current_setting('app.tenant_id', true), '') IS NULL` is not invented here: it is
already this repository's shape for exactly this exemption, on `kb_uploads_ops_read`
(migration `f2b91c47e0a3`) and `retention_worklist_ops_read` (migration `b2e6f10c94d7`). Two spellings of one
rule is the drift the quality bar forbids, and the one that survives is the narrower one.

The rejected alternative was to drop the separate SELECT policy and fold the arm into
`tenant_isolation` as `tenant_id = <guc> OR <guc> IS NULL`. That is the exact expression
`b8e2d47f0c19` had to REMOVE from both route tables, because a `FOR ALL` policy carrying
it hands every untenanted writer INSERT/UPDATE/DELETE over any tenant's row. The two-policy
shape is what keeps the widening to the verb it was granted for, and it stays.

`scripts/check_rls_coverage.py` is unaffected in the direction that matters: its rule 8
(`_check_untenanted_write`) judges an exempt table on whether an untenanted session can
WRITE, and these are SELECT policies. The narrowing only removes a read.

--------------------------------------------------------------------------------
RLS, LOCKS, DOWNGRADE
--------------------------------------------------------------------------------

No table is created and no rows are touched, so there is no `NO FORCE`/`FORCE` bracket to
write — the bracket exists for DML that RLS would filter, and `CREATE POLICY` is DDL
(`migration_rls_bracket_test`'s `DML` pattern is the authority on which is which).

`DROP POLICY`/`CREATE POLICY` take ACCESS EXCLUSIVE on the table; `lock_timeout` bounds the
wait so a queued DDL cannot park in front of every other session (hard rule 8). Both
statements are instant once the lock is held — there is no scan and no rewrite.

Reversible in the sense hard rule 8 means: `downgrade()` restores the exact `USING (true)`
expression each policy had before this revision, so the schema and every caller's behaviour
return to what they were. Nothing is dropped and no writer stops writing a column, so no
two-step deprecation applies.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7c2f4a91b83"
down_revision: str | None = "c7a41e8b52d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, policy) — the three read exemptions, spelled out rather than derived from
#: `RLS_EXEMPT_TENANT_COLUMNS`. A migration is a snapshot of the schema on the day it ran:
#: importing today's register would silently re-aim this revision at whatever is exempt
#: next year, and the migration that adds a fourth exemption is the one that should say so.
#: (c7a41e8b52d9 spells out its language set for the same reason.)
_READ_POLICIES: tuple[tuple[str, str], ...] = (
    ("engine_agent_routes", "engine_agent_routes_global_read"),
    ("engine_kb_routes", "engine_kb_routes_global_read"),
    ("pipecat_kb_objects", "pipecat_kb_objects_global_read"),
)

#: The repo-wide spelling of "no tenant is set" — `kb_uploads_ops_read` and
#: `retention_worklist_ops_read` verbatim. `current_setting(..., true)` returns the empty
#: string rather than raising when the GUC was never set in this transaction, which is why
#: the `NULLIF` is not decoration.
_UNTENANTED = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, policy in _READ_POLICIES:
        op.execute(f"DROP POLICY {policy} ON {table}")
        op.execute(f"CREATE POLICY {policy} ON {table} FOR SELECT USING ({_UNTENANTED})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, policy in _READ_POLICIES:
        op.execute(f"DROP POLICY {policy} ON {table}")
        op.execute(f"CREATE POLICY {policy} ON {table} FOR SELECT USING (true)")
