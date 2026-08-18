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
# Calevate's own telemarketer registration (SEC-COMP §3). Declared beside the column
# it constrains so the CHECK and the service that writes it cannot drift apart.
TM_REGISTRATION_STATUSES: tuple[str, ...] = (
    "not_registered",
    "submitted",
    "active",
    "suspended",
    "revoked",
)


class OutboxMessage(PKMixin, Base):
    """Written in the SAME transaction as the domain write. Dispatcher polls
    oldest-first; >=5 attempts → failed (= outbox DLQ) + alert."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(f"status IN {OUTBOX_STATUSES!r}", name="status_enum"),
        Index("ix_outbox_pending", "status", "created_at"),
    )

    # **THIS COLUMN ROUTES NOTHING, AND IT NEVER HAS.** Read that before you believe the
    # name: `service.OUTBOX_FLEET` is its only writer and writes one constant, and no
    # reader anywhere branches on it — `dispatch_outbox` publishes without it and
    # `WorkerSettings` sets no `queue_name`, so every job lands on arq's single default
    # queue whatever this says. Believing otherwise is the expensive mistake (an operator
    # assuming notifications are isolated from CRM deliveries when they share one
    # worker's ten slots), which is why the warning sits on the column rather than only
    # beside the constant.
    #
    # It is kept, not dropped, and D-162 is the record: it closes EITHER by dropping the
    # column in hard rule 8's two steps OR by a second worker fleet with
    # `WorkerSettings.queue_name` filtering on it. Honouring it today means a second
    # deployable for a platform with no clients (ROADMAP §6), and passing arq
    # `_queue_name` with no worker consuming that queue would silently stop every
    # notification. `service.OUTBOX_FLEET` carries the full argument.
    queue: Mapped[str] = mapped_column(Text, nullable=False)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # "This exact side effect, once" — a PARTIAL UNIQUE index, so once-only is a database
    # fact rather than a check-then-write (migration e83b5d1a4c07, P6.7). NULL for the
    # rows that are legitimately not unique: the CRM fan-out writes one row per subscribed
    # endpoint and those are not duplicates of each other. Written only through
    # `enqueue_outbox_once`; the index is declared in the migration rather than here
    # because it is partial, which is a strategy the migration chooses (same reasoning as
    # every other partial index in this schema).
    dedupe_key: Mapped[str | None] = mapped_column(Text)
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

    # THE TWO DRIFT SWEEPS' RECORDS, declared here late (P4.3).
    #
    # Six live columns, created by `d4b8e1c73f05` and `a7c31e05b8d4`, written by
    # `agents/reconciliation.py` and `kb/reconciliation.py`, read by two ops summaries —
    # and absent from this model, so `alembic revision --autogenerate` compared them
    # against metadata that did not mention them and would have proposed DROPPING all
    # six. CLAUDE.md's workflow is "autogenerate + hand-review diff"; an unreviewed
    # accept would delete the record that the drift exemption above spends fourteen lines
    # justifying.
    #
    # WHY THEY LIVE ON THE ROUTE ROW rather than on `agents`, restated because a reader
    # arriving at these six will ask: this row STANDS FOR one vendor-side agent object,
    # and both sweeps need a global work queue ordered by staleness plus a cross-tenant
    # ops summary — neither of which a tenant session can ask of a FORCE-RLS'd `agents`.
    # Putting them here is what lets `agents` keep its policy (hard rule 1).
    #
    # Each `*_state` holds a verdict from a fixed vocabulary and the two timestamps are
    # timestamps: no prompt, no disclosure line, no source name, no engine handle. That
    # is what keeps this globally-readable table free of anything a tenant owns.
    drift_state: Mapped[str | None] = mapped_column(Text)
    drift_checked_at: Mapped[datetime | None]
    drift_detected_at: Mapped[datetime | None]
    kb_drift_state: Mapped[str | None] = mapped_column(Text)
    kb_drift_checked_at: Mapped[datetime | None]
    kb_drift_detected_at: Mapped[datetime | None]

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
        CheckConstraint(
            f"tm_registration_status IN {TM_REGISTRATION_STATUSES!r}", name="tm_status_enum"
        ),
        # An active registration that cannot name itself is a claim, not a fact — the
        # same rule `dlt_registrations` applies to the client's PE.
        CheckConstraint(
            "tm_registration_status <> 'active' "
            "OR (tm_id IS NOT NULL AND tm_registered_at IS NOT NULL)",
            name="tm_active_is_identified",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    load_shed_mode: Mapped[str] = mapped_column(String, nullable=False, server_default="normal")
    # The big red switch (FLOWS §5): halts ALL tenants' outbound dispatch at once.
    outbound_halted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    halt_reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # Calevate's OWN telemarketer registration (SEC-COMP §3). One fact for the whole
    # platform, so it lives here rather than per-tenant: N copies of one registration
    # eventually disagree, and the launch gate would then depend on which copy it read.
    # The per-tenant half — the client's Principal Entity — is `dlt_registrations`.
    tm_registration_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="not_registered"
    )
    tm_id: Mapped[str | None] = mapped_column(Text)
    tm_registered_at: Mapped[datetime | None]
    # When WE last checked with the registrar. A registration can be suspended
    # underneath us, so "we believed it on this date" is a different fact from
    # "it was granted on this date".
    tm_verified_at: Mapped[datetime | None]
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
