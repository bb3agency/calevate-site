"""The healer moves an agent off a voice callers cannot hear (D-987)

Revision ID: d7f3a9c1e5b2
Revises: c4e8a2f6d1b9
Create Date: 2026-11-13 10:00:00.000000

* `agent_voice_history`: per agent and voice, when its calls last went through with nothing
  the caller heard going wrong and when one last failed. The healer's "last working voice".
  Tenant data, FORCEd RLS in this migration (hard rule 1). Ids and times only.
* `agent_voice_switches`: one row per move of an agent to a backup voice, with the voice
  before and after, the rungs, why, its state and the probes since. Tenant data, FORCEd RLS.
  At most one switch per agent is in force (`uq_agent_voice_switches_active`).
* `calls.ended_before_agent`: the platform said the call ended before the agent spoke
  (`hangup` `before_agent`), the one hang-up during silence the platform names.
* `heal_incidents.summary`: the healer's draft post-incident summary.
* `heal_actions.outcome` gains `shadow`: a step a playbook in dry-run would have taken.
* `heal_client_incidents.kind` gains `voice_switched`.

REVERSIBILITY. `downgrade()` drops both tables and the three columns; the client notices of
the new kind become `agent_unwell`. `heal_actions` is append-only (its trigger refuses an
UPDATE), so its `shadow` rows are kept and the narrower CHECK comes back `NOT VALID`: new rows
are held to it and the old rows stay as history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "d7f3a9c1e5b2"
down_revision: str | None = "c4e8a2f6d1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HISTORY = "agent_voice_history"
SWITCHES = "agent_voice_switches"
CLIENT = "heal_client_incidents"
ACTIONS = "heal_actions"
INCIDENTS = "heal_incidents"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_VOICE_SHAPE = "^[^[:space:]]{1,128}$"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
_RUNGS = ("clear", "studio")
_REASONS = ("voice_failed", "silent_call")
_STATES = ("switched", "restored", "held", "stood_down", "undone", "shadow")
_OLD_KINDS = ("agent_unwell", "line_protected", "platform_outage", "script_fixed", "script_fix_waiting")
_NEW_KINDS = (*_OLD_KINDS, "voice_switched")
_OLD_OUTCOMES = ("ok", "failed", "skipped", "refused")
_NEW_OUTCOMES = (*_OLD_OUTCOMES, "shadow")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _tenant_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]


def _stamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    ]


def _force_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {table} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        HISTORY,
        *_tenant_columns(),
        sa.Column("engine_voice_id", sa.Text(), nullable=False),
        sa.Column("first_good_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_good_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            f"engine_voice_id ~ '{_VOICE_SHAPE}'", name=op.f(f"ck_{HISTORY}_voice_shape")
        ),
        sa.UniqueConstraint(
            "agent_id", "engine_voice_id", name=op.f(f"uq_{HISTORY}_agent_id_engine_voice_id")
        ),
    )
    op.create_index(
        "ix_agent_voice_history_agent_good",
        HISTORY,
        ["tenant_id", "agent_id", sa.text("last_good_at DESC")],
    )
    _force_rls(HISTORY)

    op.create_table(
        SWITCHES,
        *_tenant_columns(),
        sa.Column(
            "incident_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("heal_incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_voice", sa.Text(), nullable=False),
        sa.Column("to_voice", sa.Text(), nullable=False),
        sa.Column("from_rung", sa.Text(), nullable=False),
        sa.Column("to_rung", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="switched"),
        sa.Column("probes_passed", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("switched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(_in("from_rung", _RUNGS), name=op.f(f"ck_{SWITCHES}_from_rung_enum")),
        sa.CheckConstraint(_in("to_rung", _RUNGS), name=op.f(f"ck_{SWITCHES}_to_rung_enum")),
        sa.CheckConstraint(_in("reason", _REASONS), name=op.f(f"ck_{SWITCHES}_reason_enum")),
        sa.CheckConstraint(_in("state", _STATES), name=op.f(f"ck_{SWITCHES}_state_enum")),
        sa.CheckConstraint("from_voice <> to_voice", name=op.f(f"ck_{SWITCHES}_moves")),
        sa.CheckConstraint("probes_passed >= 0", name=op.f(f"ck_{SWITCHES}_probes_nonnegative")),
    )
    op.create_index(
        "uq_agent_voice_switches_active",
        SWITCHES,
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("state = 'switched'"),
    )
    op.create_index(
        "ix_agent_voice_switches_agent_recent",
        SWITCHES,
        ["tenant_id", "agent_id", sa.text("switched_at DESC")],
    )
    op.create_index("ix_agent_voice_switches_incident", SWITCHES, ["incident_id"])
    _force_rls(SWITCHES)

    op.add_column("calls", sa.Column("ended_before_agent", sa.Boolean(), nullable=True))
    op.add_column(INCIDENTS, sa.Column("summary", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(f"ck_{INCIDENTS}_summary_cap"), INCIDENTS, "summary IS NULL OR length(summary) <= 4000"
    )
    op.drop_constraint(op.f(f"ck_{ACTIONS}_outcome_enum"), ACTIONS, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{ACTIONS}_outcome_enum"), ACTIONS, _in("outcome", _NEW_OUTCOMES)
    )
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _NEW_KINDS))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {CLIENT} NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            f"UPDATE {CLIENT} SET kind = 'agent_unwell', updated_at = now() "
            "WHERE kind = 'voice_switched'"
        ),
        note="Turned the voice-switch notices back into the generic agent notice.",
    )
    op.execute(f"ALTER TABLE {CLIENT} FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _OLD_KINDS))
    op.drop_constraint(op.f(f"ck_{ACTIONS}_outcome_enum"), ACTIONS, type_="check")
    op.execute(
        f"ALTER TABLE {ACTIONS} ADD CONSTRAINT ck_{ACTIONS}_outcome_enum "
        f"CHECK ({_in('outcome', _OLD_OUTCOMES)}) NOT VALID"
    )
    op.drop_constraint(op.f(f"ck_{INCIDENTS}_summary_cap"), INCIDENTS, type_="check")
    op.drop_column(INCIDENTS, "summary")
    op.drop_column("calls", "ended_before_agent")
    for table in (SWITCHES, HISTORY):
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.drop_index("ix_agent_voice_switches_incident", table_name=SWITCHES)
    op.drop_index("ix_agent_voice_switches_agent_recent", table_name=SWITCHES)
    op.drop_index("uq_agent_voice_switches_active", table_name=SWITCHES)
    op.drop_table(SWITCHES)
    op.drop_index("ix_agent_voice_history_agent_good", table_name=HISTORY)
    op.drop_table(HISTORY)
