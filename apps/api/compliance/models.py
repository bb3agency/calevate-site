"""Compliance & audit (DATA-MODEL §9). consent_ledger and audit_log are INSERT-only
(immutability triggers in the migration). audit_log additionally carries the tamper-
evident hash chain (BACKEND-PATTERNS §7): prev_hash/entry_hash filled by the writer
under a Redis lock; the chain head lives in Redis."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

CONSENT_PURPOSES = ("recording", "callback", "marketing")
CONSENT_STATUSES = ("granted", "declined", "withdrawn")
DATA_CATEGORIES = ("recording", "transcript", "lead", "consent_log")
RETENTION_ACTIONS = ("delete", "anonymize")
ACTOR_TYPES = ("admin", "user", "system")


class ConsentLedgerEntry(PKMixin, Base):
    __tablename__ = "consent_ledger"
    __table_args__ = (
        CheckConstraint(f"purpose IN {CONSENT_PURPOSES!r}", name="purpose_enum"),
        CheckConstraint(f"status IN {CONSENT_STATUSES!r}", name="status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)  # e.g. transcript span
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class RetentionPolicy(PKMixin, Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(f"data_category IN {DATA_CATEGORIES!r}", name="category_enum"),
        CheckConstraint(f"action IN {RETENTION_ACTIONS!r}", name="action_enum"),
        # TRAI 90-day floor for recordings (SEC-COMP §1)
        CheckConstraint(
            "data_category != 'recording' OR ttl_days >= 90", name="recording_ttl_floor"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    data_category: Mapped[str] = mapped_column(String, nullable=False)
    ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, server_default="delete")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DeletionRequest(PKMixin, Base):
    """Deletion-with-proof (DPDP): proof JSON records what/where/when/hashes."""

    __tablename__ = "deletion_requests"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None]
    proof: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class AuditLogEntry(PKMixin, Base):
    """NOT tenant-RLS'd: admin-realm surface reads it cross-tenant, always audited
    itself. INSERT-only. Includes recording/raw-transcript reads (hard rule 5)."""

    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(f"actor_type IN {ACTOR_TYPES!r}", name="actor_enum"),)

    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # Tamper-evident chain (BACKEND-PATTERNS §7)
    prev_hash: Mapped[str | None] = mapped_column(Text)
    entry_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
