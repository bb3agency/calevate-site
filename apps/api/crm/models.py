"""Calls, transcripts, extractions, leads (DATA-MODEL sections 4-5).

Cross-links: calls.lead_id is a real FK; leads.first_call_id/last_call_id are plain
UUIDs (denormalized pointers maintained by the pipeline — a second FK pair would be
circular). campaign_id stays a plain UUID until the campaigns table lands in M2.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

CALL_DIRECTIONS = ("inbound", "outbound")
CALL_STATUSES = (
    "queued",
    "ringing",
    "in_progress",
    "completed",
    "failed",
    "no_answer",
    "busy",
    "voicemail",
)
CONSENT_STATES = ("granted", "declined", "na")
OUTCOME_TAGS = ("resolved", "needs_follow_up", "transferred", "dropped")
SENTIMENTS = ("positive", "neutral", "negative")
SPEAKERS = ("agent", "caller")
LEAD_SOURCES = ("inbound_call", "webhook", "campaign", "manual")
LEAD_STATUSES = ("new", "contacted", "interested", "hot", "won", "lost")  # fixed enum, D-21
LEAD_EVENT_TYPES = ("status_change", "note", "call", "notification")


class Call(PKMixin, TimestampMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(f"direction IN {CALL_DIRECTIONS!r}", name="direction_enum"),
        CheckConstraint(f"status IN {CALL_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            f"consent_recording IS NULL OR consent_recording IN {CONSENT_STATES!r}",
            name="consent_enum",
        ),
        CheckConstraint(
            f"outcome_tag IS NULL OR outcome_tag IN {OUTCOME_TAGS!r}", name="outcome_enum"
        ),
        CheckConstraint(f"sentiment IS NULL OR sentiment IN {SENTIMENTS!r}", name="sentiment_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_call_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    from_e164: Mapped[str | None] = mapped_column(Text)
    to_e164: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    duration_s: Mapped[int | None] = mapped_column(Integer)
    recording_url: Mapped[str | None] = mapped_column(Text)  # OUR storage, never engine's
    disclosure_played: Mapped[bool | None] = mapped_column(Boolean)
    consent_recording: Mapped[str | None] = mapped_column(String)
    outcome_tag: Mapped[str | None] = mapped_column(String)
    sentiment: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))  # FK lands M2
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    # D-21 M2: the call this one follows up. Bounds the callback chain — see migration
    # efb47868ec59 for why an unbounded one is a compliance problem, not a UX one.
    callback_of_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="RESTRICT")
    )
    # {stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_p50, turn_p95}
    latency: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    engine_payload_ref: Mapped[str | None] = mapped_column(Text)  # raw vendor payload (debug only)


class TranscriptTurn(PKMixin, TimestampMixin, Base):
    """Default read = text_redacted; raw `text` gated by role + audit_log (hard rule 5)."""

    __tablename__ = "transcript_turns"
    __table_args__ = (
        UniqueConstraint("call_id", "idx"),
        CheckConstraint(f"speaker IN {SPEAKERS!r}", name="speaker_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # No `index=True`: UNIQUE(call_id, idx) leads with `call_id`, so it answers every
    # predicate a single-column index would, and the single-column one was costing an
    # index insertion per turn on the post-call pipeline for nothing (b9e5d2c74a18).
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="RESTRICT"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_redacted: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)


class CallExtraction(PKMixin, TimestampMixin, Base):
    """Every extraction stores schema_version + model + prompt_version (auditability, TRD §7).

    ONE row per call, enforced (migration d3b71c9a5e08). The post-call pipeline is
    re-entrant by design — a webhook arriving after the poller already resolved the call
    re-enters it (D-31) — and its update-or-insert closes the replay case but not the
    race: two runs can both read "no row" and both insert. Every reader here is written
    as if the invariant held (`ORDER BY created_at DESC LIMIT 1` in the CRM detail, "the"
    extraction in the retention eraser), so it is a constraint rather than a convention.

    `tenant_id` leads the key, and not only to match the pipeline's WHERE clause: under
    FORCEd RLS a unique violation is one of the few channels through which a row your
    policy hides can announce that it exists, and leading with the tenant means a
    conflict is only ever reachable against a row of your own.
    """

    __tablename__ = "call_extractions"
    __table_args__ = (UniqueConstraint("tenant_id", "call_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    errors: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class Lead(PKMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", "agent_id"),
        CheckConstraint(f"source IN {LEAD_SOURCES!r}", name="source_enum"),
        CheckConstraint(f"status IN {LEAD_STATUSES!r}", name="status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="new")
    # keys per extraction schema version
    data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    schema_version: Mapped[int | None] = mapped_column(Integer)
    first_call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    last_call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_repeat_caller: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None]


class LeadEvent(PKMixin, TimestampMixin, Base):
    __tablename__ = "lead_events"
    __table_args__ = (CheckConstraint(f"type IN {LEAD_EVENT_TYPES!r}", name="type_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    actor: Mapped[str | None] = mapped_column(Text)
