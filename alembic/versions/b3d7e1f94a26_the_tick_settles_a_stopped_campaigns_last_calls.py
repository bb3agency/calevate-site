"""the tick settles the last calls of a paused or cancelled campaign

Revision ID: b3d7e1f94a26
Revises: a7e3c9d2f5b1
Create Date: 2026-11-24 00:00:00.000000

Pause and Stop let a call that is already ringing finish. Its contact stays `dialing`
until the tick settles it (`campaign_dispatch._reap_stuck_dialing`: rung out back on the
ladder, answered-but-unclaimed `connected`), and the tick only visited tenants
`dispatch_scan()` flagged with a RUNNING campaign. A cancelled campaign therefore showed
that contact "calling now" for ever, and a paused one until it was resumed.

`has_stopped_dialing` is a sixth column on the same per-tenant walk, under the same
`app.tenant_id`, the construction d8f31a7c2409 used for call-backs: is there a paused or
cancelled campaign still holding a `dialing` contact. It is bounded work, not standing
work: the settle ends every such contact within `STUCK_DIALING_AFTER`, and pending
contacts of a stopped campaign are never claimed (the claim requires `running`). The probe
per stopped campaign is one lookup on `ix_campaign_contacts_due (campaign_id, status, ...)`.

No table, no RLS change, no DML. Reversible: `downgrade()` restores d8f31a7c2409's
five-column function verbatim.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b3d7e1f94a26"
down_revision: str | None = "a7e3c9d2f5b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "dispatch_scan"

_FUNCTION_SQL_V4 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (
    scanned_tenant_id uuid,
    active_outbound integer,
    has_running_campaign boolean,
    has_due_schedule boolean,
    has_due_callback boolean,
    has_stopped_dialing boolean
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
    callback_due boolean;
    stopped_dialing boolean;
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
                                           ELSE false END)),
               (SELECT EXISTS (SELECT 1 FROM scheduled_callbacks s
                                WHERE (s.status = 'scheduled' AND s.requested_at <= now())
                                   OR s.status = 'dialing')),
               (SELECT EXISTS (SELECT 1 FROM campaigns c
                                WHERE c.status IN ('paused', 'cancelled')
                                  AND EXISTS (SELECT 1 FROM campaign_contacts cc
                                               WHERE cc.campaign_id = c.id
                                                 AND cc.status = 'dialing')))
          INTO live, running, due, callback_due, stopped_dialing;
        IF live > 0 OR running OR due OR callback_due OR stopped_dialing THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            has_due_schedule := due;
            has_due_callback := callback_due;
            has_stopped_dialing := stopped_dialing;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

# Verbatim from d8f31a7c2409, the downgrade target.
_FUNCTION_SQL_V3 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (
    scanned_tenant_id uuid,
    active_outbound integer,
    has_running_campaign boolean,
    has_due_schedule boolean,
    has_due_callback boolean
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
    callback_due boolean;
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
                                           ELSE false END)),
               (SELECT EXISTS (SELECT 1 FROM scheduled_callbacks s
                                WHERE (s.status = 'scheduled' AND s.requested_at <= now())
                                   OR s.status = 'dialing'))
          INTO live, running, due, callback_due;
        IF live > 0 OR running OR due OR callback_due THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            has_due_schedule := due;
            has_due_callback := callback_due;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The return type changes, which CREATE OR REPLACE refuses.
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V4)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V3)
