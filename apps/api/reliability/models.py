"""The reliability triad (BACKEND-PATTERNS §4, D-30). Infra tables — not tenant-RLS'd
(claimed by workers before/without tenant context); payloads may carry tenant ids but
access is service-internal only, never exposed through tenant-facing endpoints.
All claims are CAS via conditional UPDATE (rowcount 0 = lost the race)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

OUTBOX_STATUSES = ("pending", "published", "failed")
INBOX_STATUSES = ("processing", "enqueued", "processed", "failed")
IDEMPOTENCY_STATUSES = ("processing", "completed", "failed")
LOAD_SHED_MODES = ("normal", "reduced", "emergency", "maintenance")


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
    # The claim lease (migration 7c04ab5f9e26). The claim COMMITS — an uncommitted
    # attempt bump dies with the dispatcher that wrote it — so exclusivity cannot rest
    # on the `FOR UPDATE` locks that commit releases; it rests on this deadline instead.
    # NULL = nobody holds it; in the future = in flight; in the past = abandoned, and
    # the next claim tick picks it up with its attempt count intact. `status` keeps its
    # three values on purpose, so every existing reader of it stays correct.
    locked_until: Mapped[datetime | None]
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
    # How many times this same event arrived again after the first claim — the
    # "deduplicated" column of the webhook activity view (migration 2c8993164b46).
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    enqueued_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EngineAgentRoute(Base):
    """(engine, engine_agent_ref) → (tenant_id, agent_id). The inbound routing table.

    Why this exists as its own table instead of a query against `agents`: an engine
    webhook arrives with the VENDOR's agent id and nothing else — no session, no
    tenant, no GUC — so resolving it means reading across tenants. `agents` is
    FORCE-RLS'd and MUST stay that way (hard rule 1), and the alternative (an RLS
    exemption, or running the resolver as the owner role) would punch a cross-tenant
    hole through the exact control the whole design rests on.

    So the resolver reads a table that is deliberately global and deliberately
    boring: two opaque ids and the pair they map to. It carries no PII and no call
    data, and being global is a property of routing, not a compromise of isolation.
    Written by the agent publish path in the SAME transaction that sets
    `agents.engine_agent_ref`, so the two cannot disagree.
    """

    __tablename__ = "engine_agent_routes"

    # Composite PK: (engine, engine_agent_ref) IS the natural key — the same vendor id
    # can exist on two engines during a migration and must resolve independently.
    engine: Mapped[str] = mapped_column(Text, primary_key=True)
    engine_agent_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlatformState(Base):
    """Single-row global switchboard: the load-shed mode AND the big red switch.

    BACKEND-PATTERNS §6 requires the load-shed mode to be DURABLE in Postgres (Redis
    is only its cache) so a Redis flush cannot silently re-open a service an operator
    shut. The outbound halt lives in the same row because it is the same question —
    "is the platform allowed to do work right now" — and one row means one read.

    Not tenant-scoped and deliberately not RLS'd: it is global by definition, written
    only through the audited admin ops surface (step-up confirmation, §7).
    """

    __tablename__ = "platform_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(f"load_shed_mode IN {LOAD_SHED_MODES!r}", name="load_shed_enum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    load_shed_mode: Mapped[str] = mapped_column(String, nullable=False, server_default="normal")
    # The big red switch (FLOWS §5): halts ALL tenants' outbound dispatch at once.
    outbound_halted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    halt_reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
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
