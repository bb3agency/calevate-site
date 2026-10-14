"""agents: the longest reply an agent may give, in tokens (D-769)

Revision ID: b9d4e2a7c6f1
Revises: f3b8d1c6a7e2
Create Date: 2026-10-14 12:00:00.000000

One nullable column on `agents`, set by an operator only and sent on every publish as
ThinnestAI's `maxReplyTokens`, an integer 100-800 (`thinnest-findings/mirror/snapshots/
2026-10-13/pages/api-reference/agents/update-agent.md:839-845`). NULL inherits the console's
`thinnest_reply_length` (default 300, the vendor's own), so no row is backfilled and no
live agent changes until somebody chooses.

`agents` already carries FORCEd row-level security on `tenant_id`; a column adds no policy.
Locking: ADD COLUMN without a default is a catalog change; the CHECK is added NOT VALID and
then validated, and `lock_timeout` bounds the wait. Downgrade drops the constraint and the
column, which loses only these operator choices.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4e2a7c6f1"
down_revision: str | None = "f3b8d1c6a7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_CHECK = "ck_agents_max_reply_tokens_range"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agents", sa.Column("max_reply_tokens", sa.Integer(), nullable=True))
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {_CHECK} CHECK (max_reply_tokens IS NULL OR "
        "(max_reply_tokens >= 100 AND max_reply_tokens <= 800)) NOT VALID"
    )
    op.execute(f"ALTER TABLE agents VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("agents", "max_reply_tokens")
