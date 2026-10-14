"""call_reply_scan(): every client's finished calls and their reply times, in one statement

Revision ID: d3f8b2c6a417
Revises: b9d4e2a7c6f1
Create Date: 2026-10-14 18:00:00.000000

The admin "Voice response time" screen (D-770) reports ThinnestAI's own per-call quality
figures (`calls.engine_quality`, migration a5d1c7e93f28) across every client. `calls`,
`agents`, `call_engine_signals` and `usage_events` are tenant-scoped with FORCEd RLS, and
`app.admin` widens `organizations` only (b57e2f9c4a13), so the report must enter each
client under its own `app.tenant_id`.

It does that inside Postgres, the way `dispatch_scan` (a8d4f21c9b06) does: a SECURITY
INVOKER loop that binds `app.tenant_id` to one tenant per statement, so the per-client walk
costs a `set_config` rather than a pooled session each. The rejected alternative is
`SECURITY DEFINER` under a `BYPASSRLS` owner, which is a hard-rule-1 bypass however narrow
its columns are today. The tenant list comes from `organizations`, which the caller can only
enumerate inside an `admin_session()`; called from any other session the loop sees at most
the caller's own tenant.

One row per COMPLETED call that started at or after `since` — completed calls are the ones
the platform measures, and the screen needs the unmeasured ones too, to say whether an
empty window means "no calls" or "calls, but no figures". Numbers only: the quality object
is numbers-or-null by `ck_calls_engine_quality_is_numbers`, and nothing here is text a
caller said (hard rule 6). `voice_tier` is the rung the call's minutes were metered on
(`usage_events.meta.voice_tier`), NULL for a call not yet metered.

NO NEW TABLE, SO NO NEW POLICY. Reversible: `downgrade()` drops the function.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3f8b2c6a417"
down_revision: str | None = "b9d4e2a7c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "call_reply_scan"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    call_id uuid,
    agent_id uuid,
    agent_name text,
    started_at timestamptz,
    quality jsonb,
    slow_reply boolean,
    voice_tier text
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, c.id, c.agent_id, a.name::text, c.started_at, c.engine_quality,
                   EXISTS (SELECT 1 FROM call_engine_signals s
                           WHERE s.engine_call_id = c.engine_call_id AND s.kind = 'slow_reply'),
                   (SELECT max(u.meta ->> 'voice_tier') FROM usage_events u
                     WHERE u.call_id = c.id)
              FROM calls c
              LEFT JOIN agents a ON a.id = c.agent_id
             WHERE c.started_at >= since AND c.status = 'completed';
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
