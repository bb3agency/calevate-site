"""A/B script experiments, and the arm a call actually ran

Revision ID: b3c8f27d41ae
Revises: a8d4f21c9b06
Create Date: 2026-08-13 10:00:00.000000

ROADMAP M3: "A/B greeting/script testing with conversion attribution". Three tables.

WHY THE ASSIGNMENT IS A ROW AND NOT A FUNCTION
-----------------------------------------------
`call_variant_assignments` is the load-bearing table here, and the design question it
answers is the one this feature is easiest to get wrong.

Which arm a call ran is derivable: hash the contact, mod the bucket space, compare
against the split. So it is tempting not to store it — one fewer table, one fewer write
on the dial path, and the reporting query can compute it. That is wrong, and it is wrong
in a way that produces no error and no log line: **the split is mutable**. Ramp 50/50 to
80/20 and every historical call silently re-attributes to the arm it never ran. Every
conversion rate on the screen moves. Nothing says why, and nobody can tell from the data
that anything happened. The same failure arrives, more slowly, from a variant edit or a
second experiment on the same agent.

So the derivation stays deterministic (`agents/assignment.py`, blake2b over
experiment-id + contact) because determinism is what makes an assignment EXPLAINABLE,
and the result is written down because an explanation is not evidence. UNIQUE on
`call_id`: one call, one arm, forever; the only writer uses `ON CONFLICT DO NOTHING` so a
replayed dispatch cannot move a call between arms.

The row does NOT carry the hash input. The assignment unit is a lead id or a destination
number, and a phone number copied into a second table is a second place it has to be
erased from under DPDP — the call it points at already holds it.

ONE RUNNING EXPERIMENT PER AGENT — A PARTIAL UNIQUE INDEX, NOT A CHECK
-----------------------------------------------------------------------
Two overlapping experiments on one agent would each attribute the same calls, and
neither result would mean anything. `uq_prompt_experiments_one_running_per_agent` is a
UNIQUE INDEX on `(agent_id) WHERE status = 'running'`, so the constraint is enforced by
the database against concurrent writers rather than by a read-then-write in the service
(BACKEND-PATTERNS §5). Concluded experiments are unconstrained, which is what keeps the
history — an agent accumulates as many past tests as it has run.

TWO ARMS, AND THE DISCLOSURE ON EACH
--------------------------------------
`label IN ('A','B')` plus `UNIQUE(experiment_id, label)` caps an experiment at two arms.
That is not a shortcut: three arms make three pairwise 95% intervals whose family-wise
error rate is not 5%, and `agents/proportions.py` implements no multiplicity correction.
A schema that admitted a third arm would let the surface make a claim the arithmetic
cannot support.

`disclosure_line` is NOT NULL with `length(btrim(...)) > 0` — the same shape as
`agents.disclosure_nonempty`, because an arm is what a caller actually hears and hard
rule 5 admits no exception for a variant. There is no value of this column, and no
absence of one, that publishes an arm nobody was told about.

`weight_bp` is basis points with a 5%-either-side range CHECK. A CHECK cannot see the
sibling row, so the "two arms sum to 10000" invariant is enforced by
`agents/experiments.py::start`, which is the only writer.

RLS (hard rule 1)
-----------------
All three tables carry `tenant_id` and get ENABLE + FORCE + the DATA-MODEL §1
`tenant_isolation` policy in THIS migration. The cross-tenant zero-rows proof is
`tests/prompt_experiment_test.py::test_tenant_b_sees_no_rows_of_tenant_a`, which asserts
it on raw RLS-scoped sessions against all three tables, so a service that filtered in
Python would still fail.

LOCKING (hard rule 8)
---------------------
`CREATE TABLE` locks only itself. Every FK points OUT — at `organizations`, `agents`,
`prompt_versions` and `calls` — and a validated FK takes SHARE ROW EXCLUSIVE on the
REFERENCED table for the length of its validation. `calls` is written by every webhook
and every dial, so each FK is added NOT VALID (a catalogue write) and VALIDATEd
separately (SHARE UPDATE EXCLUSIVE, which does not block inserts), under a `lock_timeout`
so a migration that cannot get its lock fails fast rather than queueing in front of the
dial path.

`prompt_experiments.promoted_variant_id` points at `prompt_experiment_variants`, which
does not exist yet when the first table is created — the same circular-FK situation
`agents` ↔ `prompt_versions` already has, resolved the same way: the column is created
bare and the constraint added after both tables exist.

DOWNGRADE
---------
Drops policies, indexes and tables in dependency order, and is exercised
(upgrade → downgrade → upgrade) rather than assumed. It loses the recorded assignments,
which is unavoidable — this is the only place they live — and any experiment mid-flight
becomes unattributable. A revert is therefore a measurement decision, not a rollback
detail. It does NOT touch `agents`: promotion writes through `prompt_versions`, so a
promoted script survives the revert exactly as any other version does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c8f27d41ae"
down_revision: str | None = "a8d4f21c9b06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("prompt_experiments", "prompt_experiment_variants", "call_variant_assignments")


# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
def _policy(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "prompt_experiments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column("conversion_metric", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concluded_at", sa.DateTime(timezone=True), nullable=True),
        # Bare: the table it references is created below (circular FK, same resolution
        # as agents ↔ prompt_versions).
        sa.Column("promoted_variant_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('running', 'concluded')", name=op.f("ck_prompt_experiments_status")
        ),
        # The two metrics `agents/models.py::CONVERSION_METRICS` can express as SQL.
        # Repeated here rather than imported because a migration cannot import
        # application code and must still constrain the same set.
        sa.CheckConstraint(
            "conversion_metric IN ('call_outcome_resolved', 'lead_won')",
            name=op.f("ck_prompt_experiments_conversion_metric"),
        ),
        # A concluded experiment states when; a running one cannot.
        sa.CheckConstraint(
            "(status = 'concluded') = (concluded_at IS NOT NULL)",
            name=op.f("ck_prompt_experiments_concluded_at_matches_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_experiments")),
    )
    op.create_index(
        op.f("ix_prompt_experiments_tenant_id"), "prompt_experiments", ["tenant_id"], unique=False
    )
    # The results read and the conclude path both look up "this agent's latest".
    op.create_index(
        "ix_prompt_experiments_agent_started",
        "prompt_experiments",
        ["agent_id", "started_at"],
        unique=False,
    )
    # At most one running test per agent — see the module docstring.
    op.create_index(
        "uq_prompt_experiments_one_running_per_agent",
        "prompt_experiments",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "prompt_experiment_variants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("prompt_version_id", sa.UUID(), nullable=False),
        sa.Column("disclosure_line", sa.Text(), nullable=False),
        sa.Column("weight_bp", sa.Integer(), nullable=False),
        sa.Column("engine_agent_ref", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("label IN ('A', 'B')", name=op.f("ck_prompt_experiment_variants_label")),
        sa.CheckConstraint(
            "weight_bp BETWEEN 500 AND 9500",
            name=op.f("ck_prompt_experiment_variants_weight_range"),
        ),
        # Hard rule 5: an arm is what the caller hears, so it always states who is calling.
        sa.CheckConstraint(
            "length(btrim(disclosure_line)) > 0",
            name=op.f("ck_prompt_experiment_variants_disclosure_nonempty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_experiment_variants")),
        sa.UniqueConstraint(
            "experiment_id", "label", name=op.f("uq_prompt_experiment_variants_label")
        ),
    )
    op.create_index(
        op.f("ix_prompt_experiment_variants_tenant_id"),
        "prompt_experiment_variants",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "call_variant_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_variant_assignments")),
        # ONE call, ONE arm, forever.
        sa.UniqueConstraint("call_id", name=op.f("uq_call_variant_assignments_call_id")),
    )
    op.create_index(
        op.f("ix_call_variant_assignments_tenant_id"),
        "call_variant_assignments",
        ["tenant_id"],
        unique=False,
    )
    # The attribution query groups by arm; without this it seq-scans every assignment
    # the tenant has ever made to score one experiment.
    op.create_index(
        "ix_call_variant_assignments_variant_id",
        "call_variant_assignments",
        ["variant_id"],
        unique=False,
    )

    # --- foreign keys: NOT VALID first, VALIDATE second (see LOCKING) ---------------
    for statement in (
        "ALTER TABLE prompt_experiments ADD CONSTRAINT "
        "fk_prompt_experiments_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        "ALTER TABLE prompt_experiments ADD CONSTRAINT fk_prompt_experiments_agent_id_agents "
        "FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE RESTRICT NOT VALID",
        "ALTER TABLE prompt_experiments ADD CONSTRAINT "
        "fk_prompt_experiments_promoted_variant_id FOREIGN KEY (promoted_variant_id) "
        "REFERENCES prompt_experiment_variants (id) ON DELETE SET NULL NOT VALID",
        "ALTER TABLE prompt_experiment_variants ADD CONSTRAINT "
        "fk_prompt_experiment_variants_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        # CASCADE: an arm has no meaning without its experiment, and the experiment row
        # is never deleted by any code path — this is a cleanup contract, not a feature.
        "ALTER TABLE prompt_experiment_variants ADD CONSTRAINT "
        "fk_prompt_experiment_variants_experiment_id FOREIGN KEY (experiment_id) "
        "REFERENCES prompt_experiments (id) ON DELETE CASCADE NOT VALID",
        # RESTRICT: the version an experiment ran must stay readable, or the history
        # cannot say what was tested.
        "ALTER TABLE prompt_experiment_variants ADD CONSTRAINT "
        "fk_prompt_experiment_variants_prompt_version_id FOREIGN KEY (prompt_version_id) "
        "REFERENCES prompt_versions (id) ON DELETE RESTRICT NOT VALID",
        "ALTER TABLE call_variant_assignments ADD CONSTRAINT "
        "fk_call_variant_assignments_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        # CASCADE on the call: retention erasure deletes calls, and an assignment that
        # outlived its call would be a dangling row pointing at nothing.
        "ALTER TABLE call_variant_assignments ADD CONSTRAINT "
        "fk_call_variant_assignments_call_id FOREIGN KEY (call_id) "
        "REFERENCES calls (id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE call_variant_assignments ADD CONSTRAINT "
        "fk_call_variant_assignments_experiment_id FOREIGN KEY (experiment_id) "
        "REFERENCES prompt_experiments (id) ON DELETE RESTRICT NOT VALID",
        "ALTER TABLE call_variant_assignments ADD CONSTRAINT "
        "fk_call_variant_assignments_variant_id FOREIGN KEY (variant_id) "
        "REFERENCES prompt_experiment_variants (id) ON DELETE RESTRICT NOT VALID",
    ):
        op.execute(statement)

    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint, table in (
        ("fk_prompt_experiments_tenant_id_organizations", "prompt_experiments"),
        ("fk_prompt_experiments_agent_id_agents", "prompt_experiments"),
        ("fk_prompt_experiments_promoted_variant_id", "prompt_experiments"),
        ("fk_prompt_experiment_variants_tenant_id_organizations", "prompt_experiment_variants"),
        ("fk_prompt_experiment_variants_experiment_id", "prompt_experiment_variants"),
        ("fk_prompt_experiment_variants_prompt_version_id", "prompt_experiment_variants"),
        ("fk_call_variant_assignments_tenant_id_organizations", "call_variant_assignments"),
        ("fk_call_variant_assignments_call_id", "call_variant_assignments"),
        ("fk_call_variant_assignments_experiment_id", "call_variant_assignments"),
        ("fk_call_variant_assignments_variant_id", "call_variant_assignments"),
    ):
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")

    # Hard rule 1, in the same migration as the tables it protects.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_policy(table))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_call_variant_assignments_variant_id", table_name="call_variant_assignments")
    op.drop_index(
        op.f("ix_call_variant_assignments_tenant_id"), table_name="call_variant_assignments"
    )
    op.drop_table("call_variant_assignments")
    op.drop_index(
        op.f("ix_prompt_experiment_variants_tenant_id"), table_name="prompt_experiment_variants"
    )
    # The circular FK has to be broken by hand before either end can be dropped:
    # `prompt_experiments.promoted_variant_id` points FORWARD at the variants table, so
    # dropping variants first fails with a dependency error and dropping experiments
    # first fails on the variants' own `experiment_id`. (This is why the round trip is
    # exercised rather than assumed — it failed the first time it was run.)
    op.execute(
        "ALTER TABLE prompt_experiments DROP CONSTRAINT IF EXISTS "
        "fk_prompt_experiments_promoted_variant_id"
    )
    op.drop_table("prompt_experiment_variants")
    op.drop_index("uq_prompt_experiments_one_running_per_agent", table_name="prompt_experiments")
    op.drop_index("ix_prompt_experiments_agent_started", table_name="prompt_experiments")
    op.drop_index(op.f("ix_prompt_experiments_tenant_id"), table_name="prompt_experiments")
    op.drop_table("prompt_experiments")
