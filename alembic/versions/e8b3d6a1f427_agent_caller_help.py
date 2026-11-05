"""per agent: whether its callers follow along on their phone, judged from what it does

Revision ID: e8b3d6a1f427
Revises: e8a3c5f17b26
Create Date: 2026-11-05 12:00:00.000000

Founder, 5 Nov 2026: the screen guide (D-906) and "Give callers time" (D-907) are suggested
per agent, from its script, its purpose and its campaigns, and asked about on its Overview.

* `agents.caller_help` — `{screen_guide: {suggested, reason}, give_time: {suggested, reason}}`
  from the last pass;
* `caller_help_state`, `caller_help_inputs`, `caller_help_at` — the pass ladder of the D-889
  lead-detail suggestions (states, inputs hash, time);
* `caller_help_dismissed` — the items the owner answered "Not now" to.

Additive only. RLS is unchanged: `agents` already carries its FORCEd policy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8b3d6a1f427"
down_revision: str | None = "e8a3c5f17b26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES` and `len(CALLER_HELP_ITEMS)`, frozen.
_STATES = ("queued", "running", "done", "failed", "skipped")
_ITEMS = 2


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents", sa.Column("caller_help", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("agents", sa.Column("caller_help_state", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("caller_help_inputs", sa.Text(), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "caller_help_dismissed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("agents", sa.Column("caller_help_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_agents_caller_help_shape"),
        "agents",
        "caller_help IS NULL OR jsonb_typeof(caller_help) = 'object'",
    )
    op.create_check_constraint(
        op.f("ck_agents_caller_help_dismissed_shape"),
        "agents",
        "jsonb_typeof(caller_help_dismissed) = 'array' "
        f"AND jsonb_array_length(caller_help_dismissed) <= {_ITEMS}",
    )
    op.create_check_constraint(
        op.f("ck_agents_caller_help_state_enum"),
        "agents",
        f"caller_help_state IS NULL OR caller_help_state IN {_STATES!r}",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_agents_caller_help_state_enum"), "agents", type_="check")
    op.drop_constraint(op.f("ck_agents_caller_help_dismissed_shape"), "agents", type_="check")
    op.drop_constraint(op.f("ck_agents_caller_help_shape"), "agents", type_="check")
    op.drop_column("agents", "caller_help_at")
    op.drop_column("agents", "caller_help_dismissed")
    op.drop_column("agents", "caller_help_inputs")
    op.drop_column("agents", "caller_help_state")
    op.drop_column("agents", "caller_help")
