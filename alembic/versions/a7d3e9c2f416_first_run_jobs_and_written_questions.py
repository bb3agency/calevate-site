"""first run: several jobs for one agent, and the owner's answers kept with their questions (D-863)

Founder, 23 Oct 2026:

- the job step is a multi-select, and the jobs picked are done by ONE agent. `first_runs.jobs`
  (`text[]`, one to three of the starter jobs, each once) replaces `first_runs.job`;
- the follow-up questions are written by our AI for this business, so a question is stored
  whole in `first_runs.questions` rather than as a key into a fixed set, and each answer is
  kept beside its question in `first_runs.answers` for the script writer.

TWO-STEP DEPRECATION (hard rule 8): this release stops writing `job` and reads `jobs`; the
column and its CHECK stay until the release after, when nothing running still writes it.
Existing rows are backfilled from it. `questions` keeps its column and CHECK; a row written in
the old `[{"key": ...}]` shape is read as the fixed question that key named
(`first_run/questions.legacy_questions`).

RLS is unchanged: both are columns of a table that already carries its FORCEd policy.

Downgrade drops both new columns and writes each run's first job back into `job` where it is
empty, so the previous release reads a run that started on this one.

Revision ID: a7d3e9c2f416
Revises: c3e8a1f5d702
Create Date: 2026-10-23 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from apps.api.db.migration_offline import execute_data_statement

revision: str = "a7d3e9c2f416"
down_revision: str | None = "c3e8a1f5d702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "first_runs"
#: Copied, not imported: this file keeps meaning what it meant on the day it ran.
_JOBS = ("answer_calls", "call_new_leads", "call_leads")
_JOBS_ARRAY = "ARRAY[" + ", ".join(f"'{job}'" for job in _JOBS) + "]::text[]"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        RUNS,
        sa.Column(
            "jobs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        RUNS,
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_jobs_enum"),
        RUNS,
        f"jobs <@ {_JOBS_ARRAY} AND cardinality(jobs) <= 3",
    )
    op.create_check_constraint(
        op.f(f"ck_{RUNS}_answers_is_array"), RUNS, "jsonb_typeof(answers) = 'array'"
    )
    execute_data_statement(
        sa.text(
            "UPDATE first_runs SET jobs = ARRAY[job] WHERE job IS NOT NULL AND jobs = '{}'"
        ),
        note="first_runs.jobs backfilled from job",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Lifted for the owner only, so the write-back sees every tenant's rows (d3b71c9a5e08).
    op.execute("ALTER TABLE first_runs NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            "UPDATE first_runs SET job = jobs[1] WHERE job IS NULL AND cardinality(jobs) > 0"
        ),
        note="first_runs.job written back from jobs",
    )
    op.execute("ALTER TABLE first_runs FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f(f"ck_{RUNS}_answers_is_array"), RUNS, type_="check")
    op.drop_constraint(op.f(f"ck_{RUNS}_jobs_enum"), RUNS, type_="check")
    op.drop_column(RUNS, "answers")
    op.drop_column(RUNS, "jobs")
