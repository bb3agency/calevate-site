"""caller chunks: ONE retrieval projection over caller personal data

Revision ID: c6b1f0d47e83
Revises: 817842cf3b97
Create Date: 2026-09-01 00:00:00.000000

`caller_chunks` — the retrieval projection over the three CALLER-DATA scopes (D-503):
CRM leads, call transcripts and their summaries, and caller memory. `dc1aaeeeff02` built
the same shape for a client's own uploaded knowledge; this is the same shape pointed at
data that belongs to a data principal, and the whole of the difference is in the erasure
and retention seams below.

It also widens `platform_ai_usage` by one column so an operator-less caller (a cron) can
pay from the platform ledger honestly — see the last section.

--------------------------------------------------------------------------------
ONE TABLE WITH A DISCRIMINATOR, NOT THREE TABLES
--------------------------------------------------------------------------------
Three tables would be three erasure arms, three retention arms and three places to get
`embedding = NULL` right. The count of arms is the risk: `insights/service.
scrub_quotes_for_calls` exists because a SECOND copy of a caller's sentence was filed
under a table that no erasure path and no `DERIVED_COPIES` entry named, and it survived a
DPDP erasure for exactly as long as nobody looked. `subject_kind` makes that failure mode
structural instead of remembered — a new scope is a row in a registry and a value in a
CHECK, and it inherits the arms that already exist rather than needing its own.

--------------------------------------------------------------------------------
AN EMBEDDING OF A CALLER'S SENTENCE IS A COPY OF THAT SENTENCE
--------------------------------------------------------------------------------
This is the premise the whole table is built on and it is not a figure of speech: the
vector is DERIVED FROM the text by a deterministic function of it, and inversion attacks
against sentence embeddings are a published research result rather than a hypothetical.
It is not anonymous for being floats. So:

* every arm that scrubs a source row ALSO nulls the vector and empties the lexemes here.
  Scrubbing `transcript_turns.text` and leaving `caller_chunks.embedding` behind would
  leave the sentence on file in the one form nobody thinks to look at;
* `retention_category` is NOT NULL and CHECKed, because a table no retention category
  names never expires (`DERIVED_COPIES`' whole argument); and
* the table STORES NO CONTENT, exactly as `kb_chunks` does not. The source row is the one
  copy. What is here is two derived keys and the ids needed to reach the source.

**AND THE CASCADE IS NOT THE MECHANISM, WHICH IS THE TRAP THIS TABLE EXISTS AROUND.**
`kb_chunks` erases by `ON DELETE CASCADE` and that is sound there only because
`workers/retention._KB_EXPIRE_SQL` genuinely DELETEs `kb_sources`. A DPDP erasure does
NOT delete a call: it SCRUBS the call in place and keeps the row, because the call is
billing evidence (`calls` is referenced by `usage_events` under FK RESTRICT). So an
`ON DELETE CASCADE` on `call_id` NEVER FIRES, and a design that relied on it would ship a
projection that outlives every erasure that was supposed to reach it. The cascade is
declared anyway — it costs nothing and it is right for the paths that DO delete — but the
erasure arms in `apps/api/retrieval/caller_erasure.py` are what actually reach these rows,
and they are called explicitly from both erasure paths and from the nightly sweep.

--------------------------------------------------------------------------------
THE SUBJECT KEY IS A **KEYED** MAC, NOT `sha256(phone)` — AND THAT IS LOAD-BEARING
--------------------------------------------------------------------------------
`subject_ref` is `compliance/caller_ref.active_caller_ref` — `hmac-sha256(K, "caller-
memory/v1" ‖ tenant_id ‖ NUL ‖ E.164)[:32]` where `K` is HKDF-SHA-256 of `PLATFORM_KEK`
under its own `info` string. It is NOT `retention._hash` / `export.subject_ref`, and the
reason is written down in this repository twice already: that construction is
`sha256(phone)[:32]` with NO KEY, Indian mobile E.164 is a ~10^9 space anyone enumerates
in seconds, and `_erase_campaign_contacts` therefore CLEARS `campaign_contacts.
dedupe_hash` rather than leaving it — "leaving it is leaving the number in a form that
reverses". `calls.erased_subject_ref` gets away with the unsalted form because it is a
TOMBSTONE on a call whose personal data is already gone and nothing is filed under it.
Here things ARE filed under it, so a reversible key beside a durable fact about a person
is a re-identifiable profile with one `for` loop in front of it. `caller_ref.py` carries
the full argument; this table is its first store.

**UNIFORMLY, FOR EVERY `subject_kind`, and not only for caller memory.** The sibling that
wrote `caller_ref.py` asked for it on the memory kind; it is applied to all four because
every argument for it is an argument about THIS table rather than about that scope. A
lead's projection is durable too, its vector is a copy of the caller's own answer by this
migration's own first premise, and `sha256(phone)` carries no tenant in the MAC input — so
the same person ringing two of our clients would collide on one column, and a dump would
join two Fiduciaries' caller data on it. Two constructions in one column would also be the
drift CLAUDE.md forbids: an erasure predicate would have to try both, and the day somebody
forgets the second one the miss is silent and the certificate still says "removed".

`subject_ref_kek_id` rides beside it because a derived key ROTATES, and here a rotation is
an ERASURE hazard rather than a nuisance: a §12 request that derives the ref under the new
key while the rows were written under the old one matches nothing, and the certificate
then says "removed" over data that is still there. `caller_refs()` returns EVERY
generation so the predicate is `subject_ref = ANY(:refs)`, and `ring_covers(kek_id)` turns
"this deployment can no longer address those rows" into an alarm the nightly sweep raises
rather than a surprise. INTEGER and not TEXT, because `ActiveCallerRef.kek_id` is an `int`
(`core/envelope.KekRing`) and storing a stringified copy of a number is a second spelling
of one fact.

**THE ERASURE REACHES A ROW THREE WAYS, and all three are needed.** `subject_ref = ANY(
refs)` is the one that always works and is the only one caller memory has. `call_id` is
the belt for a projection whose ref was derived from the OTHER party's number on the same
call. `subject_kind = 'lead' AND subject_id = ANY(lead_ids)` is the belt for a lead whose
number an earlier sweep already anonymized.

--------------------------------------------------------------------------------
`subject_id` IS AN IDEMPOTENCY KEY, NEVER A FOREIGN KEY
--------------------------------------------------------------------------------
The three scopes are NOT 1:1 with any source row and cannot be:

* a transcript chunk WINDOWS consecutive turns (a per-turn vector for "haan" is noise that
  crowds a real exchange out of the top-k), so it spans several `transcript_turns` rows —
  and `_TRANSCRIPT_DELETE_SQL` genuinely DELETEs those rows when a tenant's `transcript`
  policy action is `delete`, so a `subject_id` pointing at one would dangle;
* a lead yields several chunks from one schema-driven `leads.data`;
* a caller memory is distilled ACROSS calls and derives from no single source row at all.

So `subject_id` is whatever the SCOPE mints deterministically for a chunk — a uuid5 over
(call_id, first turn idx) for the transcript scope, the lead's own id for the lead scope —
and `idx` is its position within that subject. There is no FK and there must not be one.
`UNIQUE (subject_kind, subject_id, idx)` is the idempotency key, and it CONTAINS both
conventions: a scope that mints a distinct id per chunk writes `idx = 0` and the
constraint degenerates to `(subject_kind, subject_id)`, while a scope that keys on the
source row plus a position (`crm/lead_projection.LeadChunk.idx`) uses all three columns.

--------------------------------------------------------------------------------
`occurred_at` — THE CLOCK, CARRIED RATHER THAN JOINED
--------------------------------------------------------------------------------
The retention sweep has to date a row without knowing which of four tables it projects, so
the projection carries the clock of the thing it projects: a call's `_call_clock`, a
lead's `updated_at`, a memory's SOURCE CALL's end. One statement per category, no join, no
`CASE` over `subject_kind` that a fifth scope would have to be added to.

It is NOT `created_at`, and the difference is a whole caller population: a backfill that
projected two years of calls tonight would stamp every row with tonight, and every
caller's retention clock would restart because a background job read their data. The
clock belongs to the EVENT, so it is copied from the event.

The failure direction is chosen: a source clock that MOVES after projection leaves this
value stale-EARLY, so the vector expires slightly before its source rather than after it.
Losing a vector early degrades a search; keeping one late is a retention promise broken.

--------------------------------------------------------------------------------
`embed_state`, AND WHY IT HAS SIX VALUES WHERE `kb_chunks` HAS THREE
--------------------------------------------------------------------------------
`pending` / `ready` / `refused` are `kb_chunks`' vocabulary, unchanged and for its reasons.
Three more exist because this table is swept by things `kb_chunks` is not:

* `expired` — retention reached it. TERMINAL, and `scrubbed_at` is set.
* `erased`  — a DPDP erasure or a tenant erasure reached it. TERMINAL, `scrubbed_at` set.
* `superseded` — the SOURCE changed and no longer produces this slot (an edited lead now
  projecting four chunks where it projected six). The vector and the lexemes go, exactly
  as on the two above, but `scrubbed_at` stays NULL, so the slot can be filled again if
  the source grows back. Conflating it with `expired` would make an edit permanently
  destroy a slot; conflating it with a plain delete would let a re-projection resurrect
  something an erasure had just destroyed.

`expired` and `erased` are terminal because the ingestion sweep DISCOVERS its own work: it re-projects any
subject row that has no projection. Without a tombstone, deleting the row would let the
next tick re-project the subject and re-buy a vector for text an erasure had just
destroyed — a loop that spends money to undo a legal obligation. The row is therefore
KEPT and emptied, which is also what `scrub_quotes_for_calls` and `_EXTRACTION_SQL` do to
their rows and for the same reason: the tombstone is what makes the forgetting durable.

They are TWO states and not one because they are two different facts about the same row,
and an operator asking "did this account's data age out, or did somebody ask to be
forgotten" cannot answer it from one value.

--------------------------------------------------------------------------------
THE COLUMN TYPES, WHICH ARE `dc1aaeeeff02`'s AND NOT RE-DECIDED
--------------------------------------------------------------------------------
`vector(1536)` at `retrieval/embedding.EMBEDDING_DIMS`, HNSW `m = 16, ef_construction =
64` built CONCURRENTLY in an `autocommit_block`, GIN on `tsv`, and the `english` text
search configuration. Every one of those was measured or verified for `kb_chunks` on
1 Sep 2026 and none of the measurements is about the CONTENT: `halfvec` needs pgvector
0.7.0 and `hnsw.iterative_scan` needs 0.8.0, this server has 0.6.0 (MEASURED-HERE, and
re-measured on this database while writing this migration: `SELECT extversion FROM
pg_extension WHERE extname = 'vector'` → `0.6.0`), and `to_tsvector('english', <Telugu>)`
is byte-identical to `simple` while stemming English. Re-deciding them here would be a
second answer to a settled question.

`tsv` is NOT NULL **with a `''::tsvector` default**, which is the one deliberate departure
from `kb_chunks` (where it is NOT NULL with no default). The erasure arm must be able to
EMPTY it, and an empty `tsvector` matches nothing — `'' :: tsvector @@ plainto_tsquery(
'english', 'hello')` is false (MEASURED-HERE on this database, 1 Sep 2026). NULL would do
the same job and would put a third state (`NULL`, empty, populated) into every reader.

--------------------------------------------------------------------------------
RLS (hard rule 1)
--------------------------------------------------------------------------------
`ENABLE` + `FORCE ROW LEVEL SECURITY` and the standard `tenant_isolation` policy, in this
migration, and `caller_chunks` joins `db/registry.TENANT_TABLES` so the coverage guard
counts it. `tests/caller_chunks_rls_test.py` is the cross-tenant zero-rows test, in both
directions — the control (a neighbour's session sees none of these rows) and the mistake
RLS cannot see (a caller passing tenant A's id on tenant B's session), which is why
`caller_search.py` re-states `tenant_id` in the statement as well.

`agents.caller_memory_enabled` ARRIVES IN THIS MIGRATION TOO, and its default is the
OPPOSITE of the two disclosure toggles beside it. `ai_disclosure_enabled` and
`recording_notice_enabled` default TRUE because the safe posture is "the agent discloses";
here the safe posture is "the agent does not remember", so it defaults FALSE. An omission,
a future importer and a restore from an older dump must all yield no cross-call memory —
which is only true if the absent value is the off one.

NO BACKFILL, unlike `dc1aaeeeff02`, and the omission is deliberate rather than forgotten.
The backfill there was one statement over `kb_documents`; here the source rows belong to
four scopes that do not exist yet, and the ingestion sweep DISCOVERS un-projected subjects
on every tick — so the reach backwards is the sweep's first pass rather than a statement
written now against tables whose shape is being decided in parallel.

--------------------------------------------------------------------------------
`platform_ai_usage` GAINS `system_actor`, AND `admin_user_id` BECOMES NULLABLE
--------------------------------------------------------------------------------
D-502 recorded this gap in as many words: the founder asked for INGESTION spend to bill the
platform ledger, and `billing/platform_ai.record_platform_ai_usage` requires
`admin_user_id: UUID` because it was built for the admin copilot, where a named operator is
always behind the turn. A cron has no operator, and putting a fabricated identity on an
APPEND-ONLY ledger is worse than the gap — so D-502 metered ingestion on the TENANT ledger
and reported the gap rather than papering over it.

This closes it honestly. The property the original column was defending is stated on its
own comment: *"a row of our own spend nobody can be asked about is the one shape this
ledger must not be able to hold"*. That property is about ACCOUNTABILITY, not about a
human — a named cron is answerable in exactly the way an anonymous NULL is not. So
`admin_user_id` becomes nullable, `system_actor` is added, and
`ck_platform_ai_usage_one_actor` requires EXACTLY ONE of them to be present. The shape the
column was refusing (neither) is still refused; the shape it was accidentally refusing (a
job) is now representable and NAMED.

No row is rewritten and no trigger is touched: every existing row has an `admin_user_id`
and satisfies the new CHECK, which is why it can be added `NOT VALID` and validated in the
same migration rather than needing a backfill (hard rule 4 — nothing here UPDATEs the
ledger).

--------------------------------------------------------------------------------
REVERSIBILITY (hard rule 8)
--------------------------------------------------------------------------------
`downgrade` drops `caller_chunks` (every byte of it is derived and reconstructible by the
sweep), drops the CHECK and the column on `platform_ai_usage`, and restores
`admin_user_id NOT NULL` — which is safe only while no system row exists, so it REFUSES
with a countable reason rather than failing on a NOT NULL violation out of context. The
`vector` extension is left installed, for `dc1aaeeeff02`'s reason.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from apps.api.retrieval.embedding import EMBEDDING_DIMS

revision: str = "c6b1f0d47e83"
down_revision: str | None = "817842cf3b97"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "caller_chunks"

#: The text-search configuration, which MUST equal `dc1aaeeeff02.TS_CONFIG` and
#: `retrieval/pgvector.TS_CONFIG`. A `tsvector` stored under one configuration and a
#: `tsquery` built under another do not match, and the symptom is an empty result rather
#: than an error. Spelled here as a constant so all three are greppable together.
TS_CONFIG = "english"

#: What a projection may be OF. A closed set, because `subject_kind` decides which erasure
#: handle applies and which registry entry re-projects it — a free-form string would let a
#: typo become a scope nothing sweeps.
SUBJECT_KINDS = ("lead", "call_turn", "call_summary", "caller_memory")

#: Which `retention_policies.data_category` clock a projection expires on. A SUBSET of
#: `compliance/models.DATA_CATEGORIES`, and deliberately only the two that have a sweep arm
#: behind them in `workers/retention._apply_one`:
#:
#:   lead        → a lead's projection. The client's CRM, on the clock they agreed to for
#:                 it (default 1095d), exactly as `call_extractions.data` is.
#:   transcript  → a turn, a summary, AND a caller memory. The first two are the transcript
#:                 by definition. The third is a DISTILLATION of what the caller said
#:                 across calls, so it belongs on the clock of the words it was distilled
#:                 from — `calls.summary`'s argument, one table over.
#:
#: A THIRD VALUE IS NOT ADDED SPECULATIVELY. A category in this CHECK with no arm in the
#: sweep is precisely the defect `DERIVED_COPIES` exists against: a copy filed somewhere
#: that nothing reads. When a caller-memory SOURCE table lands and the founder sets its
#: retention period, `caller_memory` becomes a `DATA_CATEGORIES` value and a value here,
#: in that order and in one migration.
RETENTION_CATEGORIES = ("transcript", "lead")

#: `pending` / `ready` / `refused` are `kb_chunks.EMBED_STATES`, unchanged. `superseded`,
#: `expired` and `erased` are argued in the module docstring — and all three are listed
#: here, which this tuple briefly failed to do: it held five values while the model held
#: six, so the database CHECK forbade the one state `ck_caller_chunks_superseded_has_no_
#: vector` is written about, and the first sweep to supersede a slot would have raised.
#: `tests/orm_schema_fidelity_test.py` is what caught it; a retyped enum is why it could
#: happen at all.
EMBED_STATES = ("pending", "ready", "refused", "superseded", "expired", "erased")

_POLICY = (
    f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

#: THE HNSW INDEX, OUTSIDE THE MIGRATION TRANSACTION — `dc1aaeeeff02._HNSW_INDEX_SQL`'s
#: statement, its parameters and its reasoning, applied to this table. It is empty at
#: creation (nothing has projected yet), so the build is instantaneous here; the statement
#: has to be the one that is also correct on a REBUILD of a populated table, where a
#: non-concurrent form is an ACCESS EXCLUSIVE lock for minutes.
_HNSW_INDEX_SQL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_caller_chunks_embedding ON caller_chunks "
    "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
)

#: EXACTLY ONE ACTOR. See the module docstring: the property being defended is that no row
#: of our own AI spend is unattributable, and a named cron attributes it as well as a named
#: operator does. `NOT VALID` then `VALIDATE` is this repo's locking shape for adding a
#: constraint to a live table (`d5b8a2c60e17`), and here it also means the existing rows are
#: checked rather than assumed to pass.
_ONE_ACTOR_CHECK = (
    "(admin_user_id IS NOT NULL) <> (system_actor IS NOT NULL)"
)


def upgrade() -> None:
    _require_vector_extension()
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # WHAT this projects, and the reason the table is one table. See the docstring.
        sa.Column("subject_kind", sa.Text(), nullable=False),
        # The source row's primary key. NOT an FK, and that is the discriminator's price
        # paid deliberately: it points into one of four tables depending on
        # `subject_kind`, and a polymorphic FK is not a thing Postgres has. What replaces
        # the referential guarantee is the registry — a projection exists only because a
        # registered scope's discovery statement produced it from its own table, and the
        # scope's own erasure handle (`call_id`, `subject_ref`) is what reaches it.
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The call this derives from, when it derives from one. CASCADE is declared and is
        # NOT the erasure mechanism — see the docstring: an erasure scrubs a call in place
        # and keeps the row, so this cascade never fires on the path that matters.
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=True),
        # WHICH AGENT'S CONVERSATION THIS CAME OUT OF. NOT NULL: `leads.agent_id` and
        # `calls.agent_id` are both NOT NULL, so every scope has one, and a search scoped to
        # one agent is the question a client with two agents actually asks.
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        # THE KEYED SUBJECT HANDLE (`compliance/caller_ref.active_caller_ref`) and the KEK
        # generation that minted it. NOT NULL both: a projection nothing can erase by
        # subject is a projection this table must not be able to hold.
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("subject_ref_kek_id", sa.Integer(), nullable=False),
        # WHERE INSIDE THE CALL, for a transcript window. NULL on every other kind. Two
        # columns rather than a range type because they are read by a client screen that
        # shows the passage in place — without them a semantic hit can only be attributed to
        # a CALL, which hands the client a list of ids and a reading task rather than an
        # answer.
        sa.Column("first_turn_idx", sa.Integer(), nullable=True),
        sa.Column("last_turn_idx", sa.Integer(), nullable=True),
        # Position within THIS subject. See the docstring: the unique key contains both
        # scope conventions, and a scope that mints a distinct id per chunk writes 0.
        sa.Column("idx", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # WHICH CLOCK IT EXPIRES ON, in the vocabulary the client's own DPA uses.
        sa.Column("retention_category", sa.Text(), nullable=False),
        # THE CLOCK ITSELF, carried rather than joined. See the docstring.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # The sparse key. NOT NULL with an EMPTY default, because the erasure arm empties
        # it and an empty `tsvector` matches nothing (measured — see the docstring).
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            nullable=False,
            server_default=sa.text("''::tsvector"),
        ),
        # The dense key. NULLABLE by design, for `kb_chunks`' reason (the sparse arm answers
        # from the instant a row is projected) and for a second one that is this table's
        # own: NULL is what an erasure leaves behind, so the column has to admit it.
        sa.Column("embedding", Vector(EMBEDDING_DIMS), nullable=True),
        sa.Column("embed_model", sa.Text(), nullable=True),
        sa.Column("embed_dim", sa.Integer(), nullable=True),
        sa.Column(
            "embed_state", sa.Text(), nullable=False, server_default=sa.text("'pending'")
        ),
        # THE RE-EMBED IDEMPOTENCY KEY, and it is a HASH rather than the text for the one
        # reason that matters: this table stores no content, and a column holding the
        # caller's sentence would make every argument above it false. It answers exactly
        # one question — "is the source text still the text this vector was bought for?" —
        # which is the question a corrected transcript or an edited lead field asks.
        sa.Column("content_sha256", sa.Text(), nullable=False),
        # WHEN WE FORGOT IT, and it is a column rather than an inference from
        # `embedding IS NULL` for `call_extractions.scrubbed_at`'s reason: an emptied row and
        # a row nobody has embedded yet are byte-identical on the vector alone, and those two
        # are opposites. It is also what makes every scrub idempotent — a re-run of an
        # erasure counts the rows it actually changed rather than the rows it already had.
        sa.Column("scrubbed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_caller_chunks")),
        # ONE PROJECTION PER SUBJECT ROW, enforced by the database. It is what makes the
        # discovery statement idempotent by `ON CONFLICT` rather than by a read-then-write,
        # and it is what makes an `erased` tombstone actually block a re-projection: the
        # INSERT collides with the tombstone and the DO UPDATE arm refuses to revive it.
        sa.UniqueConstraint(
            "subject_kind", "subject_id", "idx", name=op.f("uq_caller_chunks_subject")
        ),
        sa.CheckConstraint(
            f"subject_kind IN {SUBJECT_KINDS!r}", name=op.f("ck_caller_chunks_subject_kind_enum")
        ),
        sa.CheckConstraint(
            f"retention_category IN {RETENTION_CATEGORIES!r}",
            name=op.f("ck_caller_chunks_retention_category_enum"),
        ),
        sa.CheckConstraint(
            f"embed_state IN {EMBED_STATES!r}", name=op.f("ck_caller_chunks_embed_state_enum")
        ),
        # THE SINGLE MOST IMPORTANT PROPERTY OF THIS TABLE, AS A DATABASE CONSTRAINT.
        # A row that has been forgotten may not still carry the sentence — in EITHER key.
        # An erasure that scrubbed the source and left `embedding` behind would leave the
        # caller's words on file in the one form nobody looks at, and a `tsv` left behind
        # would leave them in a form a `plainto_tsquery` still matches. Enforced here so no
        # future writer of this table can forget half of it.
        sa.CheckConstraint(
            "scrubbed_at IS NULL OR (embedding IS NULL AND tsv = ''::tsvector "
            "AND embed_state IN ('expired', 'erased'))",
            name=op.f("ck_caller_chunks_forgotten_has_no_keys"),
        ),
        # The revivable half of the same rule: a slot the source no longer fills carries no
        # vector either, but keeps `scrubbed_at` NULL so the source can fill it again.
        sa.CheckConstraint(
            "embed_state <> 'superseded' OR (embedding IS NULL AND scrubbed_at IS NULL)",
            name=op.f("ck_caller_chunks_superseded_has_no_vector"),
        ),
        # A turn span belongs to a transcript window and to nothing else, and its two ends
        # travel together — a half-span is a screen that cannot render the passage.
        sa.CheckConstraint(
            "(first_turn_idx IS NULL) = (last_turn_idx IS NULL)",
            name=op.f("ck_caller_chunks_turn_span_paired"),
        ),
        sa.CheckConstraint(
            "first_turn_idx IS NULL OR subject_kind = 'call_turn'",
            name=op.f("ck_caller_chunks_turn_span_scope"),
        ),
        sa.CheckConstraint("idx >= 0", name=op.f("ck_caller_chunks_idx_not_negative")),
    )
    # The search scope: one btree on one table, `dc1aaeeeff02`'s measured shape. Leading
    # `tenant_id` because no query omits it (RLS aside, the adapter re-states it), then
    # `subject_kind` because every caller of `caller_search` names the scopes it wants.
    op.create_index(
        op.f("ix_caller_chunks_scope"),
        TABLE,
        ["tenant_id", "subject_kind", "agent_id"],
        postgresql_where=sa.text("scrubbed_at IS NULL"),
    )
    op.execute("CREATE INDEX ix_caller_chunks_tsv ON caller_chunks USING gin (tsv)")
    # The sweep's work list — a partial index that SHRINKS to empty as the backlog drains
    # rather than growing with the corpus (`a7f4c31d95e8`'s shape, `kb_chunks`' reason).
    op.create_index(
        op.f("ix_caller_chunks_embed_pending"),
        TABLE,
        ["tenant_id"],
        postgresql_where=sa.text("embed_state = 'pending'"),
    )
    # THE TWO ERASURE HANDLES, each with its own partial index, because an erasure is a
    # legal deadline and a sequential scan of a fleet's projections is how one is missed.
    op.create_index(
        op.f("ix_caller_chunks_call"),
        TABLE,
        ["call_id"],
        postgresql_where=sa.text("call_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_caller_chunks_subject_ref"),
        TABLE,
        ["tenant_id", "subject_ref"],
        postgresql_where=sa.text("scrubbed_at IS NULL"),
    )
    # The retention arm: one category, oldest first. Matches the sweep's own ORDER BY so a
    # batch is an index range rather than a sort of everything the tenant holds.
    op.create_index(
        op.f("ix_caller_chunks_retention"), TABLE, ["retention_category", "occurred_at"]
    )

    # NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape. `organizations` RESTRICT
    # because offboarding is an explicit workflow and never a cascade (`db/base.TenantMixin`).
    # `calls` **SET NULL, not CASCADE**: a caller-memory row outlives the call it was learned
    # on by design, and on the call scopes a cascade would destroy the very TOMBSTONE that
    # proves we forgot the row. Provenance goes; the record that we forgot stays. It bears
    # repeating that neither behaviour is the erasure mechanism — the DPDP path does not
    # delete calls at all, which is why `caller_erasure.py` exists.
    for statement in (
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_caller_chunks_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_caller_chunks_call_id_calls "
        "FOREIGN KEY (call_id) REFERENCES calls (id) ON DELETE SET NULL NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_caller_chunks_agent_id_agents "
        "FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE NOT VALID",
    ):
        op.execute(statement)
    for constraint in (
        "fk_caller_chunks_tenant_id_organizations",
        "fk_caller_chunks_call_id_calls",
        "fk_caller_chunks_agent_id_agents",
    ):
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {constraint}")

    # Hard rule 1, in the same migration as the table it protects.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    _caller_memories()
    _agent_memory_toggle()
    _widen_platform_ai_actor()

    # LAST, and outside the transaction — `dc1aaeeeff02`'s ordering and its reason: a
    # failure here leaves a table that WORKS (every query is served by the btree and the
    # GIN index), and an operator re-runs the one statement rather than the migration.
    with op.get_context().autocommit_block():
        op.execute(_HNSW_INDEX_SQL)


def _caller_memories() -> None:
    """The caller-memory SOURCE table — the one thing `caller_chunks` cannot be.

    `caller_chunks` stores NO CONTENT, on purpose and by the first premise of this
    migration, so a distilled durable fact about a repeat caller needs a home of its own the
    way a transcript turn and a lead already have one. This is that home, and it is here
    rather than in a fourth migration because this repository has exactly one migration
    author in this change and a scope with nowhere to write is a scope that ships blocked.

    IT IS DELIBERATELY THIN. What a fact IS, how it is distilled and when it is recalled all
    belong to the scope that owns the feature; what belongs to the safety core is that the
    row is reachable by an erasure, dated by a clock a background job cannot restart, and
    isolated by a FORCEd policy. So: the keyed subject handle and its generation, the agent,
    the provenance call, `occurred_at`, `scrubbed_at`, and the fact itself.

    `source_call_id` is PROVENANCE AND NOT AN ERASURE PATH — SET NULL, so the row survives
    the call it was learned on, which is the entire point of cross-call memory. Erasure
    reaches it by `subject_ref = ANY(caller_refs(tenant, number))`, the same predicate that
    reaches its projection.

    NO RETENTION CATEGORY OF ITS OWN. A memory is DISTILLED from what the caller said, so it
    rides the tenant's existing `transcript` clock through `retention.DERIVED_COPIES` —
    `calls.summary` and the knowledge-gap quotes are already filed exactly that way, and a
    new `retention_policies.data_category` is a number the founder has to give and a row
    every existing tenant needs.
    """
    op.create_table(
        "caller_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("subject_ref_kek_id", sa.Integer(), nullable=False),
        # WHAT WE REMEMBER. One short sentence per row rather than a document: a fact is
        # what gets recalled into a prompt, and a paragraph recalled is a paragraph of
        # somebody's conversation replayed to whoever rings next.
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("source_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scrubbed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_caller_memories")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_caller_memories_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_caller_memories_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            name=op.f("fk_caller_memories_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        # A SCRUBBED MEMORY HOLDS NO WORDS, in the database rather than in a worker — the
        # `caller_chunks` rule, on the table the chunk projects. `''` and not NULL so the
        # column stays NOT NULL and every reader has one empty value to test rather than two.
        sa.CheckConstraint(
            "scrubbed_at IS NULL OR fact = ''", name=op.f("ck_caller_memories_scrubbed_is_empty")
        ),
    )
    op.create_index(
        op.f("ix_caller_memories_subject"),
        "caller_memories",
        ["tenant_id", "subject_ref"],
        postgresql_where=sa.text("scrubbed_at IS NULL"),
    )
    # The retention arm's range: one clock, oldest first.
    op.create_index(op.f("ix_caller_memories_occurred"), "caller_memories", ["occurred_at"])
    op.execute("ALTER TABLE caller_memories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE caller_memories FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON caller_memories USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _agent_memory_toggle() -> None:
    """`agents.caller_memory_enabled`, DEFAULT FALSE — and the default is the decision.

    Its two neighbours (`ai_disclosure_enabled`, `recording_notice_enabled`) default TRUE
    because the safe posture there is "the agent discloses". Here the safe posture is the
    other one: an agent that does not remember its callers is the conservative agent, so an
    omission, a future importer, and a restore from a dump written before this column
    existed must all yield NO cross-call memory. A default of TRUE would mean a schema
    change silently switched a memory feature on for every client on the platform.
    """
    op.add_column(
        "agents",
        sa.Column(
            "caller_memory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def _widen_platform_ai_actor() -> None:
    """Let a NAMED JOB pay from the platform ledger; keep an ANONYMOUS row impossible."""
    op.add_column("platform_ai_usage", sa.Column("system_actor", sa.Text(), nullable=True))
    op.alter_column("platform_ai_usage", "admin_user_id", nullable=True)
    op.execute(
        "ALTER TABLE platform_ai_usage ADD CONSTRAINT ck_platform_ai_usage_one_actor "
        f"CHECK ({_ONE_ACTOR_CHECK}) NOT VALID"
    )
    op.execute("ALTER TABLE platform_ai_usage VALIDATE CONSTRAINT ck_platform_ai_usage_one_actor")


def _require_vector_extension() -> None:
    """Install `vector`, or refuse with the statement a human must run.

    `dc1aaeeeff02._require_vector_extension`, verbatim in intent: the extension is not
    marked `trusted` (its control file carries no `trusted = true`), so `CREATE EXTENSION`
    needs a superuser, and the migration role is not guaranteed to be one in production.
    It is asked again here rather than assumed from the earlier migration, because a
    database restored from a dump taken before `dc1aaeeeff02` is a real state and
    `InsufficientPrivilege` out of context is not an error a reader can act on.
    """
    bind = op.get_bind()
    installed = bind.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).first()
    if installed is not None:
        return
    available = bind.execute(
        sa.text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
    ).first()
    if available is None:
        raise RuntimeError(
            "pgvector is not available on this PostgreSQL server, so caller_chunks cannot "
            "be created. Install the server package (Debian/Ubuntu: postgresql-16-pgvector; "
            "the pgvector/pgvector:pg16 image ships it) and re-run this migration."
        )
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as failure:  # pragma: no cover - exercised only without superuser
        raise RuntimeError(
            "pgvector is available but this role may not install it. Run "
            "`CREATE EXTENSION vector;` in the calevate database as a superuser, then "
            "re-run this migration."
        ) from failure


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON caller_memories")
    op.drop_table("caller_memories")
    op.drop_column("agents", "caller_memory_enabled")

    # THE LEDGER IS APPEND-ONLY, so this cannot delete the rows that would violate the
    # restored NOT NULL. It refuses instead, with the count, rather than raising a
    # NotNullViolation the reader would have to diagnose (errors are part of the interface).
    system_rows = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM platform_ai_usage WHERE system_actor IS NOT NULL"))
        .scalar_one()
    )
    if system_rows:
        raise RuntimeError(
            f"{system_rows} platform_ai_usage row(s) were paid for by a system actor rather "
            "than an operator, and platform_ai_usage is append-only (hard rule 4) so they "
            "cannot be removed to restore admin_user_id NOT NULL. Downgrading past "
            "c6b1f0d47e83 is only possible on a database where no background job has "
            "metered AI spend."
        )
    op.execute(
        "ALTER TABLE platform_ai_usage DROP CONSTRAINT IF EXISTS ck_platform_ai_usage_one_actor"
    )
    op.alter_column("platform_ai_usage", "admin_user_id", nullable=False)
    op.drop_column("platform_ai_usage", "system_actor")
