"""agents/organizations: how long before an unanswered question is asked again (D-907)

Revision ID: b7e2d5a9c813
Revises: d8f3a6c1e924
Create Date: 2026-10-27 23:30:00.000000

`agents.reask_after_ms` and `organizations.default_reask_after_ms`: after a question the agent
asked has had no answer, how long it waits before asking again, sent as ThinnestAI's
`voice.reaskAfterSeconds` (`0` never, otherwise 1.5 to 10 s to one decimal; thinnest-findings/
mirror/snapshots/2026-10-19/pages/api-reference/agents/update-agent.md:1452-1460). Milliseconds
on whole tenths, 0 for never, on the D-751 pattern: NULL on `agents` inherits the account's
value, NULL on `organizations` follows Calevate's 5 s, which every agent was already sent, so no
row is backfilled and nothing changes on the wire.

Both tables already carry FORCEd row-level security; a column adds no policy. ADD COLUMN without
a default is a catalog change; each CHECK is added NOT VALID and then validated, and
`lock_timeout` bounds the wait. Downgrade drops the constraints and the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d5a9c813"
down_revision: str | None = "d8f3a6c1e924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_CHECK = "{c} IS NULL OR {c} = 0 OR ({c} >= 1500 AND {c} <= 10000 AND {c} % 100 = 0)"
_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("agents", "reask_after_ms", "ck_agents_reask_after_range"),
    ("organizations", "default_reask_after_ms", "ck_organizations_default_reask_after_range"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, column, _name in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
    for table, column, name in _COLUMNS:
        check = _CHECK.format(c=column)
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check}) NOT VALID")
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, column, name in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.drop_column(table, column)
