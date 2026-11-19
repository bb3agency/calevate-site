"""a client's workspace may hold more engine agents than the console default

ThinnestAI caps the engine agents in each customer workspace at 2 on pay-as-you-go and raises
it per workspace on request (VENDOR-STATED 23 Oct 2026,
`docs/vendor/thinnest-relationship-2026-10-23.md:136-142`). The console's
`thinnest_agents_per_workspace` is the default for every client; raising it would let every
client go past the vendor's cap. `tenant_engine_workspaces.agent_allowance` is the cap the
vendor raised for THIS client's workspace, set by an operator; NULL means the default
(`agents/workspace_slots.workspace_agent_allowance`).

The table already has its FORCEd tenant policy; a new column on it needs no new one.
Additive; `downgrade()` drops the column and its check.

Revision ID: c3a9f5e2b7d1
Revises: e4b9c2a7d6f3
Create Date: 2026-11-19 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a9f5e2b7d1"
down_revision: str | None = "e4b9c2a7d6f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACES = "tenant_engine_workspaces"
_CK = "ck_tenant_engine_workspaces_agent_allowance_range"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_WORKSPACES, sa.Column("agent_allowance", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f(_CK),
        _WORKSPACES,
        "agent_allowance IS NULL OR (agent_allowance >= 1 AND agent_allowance <= 1000)",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_CK), _WORKSPACES, type_="check")
    op.drop_column(_WORKSPACES, "agent_allowance")
