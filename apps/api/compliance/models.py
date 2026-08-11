"""Compliance & audit (DATA-MODEL §9). consent_ledger and audit_log are INSERT-only
(immutability triggers in the migration). audit_log additionally carries the tamper-
evident hash chain (BACKEND-PATTERNS §7): prev_hash/entry_hash filled by the writer
under a Redis lock; the chain head lives in Redis."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

CONSENT_PURPOSES = ("recording", "callback", "marketing")
# DLT Principal Entity registration, as the registrar's own lifecycle (SEC-COMP §1/§3).
# `not_started` exists so a row can say "we have not begun" without being absent —
# absence and "pending" are different facts to an operator chasing an onboarding step.
PE_REGISTRATION_STATUSES = ("not_started", "submitted", "active", "suspended", "rejected")
# The PE→TM authorisation: the client (PE) naming Calevate (TM) as permitted to place
# calls on their behalf. Separate from the PE's own status because it fails separately:
# a perfectly registered entity that never linked us is a different to-do item.
TM_LINK_STATUSES = ("not_linked", "pending", "active", "revoked")
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


class DncEntry(PKMixin, Base):
    """Do-not-call list (DATA-MODEL §9). `tenant_id IS NULL` = a GLOBAL entry.

    Two scopes in one table, as documented, with a deliberately asymmetric RLS policy
    (see the migration): a tenant can READ global entries — it must, or a nationally
    suppressed number would still be dialled — but can only WRITE its own. Creating a
    global entry is not a tenant-reachable operation at all.

    Additions must propagate BEFORE the next dispatch tick (hard rule 5), which is why
    the check reads this table live on every dispatch path rather than caching it.
    """

    __tablename__ = "dnc_list"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'tenant')", name="scope_enum"),
        CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) "
            "OR (scope = 'tenant' AND tenant_id IS NOT NULL)",
            name="scope_matches_tenant",
        ),
        UniqueConstraint("tenant_id", "phone_e164"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String, nullable=False, server_default="tenant")
    source: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DltRegistration(PKMixin, TimestampMixin, Base):
    """Whether this client may lawfully have calls placed on their behalf (SEC-COMP §3).

    The DLT role model, per §3: the **client is the Principal Entity (PE)** and
    **Calevate is the registered Telemarketer (TM)** linked to them. Three registrations
    exist at the registrar and only two of them had a home in this schema —
    `phone_numbers.dlt_status` (the header) and `dlt_templates.status` (the voice
    template). This is the third and the widest: the ENTITY. A registered header on an
    unregistered entity is still unregistered traffic, dropped at the network as spam,
    with the complaints filed against the client.

    One row per tenant (UNIQUE on tenant_id): a business is one Principal Entity. The
    row is MUTABLE — a registration is suspended and restored over its life — so this
    is deliberately not an append-only ledger; `audit_log` carries who changed it.

    NOT modelled here: Calevate's OWN TM registration, which §3 also names. That is a
    company-level fact, true or false for every tenant at once, and it belongs with the
    other global switches in `platform_state` (DATA-MODEL §9a), not in a per-tenant
    table where it would be stored N times and disagree with itself.
    """

    __tablename__ = "dlt_registrations"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint(f"status IN {PE_REGISTRATION_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"tm_link_status IN {TM_LINK_STATUSES!r}", name="tm_link_status_enum"),
        # An `active` registration that cannot name its PE id is not a registration,
        # it is a claim. The id is what an operator checks against the registrar.
        CheckConstraint(
            "status <> 'active' OR (pe_id IS NOT NULL AND registered_at IS NOT NULL)",
            name="active_registration_names_its_pe",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pe_id: Mapped[str | None] = mapped_column(Text)  # the registrar's Principal Entity id
    entity_name: Mapped[str | None] = mapped_column(Text)  # as registered, not as branded
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="not_started")
    tm_link_status: Mapped[str] = mapped_column(String, nullable=False, server_default="not_linked")
    registered_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]  # when WE last checked it against the registrar


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
    """Deletion-with-proof (DPDP): proof JSON records what/where/when/hashes.

    The number lives exactly as long as the erasure takes. An OPEN request carries it
    because the worker's only handle on the subject is this row; a COMPLETED request has
    it cleared in the same UPDATE that stamps `proof`, because otherwise the record
    proving we erased someone is the last surviving copy of their number and no retention
    policy covers this table (migration f4a8e1c07b62). `subject_ref` — the same
    sha256(number)[:32] as the proof's `subject_hash` and the subject-access export — is
    what answers "have we already erased this person?" afterwards, and it answers it only
    to a reader who already holds the number.

    Two constraints keep those halves honest and are declared here to match the
    migration: an open request must name its subject, and every row must carry its
    reference. The first is also what keeps the partial unique index below total over the
    rows it covers — a NULL never conflicts in a unique index, so a request that could
    lose its number while still open would silently opt out of the one-open-request
    guarantee.

    `subject_ref` is NOT NULL and a BEFORE INSERT trigger derives it from the number when
    a writer does not supply one, so the hash cannot drift from the number and no INSERT
    written before the column existed becomes a failure. The application still writes it
    explicitly; the trigger fills, and never overwrites.
    """

    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NOT NULL OR phone_e164 IS NOT NULL",
            name="open_request_names_its_subject",
        ),
        CheckConstraint("subject_ref IS NOT NULL", name="subject_ref_not_null"),
        # At most ONE queued, unexecuted erasure per subject (migration e2c47b90d5a1).
        # Partial on purpose: erasure is not terminal for a phone number — the same
        # person can call the same client next month and exercise DPDP §12 again.
        # Declared with a predicate, so autogenerate cannot diff it; the migration is the
        # source of truth for its existence.
        Index(
            "uq_deletion_requests_open_subject",
            "tenant_id",
            "phone_e164",
            unique=True,
            postgresql_where=text("completed_at IS NULL"),
        ),
        Index("ix_deletion_requests_tenant_subject", "tenant_id", "subject_ref"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nullable ONLY after completion — see the CHECK above.
    phone_e164: Mapped[str | None] = mapped_column(Text)
    subject_ref: Mapped[str] = mapped_column(Text, nullable=False)
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
