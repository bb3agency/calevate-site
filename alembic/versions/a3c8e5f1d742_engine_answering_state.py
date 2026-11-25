"""Whether the voice engine is answering right now: one row per engine

Revision ID: a3c8e5f1d742
Revises: f2a7c4e9b1d6
Create Date: 2026-11-26

`platform_engine_health` counts failures per minute, which is what a RATE alarm needs, but it
cannot say whether the engine has come back: a minute with no failures is either a recovered
engine or no traffic. Owners and operators need the second fact (a banner that says calls are
paused and disappears on recovery, a test call button that is disabled while the engine is not
answering), so this row carries the run of consecutive failures and resets on the first answer.

One row per engine, upserted, rather than a row per failure, for `c4f70b1e28da`'s reason: a
hard outage fails thousands of requests a minute, and the table's size must not depend on that.

`last_route` is our route TEMPLATE (`/calls/{id}`) and `last_error` an exception class name or
an HTTP status: no URL, no id, no payload, no vendor text (hard rule 6).

No `tenant_id`: the engine is answering or it is not, for everybody at once. Registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` beside `platform_engine_health`.

Reversible: `downgrade` drops the table, and nothing else references it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c8e5f1d742"
down_revision: str | Sequence[str] | None = "f2a7c4e9b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "platform_engine_state"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column(
            "consecutive_failures", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_answer_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_kind", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_route", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("engine", name=op.f("pk_platform_engine_state")),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name=op.f("ck_platform_engine_state_non_negative")
        ),
        sa.CheckConstraint(
            "last_kind IS NULL OR last_kind IN ('server_error', 'unreachable')",
            name=op.f("ck_platform_engine_state_kind"),
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
