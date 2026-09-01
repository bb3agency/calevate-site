"""The registry a caller-data SCOPE registers its projection with (D-503).

`caller_chunks` is one table with a discriminator, and this is how a scope gets rows into
it: it registers ONE `CallerProjection`, and the shared sweep
(`apps/workers/caller_embeddings.py`) owns the transaction, the claim, the idempotency key,
the per-tick budget, the price gate and the metering for every scope at once. A scope owns
what a chunk IS and nothing else.

WHY A REGISTRY AND NOT ONE GENERIC STATEMENT. The first draft of this design had the sweep
discover un-projected subjects with a single SQL statement over a source table, which
assumed the projection was 1:1 with a source row. None of the three scopes is:

* a transcript chunk WINDOWS consecutive turns (a per-turn vector for "haan" is noise that
  crowds a real exchange out of the top-k), so one chunk spans several `transcript_turns`
  rows — and `retention._TRANSCRIPT_DELETE_SQL` genuinely DELETEs those rows when a tenant's
  `transcript` policy action is `delete`, so a `subject_id` pointing at one would dangle;
* a lead yields several chunks from one schema-driven `leads.data` payload;
* a caller memory is distilled ACROSS calls and derives from no single source row at all.

So discovery is PER SCOPE. What stays shared is everything that is dangerous to get wrong
twice.

WHAT A SCOPE MAY NOT CHOOSE, and each is a hole somebody would otherwise fall into:

* **Its retention clock.** `models.SUBJECT_RETENTION` maps kind → category, so a scope
  cannot file a caller's sentence on the 1095-day CRM clock by calling itself a lead. A
  category is a promise in the client's DPA, not a per-feature setting.
* **Its subject handle.** `subject_ref` is minted here from the phone number by
  `compliance/caller_ref.active_caller_ref` — the KEYED construction — so no scope can
  file a row under a key an erasure cannot derive, and none can accidentally use the
  unsalted `export.subject_ref`.
* **Whether an erased source re-projects.** The INSERT refuses to revive a row whose
  `scrubbed_at` is set. A scope's own belt (yielding nothing for an emptied source) is
  still expected and is argued in `call_projection.py` and `lead_projection.py`; this is
  the braces, in the one statement every scope goes through.
* **What it costs.** The sweep checks `embedding_price_is_billable()` before any provider
  call and meters what it bought (hard rule 7).

HARD RULE 6: nothing in this module logs. It handles caller text and phone numbers, and the
only safe amount of either in a log line is none — the sweep logs ids and counts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_ref import active_caller_ref
from apps.api.retrieval.models import (
    EMBED_PENDING,
    EMBED_SUPERSEDED,
    SUBJECT_KINDS,
    SUBJECT_RETENTION,
)

#: The text-search configuration, which MUST equal migration `c6b1f0d47e83.TS_CONFIG` and
#: `retrieval/pgvector.TS_CONFIG`. A `tsvector` stored under one configuration and a
#: `tsquery` built under another do not match, and the symptom is an EMPTY RESULT rather
#: than an error — the one failure shape nobody notices.
TS_CONFIG: Final = "english"


@dataclass(frozen=True, slots=True)
class ProjectedChunk:
    """One chunk a scope wants stored, with everything the store needs and nothing else.

    **IT CARRIES `phone_e164` AND THE STORE NEVER KEEPS IT.** The number is here only so
    this module can derive `subject_ref` under the platform key; it reaches no column, no
    log line and no index. A scope that cannot supply one is a scope whose rows an erasure
    could not reach by subject, which is why the field is required rather than optional.
    """

    #: What the SCOPE mints to identify this chunk. An IDEMPOTENCY KEY, never a foreign
    #: key — see the module docstring. Deterministic, so re-running discovery over an
    #: unchanged source overwrites its own row instead of adding a second one that would
    #: take a slot in the top-k.
    subject_id: UUID
    #: Position within `subject_id`. Zero for a scope that mints a distinct id per chunk.
    idx: int
    #: What gets embedded, and what the sparse key is built from. Already labelled, already
    #: redacted, already chunked — the scope's own pure function decided all three.
    text: str
    #: The agent whose conversation this came out of. NOT NULL in the store.
    agent_id: UUID
    #: The subject's number, in E.164. Used HERE and discarded — see the class docstring.
    phone_e164: str
    #: The clock of the EVENT this projects, never `now()`: a backfill that stamped tonight
    #: would restart every caller's retention period because a background job read them.
    occurred_at: datetime
    #: Provenance, and an extra erasure handle where it exists. `None` for a caller memory,
    #: which outlives any one call.
    call_id: UUID | None = None
    #: The turn span, for a transcript window only — what lets a hit be shown in place
    #: rather than merely attributed to a call id.
    first_turn_idx: int | None = None
    last_turn_idx: int | None = None


#: `(subject_id, idx)` — the half of the store's key a scope owns. What the sweep hands
#: back to `content_for` when it has claimed rows and needs their text again.
ChunkKey = tuple[UUID, int]

#: A scope's discovery: every chunk whose projection is missing or out of date, oldest
#: first, at most `limit` of them. Runs inside the tenant's RLS session.
Discover = Callable[[AsyncSession, int], Awaitable[Sequence[ProjectedChunk]]]

#: A scope's re-read: the text for chunks the sweep has CLAIMED. Separate from discovery
#: because the store holds no content — the claim happens on `caller_chunks` (which is
#: where `FOR UPDATE ... SKIP LOCKED` belongs, so two ticks cannot buy one vector twice)
#: and the text has to be fetched again from the scope's own tables.
ContentFor = Callable[[AsyncSession, Sequence[ChunkKey]], Awaitable[Mapping[ChunkKey, str]]]


@dataclass(frozen=True, slots=True)
class CallerProjection:
    """ONE scope's contribution to the shared store. Registered once, at import."""

    subject_kind: str
    discover: Discover
    content_for: ContentFor
    #: Derived, never given — see the module docstring. A field with no `init` so a caller
    #: cannot pass one, and `__post_init__` is where the kind is checked at all.
    retention_category: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(
                f"unknown caller-chunk subject kind {self.subject_kind!r}; add it to "
                "retrieval/models.SUBJECT_KINDS, to the migration's CHECK and to "
                "SUBJECT_RETENTION in one change"
            )
        object.__setattr__(self, "retention_category", SUBJECT_RETENTION[self.subject_kind])


