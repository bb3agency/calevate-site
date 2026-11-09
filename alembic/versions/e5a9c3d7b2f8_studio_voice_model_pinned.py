"""Studio agents with no voice model speak the dated Cartesia release (D-977)

Revision ID: e5a9c3d7b2f8
Revises: c3f8a1d6e4b9
Create Date: 2026-11-09 18:00:00.000000

Founder's decision, 9 Nov 2026: every Studio agent speaks `sonic-3.6-2026-08-27` unless an
operator picks another model. A null `agents.studio_voice_model` sends no model, so the agent
speaks the key's own, and `sonic-3.6` "follows Cartesia's latest stable snapshot, the dated one
never changes" (thinnest-findings snapshots/2026-10-29/pages/api-reference/agents/
set-agent-byok-voice.md:9). New Studio agents get the pinned model from `lifecycle.update_agent`;
this revision moves the agents that already exist.

- Every agent whose configured voice is a Studio one (`byok:<id>`) and whose model is NULL is
  recorded in `studio_voice_model_pins` and given the pinned model. Clear agents and models an
  operator chose are not touched. A NULL model stays a valid choice afterwards.
- Each recorded agent the engine holds (live or ready) gets one agent live-apply run
  (`agents/live_apply.py`), so its voice settings are sent from its next call, the way an
  operator's save of the model reaches it (`voice_tuning.set_voice_tuning`).

Both tables are FORCE-RLS'd, so the data statements run inside the FORCE bracket
(`f4a2c7e19d63`).

DOWNGRADE clears the model on the recorded agents still holding the model this revision set,
queues their live apply again, and drops the record. A model an operator changed since is kept.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "e5a9c3d7b2f8"
down_revision: str | None = "c3f8a1d6e4b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

TABLE = "studio_voice_model_pins"
REASON = "voice_model_pinned"
#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
PINNED_MODEL = "sonic-3.6-2026-08-27"
#: What the engine holds: `agents.models.PUBLISHED_STATUSES` (live, and ready = paused).
_HELD = "a.status IN ('live', 'paused') AND a.engine_agent_ref IS NOT NULL"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{TABLE}_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint("agent_id", name=op.f(f"uq_{TABLE}_agent")),
    )
    op.create_index(op.f(f"ix_{TABLE}_tenant_id"), TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def _queue_live_apply(*, still_holding: bool, min_revision: str | None) -> int | None:
    """One agent live-apply run per recorded agent the engine holds. `still_holding` limits
    it to agents still holding the model recorded for them (the downgrade's match)."""
    match = "AND a.studio_voice_model = p.model " if still_holding else ""
    return execute_data_statement(
        sa.text(
            "WITH touched AS ("
            f"SELECT a.tenant_id, a.id FROM {TABLE} p JOIN agents a ON a.id = p.agent_id "
            f"WHERE a.deleted_at IS NULL AND {_HELD} {match}"
            "), runs AS ("
            "INSERT INTO live_apply_runs (id, scope, tenant_id, agent_id, reasons) "
            f"SELECT gen_random_uuid(), 'agent', tenant_id, id, '[\"{REASON}\"]'::jsonb "
            "FROM touched RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, CAST(:revision AS text), "
            "now(), now() FROM runs"
        ).bindparams(revision=min_revision),
        note="Queued a live apply for each Studio agent the engine holds whose model moved.",
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _create_table()
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    pinned = execute_data_statement(
        sa.text(
            f"INSERT INTO {TABLE} (tenant_id, agent_id, model) "
            "SELECT a.tenant_id, a.id, CAST(:model AS text) FROM agents a "
            "WHERE a.deleted_at IS NULL AND a.studio_voice_model IS NULL "
            "AND a.engine_voice_id LIKE 'byok:_%'"
        ).bindparams(model=PINNED_MODEL),
        note="Recorded the Studio agents with no voice model.",
    )
    queued = _queue_live_apply(still_holding=False, min_revision=revision)
    execute_data_statement(
        sa.text(
            "UPDATE agents a SET studio_voice_model = p.model, updated_at = now() "
            f"FROM {TABLE} p WHERE p.agent_id = a.id"
        ),
        note="Put the recorded Studio agents on the pinned voice model.",
    )
    log.info("studio voice model pinned: %s agents, %s live applies queued", pinned, queued)
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    # Unstamped: the image this downgrade returns to does not contain this revision, and a
    # stamped message would wait for one that does.
    _queue_live_apply(still_holding=True, min_revision=None)
    execute_data_statement(
        sa.text(
            "UPDATE agents a SET studio_voice_model = NULL, updated_at = now() "
            f"FROM {TABLE} p WHERE p.agent_id = a.id AND a.studio_voice_model = p.model"
        ),
        note="Cleared the pinned voice model on the recorded agents still holding it.",
    )
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.drop_index(op.f(f"ix_{TABLE}_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
