"""Pip conversation turns hold a long message: 8,000 characters, up from 2,000

Revision ID: a8d3f1c6e2b9
Revises: c4e1a9b7d305
Create Date: 2026-10-30 14:00:00.000000

A person's question may now be 8,000 characters (`copilot/schemas.MAX_QUESTION_CHARS`), and
the stored turn is what the panel shows once the server's copy replaces the browser's
(D-782). At 2,000 the stored question was cut mid-word with nothing said, so the ceiling on
both conversation turn tables rises to the question's. Memories, jobs and the rest keep
2,000: they are summaries, not what somebody typed.

REVERSIBILITY. `downgrade()` restores the 2,000 ceiling `NOT VALID`, so rows already longer
stay as written and new rows are held to the old bound. Shortening them would rewrite what
people said.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a8d3f1c6e2b9"
down_revision: str | None = "c4e1a9b7d305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("copilot_conversation_turns", "admin_copilot_conversation_turns")
_NEW = 8_000
_OLD = 2_000


def _replace(table: str, ceiling: int, *, valid: bool) -> None:
    name = f"ck_{table}_content_cap"
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (length(content) <= {ceiling})"
        + ("" if valid else " NOT VALID")
    )


def upgrade() -> None:
    for table in _TABLES:
        _replace(table, _NEW, valid=True)


def downgrade() -> None:
    for table in _TABLES:
        _replace(table, _OLD, valid=False)
