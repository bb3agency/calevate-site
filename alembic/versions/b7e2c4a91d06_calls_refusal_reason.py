"""calls: why the person said no, as one countable category

Revision ID: b7e2c4a91d06
Revises: 9c3e5b7a1f28
Create Date: 2026-11-24 18:00:00.000000

One nullable column on `calls`, `refusal_reason`: the post-call reading's category for why
the person refused or put off what the call was for (`calevate_shared.extraction.
REFUSAL_REASONS`), counted by a campaign's or Inbound line's Improve tab. A category only,
never the caller's words, so it carries no prose to erase (hard rule 6).

`calls` already carries FORCEd row-level security on `tenant_id`; a column adds no policy.
No backfill: older calls were never asked. The CHECK is added NOT VALID then validated,
under `lock_timeout`. Downgrade drops the constraint and the column, losing the readings.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c4a91d06"
down_revision: str | None = "9c3e5b7a1f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_calls_refusal_reason_enum"
_CHECK = (
    "refusal_reason IS NULL OR refusal_reason IN ('price', 'busy_now', 'already_has', "
    "'not_interested', 'wants_person', 'no_trust', 'other')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("refusal_reason", sa.String(), nullable=True))
    op.execute(f"ALTER TABLE calls ADD CONSTRAINT {_CHECK_NAME} CHECK ({_CHECK}) NOT VALID")
    op.execute(f"ALTER TABLE calls VALIDATE CONSTRAINT {_CHECK_NAME}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.drop_column("calls", "refusal_reason")
