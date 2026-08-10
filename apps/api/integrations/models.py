"""Webhook config + forensic delivery log (DATA-MODEL §6/§9, D-23).

inbound_webhooks: lead sources → us (delivery starts M2; table ships now).
outbound_webhooks: us → client tools (D-23; delivery starts M2; table ships now).
webhook_deliveries: forensic log both directions.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

INBOUND_SOURCES = ("meta_lead_ads", "website_form", "zoho", "sheets", "custom")
OUTBOUND_KINDS = ("webhook", "google_sheets")
DELIVERY_DIRECTIONS = ("in", "out")


class InboundWebhook(PKMixin, TimestampMixin, Base):
    __tablename__ = "inbound_webhooks"
    __table_args__ = (CheckConstraint(f"source IN {INBOUND_SOURCES!r}", name="source_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)  # secrets-manager ref, never raw
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    mapping: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class OutboundWebhook(PKMixin, TimestampMixin, Base):
    __tablename__ = "outbound_webhooks"
    __table_args__ = (CheckConstraint(f"kind IN {OUTBOUND_KINDS!r}", name="kind_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    mapping: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class WebhookDelivery(PKMixin, Base):
    """Forensic trail (SEC-COMP §4 breach forensics). Not tenant-RLS'd: engine
    webhooks arrive before tenant resolution; rows carry payload refs, not payloads."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(f"direction IN {DELIVERY_DIRECTIONS!r}", name="direction_enum"),
    )

    direction: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    payload_ref: Mapped[str | None] = mapped_column(Text)  # object-storage key
    first_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