_REGISTRY: dict[str, CallerProjection] = {}


def register_projection(projection: CallerProjection) -> CallerProjection:
    """Add a scope to the sweep. Refuses a second registration of one kind.

    Refusing rather than overwriting because the failure it prevents is silent: two modules
    registering `lead` would leave whichever imported last as the only one that ever runs,
    and the other scope's chunks would simply never appear — with nothing to see but an
    empty search.
    """
    existing = _REGISTRY.get(projection.subject_kind)
    if existing is not None and existing is not projection:
        raise ValueError(
            f"caller-chunk subject kind {projection.subject_kind!r} is already registered; "
            "one scope owns one kind"
        )
    _REGISTRY[projection.subject_kind] = projection
    return projection


def registered_projections() -> tuple[CallerProjection, ...]:
    """Every registered scope, in a STABLE order.

    Sorted rather than insertion-ordered for `retention._due_tenants`' reason: without it
    which scopes a tick reaches before its budget runs out would depend on import order,
    and "scope X was not swept last night" would be a question with no answer.
    """
    return tuple(_REGISTRY[kind] for kind in sorted(_REGISTRY))


def content_digest(body: str) -> str:
    """`caller_chunks.content_sha256` — the answer to "is the source still what we bought a
    vector for?", and the ONLY thing derived from the text that this table keeps.

    A hash and not the text, because a content column would make the store's central claim
    false. Full-width `sha256`: a truncated digest saves nothing on a text column and this
    one is compared for equality, never enumerated.
    """
    return hashlib.sha256(body.encode()).hexdigest()


