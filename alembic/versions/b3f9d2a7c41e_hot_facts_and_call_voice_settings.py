"""known facts per agent, the voice settings each call ran on, and two reply time targets

Revision ID: b3f9d2a7c41e
Revises: f4b8d2a61c39
Create Date: 2026-10-27 12:00:00.000000

D-896 (founder, 27 Oct 2026).

* `agent_hot_facts`: one row per agent holding the facts it knows by heart, chosen from the
  client's live knowledge by what its callers ask (`apps/api/agents/hot_facts.py`). A tenant
  table, so FORCEd `tenant_isolation` in this migration (hard rule 1); the cross-tenant
  zero-rows proof is `tests/hot_facts_test.py`.
* `agents.voice_settings` / `calls.voice_settings`: the call-handling settings an agent was
  last published with, copied onto each call when its row is first written, so the Voice
  response time screen can split reply times by turn detection, filler delay and known
  facts. Closed-set values and numbers only, no text a caller said.
* `call_reply_scan` returns `voice_settings`. A changed return type cannot be `CREATE OR
  REPLACE`d, so the function is dropped and created again in one transaction.
* The stored `reply_time_target_ms` console row is retired: the setting became
  `reply_time_typical_target_ms` and `reply_time_slow_target_ms`, whose defaults are the
  founder's targets (1,600 / 2,200 ms). A saved 500 is not carried over, because it was the
  goal those two replace. Printed when removed.

Reversible: the downgrade drops the table and both columns and restores the earlier function.
The retired row stays gone (it changes no schema; the earlier code falls back to its default).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import execute_data_statement, is_offline

revision: str = "b3f9d2a7c41e"
down_revision: str | None = "f4b8d2a61c39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_hot_facts"
FUNCTION = "call_reply_scan"
RETIRED_KEY = "reply_time_target_ms"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def _scan_sql(*, with_settings: bool) -> str:
    column = ",\n    voice_settings jsonb" if with_settings else ""
    value = ", c.voice_settings" if with_settings else ""
    return f"""
CREATE FUNCTION {FUNCTION}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    call_id uuid,
    agent_id uuid,
    agent_name text,
    started_at timestamptz,
    quality jsonb,
    slow_reply boolean,
    voice_tier text{column}
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
            SELECT t, c.id, c.agent_id, a.name::text, c.started_at, c.engine_quality,
                   EXISTS (SELECT 1 FROM call_engine_signals s
                           WHERE s.engine_call_id = c.engine_call_id AND s.kind = 'slow_reply'),
                   (SELECT max(u.meta ->> 'voice_tier') FROM usage_events u
                     WHERE u.call_id = c.id){value}
              FROM calls c
              LEFT JOIN agents a ON a.id = c.agent_id
             WHERE c.started_at >= since AND c.status = 'completed';
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("budget_chars", sa.Integer(), nullable=False),
        sa.Column("used_chars", sa.Integer(), nullable=False),
        sa.Column("candidates", sa.Integer(), nullable=False),
        sa.Column("calls_read", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "jsonb_typeof(items) = 'array'", name=op.f("ck_agent_hot_facts_items_is_array")
        ),
        sa.CheckConstraint(
            "used_chars >= 0 AND budget_chars >= 0",
            name=op.f("ck_agent_hot_facts_chars_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_agent_hot_facts_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_hot_facts_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_hot_facts")),
        sa.UniqueConstraint("agent_id", name=op.f("uq_agent_hot_facts_agent_id")),
    )
    op.create_index(op.f("ix_agent_hot_facts_tenant_id"), TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    op.add_column(
        "agents",
        sa.Column("voice_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "calls",
        sa.Column("voice_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.execute(_scan_sql(with_settings=True))

    if is_offline():
        execute_data_statement(
            sa.text(f"DELETE FROM platform_settings WHERE key = '{RETIRED_KEY}'"),
            note="Deleted the retired platform_settings row.",
        )
        return
    removed = (
        op.get_bind()
        .execute(
            sa.text(
                "DELETE FROM platform_settings WHERE key = :key "
                "RETURNING value::text, updated_by::text, updated_at::text"
            ),
            {"key": RETIRED_KEY},
        )
        .first()
    )
    if removed is not None:
        print(
            f"retired platform_settings row {RETIRED_KEY}: value={removed[0]} "
            f"updated_by={removed[1]} updated_at={removed[2]}"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(timestamptz)")
    op.execute(_scan_sql(with_settings=False))
    op.drop_column("calls", "voice_settings")
    op.drop_column("agents", "voice_settings")
    op.drop_index(op.f("ix_agent_hot_facts_tenant_id"), table_name=TABLE)
    op.drop_table(TABLE)
