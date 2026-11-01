"""Mistakes on real calls (D-949): what the agent got wrong, per call, and when we fixed it

Revision ID: e7b3c9d1a4f2
Revises: d946a1b2c3e4
Create Date: 2026-11-01 18:00:00.000000

The turn checks that judge practice conversations (`agents/turn_checks`) now read every
finished real call too. Three objects:

* `call_mistakes`: one row per (call, kind) the checks found. Tenant data derived from a
  client's own transcript, so FORCEd RLS in this migration (hard rule 1). It holds a kind
  and a turn index, never words (hard rule 6). NOT append-only: a re-driven call replaces
  its own rows. `call_id` CASCADEs, like `knowledge_gap_occurrences`: an index into a
  transcript goes when an erasure removes the call.
* `platform_mistake_fixes`: an operator's statement that a kind is fixed in the platform,
  one row per statement, the latest per kind in force. Platform state with no tenant_id
  (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`); every row is audited.
* `call_mistake_scan(since)`: the admin roll-up across clients, entering each client under
  its own `app.tenant_id` the way `call_reply_scan` (d3f8b2c6a417) does, never a
  `BYPASSRLS` owner. Kinds, ids and times only.

REVERSIBILITY. `downgrade()` drops all three. The mistakes are re-derivable from the
transcripts; the fixes are an operator's notes, also in `audit_log`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3c9d1a4f2"
down_revision: str | None = "d946a1b2c3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MISTAKES = "call_mistakes"
FIXES = "platform_mistake_fixes"
FUNCTION = "call_mistake_scan"
POLICY = "tenant_isolation"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    agent_id uuid,
    call_id uuid,
    kind text,
    call_started_at timestamptz
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
            SELECT t, m.agent_id, m.call_id, m.kind, m.call_started_at
              FROM {MISTAKES} m
             WHERE m.call_started_at >= since;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        MISTAKES,
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
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "call_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("turn_idx", sa.Integer(), nullable=False),
        sa.Column("call_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("tenant_id", "call_id", "kind", name="uq_call_mistakes_call_kind"),
        sa.CheckConstraint("turn_idx >= 0", name="turn_idx_non_negative"),
    )
    op.create_index(
        "ix_call_mistakes_agent_started",
        MISTAKES,
        ["tenant_id", "agent_id", sa.text("call_started_at DESC")],
    )
    op.create_index("ix_call_mistakes_call", MISTAKES, ["call_id"])
    op.create_index("ix_call_mistakes_started", MISTAKES, [sa.text("call_started_at DESC")])
    op.execute(f"ALTER TABLE {MISTAKES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {MISTAKES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {MISTAKES} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    op.create_table(
        FIXES,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "fixed_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "fixed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("length(btrim(note)) > 0", name="note_present"),
    )
    op.create_index("ix_platform_mistake_fixes_kind_latest", FIXES, ["kind", sa.text("fixed_at DESC")])

    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.drop_index("ix_platform_mistake_fixes_kind_latest", table_name=FIXES)
    op.drop_table(FIXES)
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {MISTAKES}")
    op.drop_index("ix_call_mistakes_started", table_name=MISTAKES)
    op.drop_index("ix_call_mistakes_call", table_name=MISTAKES)
    op.drop_index("ix_call_mistakes_agent_started", table_name=MISTAKES)
    op.drop_table(MISTAKES)
