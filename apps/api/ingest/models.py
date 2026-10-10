"""A client's plan for calling new leads, and the leads held for them (D-716).

Declared here and queried in SQL by `ingest/lead_policy.py`, the seam `callbacks/models.py`
uses: the model is what puts the tables in `Base.metadata` for the RLS coverage guardrail
and autogenerate (migration a9c4e2f7d138).
"""

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: What happens to a lead that arrives outside the client's calling hours.
AFTER_HOURS_CHOICES: tuple[str, ...] = ("next_open", "open_plus_3h", "next_day", "hold")
HOLD_STATUSES: tuple[str, ...] = ("held", "released", "dropped")
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class LeadCallPolicy(PKMixin, TimestampMixin, Base):
    __tablename__ = "lead_call_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_lead_call_policies_tenant"),
        CheckConstraint("wait_seconds BETWEEN 0 AND 3600", name="wait"),
        CheckConstraint(
            "hours_start >= '09:00' AND hours_end <= '21:00' AND hours_start < hours_end",
            name="hours",
        ),
        CheckConstraint(
            "cardinality(days) BETWEEN 1 AND 7 AND days <@ "
            "ARRAY['mon','tue','wed','thu','fri','sat','sun']",
            name="days",
        ),
        CheckConstraint("cardinality(holidays) <= 60", name="holidays"),
        CheckConstraint(f"after_hours IN {AFTER_HOURS_CHOICES!r}", name="after_hours"),
        CheckConstraint("retry_attempts BETWEEN 0 AND 3", name="retry_attempts"),
        CheckConstraint("retry_interval_minutes BETWEEN 10 AND 1440", name="retry_interval"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    calling_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    wait_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    hours_start: Mapped[time] = mapped_column(Time, nullable=False, server_default="09:00")
    hours_end: Mapped[time] = mapped_column(Time, nullable=False, server_default="21:00")
    days: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['mon','tue','wed','thu','fri','sat','sun']"),
    )
    holidays: Mapped[list[date]] = mapped_column(
        ARRAY(Date), nullable=False, server_default=text("'{}'::date[]")
    )
    after_hours: Mapped[str] = mapped_column(Text, nullable=False, server_default="next_open")
    retry_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    retry_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    detect_machines: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class LeadCallHold(PKMixin, TimestampMixin, Base):
    __tablename__ = "lead_call_holds"
    __table_args__ = (
        CheckConstraint(f"status IN {HOLD_STATUSES!r}", name="status"),
        CheckConstraint("(status = 'held') = (settled_at IS NULL)", name="settled"),
        Index(
            "uq_lead_call_holds_open",
            "tenant_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'held'"),
        ),
        Index(
            "ix_lead_call_holds_queue",
            "tenant_id",
            "held_at",
            postgresql_where=text("status = 'held'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="held")
    held_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    settled_at: Mapped[datetime | None]
    settled_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    callback_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
