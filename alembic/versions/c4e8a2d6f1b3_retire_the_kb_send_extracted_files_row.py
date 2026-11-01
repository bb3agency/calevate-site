"""Retire the stored `kb_send_extracted_files` console row (1 Nov 2026, D-868)

Revision ID: c4e8a2d6f1b3
Revises: a8d3f1c6e2b9
Create Date: 2026-11-01 12:00:00.000000

A PDF's words, read by us, are now what its agents are sent, and a link is sent as its
address; there is no switch between that and the old delivery any more. The setting left
`Settings` with D-868; a row saved under it would make every process log
`platform_config_row_unmanaged` on each config load.

A migration rather than a console action, as for `thinnest_reply_languages` (`b7e4c2d9f1a3`):
the console's revert refuses a key `Settings` does not declare. The `platform_settings`
trigger bumps the config version, so every process re-reads. The removed row is printed in
the migration output.

The downgrade leaves the row gone: it changes no schema, and the earlier code reads a missing
row as the switch off, its default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement, is_offline

revision: str = "c4e8a2d6f1b3"
down_revision: str | None = "a8d3f1c6e2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_KEY = "kb_send_extracted_files"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    if is_offline():
        # The delete is emitted; only the printed copy of the removed row is skipped.
        execute_data_statement(
            sa.text(f"DELETE FROM platform_settings WHERE key = '{RETIRED_KEY}'"),
            note="Deleted the retired platform_settings row.",
        )
        return
    removed = (
        op.get_bind()
        .execute(
            sa.text(
                "DELETE FROM platform_settings WHERE key = :key "
                "RETURNING value::text, updated_by::text, updated_at::text"
            ),
            {"key": RETIRED_KEY},
        )
        .first()
    )
    if removed is not None:
        print(
            f"retired platform_settings row {RETIRED_KEY}: value={removed[0]} "
            f"updated_by={removed[1]} updated_at={removed[2]}"
        )


def downgrade() -> None:
    pass
