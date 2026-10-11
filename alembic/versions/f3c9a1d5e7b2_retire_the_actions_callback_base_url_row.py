"""Retire the stored `actions_callback_base_url` console row (11 Oct 2026)

Revision ID: f3c9a1d5e7b2
Revises: e2b8c4d17a63
Create Date: 2026-10-11 12:00:00.000000

D-642 deleted the `actions_callback_base_url` setting; `engine_actions_base_url` replaced
it. A row stored under the old key was left in `platform_settings`, so every process logs
`platform_config_row_unmanaged` on each config load, and nothing reads the value.

A migration rather than a console action: the console's revert refuses a key `Settings` does
not declare (`ops/config_service._refuse_unmanaged`), this row is the only one of its kind,
and its removal follows from a code release (the key left with D-642), not from an operator
decision. The `platform_settings` trigger bumps the config version, so every process
re-reads. The removed row is printed in the migration output, so the deploy log keeps it.

The downgrade leaves the row gone. It changes no schema, and no revision since D-642 reads
the key, so every revision a downgrade can land on behaves the same without it; restoring
it would only bring the log line back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9a1d5e7b2"
down_revision: str | None = "e2b8c4d17a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_KEY = "actions_callback_base_url"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
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
