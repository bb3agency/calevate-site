"""platform_maintenance_windows, and the campaign column that makes a resume possible

Revision ID: e5c81d09b74a
Revises: b2f74a19d3c8
Create Date: 2026-09-05

MAINTENANCE MODE (D-544). Two objects, and they ship in one revision because neither is
useful without the other: the window is the state machine, and
`campaigns.paused_by_maintenance_id` is what lets its END put back exactly the campaigns
its START stopped.

--------------------------------------------------------------------------------
1. `platform_maintenance_windows`
--------------------------------------------------------------------------------
PLATFORM-SCOPED, so it carries no `tenant_id` and gets no `tenant_isolation` policy — the
same shape as `platform_state`, `platform_settings` and the rest of the `platform_` family
(PLATFORM-CONFIG §5). Hard rule 1 is satisfied the way it is satisfied for every one of
those: the table is registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with the reason
written out, and `scripts/check_rls_coverage.py` rule 7(a) FAILS CI on any `platform_*`
table that is not, so this cannot be quietly forgotten. It holds no tenant data at all —
an operator's sentence, four timestamps and a state word.

`ux_platform_maintenance_windows_open` is partial-unique on a constant expression over the
three OPEN states, which makes "at most one live window on the platform" a database fact
rather than a reader's `if`. Two operators scheduling at the same instant would otherwise
both read "none open" and both insert, and the tick would then advance whichever it saw
first while the other sat scheduled for ever. A UNIQUE index on `(true)` filtered by state
is the standard shape for a singleton row and it costs one entry.

`ix_platform_maintenance_windows_recent` serves the console's history list, which is the
only unbounded read on this table.

--------------------------------------------------------------------------------
2. `campaigns.paused_by_maintenance_id`
--------------------------------------------------------------------------------
Nullable, FK to the window with `ON DELETE SET NULL`, and a partial index on it because
the resume sweep's whole query is `WHERE paused_by_maintenance_id = :id`. `campaigns` is
tenant-scoped and already FORCE-RLS'd; adding a column changes none of that, and the
column carries no personal data (a uuid of ours).

ADDING A NULLABLE COLUMN WITH NO DEFAULT IS A CATALOGUE-ONLY CHANGE on PostgreSQL 11+ —
no table rewrite — so the ACCESS EXCLUSIVE lock is held for microseconds. It is still
taken under `lock_timeout` because `campaigns` is read by the dispatch tick every thirty
seconds and a lock queue behind a long read would stall dialling, not just this migration.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------
Drops the column and the table. Hard rule 8's two-step deprecation is about a column code
has STOPPED writing while rows still depend on it; this is the reverse direction — the
revision that creates an object may drop it, and pre-migration code runs correctly against
the post-downgrade schema because pre-migration code knows about neither.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c81d09b74a"
down_revision: str | None = "b2f74a19d3c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES = "('scheduled', 'draining', 'active', 'completed', 'cancelled')"
OPEN_STATES = "('scheduled', 'draining', 'active')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "platform_maintenance_windows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), server_default="scheduled", nullable=False),
        sa.Column("max_drain_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("draining_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drain_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forced", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "stragglers", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "in_flight", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("probed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_load_shed_mode", sa.Text(), nullable=True),
        sa.Column("advance_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amended_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"state IN {STATES}", name=op.f("ck_platform_maintenance_windows_state_enum")
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name=op.f("ck_platform_maintenance_windows_ends_after_start"),
        ),
        sa.CheckConstraint(
            "max_drain_minutes BETWEEN 1 AND 240",
            name=op.f("ck_platform_maintenance_windows_max_drain_minutes_range"),
        ),
        sa.CheckConstraint(
            "NOT forced OR activated_at IS NOT NULL",
            name=op.f("ck_platform_maintenance_windows_forced_implies_activated"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_maintenance_windows_created_by_admin_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_maintenance_windows")),
    )
    # AT MOST ONE OPEN WINDOW, as a database fact. Expression index, so autogenerate
    # cannot diff it and THIS revision is the source of truth for its existence.
    op.execute(
        "CREATE UNIQUE INDEX ux_platform_maintenance_windows_open "
        "ON platform_maintenance_windows ((true)) "
        f"WHERE state IN {OPEN_STATES}"
    )
    op.execute(
        "CREATE INDEX ix_platform_maintenance_windows_recent "
        "ON platform_maintenance_windows (starts_at DESC, id DESC)"
    )

    op.add_column(
        "campaigns", sa.Column("paused_by_maintenance_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_campaigns_paused_by_maintenance_id_platform_maintenance_windows"),
        "campaigns",
        "platform_maintenance_windows",
        ["paused_by_maintenance_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_campaigns_paused_by_maintenance",
        "campaigns",
        ["paused_by_maintenance_id"],
        postgresql_where=sa.text("paused_by_maintenance_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index(
        "ix_campaigns_paused_by_maintenance",
        table_name="campaigns",
        postgresql_where=sa.text("paused_by_maintenance_id IS NOT NULL"),
    )
    op.drop_constraint(
        op.f("fk_campaigns_paused_by_maintenance_id_platform_maintenance_windows"),
        "campaigns",
        type_="foreignkey",
    )
    op.drop_column("campaigns", "paused_by_maintenance_id")
    op.drop_table("platform_maintenance_windows")
