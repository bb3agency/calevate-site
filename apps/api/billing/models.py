"""Billing & metering (DATA-MODEL §8). Money = NUMERIC(12,4) INR, never floats
(hard rule 7). usage_events is INSERT-only — the immutability trigger ships in the
same migration; fixes are compensating entries."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

UNIT_TYPES = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
)

MONEY = Numeric(12, 4)


class UsageEvent(PKMixin, Base):
    """Append-only ledger. Records OUR cost (unit_cost_paid) next to billable qty —
    per-client margin is a query (D-12). Maps 1:1 onto Get Call's cost.breakdown."""

    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint(f"unit_type IN {UNIT_TYPES!r}", name="unit_type_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))
    unit_type: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost_paid: Mapped[Decimal | None] = mapped_column(MONEY)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Plan(PKMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    setup_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    monthly_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    included_min: Mapped[int | None] = mapped_column(Integer)
    overage_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    hard_cap_min: Mapped[int | None] = mapped_column(Integer)
    hard_cap_spend: Mapped[Decimal | None] = mapped_column(MONEY)
    concurrency_ceiling: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    effective_from: Mapped[datetime | None]
    effective_to: Mapped[datetime | None]


class SpendState(TimestampMixin, Base):
    """Read by voice-runtime & campaign engine BEFORE dispatch — fail closed when capped."""

    __tablename__ = "spend_state"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True
    )
    month: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM' (IST billing month)
    minutes_used: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, server_default="0"
    )
    spend_used: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    capped: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


# Referenced (not yet modeled — M2): credit_ledger, invoices, engine_capacity.
