"""The halt and a DNC addition reach a dial that is already ringing

Revision ID: b7e4c0a63f29
Revises: a6d3b9f52e18
Create Date: 2026-10-02 00:00:00.000000

`queued_dial_scan` matched `status = 'queued'` only. On the owned runtime the carrier's
`Ring` callback moves the row to `ringing` (`apps/api/engine/vobiz.parse_event`), so a
phone that was already ringing when the big red switch was thrown, or when its number was
added to the DNC list, was not in the scan and kept ringing until somebody answered it.
Ending a ringing call is the same carrier request as ending a queued one (`end_call`), so
the scan now matches both.

`in_progress` stays out: a call somebody has answered is a conversation, and cutting it off
mid-sentence is a different decision from stopping a dial. The halt stops new dials and
recalls unanswered ones; it does not hang up on a person who is talking.

Same signature, so `CREATE OR REPLACE` replaces the body in place (no overload to drop) and
the callers in `workers/dial_recall.py` are unchanged. Every other line of the body is
`a7e3b91c04df`'s.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e4c0a63f29"
down_revision: str | None = "a6d3b9f52e18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "queued_dial_scan"


def _body(statuses: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(
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
               AND c.status IN ({statuses})
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


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_body("'queued', 'ringing'"))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_body("'queued'"))
