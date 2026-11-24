"""Pip writes the outcome of every step that has none (D-1036)

Revision ID: c4f1a8d2e7b3
Revises: b3d7e1f94a26
Create Date: 2026-11-24 12:00:00.000000

A step's "Outcome of this step" is Pip's to write, never the owner's to type (D-1036). A
script written before outcomes existed, edited by hand or given a new step has steps with
none, so each campaign and inbound line gets the agent-pass columns (`agents/agent_pass`):
`step_outcomes_state`, `step_outcomes_at` and `step_outcomes_inputs`. The answer itself is
written into the holder's `script`, so there is no answer column. The state is what the call
flow reads to show Pip at work; the inputs hash is what lets the hourly sweep leave a script
it already tried alone until the script changes.

`script_lacks_step_outcome(script)` is the SQL twin of `campaigns/step_outcomes.missing_steps`
(a structured script with stages, a step of which has no outcome, the steps numbered as
`call_script.stage_steps` numbers them); `tests/step_outcomes_test.py` pins the two to the
same answers. `step_outcome_scan(stale_minutes, retry_minutes)` is the sweep's worklist in
one statement, `call_reply_scan`'s shape (d3f8b2c6a417): a SECURITY INVOKER loop that enters
each organization under its own `app.tenant_id`, called from an `admin_session()`, so no
policy is bypassed. It names the open holders lacking an outcome whose pass never ran, was
skipped (Pip off for the account: the sweep asks again each hour), failed longer than
`retry_minutes` ago, or died (queued or running past `stale_minutes`); a finished campaign
is left out.

`calls.step_progress` is where a call got to against those outcomes (`crm/step_progress`):
one reading per step, `reached` / `not_reached` / `unclear`, with turn indexes and step names
only, never the words (hard rule 6). NULL for a call never judged.

NO NEW TABLE, SO NO NEW POLICY: the three tables keep their FORCEd `tenant_isolation`.
Reversible: `downgrade()` drops the two functions, the CHECKs and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f1a8d2e7b3"
down_revision: str | None = "b3d7e1f94a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES` (the agent-pass ladder), frozen at this revision.
_STATES = ("queued", "running", "done", "failed", "skipped")
_TABLES = ("campaigns", "inbound_lines")
LACKS = "script_lacks_step_outcome"
SCAN = "step_outcome_scan"

_LACKS_SQL = f"""
CREATE OR REPLACE FUNCTION {LACKS}(script jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT COALESCE(jsonb_typeof(script -> 'stages') = 'array', false)
       AND jsonb_array_length(script -> 'stages') > 0
       AND COALESCE(jsonb_typeof(script -> 'raw_override'), 'null') = 'null'
       AND EXISTS (
           SELECT 1
             FROM (
                 SELECT CASE WHEN bool_and(jsonb_typeof(st -> 'step') = 'number') OVER ()
                             THEN (st ->> 'step')::int ELSE ord::int END AS step
                   FROM jsonb_array_elements(script -> 'stages') WITH ORDINALITY AS s(st, ord)
             ) steps
            WHERE NOT EXISTS (
                SELECT 1
                  FROM jsonb_array_elements(
                           CASE WHEN jsonb_typeof(script -> 'step_outcomes') = 'array'
                                THEN script -> 'step_outcomes' ELSE '[]'::jsonb END
                       ) o
                 WHERE jsonb_typeof(o -> 'step') = 'number'
                   AND (o ->> 'step')::int = steps.step
                   AND btrim(COALESCE(o ->> 'outcome', '')) <> ''
            )
       )
$$
"""

_SCAN_SQL = f"""
CREATE OR REPLACE FUNCTION {SCAN}(stale_minutes integer, retry_minutes integer)
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
             WHERE c.archived_at IS NULL
               AND c.status NOT IN ('completed', 'cancelled')
               AND {LACKS}(c.script)
               AND (c.step_outcomes_state IS NULL
                    OR c.step_outcomes_state = 'skipped'
                    OR (c.step_outcomes_state = 'failed'
                        AND c.step_outcomes_at < now() - make_interval(mins => retry_minutes))
                    OR (c.step_outcomes_state IN ('queued', 'running')
                        AND c.step_outcomes_at < now() - make_interval(mins => stale_minutes)))
            UNION ALL
            SELECT t, 'line'::text, l.id
              FROM inbound_lines l
             WHERE l.archived_at IS NULL
               AND {LACKS}(l.script)
               AND (l.step_outcomes_state IS NULL
                    OR l.step_outcomes_state = 'skipped'
                    OR (l.step_outcomes_state = 'failed'
                        AND l.step_outcomes_at < now() - make_interval(mins => retry_minutes))
                    OR (l.step_outcomes_state IN ('queued', 'running')
                        AND l.step_outcomes_at < now() - make_interval(mins => stale_minutes)));
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.add_column(table, sa.Column("step_outcomes_state", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("step_outcomes_inputs", sa.Text(), nullable=True))
        op.add_column(
            table, sa.Column("step_outcomes_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_step_outcomes_state_enum"),
            table,
            f"step_outcomes_state IS NULL OR step_outcomes_state IN {_STATES!r}",
        )
    op.add_column(
        "calls",
        sa.Column("step_progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_calls_step_progress_shape"),
        "calls",
        "step_progress IS NULL OR jsonb_typeof(step_progress) = 'object'",
    )
    op.execute(_LACKS_SQL)
    op.execute(_SCAN_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(integer, integer)")
    op.execute(f"DROP FUNCTION IF EXISTS {LACKS}(jsonb)")
    op.drop_constraint(op.f("ck_calls_step_progress_shape"), "calls", type_="check")
    op.drop_column("calls", "step_progress")
    for table in _TABLES:
        op.drop_constraint(op.f(f"ck_{table}_step_outcomes_state_enum"), table, type_="check")
        op.drop_column(table, "step_outcomes_at")
        op.drop_column(table, "step_outcomes_inputs")
        op.drop_column(table, "step_outcomes_state")
