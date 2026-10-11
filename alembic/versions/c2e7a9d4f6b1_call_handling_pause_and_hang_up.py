"""agents and organizations: the pause before replying and hanging up when finished (D-751)

Revision ID: c2e7a9d4f6b1
Revises: f8a2d6c41e95
Create Date: 2026-10-11 21:00:00.000000

Two nullable columns on each table. On `agents` NULL inherits the account's value, on
`organizations` NULL follows Calevate's (`agents/call_handling`), so no row is backfilled and
no live agent's behaviour moves until somebody chooses: the hang-up stays on (D-749) and the
pause stays at the vendor's 0.25 s, which is what every agent publishes today.

The pause is whole milliseconds bounded to ThinnestAI's `voice.turnSilenceSeconds` range,
0.2 to 3 s (docs.thinnest.ai api-reference/agents/update-agent, read 11 Oct 2026).

Both tables already carry FORCEd row-level security on `tenant_id` / `id`; a column adds no
policy. Locking: ADD COLUMN without a default is a catalog change; each CHECK is added
NOT VALID and then validated, so the brief ACCESS EXCLUSIVE does not wait on a scan.
`lock_timeout` bounds the wait. Downgrade drops the constraints and columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2e7a9d4f6b1"
down_revision: str | None = "f8a2d6c41e95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `agents.models`: a migration is a snapshot.
CK_AGENT = "ck_agents_turn_silence_range"
CK_ORG = "ck_organizations_default_turn_silence_range"
_AGENT_SQL = "turn_silence_ms IS NULL OR (turn_silence_ms >= 200 AND turn_silence_ms <= 3000)"
_ORG_SQL = (
    "default_turn_silence_ms IS NULL OR "
    "(default_turn_silence_ms >= 200 AND default_turn_silence_ms <= 3000)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agents", sa.Column("turn_silence_ms", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("end_call_on_finish", sa.Boolean(), nullable=True))
    op.add_column(
        "organizations", sa.Column("default_turn_silence_ms", sa.Integer(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("default_end_call_on_finish", sa.Boolean(), nullable=True)
    )
    op.execute(f"ALTER TABLE agents ADD CONSTRAINT {CK_AGENT} CHECK ({_AGENT_SQL}) NOT VALID")
    op.execute(f"ALTER TABLE agents VALIDATE CONSTRAINT {CK_AGENT}")
    op.execute(f"ALTER TABLE organizations ADD CONSTRAINT {CK_ORG} CHECK ({_ORG_SQL}) NOT VALID")
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {CK_ORG}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {CK_ORG}")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {CK_AGENT}")
    op.drop_column("organizations", "default_end_call_on_finish")
    op.drop_column("organizations", "default_turn_silence_ms")
    op.drop_column("agents", "end_call_on_finish")
    op.drop_column("agents", "turn_silence_ms")
