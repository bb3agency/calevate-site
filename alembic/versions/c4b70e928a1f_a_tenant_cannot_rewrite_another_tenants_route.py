"""a tenant cannot rewrite another tenant's inbound route — the exemption only bought READS

Revision ID: c4b70e928a1f
Revises: a2e9f31c605d
Create Date: 2026-08-16 10:20:00.000000

`engine_agent_routes` is one of two tables that carry a `tenant_id` and are deliberately
not policied on it (`registry.RLS_EXEMPT_TENANT_COLUMNS`). The reason recorded there is
entirely about READING:

    "an engine webhook arrives with only the VENDOR agent id and no session, so
     resolving it to a tenant is inherently cross-tenant"

That is true and it is why the table exists. It says nothing about writing, and the table
had no RLS at all, so a session scoped to tenant A could do all of this to tenant B's
rows — measured, not inferred, on a migrated database as `calevate_app`:

    SET app.tenant_id = A;
    UPDATE engine_agent_routes SET active = false WHERE tenant_id = B;   -->  UPDATE 1
    DELETE FROM engine_agent_routes            WHERE tenant_id = B;      -->  DELETE 1
    UPDATE engine_agent_routes SET tenant_id = A WHERE tenant_id = B;    -->  UPDATE 1

Row three is the interesting one: it re-points another client's inbound calls at your own
agent. Rows one and two silence them. Every one of the forty-two tenant-isolated tables
refuses the same three; this table refused none, because an exemption written for a read
was applied to every verb.

THIS IS A BUG CLASS THIS REPO HAS ALREADY FIXED ONCE. `e4f2a86b13d7` — "A tenant cannot
DELETE a global DNC row — WITH CHECK never guarded that verb" — is the same shape on
`dnc_list`: a table with a deliberately-widened READ, where the widening quietly widened
the writes too. `dnc_list` came out of that with an asymmetric policy. This is the second
table with the same shape and it never got the same treatment.

--------------------------------------------------------------------------------
THE POLICY, AND WHY IT IS TWO POLICIES
--------------------------------------------------------------------------------

    engine_agent_routes_global_read   FOR SELECT  USING (true)
    tenant_isolation                  FOR ALL     USING/WITH CHECK
                                                  (tenant_id = GUC OR GUC IS NULL)

Permissive policies are OR'd PER COMMAND, and `FOR SELECT` only participates in SELECT.
So a read is global — unchanged, which is the whole point of the exemption — while
INSERT, UPDATE and DELETE see only the second policy. Writing it as one `FOR ALL` policy
with `USING (true)` would have widened the writes right back; writing the read half as
`USING (true OR tenant_id = GUC)` would have satisfied the guardrail's "the expression
mentions the GUC" rule while meaning `true`, which is worse than an honest exemption.

`OR GUC IS NULL` — an UNTENANTED session may write any row. That is not a hole, it is the
same asymmetry `a1c8e40f27b9` gave `dnc_list`: a session with no `app.tenant_id` is ops
and workers (`agents/reconciliation.record_drift` stamps `drift_state` across tenants
from no session at all, `untenanted_session` by design), never a client. A client request
always carries the GUC, because `tenant_session` is the only way one reaches the
database.

--------------------------------------------------------------------------------
WHAT CHANGES FOR A CALLER, AND THE ONE BEHAVIOUR THAT IS DELIBERATELY DIFFERENT
--------------------------------------------------------------------------------

Nothing changes for the three writers in the tree. `agents/service.publish_*` upserts its
OWN tenant's route from a tenant session; `agents/experiments.conclude` retires arms
`WHERE tenant_id = :tid`; `agents/reconciliation.record_drift` runs untenanted. All 567
tests touching agents, engine, ingest, dispatch, retention, pipeline, experiments and
drift pass with the policy installed.

One behaviour IS different, and it is an improvement rather than a regression. The
publish path is `INSERT ... ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET
tenant_id = EXCLUDED.tenant_id, ...`. If the conflicting row belonged to a DIFFERENT
tenant, that statement used to silently re-tenant it — one client's vendor agent
reference quietly transferred to another. It now raises:

    new row violates row-level security policy (USING expression) for table
    "engine_agent_routes"

A vendor-generated reference colliding across tenants should not happen; if it ever does,
a refusal an operator can see beats a silent transfer nobody can.

--------------------------------------------------------------------------------
THE TABLE STAYS RLS-EXEMPT IN THE REGISTRY
--------------------------------------------------------------------------------

Its read really is global, so it cannot satisfy `check_rls_coverage`'s rule that every
permissive policy's USING clause consults the GUC, and pretending otherwise would be the
dishonest `true OR ...` above. The exemption's REASON is amended in the same change to
say which verbs it now covers, and `rls_sweep_test` gains the behavioural pin: no
RLS-exempt table that carries a `tenant_id` may let a tenant session modify or destroy
another tenant's existing row.

DOWNGRADE: exact — both policies dropped, RLS disabled and un-FORCEd, back to a table
with no row security. Nothing else in the schema references them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4b70e928a1f"
down_revision: str | None = "a2e9f31c605d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "engine_agent_routes"
READ_POLICY = "engine_agent_routes_global_read"
WRITE_POLICY = "tenant_isolation"

# Spelled out rather than shared with the other migrations that write it: a migration is
# a snapshot of the schema on the day it ran (the rule c2f7a91b4e63 states). NULLIF on
# the empty string is the repo-wide form — `SET LOCAL app.tenant_id = ''` must read as
# "no tenant", not fail the ::uuid cast.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT_OR_OPS = f"(tenant_id = ({_GUC})::uuid OR {_GUC} IS NULL)"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee holds for the table owner too — without it, the owner is
    # exempt and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {READ_POLICY} ON {TABLE} FOR SELECT USING (true)")
    op.execute(
        f"CREATE POLICY {WRITE_POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT_OR_OPS} WITH CHECK {_OWN_TENANT_OR_OPS}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {WRITE_POLICY} ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
