"""A new agent volunteers neither opening notice (D-669)

Revision ID: a6d2f81c4e3b
Revises: c5d82f1a9e47
Create Date: 2026-10-03 14:00:00.000000

Founder, 3 Oct 2026: every call starts with the greeting only. `agents.ai_disclosure_enabled`
and `agents.recording_notice_enabled` now default FALSE, so a row written without naming
them is an agent that volunteers nothing. Both stay per-agent toggles (D-163).

ONLY THE DEFAULT MOVES. No stored value is touched: an existing agent keeps the posture its
owner has, and changing it is the owner's switch in the console, which republishes and
writes an audit row. An UPDATE here would flip a live line's compliance posture with no
audit entry and no republish, so the engine would keep speaking notices our table says it
had stopped.

What does not move with it (hard rule 5): both sentences stay NOT NULL and non-blank, the
dial gate still requires the AI sentence on file, and the truthful-answer floor is composed
into every prompt whatever these two columns say.

`ALTER COLUMN ... SET DEFAULT` is a catalog-only change in PostgreSQL; it rewrites no rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6d2f81c4e3b"
down_revision: str | None = "c5d82f1a9e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOGGLES = ("ai_disclosure_enabled", "recording_notice_enabled")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _TOGGLES:
        op.execute(f"ALTER TABLE agents ALTER COLUMN {column} SET DEFAULT false")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _TOGGLES:
        op.execute(f"ALTER TABLE agents ALTER COLUMN {column} SET DEFAULT true")
