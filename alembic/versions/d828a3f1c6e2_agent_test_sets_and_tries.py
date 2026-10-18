"""agent tests: a versioned test set per run and several tries per test (D-828)

Founder, 19 Oct 2026: runs compared different tests ("2 of 12" against "0 of 13") and one
conversation per test proved nothing either way. A run now asks one version of the agent's
test set, "Test again" asks the same version, and every test is tried several times.

`agent_test_runs.set_version`: the version of the agent's test set the run asked (null on
runs before D-828). `trials`: tries per test planned (1 on earlier runs, which had one).
`trials_done` and `trial_started`: the compare-and-swap guards of the one-job-per-try chain.
`trial_results`: each finished try's results, aggregated into `results` by the last try.
`practice_callers`: the owner asked for AI-written practice callers in this new set.

Columns only; the table's FORCEd RLS policy (f7c3a9e15d26) covers them. Downgrade drops
them; the stored tries of finished runs are lost with them, their aggregated `results` stay.

Revision ID: d828a3f1c6e2
Revises: e4b7c2d9a183
Create Date: 2026-10-19 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d828a3f1c6e2"
down_revision: str | None = "e4b7c2d9a183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "agent_test_runs"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(RUNS, sa.Column("set_version", sa.Integer(), nullable=True))
    op.add_column(
        RUNS, sa.Column("trials", sa.SmallInteger(), server_default="1", nullable=False)
    )
    op.add_column(
        RUNS, sa.Column("trials_done", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.add_column(
        RUNS, sa.Column("trial_started", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.add_column(
        RUNS,
        sa.Column("trial_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        RUNS,
        sa.Column("practice_callers", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(op.f(f"ck_{RUNS}_trials_range"), RUNS, "trials BETWEEN 1 AND 5")
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_trials_done_range"),
        RUNS,
        "trials_done BETWEEN 0 AND trials AND trial_started BETWEEN trials_done AND trials",
    )
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_trial_results_is_array"),
        RUNS,
        "trial_results IS NULL OR jsonb_typeof(trial_results) = 'array'",
    )
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_set_version_positive"), RUNS, "set_version IS NULL OR set_version >= 1"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name in (
        "set_version_positive",
        "trial_results_is_array",
        "trials_done_range",
        "trials_range",
    ):
        op.drop_constraint(op.f(f"ck_{RUNS}_{name}"), RUNS, type_="check")
    for column in (
        "practice_callers",
        "trial_results",
        "trial_started",
        "trials_done",
        "trials",
        "set_version",
    ):
        op.drop_column(RUNS, column)
