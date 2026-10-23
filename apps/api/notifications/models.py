"""How far each person has read the bell's feed (D-869, migration b9e4d2a7c513).

One row per (account, person) holding the newest instant they have seen. A high-water
mark rather than a row per item: the feed is assembled from sources that already exist
(the needs-attention queue and the announcements), so there is no item table to mark, and
"unread" is simply "newer than the mark".
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
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
