"""calls.engine_quality and call_engine_signals: how a call went, from the voice platform

Revision ID: a5d1c7e93f28
Revises: f3c9a1d5e7b2
Create Date: 2026-10-11 14:00:00.000000

ThinnestAI reports two new things about a call (docs.thinnest.ai api-reference/webhooks,
"Problems on a live call" and "Call quality", read 11 Oct 2026):

* `quality`, written once when the call ends, on `call.completed`, `call.analysed` and Get
  Call: reply times, silences, interruptions, model errors and backup answers. One object per
  call, so it is a column on `calls`, numbers only. The CHECK makes that a property of the
  data: every value of the object is a number or null.
* `call.problem`, sent while the call is still live, at most once per kind per call; and the
  notices `lead.captured` and `conversation.escalated`, which now name their call. These are
  their own table, keyed by the platform's call id and not by a foreign key to `calls`: a
  problem on an inbound call arrives before we hold a row for that call. Kind and time only.

ISOLATION (hard rule 1), in this migration: `tenant_id`, the DATA-MODEL §1 policy, ENABLE
plus FORCE. The cross-tenant proof is `tests/thinnest_call_signals_test.py`.

LOCKING. `calls` gains a nullable column (no rewrite) and a CHECK added NOT VALID, then
validated (SHARE UPDATE EXCLUSIVE). The new table locks nothing.

DOWNGRADE drops the table, the column, the constraint and the function. It loses only these
readings; the engine's raw document is still archived under the call's prefix (D-126).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a5d1c7e93f28"
down_revision: str | None = "f3c9a1d5e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "conversation_escalated",
    "lead_captured",
    "no_answer_from_model",
    "own_key_failed",
    "slow_reply",
    "voice_failed",
)

_POLICY = (
    "CREATE POLICY tenant_isolation ON call_engine_signals USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# An object whose values are numbers or null. A function because a CHECK cannot hold the
# subquery over `jsonb_each`.
_QUALITY_FUNCTION = """
CREATE OR REPLACE FUNCTION call_quality_is_numeric(quality jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT jsonb_typeof(quality) = 'object' AND NOT EXISTS (
    SELECT 1 FROM jsonb_each(quality) AS entry(key, value)
    WHERE jsonb_typeof(entry.value) NOT IN ('number', 'null')
  )
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_QUALITY_FUNCTION)
    op.add_column(
        "calls",
        sa.Column("engine_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT ck_calls_engine_quality_is_numbers CHECK "
        "(engine_quality IS NULL OR call_quality_is_numeric(engine_quality)) NOT VALID"
    )
    op.execute("ALTER TABLE calls VALIDATE CONSTRAINT ck_calls_engine_quality_is_numbers")

    op.create_table(
        "call_engine_signals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("engine_call_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"kind IN {_KINDS!r}", name=op.f("ck_call_engine_signals_kind_enum")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_call_engine_signals_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_call_engine_signals_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_engine_signals")),
        sa.UniqueConstraint(
            "tenant_id",
            "engine_call_id",
            "kind",
            name=op.f("uq_call_engine_signals_tenant_id"),
        ),
    )
    op.create_index(
        op.f("ix_call_engine_signals_tenant_id"), "call_engine_signals", ["tenant_id"], unique=False
    )
    op.execute("ALTER TABLE call_engine_signals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_engine_signals FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON call_engine_signals")
    op.drop_index(op.f("ix_call_engine_signals_tenant_id"), table_name="call_engine_signals")
    op.drop_table("call_engine_signals")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS ck_calls_engine_quality_is_numbers")
    op.drop_column("calls", "engine_quality")
    op.execute("DROP FUNCTION IF EXISTS call_quality_is_numeric(jsonb)")
