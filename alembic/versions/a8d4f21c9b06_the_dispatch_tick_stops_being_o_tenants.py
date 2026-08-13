"""the dispatch tick stops being O(every tenant that ever published an agent)

Revision ID: a8d4f21c9b06
Revises: d2b6f04a17c9
Create Date: 2026-08-13 14:05:00.000000

`dispatch_campaign_tick` is scheduled `second={0, 30}` and its screening phase cost one
`tenant_session` — a pool checkout, a `SET LOCAL` for RLS, one SELECT, a COMMIT — for
EVERY tenant with a published agent. Measured on a 33,298-organization / 12,070-route
development database (D-57, and `tests/dispatch_scale_test.py` is the instrument):

    12,070 tenant sessions · 22.87s   — for a job whose interval is 30 seconds

and the split of that 22.87s, which is what decided the shape of this migration:

    session setup (checkout + pre_ping + BEGIN + set_config)  11.02s   48%
    the per-tenant SELECT itself                               6.76s   30%
    COMMIT + return to pool                                    4.91s   21%
    the tenant-list query                                      0.28s    1%

**Two thirds of the tick was session machinery, not query time**, and 80% of the wall
clock was CPU burnt in the worker process rather than waiting on Postgres — so
parallelising the loop measured 22.9s → 17.2s at 8-way (1.3x, not 8x: one asyncio loop
cannot parallelise its own CPU). The cost had to be removed, not spread.

D-57 removes it by moving the screening loop INTO Postgres, where re-scoping to a
tenant is a `set_config` call rather than a connection round trip. This migration is
that function plus the two indexes it probes.

**NO NEW TABLE, SO NO NEW RLS POLICY** — stated rather than left to be inferred, the
way `d2b6f04a17c9` states it. Nothing here carries `tenant_id`: two partial indexes on
tables that already have `tenant_isolation` FORCEd (`calls`, `campaigns`, migration
05bba2f3c19c) and one function. An index changes which rows a plan can REACH, never
which rows a policy admits; `scripts/check_rls_coverage.py` reads the live catalog and
would say so if that were wrong.

1. `dispatch_scan(active_statuses, active_horizon)` — SECURITY INVOKER, no exemption
-----------------------------------------------------------------------------------
The function loops over `engine_agent_routes` (the global, deliberately un-RLS'd
routing bridge — `db/registry.py` records why it may be global) and for each tenant
does exactly what the worker's loop did: set `app.tenant_id` to that ONE tenant, then
ask its two screening questions under that tenant's own policies.

**It is `SECURITY INVOKER` (the default, written out because the default is the
load-bearing part).** It runs as the calling role with that role's policies applied to
every statement; it holds no grant the caller lacks. The rejected alternative is the
one every "cross-tenant aggregate" answer on the internet reaches for first —
`SECURITY DEFINER` owned by a role with `BYPASSRLS`, which returns the same three
columns 100x faster and is a hard-rule-1 violation wearing a function's clothes: it
would put a role that cannot see RLS on the dial path, and the next reader would
reasonably add a fourth column to it. pganalyze's write-up of exactly this trade
("a function marked SECURITY DEFINER and owned by a superuser can bypass RLS if not
managed carefully ... SECURITY INVOKER is preferred for multi-tenant scenarios") is the
short version. We take the 100x and keep the policy.

What it therefore is NOT: a widening. Every statement inside runs with `app.tenant_id`
bound to exactly one tenant, which is the same guarantee `db/session.py`'s
`tenant_session` gives; the loop just does not pay a connection for each. Postgres
re-evaluates the policy's `current_setting('app.tenant_id')` per statement (it is
STABLE — constant within a statement, not across them), and
`tests/dispatch_scan_rls_test.py` proves it on data rather than on that sentence: two
tenants with different live-call counts must come back with their own numbers, which a
plan-cached or leaked GUC could not produce.

`active_statuses` and `active_horizon` are PARAMETERS, not literals, so
`ACTIVE_STATUSES` and `ACTIVE_CALL_HORIZON` keep exactly one definition — in
`apps/workers/campaign_dispatch.py`, where the FLOWS §5 rules that justify them live. A
function body that repeated them would be a second source of truth that no test can see
drifting, and the failure mode is silent over-dialling.

The GUC is restored to whatever the caller had on the way out. It is transaction-local
either way (`set_config(..., true)`), so an aborted transaction resets it regardless;
restoring is for the caller that keeps using its session afterwards.

2. `ix_calls_outbound_live` — partial on `direction`, INDEXED on `status`
-------------------------------------------------------------------------
    (tenant_id, status, updated_at) WHERE direction = 'outbound'

The obvious index is fully partial — `WHERE direction = 'outbound' AND status IN
('queued','ringing','in_progress')` — and it would never be used. A partial index is
only chosen when the planner can PROVE the query's quals imply the index predicate at
PLAN time (PG16 §11.8), and the scan asks `status = ANY($1)`: `$1` is a bind parameter,
so nothing about its contents is provable when the plan is built. Putting `status` in
the KEY instead is what makes a parameterised list usable — btree handles
`ScalarArrayOpExpr` as an index qual — and it is what lets the constant stay in Python.

Measured on 1,001,813 `calls` rows over 12,070 tenants: the scan runs 2.65s without it
(index scan on `ix_calls_tenant_id`, which walks all 83 historical calls per tenant) and
1.11s with it, index-only, `Heap Fetches: 0`. Size: 56 MB, built in 1.16s. That is the
whole justification — this probe must cost O(live calls), not O(call history), or it
degrades every month the platform is alive while looking unchanged.

3. `ix_campaigns_running` — fully partial, because here the predicate IS a literal
----------------------------------------------------------------------------------
    (tenant_id) WHERE status = 'running'

'running' is written into the function, so the implication is provable and the index
holds only the campaigns a tick could act on: 16 kB for 289 rows out of 24,141
campaigns. Index-only scan, `Heap Fetches: 0`.

Plain `CREATE INDEX`, not `CONCURRENTLY`, following `d2b6f04a17c9` and every other
index in this tree: alembic runs a migration in one transaction and `CONCURRENTLY`
cannot. `SET LOCAL lock_timeout = '3s'` is the guard — `calls` is the busiest table
here and a build that cannot take its lock in three seconds must fail the deploy rather
than block the post-call pipeline behind it.

Reversible: `downgrade()` drops the function and both indexes. Nothing reads them
afterwards — the worker's own fallback is not "run slower", it is an error, which is
correct: a dispatcher that silently reverted to a 23-second tick is the failure this
whole revision exists to make impossible to have quietly.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8d4f21c9b06"
down_revision: str | Sequence[str] | None = "d2b6f04a17c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "dispatch_scan"
CALLS_INDEX = "ix_calls_outbound_live"
CAMPAIGNS_INDEX = "ix_campaigns_running"

# One statement per tenant, not two: folding the count and the EXISTS into a single
# SELECT halved the loop (measured 1.11s -> 0.24s at 12,070 tenants), because at this
# iteration count the SPI round trip costs more than either question does.
_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (scanned_tenant_id uuid, active_outbound integer, has_running_campaign boolean)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    live integer;
    running boolean;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT (SELECT count(*) FROM calls c
                 WHERE c.direction = 'outbound'
                   AND c.status = ANY (active_statuses)
                   AND c.updated_at > now() - active_horizon),
               (SELECT EXISTS (SELECT 1 FROM campaigns c WHERE c.status = 'running'))
          INTO live, running;
        IF live > 0 OR running THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"CREATE INDEX {CALLS_INDEX} ON calls (tenant_id, status, updated_at) "
        "WHERE direction = 'outbound'"
    )
    op.execute(f"CREATE INDEX {CAMPAIGNS_INDEX} ON campaigns (tenant_id) WHERE status = 'running'")
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(f"DROP INDEX {CAMPAIGNS_INDEX}")
    op.execute(f"DROP INDEX {CALLS_INDEX}")
