"""Agents that answer and place calls wait for the person's "Hello" too (D-958)

Revision ID: d958b4e1a2c7
Revises: c4e9a2d71f58
Create Date: 2026-11-02

`call_handling.opening_waits_default` now switches `opening_waits_for_caller` on for a
"both" agent at creation, as `f4b8c1d6a273` did for outbound-only agents. This switches on
the existing "both" agents that still hold the old default. ThinnestAI's switch is the
agent's, with no per-call override on Place Call, so it cannot be on for placed calls only.

Which rows: `direction = 'both'`, still off, and never the subject of a call-handling save
from any door (the client route `agent.call_handling_set`, the admin door
`admin.agent_call_handling_set`, Pip's `agent.settings_set`). `audit_log` does not keep
which setting a save moved, so an agent whose owner changed any call setting is left as
it is; the owner may have switched this one off on purpose. `audit_log` is unpoliced
(`db/registry.RLS_EXEMPT_TENANT_COLUMNS`), so only `agents` needs the NO FORCE bracket.

The settings drift sweep pushes the new value to every live agent; no republish is needed.

DOWNGRADE switches the same rows back off: a "both" agent that is on and was never the
subject of a call-handling save. An owner's own "on" after the upgrade is such a save, so
it is kept.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d958b4e1a2c7"
down_revision: str | None = "c4e9a2d71f58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEVER_SAVED = (
    "a.direction = 'both' "
    "AND NOT EXISTS (SELECT 1 FROM audit_log AS l WHERE l.object_id = a.id::text "
    "AND l.action IN "
    "('agent.call_handling_set', 'admin.agent_call_handling_set', 'agent.settings_set'))"
)
#: Named so `tests/opening_waits_for_caller_test.py` runs the statements that ran.
_BACKFILL = (
    "UPDATE agents AS a SET opening_waits_for_caller = true "
    f"WHERE NOT a.opening_waits_for_caller AND {_NEVER_SAVED}"
)
_UNFILL = (
    "UPDATE agents AS a SET opening_waits_for_caller = false "
    f"WHERE a.opening_waits_for_caller AND {_NEVER_SAVED}"
)


def _run_unforced(statement: str) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Lifted for the owner only, so the statement sees every tenant's rows (d3b71c9a5e08).
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _run_unforced(_BACKFILL)


def downgrade() -> None:
    _run_unforced(_UNFILL)
