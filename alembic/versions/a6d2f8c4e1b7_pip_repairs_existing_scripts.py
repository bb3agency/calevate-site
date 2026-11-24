"""Pip repairs the lines of an existing script the script checks fault

Revision ID: a6d2f8c4e1b7
Revises: b3d7e1f94a26
Create Date: 2026-11-24 13:00:00.000000

The script checks (`script_lint.flow_problems`, the call-mistake checks) ran only when Pip
wrote a new draft, so a campaign's or inbound line's script written before a check existed
kept the fault on every call. Each holder gets the agent-pass columns (`agents/agent_pass`)
for the repair pass (`agents/script_heal`): `script_heal_state`, `script_heal_at` and
`script_heal_inputs`, the last the md5 of the script it last checked joined with the checks'
version, so an unchanged script is never checked twice. `script_heal_fixed` maps each call
mistake kind the pass cleared from the script to when, which the call page reads to say the
script was repaired rather than "our team has been told".

`script_heal_scan(stale_minutes, retry_minutes, checks)` is the hourly sweep's worklist in one
statement, `call_reply_scan`'s shape (d3f8b2c6a417): a SECURITY INVOKER loop that enters each
organization under its own `app.tenant_id`, called from an `admin_session()`, so no policy is
bypassed. It names the open structured scripts not checked in their current form, whose pass
was skipped, failed longer than `retry_minutes` ago, or died; a finished campaign is left out.

NO NEW TABLE, SO NO NEW POLICY: both tables keep their FORCEd `tenant_isolation`.
Reversible: `downgrade()` drops the function, the CHECKs and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a6d2f8c4e1b7"
down_revision: str | None = "b3d7e1f94a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES` (the agent-pass ladder), frozen at this revision.
_STATES = ("queued", "running", "done", "failed", "skipped")
_TABLES = ("campaigns", "inbound_lines")
SCAN = "script_heal_scan"


def _due(alias: str) -> str:
    return f"""
               {alias}.archived_at IS NULL
               AND jsonb_typeof({alias}.script) = 'object'
               AND COALESCE(jsonb_typeof({alias}.script -> 'raw_override'), 'null') = 'null'
               AND ({alias}.script_heal_state IS NULL
                    OR {alias}.script_heal_state = 'skipped'
                    OR ({alias}.script_heal_state = 'done'
                        AND {alias}.script_heal_inputs IS DISTINCT FROM
                            md5({alias}.script::text || checks))
                    OR ({alias}.script_heal_state = 'failed'
                        AND {alias}.script_heal_at < now() - make_interval(mins => retry_minutes))
                    OR ({alias}.script_heal_state IN ('queued', 'running')
                        AND {alias}.script_heal_at < now() - make_interval(mins => stale_minutes)))"""


_SCAN_SQL = f"""
CREATE OR REPLACE FUNCTION {SCAN}(stale_minutes integer, retry_minutes integer, checks text)
RETURNS TABLE (scanned_tenant_id uuid, kind text, holder_id uuid)
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
            SELECT t, 'campaign'::text, c.id
              FROM campaigns c
             WHERE c.status NOT IN ('completed', 'cancelled') AND {_due("c")}
            UNION ALL
            SELECT t, 'line'::text, l.id
              FROM inbound_lines l
             WHERE {_due("l")};
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.add_column(table, sa.Column("script_heal_state", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("script_heal_inputs", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("script_heal_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "script_heal_fixed",
                JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_script_heal_state_enum"),
            table,
            f"script_heal_state IS NULL OR script_heal_state IN {_STATES!r}",
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_script_heal_fixed_object"),
            table,
            "jsonb_typeof(script_heal_fixed) = 'object'",
        )
    op.execute(_SCAN_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(integer, integer, text)")
    for table in _TABLES:
        op.drop_constraint(op.f(f"ck_{table}_script_heal_fixed_object"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_script_heal_state_enum"), table, type_="check")
        op.drop_column(table, "script_heal_fixed")
        op.drop_column(table, "script_heal_at")
        op.drop_column(table, "script_heal_inputs")
        op.drop_column(table, "script_heal_state")
