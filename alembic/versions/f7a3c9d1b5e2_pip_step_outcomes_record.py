"""Record the step outcomes Pip wrote, so it may rewrite its own and never the owner's

Revision ID: f7a3c9d1b5e2
Revises: c4f1a8d2e7b3
Create Date: 2026-11-24 22:00:00.000000

`step_outcomes_pip` (campaigns and inbound_lines) is what the step-outcomes pass
(`workers/step_outcomes`) wrote:

    {"rules": <writer rules version the last pass ran under>,
     "subject": <the word every outcome uses for the person called>,
     "outcomes": {"<step>": {"outcome": <the exact text>, "rules": <version it was written under>}}}

An outcome is Pip's while the script still holds exactly that text; one the owner typed or
edited holds other text and is never touched. When `campaigns/step_outcomes.RULES_VERSION`
moves past the version an outcome of Pip's was written under, the pass rewrites it.

Outcomes written by 0.5.33 have no entry here and are treated as the owner's: nothing stored
says which steps that pass wrote (it kept a hash of its request, not the text), so they are
never overwritten without the owner handing them back (`hand_back_to_pip`).

`script_pip_outcomes_stale(script, pip, rules)` is the SQL twin of
`campaigns/step_outcomes.pip_outcomes_stale`; `step_outcome_scan` gains a `rules` argument and
also names the holders whose Pip outcomes are stale, so the hourly sweep rewrites them.

NO NEW TABLE, SO NO NEW POLICY: the two tables keep their FORCEd `tenant_isolation`.
Reversible: `downgrade()` puts back the two-argument scan and drops the function, the CHECKs
and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a3c9d1b5e2"
down_revision: str | None = "c4f1a8d2e7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("campaigns", "inbound_lines")
LACKS = "script_lacks_step_outcome"
STALE = "script_pip_outcomes_stale"
SCAN = "step_outcome_scan"

_STALE_SQL = f"""
CREATE OR REPLACE FUNCTION {STALE}(script jsonb, pip jsonb, rules integer)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT COALESCE(
        jsonb_typeof(pip) = 'object'
        AND CASE WHEN jsonb_typeof(pip -> 'rules') = 'number'
                 THEN (pip ->> 'rules')::numeric ELSE 0 END < rules
        AND EXISTS (
            SELECT 1
              FROM jsonb_each(
                       CASE WHEN jsonb_typeof(pip -> 'outcomes') = 'object'
                            THEN pip -> 'outcomes' ELSE '{{}}'::jsonb END
                   ) p,
                   jsonb_array_elements(
                       CASE WHEN jsonb_typeof(script -> 'step_outcomes') = 'array'
                            THEN script -> 'step_outcomes' ELSE '[]'::jsonb END
                   ) o
             WHERE jsonb_typeof(p.value) = 'object'
               AND jsonb_typeof(p.value -> 'outcome') = 'string'
               AND o ->> 'outcome' = p.value ->> 'outcome'
               AND CASE WHEN jsonb_typeof(p.value -> 'rules') = 'number'
                        THEN (p.value ->> 'rules')::numeric ELSE 0 END < rules
        ),
        false
    )
$$
"""


def _scan_sql(*, with_rules: bool) -> str:
    """The sweep's worklist. With `rules`, a holder whose Pip outcomes are stale is named too,
    a finished pass included: the version moved since it ran."""

    def holder(alias: str, table: str, kind: str, extra_where: str) -> str:
        stale = f"{STALE}({alias}.script, {alias}.step_outcomes_pip, rules)"
        needs = f"({LACKS}({alias}.script) OR {stale})" if with_rules else f"{LACKS}({alias}.script)"
        done = f"\n                    OR ({alias}.step_outcomes_state = 'done' AND {stale})"
        return f"""
            SELECT t, '{kind}'::text, {alias}.id
              FROM {table} {alias}
             WHERE {alias}.archived_at IS NULL{extra_where}
               AND {needs}
               AND ({alias}.step_outcomes_state IS NULL
                    OR {alias}.step_outcomes_state = 'skipped'{done if with_rules else ""}
                    OR ({alias}.step_outcomes_state = 'failed'
                        AND {alias}.step_outcomes_at < now() - make_interval(mins => retry_minutes))
                    OR ({alias}.step_outcomes_state IN ('queued', 'running')
                        AND {alias}.step_outcomes_at < now() - make_interval(mins => stale_minutes)))"""

    campaign = holder("c", "campaigns", "campaign", "\n               AND c.status NOT IN ('completed', 'cancelled')")
    line = holder("l", "inbound_lines", "line", "")
    args = "stale_minutes integer, retry_minutes integer" + (", rules integer" if with_rules else "")
    return f"""
CREATE OR REPLACE FUNCTION {SCAN}({args})
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
        RETURN QUERY{campaign}
            UNION ALL{line};
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("step_outcomes_pip", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_step_outcomes_pip_shape"),
            table,
            "step_outcomes_pip IS NULL OR jsonb_typeof(step_outcomes_pip) = 'object'",
        )
    op.execute(_STALE_SQL)
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(integer, integer)")
    op.execute(_scan_sql(with_rules=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(integer, integer, integer)")
    op.execute(_scan_sql(with_rules=False))
    op.execute(f"DROP FUNCTION IF EXISTS {STALE}(jsonb, jsonb, integer)")
    for table in _TABLES:
        op.drop_constraint(op.f(f"ck_{table}_step_outcomes_pip_shape"), table, type_="check")
        op.drop_column(table, "step_outcomes_pip")
