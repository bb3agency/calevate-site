"""What the adoption job did with each agent's own engine agent (D-1019)

An agent holds no engine agent of its own once its client's assignments do (founder, 18 Nov
2026): the job `agents/engine_retirement` gives each agent's existing vendor agent to the one
draft line with numbers, or the one running campaign, that uses it, or retires it when
nothing does. `agent_engine_retirements` is one row per (agent, old engine agent): the
outcome (`adopted_line`, `adopted_campaign`, `retired`, `held`, `waiting`), the line or
campaign that took it over, and our code for why it was held or is waiting. A rerun updates
the row, so an hourly sweep alarms once per cause.

RLS: `tenant_id` and the FORCEd `tenant_isolation` policy (hard rule 1); the cross-tenant
zero-rows proof is `tests/agent_engine_retirement_test.py`. An account's erasure deletes the
rows (`workers/retention.execute_tenant_erasure`). Additive; `downgrade()` drops the table.

Revision ID: e4b9c2a7d6f3
Revises: b2d7f4a9c6e1
Create Date: 2026-11-18 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b9c2a7d6f3"
down_revision: str | None = "b2d7f4a9c6e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_engine_retirements"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `agents/models.RETIREMENT_OUTCOMES`, spelled here because a migration is the schema on the
#: day it ran.
_OUTCOMES = ("adopted_line", "adopted_campaign", "retired", "held", "waiting")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("old_ref", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("holder_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"outcome IN {_OUTCOMES!r}", name=op.f(f"ck_{TABLE}_outcome_enum")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{TABLE}_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", "old_ref", name=f"uq_{TABLE}_agent_ref"),
    )
    op.create_index(f"ix_{TABLE}_tenant", TABLE, ["tenant_id", "outcome"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(TABLE)
