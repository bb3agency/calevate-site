"""The healer fixes real-call mistakes in the agent's own script (D-985)

Revision ID: c4e8a2f6d1b9
Revises: b7d2e9f4a1c6
Create Date: 2026-11-12 23:30:00.000000

* `agent_mistake_fixes`: one row per automatic fix of one mistake kind in one agent's script:
  its state (fixing, live, fixed, rolled_back, needs_person), what ended it, the script
  versions before and after, the attempts, and the healer incident doing it. Tenant data,
  so FORCEd RLS in this migration (hard rule 1). Ids, kinds, version numbers and times only.
  At most one fix per agent and kind is in progress (`uq_agent_mistake_fixes_active`).
* `heal_client_incidents.kind` gains `script_fixed` (the owner's notice that a fix is live)
  and `script_fix_waiting` (a fix waits on the client's AI allowance).
* `agent_mistake_fix_scan(since)`: the operator's board across clients, entering each client
  under its own `app.tenant_id` as `call_mistake_scan` (e7b3c9d1a4f2) does.

REVERSIBILITY. `downgrade()` drops the function and the table, and turns the two new client
notice kinds back into `agent_unwell` before restoring the narrower CHECK; the fixes
themselves are also recorded in `heal_actions` and the agents' prompt version history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c4e8a2f6d1b9"
down_revision: str | None = "b7d2e9f4a1c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXES = "agent_mistake_fixes"
CLIENT = "heal_client_incidents"
FUNCTION = "agent_mistake_fix_scan"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
_STATES = ("fixing", "live", "fixed", "rolled_back", "needs_person")
_ENDINGS = (
    "came_back",
    "worse",
    "owner",
    "no_script_cause",
    "waited_too_long",
    "attempts_spent",
    "script_changed",
    "agent_gone",
)
_OLD_KINDS = ("agent_unwell", "line_protected", "platform_outage")
_NEW_KINDS = (*_OLD_KINDS, "script_fixed", "script_fix_waiting")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    fix_id uuid,
    agent_id uuid,
    agent_name text,
    kind text,
    state text,
    ended_because text,
    attempts integer,
    version_before integer,
    version_after integer,
    live_at timestamptz,
    settled_at timestamptz,
    created_at timestamptz
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, f.id, f.agent_id, a.name::text, f.kind, f.state, f.ended_because,
                   f.attempts::integer, f.version_before, f.version_after, f.live_at,
                   f.settled_at, f.created_at
              FROM {FIXES} f JOIN agents a ON a.id = f.agent_id
             WHERE f.created_at >= since OR f.state IN ('fixing', 'live');
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        FIXES,
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
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="fixing"),
        sa.Column("ended_because", sa.Text(), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("waits", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "incident_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("heal_incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("proposal_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("version_before", sa.Integer(), nullable=True),
        sa.Column("version_base", sa.Integer(), nullable=True),
        sa.Column("version_after", sa.Integer(), nullable=True),
        sa.Column("live_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "undone_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(_in("state", _STATES), name=op.f(f"ck_{FIXES}_state_enum")),
        sa.CheckConstraint(
            f"ended_because IS NULL OR {_in('ended_because', _ENDINGS)}",
            name=op.f(f"ck_{FIXES}_ended_because_enum"),
        ),
        sa.CheckConstraint(
            "(state IN ('fixed', 'rolled_back', 'needs_person')) = (settled_at IS NOT NULL)",
            name=op.f(f"ck_{FIXES}_settled_iff"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND waits >= 0", name=op.f(f"ck_{FIXES}_counts_nonnegative")
        ),
    )
    op.create_index(
        "uq_agent_mistake_fixes_active",
        FIXES,
        ["agent_id", "kind"],
        unique=True,
        postgresql_where=sa.text("state IN ('fixing', 'live')"),
    )
    op.create_index(
        "ix_agent_mistake_fixes_agent_kind",
        FIXES,
        ["tenant_id", "agent_id", "kind", sa.text("created_at DESC")],
    )
    op.create_index("ix_agent_mistake_fixes_incident", FIXES, ["incident_id"])
    op.execute(f"ALTER TABLE {FIXES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {FIXES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {FIXES} FOR ALL USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _NEW_KINDS))
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.execute(f"ALTER TABLE {CLIENT} NO FORCE ROW LEVEL SECURITY")
    execute_data_statement(
        sa.text(
            f"UPDATE {CLIENT} SET kind = 'agent_unwell', updated_at = now() "
            "WHERE kind IN ('script_fixed', 'script_fix_waiting')"
        ),
        note="Turned the script-fix notices back into the generic agent notice.",
    )
    op.execute(f"ALTER TABLE {CLIENT} FORCE ROW LEVEL SECURITY")
    op.drop_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, type_="check")
    op.create_check_constraint(op.f(f"ck_{CLIENT}_kind_enum"), CLIENT, _in("kind", _OLD_KINDS))
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {FIXES}")
    op.drop_index("ix_agent_mistake_fixes_incident", table_name=FIXES)
    op.drop_index("ix_agent_mistake_fixes_agent_kind", table_name=FIXES)
    op.drop_index("uq_agent_mistake_fixes_active", table_name=FIXES)
    op.drop_table(FIXES)
