"""Announcements, notification read marks and a call's follow-up state (D-869)

Revision ID: b9e4d2a7c513
Revises: f2b7c4e9d815
Create Date: 2026-10-24 12:00:00.000000

Four objects for the UI wave's backend lane (founder decision f7d9f716, 24 Oct 2026):

1. `platform_announcements` — the bar the admin console composes for every client, trial
   clients, paid clients or one client. Platform-scoped like `platform_maintenance_windows`
   (no tenant_id; registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`). The one-client
   audience names its client in `target_tenant_id`, which is a TARGET, not an owner: the
   row is the operator's, and a tenant session reads it only through
   `announcements/service.active_for`, which filters on audience.
2. `announcement_dismissals` — one row per (client, announcement) once anyone in that
   account dismisses it. Tenant data: FORCEd `tenant_isolation`.
3. `notification_reads` — how far each person has read the bell's feed: one row per
   (client, person), the newest instant they have seen. Tenant data: FORCEd
   `tenant_isolation`.
4. `calls.follow_up_state` / `follow_up_set_at` / `follow_up_set_by` — what a person marked
   on a call ("resolved" or "needs you") from the phone swipe or the desktop menu. Separate
   from `outcome_tag`, which the pipeline derives and rewrites; a person's mark must not be
   overwritten by a re-run of the pipeline.

No DML in either direction, so no NO FORCE / FORCE bracket is needed. Reversible:
`downgrade()` drops the three columns, both policies and the three tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e4d2a7c513"
down_revision: str | None = "f2b7c4e9d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TONES = "'info', 'success', 'warning', 'critical'"
_AUDIENCES = "'all', 'trial', 'paid', 'tenant'"
_FOLLOW_UP_STATES = "'resolved', 'needs_you'"


def _policy(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        # Client-facing, verbatim. Named `message`, not `text`, because the column holds an
        # operator's sentence and never a person's data.
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("link_label", sa.Text(), nullable=True),
        sa.Column("tone", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("target_tenant_id", sa.UUID(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        # Set by "End now"; an ended row is history and never shown again.
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["target_tenant_id"],
            ["organizations.id"],
            name=op.f("fk_platform_announcements_target_tenant_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_announcements_created_by_admin_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_announcements_updated_by_admin_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_announcements")),
        sa.CheckConstraint(f"tone IN ({_TONES})", name=op.f("ck_platform_announcements_tone")),
        sa.CheckConstraint(
            f"audience IN ({_AUDIENCES})", name=op.f("ck_platform_announcements_audience")
        ),
        # The one-client audience names its client, and no other audience does.
        sa.CheckConstraint(
            "(audience = 'tenant') = (target_tenant_id IS NOT NULL)",
            name=op.f("ck_platform_announcements_target"),
        ),
        sa.CheckConstraint(
            "char_length(message) BETWEEN 1 AND 280",
            name=op.f("ck_platform_announcements_message_length"),
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name=op.f("ck_platform_announcements_window"),
        ),
        # A label without a link has nothing to open.
        sa.CheckConstraint(
            "link_label IS NULL OR link_url IS NOT NULL",
            name=op.f("ck_platform_announcements_label_needs_link"),
        ),
    )
    # What the client read asks: the rows not ended, ordered by start.
    op.create_index(
        "ix_platform_announcements_open",
        "platform_announcements",
        ["starts_at"],
        unique=False,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "announcement_dismissals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("announcement_id", sa.UUID(), nullable=False),
        # No "dismissed by" column: who pressed it is the `announcement.dismissed` audit row.
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_announcement_dismissals_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["platform_announcements.id"],
            name=op.f("fk_announcement_dismissals_announcement_id_platform_announcements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_announcement_dismissals")),
        sa.UniqueConstraint(
            "tenant_id",
            "announcement_id",
            name=op.f("uq_announcement_dismissals_tenant_id_announcement_id"),
        ),
    )
    op.create_index(
        op.f("ix_announcement_dismissals_tenant_id"),
        "announcement_dismissals",
        ["tenant_id"],
        unique=False,
    )
    op.execute("ALTER TABLE announcement_dismissals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE announcement_dismissals FORCE ROW LEVEL SECURITY")
    op.execute(_policy("announcement_dismissals"))

    op.create_table(
        "notification_reads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("seen_through", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_notification_reads_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_reads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_reads")),
        sa.UniqueConstraint(
            "tenant_id", "user_id", name=op.f("uq_notification_reads_tenant_id_user_id")
        ),
    )
    op.create_index(
        op.f("ix_notification_reads_tenant_id"), "notification_reads", ["tenant_id"], unique=False
    )
    op.execute("ALTER TABLE notification_reads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_reads FORCE ROW LEVEL SECURITY")
    op.execute(_policy("notification_reads"))

    op.add_column("calls", sa.Column("follow_up_state", sa.Text(), nullable=True))
    op.add_column(
        "calls", sa.Column("follow_up_set_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("calls", sa.Column("follow_up_set_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_calls_follow_up_set_by_users"),
        "calls",
        "users",
        ["follow_up_set_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_calls_follow_up_state"),
        "calls",
        f"follow_up_state IS NULL OR follow_up_state IN ({_FOLLOW_UP_STATES})",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_calls_follow_up_state"), "calls", type_="check")
    op.drop_constraint(op.f("fk_calls_follow_up_set_by_users"), "calls", type_="foreignkey")
    op.drop_column("calls", "follow_up_set_by")
    op.drop_column("calls", "follow_up_set_at")
    op.drop_column("calls", "follow_up_state")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_reads")
    op.drop_index(op.f("ix_notification_reads_tenant_id"), table_name="notification_reads")
    op.drop_table("notification_reads")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON announcement_dismissals")
    op.drop_index(op.f("ix_announcement_dismissals_tenant_id"), table_name="announcement_dismissals")
    op.drop_table("announcement_dismissals")

    op.drop_index("ix_platform_announcements_open", table_name="platform_announcements")
    op.drop_table("platform_announcements")
