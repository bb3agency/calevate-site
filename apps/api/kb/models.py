"""KB tables (DATA-MODEL §7, narrowed by D-28/D-33).

`kb_chunks` with its `vector(1024)` column and HNSW index is NOT created here: D-28
moved retrieval to a managed service and made those tables contingency. What we build
is the part that stays ours whichever provider wins — the source, its versions, and the
approval gate — plus the chunk TEXT needed to preview what a client is about to publish.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

KB_KINDS = ("file", "url", "text", "call_corpus")
KB_STATUSES = ("uploaded", "parsed", "pending_approval", "approved", "rejected", "archived")


class KbSource(PKMixin, TimestampMixin, Base):
    """One thing a client wants their agent to know, at one version.

    Versioning is why `status` and `version` live together: publishing a new version
    archives the previous one rather than editing it, so rollback is reactivating a row
    (FLOWS §7) instead of restoring a backup.
    """

    __tablename__ = "kb_sources"
    __table_args__ = (
        CheckConstraint(f"kind IN {KB_KINDS!r}", name="kind_enum"),
        CheckConstraint(f"status IN {KB_STATUSES!r}", name="status_enum"),
        UniqueConstraint("agent_id", "name", "version"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="uploaded")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Who approved it, and when it went live — the two questions a dispute asks.
    approved_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    approved_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    submitted_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class KbDocument(PKMixin, TimestampMixin, Base):
    """A chunk of a source, stored as TEXT for preview and for the dual-push payload.

    No embedding column, by decision (D-28). `meta` carries provider-side document /
    namespace ids so a row can be traced into whichever managed service holds the
    vectors — and so a DPDP deletion can prove it removed both copies.
    """

    __tablename__ = "kb_documents"
    __table_args__ = (UniqueConstraint("source_id", "idx"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class KbRetrievalLog(PKMixin, Base):
    """Powers the knowledge-gap report (TRD §6): T4 misses are what a client should add
    next. Stores the QUERY, never the caller — it is a content signal, not a call record."""

    __tablename__ = "kb_retrieval_logs"
    __table_args__ = (CheckConstraint("tier IN ('t0','t1','t2','t3','t4')", name="tier_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    top_score: Mapped[float | None]
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
