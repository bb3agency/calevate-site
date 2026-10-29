"""Retire the stored `cartesia_agent_cap` and `stt_autodetect_language` console rows (D-939)

Revision ID: d9e2b4f7a160
Revises: f3a8c2d61b07

D-939 removed both settings: the cap was read only by the voice offer D-763 deleted, and the
detection switch served the transcriber D-639 deleted. A row stored under either key would
log `platform_config_row_unmanaged` on every config load in every process. Same shape and
reasoning as `f3c9a1d5e7b2` (retire the actions_callback_base_url row): the console refuses
to revert a key `Settings` no longer declares, and the removal follows from a release.

The downgrade leaves the rows gone: no revision reads either key any more.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement, is_offline

revision: str = "d9e2b4f7a160"
down_revision: str | None = "f3a8c2d61b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_KEYS = ("cartesia_agent_cap", "stt_autodetect_language")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for key in RETIRED_KEYS:
        if is_offline():
            execute_data_statement(
                sa.text(f"DELETE FROM platform_settings WHERE key = '{key}'"),
                note="Deleted a retired platform_settings row.",
            )
            continue
        removed = (
            op.get_bind()
            .execute(
                sa.text(
                    "DELETE FROM platform_settings WHERE key = :key "
                    "RETURNING value::text, updated_by::text, updated_at::text"
                ),
                {"key": key},
            )
            .first()
        )
        if removed is not None:
            print(
                f"retired platform_settings row {key}: value={removed[0]} "
                f"updated_by={removed[1]} updated_at={removed[2]}"
            )


def downgrade() -> None:
    pass
