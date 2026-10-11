"""A saved setting reaches every live agent at once: one run per change (D-720)

Revision ID: f1a7c3e9b2d4
Revises: e9b2c7d4a1f3
Create Date: 2026-10-10 21:00:00.000000

`live_apply_runs` records one "bring the live agents up to date" pass, queued in the same
transaction as the write that made it necessary (`apps/api/agents/live_apply.py`): an ops
console platform setting, a client setting, or an agent's own change. The worker walks the
affected live agents in bounded batches from a resumable cursor, republishes each through
`agents/service.publish_agent` and reads it back; the counts and the failed agents are what
the ops console shows as "Applied to N of M live agents".

Platform machinery, admin realm only, so a NULLABLE `tenant_id` without a tenant policy, the
`heal_incidents` shape (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`): a platform run has no
client, and a tenant policy would let a client's session read the operator's apply history.
No personal data: ids, setting keys, counts, our refusal codes and an agent's display name.

DOWNGRADE drops the table. Queued runs are lost; the live agents keep whatever they were
last published with, and the drift sweep keeps reporting any that differ.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f1a7c3e9b2d4"
down_revision: str | None = "e9b2c7d4a1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "live_apply_runs"
SCOPES = ("platform", "tenant", "agent")
STATUSES = ("pending", "running", "done", "superseded")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(*names: str) -> list[sa.Column[object]]:
    return [
        sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for n in names
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("reasons", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("applied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retrying", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("cursor_tenant_id", sa.UUID(), nullable=True),
        sa.Column("cursor_agent_id", sa.UUID(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("walked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(_in("scope", SCOPES), name=op.f(f"ck_{TABLE}_scope_enum")),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f(f"ck_{TABLE}_status_enum")),
        sa.CheckConstraint(
            "(scope = 'platform' AND tenant_id IS NULL AND agent_id IS NULL) OR "
            "(scope = 'tenant' AND tenant_id IS NOT NULL AND agent_id IS NULL) OR "
            "(scope = 'agent' AND tenant_id IS NOT NULL AND agent_id IS NOT NULL)",
            name=op.f(f"ck_{TABLE}_scope_target"),
        ),
        sa.CheckConstraint(
            "applied >= 0 AND failed >= 0 AND retrying >= 0",
            name=op.f(f"ck_{TABLE}_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'done') = (finished_at IS NOT NULL)", name=op.f(f"ck_{TABLE}_done_iff")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{TABLE}_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "ix_live_apply_runs_open",
        TABLE,
        ["scope", "tenant_id", "agent_id"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index("ix_live_apply_runs_created", TABLE, [sa.text("created_at DESC")])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_live_apply_runs_created", table_name=TABLE)
    op.drop_index("ix_live_apply_runs_open", table_name=TABLE)
    op.drop_table(TABLE)
