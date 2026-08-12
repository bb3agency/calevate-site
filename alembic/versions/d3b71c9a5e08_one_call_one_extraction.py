"""one call, one extraction

Revision ID: d3b71c9a5e08
Revises: 2faa301dc488
Create Date: 2026-08-11 05:10:00.000000

`_persist_extraction` (apps/workers/pipeline.py) was changed from a plain INSERT to an
update-or-insert, which closes the REPLAY case: a webhook arriving after the poller has
already resolved the call re-enters the pipeline (D-31) and no longer files a second
extraction. It does not close the RACE. Two pipeline runs for one call — an ARQ retry
overlapping the reconciliation poller — can both read "no row", and both insert. What
serializes them today is the ARQ job id, which is keyed on the call; that is a Redis
convention, not a database fact, and it evaporates the moment a job is enqueued by any
path that keys it differently.

The CRM reads one extraction per call (`ORDER BY created_at DESC LIMIT 1`,
apps/api/crm/service.py) and the retention eraser rewrites "the" extraction for a call.
Both are written as if the invariant were enforced. This makes it enforced.

**Existing data.** It was not clean. On this database 47 (tenant_id, call_id) pairs
carried two rows each out of 236 — residue of the pre-fix plain INSERT, exactly the
duplicates the pipeline change was about. So the constraint cannot simply be declared:
it has to be earned first, and a migration that discovers this on production instead of
here is a failed deploy. `upgrade()` therefore collapses each pair before it adds the
constraint, in the same transaction, so no window exists in which a new duplicate can
be inserted between the two.

**Which row survives.** The newest by `created_at`, tie-broken by `id` — precisely the
row every reader already returns. The rows deleted here are rows no query in the
codebase could reach: the CRM detail takes the newest, and nothing else selects more
than one. Collapsing them changes no observable behaviour; it only removes the second
answer nobody could ask for.

Deleting is allowed on this table and only looks like it isn't. `call_extractions` is
not an append-only ledger — it is absent from `APPEND_ONLY_TABLES` (apps/api/db/
registry.py), it carries no immutability trigger, and the retention worker already
rewrites its `data` in place. Nothing references it by foreign key, so nothing is
orphaned.

**Why the key is (tenant_id, call_id) and not (call_id).** Two reasons, one practical
and one about isolation:

- it is the pipeline's own WHERE clause, so the upsert it wants can name it directly;
- under FORCEd RLS a unique violation is one of the very few channels through which a
  row your policy hides can announce that it exists. Leading with `tenant_id` means a
  conflict is only ever reachable against a row of your own. `calls.id` is a global
  primary key, so a cross-tenant collision is not reachable today — but a uniqueness
  constraint should not be the thing standing between us and that on the day the calls
  table gains a second writer.

**RLS.** No new table, so no new policy (hard rule 1 is satisfied by inheritance —
`call_extractions` already carries a FORCEd `tenant_isolation` policy). The dedupe,
however, has to be told about it. Migrations run as the table OWNER, and FORCE ROW
LEVEL SECURITY means the owner is subject to the policy too; with no `app.tenant_id`
GUC set the policy is fail-closed, so the DELETE would touch zero rows, report success,
and the CREATE UNIQUE INDEX behind it would then fail on data the migration believed it
had cleaned. The `NO FORCE` / `FORCE` bracket is how this one statement gets to see
every tenant's rows:

- it lifts RLS for the OWNER only — `calevate_app`, which is not the owner and is
  NOSUPERUSER NOBYPASSRLS, keeps every policy for the whole duration;
- DDL is transactional in Postgres, so FORCE is restored before anything commits, and
  any failure in between rolls the whole bracket back;
- it does not depend on the migration role being a superuser, which the local owner
  happens to be and a managed-Postgres owner generally is not.

**Locking.** Plain `ADD CONSTRAINT ... UNIQUE`, not `CREATE UNIQUE INDEX CONCURRENTLY`,
and deliberately so. CONCURRENTLY cannot run inside a transaction, which would split the
dedupe from the constraint — a row inserted in that gap leaves an INVALID index and a
table that still permits the race, i.e. the failure mode this migration exists to
remove. The table holds 236 rows; the SHARE lock is held for microseconds, which is not
a hazard even with other suites hammering the same database.

**Downgrade** drops the constraint and stops there. It does not resurrect the collapsed
duplicates and should not: they were unreachable rows whose only property was to make
"the extraction for this call" ambiguous. Reversibility in the sense hard rule 8 means —
the schema returns to its previous shape and the pre-migration code runs correctly
against the result — holds exactly.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3b71c9a5e08"
down_revision: str | None = "2faa301dc488"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "uq_call_extractions_tenant_id_call_id"

# Keep the newest row per (tenant_id, call_id) — the one the CRM already returns — and
# delete the rest. `created_at DESC, id DESC` is a TOTAL order: two racing inserts can
# share `created_at` to the microsecond, and a partial order here would make the
# survivor depend on the plan.
_DEDUPE = """
DELETE FROM call_extractions victim
USING (
    SELECT id,
           row_number() OVER (
               PARTITION BY tenant_id, call_id
               ORDER BY created_at DESC, id DESC
           ) AS rn
    FROM call_extractions
) ranked
WHERE victim.id = ranked.id AND ranked.rn > 1
"""


def upgrade() -> None:
    op.execute("ALTER TABLE call_extractions NO FORCE ROW LEVEL SECURITY")
    op.execute(_DEDUPE)
    op.execute("ALTER TABLE call_extractions FORCE ROW LEVEL SECURITY")
    op.create_unique_constraint(CONSTRAINT, "call_extractions", ["tenant_id", "call_id"])


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "call_extractions", type_="unique")
