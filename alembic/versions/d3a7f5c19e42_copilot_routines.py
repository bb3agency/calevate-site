"""copilot routines — instructions the assistant runs on a schedule, and their run history

Revision ID: d3a7f5c19e42
Revises: a2f7c4e9d61b
Create Date: 2026-10-09 22:00:00.000000

D-694's background routines. Two tenant tables.

`copilot_routines` is one standing instruction a person gave the assistant ("every morning,
call back yesterday's missed leads"), with a schedule in IST (`days` as a Monday-first
seven-bit mask, `at_minute` as minutes after IST midnight) and `next_run_at`, the instant the
next run is due. A routine is personal, like `copilot_jobs`: it runs AS the person who wrote
it, through that person's own permissions, and is visible only to them. `instruction` is
redacted on write (`copilot/memory.redacted_content`), the same as a job's goal.

`next_run_at IS NOT NULL` exactly when the routine is enabled, held by a CHECK, so "enabled
but never due" and "disabled but due" are unrepresentable and the due query needs one
predicate.

THE TICK READS ACROSS TENANTS, so `copilot_routines` carries `kb_uploads`' asymmetric pair
(migration f2b91c47e0a3): `tenant_isolation` is the strict own-tenant form for every verb,
and `copilot_routines_ops_read` lets an UNTENANTED session — the routine tick, which has no
tenant — SELECT. The tick reads ids and due instants only; every write it makes happens in a
tenant session. A worklist row per tenant (`retention_worklist`'s shape) was the alternative,
and it costs a tenant session per tenant per minute to find out that nothing is due; this
costs one indexed read.

`copilot_routine_runs` is one firing of a routine: the slot it was due for, whether it was a
scheduled or a manual run, whether a background job was queued for it or why it was skipped,
and the job. `UNIQUE (routine_id, slot_at)` makes a slot fire once however many ticks see it.

REVERSIBILITY. `downgrade()` drops both tables. What a routine DID is in `copilot_jobs`,
`copilot_actions` and `audit_log`, none of which this touches.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a7f5c19e42"
down_revision: str | None = "a2f7c4e9d61b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUTINES = "copilot_routines"
RUNS = "copilot_routine_runs"
OPS_READ_POLICY = "copilot_routines_ops_read"

_MAX_NAME = 80
_MAX_INSTRUCTION = 2_000
_MAX_REASON = 300

# Spelled out rather than imported, as every migration here spells its constants.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
#: `retention_worklist_ops_read`'s form, verbatim: the untenanted worker, and only it.
_UNTENANTED = f"({_GUC} IS NULL)"


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
        ROUTINES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=_MAX_NAME), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("days", sa.SmallInteger(), nullable=False),
        sa.Column("at_minute", sa.SmallInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f(f"ck_{ROUTINES}_name_not_blank")),
        sa.CheckConstraint(
            "length(btrim(instruction)) > 0", name=op.f(f"ck_{ROUTINES}_instruction_not_blank")
        ),
        sa.CheckConstraint(
            f"length(instruction) <= {_MAX_INSTRUCTION}", name=op.f(f"ck_{ROUTINES}_instruction_cap")
        ),
        sa.CheckConstraint("days BETWEEN 1 AND 127", name=op.f(f"ck_{ROUTINES}_days_mask")),
        sa.CheckConstraint(
            "at_minute BETWEEN 0 AND 1439", name=op.f(f"ck_{ROUTINES}_at_minute_range")
        ),
        sa.CheckConstraint(
            "enabled = (next_run_at IS NOT NULL)", name=op.f(f"ck_{ROUTINES}_due_iff_enabled")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ROUTINES}")),
    )
    op.create_index(
        op.f(f"ix_{ROUTINES}_tenant_user_recent"), ROUTINES, ["tenant_id", "user_id", "created_at"]
    )
    # The tick's one read: enabled routines by due instant. Partial, because a disabled
    # routine is never due.
    op.create_index(
        op.f(f"ix_{ROUTINES}_due"),
        ROUTINES,
        ["next_run_at"],
        postgresql_where=sa.text("enabled"),
    )
    _add_fks(
        ROUTINES,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            # CASCADE: a routine runs AS its author, and has nobody to run as once they are gone.
            ("user_id", "users", "CASCADE"),
        ),
    )
    op.execute(f"ALTER TABLE {ROUTINES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {ROUTINES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {ROUTINES} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    op.execute(f"CREATE POLICY {OPS_READ_POLICY} ON {ROUTINES} FOR SELECT USING {_UNTENANTED}")

    op.create_table(
        RUNS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("routine_id", sa.UUID(), nullable=False),
        sa.Column("slot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual')", name=op.f(f"ck_{RUNS}_trigger_enum")
        ),
        sa.CheckConstraint("status IN ('queued', 'skipped')", name=op.f(f"ck_{RUNS}_status_enum")),
        # A skipped run always says why; a queued one has nothing to explain.
        sa.CheckConstraint(
            "(status = 'skipped') = (reason IS NOT NULL)", name=op.f(f"ck_{RUNS}_reason_iff_skipped")
        ),
        sa.CheckConstraint(
            f"reason IS NULL OR length(reason) <= {_MAX_REASON}", name=op.f(f"ck_{RUNS}_reason_cap")
        ),
        sa.UniqueConstraint("routine_id", "slot_at", name=op.f(f"uq_{RUNS}_routine_id_slot_at")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RUNS}")),
    )
    op.create_index(op.f(f"ix_{RUNS}_routine_recent"), RUNS, ["routine_id", "created_at"])
    _add_fks(
        RUNS,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            ("routine_id", ROUTINES, "CASCADE"),
            # SET NULL: a job can be erased with the activity log; the run still happened.
            ("job_id", "copilot_jobs", "SET NULL"),
        ),
    )
    op.execute(f"ALTER TABLE {RUNS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RUNS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {RUNS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(RUNS)
    op.execute(f"DROP POLICY IF EXISTS {OPS_READ_POLICY} ON {ROUTINES}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {ROUTINES}")
    op.drop_table(ROUTINES)
