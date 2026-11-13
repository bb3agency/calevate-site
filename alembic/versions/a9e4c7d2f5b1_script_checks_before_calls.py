"""The call-mistake checks run on live scripts before any call (D-989)

Revision ID: a9e4c7d2f5b1
Revises: c4e8a2f6d1b9
Create Date: 2026-11-13 12:00:00.000000

* `agent_mistake_fixes.found_by`: `call` (a real call showed the kind, D-985) or
  `script_check` (the sweep of live scripts found its cause before any call, D-989), so the
  operator's board and the owner's notice say which.
* `agents.script_checked_version`: the live script version the sweep last checked, so an
  agent is checked again only when its live script changed.
* `heal_client_incidents.kind` gains `script_check_fixed` and `script_check_waiting`, the
  owner's two notices for a fix the sweep opened.
* `agent_mistake_fix_scan(since)` also returns `found_by` (its return type changes, so it is
  dropped and created again); `agent_script_check_due(n)` lists up to `n` live or paused
  agents whose live script version differs from the one last checked, entering each client
  under its own `app.tenant_id` as the scan does.

REVERSIBILITY. `downgrade()` drops the new function, puts the earlier scan back, turns the two
new notice kinds into their call-found twins before restoring the narrower CHECK, and drops
both columns; which fixes the sweep opened is also in each fix's incident trigger code.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "a9e4c7d2f5b1"
down_revision: str | None = "c4e8a2f6d1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXES = "agent_mistake_fixes"
CLIENT = "heal_client_incidents"
SCAN = "agent_mistake_fix_scan"
DUE = "agent_script_check_due"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
_FOUND_BY = ("call", "script_check")
_OLD_KINDS = ("agent_unwell", "line_protected", "platform_outage", "script_fixed", "script_fix_waiting")
_NEW_KINDS = (*_OLD_KINDS, "script_check_fixed", "script_check_waiting")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _scan_sql(*, found_by: bool) -> str:
    """`agent_mistake_fix_scan` as c4e8a2f6d1b9 made it, with `found_by` when asked."""
    column = "\n    found_by text," if found_by else ""
    value = " f.found_by," if found_by else ""
    return f"""
CREATE OR REPLACE FUNCTION {SCAN}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    fix_id uuid,
    agent_id uuid,
    agent_name text,
    kind text,
    state text,
    ended_because text,
    attempts integer,
    version_before integer,
    version_after integer,
    live_at timestamptz,
    settled_at timestamptz,{column}
    created_at timestamptz
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
            SELECT t, f.id, f.agent_id, a.name::text, f.kind, f.state, f.ended_because,
                   f.attempts::integer, f.version_before, f.version_after, f.live_at,
                   f.settled_at,{value} f.created_at
              FROM {FIXES} f JOIN agents a ON a.id = f.agent_id
             WHERE f.created_at >= since OR f.state IN ('fixing', 'live');
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


# The live version is the live pointer's, else the draft pointer's: `live_prompt_id` is NULL
# when the two agree (`prompts.insert_prompt_version`).
_DUE_SQL = f"""
CREATE OR REPLACE FUNCTION {DUE}(n integer)
RETURNS TABLE (
    scanned_tenant_id uuid,
    agent_id uuid,
    live_version integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    found integer := 0;
    got integer;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        EXIT WHEN found >= n;
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, a.id, v.version
              FROM agents a
              JOIN prompt_versions v ON v.id = COALESCE(a.live_prompt_id, a.system_prompt_id)
             WHERE a.deleted_at IS NULL AND a.status IN ('live', 'paused')
               AND a.script_checked_version IS DISTINCT FROM v.version
             ORDER BY a.id
             LIMIT n - found;
        GET DIAGNOSTICS got = ROW_COUNT;
        found := found + got;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        FIXES, sa.Column("found_by", sa.Text(), nullable=False, server_default="call")
    )
    op.create_check_constraint(
        op.f(f"ck_{FIXES}_found_by_enum"), FIXES, _in("found_by", _FOUND_BY)
    )
    op.add_column("agents", sa.Column("script_checked_version", sa.Integer(), nullable=True))
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _NEW_KINDS))
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(timestamptz)")
    op.execute(_scan_sql(found_by=True))
    op.execute(_DUE_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {DUE}(integer)")
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(timestamptz)")
    op.execute(_scan_sql(found_by=False))
    op.execute(f"ALTER TABLE {CLIENT} NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            f"UPDATE {CLIENT} SET kind = CASE kind WHEN 'script_check_fixed' THEN 'script_fixed' "
            "ELSE 'script_fix_waiting' END, updated_at = now() "
            "WHERE kind IN ('script_check_fixed', 'script_check_waiting')"
        ),
        note="Turned the script-check notices into the call-found script-fix notices.",
    )
    op.execute(f"ALTER TABLE {CLIENT} FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _OLD_KINDS))
    op.drop_column("agents", "script_checked_version")
    op.drop_constraint(op.f(f"ck_{FIXES}_found_by_enum"), FIXES, type_="check")
    op.drop_column(FIXES, "found_by")
