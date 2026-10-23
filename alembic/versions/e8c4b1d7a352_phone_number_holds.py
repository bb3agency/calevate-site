"""a stopped client's rented number is held, then released before the next renewal (D-860)

Founder, 23 Oct 2026: when a client stops (its account is closed, or its wallet has been
below zero for the console's `number_hold_after_negative_days`), each number it rents
through us is held: nobody answers it, nobody is charged rent for it, and it is released
before the voice platform's next monthly renewal unless the client tops up or the account
is reopened first.

`phone_number_holds`: one row per hold, at most one open per number
(`uq_phone_number_holds_open`, the conflict target of the hold's insert). `release_at` is
NULL until the hold job has read the platform's rent day and set it. The three
`*_notice_at` stamps are when each email was queued.

RLS: `tenant_id` and the FORCEd `tenant_isolation` policy (hard rule 1); the cross-tenant
zero-rows proof is `tests/number_holds_test.py`. The rows hold ids, instants and our codes,
no personal data, so an account's erasure leaves them, as it leaves `phone_numbers`.

Downgrade drops the table.

Revision ID: e8c4b1d7a352
Revises: d6f1a8c3e925
Create Date: 2026-10-23 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8c4b1d7a352"
down_revision: str | None = "d6f1a8c3e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOLDS = "phone_number_holds"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `agents/models.NUMBER_HOLD_*`, spelled here because a migration is the schema on the day
#: it ran.
_REASONS = ("account_closed", "wallet_negative")
_ENDS = ("resumed", "released")
_ANCHORS = ("vendor", "recorded")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        HOLDS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("number_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "held_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchor_source", sa.Text(), nullable=True),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"reason IN {_REASONS!r}", name=op.f(f"ck_{HOLDS}_reason_enum")),
        sa.CheckConstraint(
            f"end_reason IS NULL OR end_reason IN {_ENDS!r}",
            name=op.f(f"ck_{HOLDS}_end_reason_enum"),
        ),
        sa.CheckConstraint(
            f"anchor_source IS NULL OR anchor_source IN {_ANCHORS!r}",
            name=op.f(f"ck_{HOLDS}_anchor_source_enum"),
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL) = (end_reason IS NULL)", name=op.f(f"ck_{HOLDS}_ended_with_reason")
        ),
        sa.CheckConstraint(
            "release_at IS NULL OR release_at >= held_at",
            name=op.f(f"ck_{HOLDS}_release_after_hold"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{HOLDS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{HOLDS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["phone_numbers.id"],
            name=op.f(f"fk_{HOLDS}_number_id_phone_numbers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f(f"fk_{HOLDS}_agent_id_agents"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "uq_phone_number_holds_open",
        HOLDS,
        ["number_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_phone_number_holds_tenant_open",
        HOLDS,
        ["tenant_id"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.execute(f"ALTER TABLE {HOLDS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {HOLDS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {HOLDS} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {HOLDS}")
    op.drop_index("ix_phone_number_holds_tenant_open", table_name=HOLDS)
    op.drop_index("uq_phone_number_holds_open", table_name=HOLDS)
    op.drop_table(HOLDS)
