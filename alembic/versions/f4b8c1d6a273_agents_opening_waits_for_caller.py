"""agents.opening_waits_for_caller: the opening waits for the person's "Hello" (D-871)

Revision ID: f4b8c1d6a273
Revises: cdd375802099
Create Date: 2026-10-24

Sent as ThinnestAI's `voice.openingWaitsForCaller` on every publish and repaired as drift.
Existing agents that only place calls are switched on, because the person who picks up an
outbound call speaks first; agents that answer calls stay off, because a caller ringing a
business expects it to speak first. The hourly settings sweep pushes the new value to every
live agent without a republish.

`agents` is FORCE-RLS and the migration role is subject to `tenant_isolation`, so the
backfill lifts RLS for the owner around the UPDATE (d3b71c9a5e08, cdd375802099).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b8c1d6a273"
down_revision: str | None = "cdd375802099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Named so `tests/opening_waits_for_caller_test.py` runs the statement that ran.
_BACKFILL = "UPDATE agents SET opening_waits_for_caller = true WHERE direction = 'outbound'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents",
        sa.Column(
            "opening_waits_for_caller",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(_BACKFILL)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("agents", "opening_waits_for_caller")
