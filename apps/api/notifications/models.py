"""The bell's read marks (D-869, migration b9e4d2a7c513) and what each person wants to be told,
and how (D-1048, migration c7d3a9e5f218).

`notification_reads`: one row per (account, person) holding the newest instant they have seen.
A high-water mark rather than a row per item: most of the feed is assembled from sources that
already exist (the needs-attention queue and the announcements), so "unread" is simply "newer
than the mark".
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, SmallInteger, Text, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin


class NotificationRead(PKMixin, TimestampMixin, Base):
    __tablename__ = "notification_reads"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seen_through: Mapped[datetime] = mapped_column(nullable=False)


class NotificationPreference(PKMixin, TimestampMixin, Base):
    """One person's alert choices: the cells they switched off, quiet hours in IST and the
    daily email cap. The account email and the owner's WhatsApp follow the first owner's row
    (`preferences.governing_user`)."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: `kind:channel` cells switched off. Stored as what is OFF so a kind added later starts on.
    off: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    quiet_start_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="21")
    quiet_end_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="8")
    daily_cap: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="12")


class NotificationDelivery(PKMixin, TimestampMixin, Base):
    """What the alert gate decided for one alert on one channel, or a bell item a job posted.
    Titles are our own sentences; `ref` carries ids only (hard rule 6)."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("tenant_id", "channel", "dedupe_key"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: `sent`, `held` (quiet hours), `folded` (past the daily cap) or `released` (went out in
    #: the digest that followed).
    state: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    href: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    due_at: Mapped[datetime | None] = mapped_column()
    released_at: Mapped[datetime | None] = mapped_column()
