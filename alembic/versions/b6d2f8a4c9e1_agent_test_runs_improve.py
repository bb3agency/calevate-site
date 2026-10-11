"""agent_test_runs: generated scenarios, retest rounds, auto-improve and the proposal (D-724)

A run now stores the scenarios the AI wrote for it, which earlier run it re-tests, its round
of the improve loop, whether its owner asked for auto-improve, the improvement proposal made
from it, and a plain note on how it ran. All columns are additive and nullable or defaulted,
so code from before this revision keeps writing rows it understands. The table's FORCEd RLS
policy (f7c3a9e15d26) covers the new columns; no policy changes.

Revision ID: b6d2f8a4c9e1
Revises: c4e8b2d6f1a3
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b6d2f8a4c9e1"
down_revision: str | None = "c4e8b2d6f1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_test_runs"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("scenarios", postgresql.JSONB(), nullable=True))
    op.add_column(
        TABLE, sa.Column("improve_round", sa.SmallInteger(), server_default="1", nullable=False)
    )
    op.add_column(TABLE, sa.Column("retest_of", sa.UUID(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("auto_improve", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(TABLE, sa.Column("improvement", postgresql.JSONB(), nullable=True))
    op.add_column(TABLE, sa.Column("note", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f(f"fk_{TABLE}_retest_of_{TABLE}"),
        TABLE,
        TABLE,
        ["retest_of"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_round_range"), TABLE, "improve_round BETWEEN 1 AND 3"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_scenarios_is_array"),
        TABLE,
        "scenarios IS NULL OR jsonb_typeof(scenarios) = 'array'",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_improvement_is_object"),
        TABLE,
        "improvement IS NULL OR jsonb_typeof(improvement) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(f"ck_{TABLE}_improvement_is_object"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_scenarios_is_array"), TABLE, type_="check")
    op.drop_constraint(op.f(f"ck_{TABLE}_round_range"), TABLE, type_="check")
    op.drop_constraint(op.f(f"fk_{TABLE}_retest_of_{TABLE}"), TABLE, type_="foreignkey")
    op.drop_column(TABLE, "note")
    op.drop_column(TABLE, "improvement")
    op.drop_column(TABLE, "auto_improve")
    op.drop_column(TABLE, "retest_of")
    op.drop_column(TABLE, "improve_round")
    op.drop_column(TABLE, "scenarios")
