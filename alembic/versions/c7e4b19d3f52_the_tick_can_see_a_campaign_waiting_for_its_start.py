"""the dispatch tick can see a campaign waiting for its start time

Revision ID: c7e4b19d3f52
Revises: a1c7d4e93b02
Create Date: 2026-08-14 10:40:00.000000

`campaigns.schedule` had no reader. Closing it means the dispatch tick has to find a
campaign whose start time has arrived — and `campaigns` is FORCE-RLS'd (05bba2f3c19c),
so "which tenants have one" is a question that only exists inside a tenant session.
That is precisely the shape D-57 spent a migration removing from this tick, and
re-introducing a per-tenant sweep to find scheduled campaigns would put the 12,070
sessions back for a feature that fires a handful of times a day.

So the scan answers it, in the same walk, under the same per-tenant `app.tenant_id`:
`dispatch_scan()` gains a fourth output column, `has_due_schedule`.

**THE COLUMN ANSWERS "IS ONE DUE", NOT "IS THERE ONE" — and that was a correction.**
--------------------------------------------------------------------------------------
The first version of this migration asked the looser question (`status = 'scheduled'`,
a bare literal) and left the due comparison entirely to
`apps/api/campaigns/scheduling.py`, on the argument that one definition of "due" is
better than two. `tests/dispatch_scale_test.py` refused it, correctly: a campaign
scheduled for next month is not WORK, and under the loose question its tenant paid a
`tenant_session` every 30 seconds for a month — 2,880 sessions a day per pending
schedule, for a tick whose entire property (D-57) is that its cost is proportional to
work. The invariant that test states is "the tick opens no session for a tenant with
nothing to dial", and it is the invariant worth keeping.

So the predicate is here, and the two objections that pushed it out are answered rather
than ignored:

- **DRIFT.** This is a SCREEN, not the definition — the same relationship
  `engine_agent_routes` already has with the tick, and stated the same way: it is a
  proven SUPERSET of what a tick must visit, never a narrower set. `due_schedules()`
  remains the sole authority on what a schedule MEANS (the `kind` discriminator that
  keeps an unbuilt recurrence from firing once, the offset requirement, the parse). A
  superset that lets through a row the service then declines costs one session; a subset
  would silently never start a campaign, which is why the asymmetry is the whole design.
  `tests/campaign_schedule_test.py` pins both directions — a far-future schedule is not
  visited, and a `kind` this build cannot run is visited and refused.
- **BLAST RADIUS.** `(schedule->>'start_at')::timestamptz` raises on a malformed value,
  and this loop runs across EVERY tenant on the platform in ONE function call: one bad
  row in one tenant would abort the scan for everybody, a platform-wide dial outage from
  a single JSON string. `pg_input_is_valid(text, text)` (PG16) tests the cast without
  performing it, and it is wrapped in a `CASE` rather than `AND`-ed, because SQL does not
  guarantee `AND` short-circuits — a planner free to evaluate the cast first would
  reintroduce exactly the abort the guard exists to prevent. An unparseable value
  therefore reads as "not due" here and is alerted on by `_parse_schedule` when the
  service looks at it, which is the surface that can say WHICH campaign.

`ix_campaigns_scheduled` is the exact twin of `ix_campaigns_running` from a8d4f21c9b06,
and for the same reason: 'scheduled' is a LITERAL inside the function body, so the
planner can prove the query's qual implies the partial index's predicate and use it
(PG16 §11.8). Fully partial, tenant_id only — the JSON comparison is a filter over the
handful of rows it admits, not something to index. It cannot BE indexed anyway: a
text-to-timestamptz cast is STABLE, not IMMUTABLE (its result depends on the session
TimeZone for strings without an offset), and Postgres refuses a non-immutable index
expression.

**NO NEW TABLE, SO NO NEW RLS POLICY.** Nothing here carries `tenant_id` of its own: one
partial index on `campaigns`, which already has `tenant_isolation` FORCEd, and one
replacement function that is still `SECURITY INVOKER` and still sets `app.tenant_id` to
exactly one tenant before every statement it runs. An index changes which rows a plan
can REACH, never which rows a policy admits.

The function is DROPped and re-CREATEd rather than `CREATE OR REPLACE`d: Postgres
refuses to replace a function whose OUT parameters change, which is what adding a
result column is.

Reversible: `downgrade()` restores the three-column function verbatim from a8d4f21c9b06
and drops the index. The worker reads the fourth column by name, so a downgrade without
a matching code rollback fails loudly rather than silently never firing a schedule —
which is the correct direction for a column whose absence means "no campaign ever
starts".
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e4b19d3f52"
down_revision: str | Sequence[str] | None = "a1c7d4e93b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "dispatch_scan"
SCHEDULED_INDEX = "ix_campaigns_scheduled"

# Still one statement per tenant (a8d4f21c9b06 measured the SPI round trip as the cost
# that mattered at this iteration count): the third question rides along in the same
# SELECT rather than adding a second one.
_FUNCTION_SQL_V2 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (
    scanned_tenant_id uuid,
    active_outbound integer,
    has_running_campaign boolean,
    has_due_schedule boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    live integer;
    running boolean;
    due boolean;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT (SELECT count(*) FROM calls c
                 WHERE c.direction = 'outbound'
                   AND c.status = ANY (active_statuses)
                   AND c.updated_at > now() - active_horizon),
               (SELECT EXISTS (SELECT 1 FROM campaigns c WHERE c.status = 'running')),
               (SELECT EXISTS (SELECT 1 FROM campaigns c
                                WHERE c.status = 'scheduled'
                                  AND CASE WHEN pg_input_is_valid(
                                                  c.schedule->>'start_at', 'timestamptz')
                                           THEN (c.schedule->>'start_at')::timestamptz <= now()
                                           ELSE false END))
          INTO live, running, due;
        IF live > 0 OR running OR due THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            has_due_schedule := due;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

# Verbatim from a8d4f21c9b06 — the downgrade target, kept whole rather than patched, so
# a rollback lands on the function that revision's tests describe.
_FUNCTION_SQL_V1 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
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
        f"CREATE INDEX {SCHEDULED_INDEX} ON campaigns (tenant_id) WHERE status = 'scheduled'"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V2)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V1)
    op.execute(f"DROP INDEX {SCHEDULED_INDEX}")
