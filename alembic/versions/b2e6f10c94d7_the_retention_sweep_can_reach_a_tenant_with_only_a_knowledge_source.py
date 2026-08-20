"""the retention sweep can reach a tenant whose only expirable data is a knowledge source

Revision ID: b2e6f10c94d7
Revises: f1c8b7d5a903
Create Date: 2026-08-20 14:40:00.000000

D-368, closed. `apps/workers/retention.py::_due_tenants` builds the nightly sweep's
worklist from `engine_agent_routes`, and its docstring records both the hole and the
reason it was left open:

    "D-179 then added `kb`, and a knowledge source is the one expirable artefact a tenant
     can hold WITHOUT ever publishing an agent. `kb/service.reject_source` moves a source
     `pending_approval → rejected` with no engine involvement at all, so a tenant that
     uploads a document, has it refused, and never publishes has ... NO
     `engine_agent_routes` row, so it is not in this list and its nightly sweep never
     runs."

Retention is a DPDP obligation and not a cleanup task, so a tenant silently outside the
sweep is a compliance failure. It also cannot be argued away as unreachable: the
population is bounded to `rejected` sources, and "bounded" is not "empty" — a
`kb_documents` row holds whatever the client uploaded.

--------------------------------------------------------------------------------
THE SHAPE, AND THE TWO THIS ONE WAS CHOSEN OVER
--------------------------------------------------------------------------------

`_due_tenants` weighed two closures and took neither, correctly:

* *Read `kb_sources` across tenants.* Needs an RLS exemption on a table that holds CLIENT
  CONTENT, where the two existing tenant-carrying exemptions (`audit_log`,
  `engine_agent_routes`) hold a hash chain and two routing keys. Reading one derived fact
  is not worth a global read of the rows it is derived from.
* *Walk `organizations` under `admin_session`.* Reinstates the per-tenant fan-out D-57 and
  P6.2 deliberately removed, on ~16k rows, to reach a handful.

This is the third: a table that IS the fact. One tenant id, one reason from a closed
vocabulary, one timestamp — no title, no document, no engine handle. Globally readable for
exactly the reason `engine_agent_routes` is, and carrying no more than it does, so
`kb_sources` keeps its FORCEd `tenant_isolation` policy untouched (hard rule 1).

--------------------------------------------------------------------------------
WHY A TRIGGER MAINTAINS IT
--------------------------------------------------------------------------------

D-368's objection to a presence table was that it buys "a second bridge to keep in step
with the first". A trigger is what removes that cost: the invariant

    a tenant that holds a knowledge source is in the retention worklist

holds for EVERY writer of `kb_sources` — `kb/service.py` today, whatever is written next,
and an operator inserting by hand during an incident. An application-level write would
hold only for the call sites that remember it, which is the same argument
`b8d3f47c2a19` makes for putting a unique index behind an advisory lock: a convention
protects the callers that take it and a database object protects the table.

The trigger fires on INSERT and is deliberately NOT conditioned on `status`. `_KB_EXPIRABLE`
matches `archived` and `rejected` today; conditioning on that set would couple this table
to a predicate that has already changed once, and the failure direction is asymmetric —
registering a tenant with nothing expired costs ONE cheap probe on a nightly job, and
missing one costs a legal obligation. So the sentence the trigger enforces has no status in
it at all.

`SECURITY INVOKER` (the default), so the write happens as the tenant's own session and is
checked by the policy below. It cannot write another tenant's row: `kb_sources`' own policy
already forces `NEW.tenant_id` to equal the session GUC.

--------------------------------------------------------------------------------
THE BACKFILL — the half enforcement cannot do
--------------------------------------------------------------------------------

A trigger reaches forward only, and the tenants in the hole are already in it. The INSERT
... SELECT below is the reach backwards, and it is why this migration and not a code change
closes the defect: it runs as the OWNER role (`env.py` refuses to run as the app role), so
it can see every tenant's `kb_sources` rows and register each tenant exactly once.

`DISTINCT tenant_id` — the table is an index, not a log.

--------------------------------------------------------------------------------
RLS — AND THIS TABLE NEEDS NO EXEMPTION, WHICH IS THE POINT
--------------------------------------------------------------------------------

    tenant_isolation             FOR ALL     USING/WITH CHECK (tenant_id = GUC)
    retention_worklist_ops_read  FOR SELECT  USING (GUC IS NULL)

The obvious shape was the pair `c4b70e928a1f` gave `engine_agent_routes` — a
`FOR SELECT USING (true)` beside an own-tenant-or-ops write policy — and it is WIDER than
this problem. `USING (true)` makes the table readable cross-tenant from a TENANT session
too, and nothing needs that: the only reader is `retention._due_tenants`, which runs in a
worker under `untenanted_session`. So the read arm is exactly that session and no other,
and the write arm is strictly own-tenant — an untenanted session cannot write here either,
which is one verb narrower than `engine_agent_routes` and `dnc_list` allow themselves.
Nothing needs to: the trigger runs inside the tenant's own session, and the backfill above
runs BEFORE `ENABLE ROW LEVEL SECURITY`, so it depends on no bypass at all.

Permissive policies are OR'd PER COMMAND, and `FOR SELECT` participates only in SELECT —
so a tenant session reads its own rows and no others, an untenanted session reads all of
them and writes none, and INSERT/UPDATE/DELETE see only `tenant_isolation` whoever asks.

Both USING clauses consult the tenancy GUC, so `check_rls_coverage` judges this table by
the ordinary rule and `db/registry.TENANT_TABLES` is where it is listed —
`RLS_EXEMPT_TENANT_COLUMNS` gains nothing. That matters more than tidiness: the exemption
dict is the cheapest way to smuggle a tenant table past hard rule 1, and a closure for
D-368 that widened it would have paid for a compliance fix with a tenancy hole.
`tests/rls_sweep_test.py` then sweeps this table generically, with no list to update.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Exact and total: trigger, function, policies and table dropped, in dependency order.
Nothing else references any of them, and the pre-migration `_due_tenants` — which reads
`engine_agent_routes` alone — runs correctly against the post-downgrade schema. That is
the sense hard rule 8 means by reversible. The DATA is lost on a downgrade, which is
recoverable: re-running the upgrade rebuilds it from `kb_sources` by the same backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e6f10c94d7"
down_revision: str | None = "f1c8b7d5a903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "retention_worklist"
READ_POLICY = "retention_worklist_ops_read"
WRITE_POLICY = "tenant_isolation"
TRIGGER = "kb_source_registers_retention_worklist"
FUNCTION = "register_retention_worklist"

# The reason this migration writes. Spelled as a literal rather than imported from
# `compliance/models.RETENTION_WORKLIST_REASONS`: a migration is a snapshot of the schema
# on the day it ran (the rule `c2f7a91b4e63` states), and a constant edited later must not
# change what this file did.
REASON = "kb_source"

# NULLIF on the empty string is the repo-wide form — `SET LOCAL app.tenant_id = ''` must
# read as "no tenant", not fail the ::uuid cast.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
#: The worker's read, and ONLY the worker's read. `_due_tenants` runs under
#: `untenanted_session`; a client request always carries the GUC because `tenant_session`
#: is the only way one reaches the database.
_OPS_SESSION = f"({_GUC} IS NULL)"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
            tenant_id     uuid        NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            reason        varchar     NOT NULL,
            registered_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_{TABLE} PRIMARY KEY (tenant_id, reason),
            CONSTRAINT ck_{TABLE}_reason_enum CHECK (reason IN ('{REASON}'))
        )
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION}() RETURNS trigger AS $$
        BEGIN
            INSERT INTO {TABLE} (tenant_id, reason)
            VALUES (NEW.tenant_id, '{REASON}')
            ON CONFLICT (tenant_id, reason) DO NOTHING;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    # AFTER, so a refused INSERT registers nothing, and FOR EACH ROW because the tenant is
    # a property of the row. `RETURN NULL` is correct for an AFTER trigger: its return
    # value is ignored, and returning NULL says so rather than implying it matters.
    op.execute(
        f"CREATE TRIGGER {TRIGGER} AFTER INSERT ON kb_sources "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
    )

    # The reach backwards. Runs as the owner role, which is the only session that can see
    # every tenant's rows — see the docstring.
    op.execute(
        f"INSERT INTO {TABLE} (tenant_id, reason) "
        f"SELECT DISTINCT tenant_id, '{REASON}' FROM kb_sources "
        "ON CONFLICT (tenant_id, reason) DO NOTHING"
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it the owner is
    # exempt and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {READ_POLICY} ON {TABLE} FOR SELECT USING {_OPS_SESSION}")
    op.execute(
        f"CREATE POLICY {WRITE_POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON kb_sources")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
    op.execute(f"DROP POLICY IF EXISTS {WRITE_POLICY} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON {TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
