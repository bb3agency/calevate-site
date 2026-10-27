"""The Telugu close and first questions lose the stock "సరే అండి," on agents still holding it (D-894)

Revision ID: d7c2e9a4f6b1
Revises: b3f9d2a7c41e
Create Date: 2026-10-27 18:00:00.000000

On the Sri Estates test calls of 27 Oct 2026 the agent put "సరే అండి" before every next
question, and the founder approved taking the stock opener off the trade plans' Telugu close
and every trade's first question (`agents/trade_playbooks.TE_OPENER_LINES`). A starter stores
those lines on the steps of each agent's script, so the plan's change alone reaches only agents
made from now on.

A step changes only where its line is still the old plan line word for word (after trimming,
as the worker compares); a line the owner edited is never touched.

* The autosaved draft (`agents.script_draft`) reaches no call, so it is changed here, in SQL.
* The current script (`prompt_versions.structured_script` behind `agents.system_prompt_id`) is
  immutable history and a live agent must be republished, so it is changed by the existing
  `refresh_example_lines` job (`apps/workers/example_line_refresh.py`), one outbox message per
  account, which writes a new version and republishes a live agent through
  `script_builder.rewrite_script`. An agent with an unpublished script edit gets the change on
  that edit, which reaches callers when the owner puts it live.

Every step changed or queued is recorded in `script_line_changes` (agent, draft or script,
position, old and new line). DOWNGRADE restores the opener on exactly those steps: the drafts
here where the step still holds the new line, the scripts by queueing the inverse job limited to
the recorded positions (`stages`); then the record table goes. Nothing is rewritten in place
in a prompt version: every version stays as it was heard.
"""

import json
from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "d7c2e9a4f6b1"
down_revision: str | None = "b3f9d2a7c41e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

TABLE = "script_line_changes"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
#: `tests/telugu_stock_opener_test.py` holds them equal to the shipped plan.
#: `apps/workers/example_line_refresh.JOB_NAME`.
JOB = "refresh_example_lines"
NOTES = 'Example lines updated: the stock "సరే అండి," taken off (D-894)'
UNDO_NOTES = 'Example lines restored: the stock "సరే అండి," put back'

#: (the old line, the new one), Telugu only: the close, then each trade's first question.
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "సరే అండి, మీరు చెప్పింది టీమ్ కి చెప్తాను, వాళ్ళు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా?",
        "మీరు చెప్పింది టీమ్ కి చెప్తాను, వాళ్ళు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా?",
    ),
    (
        "సరే అండి, డాక్టర్ ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
        "డాక్టర్ ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
    ),
    ("సరే అండి, ఏ ఏరియా లో చూస్తున్నారు?", "ఏ ఏరియా లో చూస్తున్నారు?"),
    (
        "సరే అండి, హెల్త్ పాలసీ కావాలా, లైఫ్ పాలసీ కావాలా?",
        "హెల్త్ పాలసీ కావాలా, లైఫ్ పాలసీ కావాలా?",
    ),
    ("సరే అండి, ఏ కోర్స్ గురించి అడుగుతున్నారు?", "ఏ కోర్స్ గురించి అడుగుతున్నారు?"),
    ("సరే అండి, ఏ ఐటమ్ కావాలి?", "ఏ ఐటమ్ కావాలి?"),
    ("సరే అండి, ఏ సర్వీస్ కావాలి?", "ఏ సర్వీస్ కావాలి?"),
    ("సరే అండి, మీ వెహికల్ ఏ మోడల్?", "మీ వెహికల్ ఏ మోడల్?"),
    ("సరే అండి, మీకు ఏం కావాలో చెప్తారా?", "మీకు ఏం కావాలో చెప్తారా?"),
)

_DRAFT_SOURCE = "agents a"
_SCRIPT_SOURCE = "agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id"


def _steps(script: str) -> str:
    """The script's steps as rows; a script with no step array (freeform, or no draft) has
    none. The guard sits inside the call rather than in WHERE, because SQL does not promise
    to test a WHERE clause before evaluating a set-returning function on a non-array."""
    return (
        f"jsonb_array_elements(CASE WHEN jsonb_typeof({script} -> 'stages') = 'array' "
        f"THEN {script} -> 'stages' ELSE '[]'::jsonb END)"
    )


