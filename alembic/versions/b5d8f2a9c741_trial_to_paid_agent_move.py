"""a paying client's agents move to its own workspace; the go-live guide; paid test calls (D-859)

Founder, 23 Oct 2026: when a trial client pays, its agents move by themselves into its own
ThinnestAI customer workspace with their state kept, the owner is guided through going live,
and test calls to the owner's phone go on after payment.

1. `agent_workspace_moves`: one row per (agent, target workspace), the move job's outcome for
   that agent (`waiting`, `moved`, `held`, `failed`), the reason code of the last refusal, the
   attempts, and the code an operator was last alarmed with (so an hourly retry does not page
   twice for the same cause). The go-live guide reads it as the move's progress.
2. `go_live_guides`: one row per client, written at the first payment: when the guide was
   owed, and when the owner finished it or put it aside. The sign-in junction and the
   dashboard read it as the guide's marker.
3. `calls.paid_test_call`: a test call a paying account placed to the owner's own phone from
   its own number. A partial index on `(tenant_id, created_at) WHERE paid_test_call` serves
   the daily cap, as `ix_calls_trial_recent` serves the trial's.
4. `organizations.first_paid_via` admits `operator_conversion`: an operator converting an
   invoiced or managed account's trial (`billing/trial_routes.close_trial`) stamps the account
   paid, so `PAID_TENANT_SQL` and everything keyed on it agree with the trial. Accounts an
   operator converted before this revision are backfilled from the trial's end, inside a
   `NO FORCE ROW LEVEL SECURITY` bracket (the owner is subject to the FORCEd policies, so an
   unbracketed UPDATE would see no row).

RLS: both new tables carry `tenant_id` and the FORCEd `tenant_isolation` policy (hard rule 1);
the cross-tenant zero-rows proof is `tests/go_live_test.py`. An account's erasure deletes both
(`workers/retention.execute_tenant_erasure`).

Downgrade drops both tables and the column, clears the backfilled stamps (they were NULL
before) and restores the narrower CHECK.

Revision ID: b5d8f2a9c741
Revises: d6f1a8c3e925
Create Date: 2026-10-23 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5d8f2a9c741"
down_revision: str | None = "d6f1a8c3e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVES = "agent_workspace_moves"
GUIDES = "go_live_guides"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `go_live/models.MOVE_STATES`, spelled here because a migration is the schema on the day it
#: ran.
_MOVE_STATES = ("waiting", "moved", "held", "failed")
_PAID_VIA_BEFORE = ("wallet_topup", "manual_topup", "before_d697")
_PAID_VIA_AFTER = (*_PAID_VIA_BEFORE, "operator_conversion")
_CK_PAID_VIA = "ck_organizations_first_paid_via_enum"

#: Accounts an operator converted before this revision: paid from the trial's end.
_BACKFILL = """
UPDATE organizations o
   SET first_paid_at = t.ended_at, first_paid_via = 'operator_conversion'
  FROM (SELECT DISTINCT ON (tenant_id) tenant_id, status, ended_at
          FROM tenant_trials ORDER BY tenant_id, started_at DESC, id DESC) t
 WHERE t.tenant_id = o.id AND t.status = 'converted' AND t.ended_at IS NOT NULL
   AND o.first_paid_at IS NULL
"""


def _stamps() -> list[sa.Column[object]]:
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


def _paid_via(values: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK_PAID_VIA}")
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CK_PAID_VIA} "
        f"CHECK (first_paid_via IS NULL OR first_paid_via IN ({listed})) NOT VALID"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        MOVES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="waiting", nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alarmed_code", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"status IN {_MOVE_STATES!r}", name=op.f(f"ck_{MOVES}_status_enum")),
        sa.CheckConstraint("attempts >= 0", name=op.f(f"ck_{MOVES}_attempts_not_negative")),
        sa.CheckConstraint(
            "(status = 'moved') = (moved_at IS NOT NULL)", name=op.f(f"ck_{MOVES}_moved_stamped")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{MOVES}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{MOVES}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{MOVES}_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", "workspace_id", name="uq_agent_workspace_moves_agent"),
    )
    op.create_index("ix_agent_workspace_moves_tenant", MOVES, ["tenant_id", "status"])
    _isolate(MOVES)

    op.create_table(
        GUIDES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("owed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{GUIDES}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{GUIDES}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_go_live_guides_tenant"),
    )
    _isolate(GUIDES)

    op.add_column(
        "calls",
        sa.Column("paid_test_call", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_calls_paid_test_recent",
        "calls",
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("paid_test_call"),
    )

    _paid_via(_PAID_VIA_AFTER)
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_trials NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK_PAID_VIA}")
        op.execute(_BACKFILL)
    finally:
        op.execute("ALTER TABLE tenant_trials FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE organizations SET first_paid_at = NULL, first_paid_via = NULL "
            "WHERE first_paid_via = 'operator_conversion'"
        )
        _paid_via(_PAID_VIA_BEFORE)
        op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK_PAID_VIA}")
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.drop_index("ix_calls_paid_test_recent", table_name="calls")
    op.drop_column("calls", "paid_test_call")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {GUIDES}")
    op.drop_table(GUIDES)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {MOVES}")
    op.drop_index("ix_agent_workspace_moves_tenant", table_name=MOVES)
    op.drop_table(MOVES)
