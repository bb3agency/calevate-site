"""Retire the stored `thinnest_reply_languages` console row (19 Oct 2026, D-830)

Revision ID: b7e4c2d9f1a3
Revises: d828a3f1c6e2
Create Date: 2026-10-19 12:00:00.000000

Every agent now follows the caller: ThinnestAI is sent `language: "auto"` for one language or
several, and the `languages` list the switch would have sent is never sent (under auto it
would be `[]`). The setting left `Settings` with D-830; a row saved under it would make every
process log `platform_config_row_unmanaged` on each config load.

A migration rather than a console action, as for `actions_callback_base_url`
(`f3c9a1d5e7b2`): the console's revert refuses a key `Settings` does not declare, and the
removal follows from a code release. The `platform_settings` trigger bumps the config version,
so every process re-reads. The removed row is printed in the migration output.

The downgrade leaves the row gone: it changes no schema, and a restored row would only make
the earlier code send the list again, which the founder's decision withdrew.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement, is_offline

revision: str = "b7e4c2d9f1a3"
down_revision: str | None = "d828a3f1c6e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_KEY = "thinnest_reply_languages"


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
