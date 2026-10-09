"""copilot actions and jobs — the assistant's activity log, its Undo and its background work

Revision ID: e6c2a9d41f07
Revises: b4d8e1f3a6c9
Create Date: 2026-10-09 00:00:00.000000

D-694. Three tables.

`copilot_actions` is one row per thing the CLIENT assistant did, tried or is waiting to be
allowed to do: who asked, the tool, its tier, the arguments after redaction, the state the
record was in BEFORE the action (`prior_state`, enough to invert it) and after it
(`result_state`, the compare value of the inverse's compare-and-swap), how long the Undo
stays offered, and whether it was undone. A refusal is a row too, with no arguments. A
CONFIRM-tier action reached by a background job waits here as `pending_approval`, holding
the exact arguments it would run with in `pending_args` until a person decides; the column
is cleared on the decision. It is tenant data and carries the FORCEd tenant policy.

`admin_copilot_actions` is the admin realm's twin. A SECOND TABLE rather than a realm
column, for the reason `admin_copilot_memories` and `admin_copilot_conversation_turns`
already give: the actor is an `admin_users.id`, not a `users.id`, and an operator's action
on platform state has no tenant whose policy could hold the row. A nullable `tenant_id`
under a realm discriminator would be a policy that cannot be written. It carries no
tenant_id and no policy; `viewing_tenant_id` is context, SET NULL on tenant delete.

`copilot_jobs` is one background job: a request bigger than the interactive budget,
handed to an ARQ worker, with its progress written here so the panel can poll or stream
it. Tenant data, FORCEd tenant policy. `progress` is a bounded jsonb array.

Neither the action log nor the jobs table is append-only: an action becomes `undone`, an
approval is decided, a job moves through its states. The immutable record of every act is
still `audit_log`, which each act writes in its own transaction.

REVERSIBILITY. `downgrade()` drops the three tables. Nothing here is the only record of
anything: every executed act has its `audit_log` row and every paid model turn its
`usage_events` rows, both of which survive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6c2a9d41f07"
down_revision: str | None = "b4d8e1f3a6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = "copilot_actions"
ADMIN_ACTIONS = "admin_copilot_actions"
JOBS = "copilot_jobs"

_MAX_TEXT = 500
_MAX_CONTENT = 2_000
_MAX_PROGRESS = 200


def _policy(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _action_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tool", sa.String(length=80), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.String(length=80), nullable=True),
        sa.Column("args_redacted", postgresql.JSONB(), nullable=True),
        sa.Column("prior_state", postgresql.JSONB(), nullable=True),
        sa.Column("result_state", postgresql.JSONB(), nullable=True),
        sa.Column("pending_args", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("undoable_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    ]


def _action_checks(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "status IN ('done', 'undone', 'refused', 'pending_approval', 'rejected', "
            "'expired')",
            name=op.f(f"ck_{table}_status_enum"),
        ),
        sa.CheckConstraint("tier IN ('immediate', 'confirm')", name=op.f(f"ck_{table}_tier_enum")),
        sa.CheckConstraint(
            "source IN ('interactive', 'job')", name=op.f(f"ck_{table}_source_enum")
        ),
        # The undo pair moves together, so "undone with no instant" and "an instant on a
        # row that was not undone" are both unrepresentable.
        sa.CheckConstraint(
            "(status = 'undone') = (undone_at IS NOT NULL)", name=op.f(f"ck_{table}_undone_pair")
        ),
        # Executable intent never outlives the decision about it.
        sa.CheckConstraint(
            "pending_args IS NULL OR status = 'pending_approval'",
            name=op.f(f"ck_{table}_pending_args_only_pending"),
        ),
        # "Attempts are logged even when refused" — without their arguments.
        sa.CheckConstraint(
            "status <> 'refused' OR args_redacted IS NULL",
            name=op.f(f"ck_{table}_refusal_has_no_args"),
        ),
        sa.CheckConstraint(
            f"summary IS NULL OR length(summary) <= {_MAX_TEXT}",
            name=op.f(f"ck_{table}_summary_cap"),
        ),
        sa.CheckConstraint(
            f"refusal_reason IS NULL OR length(refusal_reason) <= {_MAX_TEXT}",
            name=op.f(f"ck_{table}_refusal_reason_cap"),
        ),
    ]


def _add_fks(table: str, fks: Sequence[tuple[str, str, str]]) -> None:
    """NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape, on empty new tables."""
    for column, referred, on_delete in fks:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column}_{referred} "
            f"FOREIGN KEY ({column}) REFERENCES {referred} (id) ON DELETE {on_delete} NOT VALID"
        )
    for column, referred, _ in fks:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_{column}_{referred}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # --- background jobs (first: the action log references it) ----------------------
    op.create_table(
        JOBS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("screen_route", sa.String(length=200), nullable=False),
        sa.Column(
            "progress",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name=op.f(f"ck_{JOBS}_status_enum"),
        ),
        sa.CheckConstraint("length(btrim(goal)) > 0", name=op.f(f"ck_{JOBS}_goal_not_blank")),
        sa.CheckConstraint(f"length(goal) <= {_MAX_CONTENT}", name=op.f(f"ck_{JOBS}_goal_cap")),
        sa.CheckConstraint(
            f"result IS NULL OR length(result) <= {_MAX_CONTENT * 2}",
            name=op.f(f"ck_{JOBS}_result_cap"),
        ),
        sa.CheckConstraint(
            f"jsonb_array_length(progress) <= {_MAX_PROGRESS}",
            name=op.f(f"ck_{JOBS}_progress_cap"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{JOBS}")),
    )
    op.create_index(
        op.f(f"ix_{JOBS}_tenant_user_recent"), JOBS, ["tenant_id", "user_id", "created_at"]
    )
    _add_fks(
        JOBS,
        (
            # RESTRICT: offboarding is an explicit workflow (FLOWS §9), never a cascade.
            ("tenant_id", "organizations", "RESTRICT"),
            # CASCADE: a deleted person's background work has no subject left.
            ("user_id", "users", "CASCADE"),
        ),
    )
    op.execute(f"ALTER TABLE {JOBS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {JOBS} FORCE ROW LEVEL SECURITY")
    op.execute(_policy(JOBS))

    # --- the client realm's action log -------------------------------------------------
    op.create_table(
        ACTIONS,
        *_action_columns(),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("undone_by", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        *_action_checks(ACTIONS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ACTIONS}")),
    )
    # The activity log a person reads: their own rows, newest first.
    op.create_index(
        op.f(f"ix_{ACTIONS}_tenant_actor_recent"),
        ACTIONS,
        ["tenant_id", "actor_user_id", "created_at"],
    )
    # The Approvals inbox: a partial index, because pending rows are a sliver of the log.
    op.create_index(
        op.f(f"ix_{ACTIONS}_pending"),
        ACTIONS,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status = 'pending_approval'"),
    )
    _add_fks(
        ACTIONS,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            # SET NULL: the row is the account's record of what its assistant did, and it
            # outlives the colleague who asked. `audit_log` holds the attribution.
            ("actor_user_id", "users", "SET NULL"),
            ("job_id", "copilot_jobs", "SET NULL"),
            ("undone_by", "users", "SET NULL"),
            ("decided_by", "users", "SET NULL"),
        ),
    )
    op.execute(f"ALTER TABLE {ACTIONS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {ACTIONS} FORCE ROW LEVEL SECURITY")
    op.execute(_policy(ACTIONS))

    # --- the admin realm's action log --------------------------------------------------
    # No tenant_id, no policy: see the module docstring. `db/registry.py` carries the
    # standing justification, which is what `scripts/check_rls_coverage.py` reads.
    op.create_table(
        ADMIN_ACTIONS,
        *_action_columns(),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column("viewing_tenant_id", sa.UUID(), nullable=True),
        sa.Column("undone_by", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        *_action_checks(ADMIN_ACTIONS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ADMIN_ACTIONS}")),
    )
    op.create_index(
        op.f(f"ix_{ADMIN_ACTIONS}_actor_recent"), ADMIN_ACTIONS, ["admin_user_id", "created_at"]
    )
    _add_fks(
        ADMIN_ACTIONS,
        (
            ("admin_user_id", "admin_users", "SET NULL"),
            ("viewing_tenant_id", "organizations", "SET NULL"),
            ("undone_by", "admin_users", "SET NULL"),
            ("decided_by", "admin_users", "SET NULL"),
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(ADMIN_ACTIONS)
    op.drop_table(ACTIONS)
    op.drop_table(JOBS)
