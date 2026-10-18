"""agent tests: why an improve round stopped, what the agent's inputs were, and tests marked wrong (D-823)

Founder, 18 Oct 2026 (rememory decision 565c8ef2): "Improve my agent" stops with a stated
reason instead of looping, a "Test again" with nothing changed is refused, and the owner can
mark a test wrong.

`agent_test_runs.improve_stop`: the terminal reason of the run's last improve round, one of
`IMPROVE_STOPS`. `agent_test_runs.inputs_hash`: a fingerprint of what the agent was tested
with (live script version, pinned facts, published knowledge, hand-over and call-back state),
so a retest of the same inputs can be refused. Both nullable; the table's FORCEd RLS policy
(f7c3a9e15d26) covers them.

`agent_test_labels`: a NEW tenant table, so its FORCEd policy ships here (hard rule 1); the
cross-tenant zero-rows proof is `tests/agent_test_improve_test.py`. One row per test the
owner marked wrong: the run, the scenario key, the saved test it came from, and a snapshot
of closed-set values (verdict, owner, probe, the judge's verdict and model) for calibrating
the judge later. No prose is stored: the conversation stays on the run.

Downgrade drops the table and the two columns; the labels are lost with it.

Revision ID: c7e2a9f4d3b1
Revises: b9e4c2d7a316
Create Date: 2026-10-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e2a9f4d3b1"
down_revision: str | None = "b9e4c2d7a316"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "agent_test_runs"
TABLE = "agent_test_labels"
IMPROVE_STOPS = ("completed", "no_change", "nothing_fixable_by_script", "budget", "failed")
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(RUNS, sa.Column("improve_stop", sa.Text(), nullable=True))
    op.add_column(RUNS, sa.Column("inputs_hash", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_improve_stop_enum"),
        RUNS,
        f"improve_stop IS NULL OR improve_stop IN {IMPROVE_STOPS!r}",
    )
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("test_key", sa.Text(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.Text(), server_default="wrong", nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("label IN ('wrong')", name=op.f(f"ck_{TABLE}_label_enum")),
        sa.CheckConstraint(
            "char_length(test_key) BETWEEN 1 AND 120", name=op.f(f"ck_{TABLE}_test_key_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name=op.f(f"ck_{TABLE}_snapshot_is_object")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint("run_id", "test_key", name=op.f(f"uq_{TABLE}_run_id_test_key")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f(f"fk_{TABLE}_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{RUNS}.id"],
            name=op.f(f"fk_{TABLE}_run_id_{RUNS}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["agent_test_cases.id"],
            name=op.f(f"fk_{TABLE}_case_id_agent_test_cases"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f(f"ix_{TABLE}_agent_id"), TABLE, ["agent_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index(op.f(f"ix_{TABLE}_agent_id"), table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_constraint(op.f(f"ck_{RUNS}_improve_stop_enum"), RUNS, type_="check")
    op.drop_column(RUNS, "inputs_hash")
    op.drop_column(RUNS, "improve_stop")
