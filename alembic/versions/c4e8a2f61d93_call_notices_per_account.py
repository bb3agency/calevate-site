"""the AI and recording notice switches move to the client account (D-1021)

Founder, 19 Nov 2026: every call made from or to a client's numbers has ONE AI switch and ONE
recording switch; the words spoken still follow the call's direction. So
`organizations.notice_ai_enabled` and `organizations.notice_recording_enabled` replace the
per-agent `agents.ai_disclosure_enabled` / `agents.recording_notice_enabled` (D-163) as the
switches every call reads. Two columns, not one: the AI notice and the recording notice are
separate obligations under separate regimes (D-163 stands).

Backfill: an account's switch is ON when ANY of its agents not deleted has it on, because
folding several agents into one switch must never leave a caller who heard a notice
yesterday without it today.

The agent columns are kept, unread, under hard rule 8's two-step; the drop is a later
migration. `organizations` already has its FORCEd tenant policy, so new columns need none.
`downgrade()` writes each account's switches back onto its agents, so the code before D-1021
reads the posture the account had, then drops the columns.

Revision ID: c4e8a2f61d93
Revises: d7e2a4c9f1b6
Create Date: 2026-11-19 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f61d93"
down_revision: str | None = "d7e2a4c9f1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("notice_ai_enabled", "ai_disclosure_enabled"),
    ("notice_recording_enabled", "recording_notice_enabled"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for account_column, _agent_column in _COLUMNS:
        op.add_column(
            "organizations",
            sa.Column(account_column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    for account_column, agent_column in _COLUMNS:
        op.execute(
            f"UPDATE organizations o SET {account_column} = true "
            f"WHERE EXISTS (SELECT 1 FROM agents a WHERE a.tenant_id = o.id "
            f"AND a.deleted_at IS NULL AND a.{agent_column})"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for account_column, agent_column in _COLUMNS:
        op.execute(
            f"UPDATE agents a SET {agent_column} = o.{account_column} "
            "FROM organizations o WHERE o.id = a.tenant_id"
        )
    for account_column, _agent_column in reversed(_COLUMNS):
        op.drop_column("organizations", account_column)
