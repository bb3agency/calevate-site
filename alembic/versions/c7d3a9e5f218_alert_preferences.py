"""alerts you can shape: per-person preferences, held and folded alerts, morning summary (D-1048)

Revision ID: c7d3a9e5f218
Revises: e8b4d1f6a2c9
Create Date: 2026-11-28

1. `notification_preferences` — one row per (account, person): which alert kinds reach which
   channel (`off` lists the `kind:channel` cells the person switched off, so a kind added
   later starts on), quiet hours in IST and the daily email cap. Tenant data: FORCEd
   `tenant_isolation`.
2. `notification_deliveries` — what the alert gate decided for one alert on one channel: sent
   now, held for quiet hours, folded past the daily cap, or released in the digest that
   followed; and the bell items a job posts (`campaign_finished`). Keyed
   `(tenant_id, channel, dedupe_key)` so a retried job finds its own decision. Titles are
   our own sentences and `ref` holds ids only (hard rule 6). Tenant data: FORCEd
   `tenant_isolation`.
3. `organizations.owner_digest_slot` — `evening` (20:58 IST, the day so far) or `morning`
   (08:00 IST, the day before). Every existing account keeps `evening`.

No DML in either direction. Reversible: `downgrade()` drops the column, both policies and
both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d3a9e5f218"
down_revision: str | Sequence[str] | None = "e8b4d1f6a2c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNELS = "'bell', 'email', 'whatsapp'"
_STATES = "'sent', 'held', 'folded', 'released'"
_SLOT_CHECK = "ck_organizations_owner_digest_slot"


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


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_tenant_id_organizations"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "off",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("quiet_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("quiet_start_hour", sa.SmallInteger(), server_default="21", nullable=False),
        sa.Column("quiet_end_hour", sa.SmallInteger(), server_default="8", nullable=False),
        sa.Column("daily_cap", sa.SmallInteger(), server_default="12", nullable=False),
        *_timestamps(),
        _tenant_fk("notification_preferences"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint(
            "tenant_id", "user_id", name=op.f("uq_notification_preferences_tenant_id_user_id")
        ),
        sa.CheckConstraint(
            "quiet_start_hour BETWEEN 0 AND 23 AND quiet_end_hour BETWEEN 0 AND 23 "
            "AND quiet_start_hour <> quiet_end_hour",
            name=op.f("ck_notification_preferences_quiet_hours"),
        ),
        sa.CheckConstraint(
            "daily_cap BETWEEN 1 AND 100", name=op.f("ck_notification_preferences_daily_cap")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(off) = 'array'", name=op.f("ck_notification_preferences_off_array")
        ),
    )
    op.create_index(
        op.f("ix_notification_preferences_tenant_id"),
        "notification_preferences",
        ["tenant_id"],
        unique=False,
    )
    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_preferences FORCE ROW LEVEL SECURITY")
    op.execute(_policy("notification_preferences"))

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("href", sa.Text(), nullable=True),
        sa.Column("ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _tenant_fk("notification_deliveries"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint(
            "tenant_id",
            "channel",
            "dedupe_key",
            name=op.f("uq_notification_deliveries_tenant_id_channel_dedupe_key"),
        ),
        sa.CheckConstraint(
            f"channel IN ({_CHANNELS})", name=op.f("ck_notification_deliveries_channel")
        ),
        sa.CheckConstraint(f"state IN ({_STATES})", name=op.f("ck_notification_deliveries_state")),
        sa.CheckConstraint(
            "state NOT IN ('held', 'folded') OR due_at IS NOT NULL",
            name=op.f("ck_notification_deliveries_waiting_has_due"),
        ),
    )
    op.create_index(
        op.f("ix_notification_deliveries_tenant_id"),
        "notification_deliveries",
        ["tenant_id"],
        unique=False,
    )
    # The daily cap counts one account's sends on one channel since the IST midnight.
    op.create_index(
        "ix_notification_deliveries_sent_today",
        "notification_deliveries",
        ["tenant_id", "channel", "created_at"],
    )
    # The release sweep reads every account's waiting rows that fell due.
    op.create_index(
        "ix_notification_deliveries_waiting",
        "notification_deliveries",
        ["due_at"],
        postgresql_where=sa.text("state IN ('held', 'folded')"),
    )
    op.execute("ALTER TABLE notification_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_deliveries FORCE ROW LEVEL SECURITY")
    op.execute(_policy("notification_deliveries"))

    op.add_column(
        "organizations",
        sa.Column("owner_digest_slot", sa.Text(), server_default="evening", nullable=False),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_SLOT_CHECK} "
        "CHECK (owner_digest_slot IN ('evening', 'morning')) NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_SLOT_CHECK}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_SLOT_CHECK}")
    op.drop_column("organizations", "owner_digest_slot")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_deliveries")
    op.drop_index("ix_notification_deliveries_waiting", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_sent_today", table_name="notification_deliveries")
    op.drop_index(
        op.f("ix_notification_deliveries_tenant_id"), table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_preferences")
    op.drop_index(
        op.f("ix_notification_preferences_tenant_id"), table_name="notification_preferences"
    )
    op.drop_table("notification_preferences")
