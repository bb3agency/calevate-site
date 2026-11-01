"""The trade plans' retired example lines come off every agent still holding them (D-962)

Revision ID: e962a4c1d7b3
Revises: d958b4e1a2c7
Create Date: 2026-11-02

On the founder's Rytu Khata call of 2 Nov 2026 the agent said the plan's ready-made "you
enquired with us earlier, do you still want it?" to a caller nothing on the call said had
enquired. The plans now hold no spoken lines (`agents/trade_playbooks`), but a ready-made script
stored them on each step of every agent made from it.

This queues one `strip_retired_example_lines` outbox message per account with an agent (not
deleted) whose current script or autosaved draft has any step with an example line. The worker
(`apps/workers/retired_line_strip.py`) empties only the lines that are still a retired line word
for word (`agents/retired_lines.RETIRED_LINES`), writes a new script version, republishes a live
agent and audits each agent it changed; an account with none finds nothing. The filter here is
deliberately wider than the worker's: the lines are matched in one place, the worker, rather
than copied into SQL.

DOWNGRADE queues nothing and puts no line back: each removed line is in the agent's previous
script version, which the owner can restore, and a retired line is the defect this removes.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "e962a4c1d7b3"
down_revision: str | None = "d958b4e1a2c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN: `apps/workers/retired_line_strip.JOB_NAME` on the day this ran.
JOB = "strip_retired_example_lines"


def _has_line(script: str) -> str:
    """Whether `script` (a jsonb expression) has a step with a non-blank example line. The
    array guard sits inside the call, because SQL does not promise to test a WHERE clause
    before evaluating a set-returning function on a non-array."""
    return (
        "EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN "
        f"jsonb_typeof({script} -> 'stages') = 'array' THEN {script} -> 'stages' "
        "ELSE '[]'::jsonb END) st WHERE btrim(coalesce(st ->> 'sounds_like', '')) <> '')"
    )


#: Named so `tests/dynamic_wording_2026_11_02_test.py` runs the statement that ran.
QUEUE = (
    "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, created_at, "
    "updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', "
    "t.tenant_id::text), 'pending', 0, now(), now() FROM (SELECT DISTINCT a.tenant_id "
    "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
    f"WHERE a.deleted_at IS NULL AND ({_has_line('pv.structured_script')} "
    f"OR (a.script_draft IS NOT NULL AND {_has_line('a.script_draft')}))) t"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions NO FORCE ROW LEVEL SECURITY")
    queued = execute_data_statement(
        sa.text(QUEUE).bindparams(job=JOB),
        note="Queued the retired-line job for accounts whose agents have example lines.",
    )
    log.info("retired example lines: %s account(s) queued", queued)
    op.execute("ALTER TABLE prompt_versions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing: see the module docstring."""
