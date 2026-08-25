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
    __table_args__ = (
        CheckConstraint(f"source IN {INBOUND_SOURCES!r}", name="source_enum"),
        # The retiring secret and its deadline are one fact (migration a1c7d4e93b02):
        # a previous secret with no expiry never dies, an expiry with no secret is a
        # window onto nothing.
        CheckConstraint(
            "(previous_secret_ref IS NULL) = (previous_secret_expires_at IS NULL)",
            name="previous_secret_paired",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)  # secrets-manager ref, never raw
    # The secret this one replaced, honoured until `previous_secret_expires_at` so a
    # rotation does not 401 every submission a client has not finished re-pasting yet
    # (ingest/service.py `accepted_secrets`). Bounded by construction: nothing renews it.
    previous_secret_ref: Mapped[str | None] = mapped_column(Text)
    previous_secret_expires_at: Mapped[datetime | None] = mapped_column()
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

    # Per-endpoint opt-ins for `call.completed` (migration c3a9f1b48e70). All default
    # FALSE: the base contract is summary-and-outcome only, and each of these lets a
    # client ask for more against their OWN endpoint — a fact recorded in the config row
    # rather than assumed. `include_raw_transcript` is the unredacted transcript and is
    # gated at the registration route with the same role control as a raw read
    # (`calls:read_raw`); every delivery that carries it writes an `audit_log` row
    # (hard rule 5). See `integrations.service.call_completed_payload`.
    include_recording_url: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    include_transcript: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    include_raw_transcript: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class WebhookDelivery(PKMixin, Base):
    """Forensic trail (SEC-COMP §4 breach forensics). Not tenant-RLS'd: engine
    webhooks arrive before tenant resolution; rows carry payload refs, not payloads.

    **THE TWO DIRECTIONS ARE NOT THE SAME KIND OF RECORD, AND AN INVESTIGATOR MEETS THIS
    DECLARATION BEFORE THEY MEET ANY QUERY** (D-219; the finding is R-9 in
    `docs/evidence/audit-reliability.md`).

    `direction='out'` IS complete: `integrations.service.record_delivery` upserts a row
    per delivery id whatever the outcome, so every attempt we made — delivered, failed,
    skipped — is on file with its status, attempts and `payload_ref`.

    `direction='in'` is a record of what we ACCEPTED, not of what arrived. The receiver
    (`apps/voice-runtime/webhook_routes.py`) writes its row inside `if claimed:`, so a
    delivery refused at the source-IP check, refused over the size cap, refused as
    unkeyable, or abandoned at the claim deadline leaves NOTHING here. That is not an
    omission to be fixed by writing more rows: those four refusals happen before the
    request has become an event at all, hard rule 3 forbids a DB write on that path, and
    the write rate on an unauthenticated endpoint is the CALLER'S to choose. Inbound
    scope is read from the alert stream instead —
    `integrations.service.INBOUND_REFUSAL_ALERTS` names the codes and
    `integrations/service.py` carries the full argument.

    A `duplicate` is the one inbound outcome that leaves no row here and IS still
    durably recorded: `webhook_inbox_events.duplicate_count` counts it, keyed on the
    transition."""

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
    # Why a failed delivery failed, in OUR vocabulary: an authored refusal code
    # (`sheet_not_shared`, `no_credential_ref`) or an exception type. NEVER vendor prose
    # — a provider's error string is untrusted text that can quote the payload we handed
    # it, and this column is read by a client-facing screen (hard rule 6).
    reason: Mapped[str | None] = mapped_column(Text)
    # Outbound only (D-23): which client endpoint this attempt targeted. The delivery
    # screen scopes by it THROUGH `outbound_webhooks`, which is tenant-RLS'd, so this
    # table needs no policy of its own (migration 4be32bf3d12c).
    endpoint_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_webhooks.id", ondelete="SET NULL")
    )
    first_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
