"""agents/organizations: the opening's silent wait; agents: an operator's turn detection (D-901)

Revision ID: a9c4e1d7b352
Revises: e5a1c7d93b20
Create Date: 2026-10-27 18:00:00.000000

- `agents.opening_wait_ms` and `organizations.default_opening_wait_ms`: how long an opening that
  waits for the person's hello waits through silence before it plays, sent as ThinnestAI's
  `voice.openingWaitSeconds` (0.5 to 10 s to a tenth, ThinnestAI email of 27 Oct 2026,
  VENDOR-STATED). Milliseconds on whole tenths, on the D-751 pattern: NULL on `agents` inherits
  the account's value, NULL on `organizations` follows the console's
  `thinnest_opening_wait_ms`, so no row is backfilled and nothing changes on the wire.
- `agents.turn_detection`: an operator's `timer`, `ear` or `smart` for one agent, over the
  console's `thinnest_turn_detection`, so one agent can be tried on another mode. NULL follows
  the console.

Both tables already carry FORCEd row-level security; a column adds no policy. ADD COLUMN without
a default is a catalog change; each CHECK is added NOT VALID and then validated, and
`lock_timeout` bounds the wait. Downgrade drops the constraints and the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e1d7b352"
down_revision: str | None = "e5a1c7d93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from the models: a migration is a snapshot.
_WAIT_CHECK = "{c} IS NULL OR ({c} >= 500 AND {c} <= 10000 AND {c} % 100 = 0)"
_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine[object], str, str], ...] = (
    (
        "agents",
        "opening_wait_ms",
        sa.Integer(),
        "ck_agents_opening_wait_range",
        _WAIT_CHECK.format(c="opening_wait_ms"),
    ),
    (
        "organizations",
        "default_opening_wait_ms",
        sa.Integer(),
        "ck_organizations_default_opening_wait_range",
        _WAIT_CHECK.format(c="default_opening_wait_ms"),
    ),
    (
        "agents",
        "turn_detection",
        sa.Text(),
        "ck_agents_turn_detection_enum",
        "turn_detection IS NULL OR turn_detection IN ('timer', 'ear', 'smart')",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, column, kind, _name, _check in _COLUMNS:
        op.add_column(table, sa.Column(column, kind, nullable=True))
    for table, _column, _kind, name, check in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check}) NOT VALID")
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, column, _kind, name, _check in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.drop_column(table, column)
