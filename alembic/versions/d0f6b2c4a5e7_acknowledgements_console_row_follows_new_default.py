"""A console row holding the old acknowledgements default follows the new one (25 Nov 2026)

Revision ID: d0f6b2c4a5e7
Revises: c9e5a1b3f4d6
Create Date: 2026-11-25 10:30:00.000000

`thinnest_acknowledgements` defaults to false from this release (founder, 25 Nov 2026: the
agent waits silently while a caller pauses under `ear`). A console value is a row in
`platform_settings`; with no row, every process follows the code default. A row saved as
`true` holds exactly the old default, so it is deleted and the setting follows the new one.
A row holding `false` already says what the founder decided and is left as it is.

A deletion, as the retired-row migrations do (`b7e4c2d9f1a3`), rather than an UPDATE: the
console's own revert is a deletion, and an UPDATE would leave the row naming the operator who
saved `true` as the author of `false`. The `platform_settings` trigger bumps the config
version, so every process re-reads. The removed row is printed in the migration output.

The downgrade leaves the row gone: it changes no schema, the earlier code's default is
`true`, so with no row that release says the same as the deleted row did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement, is_offline

revision: str = "d0f6b2c4a5e7"
down_revision: str | None = "c9e5a1b3f4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "thinnest_acknowledgements"
_DELETE = f"DELETE FROM platform_settings WHERE key = '{KEY}' AND value = 'true'::jsonb"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    if is_offline():
        execute_data_statement(
            sa.text(_DELETE),
            note="Deleted a platform_settings row that held the old acknowledgements default.",
        )
        return
    removed = (
        op.get_bind()
        .execute(sa.text(_DELETE + " RETURNING updated_by::text, updated_at::text"))
        .first()
    )
    if removed is not None:
        print(
            f"platform_settings row {KEY} held true (the old default) and now follows the new "
            f"default false: updated_by={removed[0]} updated_at={removed[1]}"
        )


def downgrade() -> None:
    pass
