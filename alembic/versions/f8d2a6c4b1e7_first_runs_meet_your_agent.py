"""a new owner's first run ("Meet your agent") and its spoken brief's recordings (D-855)

Founder, 23 Oct 2026: the first thing a new owner sees is building their first agent (its job,
a brief in their own words, up to three follow-up questions, a build they watch, a test call to
their own phone), not the business setup wizard.

`first_runs` is one row per client (`UNIQUE(tenant_id)`): the job and languages chosen, the
brief, the follow-up questions a worker wrote, the build's progress step by step, the agent it
built, and when the owner finished or put it aside. It is also the first-run marker the
sign-in junction reads: `business_profiles.setup_started_at` cannot serve, because any profile
save sets it. `question_runs` and `build_runs` bound how many times the model is asked.

`first_run_recordings` is one row per spoken piece of the brief (up to three of 30 s): the
object key of the audio until a worker has heard it, then the words. The key is cleared when
the audio is deleted, which happens as soon as the words exist.

Tenant data, so both carry `tenant_id` and the FORCEd `tenant_isolation` policy (hard rule 1);
the cross-tenant zero-rows proof is `tests/first_run_test.py`. An account's erasure deletes
both (`workers/retention.execute_tenant_erasure`).

`business_copies.last_trigger` gains `first_run`: the examples are written again once the owner
has described the business in their own words.

Downgrade drops both tables with their policies and restores the trigger list; an account
mid-way through its first run lands on the dashboard instead.

Revision ID: f8d2a6c4b1e7
Revises: b7e2d4f9a613
Create Date: 2026-10-23 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f8d2a6c4b1e7"
down_revision: str | None = "b7e2d4f9a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "first_runs"
RECORDINGS = "first_run_recordings"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `first_run/models.py`, spelled here because a migration must not import application code
#: that will change after it.
_JOBS = ("answer_calls", "call_new_leads", "call_leads")
_QUESTION_STATES = ("idle", "writing", "ready", "failed")
_BUILD_STATES = ("idle", "building", "built", "failed")
_RECORDING_STATES = ("queued", "hearing", "heard", "failed")

_COPY_TRIGGERS_BEFORE = ("signup", "refresh", "scheduled", "operator")
_COPY_TRIGGERS_AFTER = (*_COPY_TRIGGERS_BEFORE, "first_run")


def _stamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        RUNS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("job", sa.Text(), nullable=True),
        sa.Column("language_primary", sa.Text(), nullable=True),
        sa.Column(
            "languages_extra",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("questions_status", sa.Text(), server_default="idle", nullable=False),
        sa.Column(
            "questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("questions_disclosure", sa.Text(), nullable=True),
        sa.Column("questions_brief_hash", sa.Text(), nullable=True),
        sa.Column("question_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("build_status", sa.Text(), server_default="idle", nullable=False),
        sa.Column(
            "build_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("build_disclosure", sa.Text(), nullable=True),
        sa.Column("build_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("build_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"job IS NULL OR job IN {_JOBS!r}", name=op.f(f"ck_{RUNS}_job_enum")),
        sa.CheckConstraint(
            f"questions_status IN {_QUESTION_STATES!r}",
            name=op.f(f"ck_{RUNS}_questions_status_enum"),
        ),
        sa.CheckConstraint(
            f"build_status IN {_BUILD_STATES!r}", name=op.f(f"ck_{RUNS}_build_status_enum")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(questions) = 'array'", name=op.f(f"ck_{RUNS}_questions_is_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(build_steps) = 'object'", name=op.f(f"ck_{RUNS}_build_steps_is_object")
        ),
        sa.CheckConstraint(
            "brief IS NULL OR char_length(brief) <= 4000", name=op.f(f"ck_{RUNS}_brief_length")
        ),
        sa.CheckConstraint(
            "question_runs >= 0 AND build_runs >= 0", name=op.f(f"ck_{RUNS}_runs_not_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RUNS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{RUNS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{RUNS}_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_first_runs_tenant"),
    )
    _isolate(RUNS)

    op.create_table(
        RECORDINGS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("first_run_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("words", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            f"status IN {_RECORDING_STATES!r}", name=op.f(f"ck_{RECORDINGS}_status_enum")
        ),
        sa.CheckConstraint(
            "words IS NULL OR char_length(words) <= 2000", name=op.f(f"ck_{RECORDINGS}_words_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RECORDINGS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{RECORDINGS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["first_run_id"],
            [f"{RUNS}.id"],
            name=op.f(f"fk_{RECORDINGS}_first_run_id_first_runs"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_first_run_recordings_run", RECORDINGS, ["first_run_id", "created_at"], unique=False
    )
    _isolate(RECORDINGS)

    op.drop_constraint(
        op.f("ck_business_copies_last_trigger_enum"), "business_copies", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_business_copies_last_trigger_enum"),
        "business_copies",
        f"last_trigger IS NULL OR last_trigger IN {_COPY_TRIGGERS_AFTER!r}",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Lifted for the owner only, so the rewrite sees every tenant's rows (d3b71c9a5e08).
    op.execute("ALTER TABLE business_copies NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE business_copies SET last_trigger = 'refresh' WHERE last_trigger = 'first_run'"
    )
    op.execute("ALTER TABLE business_copies FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        op.f("ck_business_copies_last_trigger_enum"), "business_copies", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_business_copies_last_trigger_enum"),
        "business_copies",
        f"last_trigger IS NULL OR last_trigger IN {_COPY_TRIGGERS_BEFORE!r}",
    )
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {RECORDINGS}")
    op.drop_index("ix_first_run_recordings_run", table_name=RECORDINGS)
    op.drop_table(RECORDINGS)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {RUNS}")
    op.drop_table(RUNS)
