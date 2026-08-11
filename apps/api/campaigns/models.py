"""Campaign tables (DATA-MODEL §6).

Two state machines, both driven by CAS transitions (BACKEND-PATTERNS §5):

- `campaigns.status`: draft → scheduled → running ⇄ paused → completed | cancelled.
- `campaign_contacts.status`: pending → dialing → connected | no_answer | failed |
  dnc_blocked | completed. `dnc_blocked` is TERMINAL — a number that opted out is not
  "retryable", it is done.

`dlt_templates` ships alongside because the launch gate reads it: an approved template
is one of the named blockers (SEC-COMP §3), and the 140/160 series-vs-classification
match is a CHECK at launch, not a convention.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

CAMPAIGN_CLASSIFICATIONS = ("promotional", "transactional", "service")
CAMPAIGN_STATUSES = ("draft", "scheduled", "running", "paused", "completed", "cancelled")
CONTACT_STATUSES = (
    "pending",
    "dialing",
    "connected",
    "no_answer",
    "failed",
    "dnc_blocked",
    "completed",
)
TEMPLATE_STATUSES = ("draft", "submitted", "approved", "rejected")


class Campaign(PKMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            f"classification IN {CAMPAIGN_CLASSIFICATIONS!r}", name="classification_enum"
        ),
        CheckConstraint(f"status IN {CAMPAIGN_STATUSES!r}", name="status_enum"),
        # Per-campaign concurrency slider, bounded by the plan ceiling at launch time
        # (FLOWS §5 rule 4); the DB bound is the absolute sanity limit.
        CheckConstraint("concurrency BETWEEN 1 AND 10", name="concurrency_range"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    number_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    dlt_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dlt_templates.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    schedule: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    # {max_attempts, backoff_minutes, windows} — FLOWS §5 per-contact retries.
    retry_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    calling_hours: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    engine_campaign_ref: Mapped[str | None] = mapped_column(Text)
    launched_at: Mapped[datetime | None]


class CampaignContact(PKMixin, TimestampMixin, Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164"),
        CheckConstraint(f"status IN {CONTACT_STATUSES!r}", name="status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempt_at: Mapped[datetime | None]
    next_attempt_at: Mapped[datetime | None]
    last_call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    dedupe_hash: Mapped[str | None] = mapped_column(Text)


class DltTemplate(PKMixin, TimestampMixin, Base):
    """The DLT voice template a campaign speaks under. `dlt_ref` is the registrar's id;
    `approved` is what the launch gate requires (SEC-COMP §3)."""

    __tablename__ = "dlt_templates"
    __table_args__ = (
        CheckConstraint("kind = 'voice'", name="kind_enum"),
        CheckConstraint(
            f"classification IN {CAMPAIGN_CLASSIFICATIONS!r}", name="classification_enum"
        ),
        CheckConstraint(f"status IN {TEMPLATE_STATUSES!r}", name="status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="voice")
    classification: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dlt_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
