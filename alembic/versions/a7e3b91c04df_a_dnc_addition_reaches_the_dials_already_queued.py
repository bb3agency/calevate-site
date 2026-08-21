"""A DNC addition can reach the dials the vendor is already holding — D-428(b)

Revision ID: a7e3b91c04df
Revises: d5c81f30ab47

WHAT THIS OPENS. D-428 split the recall in two and shipped only the halt half
(d5c81f30ab47): `queued_dial_scan(max_rows)` walks the WHOLE fleet, which is right for the
big red switch and useless for a suppression, where the question is "which queued dials go
to THIS number". Until now a DNC addition closed `check_dispatch` for the next tick and
never reached the queue the vendor is holding — so a number suppressed at 20:58 could ring
at 21:01 from a dial accepted before the suppression existed.

WHY THE SAME FUNCTION AND NOT A SECOND ONE. The scan's hard part is not the predicate, it
is the SECURITY INVOKER tenant loop: `calls` is FORCE-RLS'd, so an untenanted probe returns
zero rows for every tenant and reads exactly like an empty queue. A sibling function would
be a second copy of that construction to review, and the two would answer differently the
day one of them was fixed. So the filter is a parameter and the loop is one thing.

DROPPED AND RECREATED rather than `CREATE OR REPLACE`, because adding a parameter — even a
defaulted one — creates an OVERLOAD rather than replacing the function, and
`queued_dial_scan(500)` would then be ambiguous between the two and fail at the call site
with a Postgres error nobody would connect to a migration. The one-argument call in
`workers/dial_recall.py` keeps working against the new signature because both new
parameters default to NULL.

THE TWO FILTERS ARE INDEPENDENT AND BOTH ARE NULLABLE, because three callers need three
combinations and inventing a sentinel for "no filter" is how a scan silently starts
matching nothing:

* `p_phones NULL, p_tenant NULL`   the halt: every queued dial in the fleet.
* `p_phones set, p_tenant set`     a tenant's own DNC entry — that client's dials only.
* `p_phones set, p_tenant NULL`    a GLOBAL suppression, which outranks every tenant's own
                                   list and therefore has to reach every tenant's queue.

`recall_requested_at IS NULL` stays in the predicate for all three. A dial the halt already
stopped does not need a second stop, and the stamp is what makes both paths idempotent —
re-POSTing a stop for an already-stopped execution takes the vendor's refusal and reports a
failure on work that succeeded.

NO NEW INDEX, for the reason the previous migration gives: `ix_calls_outbound_live` is
`(tenant_id, status, updated_at) WHERE direction = 'outbound'` and its leading columns
answer the predicate; `to_e164` is a residual filter over the handful of rows a single
tenant has queued at once, which is bounded by the account's concurrency ceiling rather
than by the size of the table.
"""

from __future__ import annotations

from alembic import op

revision = "a7e3b91c04df"
down_revision = "d5c81f30ab47"
branch_labels = None
depends_on = None

FUNCTION = "queued_dial_scan"

_NEW_SQL = f"""
CREATE FUNCTION {FUNCTION}(
    max_rows integer,
    p_phones text[] DEFAULT NULL,
    p_tenant uuid DEFAULT NULL
)
RETURNS TABLE (scanned_tenant_id uuid, call_id uuid, engine_call_id text)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    emitted integer := 0;
BEGIN
    FOR t IN
        SELECT DISTINCT r.tenant_id
          FROM engine_agent_routes r
         WHERE p_tenant IS NULL OR r.tenant_id = p_tenant
         ORDER BY 1
    LOOP
        EXIT WHEN emitted >= max_rows;
        PERFORM set_config('app.tenant_id', t::text, true);
        FOR call_id, engine_call_id IN
            SELECT c.id, c.engine_call_id
              FROM calls c
             WHERE c.direction = 'outbound'
               AND c.status = 'queued'
               AND c.recall_requested_at IS NULL
               AND c.engine_call_id NOT LIKE 'local:%'
               AND (p_phones IS NULL OR c.to_e164 = ANY(p_phones))
             ORDER BY c.created_at
             LIMIT max_rows - emitted
        LOOP
            scanned_tenant_id := t;
            emitted := emitted + 1;
            RETURN NEXT;
        END LOOP;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

_OLD_SQL = f"""
CREATE FUNCTION {FUNCTION}(max_rows integer)
RETURNS TABLE (scanned_tenant_id uuid, call_id uuid, engine_call_id text)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    emitted integer := 0;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        EXIT WHEN emitted >= max_rows;
        PERFORM set_config('app.tenant_id', t::text, true);
        FOR call_id, engine_call_id IN
            SELECT c.id, c.engine_call_id
              FROM calls c
             WHERE c.direction = 'outbound'
               AND c.status = 'queued'
               AND c.recall_requested_at IS NULL
               AND c.engine_call_id NOT LIKE 'local:%'
             ORDER BY c.created_at
             LIMIT max_rows - emitted
        LOOP
            scanned_tenant_id := t;
            emitted := emitted + 1;
            RETURN NEXT;
        END LOOP;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(integer)")
    op.execute(_NEW_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(integer, text[], uuid)")
    op.execute(_OLD_SQL)
