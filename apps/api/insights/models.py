"""Knowledge-gap tables: the aggregate a client acts on, and the per-call provenance
that makes its counts auditable and idempotent (DATA-MODEL §1 conventions).

TWO TABLES, and the split is the same one `crm.CallEngineLatency` makes about samples vs
aggregates: `knowledge_gap_occurrences` is one row per (call, topic) — the raw evidence,
re-derivable from the transcript — and `knowledge_gaps` is the roll-up per (agent, topic)
that the dashboard reads. The aggregate is a pure function of the occurrences, so a
re-processed call REPLACES its own occurrence rows and the aggregate is recomputed from
what survives; nothing is ever double-counted (see `service.record_call_gaps`).

NEITHER IS APPEND-ONLY (hard rule 4), deliberately, and the reason is the same as the key
moments migration's: both hold DERIVED data, not a record that something happened. An
occurrence is an index into a transcript we still hold; the aggregate is a running tally
the client mutates (dismiss/teach). The immutable trail of those mutations is `audit_log`,
where every other client mutation in this repo records itself — not a second copy here.

BOTH CARRY `tenant_id` AND GET THE FORCEd `tenant_isolation` POLICY in the same migration
(hard rule 1). The quote columns hold REDACTED text only (hard rule 6) — the detector is
handed `transcript_turns.text_redacted` and never the raw turn, so no raw-PII path reaches
these rows.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: How the caller's unanswered moment was recognised. A closed set, spelled here as the
#: DB's copy of the `Literal` in `detection.py` — annotated so a typo is a mypy error on
#: the line that makes it, exactly as `crm.models.CALL_STATUSES` is (that file argues why).
#:
#: - `dont_know`           the agent stated it could not answer ("I don't know", "teliyadu")
#: - `deferred_channel`    the agent punted to WhatsApp / a human callback instead of answering
#: - `unanswered_question` a direct caller question the agent never actually answered
GAP_SIGNALS: tuple[str, ...] = ("dont_know", "deferred_channel", "unanswered_question")

#: The lifecycle of a gap. `open` is the urgent, dashboard-visible state; `taught` and
#: `dismissed` are both terminal client decisions and drop off the urgent surface.
GAP_STATUSES: tuple[str, ...] = ("open", "taught", "dismissed")


class KnowledgeGapOccurrence(PKMixin, TimestampMixin, Base):
    """One (call, topic) the agent could not answer — the provenance behind one count.

    UNIQUE (tenant_id, call_id, topic_key) is the whole idempotency guarantee: a call
    contributes at most one row per topic, so re-processing the call DELETEs its rows and
    re-inserts, and the aggregate recomputes from the survivors. `tenant_id` leads the key
    for `crm.CallExtraction`'s reason — under FORCEd RLS a unique violation is only ever
    reachable against a row of your own.

    `hit_count` is how many times the topic surfaced IN THIS CALL, so the aggregate can
    say "3x on 2 calls" (occurrences ≠ calls) rather than collapsing to one number.
    """

    __tablename__ = "knowledge_gap_occurrences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id", "topic_key"),
        CheckConstraint(f"signal IN {GAP_SIGNALS!r}", name="signal_enum"),
        CheckConstraint("hit_count >= 1", name="hit_count_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # CASCADE, unlike the calls this repo keeps for billing evidence: an occurrence is a
    # derived index into a transcript, so when a DPDP erasure or offboarding removes the
    # call it is describing, the index must go with it rather than orphan.
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_key: Mapped[str] = mapped_column(Text, nullable=False)
    topic_label: Mapped[str] = mapped_column(Text, nullable=False)
    #: The caller's question and the agent's deflection, REDACTED (hard rule 6). These are
    #: the caller-facing quotes the card renders; they are never the raw turn text.
    question_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    answer_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    signal: Mapped[str] = mapped_column(String, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class KnowledgeGap(PKMixin, TimestampMixin, Base):
    """The roll-up per (tenant, agent, topic) — what the dashboard urgent card reads.

    Every count on this row is DERIVED from `knowledge_gap_occurrences` and recomputed
    under a row lock on every write (`service._recompute_aggregate`), so two calls of the
    same topic finishing at once cannot lose an update. `status` is the ONE field the
    recompute never touches — it belongs to the client (dismiss/teach) and a recurrence
    must not silently re-open a gap they deliberately closed.
    """

    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "topic_key"),
        CheckConstraint(f"status IN {GAP_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"top_signal IN {GAP_SIGNALS!r}", name="top_signal_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    topic_key: Mapped[str] = mapped_column(Text, nullable=False)
    topic_label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="open")
    #: SUM(hit_count) across occurrences — the "Nx". Never below `call_count`.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: COUNT(occurrences) — the "on M calls". One occurrence row per call by construction.
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: The most recent occurrence's quotes — what the card shows. Redacted (hard rule 6).
    example_question_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    example_answer_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    #: The signal on the most recent occurrence, for the badge wording.
    top_signal: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Set when the client acts. `resolution` is the free-text answer they taught (or a
    #: dismissal note); `resolved_by`/`resolved_at` are who and when. All NULL while open.
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None]
    #: The draft KB source seeded from a "teach" action, when one was created. A plain UUID
    #: rather than an FK: the KB module owns `kb_sources` and a hard FK would couple this
    #: table's lifetime to another module's (the same call `crm.Lead.first_call_id` makes).
    kb_source_id: Mapped[UUID | None]


__all__ = ["GAP_SIGNALS", "GAP_STATUSES", "KnowledgeGap", "KnowledgeGapOccurrence"]