def _record(target: str, source: str, script: str) -> int | None:
    """Record each step of the draft or the current script whose line is an old line."""
    return execute_data_statement(
        sa.text(
            f"INSERT INTO {TABLE} (target, tenant_id, agent_id, stage_index, before_text, "
            "after_text) SELECT CAST(:target AS text), a.tenant_id, a.id, (st.ord - 1)::int, "
            f"st.v ->> 'sounds_like', p.v ->> 1 FROM {source} "
            f"CROSS JOIN LATERAL {_steps(script)} WITH ORDINALITY st(v, ord) "
            "JOIN jsonb_array_elements(CAST(:pairs AS jsonb)) p(v) "
            "ON btrim(st.v ->> 'sounds_like') = p.v ->> 0 "
            "WHERE a.deleted_at IS NULL"
        ).bindparams(target=target, pairs=_pairs_json(REPLACEMENTS)),
        note=f"Recorded the {target} steps holding the stock Telugu opener.",
    )


def _pairs_json(pairs: Sequence[tuple[str, str]]) -> str:
    return json.dumps([list(pair) for pair in pairs], ensure_ascii=False)


def _rewrite_drafts(*, column: str, expect: str) -> int | None:
    """Put `column` (after_text or before_text) on every recorded draft step that still holds
    `expect` (the other one), in one statement per agent so several steps change together."""
    return execute_data_statement(
        sa.text(
            "UPDATE agents a SET script_draft = jsonb_set(a.script_draft, '{stages}', ("
            "SELECT jsonb_agg(CASE WHEN c.id IS NULL THEN st.v ELSE jsonb_set(st.v, "
            f"'{{sounds_like}}', to_jsonb(c.{column})) END ORDER BY st.ord) "
            f"FROM {_steps('a.script_draft')} WITH ORDINALITY st(v, ord) "
            f"LEFT JOIN {TABLE} c ON c.agent_id = a.id AND c.target = 'draft' "
            f"AND c.stage_index = st.ord - 1 AND st.v ->> 'sounds_like' = c.{expect})) "
            f"WHERE EXISTS (SELECT 1 FROM {TABLE} c, {_steps('a.script_draft')} "
            "WITH ORDINALITY st(v, ord) WHERE c.agent_id = a.id AND c.target = 'draft' "
            f"AND c.stage_index = st.ord - 1 AND st.v ->> 'sounds_like' = c.{expect})"
        ),
        note=f"Rewrote the recorded draft steps to their {column}.",
    )


def _queue(*, forward: bool) -> int | None:
    """One `refresh_example_lines` message per account with a recorded script step, carrying
    the pairs, the recorded positions per agent and the version note."""
    pairs = REPLACEMENTS if forward else tuple((new, old) for old, new in REPLACEMENTS)
    return execute_data_statement(
        sa.text(
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object("
            "'tenant_id', s.tenant_id::text, 'replacements', CAST(:pairs AS jsonb), "
            "'notes', CAST(:notes AS text), 'stages', s.stages), 'pending', 0, now(), now() "
            "FROM (SELECT g.tenant_id, jsonb_object_agg(g.agent_id::text, g.idx) AS stages "
            "FROM (SELECT tenant_id, agent_id, jsonb_agg(stage_index ORDER BY stage_index) AS idx "
            f"FROM {TABLE} WHERE target = 'script' GROUP BY tenant_id, agent_id) g "
            "GROUP BY g.tenant_id) s"
        ).bindparams(
            job=JOB, pairs=_pairs_json(pairs), notes=NOTES if forward else UNDO_NOTES
        ),
        note="Queued the example-line job for accounts with a recorded script step.",
    )


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("before_text", sa.Text(), nullable=False),
        sa.Column("after_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "target IN ('draft', 'script')", name=op.f("ck_script_line_changes_target_enum")
        ),
        sa.CheckConstraint(
            "stage_index >= 0", name=op.f("ck_script_line_changes_stage_index_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_script_line_changes_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_script_line_changes_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_line_changes")),
        sa.UniqueConstraint(
            "agent_id", "target", "stage_index", name=op.f("uq_script_line_changes_step")
        ),
    )
    op.create_index(op.f("ix_script_line_changes_tenant_id"), TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _create_table()
    # The FORCE bracket (`f4a2c7e19d63`): all three tables are FORCE-RLS'd, so without it the
    # owner's statements see no rows and nothing is recorded, changed or queued.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    drafts = _record("draft", _DRAFT_SOURCE, "a.script_draft")
    scripts = _record("script", _SCRIPT_SOURCE, "pv.structured_script")
    _rewrite_drafts(column="after_text", expect="before_text")
    queued = _queue(forward=True)
    log.info(
        "stock Telugu opener: %s draft step(s), %s script step(s), %s account(s) queued",
        drafts,
        scripts,
        queued,
    )
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    _rewrite_drafts(column="before_text", expect="after_text")
    _queue(forward=False)
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_script_line_changes_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
