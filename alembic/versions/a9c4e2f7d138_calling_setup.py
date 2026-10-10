"""calling setup: the caller-lookup secret, a client's lead calling plan, held leads

Revision ID: a9c4e2f7d138
Revises: a8d3f6c1e924
Create Date: 2026-10-10 21:00:00.000000

Three things, one lane (D-716):

1. `engine_agent_routes.call_start_secret_*`. ThinnestAI asks our per-agent caller-lookup
   endpoint who is ringing before the agent answers, signed with a secret IT mints and shows
   once, on the response to the request that sets the address (`voice.callStartSecret`,
   docs.thinnest.ai api-reference/agents/update-agent, read 10 Oct 2026). The lookup request
   carries no tenant, so the secret sits on the route row for `action_secret_*`'s reason
   (e8a4c2f17b39), sealed under `PLATFORM_KEK`, five columns all set or all NULL.

2. `lead_call_policies`: one row per client (founder decision 10, 10 Oct 2026): which agent
   calls new leads, how long to wait, the client's calling hours, days and holidays inside
   the platform window, what happens to a lead that arrives after hours, retries when nobody
   answers, and the answering-machine switch. No row means the defaults, which are exactly
   the behaviour before this table existed.

3. `lead_call_holds`: leads that arrived after hours on a "hold for me" plan, waiting for
   the client to release them. No phone number is copied here; the lead row holds it.

Both new tables are tenant data and carry the FORCEd `tenant_isolation` policy (hard rule 1).
The downgrade drops the tables and the secret columns: the next publish after a re-upgrade
finds no secret held and rotates the vendor's (`reliability/engine_lookups.py`).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9c4e2f7d138"
down_revision: str | None = "a8d3f6c1e924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTES = "engine_agent_routes"
_SEALED = (
    "call_start_secret_ciphertext",
    "call_start_secret_nonce",
    "call_start_secret_dek_wrapped",
    "call_start_secret_dek_nonce",
    "call_start_secret_kek_version",
)
_WHOLE = "ck_engine_agent_routes_call_start_secret_sealed_whole"

POLICIES = "lead_call_policies"
HOLDS = "lead_call_holds"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _isolate(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _SEALED[:-1]:
        op.add_column(_ROUTES, sa.Column(column, sa.LargeBinary(), nullable=True))
    op.add_column(_ROUTES, sa.Column(_SEALED[-1], sa.Integer(), nullable=True))
    all_null = " AND ".join(f"{c} IS NULL" for c in _SEALED)
    none_null = " AND ".join(f"{c} IS NOT NULL" for c in _SEALED)
    op.create_check_constraint(op.f(_WHOLE), _ROUTES, f"({all_null}) OR ({none_null})")

    op.create_table(
        POLICIES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("calling_agent_id", sa.UUID(), nullable=True),
        sa.Column("wait_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hours_start", sa.Time(), server_default="09:00", nullable=False),
        sa.Column("hours_end", sa.Time(), server_default="21:00", nullable=False),
        sa.Column(
            "days",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("ARRAY['mon','tue','wed','thu','fri','sat','sun']"),
            nullable=False,
        ),
        sa.Column(
            "holidays",
            postgresql.ARRAY(sa.Date()),
            server_default=sa.text("'{}'::date[]"),
            nullable=False,
        ),
        sa.Column("after_hours", sa.Text(), server_default="next_open", nullable=False),
        sa.Column("retry_attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("retry_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("detect_machines", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("wait_seconds BETWEEN 0 AND 3600", name=op.f(f"ck_{POLICIES}_wait")),
        # Inside the platform window (09:00-21:00 IST, `calevate_shared.calling_window`): a
        # client may narrow it, never widen it.
        sa.CheckConstraint(
            "hours_start >= '09:00' AND hours_end <= '21:00' AND hours_start < hours_end",
            name=op.f(f"ck_{POLICIES}_hours"),
        ),
        sa.CheckConstraint(
            "cardinality(days) BETWEEN 1 AND 7 AND days <@ "
            "ARRAY['mon','tue','wed','thu','fri','sat','sun']",
            name=op.f(f"ck_{POLICIES}_days"),
        ),
        sa.CheckConstraint("cardinality(holidays) <= 60", name=op.f(f"ck_{POLICIES}_holidays")),
        sa.CheckConstraint(
            "after_hours IN ('next_open', 'open_plus_3h', 'next_day', 'hold')",
            name=op.f(f"ck_{POLICIES}_after_hours"),
        ),
        sa.CheckConstraint(
            "retry_attempts BETWEEN 0 AND 3", name=op.f(f"ck_{POLICIES}_retry_attempts")
        ),
        sa.CheckConstraint(
            "retry_interval_minutes BETWEEN 10 AND 1440",
            name=op.f(f"ck_{POLICIES}_retry_interval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{POLICIES}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{POLICIES}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["calling_agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{POLICIES}_calling_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_lead_call_policies_tenant"),
    )
    _isolate(POLICIES)

    op.create_table(
        HOLDS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="held", nullable=False),
        sa.Column(
            "held_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_by", sa.UUID(), nullable=True),
        sa.Column("callback_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('held', 'released', 'dropped')", name=op.f(f"ck_{HOLDS}_status")
        ),
        sa.CheckConstraint(
            "(status = 'held') = (settled_at IS NULL)", name=op.f(f"ck_{HOLDS}_settled")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{HOLDS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{HOLDS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f(f"fk_{HOLDS}_lead_id_leads"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{HOLDS}_agent_id_agents"),
            ondelete="CASCADE",
        ),
    )
    # One open hold per lead: a lead that arrives twice overnight is held once.
    op.create_index(
        "uq_lead_call_holds_open",
        HOLDS,
        ["tenant_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'held'"),
    )
    op.create_index(
        "ix_lead_call_holds_queue",
        HOLDS,
        ["tenant_id", "held_at"],
        postgresql_where=sa.text("status = 'held'"),
    )
    _isolate(HOLDS)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {HOLDS}")
    op.drop_index("ix_lead_call_holds_queue", table_name=HOLDS)
    op.drop_index("uq_lead_call_holds_open", table_name=HOLDS)
    op.drop_table(HOLDS)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {POLICIES}")
    op.drop_table(POLICIES)
    op.drop_constraint(op.f(_WHOLE), _ROUTES, type_="check")
    for column in reversed(_SEALED):
        op.drop_column(_ROUTES, column)
