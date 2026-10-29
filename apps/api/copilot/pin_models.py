"""The dashboard pin tables (migration `c9d4e7a2b815`), declared so `Base.metadata` is
complete. The migration is the schema of record and carries the reasoning."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

MAX_PIN_CHART: Final = 40
MAX_PIN_TITLE: Final = 80


def _checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("jsonb_typeof(args) = 'object'", name="args_object"),
        CheckConstraint("position BETWEEN 0 AND 99", name="position_range"),
    )


class DashboardPin(PKMixin, TimestampMixin, Base):
    """One chart kept on an account's home: the query, never the figures."""

    __tablename__ = "dashboard_pins"
    __table_args__ = (
        *_checks(),
        Index("ix_dashboard_pins_tenant_position", "tenant_id", "position"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    chart: Mapped[str] = mapped_column(String(MAX_PIN_CHART), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(MAX_PIN_TITLE), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    removed_at: Mapped[datetime | None]


class AdminDashboardPin(PKMixin, TimestampMixin, Base):
    """One chart kept on the admin home, shared by the operators. Platform-scoped."""

    __tablename__ = "admin_dashboard_pins"
    __table_args__ = (
        *_checks(),
        Index("ix_admin_dashboard_pins_position", "position"),
    )

    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    chart: Mapped[str] = mapped_column(String(MAX_PIN_CHART), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(MAX_PIN_TITLE), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    removed_at: Mapped[datetime | None]


__all__ = ["MAX_PIN_CHART", "MAX_PIN_TITLE", "AdminDashboardPin", "DashboardPin"]
