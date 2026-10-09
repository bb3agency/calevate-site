"""The auto-healer's tables (migration `b7d4e2a91c3f`, D-701), declared so `Base.metadata`
is complete. The migration is the schema of record.

Two are platform machinery read only by operators (`heal_incidents`, `heal_actions`) and
carry a nullable `tenant_id` without RLS, like `audit_log`; the client sees its own side
of an incident through `heal_client_incidents`, which is FORCE-RLS'd like every other
tenant table.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

INCIDENT_SCOPES: Final = ("agent", "tenant", "platform")
INCIDENT_STATES: Final = ("open", "mitigated", "escalated", "resolved")
STATUS_COMPONENTS: Final = ("calls", "dashboard", "numbers", "assistant")
ACTION_STEPS: Final = (
    "schedule",
    "act",
    "verify",
    "undo",
    "escalate",
    "protect",
    "restore",
    "notify",
    "propose",
    "decide",
)
ACTION_OUTCOMES: Final = ("ok", "failed", "skipped", "refused")
ACTOR_TYPES: Final = ("healer", "admin", "user")
CLIENT_INCIDENT_KINDS: Final = ("agent_unwell", "line_protected", "platform_outage")
PROTECTIONS: Final = ("none", "paused", "forwarded")
PROPOSAL_KINDS: Final = ("rollback_prompt", "review_knowledge", "review_languages")
PROPOSAL_STATUSES: Final = ("pending", "applied", "dismissed", "expired")

MAX_ACTION_DETAIL: Final = 500
MAX_PUBLIC_TITLE: Final = 120


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class HealIncident(PKMixin, TimestampMixin, Base):
    """One problem the healer is working on, from detection to resolution."""

    __tablename__ = "heal_incidents"
    __table_args__ = (
        CheckConstraint(_in("scope", INCIDENT_SCOPES), name="scope_enum"),
        CheckConstraint(_in("state", INCIDENT_STATES), name="state_enum"),
        CheckConstraint(
            f"component IS NULL OR {_in('component', STATUS_COMPONENTS)}", name="component_enum"
        ),
        CheckConstraint("NOT public OR public_title IS NOT NULL", name="public_has_title"),
        CheckConstraint("(state = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_iff"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index(
            "uq_heal_incidents_open_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "ix_heal_incidents_due", "next_attempt_at", postgresql_where=text("resolved_at IS NULL")
        ),
        Index("ix_heal_incidents_opened", text("opened_at DESC")),
    )

    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    playbook: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_code: Mapped[str] = mapped_column(String(96), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None]
    component: Mapped[str | None] = mapped_column(String(16))
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    public_title: Mapped[str | None] = mapped_column(String(MAX_PUBLIC_TITLE))
    last_outcome: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    mitigated_at: Mapped[datetime | None]
    escalated_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]


class HealAction(PKMixin, Base):
    """One thing the healer did, tried, skipped or was told to do. Append-only."""

    __tablename__ = "heal_actions"
    __table_args__ = (
        CheckConstraint(_in("step", ACTION_STEPS), name="step_enum"),
        CheckConstraint(_in("outcome", ACTION_OUTCOMES), name="outcome_enum"),
        CheckConstraint(_in("actor_type", ACTOR_TYPES), name="actor_type_enum"),
        CheckConstraint(
            f"detail IS NULL OR length(detail) <= {MAX_ACTION_DETAIL}", name="detail_cap"
        ),
        Index("ix_heal_actions_at", text("at DESC")),
        Index("ix_heal_actions_incident", "incident_id", "at"),
        Index("ix_heal_actions_playbook_at", "playbook", text("at DESC")),
        Index("ix_heal_actions_alert", "alert_id", postgresql_where=text("alert_id IS NOT NULL")),
    )

    at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    incident_id: Mapped[UUID | None] = mapped_column(ForeignKey("heal_incidents.id"))
    playbook: Mapped[str] = mapped_column(String(64), nullable=False)
    step: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    tenant_id: Mapped[UUID | None]
    agent_id: Mapped[UUID | None]
    alarm_code: Mapped[str | None] = mapped_column(String(96))
    #: The `platform_alerts` episode a founder page was sent for, so it is sent once.
    alert_id: Mapped[UUID | None]
    detail: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="healer")
    actor_id: Mapped[UUID | None]


class HealClientIncident(PKMixin, TimestampMixin, Base):
    """A client's side of an incident: what happened to their line and what we did."""

    __tablename__ = "heal_client_incidents"
    __table_args__ = (
        CheckConstraint(_in("kind", CLIENT_INCIDENT_KINDS), name="kind_enum"),
        CheckConstraint(_in("protection", PROTECTIONS), name="protection_enum"),
        CheckConstraint("state IN ('open', 'resolved')", name="state_enum"),
        CheckConstraint("(state = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_iff"),
        CheckConstraint(
            "campaigns_paused >= 0 AND requeued >= 0 AND missed_calls >= 0",
            name="counts_nonnegative",
        ),
        UniqueConstraint(
            "incident_id", "tenant_id", "agent_id", postgresql_nulls_not_distinct=True
        ),
        Index("ix_heal_client_incidents_tenant_recent", "tenant_id", text("opened_at DESC")),
        Index(
            "ix_heal_client_incidents_open_agent",
            "agent_id",
            postgresql_where=text("state = 'open'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("heal_incidents.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    protection: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    campaigns_paused: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requeued: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    missed_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    must_act: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    opened_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    protected_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    notified_at: Mapped[datetime | None]
    restored_notified_at: Mapped[datetime | None]
    notified_by: Mapped[str | None] = mapped_column(String(32))


class HealFallbackPhone(PKMixin, TimestampMixin, Base):
    """The client's own phone that takes their calls while their agent cannot (owner-set)."""

    __tablename__ = "heal_fallback_phones"
    __table_args__ = (
        CheckConstraint(r"phone_e164 ~ '^\+91[6-9][0-9]{9}$'", name="phone_india_mobile"),
        UniqueConstraint("tenant_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    #: A `users.id`, or an `admin_users.id` when an operator set it in view-as.
    updated_by: Mapped[UUID | None]


class AgentHealthWindow(PKMixin, TimestampMixin, Base):
    """One agent's real calls over one fifteen-minute window, and the score they earn."""

    __tablename__ = "agent_health_windows"
    __table_args__ = (
        CheckConstraint(
            "calls >= 0 AND short_calls >= 0 AND failed_calls >= 0 AND slow_starts >= 0 "
            "AND escalations >= 0 AND knowledge_misses >= 0 AND action_failures >= 0 "
            "AND language_misses >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        UniqueConstraint("agent_id", "window_start"),
        Index("ix_agent_health_windows_tenant_recent", "tenant_id", text("window_start DESC")),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    calls: Mapped[int] = mapped_column(Integer, nullable=False)
    short_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    slow_starts: Mapped[int] = mapped_column(Integer, nullable=False)
    escalations: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_misses: Mapped[int] = mapped_column(Integer, nullable=False)
    action_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    language_misses: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    baseline: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    deviating: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class HealProposal(PKMixin, TimestampMixin, Base):
    """A behaviour change the healer will not make on its own, waiting for a person."""

    __tablename__ = "heal_proposals"
    __table_args__ = (
        CheckConstraint(_in("kind", PROPOSAL_KINDS), name="kind_enum"),
        CheckConstraint(_in("status", PROPOSAL_STATUSES), name="status_enum"),
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)", name="decided_iff_not_pending"
        ),
        Index(
            "uq_heal_proposals_one_pending",
            "agent_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_heal_proposals_tenant_recent", "tenant_id", text("created_at DESC")),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("heal_incidents.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    #: Ids and numbers only (a prompt version to restore, the share of misses); never text.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: A `users.id`, or an `admin_users.id` when an operator decided in view-as.
    decided_by: Mapped[UUID | None]
    decided_at: Mapped[datetime | None]


__all__ = [
    "ACTION_OUTCOMES",
    "ACTION_STEPS",
    "ACTOR_TYPES",
    "CLIENT_INCIDENT_KINDS",
    "INCIDENT_SCOPES",
    "INCIDENT_STATES",
    "MAX_ACTION_DETAIL",
    "MAX_PUBLIC_TITLE",
    "PROPOSAL_KINDS",
    "PROPOSAL_STATUSES",
    "PROTECTIONS",
    "STATUS_COMPONENTS",
    "AgentHealthWindow",
    "HealAction",
    "HealClientIncident",
    "HealFallbackPhone",
    "HealIncident",
    "HealProposal",
]
