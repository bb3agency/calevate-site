"""calls: each turn's timings; call_reply_scan returns them (D-902)

Revision ID: d8f3a6c1e924
Revises: a9c4e1d7b352
Create Date: 2026-10-27 22:00:00.000000

- `calls.engine_timeline`: where the time went in each turn of the call, as the voice platform
  timed it (`calevate_shared.events.CallTimeline`, dumped): milliseconds from the moment the
  caller stopped speaking to the first sound, the answer, and the split of the wait. Times
  only, no words, so it holds nothing personal. NULL until fetched, and on calls the platform
  timed nothing for. A CHECK keeps it an object holding a `turns` array.
- `call_reply_scan` also returns `engine_timeline`, so the Voice response time screen can give
  the medians of each step by turn detection. A changed return type cannot be `CREATE OR
  REPLACE`d, so the function is dropped and created again in one transaction.

The answer time (`answer_ms_*`) and knowledge turns travel inside `calls.engine_quality`, whose
numbers-only CHECK they already satisfy, so that column is unchanged.

`calls` already carries FORCEd row-level security; a column adds no policy. ADD COLUMN without a
default is a catalog change; the CHECK is added NOT VALID and then validated under
`lock_timeout`. Downgrade restores the earlier function and drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8f3a6c1e924"
down_revision: str | None = "a9c4e1d7b352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "call_reply_scan"
CHECK = "ck_calls_engine_timeline_shape"
_SHAPE = (
    "engine_timeline IS NULL OR (jsonb_typeof(engine_timeline) = 'object' "
    "AND jsonb_typeof(engine_timeline -> 'turns') = 'array')"
)


def _scan_sql(*, with_timeline: bool) -> str:
    """`call_reply_scan` as migration b3f9d2a7c41e left it, plus the timeline when asked.
    Spelled out rather than imported: a migration is a snapshot."""
    column = ",\n    timeline jsonb" if with_timeline else ""
    value = ", c.engine_timeline" if with_timeline else ""
    return f"""
CREATE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    call_id uuid,
    agent_id uuid,
    agent_name text,
    started_at timestamptz,
    quality jsonb,
    slow_reply boolean,
    voice_tier text,
    voice_settings jsonb{column}
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
                     WHERE u.call_id = c.id), c.voice_settings{value}
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
    op.add_column(
        "calls",
        sa.Column("engine_timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(f"ALTER TABLE calls ADD CONSTRAINT {CHECK} CHECK ({_SHAPE}) NOT VALID")
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {CHECK}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.execute(_scan_sql(with_timeline=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.execute(_scan_sql(with_timeline=False))
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {CHECK}")
    op.drop_column("calls", "engine_timeline")
