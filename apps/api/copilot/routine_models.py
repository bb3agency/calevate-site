"""The routines tables (migration `d3a7f5c19e42`), declared so `Base.metadata` is complete.

The migration is the schema of record and carries the reasoning; this file exists for
`copilot/models.py`'s reason — `alembic/env.py` autogenerates against `Base.metadata`, and
a column or index the model does not declare is one the next `--autogenerate` proposes to
drop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: The longest routine name, instruction and skip reason. Repeated by the schema so a writer
#: refuses before the round trip with a sentence rather than a constraint name.
MAX_ROUTINE_NAME: Final = 80
MAX_ROUTINE_INSTRUCTION: Final = 2_000
MAX_RUN_REASON: Final = 300


class CopilotRoutine(PKMixin, TimestampMixin, Base):
    """One standing instruction the assistant runs on a schedule, as the person who wrote it."""

    __tablename__ = "copilot_routines"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(btrim(instruction)) > 0", name="instruction_not_blank"),
        CheckConstraint(
            f"length(instruction) <= {MAX_ROUTINE_INSTRUCTION}", name="instruction_cap"
        ),
        CheckConstraint("days BETWEEN 1 AND 127", name="days_mask"),
        CheckConstraint("at_minute BETWEEN 0 AND 1439", name="at_minute_range"),
        CheckConstraint("enabled = (next_run_at IS NOT NULL)", name="due_iff_enabled"),
        Index("ix_copilot_routines_tenant_user_recent", "tenant_id", "user_id", "created_at"),
        Index("ix_copilot_routines_due", "next_run_at", postgresql_where=text("enabled")),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(MAX_ROUTINE_NAME), nullable=False)
    #: Redacted on write, like a job's goal.
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    #: Monday-first seven-bit mask: bit 0 is Monday, bit 6 is Sunday. 127 is every day.
    days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: Minutes after midnight IST.
    at_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    next_run_at: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]


class CopilotRoutineRun(PKMixin, TimestampMixin, Base):
    """One firing of a routine: queued as a background job, or skipped with the reason."""

    __tablename__ = "copilot_routine_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger_enum"),
        CheckConstraint("status IN ('queued', 'skipped')", name="status_enum"),
        CheckConstraint("(status = 'skipped') = (reason IS NOT NULL)", name="reason_iff_skipped"),
        CheckConstraint(f"reason IS NULL OR length(reason) <= {MAX_RUN_REASON}", name="reason_cap"),
        UniqueConstraint("routine_id", "slot_at"),
        Index("ix_copilot_routine_runs_routine_recent", "routine_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    routine_id: Mapped[UUID] = mapped_column(
        ForeignKey("copilot_routines.id", ondelete="CASCADE"), nullable=False
    )
    slot_at: Mapped[datetime] = mapped_column(nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("copilot_jobs.id", ondelete="SET NULL"))


__all__ = [
    "MAX_ROUTINE_INSTRUCTION",
    "MAX_ROUTINE_NAME",
    "MAX_RUN_REASON",
    "CopilotRoutine",
    "CopilotRoutineRun",
]
