"""The reliability triad (BACKEND-PATTERNS §4, D-30). Infra tables — not tenant-RLS'd
(claimed by workers before/without tenant context); payloads may carry tenant ids but
access is service-internal only, never exposed through tenant-facing endpoints.
All claims are CAS via conditional UPDATE (rowcount 0 = lost the race)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

OUTBOX_STATUSES = ("pending", "published", "failed")
INBOX_STATUSES = ("processing", "enqueued", "processed", "failed")
IDEMPOTENCY_STATUSES = ("processing", "completed", "failed")


class OutboxMessage(PKMixin, Base):
    """Written in the SAME transaction as the domain write. Dispatcher polls
    oldest-first; >=5 attempts → failed (= outbox DLQ) + alert."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(f"status IN {OUTBOX_STATUSES!r}", name="status_enum"),
        Index("ix_outbox_pending", "status", "created_at"),
    )

    queue: Mapped[str] = mapped_column(Text, nullable=False)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    job_id: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WebhookInboxEvent(PKMixin, Base):
    """Durable dedupe of engine events. Same (provider, event_key) with a DIFFERENT
    payload_hash = 409 (spoof/corruption signal). Redis SETNX on the delivery id
    stays the fast path; this row is the durable truth."""

    __tablename__ = "webhook_inbox_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_key"),
        CheckConstraint(f"status IN {INBOX_STATUSES!r}", name="status_enum"),
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    event_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="processing")
    event_name: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IdempotencyRecord(PKMixin, Base):
    """scope_key is an HMAC fingerprint of tenant/user — raw ids never stored.
    request_hash mismatch on the same key = 409; COMPLETED replays the stored
    response with an Idempotent-Replayed header. TTL ~24h via expires_at sweep."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope_key", "route", "method", "idempotency_key"),
        CheckConstraint(f"status IN {IDEMPOTENCY_STATUSES!r}", name="status_enum"),
        Index("ix_idempotency_expiry", "expires_at"),
    )

    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="processing")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
