"""Calls, transcripts, extractions, leads (DATA-MODEL sections 4-5).

Cross-links: calls.lead_id is a real FK; leads.first_call_id/last_call_id are plain
UUIDs (denormalized pointers maintained by the pipeline — a second FK pair would be
circular). campaign_id stays a plain UUID until the campaigns table lands in M2.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from calevate_shared.carrier import CARRIERS
from calevate_shared.events import CallDirection, CallStatus, Speaker
from calevate_shared.extraction import (
    LEGACY_OUTCOME_TAGS,
    OUTCOME_HINTS,
    OutcomeTag,
    Sentiment,
)
from calevate_shared.worker_api import DEGRADED_KNOWLEDGE_STATES, KNOWLEDGE_STATES
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    column,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.crm.schemas import LeadStatus
from apps.api.db.base import Base, PKMixin, TimestampMixin

# EVERY TUPLE BELOW IS ANNOTATED WITH THE TYPE ITS MEMBERS ARE, and that is the whole
# guard. Each one is interpolated into a `CheckConstraint` below, so it is the DATABASE's
# copy of a vocabulary whose other copy is a `Literal` — `calevate_shared.events`,
# `calevate_shared.extraction`, `crm.schemas`. Unannotated they infer `tuple[str, ...]`,
# which means a typo ("no_ansewr") or an invented member ("abandoned") produced a CHECK
# the API's Literal did not name, and nothing said a word: the two halves only met at
# runtime, where Postgres refuses the row or Pydantic refuses the response. Annotated,
# the mistake is an error on the line that makes it.
#
# The annotation catches a WRONG member, not a MISSING one — a shorter tuple is still a
# valid `tuple[X, ...]`. Completeness is pinned behaviourally where it matters
# (`tests/dashboard_daily_test.py` walks `CALL_STATUSES` against the classifier).
CALL_DIRECTIONS: tuple[CallDirection, ...] = ("inbound", "outbound")
CALL_STATUSES: tuple[CallStatus, ...] = (
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
OUTCOME_TAGS: tuple[OutcomeTag, ...] = (
    "call_back_booked",
    "needs_you",
    "answered",
    "transferred",
    "hung_up_early",
    "missed",
)
#: What the `calls` CHECK admits: the current words and, for one release, the words stored
#: before 10 Oct 2026 (hard rule 8, migration c4e8a1f7d290). Nothing writes a legacy word.
STORED_OUTCOME_TAGS: tuple[str, ...] = (
    *LEGACY_OUTCOME_TAGS,
    *(tag for tag in OUTCOME_TAGS if tag not in LEGACY_OUTCOME_TAGS),
)
SUMMARY_SOURCES = ("engine", "extraction")
#: `pending` the pipeline has not written one yet; `ready` there is a summary; `failed` the
#: model failed and the engine wrote none; `empty` the call had nothing to summarise.
SUMMARY_STATES = ("pending", "ready", "failed", "empty")
#: `unavailable` is a call from before turns were translated (migration c4e8a1f7d290).
TRANSLATION_STATES = ("pending", "ready", "failed", "not_needed", "unavailable")
LEAD_STATUS_SETTERS = ("system", "person")
SENTIMENTS: tuple[Sentiment, ...] = ("positive", "neutral", "negative")
SPEAKERS: tuple[Speaker, ...] = ("agent", "caller")
LEAD_SOURCES = ("inbound_call", "webhook", "campaign", "manual", "test_call", "outbound_call")
LEAD_STATUSES: tuple[LeadStatus, ...] = (
    "new",
    "contacted",
    "interested",
    "hot",
    "won",
    "lost",
)  # fixed enum, D-21
# `assignment` is a MEMBER rather than another `note` kind, and the choice is not
# cosmetic. The precedent that governs is `status_change`, not the `note` reuse in
# `ingest/service.py`: both are "a person changed a field on the lead", and modelling
# one of them as a type while the other hides inside a payload discriminator would be
# two ways of recording one shape of event. The ingest reuse exists because "blocked"
# has no natural member here AND that milestone shipped no migration — this slice ships
# one anyway (the assignee index), so the member costs nothing extra. Widening a CHECK
# is additive, so hard rule 8's two-step deprecation does not apply (migration
# d2b6f04a17c9).
LEAD_EVENT_TYPES = ("status_change", "note", "call", "notification", "assignment")


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
            f"outcome_tag IS NULL OR outcome_tag IN {STORED_OUTCOME_TAGS!r}",
            name="outcome_enum",
        ),
        CheckConstraint(
            "(business_outcome IS NULL) = (business_outcome_label IS NULL)",
            name="business_outcome_labelled",
        ),
        CheckConstraint(
            f"summary_source IS NULL OR summary_source IN {SUMMARY_SOURCES!r}",
            name="summary_source_enum",
        ),
        CheckConstraint(f"summary_state IN {SUMMARY_STATES!r}", name="summary_state_enum"),
        CheckConstraint(
            f"translation_state IN {TRANSLATION_STATES!r}", name="translation_state_enum"
        ),
        CheckConstraint("headline IS NULL OR char_length(headline) <= 90", name="headline_length"),
        CheckConstraint(f"sentiment IS NULL OR sentiment IN {SENTIMENTS!r}", name="sentiment_enum"),
        CheckConstraint(
            f"knowledge_state IS NULL OR knowledge_state IN {tuple(sorted(KNOWLEDGE_STATES))!r}",
            name="knowledge_state_enum",
        ),
        CheckConstraint(f"carrier IS NULL OR carrier IN {CARRIERS!r}", name="carrier_enum"),
        # An opaque carrier id and never a bare digit run (hard rule 6), the rule
        # `processor_erasure_tasks.vendor_refs` keeps (migration b3e9c4a71f20, D-668).
        CheckConstraint(
            "carrier_recording_id IS NULL OR ("
            "carrier_recording_id ~ '^[A-Za-z0-9_-]{1,128}$' "
            "AND carrier_recording_id !~ '^[0-9]{7,}$')",
            name="carrier_recording_id_shape",
        ),
        # What the voice platform charged, never negative (migration f3b8d1e5a7c2).
        CheckConstraint(
            "engine_charged_inr IS NULL OR engine_charged_inr >= 0",
            name="engine_charged_inr_not_negative",
        ),
        CheckConstraint(
            "engine_quality IS NULL OR call_quality_is_numeric(engine_quality)",
            name="engine_quality_is_numbers",
        ),
        # Recordings the carrier reported and we have not copied yet: the copy sweep's
        # worklist (`workers/carrier_recordings`), a handful of rows at any moment.
        Index(
            "ix_calls_recording_uncopied",
            "tenant_id",
            "created_at",
            postgresql_where=text("carrier_recording_id IS NOT NULL AND recording_url IS NULL"),
        ),
        # Copied recordings whose carrier copy is not yet deleted: the one-day expiry
        # sweep's worklist (migration c5d82f1a9e47).
        Index(
            "ix_calls_carrier_recording_undeleted",
            "tenant_id",
            "created_at",
            postgresql_where=text(
                "carrier_recording_id IS NOT NULL AND recording_url IS NOT NULL "
                "AND carrier_recording_deleted_at IS NULL"
            ),
        ),
        # Calls whose content deletion at the voice platform is queued and not yet settled:
        # the backstop's worklist (`workers/engine_customer_data`, migration e4b7d2a9c160).
        Index(
            "ix_calls_engine_content_owed",
            "tenant_id",
            "engine_content_delete_requested_at",
            postgresql_where=text(
                "engine_content_delete_requested_at IS NOT NULL "
                "AND (engine_content_deleted_at IS NULL OR engine_content_recordings_pending > 0)"
            ),
        ),
        CheckConstraint(
            "engine_content_recordings_pending IS NULL OR engine_content_recordings_pending >= 0",
            name="engine_content_recordings_pending_nonnegative",
        ),
        # The complaint-spike check (`campaigns/complaint_spike.py`, OPERATIONS §4) is
        # the first thing in this repo to filter calls by campaign, and it runs once per
        # running campaign per 30-second dispatch tick. PARTIAL because inbound calls
        # belong to no campaign and are the majority of this table; `started_at` is in
        # the key because the check only ever looks at a rolling window.
        Index(
            "ix_calls_campaign_started",
            "campaign_id",
            "started_at",
            postgresql_where=text("campaign_id IS NOT NULL"),
        ),
        # A DPDP ERASURE FINDS ITS SUBJECT'S CALLS BY PHONE, AND HAD NO INDEX TO DO IT
        # WITH. `execute_deletion_request` selects
        # `WHERE from_e164 = :phone OR to_e164 = :phone OR erased_subject_ref = :ref`;
        # only the third column was indexed, so an OR that Postgres would otherwise serve
        # as a BitmapOr of three index scans degraded to a sequential scan of every call
        # the platform holds. That is the one query in this repository with a statutory
        # clock on it (DPDP §12), and it got slower with every call ever placed.
        #
        # PARTIAL, and the predicate is the erasure's own postcondition: both columns are
        # set to NULL when a subject is erased, so `IS NOT NULL` excludes exactly the rows
        # a later erasure can never match again. The index therefore holds live callers
        # only and shrinks as erasures are discharged.
        Index(
            "ix_calls_from_e164",
            "from_e164",
            postgresql_where=text("from_e164 IS NOT NULL"),
        ),
        Index(
            "ix_calls_to_e164",
            "to_e164",
            postgresql_where=text("to_e164 IS NOT NULL"),
        ),
        # Calls of the former owned runtime that answered without their knowledge (migration
        # e2a91c7f45b8). PARTIAL over the four failure states; kept with the column.
        Index(
            "ix_calls_knowledge_degraded",
            "agent_id",
            "created_at",
            # An EXPRESSION and not `text()`: the predicate names a set that lives in the
            # wire vocabulary, and splicing it into a SQL string would be the untraceable
            # fragment `check_raw_sql` refuses (D-172). `in_()` renders the members itself.
            postgresql_where=column("knowledge_state").in_(sorted(DEGRADED_KNOWLEDGE_STATES)),
        ),
        # The trial line and the daily cap count a tenant's recent test calls (D-697).
        Index(
            "ix_calls_trial_recent",
            "tenant_id",
            "created_at",
            postgresql_where=text("trial_call"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_call_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    #: OUR FORMER CARRIER'S OWN ID FOR THIS CALL (migration c7f1a9d4e620), a different vendor's
    #: identifier from `engine_call_id`. It exists for the erasure we cannot perform
    #: ourselves: a written request to the carrier has to name the calls by its own id.
    #:
    #: No longer written; it was set once per call (first value wins), and is
    #: read by both erasures, which quote it in the `telephony` task.
    #: Nullable because calls that predate the carrier leg have no such id and never will — a
    #: backfill would be inventing identifiers. It is deliberately NOT cleared by any erasure
    #: arm: it names a row in somebody else's system rather than describing a person, and
    #: destroying the only handle on a copy we are obliged to have erased is the failure
    #: `recording_erasure_holds` exists to prevent.
    carrier_call_id: Mapped[str | None] = mapped_column(Text)
    #: The former carrier that held this call's leg (migration f5c2a8e41d07). No longer
    #: written; kept for historical rows until the column is dropped (hard rule 8).
    carrier: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    from_e164: Mapped[str | None] = mapped_column(Text)
    to_e164: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    duration_s: Mapped[int | None] = mapped_column(Integer)
    recording_url: Mapped[str | None] = mapped_column(Text)  # OUR storage, never engine's
    # THE SECOND RECORDING — the transferred leg, when this call was handed to a person
    # (D-533, migration b8d1f04c73a9). OUR object key on the same terms as the column
    # above: same bucket, same `recordings/` prefix, same retention clock, cleared by the
    # same sweep and the same erasure. NULL on every call that never handed over, which is
    # almost all of them.
    transfer_recording_url: Mapped[str | None] = mapped_column(Text)
    #: Our former carrier's id for its recording of this call (D-668), quoted at the carrier by
    #: an erasure. No longer written. Never a URL; `recording_url` is our copy.
    carrier_recording_id: Mapped[str | None] = mapped_column(Text)
    #: When our copy of the carrier's recording was stored, and when the carrier confirmed
    #: its own copy deleted, one day later (migration c5d82f1a9e47).
    recording_copied_at: Mapped[datetime | None]
    carrier_recording_deleted_at: Mapped[datetime | None]
    #: The voice platform's copy of this call's content (recording, transcript, summary,
    #: collected fields): when we queued its deletion, when the platform said it was
    #: deleted, and how many recording files it still retries (migration e4b7d2a9c160).
    engine_content_delete_requested_at: Mapped[datetime | None]
    engine_content_deleted_at: Mapped[datetime | None]
    engine_content_recordings_pending: Mapped[int | None] = mapped_column(Integer)
    disclosure_played: Mapped[bool | None] = mapped_column(Boolean)
    consent_recording: Mapped[str | None] = mapped_column(String)
    #: The client-facing outcome, DERIVED from facts by `crm/outcomes.derive_outcome`.
    outcome_tag: Mapped[str | None] = mapped_column(String)
    #: What the call came to for THIS business (D-836): the key of the agent's outcome the
    #: extraction model chose, and its label as it read then, so an owner's later rename or
    #: removal never rewrites a past call. Both NULL, or both set.
    business_outcome: Mapped[str | None] = mapped_column(Text)
    business_outcome_label: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String)
    #: The English summary. Precedence (`workers/pipeline._summaries`): the engine's own
    #: when it is written in Latin script, else the extraction model's.
    summary: Mapped[str | None] = mapped_column(Text)
    #: The same summary in the call's language (`summary_language`, BCP-47), for the
    #: "show in Telugu" toggle. NULL for an English call or when none could be written.
    summary_local: Mapped[str | None] = mapped_column(Text)
    summary_language: Mapped[str | None] = mapped_column(Text)
    #: Who wrote `summary`: `engine` or `extraction`.
    summary_source: Mapped[str | None] = mapped_column(Text)
    summary_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    #: One line for the call list (at most 90 characters), and what the business should do
    #: next. Model prose about the call, STORED REDACTED because the lead list shows it too.
    headline: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[str | None] = mapped_column(Text)
    #: The caller asked to be called back (the extraction's reading), booked or not.
    callback_requested: Mapped[bool | None] = mapped_column(Boolean)
    #: Whether `transcript_turns.text_en` has been written for this call.
    translation_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    #: HAS THE CROSS-CALL MEMORY DISTILLER LOOKED AT THIS CALL, AND WHAT DID IT DECIDE?
    #: `pending` / `remembered` / `nothing` / `skipped` — `compliance.caller_memory.
    #: CALLER_MEMORY_STATES`, and the CHECK in migration `a1f6c30d92be`.
    #:
    #: THE THIRD STATE IS WHY THE COLUMN EXISTS (D-513): `caller_memories.source_call_id`
    #: can say "this call produced a fact" and can never say "this call was read and owed
    #: nothing", which is what most calls owe — so without a durable negative every retry
    #: re-buys the same answer. `kb_documents.gloss_state` is the same shape for the same
    #: reason.
    caller_memory_state: Mapped[str] = mapped_column(
        String, nullable=False, server_default="pending"
    )
    #: Whether a call of the former owned runtime had its client's knowledge (migration
    #: e2a91c7f45b8; `calevate_shared.worker_api.KnowledgeState`). No longer written; NULL on
    #: every engine call. Kept until the column is dropped (hard rule 8).
    knowledge_state: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))  # FK lands M2
    #: A free-trial test call (D-697), placed from the shared trial number. What the trial's
    #: daily cap, its free minutes and the one-test-call-at-a-time line count.
    trial_call: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    #: The forwarding test this inbound call was (D-746): its minutes are ours, it files no lead.
    forwarding_test_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("forwarding_tests.id", ondelete="SET NULL")
    )
    #: A forwarded call that showed the client's own published number instead of the
    #: caller's (D-746): the lead is filed under the call-back number the caller gave.
    caller_id_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    #: The engine put this call through to a phone with a number forward, so no agent took it
    #: and there is no recording (D-835). Unrelated to `caller_id_hidden`, which is a call
    #: the client's own phone forwarded TO an agent.
    forwarded_to_phone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    # D-21 M2: the call this one follows up. Bounds the callback chain — see migration
    # efb47868ec59 for why an unbounded one is a compliance problem, not a UX one.
    callback_of_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="RESTRICT")
    )
    # No `latency` column. It was declared here to hold {stt_ms, llm_ttft_ms, tts_ttfa_ms,
    # turn_p50, turn_p95}, was never written by anything, and is dropped in migration
    # f1a7c39d5be2 — the in-call audio path runs inside the rented engine, so nothing we
    # trace is inside it, and the vendor's own per-component timings are neither the same
    # numbers nor validated against a stopwatch yet (D-39(b)). The migration's docstring
    # holds the full argument and what re-opens it at pilot gate 4.
    # When the outbound CRM fan-out (D-23) was promised for this call — the fact the
    # pipeline and the poller used to reconstruct by containment-scanning the whole
    # outbox, twice per call, under the per-call lock (P6.7, migration e83b5d1a4c07).
    # Both askers already hold this row, so the question now costs nothing. NULL means
    # "not yet", and that is also the correct answer for a tenant with no subscribed
    # endpoint — `_expected_artifacts` decides whether one was OWED, which is a
    # different question and stays where it is.
    crm_notified_at: Mapped[datetime | None]
    engine_payload_ref: Mapped[str | None] = mapped_column(Text)  # raw vendor payload (debug only)
    #: What the voice platform says it charged for this call, in rupees, set once when it
    #: settles (ThinnestAI `costMicro`). A reconciliation input, never `unit_cost_paid`
    #: (hard rule 7): `workers/engine_charges.reconcile_call_charge`.
    engine_charged_inr: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    #: How the call went as the voice platform measured it once it ended
    #: (`calevate_shared.events.CallQuality`, dumped): reply times, silences, interruptions,
    #: model errors and backup answers, each NULL when not measured. Numbers only, which the
    #: CHECK of migration a5d1c7e93f28 enforces. NULL until the platform reports it.
    engine_quality: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    # The one-way handle a DPDP erasure leaves behind when it clears this row's numbers
    # (D-310, migration c1e9a4f7d302). Without it an erased call is orphaned from its
    # subject forever — the two phone columns were the only join — so records that arrive
    # for that call AFTER the certificate (a call still in flight when the erasure ran)
    # could never be reached by the same person's standing instruction. Same construction
    # as `deletion_requests.subject_ref`, for the same reason.
    erased_subject_ref: Mapped[str | None] = mapped_column(Text)
    # The instant the big red switch asked the vendor to drop this dial before it rang
    # (D-432, migration d5c81f30ab47). NULL means never asked, which is the right reading
    # for every row written before the recall existed.
    #
    # THE JOB DOES NOT SETTLE THE CALL, and this column is what makes that affordable: the
    # reconciliation poller is the guarantee of record (D-31), so the row stays `queued`
    # until the poller closes it, and this stamp is the only thing that keeps a second
    # halt from re-POSTing a stop for every dial already stopped -- and then raising
    # "could not stop N dials" on work that succeeded.
    recall_requested_at: Mapped[datetime | None]


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
    #: The turn in English, translated after the call FROM `text_redacted`, so it is
    #: redacted like it and served on the default view. NULL when the turn was already
    #: English or nothing translated it. The original stays the record.
    text_en: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    #: `start_ms` is a rough position, not a point in the audio (ThinnestAI's turn time is
    #: when the line was written down). e2b8c4d17a63.
    start_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())


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
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id"),
        CheckConstraint(
            f"outcome_hint IS NULL OR outcome_hint IN {OUTCOME_HINTS!r}",
            name="outcome_hint_enum",
        ),
    )

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
    #: The model's own reading of the conversation (`OutcomeHint`) and whether the caller
    #: asked for something the agent could not handle. Kept so a re-drive derives the same
    #: `calls.outcome_tag` without paying for the model again.
    outcome_hint: Mapped[str | None] = mapped_column(Text)
    #: The key of the agent's business outcome the model chose (D-836), kept for the same
    #: re-drive reason as `outcome_hint`.
    business_outcome: Mapped[str | None] = mapped_column(Text)
    out_of_scope: Mapped[bool | None] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    errors: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: Key moments — `[{at_ms, kind, label, label_redacted, source}]` (f8c1d47a90e3).
    #: NULL and `[]` differ and both are real: NULL is "nobody has looked at this call",
    #: `[]` is "we looked and it had none". Erased with `data` by all three sweeps in
    #: `workers/retention.py` — a marker outliving the extraction it indexes would be a
    #: second copy of erased data under a column nobody thought of.
    moments: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    #: Per-field "confirm before acting" advisories — `{field_key: reason}` (e7c2f9a41d38).
    #: Distinct from `errors` (which drives `valid`): a needs-review field is stored and
    #: usable, it just carries a deterministic doubt — today a dial-critical field (a phone)
    #: whose captured value is not a standard Indian mobile. PII-FREE by construction (the
    #: value lives in `data`; the reason names only the field). NULL/`{}` differ as they do
    #: for `moments`, and it is erased with `data` by all three sweeps in
    #: `workers/retention.py` for the same reason a marker must not outlive its extraction.
    needs_review: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: WHEN WE DESTROYED THIS ROW'S CONTENTS — never when the agent captured nothing
    #: (migration f2a6d81b39c4). `data = '{}'` is written both by an extraction that found
    #: nothing and by all three sweeps in `workers/retention.py` that empty one, and the
    #: two facts are opposites: the weekly knowledge digest reads this column to answer
    #: "which required fields does the agent keep missing", and without the marker a
    #: tenant whose lead retention is shorter than the digest window was told a working
    #: agent had missed a field on calls where it had not. Stamped by the scrubber in the
    #: same UPDATE that empties `data`; NULL means "not scrubbed", which is also the
    #: honest reading for every row written before the column existed.
    scrubbed_at: Mapped[datetime | None]


class Lead(PKMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", "agent_id"),
        CheckConstraint(f"source IN {LEAD_SOURCES!r}", name="source_enum"),
        CheckConstraint(f"status IN {LEAD_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"status_set_by IN {LEAD_STATUS_SETTERS!r}", name="status_set_by_enum"),
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
    #: Who last moved `status`: `person` (a screen, the copilot, a bulk action) or `system`
    #: (the after-call rules). The rules never move a status a person set.
    status_set_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    status_set_at: Mapped[datetime | None]
    # keys per extraction schema version
    data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    schema_version: Mapped[int | None] = mapped_column(Integer)
    first_call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    last_call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_repeat_caller: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None]


class LeadSavedView(PKMixin, TimestampMixin, Base):
    """A named filter+column combination, PRIVATE to the user who saved it (SURFACES §2).

    **Why a table and not a column on `memberships`.** A person keeps several of these
    ("Hot this week", "Unassigned walk-ins"), each with a name and its own lifetime, so
    the cardinality is per-user-per-tenant-per-VIEW and a JSONB blob on the membership
    would be a list nobody can constrain, index or delete a single element of.

    **Private only, and the table says so by having no visibility column.** Shared views
    are a separate slice with a separate question — who may edit a view three colleagues
    depend on, and what happens to their screens when someone does. The industry default
    is private-unless-explicitly-shared (Tableau custom views, SeaTable private views),
    and private-first is the only version that cannot leak: there is no shared row here
    to get a permission wrong on. Adding `visibility` later is an additive migration.

    **`user_id` is a plain FK to a GLOBAL table** (`users`, no RLS — DATA-MODEL §2), so
    it is `tenant_id` that isolates this row and `UNIQUE(tenant_id, user_id, name)` that
    scopes a name to one person on one account. Every read also filters `user_id`
    explicitly: RLS answers "which tenant", never "which person", and treating the
    policy as if it did is how one colleague's views would show up in another's picker.

    `filters` and `columns` are JSONB validated at the API boundary (`SavedViewFilters`,
    DATA-MODEL §10's stated pattern), because the whole content of a view is "whatever
    the extraction schema currently offers" and that is not a column list.
    """

    __tablename__ = "lead_saved_views"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "name"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: NO `index=True`, and its absence is the schema (D-192). Migration `a7e2c40d9b53`
    #: built `ix_lead_saved_views_tenant_user (tenant_id, user_id)` and no bare `user_id`
    #: btree, because every read of this table filters BOTH columns — the docstring above
    #: says so — and the composite serves that with one index. The model said `index=True`
    #: anyway, so `Base.metadata` declared an `ix_lead_saved_views_user_id` the database has
    #: never had and the next `--autogenerate` proposed creating it. Proven by
    #: `compare_metadata` against a database migrated from base to head: one `add_index`.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    #: NULL = "no column choice was made", which renders every column this agent has.
    #: An empty array would mean the same thing and is refused by the CHECK, so there is
    #: one spelling of the absence rather than two.
    columns: Mapped[list[str] | None] = mapped_column(JSONB)


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


class CallEngineLatency(PKMixin, TimestampMixin, Base):
    """Per-turn STT/LLM/TTS timings our former Pipecat loop reported for one call.

    **NOTHING WRITES OR READS THIS TABLE ANY MORE (D-770).** D-763 removed the Pipecat
    loop, the only producer; ThinnestAI reports per-call reply times instead, kept on
    `calls.engine_quality` and read by `apps/api/ops/reply_times.py`. The table and this
    model stay until a later release drops them (hard rule 8: never drop in the release
    that stops writing). Its rows are numbers only (the CHECK in `b7d3e91c4a05`), and
    `call_id` is `ON DELETE CASCADE`, so an erased call takes its row with it.
    """

    __tablename__ = "call_engine_latency"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: UNIQUE: one row per call. The post-call pipeline re-runs on every re-drive and the
    #: reconciliation poller can drive it a second time, so the write is an upsert onto
    #: this constraint — a second run must replace the measurement, never append a second
    #: one that would double every turn in the distribution.
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: OUR name for the adapter (`ExecutionSnapshot.engine`), never a vendor product name.
    #: Stored because the numbers are not comparable across engines and a distribution
    #: mixing two of them would be meaningless.
    engine: Mapped[str] = mapped_column(String, nullable=False)
    #: Where the engine says it ran (`in`, `us`, ...). NULL = it did not say. THE COLUMN
    #: THE GATE GROUPS BY — with it the geography question is a `GROUP BY`, without it the
    #: two pilot calls are two numbers nobody can attribute.
    region: Mapped[str | None] = mapped_column(String)
    #: End of the caller's utterance -> start of the agent's audio, as the ENGINE measures
    #: it. NUMERIC rather than float: it is compared and aggregated, and this repo does not
    #: keep two numeric habits.
    time_to_first_audio_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: `[{"turn": 1, "stt_ms": ..., "llm_ttft_ms": ..., "tts_ttfa_ms": ...}, ...]` —
    #: One object per turn, numbers only. An empty array is legitimate and
    #: means the engine returned a latency object with no readable turns in it;
    #: `parse_warnings` then says why, which is a different fact from "no object at all"
    #: (that writes no row).
    turns: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    #: What the adapter could not read, in OUR words — never a vendor message. NULL when
    #: the payload parsed cleanly, so a warning is visible as a warning rather than as an
    #: empty list nobody looks inside.
    parse_warnings: Mapped[list[str] | None] = mapped_column(JSONB)


#: What the voice platform reports about a call beside its result: a problem while it was
#: live (`calevate_shared.events.EngineProblemKind`) or a notice its agent raised.
CALL_ENGINE_SIGNAL_KINDS = (
    "conversation_escalated",
    "lead_captured",
    "no_answer_from_model",
    "own_key_failed",
    "slow_reply",
    "voice_failed",
)


class CallEngineSignal(PKMixin, TimestampMixin, Base):
    """One thing the voice platform reported about a call, at most once per kind per call
    (migration a5d1c7e93f28).

    Keyed by the platform's call id rather than a foreign key to `calls`: a problem arrives
    while an inbound call is still live, before we hold a row for it, and the call screen
    and the healer join on `calls.engine_call_id`. Kind and time only, never the platform's
    own sentence, so nothing a vendor writes is stored here.
    """

    __tablename__ = "call_engine_signals"
    __table_args__ = (
        CheckConstraint(f"kind IN {CALL_ENGINE_SIGNAL_KINDS!r}", name="kind_enum"),
        UniqueConstraint("tenant_id", "engine_call_id", "kind"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Our agent the platform names; on a handed call, the agent that raised it.
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    engine_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime | None]
