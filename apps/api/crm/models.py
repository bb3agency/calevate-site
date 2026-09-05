"""Calls, transcripts, extractions, leads (DATA-MODEL sections 4-5).

Cross-links: calls.lead_id is a real FK; leads.first_call_id/last_call_id are plain
UUIDs (denormalized pointers maintained by the pipeline — a second FK pair would be
circular). campaign_id stays a plain UUID until the campaigns table lands in M2.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from calevate_shared.events import CallDirection, CallStatus, Speaker
from calevate_shared.extraction import OutcomeTag, Sentiment
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
OUTCOME_TAGS: tuple[OutcomeTag, ...] = ("resolved", "needs_follow_up", "transferred", "dropped")
SENTIMENTS: tuple[Sentiment, ...] = ("positive", "neutral", "negative")
SPEAKERS: tuple[Speaker, ...] = ("agent", "caller")
LEAD_SOURCES = ("inbound_call", "webhook", "campaign", "manual")
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
            f"outcome_tag IS NULL OR outcome_tag IN {OUTCOME_TAGS!r}", name="outcome_enum"
        ),
        CheckConstraint(f"sentiment IS NULL OR sentiment IN {SENTIMENTS!r}", name="sentiment_enum"),
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
    # THE SECOND RECORDING — the transferred leg, when this call was handed to a person
    # (D-533, migration b8d1f04c73a9). OUR object key on the same terms as the column
    # above: same bucket, same `recordings/` prefix, same retention clock, cleared by the
    # same sweep and the same erasure. NULL on every call that never handed over, which is
    # almost all of them.
    transfer_recording_url: Mapped[str | None] = mapped_column(Text)
    disclosure_played: Mapped[bool | None] = mapped_column(Boolean)
    consent_recording: Mapped[str | None] = mapped_column(String)
    outcome_tag: Mapped[str | None] = mapped_column(String)
    sentiment: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
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
    campaign_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))  # FK lands M2
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
    """What the ENGINE says its own pipeline cost on one call, per turn.

    **THIS IS NOT `calls.latency` COMING BACK** (migration `f1a7c39d5be2` dropped that
    column, and `tests/call_latency_column_test.py` keeps it dropped). That column promised
    `turn_p50`/`turn_p95` — VOICE-TO-VOICE numbers, the interval between the caller
    finishing a word and the caller hearing audio. Both ends of that interval exist on the
    PSTN leg, our stack is not in the audio path (D-25/D-33), and nothing could ever have
    written it honestly. That is still true and this table does not change it.

    What this table holds is a different and genuinely observed quantity: the engine's own
    per-component timings, which it publishes per execution and which we used to throw
    away. It is a SEPARATE TABLE rather than columns on `calls` for exactly that reason —
    the name of the thing is "what the engine reported", and putting it on the call row
    would let the next reader read it as the call's latency.

    **WHY IT IS WORTH A TABLE NOW.** D-410 pinned the language model to South India while
    the engine's orchestrator stayed US-hosted
    (`bolna-findings/mirror/pages/concepts/security.md:29`), so every conversational turn
    paid a US->India->US round trip inside a 350ms budget (TRD §4). D-449 moved the
    deployment to `eastus2`, beside the orchestrator, on an argument rather than on a
    measurement — and gave up the India residency claim to do it. `llm_ttft_ms` per turn,
    grouped by `region`, is the measurement that was missing then and is still missing:
    two pilot calls, one on each geography, settle OPERATIONS §2 gate 4 by arithmetic
    instead of by argument. A trade made on an estimate is one that gets made twice.

    **ONE REPRESENTATION, NO AGGREGATES.** No stored p50, p95, breach count or turn count:
    every one of them is `jsonb_array_elements(turns)` away, and a denormalized statistic
    beside the samples it summarizes is a number that can disagree with its own evidence
    (the argument `quality.QaReport` makes about not storing rendered Markdown beside the
    computation). `apps/api/ops/engine_latency.py` is the one place the arithmetic lives.

    **NOTHING HERE IS PERSONAL DATA and the schema is what guarantees it** (hard rule 6).
    The vendor reports recognised caller speech beside these timings; `CallLatency` has no
    field for text, `turns` accepts only the four numeric keys, and the CHECK constraint in
    the migration refuses an array element that is not an object of numbers. A DPDP erasure
    still reaches this row the ordinary way — `call_id` is `ON DELETE CASCADE`, so the row
    cannot outlive the call it describes.
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
    #: `calevate_shared.engine.TurnLatency`, dumped. An empty array is legitimate and
    #: means the engine returned a latency object with no readable turns in it;
    #: `parse_warnings` then says why, which is a different fact from "no object at all"
    #: (that writes no row).
    turns: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    #: What the adapter could not read, in OUR words — never a vendor message. NULL when
    #: the payload parsed cleanly, so a warning is visible as a warning rather than as an
    #: empty list nobody looks inside.
    parse_warnings: Mapped[list[str] | None] = mapped_column(JSONB)
