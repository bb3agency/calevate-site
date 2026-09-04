"""KB tables (DATA-MODEL §7; D-28 narrowed them, D-502 restored `kb_chunks`).

The source, its versions and the approval gate are the part that stays ours whichever
provider serves retrieval, plus the chunk TEXT needed to preview what a client is about to
publish. `kb_chunks` is the RETRIEVAL PROJECTION over that text (D-502, migration
`dc1aaeeeff02`): it stores no content of its own, only the two derived keys and the scope a
query filters on.
"""

from datetime import datetime
from uuid import UUID

from calevate_shared.document_ingest import CONVERTIBLE_KINDS
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin
from apps.api.kb.gloss import GLOSS_PENDING, GLOSS_STATES
from apps.api.retrieval.embedding import EMBEDDING_DIMS

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
    __table_args__ = (
        UniqueConstraint("source_id", "idx"),
        CheckConstraint(f"gloss_state IN {GLOSS_STATES!r}", name="gloss_state_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: A short ENGLISH rendering of `content`, written once at ingestion by
    #: `apps/workers/kb_gloss.py` (migration `a7f4c31d95e8`).
    #:
    #: IT IS A RETRIEVAL KEY AND NEVER AN UTTERANCE. `retrieval/compiled_facts.py` scores
    #: it against a question and then returns the ORIGINAL line; nothing compiles it into a
    #: prompt, pushes it to the engine, or shows it to a caller. So a machine translation
    #: cannot widen what a client's agent may say — the human approved Telugu, the agent
    #: still says Telugu, and the gloss only changes whether a Tenglish question finds it.
    #: `kb/gloss.py` carries the measurement that justifies the column.
    gloss: Mapped[str | None] = mapped_column(Text)
    #: Which model wrote `gloss`. Provenance, so "machine-generated" is a checkable fact on
    #: the row rather than a convention — the preview screen marks the gloss from this.
    gloss_model: Mapped[str | None] = mapped_column(Text)
    #: `pending` / `ready` / `not_needed` (`kb/gloss.GLOSS_STATES`). THE IDEMPOTENCY KEY of
    #: the gloss sweep: `not_needed` is how an English chunk says "looked at, nothing owed",
    #: which `gloss IS NULL` cannot say and which is the difference between a sweep that
    #: converges and one that re-pays a model call for the same "no" on every tick.
    gloss_state: Mapped[str] = mapped_column(String, nullable=False, server_default=GLOSS_PENDING)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)


#: `kb_chunks.embed_state` — the sweep's idempotency key, as a closed vocabulary.
#:
#: `pending` nobody has embedded this yet · `ready` a vector is stored · `refused` the
#: provider answered and the answer was unusable (a width the column cannot hold, or an
#: empty array), which is a state a retry cannot fix and which must therefore not look like
#: `pending`. Without the third value the sweep would buy the same refusal on every tick
#: for ever — `kb_documents.gloss_state`'s argument, one column over.
EMBED_PENDING = "pending"
EMBED_READY = "ready"
EMBED_REFUSED = "refused"
EMBED_STATES: tuple[str, ...] = (EMBED_PENDING, EMBED_READY, EMBED_REFUSED)


class KbChunk(PKMixin, TimestampMixin, Base):
    """The retrieval projection of ONE published chunk (D-502). Holds no content.

    WHY IT IS A SEPARATE TABLE FROM `KbDocument`, in one line each — the migration
    `dc1aaeeeff02` carries the long form. (1) A row exists here only because
    `kb/service.publish_source` put it here for an APPROVED source, so the approval gate is
    structural rather than a predicate somebody must remember. (2) `agent_id` and
    `is_active` are denormalised off `kb_sources` so the scope predicate is ONE btree on ONE
    table — which is the plan `docs/evidence/kb-retrieval-bakeoff.md` §2.3(b) actually
    measured, and the reason the pre-0.8.0 filtered-scan hazard does not arise.

    **NO `content` COLUMN, DELIBERATELY.** The client's prose lives once, on `kb_documents`,
    and is reached through `document_id`. A second copy would double what retention and
    backups pay for, give a DPDP erasure two rows to find, and let a correction to one
    silently diverge from the other. Everything stored here is DERIVED and reconstructible.

    **ERASURE IS BY CASCADE HERE AND THAT IS SOUND, WHICH IS NOT TRUE OF EVERY SCOPE.** A
    cascade only erases when something is actually deleted, and `workers/retention.py`'s
    `_KB_EXPIRE_SQL` genuinely DELETEs `kb_sources` (its comment: "A DELETE, not an
    anonymize"), taking `kb_documents` and therefore these rows with it. The transcript
    scope is the opposite — a DPDP erasure SCRUBS a call in place and keeps the row as
    billing evidence, so a cascade there never fires. Any future embedding of caller data
    needs an explicit erasure arm, not this pattern.
    """

    __tablename__ = "kb_chunks"
    __table_args__ = (
        # ONE projection per chunk. What makes both the publish path and the backfill
        # idempotent through `ON CONFLICT` rather than a read-then-write, and what stops a
        # republished source accumulating duplicates that would each take a top-k slot.
        UniqueConstraint("document_id", name="uq_kb_chunks_document_id"),
        CheckConstraint(f"embed_state IN {EMBED_STATES!r}", name="ck_kb_chunks_embed_state_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False
    )
    #: The sparse key: the chunk's own text AND its English gloss, under one text-search
    #: configuration (`dc1aaeeeff02.TS_CONFIG`). A plain column rather than GENERATED
    #: because it is built from a JOIN — the gloss lives on `kb_documents` and a generated
    #: column may only read its own row.
    tsv: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    #: The dense key. NULLABLE by design: a chunk is searchable by its sparse arm the
    #: instant it is published and gains its dense arm when the sweep reaches it, so
    #: publishing never depends on a provider being up.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMS))
    #: Which model wrote `embedding`, and at what width. Provenance, and the thing a
    #: re-embedding sweep would compare against to find rows written by a superseded model.
    embed_model: Mapped[str | None] = mapped_column(Text)
    embed_dim: Mapped[int | None] = mapped_column(Integer)
    embed_state: Mapped[str] = mapped_column(String, nullable=False, server_default=EMBED_PENDING)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    #: Whether this projection is of the LIVE version of its source. `publish_source`
    #: archives a superseded version rather than deleting it (FLOWS §7 rollback), so the
    #: projection follows: the rows stay, addressable by a rollback, and are invisible to
    #: retrieval.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


#: `kb_uploads.source_kind`. The two kinds the ENGINE takes natively plus the conversion
#: lane's own `CONVERTIBLE_KINDS`, derived from it rather than retyped so a kind a reader
#: can serve and a kind this column can hold are one vocabulary — the drift that would
#: otherwise show up as an upload accepted at the door and unreadable in a worker.
UPLOAD_NATIVE_KINDS: tuple[str, ...] = ("pdf", "url")
UPLOAD_KINDS: tuple[str, ...] = (*UPLOAD_NATIVE_KINDS, *sorted(CONVERTIBLE_KINDS))

#: How far an upload has got. The last three are the VENDOR's own words for a knowledge
#: base, spelled the same way on purpose — the value a client reads is the value the engine
#: reported, not a paraphrase somebody has to keep in step (migration `b3f7c21ea940`).
UPLOAD_RECEIVED = "received"
UPLOAD_CONVERTING = "converting"
UPLOAD_CONVERSION_UNAVAILABLE = "conversion_unavailable"
UPLOAD_CONVERSION_FAILED = "conversion_failed"
UPLOAD_PROCESSING = "processing"
UPLOAD_PROCESSED = "processed"
UPLOAD_ERROR = "error"
UPLOAD_STATUSES: tuple[str, ...] = (
    UPLOAD_RECEIVED,
    UPLOAD_CONVERTING,
    UPLOAD_CONVERSION_UNAVAILABLE,
    UPLOAD_CONVERSION_FAILED,
    UPLOAD_PROCESSING,
    UPLOAD_PROCESSED,
    UPLOAD_ERROR,
)

#: The statuses a sweep should try again. `conversion_unavailable` is NOT here: no
#: converter is installed for that kind on this deployment, and retrying it on a timer
#: buys nothing but log lines until an operator installs one. `error` is not here either —
#: the engine or we refused this document, and the remediation is on the row.
UPLOAD_RETRYABLE: tuple[str, ...] = (UPLOAD_RECEIVED, UPLOAD_CONVERTING, UPLOAD_PROCESSING)


class KbUpload(PKMixin, TimestampMixin, Base):
    """The file, photograph or link behind ONE `kb_sources` version.

    1:1 with that version (`uq_kb_uploads_source`), because an upload IS a knowledge source
    — it is approved, versioned, published, superseded and expired by exactly the machinery
    pasted text is. What lives here is only what is true of an uploaded ORIGINAL: what kind
    it is, where the bytes are, what the engine was handed, and how far it got. The review
    state, the submitter and the live flag are `kb_sources`' columns and are NOT copied.

    **NO `rag_id` COLUMN.** The vendor mints two identifiers and only the one an agent
    references (`vector_id`) is stored, in `engine_kb_routes.engine_kb_ref` — migration
    `f1c9e0a73b46` took that decision and its reason holds here: a second vendor identifier
    above the adapter is a vendor payload shape crossing hard rule 2's wall, and it is
    recoverable at the one call site that needs it.
    """

    __tablename__ = "kb_uploads"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_kb_uploads_source"),
        CheckConstraint(f"source_kind IN {UPLOAD_KINDS!r}", name="ck_kb_uploads_kind"),
        CheckConstraint(f"ingest_status IN {UPLOAD_STATUSES!r}", name="ck_kb_uploads_status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    #: Object-storage ref for what the CLIENT sent. NULL for a link — there is nothing of
    #: ours to store, the vendor scrapes the page itself.
    original_key: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    original_bytes: Mapped[int | None] = mapped_column(BigInteger)
    original_sha256: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    #: Object-storage ref for what the ENGINE is handed: the original when it is already a
    #: PDF, the converter's output otherwise, NULL for a link.
    document_key: Mapped[str | None] = mapped_column(Text)
    document_bytes: Mapped[int | None] = mapped_column(BigInteger)
    #: Hex SHA-256 of the document bytes — the publisher's re-upload guard, the same key
    #: `KBSourceRef.content_sha256` carries for a rendered document.
    document_sha256: Mapped[str | None] = mapped_column(Text)
    #: HOW the text was obtained (`parsed` / `ocr`) and BY WHAT — the reader's name, or
    #: the model id when a model read a photograph. Provenance, the argument
    #: `kb_documents.gloss_model` makes: "machine-generated" is worth nothing unless the
    #: row says which machine. `ocr` is also a GATE and not only a label: text a model read
    #: off a photograph is never auto-approved, whoever uploaded it.
    text_provenance: Mapped[str | None] = mapped_column(Text)
    extractor: Mapped[str | None] = mapped_column(Text)
    ingest_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=UPLOAD_RECEIVED
    )
    #: A sentence written for the CLIENT and rendered beside the row. Never a key, a path
    #: or a stack (hard rule 6).
    ingest_detail: Mapped[str | None] = mapped_column(Text)
    #: For a link: the digest of the page text as we last read it, and the two clocks that
    #: make the re-scrape sweep idempotent and auditable. What the engine indexes is still
    #: what the engine scrapes; this is change detection and nothing else.
    content_digest: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None]
    change_detected_at: Mapped[datetime | None]


class KbRetrievalLog(PKMixin, Base):
    """Powers the knowledge-gap report (TRD §6): T4 misses are what a client should add
    next. Stores the QUERY, never the caller — it is a content signal, not a call record.

    **GAP (2026-08-11): nothing writes this table, and nothing can yet.** Recorded here
    rather than in a ticket because the table is the only thing that outlives the
    discussion. In-call retrieval happens inside the engine (D-33), and neither surface
    the engine gives us reports an outcome: `CallEvent` is call lifecycle,
    `ExecutionSnapshot` is status/cost/recording/transcript. No query, no tier, no
    score. Whether the engine can ever report one is pilot gate 8.

    The substitute — inferring a miss from a post-call transcript — is refused on two
    counts: `query` would hold raw caller utterances in a table with no `text_redacted`
    counterpart (hard rule 5), and `tier`/`top_score`/`latency_ms` would carry invented
    values for a retrieval we did not perform. The reader is deferred for a third
    reason: TRD §6 puts knowledge-gap analysis on the managed RAG/memory service, whose
    provider is blocked behind the D-28 bake-off gate.

    Closing it: a producer becomes possible when pilot gate 8 shows the engine reporting
    retrieval outcomes, or when the D-28 provider serves in-call retrieval and we see
    the queries ourselves. `tests/kb_tiers_test.py` fails the day either lands.
    """

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
