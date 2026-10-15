"""calls track their content's deletion at the voice platform; workspaces their retention

Revision ID: e4b7d2a9c160
Revises: c7d4e1a95b38
Create Date: 2026-10-15 19:00:00.000000

ThinnestAI can now delete one call's recording and transcript (`DELETE /calls/{id}/content`)
and keep a workspace's calls for a set number of days (`callRetentionDays`)
(`thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/post-call/
delete-call-content.md:443-589`, `workspace/update-workspace.md:528-599`).

`calls`:

* `engine_content_delete_requested_at` — when a retention sweep or an erasure queued the
  deletion. The sweep selects only calls without it, so a call is queued once; the backstop
  re-queues one still owed a day later.
* `engine_content_deleted_at` — the platform's `contentDeletedAt`.
* `engine_content_recordings_pending` — files the platform still retries nightly; the
  deletion is settled at 0.

`calls` already has its tenant policy (FORCEd RLS); new columns on it need no new one.

`tenant_engine_workspaces`: the `callRetentionDays` we last confirmed on the client's
workspace, the plan's ceiling read with it, when, and our code for the last failure.

The partial index serves the backstop, which reads only the calls still owed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e4b7d2a9c160"
down_revision = "c7d4e1a95b38"
branch_labels = None
depends_on = None

_WORKSPACES = "tenant_engine_workspaces"
_PENDING_CK = "ck_calls_engine_content_recordings_pending_nonnegative"
_DAYS_CK = "ck_tenant_engine_workspaces_retention_days_positive"
_ERROR_CK = "ck_tenant_engine_workspaces_retention_error_code_bounded"
_INDEX = "ix_calls_engine_content_owed"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls",
        sa.Column("engine_content_delete_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calls", sa.Column("engine_content_deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "calls", sa.Column("engine_content_recordings_pending", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        op.f(_PENDING_CK),
        "calls",
        "engine_content_recordings_pending IS NULL OR engine_content_recordings_pending >= 0",
    )
    op.add_column(_WORKSPACES, sa.Column("retention_days", sa.Integer(), nullable=True))
    op.add_column(_WORKSPACES, sa.Column("retention_plan_days", sa.Integer(), nullable=True))
    op.add_column(
        _WORKSPACES, sa.Column("retention_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(_WORKSPACES, sa.Column("retention_error_code", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(_DAYS_CK),
        _WORKSPACES,
        "(retention_days IS NULL OR retention_days >= 1) "
        "AND (retention_plan_days IS NULL OR retention_plan_days >= 1)",
    )
    op.create_check_constraint(
        op.f(_ERROR_CK),
        _WORKSPACES,
        "retention_error_code IS NULL OR char_length(retention_error_code) <= 64",
    )
    # CONCURRENTLY: `calls` is written by every live call, and a plain build would block
    # those writes while it runs.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON calls "
            "(tenant_id, engine_content_delete_requested_at) "
            "WHERE engine_content_delete_requested_at IS NOT NULL "
            "AND (engine_content_deleted_at IS NULL OR engine_content_recordings_pending > 0)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_ERROR_CK), _WORKSPACES, type_="check")
    op.drop_constraint(op.f(_DAYS_CK), _WORKSPACES, type_="check")
    op.drop_column(_WORKSPACES, "retention_error_code")
    op.drop_column(_WORKSPACES, "retention_checked_at")
    op.drop_column(_WORKSPACES, "retention_plan_days")
    op.drop_column(_WORKSPACES, "retention_days")
    op.drop_constraint(op.f(_PENDING_CK), "calls", type_="check")
    op.drop_column("calls", "engine_content_recordings_pending")
    op.drop_column("calls", "engine_content_deleted_at")
    op.drop_column("calls", "engine_content_delete_requested_at")
