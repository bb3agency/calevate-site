"""The real-estate starter's example lines ask the size openly and offer the next days (D-888)

Revision ID: c8e4a1f7b2d5
Revises: c8e2f4a6b913
Create Date: 2026-10-25 21:00:00.000000

On the Sri Estates calls of 25 Oct 2026 the agent asked "two or three BHK?" of a caller who
wanted five, and on a Sunday evening offered a site visit "this weekend, Saturday or Sunday".
Both are the real-estate plan's own example lines (`agents/trade_playbooks.TRADE_WORDS`),
which a starter stores on each step of the agent's script, so the plan's new lines reach only
agents made from now on.

This queued one `refresh_example_lines` outbox message per account whose agents held an old
line, and the worker put the new line on that step. Since D-962 (2 Nov 2026) the plans hold no
spoken lines at all, that job is retired, and migration `e962a4c1d7b3` takes every plan line,
old and new, off live agents; so this revision now queues nothing in either direction (a queued
message would name a job no worker runs). It ran in production on 25 Oct 2026; the versions it
caused stay on file as history.
"""

from collections.abc import Sequence

revision: str = "c8e4a1f7b2d5"
down_revision: str | None = "c8e2f4a6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    """Nothing since D-962: see the module docstring."""


def downgrade() -> None:
    """Nothing since D-962: see the module docstring."""
