"""copilot plans — one approved set of targets, run exactly (D-893 F3)

Revision ID: f4b8d2a61c39
Revises: f2a6c8e1d5b9
Create Date: 2026-10-26 23:30:00.000000

A plan is what one approval covers when an action touches a set: who (the frozen targets),
why, when, the estimate, who is left out and why. Two tenant tables, and a `kind` on
campaigns so a dialling plan's campaign can be told from one a person built.

`copilot_plans` holds the action (a registry name), its canonical change arguments, the
lens as a person reads it (redacted), counts, the estimate in INR (NUMERIC; NULL is "not
known", never zero), a SHA-256 over all of it (`plan_hash`, what the confirm token binds),
the status (`proposed -> approved -> running -> done`, or `cancelled` / `expired`) and the
running tallies. It carries `copilot_routines`' asymmetric pair: the strict own-tenant
policy for every verb plus `copilot_plans_ops_read`, a `FOR SELECT` for the UNTENANTED
resume sweep that re-queues a plan whose worker died. Every write is in a tenant session.

`copilot_plan_targets` is one row per target, frozen when the plan is built: the target's
id and type, its order, `excluded` (left out when the plan was made, with the reason), and
its outcome (`pending | done | skipped | failed`, with a reason). `UNIQUE (plan_id,
target_id)` is what makes the run idempotent per target. No name or number is copied here;
the card reads names through the lead.

`campaigns.kind` is `standard` for every existing row (the column default) and `pip` for a
campaign a dialling plan creates, so the line limit, pacing, calling hours and retries of a
campaign apply to Pip's calls.

REVERSIBILITY. `downgrade()` drops the two tables and the column. What a plan DID is in the
leads, call-backs and campaigns it touched and in `audit_log`, none of which this touches;
dropping `kind` makes a `pip` campaign an ordinary one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "f4b8d2a61c39"
down_revision: str | None = "f2a6c8e1d5b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLANS = "copilot_plans"
TARGETS = "copilot_plan_targets"
OPS_READ_POLICY = "copilot_plans_ops_read"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_UNTENANTED = f"({_GUC} IS NULL)"

_PLAN_STATUSES = "('proposed', 'approved', 'running', 'done', 'cancelled', 'expired')"
_TARGET_STATUSES = "('pending', 'done', 'skipped', 'failed')"
_ORIGINS = "('pip', 'console')"
_TARGET_TYPES = "('lead', 'call', 'callback')"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
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

    op.create_table(
        PLANS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("lens_text", sa.Text(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("exclusions", postgresql.JSONB(), nullable=False),
        sa.Column("estimate_inr", sa.Numeric(14, 2), nullable=True),
        sa.Column("estimate_note", sa.Text(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"status IN {_PLAN_STATUSES}", name=op.f(f"ck_{PLANS}_status_enum")),
        sa.CheckConstraint(f"origin IN {_ORIGINS}", name=op.f(f"ck_{PLANS}_origin_enum")),
        sa.CheckConstraint(
            f"target_type IN {_TARGET_TYPES}", name=op.f(f"ck_{PLANS}_target_type_enum")
        ),
        sa.CheckConstraint(
            "target_count >= 0 AND excluded_count >= 0", name=op.f(f"ck_{PLANS}_counts")
        ),
        sa.CheckConstraint(
            "estimate_inr IS NULL OR estimate_inr >= 0", name=op.f(f"ck_{PLANS}_estimate")
        ),
        # An approved plan says when; one that has not been approved has no approval time.
        sa.CheckConstraint(
            "(status IN ('proposed', 'expired')) OR approved_at IS NOT NULL "
            "OR status = 'cancelled'",
            name=op.f(f"ck_{PLANS}_approved_at"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PLANS}")),
    )
    op.create_index(
        op.f(f"ix_{PLANS}_tenant_user_recent"), PLANS, ["tenant_id", "user_id", "created_at"]
    )
    # The resume sweep's one read: plans a worker should be holding.
    op.create_index(
        op.f(f"ix_{PLANS}_active"),
        PLANS,
        ["updated_at"],
        postgresql_where=sa.text("status IN ('approved', 'running')"),
    )
    _add_fks(
        PLANS,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            # CASCADE: a plan runs AS the person who approved it, and has nobody to run as
            # once they are gone; what it did is in the rows it touched and the audit log.
            ("user_id", "users", "CASCADE"),
            ("campaign_id", "campaigns", "SET NULL"),
        ),
    )
    op.execute(f"ALTER TABLE {PLANS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {PLANS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {PLANS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    op.execute(f"CREATE POLICY {OPS_READ_POLICY} ON {PLANS} FOR SELECT USING {_UNTENANTED}")

    op.create_table(
        TARGETS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("excluded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN {_TARGET_STATUSES}", name=op.f(f"ck_{TARGETS}_status_enum")
        ),
        # Left out when the plan was made: skipped from the start, and it always says why.
        sa.CheckConstraint(
            "NOT excluded OR (status = 'skipped' AND reason IS NOT NULL)",
            name=op.f(f"ck_{TARGETS}_excluded_says_why"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 300", name=op.f(f"ck_{TARGETS}_reason_cap")
        ),
        sa.UniqueConstraint("plan_id", "target_id", name=op.f(f"uq_{TARGETS}_plan_id_target_id")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TARGETS}")),
    )
    op.create_index(op.f(f"ix_{TARGETS}_plan_position"), TARGETS, ["plan_id", "position"])
    op.create_index(
        op.f(f"ix_{TARGETS}_pending"),
        TARGETS,
        ["plan_id", "position"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    _add_fks(
        TARGETS,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            ("plan_id", PLANS, "CASCADE"),
        ),
    )
    op.execute(f"ALTER TABLE {TARGETS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TARGETS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TARGETS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    op.add_column(
        "campaigns",
        sa.Column("kind", sa.String(length=16), server_default="standard", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_campaigns_kind_enum"), "campaigns", "kind IN ('standard', 'pip')"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_campaigns_kind_enum"), "campaigns", type_="check")
    op.drop_column("campaigns", "kind")
    op.drop_table(TARGETS)
    op.execute(f"DROP POLICY IF EXISTS {OPS_READ_POLICY} ON {PLANS}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {PLANS}")
    op.drop_table(PLANS)
