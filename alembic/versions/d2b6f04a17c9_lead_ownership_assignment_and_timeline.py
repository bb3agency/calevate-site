"""lead ownership: an assignment event type, and an index the "my leads" filter can use

Revision ID: d2b6f04a17c9
Revises: b7d2e4a91c38
Create Date: 2026-08-13 10:40:00.000000

ROADMAP M3 lists "Client staff roles, lead assignment, lead_events timeline".
`leads.assigned_to` has existed since the core migration and nothing read or wrote it
(`scripts/check_wiring.py` carried it as a dated deferral). This revision is the
schema half of closing that: the event type the assignment writes, and the index the
filter it enables needs.

**NO NEW TABLE, SO NO NEW RLS POLICY — stated rather than left to be inferred.**
Hard rule 1 asks for a policy in the same migration as any new tenant table. Both
objects here belong to tables that already carry `tenant_isolation` FORCEd on
`tenant_id` (`leads`, `lead_events`, migration 05bba2f3c19c), and neither a CHECK
constraint nor an index can widen a policy: a partial index changes which rows are
REACHABLE by a plan, never which rows a policy admits, and the policy is applied above
the access method. `scripts/check_rls_coverage.py` reads the live catalog and would say
so if that were wrong.

1. `lead_events.type` GAINS `assignment`
-----------------------------------------
The rejected alternative is the one `apps/api/ingest/service.py:379` took — reuse
`note` and discriminate on `payload->>'kind'`. It is a real precedent and it does not
govern here, for two reasons. First, the sibling that DOES govern is `status_change`:
"a person changed a field on this lead" is already a first-class type, and recording
the owner change one level down inside a payload while the status change sits at the
top would be two ways of modelling one shape of event. Second, ingest's reuse exists
because `blocked` has no natural member AND that milestone shipped no migration; this
slice ships one anyway for the index below, so the member is free.

Widening a CHECK is ADDITIVE: every row that satisfied the four-value predicate
satisfies the five-value one, so hard rule 8's two-step deprecation (which governs
REMOVING a value while writers still exist) does not apply, and `downgrade()` is only
safe because nothing outside this release writes the new value.

DROP-then-ADD inside the migration's transaction rather than the
`ADD ... NOT VALID` + `VALIDATE CONSTRAINT` dance. The dance exists to swap the
table-scan's ACCESS EXCLUSIVE lock for SHARE UPDATE EXCLUSIVE, and it buys nothing
here: the two statements share one transaction, which already holds ACCESS EXCLUSIVE
from the DROP, so the only way to collect the benefit would be to split this across two
releases for a constraint that is logically already satisfied by every existing row.
`lock_timeout` bounds the WAIT for the lock — the exposure a short DDL actually has —
exactly as `b9e5d2c74a18` argued for its index drops.

`downgrade()` deletes the `assignment` rows before narrowing the CHECK. That is a
DELETE of client-visible history and it is deliberate: the alternative is a downgrade
that fails on the first tenant who assigned a lead, and a migration that cannot run
backwards is not reversible in any sense hard rule 8 recognises. `lead_events` is a
timeline, not one of hard rule 4's append-only ledgers (`apps/workers/whatsapp.py`
says so where it UPDATEs a notification row in place), so removing rows is not a ledger
violation — it is data loss, which is what a downgrade of this shape costs.

2. `ix_leads_assigned_to` — PARTIAL on `assigned_to IS NOT NULL`
-----------------------------------------------------------------
The filter is `WHERE deleted_at IS NULL AND assigned_to = :user` under the tenant
policy's own `tenant_id = ...`. `ix_leads_tenant_id` bounds the scan to the tenant and
nothing narrows it further, so on a large account the "my leads" chip reads every lead
in the business to find the twenty a person owns — the defect the leads list already
learned once about counting (BUILD-LOG §52).

MEASURED on this schema, one tenant, 60k leads, 300 of them assigned, `ANALYZE`d, plan
taken as the owner with the tenant GUC set:

    without     Seq Scan on leads, Rows Removed by Filter: 59700   1035 buffers  5.6ms
    with        Index Scan using ix_leads_assigned_to               301 buffers  0.5ms

PARTIAL, not plain, and the reason is the column's shape rather than tidiness: a lead
is unassigned until a person claims it, so `assigned_to` is NULL on the overwhelming
majority of rows and NULLs are the one thing this predicate can never match. At the
volume above the same index costs **16 kB partial against 424 kB plain**, and the
difference is paid on the post-call pipeline's hot path — every lead upsert would
otherwise buy an index insertion for a value that is NULL.

The predicate must appear in the query for the planner to use a partial index (PG16
§11.8), and it does: `assigned_to = :user` implies `assigned_to IS NOT NULL`, which is
an implication Postgres's predicate prover makes on its own — the plan above is the
evidence, not the argument. `deleted_at IS NULL` is deliberately NOT in the index
predicate: `crm.service._lead_scope` always emits it, but tying the index to a second
clause makes it unusable the day a caller legitimately asks a different question about
an assigned lead, and soft-deleted leads are rare enough that it would shrink nothing.

Single-column, not `(tenant_id, assigned_to)`. A composite would make
`ix_leads_tenant_id` a strict prefix of it, and `b9e5d2c74a18` measured that index as
one of the seven that must STAY (dropping it moves eight plans to Seq Scan); a
composite whose first column duplicates a keeper is a third copy of `tenant_id`, and
the BitmapAnd the planner builds from the two single-column indexes is what the
measurement above already shows working.

NOT `CONCURRENTLY`, same reasoning as `b9e5d2c74a18`: it cannot run inside a
transaction block, so it would trade this revision's atomicity — the constraint and the
index must land together or not at all, because the service writes the new event type
the moment it deploys — for a lock held over a table that is small on every tenant we
have. `lock_timeout` bounds the wait.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2b6f04a17c9"
down_revision: str | None = "b7d2e4a91c38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_lead_events_type_enum"
# Kept in the shape `apps/api/crm/models.py` renders, so a reader diffing the two sees
# one string rather than two spellings of one tuple.
TYPES_BEFORE = "('status_change', 'note', 'call', 'notification')"
TYPES_AFTER = "('status_change', 'note', 'call', 'notification', 'assignment')"

INDEX = "ix_leads_assigned_to"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE lead_events DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE lead_events ADD CONSTRAINT {CONSTRAINT} CHECK (type IN {TYPES_AFTER})")
    op.execute(f"CREATE INDEX {INDEX} ON leads (assigned_to) WHERE assigned_to IS NOT NULL")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX {INDEX}")
    # Before the narrower CHECK, not after: `ADD CONSTRAINT` validates, so an account
    # that has assigned a lead would otherwise make this downgrade unrunnable. The cost
    # is stated in the module docstring.
    # The bracket (`d3b71c9a5e08`): this table is FORCE ROW LEVEL SECURITY, which
    # subjects the OWNER to `tenant_isolation` too, and that policy is fail-closed on an
    # unset `app.tenant_id`. Unbracketed, the statement below matches ZERO rows and
    # reports success. Added by `e1a4d70c9b52`'s round, which hit exactly this in
    # production; `tests/migration_rls_bracket_test.py` now fails the build on a new one.
    op.execute("ALTER TABLE lead_events NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM lead_events WHERE type = 'assignment'")
    op.execute("ALTER TABLE lead_events FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE lead_events DROP CONSTRAINT {CONSTRAINT}")
    op.execute(
        f"ALTER TABLE lead_events ADD CONSTRAINT {CONSTRAINT} CHECK (type IN {TYPES_BEFORE})"
    )
