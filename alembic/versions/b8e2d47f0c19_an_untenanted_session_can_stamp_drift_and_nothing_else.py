"""an untenanted session can stamp drift and nothing else — the route tables lose their write arm

Revision ID: b8e2d47f0c19
Revises: f4a2c7e19d63
Create Date: 2026-09-10 19:40:00.000000

`engine_agent_routes` and `engine_kb_routes` each carried ONE policy for every write verb:

    tenant_isolation  FOR ALL  USING/WITH CHECK (tenant_id = <guc> OR <guc> IS NULL)

The second arm is the subject of this migration. Measured on a migrated database as
`calevate_app` (NOSUPERUSER NOBYPASSRLS), in a transaction that was rolled back, with NO
`app.tenant_id` set at all — 10 Sep 2026:

    INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id)
      VALUES ('fake','audit-probe-1', <any tenant>, <any agent>);        -->  INSERT 0 1
    UPDATE engine_agent_routes SET tenant_id = <another tenant>
      WHERE engine_agent_ref = 'audit-probe-1';                          -->  UPDATE 1
    DELETE FROM engine_agent_routes WHERE engine_agent_ref = 'audit-probe-1';
                                                                         -->  DELETE 1
    INSERT INTO engine_kb_routes (...) VALUES (...);                     -->  INSERT 0 1
    DELETE FROM engine_kb_routes WHERE engine_kb_ref = 'audit-kb-1';     -->  DELETE 1

`c4b70e928a1f` closed the TENANT half of exactly this hole ("a tenant cannot rewrite
another tenant's route") and wrote the untenanted arm down as deliberate, because the
drift sweeps genuinely do write from `untenanted_session`. What that reasoning missed is
that a policy is not a permission granted to a caller — it is a permission granted to a
SHAPE OF SESSION, and every future untenanted writer inherits it. `engine_agent_routes`
decides which agent an inbound number reaches: a re-tenanted row sends one client's
inbound calls into another client's agent, silently, with no request involved.

--------------------------------------------------------------------------------
WHAT THIS DOES
--------------------------------------------------------------------------------

Both tables' `tenant_isolation` policy becomes the strict repo-wide form —

    tenant_isolation  FOR ALL  USING/WITH CHECK (tenant_id = <guc>)

— and the two `*_global_read` policies (`FOR SELECT USING (true)`) are UNTOUCHED. Reads
stay global, which is the whole content of these tables' `RLS_EXEMPT_TENANT_COLUMNS`
entries: an engine webhook arrives with only a vendor id and no session, and the KB
orphan question ("which objects on this account does no tenant of ours claim") cannot be
asked from a tenant session at all. Permissive policies are OR'd PER COMMAND, so the
`FOR SELECT` policy participates in SELECT only and the write verbs now see the strict
policy alone.

After this, an untenanted session on either table can read everything and write nothing.

--------------------------------------------------------------------------------
THE ARM WAS LOAD-BEARING, SO THE SWEEPS MOVED — THEY DID NOT LOSE ANYTHING
--------------------------------------------------------------------------------

`agents/reconciliation.record_drift` and `kb/reconciliation.record_kb_drift` are the only
two writers that used the untenanted arm, and both are UPDATEs of the drift columns on
`engine_agent_routes`, keyed on `(engine, engine_agent_ref)`. They now run under
`tenant_session(candidate.tenant_id)` and take that `tenant_id` as an argument.

**The tenant was never unknown at the point of the write.** The sweep's cross-tenant leg
is its BATCH READ (`claim_drift_batch` / `claim_kb_drift_batch`), which is untenanted and
stays untenanted — it is a read, and the global-read policy is what buys it. Every
candidate that read returns already carries `tenant_id`, and the agent sweep was already
opening `tenant_session(candidate.tenant_id)` three lines later for the inbound half of
the verdict. So the sweep still starts from what the vendor lists rather than from a
tenant, and only the WRITE is scoped to the tenant the row itself names.

`engine_kb_routes` had no untenanted writer at all: every write is `kb/service.
record_engine_kb_ref`, reached from `publish_source`, and both of its callers
(`admin/routes.publish_kb`, `workers/kb_ingest`) open `tenant_session` first. Its untenanted
arm bought nothing and is simply gone.

--------------------------------------------------------------------------------
THE SHAPES THAT WERE REJECTED, AND WHY
--------------------------------------------------------------------------------

1. **A split policy that keeps an untenanted write: `tenant_isolation` strict, plus
   `FOR UPDATE USING (<guc> IS NULL)`** — `retention_worklist`'s and `kb_uploads`' shape,
   which is the first thing to reach for and is what the audit suggested. Rejected on two
   independent grounds. (a) It CANNOT express the property this change exists to
   guarantee: on an UPDATE, `WITH CHECK` sees only the NEW row and RLS has no access to
   the OLD one, so `WITH CHECK (<guc> IS NULL)` accepts `SET tenant_id = <anyone>`. The
   re-tenanting stays open, and only a trigger comparing OLD and NEW could close it —
   machinery to hold open a door nothing needs. (b) `scripts/check_rls_coverage.py`'s
   untenanted-write rule refuses that shape on any command but SELECT, with no waiver, and
   the two shapes it does accept (a separate `FOR SELECT` policy; `dnc_list`'s
   `tenant_id IS NULL` global-row arm) are both about rows that belong to nobody. These
   rows belong to somebody.

2. **Column-level GRANTs — `REVOKE UPDATE`, then `GRANT UPDATE (drift_state, ...)`.**
   Privileges attach to a ROLE, and `tenant_session` and `untenanted_session` are the same
   role (`calevate_app`) holding the same grants; a grant narrow enough for the sweep would
   equally refuse the publish path's `ON CONFLICT DO UPDATE SET tenant_id, agent_id,
   active` and `agents/experiments.conclude`'s `active = false`. A privilege also cannot
   say "unchanged" — only "not written" — so it answers a different question from the one
   asked.

3. **A dedicated database role for the sweeps** (with a `SECURITY DEFINER` function or
   `BYPASSRLS`). This repo has already taken this decision once, in the opposite
   direction and in writing: `a8d4f21c9b06` rejected `SECURITY DEFINER` owned by a
   privileged role as "a hard-rule-1 violation wearing a function's clothes" and made
   `dispatch_scan` re-scope the GUC per tenant instead. Doing the same thing here is what
   shape 0 above IS — and it costs no new role, no second DSN, no bootstrap ordering and
   no function whose next reader adds a fourth statement to it.

4. **Moving the drift columns onto a platform-scoped table of their own** (no `tenant_id`,
   so an untenanted writer is entitled to it by construction). Genuinely clean on paper,
   and rejected on blast radius rather than on principle: `drift_state` is read by the
   dispatch gate, the ops summaries and the inbound-silence verdict `f4a2c7e19d63` has
   just built, the columns come with two CHECKs and two partial indexes, and hard rule 8
   makes it a two-release deprecation. The route row deliberately STANDS FOR one vendor
   agent object (`d4b8e1c73f05`); splitting the observation off duplicates the
   `(engine, engine_agent_ref)` key, adds a join to every ops read, and invents an orphan
   class of its own.

--------------------------------------------------------------------------------
NO DATA STATEMENT, SO NO `NO FORCE` / `FORCE` BRACKET
--------------------------------------------------------------------------------

Said out loud because both tables are FORCE-RLS'd and `d3b71c9a5e08` established the
bracket for exactly this situation. That bracket exists for DML: a migration runs as the
table OWNER, FORCE makes the owner subject to the policy, and an UPDATE/DELETE with no
GUC set would touch zero rows and report success. Everything here is policy DDL, which no
policy filters, and nothing in this migration reads or writes a row.

DOWNGRADE: exact. Both policies are dropped and recreated in the widened form
`c4b70e928a1f` and `f1c9e0a73b46` installed, so `downgrade -1` returns the catalogue to
byte-identical expressions. It re-opens the hole, which is what a downgrade of this
migration means; the code that runs against the downgraded schema (the sweeps under
`tenant_session`) keeps working either way, because the strict arm is a SUBSET of the
widened one.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e2d47f0c19"
down_revision: str | None = "f4a2c7e19d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WRITE_POLICY = "tenant_isolation"
TABLES = ("engine_agent_routes", "engine_kb_routes")

# Spelled out rather than imported, because a migration is a snapshot of the schema on the
# day it ran (the rule `c2f7a91b4e63` states). NULLIF on the empty string is the repo-wide
# form — `SET LOCAL app.tenant_id = ''` must read as "no tenant", not fail the ::uuid cast.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"


def _install(expression: str) -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY {WRITE_POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {WRITE_POLICY} ON {table} FOR ALL "
            f"USING {expression} WITH CHECK {expression}"
        )


def upgrade() -> None:
    _install(_OWN_TENANT)


def downgrade() -> None:
    _install(_OWN_TENANT_OR_OPS)
