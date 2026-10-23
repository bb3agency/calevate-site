"""The announcement bar's two tables (D-869, migration b9e4d2a7c513).

`platform_announcements` is the operator's: one row per message, no tenant_id, read by a
client only through `service.active_for`, which applies the audience. It is registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` beside `platform_maintenance_windows`, for the same
reason. `announcement_dismissals` is the client's: which messages this account has put
away, FORCE-RLS'd on `tenant_id`.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

Tone = Literal["info", "success", "warning", "critical"]
TONES: tuple[Tone, ...] = ("info", "success", "warning", "critical")
#: `trial` is an account that has never paid (`organizations.first_paid_at IS NULL`, D-697);
#: `paid` is one that has; `tenant` is one named account.
Audience = Literal["all", "trial", "paid", "tenant"]
AUDIENCES: tuple[Audience, ...] = ("all", "trial", "paid", "tenant")

#: What fits in one line of the bar on a phone without becoming a paragraph.
MAX_MESSAGE_CHARS = 280


class PlatformAnnouncement(PKMixin, TimestampMixin, Base):
    __tablename__ = "platform_announcements"
    __table_args__ = (
        CheckConstraint(f"tone IN {TONES!r}", name="tone"),
        CheckConstraint(f"audience IN {AUDIENCES!r}", name="audience"),
        CheckConstraint("(audience = 'tenant') = (target_tenant_id IS NOT NULL)", name="target"),
        CheckConstraint(
            f"char_length(message) BETWEEN 1 AND {MAX_MESSAGE_CHARS}", name="message_length"
        ),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window"),
        CheckConstraint("link_label IS NULL OR link_url IS NOT NULL", name="label_needs_link"),
        Index(
            "ix_platform_announcements_open",
            "starts_at",
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text)
    link_label: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    target_tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )


class AnnouncementDismissal(PKMixin, TimestampMixin, Base):
    __tablename__ = "announcement_dismissals"
    __table_args__ = (UniqueConstraint("tenant_id", "announcement_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    announcement_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_announcements.id", ondelete="CASCADE"), nullable=False
    )
