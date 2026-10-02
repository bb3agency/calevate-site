"""Count the carrier lines in use, both directions, platform-wide (D-663)

Revision ID: a6d3b9f52e18
Revises: f5c2a8e41d07
Create Date: 2026-10-02 00:00:00.000000

The carrier account has a fixed number of simultaneous calls (Vobiz answers the excess with
`429 Too Many Requests`, `vobiz-findings/mirror/pages/call/make-call.md:134`, and an inbound
caller over the limit is refused). Inbound and outbound share that number, so the dial gate
in `agents.service.dispatch_call` has to count both before it places a call.

`carrier_lines_in_use(p_carrier, live_horizon, ring_horizon)` returns that count for one
carrier. A row is a line in use when it is on that carrier and either

* `ringing` / `in_progress` and created within `live_horizon` (the longest call an agent may
  run, plus a margin), or
* `queued` and created within `ring_horizon` (the dial's ring timeout, plus a margin).

The horizons are what let a row stranded by a lost callback age out instead of holding a
line for ever; the caller passes them so the constants live in one Python module.

SECURITY INVOKER, one statement per tenant, the construction `dispatch_scan` (a8d4f21c9b06)
and `queued_dial_scan` (a7e3b91c04df) use and for their reason: `calls` is FORCE-RLS'd, so an
untenanted count reads zero for every tenant. The tenant set is `engine_agent_routes`, the
same set those two walk: a call belongs to an agent, and an agent that was ever published has
a route. The entry `app.tenant_id` is restored before returning, so the dial gate can call it
inside its own tenant session and go on writing under that tenant.

An INBOUND row with a NULL carrier is counted against every carrier. The worker writes an
inbound row during the call without knowing the carrier, and the carrier's hangup callback
stamps it afterwards, so a caller on the line right now is exactly such a row; over-counting
idles one outbound line, under-counting turns a caller away. An outbound row with a NULL
carrier predates the column (the dial gate stamps every new one) and is not counted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6d3b9f52e18"
down_revision: str | None = "f5c2a8e41d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "carrier_lines_in_use"

_SQL = f"""
CREATE FUNCTION {FUNCTION}(
    p_carrier text,
    live_horizon interval,
    ring_horizon interval
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    in_use integer := 0;
    here integer;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT count(*) INTO here
          FROM calls c
         WHERE c.tenant_id = t
           AND (c.carrier = p_carrier OR (c.carrier IS NULL AND c.direction = 'inbound'))
           AND (
                (c.status IN ('ringing', 'in_progress')
                 AND c.created_at > now() - live_horizon)
             OR (c.status = 'queued' AND c.created_at > now() - ring_horizon)
           );
        in_use := in_use + here;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
    RETURN in_use;
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text, interval, interval)")