#: THE ONE INSERT. `ON CONFLICT ... DO UPDATE` rather than a read-then-write, so a
#: re-discovery is idempotent in the database rather than in a race window.
#:
#: **THE `WHERE` CLAUSE IS THE SAFETY PROPERTY AND NOT AN OPTIMISATION.** Two conditions,
#: and each refuses a different disaster:
#:
#: * `caller_chunks.scrubbed_at IS NULL` — a row an erasure or a retention sweep forgot is
#:   NEVER revived. Without it, a discovery running minutes after a §12 request would
#:   re-project the subject and re-buy a vector for text the erasure had just destroyed:
#:   money spent to undo a legal obligation, with the certificate already signed.
#: * `content_sha256 IS DISTINCT FROM EXCLUDED.content_sha256` — an unchanged chunk is NOT
#:   reset to `pending`, so a nightly discovery does not re-buy the whole corpus every
#:   night. `IS DISTINCT FROM` and not `<>` for `kb_embeddings._CLAIM_SQL`'s reason: the
#:   stored value can be from a row written before this column carried anything, and `<>`
#:   answers NULL and skips exactly those.
#:
#: `tsv` is built HERE, in the statement, from the parameter — so a chunk is searchable by
#: its sparse arm the moment it is discovered and gains its dense arm when the sweep
#: reaches it, exactly as a published knowledge chunk is.
_UPSERT_SQL: Final = f"""
INSERT INTO caller_chunks (
  id, tenant_id, subject_kind, subject_id, idx, call_id, agent_id, subject_ref,
  subject_ref_kek_id, first_turn_idx, last_turn_idx, retention_category, occurred_at,
  tsv, content_sha256, embed_state, created_at, updated_at)
VALUES (
  :id, :tid, :kind, :sid, :idx, :call_id, :aid, :ref, :kek, :first_turn, :last_turn,
  :category, :occurred_at, to_tsvector('{TS_CONFIG}', :body), :sha, '{EMBED_PENDING}',
  now(), now())
ON CONFLICT (subject_kind, subject_id, idx) DO UPDATE SET
  tsv = EXCLUDED.tsv,
  content_sha256 = EXCLUDED.content_sha256,
  call_id = EXCLUDED.call_id,
  agent_id = EXCLUDED.agent_id,
  subject_ref = EXCLUDED.subject_ref,
  subject_ref_kek_id = EXCLUDED.subject_ref_kek_id,
  first_turn_idx = EXCLUDED.first_turn_idx,
  last_turn_idx = EXCLUDED.last_turn_idx,
  occurred_at = EXCLUDED.occurred_at,
  embedding = NULL,
  embed_model = NULL,
  embed_dim = NULL,
  embed_state = '{EMBED_PENDING}',
  updated_at = now()
WHERE caller_chunks.scrubbed_at IS NULL
  AND caller_chunks.content_sha256 IS DISTINCT FROM EXCLUDED.content_sha256
"""

#: The slots a scope no longer fills. An edited lead that projected six chunks and now
#: projects four leaves two rows behind holding the caller's OLD answers — the same defect
#: class as a derived copy nothing expires, on a shorter clock.
#:
#: `superseded` and not `expired`: `scrubbed_at` stays NULL, so if the source grows back the
#: slot can be filled again. A tombstone here would make an edit permanently destroy a slot.
_SUPERSEDE_SQL: Final = f"""
UPDATE caller_chunks
   SET embedding = NULL, embed_model = NULL, embed_dim = NULL, tsv = ''::tsvector,
       content_sha256 = '', embed_state = '{EMBED_SUPERSEDED}', updated_at = now()
 WHERE subject_kind = :kind AND subject_id = :sid AND idx > :last_idx
   AND scrubbed_at IS NULL AND embed_state <> '{EMBED_SUPERSEDED}'
"""


async def store_chunks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    projection: CallerProjection,
    chunks: Sequence[ProjectedChunk],
) -> int:
    """Write one scope's discovered chunks into the shared store. Returns rows written.

    Runs INSIDE the caller's tenant session and inside the sweep's transaction, so the
    projection and whatever else that tick did commit together or not at all.

    Grouped by `subject_id` so the supersession statement can run once per subject with the
    highest `idx` that survived — the chunk list is what the scope's pure function produced,
    so anything above that index is a slot the source no longer fills.
    """
    from apps.api.db.base import uuid7  # local: this module is imported by the worker too

    written = 0
    highest: dict[UUID, int] = {}
    for chunk in chunks:
        handle = active_caller_ref(tenant_id, chunk.phone_e164)
        await session.execute(
            text(_UPSERT_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "kind": projection.subject_kind,
                "sid": chunk.subject_id,
                "idx": chunk.idx,
                "call_id": chunk.call_id,
                "aid": chunk.agent_id,
                "ref": handle.ref,
                "kek": handle.kek_id,
                "first_turn": chunk.first_turn_idx,
                "last_turn": chunk.last_turn_idx,
                "category": projection.retention_category,
                "occurred_at": chunk.occurred_at,
                "body": chunk.text,
                "sha": content_digest(chunk.text),
            },
        )
        written += 1
        highest[chunk.subject_id] = max(highest.get(chunk.subject_id, 0), chunk.idx)

    for subject_id, last_idx in highest.items():
        await session.execute(
            text(_SUPERSEDE_SQL),
            {"kind": projection.subject_kind, "sid": subject_id, "last_idx": last_idx},
        )
    return written


__all__ = [
    "TS_CONFIG",
    "CallerProjection",
    "ChunkKey",
    "ContentFor",
    "Discover",
    "ProjectedChunk",
    "content_digest",
    "register_projection",
    "registered_projections",
    "store_chunks",
]
