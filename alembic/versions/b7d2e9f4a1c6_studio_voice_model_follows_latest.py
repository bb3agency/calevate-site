"""Studio agents on the dated Sonic 3.6 move to `sonic-3.6` (D-983)

Revision ID: b7d2e9f4a1c6
Revises: f3c8a1d6e2b9
Create Date: 2026-11-12 23:00:00.000000

Founder's decision, 12 Nov 2026: every Studio agent speaks `sonic-3.6`, which follows Cartesia's
latest stable 3.6 snapshot, not the dated `sonic-3.6-2026-08-27` that D-977 (`e5a9c3d7b2f8`)
gave them (thinnest-findings snapshots/2026-10-29/pages/api-reference/agents/
set-agent-byok-voice.md:9).

- Every Studio agent (`byok:<id>`) on the dated model is moved. Those given it by a voice change
  since `e5a9c3d7b2f8` are recorded in `studio_voice_model_pins` first, so the downgrade can
  move them back too.
- Each agent the engine holds (live or ready) gets one agent live-apply run, so the model
  reaches it from its next call.

Both tables are FORCE-RLS'd, so the data statements run inside the FORCE bracket
(`f4a2c7e19d63`).

DOWNGRADE puts the dated model back on recorded agents still on `sonic-3.6` and queues their
live apply.
"""

from collections.abc import Callable, Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "b7d2e9f4a1c6"
down_revision: str | None = "f3c8a1d6e2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

TABLE = "studio_voice_model_pins"
REASON = "voice_model_follows_latest"
#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
DATED_MODEL = "sonic-3.6-2026-08-27"
LATEST_MODEL = "sonic-3.6"
_STUDIO = "a.deleted_at IS NULL AND a.engine_voice_id LIKE 'byok:_%'"
#: What the engine holds: `agents.models.PUBLISHED_STATUSES` (live, and ready = paused).
_HELD = "a.status IN ('live', 'paused') AND a.engine_agent_ref IS NOT NULL"


def _queue_live_apply(
    *, holding: str, models: dict[str, str], min_revision: str | None
) -> int | None:
    """One agent live-apply run per Studio agent the engine holds that matches `holding`."""
    return execute_data_statement(
        sa.text(
            "WITH touched AS ("
            f"SELECT a.tenant_id, a.id FROM agents a WHERE {_STUDIO} AND {_HELD} AND {holding}"
            "), runs AS ("
            "INSERT INTO live_apply_runs (id, scope, tenant_id, agent_id, reasons) "
            f"SELECT gen_random_uuid(), 'agent', tenant_id, id, '[\"{REASON}\"]'::jsonb "
            "FROM touched RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, CAST(:revision AS text), "
            "now(), now() FROM runs"
        ).bindparams(revision=min_revision, **models),
        note="Queued a live apply for each Studio agent the engine holds whose model moved.",
    )


def _bracket(run: Callable[[], None]) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    run()
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


_ON_DATED = "a.studio_voice_model = CAST(:dated AS text)"
_ON_LATEST_RECORDED = (
    f"a.studio_voice_model = CAST(:latest AS text) AND EXISTS (SELECT 1 FROM {TABLE} p "
    "WHERE p.agent_id = a.id AND p.model = CAST(:dated AS text))"
)


def _upgrade() -> None:
    recorded = execute_data_statement(
        sa.text(
            f"INSERT INTO {TABLE} (tenant_id, agent_id, model) "
            "SELECT a.tenant_id, a.id, CAST(:dated AS text) FROM agents a "
            f"WHERE {_STUDIO} AND {_ON_DATED} ON CONFLICT (agent_id) DO NOTHING"
        ).bindparams(dated=DATED_MODEL),
        note="Recorded the Studio agents given the dated model since the pin.",
    )
    queued = _queue_live_apply(
        holding=_ON_DATED, models={"dated": DATED_MODEL}, min_revision=revision
    )
    execute_data_statement(
        sa.text(
            "UPDATE agents a SET studio_voice_model = CAST(:latest AS text), updated_at = now() "
            f"WHERE {_STUDIO} AND {_ON_DATED}"
        ).bindparams(dated=DATED_MODEL, latest=LATEST_MODEL),
        note="Moved the Studio agents on the dated model to sonic-3.6.",
    )
    log.info("studio voice model follows latest: %s newly recorded, %s live applies", recorded, queued)


def _downgrade() -> None:
    # Unstamped: the image this downgrade returns to does not contain this revision.
    _queue_live_apply(
        holding=_ON_LATEST_RECORDED,
        models={"dated": DATED_MODEL, "latest": LATEST_MODEL},
        min_revision=None,
    )
    execute_data_statement(
        sa.text(
            "UPDATE agents a SET studio_voice_model = CAST(:dated AS text), updated_at = now() "
            f"WHERE {_STUDIO} AND {_ON_LATEST_RECORDED}"
        ).bindparams(dated=DATED_MODEL, latest=LATEST_MODEL),
        note="Put the dated model back on the recorded agents still on sonic-3.6.",
    )


def upgrade() -> None:
    _bracket(_upgrade)


def downgrade() -> None:
    _bracket(_downgrade)
