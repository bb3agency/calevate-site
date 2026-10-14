"""agents: how a Studio voice sounds (speed, volume, emotion, voice model, dictionary)

Revision ID: f3b8d1c6a7e2
Revises: a4c8e1f6b2d9
Create Date: 2026-10-13 20:00:00.000000

Five nullable columns on `agents`, set by an operator for an agent that speaks a voice of our
own Cartesia key (Studio) and sent with `PUT /agents/{id}/byok-voice`
(`thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/bring-your-own-keys.md:
362-407`; `agents/set-agent-byok-voice.md:587-627`). NULL leaves the provider's default, so no
row is backfilled and no live agent changes until somebody chooses.

- `studio_voice_speed` NUMERIC(3,2), 0.60-1.50.
- `studio_voice_volume` NUMERIC(3,2), 0.50-2.00.
- `studio_voice_emotion`: one of the eight emotions the docs name.
- `studio_voice_model`: `sonic-3.6`, `sonic-3.6-2026-08-27`, `sonic-3.5`, `sonic-3`, `sonic-2`.
- `studio_voice_dictionary_id`: the vendor's own pattern for a pronunciation dictionary id.
- With `sonic-2`, speed, volume and emotion must be NULL (the vendor refuses them).

`agents` already carries FORCEd row-level security on `tenant_id`; a column adds no policy.
Locking: ADD COLUMN without a default is a catalog change; each CHECK is added NOT VALID and
then validated, and `lock_timeout` bounds the wait. Downgrade drops the constraints and the
columns, which loses only these operator choices.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1c6a7e2"
down_revision: str | None = "a4c8e1f6b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine[object]], ...] = (
    ("studio_voice_speed", sa.Numeric(3, 2)),
    ("studio_voice_volume", sa.Numeric(3, 2)),
    ("studio_voice_emotion", sa.Text()),
    ("studio_voice_model", sa.Text()),
    ("studio_voice_dictionary_id", sa.Text()),
)
_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "ck_agents_studio_voice_speed_range",
        "studio_voice_speed IS NULL OR (studio_voice_speed >= 0.6 AND studio_voice_speed <= 1.5)",
    ),
    (
        "ck_agents_studio_voice_volume_range",
        "studio_voice_volume IS NULL OR "
        "(studio_voice_volume >= 0.5 AND studio_voice_volume <= 2.0)",
    ),
    (
        "ck_agents_studio_voice_emotion_enum",
        "studio_voice_emotion IS NULL OR studio_voice_emotion IN ('neutral', 'calm', 'content', "
        "'sad', 'angry', 'scared', 'happy', 'excited')",
    ),
    (
        "ck_agents_studio_voice_model_enum",
        "studio_voice_model IS NULL OR studio_voice_model IN ('sonic-3.6', "
        "'sonic-3.6-2026-08-27', 'sonic-3.5', 'sonic-3', 'sonic-2')",
    ),
    (
        "ck_agents_studio_voice_dictionary_id_shape",
        "studio_voice_dictionary_id IS NULL OR "
        "studio_voice_dictionary_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$'",
    ),
    (
        "ck_agents_studio_voice_old_model_untuned",
        "studio_voice_model IS DISTINCT FROM 'sonic-2' OR (studio_voice_speed IS NULL "
        "AND studio_voice_volume IS NULL AND studio_voice_emotion IS NULL)",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column, kind in _COLUMNS:
        op.add_column("agents", sa.Column(column, kind, nullable=True))
    for name, check in _CHECKS:
        op.execute(f"ALTER TABLE agents ADD CONSTRAINT {name} CHECK ({check}) NOT VALID")
        op.execute(f"ALTER TABLE agents VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, _check in reversed(_CHECKS):
        op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {name}")
    for column, _kind in reversed(_COLUMNS):
        op.drop_column("agents", column)
