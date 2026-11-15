"""A campaign keeps the test calls made from it (founder, 16 Nov 2026)

Revision ID: b3d8e1f6a2c9
Revises: a7e2c9f4d1b8
Create Date: 2026-11-16 02:00:00.000000

* `campaigns.test_call_ids`: the calls its Test call placed, newest last, so the Test call
  section can list them with their recordings. A list on the campaign rather than
  `calls.campaign_id`, which would count a test call in the campaign's results. Removing one
  from the list leaves the call itself in the call logs.

Additive. `downgrade()` drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3d8e1f6a2c9"
down_revision: str | None = "a7e2c9f4d1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "campaigns",
        sa.Column(
            "test_call_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("campaigns", "test_call_ids")
