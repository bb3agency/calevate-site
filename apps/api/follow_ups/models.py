"""Tables behind Follow-ups (D-940, migration f4b8d2a6c913).

`follow_ups` is the journey a client edits; `follow_up_versions` freezes its steps at each
publish (INSERT-only), so a run started on version 3 finishes on version 3 whatever is
published after it. `follow_up_runs` is one lead going through one version, and
`follow_up_run_events` what happened at each step (INSERT-only).

Ids and short codes only. The one phone number is `follow_up_runs.phone_e164`, which a run
needs before it has a lead row; no column holds a message body or anything a caller said.

All four are tenant tables with FORCEd RLS (hard rule 1); the cross-tenant zero-rows proof
is `tests/follow_ups_rls_test.py`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

FOLLOW_UP_STATUSES = ("draft", "live", "paused", "off")
RUN_STATUSES = ("running", "waiting", "done", "stopped")
LIVE_RUN_STATUSES = ("running", "waiting")
#: The ready-made Follow-ups a client can start from (docs/FOLLOW-UPS.md, Starters).
STARTER_KEYS = (
    "call_new_leads",
    "qualify_new_leads",
    "missed_call_callback",
    "appointment_reminder",
    "payment_reminder",
    "win_back",
)
MAX_NAME_CHARS = 80


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class FollowUp(PKMixin, TimestampMixin, Base):
    __tablename__ = "follow_ups"
    __table_args__ = (
        CheckConstraint(_in("status", FOLLOW_UP_STATUSES), name="status_enum"),
        CheckConstraint(
            f"char_length(btrim(name)) BETWEEN 1 AND {MAX_NAME_CHARS}", name="name_length"
        ),
        CheckConstraint("jsonb_typeof(trigger) = 'object'", name="trigger_is_object"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_is_object"),
        CheckConstraint("draft IS NULL OR jsonb_typeof(draft) = 'array'", name="draft_is_array"),
        CheckConstraint(
            "status NOT IN ('live', 'paused') OR live_version_id IS NOT NULL",
            name="live_has_version",
        ),
        CheckConstraint(f"starter IS NULL OR {_in('starter', STARTER_KEYS)}", name="starter_enum"),
        # One ready-made "Call new leads" per account: the migration creates it and the
        # starters list offers it only while none exists.
        Index(
            "uq_follow_ups_call_new_leads",
            "tenant_id",
            unique=True,
            postgresql_where=text("starter = 'call_new_leads'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    #: What starts a run, as being edited. Runs read the frozen copy on their version.
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: The steps being edited; NULL when nothing differs from the live version.
    draft: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    live_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "follow_up_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_follow_ups_live_version_id_follow_up_versions",
        )
    )
    starter: Mapped[str | None] = mapped_column(String)
    #: NULL when no person of this account made it (the migration, an operator).
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class FollowUpVersion(PKMixin, Base):
    __tablename__ = "follow_up_versions"
    __table_args__ = (
        UniqueConstraint("follow_up_id", "number", name="uq_follow_up_versions_number"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("jsonb_typeof(steps) = 'array'", name="steps_is_array"),
        CheckConstraint("jsonb_typeof(trigger) = 'object'", name="trigger_is_object"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_is_object"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    follow_up_id: Mapped[UUID] = mapped_column(
        ForeignKey("follow_ups.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Who published it; a plain id because an append-only row cannot take `SET NULL`.
    published_by: Mapped[UUID | None] = mapped_column()
    published_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class FollowUpRun(PKMixin, TimestampMixin, Base):
    __tablename__ = "follow_up_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status_enum"),
        CheckConstraint("attempt >= 0", name="attempt_not_negative"),
        CheckConstraint(
            "(status IN ('done', 'stopped')) = (ended_at IS NOT NULL)", name="ended_when_over"
        ),
        CheckConstraint(
            "end_reason IS NULL OR char_length(end_reason) <= 64", name="end_reason_length"
        ),
        # Nobody is in the same Follow-up twice at once.
        Index(
            "uq_follow_up_runs_one_live",
            "follow_up_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status IN ('running', 'waiting') AND lead_id IS NOT NULL"),
        ),
        # A date, a call or a delivery starts a lead once.
        Index(
            "uq_follow_up_runs_trigger",
            "follow_up_id",
            "lead_id",
            "trigger_ref",
            unique=True,
            postgresql_where=text("lead_id IS NOT NULL"),
        ),
        Index(
            "uq_follow_up_runs_trigger_no_lead",
            "follow_up_id",
            "phone_e164",
            "trigger_ref",
            unique=True,
            postgresql_where=text("lead_id IS NULL"),
        ),
        Index(
            "ix_follow_up_runs_due",
            "tenant_id",
            "wake_at",
            postgresql_where=text("status = 'waiting' AND wake_at IS NOT NULL"),
        ),
        Index("ix_follow_up_runs_follow_up", "follow_up_id", text("started_at DESC")),
        Index(
            "ix_follow_up_runs_phone_live",
            "tenant_id",
            "phone_e164",
            postgresql_where=text("status IN ('running', 'waiting')"),
        ),
        Index(
            "ix_follow_up_runs_waiting_call",
            "waiting_call_id",
            postgresql_where=text("waiting_call_id IS NOT NULL"),
        ),
        Index("ix_follow_up_runs_lead", "lead_id", postgresql_where=text("lead_id IS NOT NULL")),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    follow_up_id: Mapped[UUID] = mapped_column(
        ForeignKey("follow_ups.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("follow_up_versions.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="waiting")
    step_id: Mapped[str] = mapped_column(String, nullable=False)
    wake_at: Mapped[datetime | None] = mapped_column()
    waiting_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL")
    )
    #: The call this run last placed (or the call that started it): what `decide` reads.
    last_call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    trigger_ref: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column()
    end_reason: Mapped[str | None] = mapped_column(String)
    goal_reached: Mapped[bool] = mapped_column(nullable=False, server_default="false")


class FollowUpRunEvent(PKMixin, Base):
    __tablename__ = "follow_up_run_events"
    __table_args__ = (
        CheckConstraint("char_length(result) <= 64", name="result_length"),
        CheckConstraint("char_length(kind) <= 32", name="kind_length"),
        Index("ix_follow_up_run_events_run", "run_id", "at"),
        # One outcome per (run, step, attempt): a worker retry finds it and moves on.
        Index(
            "uq_follow_up_run_events_step",
            "run_id",
            "step_id",
            "attempt",
            "kind",
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("follow_up_runs.id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    kind: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    #: A plain id: an append-only row cannot follow a call's erasure with `SET NULL`.
    call_id: Mapped[UUID | None] = mapped_column()
    at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


__all__ = [
    "FOLLOW_UP_STATUSES",
    "LIVE_RUN_STATUSES",
    "MAX_NAME_CHARS",
    "RUN_STATUSES",
    "STARTER_KEYS",
    "FollowUp",
    "FollowUpRun",
    "FollowUpRunEvent",
    "FollowUpVersion",
]
