"""The plan tables (migration `f4b8d2a61c39`, D-893 F3), declared so `Base.metadata` is
complete. The migration is the schema of record and carries the reasoning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

PlanStatus = Literal["proposed", "approved", "running", "done", "cancelled", "expired"]
PLAN_STATUSES: Final[tuple[PlanStatus, ...]] = (
    "proposed",
    "approved",
    "running",
    "done",
    "cancelled",
    "expired",
)
TargetStatus = Literal["pending", "done", "skipped", "failed"]
TARGET_STATUSES: Final[tuple[TargetStatus, ...]] = ("pending", "done", "skipped", "failed")
PlanOrigin = Literal["pip", "console"]
TargetType = Literal["lead", "call", "callback"]
MAX_TARGET_REASON: Final = 300


class CopilotPlan(PKMixin, TimestampMixin, Base):
    """One set action, frozen for one approval."""

    __tablename__ = "copilot_plans"
    __table_args__ = (
        CheckConstraint(f"status IN {PLAN_STATUSES!r}", name="status_enum"),
        CheckConstraint("origin IN ('pip', 'console')", name="origin_enum"),
        CheckConstraint("target_type IN ('lead', 'call', 'callback')", name="target_type_enum"),
        CheckConstraint("target_count >= 0 AND excluded_count >= 0", name="counts"),
        CheckConstraint("estimate_inr IS NULL OR estimate_inr >= 0", name="estimate"),
        CheckConstraint(
            "(status IN ('proposed', 'expired')) OR approved_at IS NOT NULL "
            "OR status = 'cancelled'",
            name="approved_at",
        ),
        Index("ix_copilot_plans_tenant_user_recent", "tenant_id", "user_id", "created_at"),
        Index(
            "ix_copilot_plans_active",
            "updated_at",
            postgresql_where=text("status IN ('approved', 'running')"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    lens_text: Mapped[str] = mapped_column(Text, nullable=False)
    run_at: Mapped[datetime | None]
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exclusions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    estimate_inr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimate_note: Mapped[str] = mapped_column(Text, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    approved_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    done_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    result: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL")
    )


class CopilotPlanTarget(PKMixin, TimestampMixin, Base):
    """One frozen target of a plan, and what happened to it."""

    __tablename__ = "copilot_plan_targets"
    __table_args__ = (
        CheckConstraint(f"status IN {TARGET_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            "NOT excluded OR (status = 'skipped' AND reason IS NOT NULL)",
            name="excluded_says_why",
        ),
        CheckConstraint(
            f"reason IS NULL OR length(reason) <= {MAX_TARGET_REASON}", name="reason_cap"
        ),
        UniqueConstraint("plan_id", "target_id"),
        Index("ix_copilot_plan_targets_plan_position", "plan_id", "position"),
        Index(
            "ix_copilot_plan_targets_pending",
            "plan_id",
            "position",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("copilot_plans.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None]


__all__ = [
    "MAX_TARGET_REASON",
    "PLAN_STATUSES",
    "TARGET_STATUSES",
    "CopilotPlan",
    "CopilotPlanTarget",
    "PlanOrigin",
    "PlanStatus",
    "TargetStatus",
    "TargetType",
]
