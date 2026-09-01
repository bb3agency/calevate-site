"""The TRANSCRIPT scope's store half: discovery, re-read, and the two forgetting arms.

`call_projection.py` decides what a chunk IS (a window of turns, ending on an answer, with
the speaker labelled). This module is everything that touches the database on its behalf:
what needs projecting, how to read a claimed chunk's text back, and — the part that matters
more than the search — how a caller's sentence is reached when they ask to be forgotten and
when the tenant's retention clock runs out.

--------------------------------------------------------------------------------
THE PREMISE: AN EMBEDDING OF A CALLER'S SENTENCE IS A COPY OF THAT SENTENCE
--------------------------------------------------------------------------------
Not a figure of speech. The vector is a deterministic function of the text and is
substantially invertible with the model; `caller_chunks.tsv` is literally the caller's
lexemes. So "the transcript was scrubbed" is not the same statement as "the sentence is
gone", and this module is where the second one is made true.

**A `CASCADE` ON `call_id` DOES NOT DO IT, AND THIS IS THE MISTAKE THAT SHIPPED TWICE.**
A DPDP erasure does not DELETE a call — `execute_deletion_request` overwrites
`transcript_turns.text` / `.text_redacted` with `retention.REDACTED_MARK`, sets
`calls.summary = NULL` and KEEPS the row, because a call is billing evidence
(`usage_events` references it under FK RESTRICT). Nothing is deleted, so a cascade never
fires. `insights/service.scrub_quotes_for_calls` exists because exactly this happened to
the knowledge-gap quotes; `retention.DERIVED_COPIES` exists because exactly this happened
to `calls.summary`. This scope is the third instance of the same shape, and the response is
the same one that worked: an EXPLICIT arm, called by name from both erasure paths and from
the retention sweep.

**AND THE RETENTION CLOCK IS THE OTHER HALF.** An erasure is a request somebody makes; a
retention period is a promise made to every caller who never makes one. A table no
`retention_policies.data_category` names never expires, so these rows carry
`retention_category = 'transcript'` — set by `caller_projections.CallerProjection`, which
derives it from `models.SUBJECT_RETENTION` rather than letting this scope choose — and
`expire_transcript_projections` is the arm that reads it.

--------------------------------------------------------------------------------
SCRUBBED, NOT DELETED — THE TOMBSTONE IS THE POINT
--------------------------------------------------------------------------------
Both arms EMPTY the row and set `scrubbed_at`; neither deletes it. `scrub_quotes_for_calls`
keeps its row so a client's analytics do not silently move under a stranger's erasure; here
the reason is sharper still — **discovery re-projects anything with no live projection**, so
deleting the row would let the next tick re-project the call and re-buy a vector for text
the erasure had just destroyed. Money spent to undo a legal obligation, on a certificate
already signed. The tombstone is what makes the forgetting durable, and
`caller_projections._UPSERT_SQL`'s `WHERE caller_chunks.scrubbed_at IS NULL` is what honours
it.

`ck_caller_chunks_forgotten_has_no_keys` is the database's own check that an emptied row
really has no keys left, so neither arm can half-forget a row even if this module is wrong.

--------------------------------------------------------------------------------
WHAT DISCOVERY REFUSES TO PROJECT
--------------------------------------------------------------------------------
A call with no usable turn, and a call whose caller number is gone. The second is not a
convenience: `caller_chunks.subject_ref` is the KEYED handle an erasure derives from the
number, and `execute_deletion_request` NULLs `from_e164`/`to_e164`. A call with no number
is therefore either already erased or was never dialled by anyone we can name, and a row
filed under no subject would be a row a future §12 request could not reach by subject at
all. Refusing to write it is cheaper than any recovery.

HARD RULE 6: no turn text, no summary, no phone number and no `subject_ref` reaches a log
line here. Ids and counts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.performance import IST_ZONE
from apps.api.db.result import rowcount_of
from apps.api.retrieval.call_projection import (
    SUBJECT_KIND_SUMMARY,
    SUBJECT_KIND_TURNS,
    SUBJECT_KINDS,
    CallChunk,
    Turn,
    label_turn,
    project_call,
    subject_id_for,
)
from apps.api.retrieval.caller_projections import (
    CallerProjection,
    ChunkKey,
    ProjectedChunk,
    register_projection,
)
from apps.api.retrieval.caller_search import CallerHit
from apps.api.retrieval.models import EMBED_ERASED, EMBED_EXPIRED, RETENTION_TRANSCRIPT

#: `retention.REDACTED_MARK`, spelled again rather than imported.
#:
#: `apps/workers/retention.py` is the module whose erasure arm CALLS this one, so importing
#: it back would be the cycle `compliance/caller_ref.py` already routes around for
#: `ANONYMIZED_PHONE` — same trade, same mitigation: the duplication is pinned against the
#: original by `tests/caller_chunk_erasure_test.py`, which fails the day either moves.
#:
#: It matters here in two places and both are the same property: discovery must not offer an
#: erased call, and `project_call` must yield nothing for an erased turn. Belt and braces
#: around a re-projection racing an erasure.
REDACTED_MARK: Final = "[erased]"

#: `retention.DERIVED_COPIES["transcript"]` gains these two entries — THE LINE TO ADD, and
#: it is spelled here so the scope that creates the copies is the scope that names them.
#:
#: They are two entries and not one because `DERIVED_COPIES` is read by humans as the
#: policy statement of what the transcript clock owns, and "the vectors of the turns" and
#: "the vector of the summary" are two derived copies of two different things, exactly as
#: `calls.summary` and `knowledge_gap_occurrences.question_redacted` are listed apart.
DERIVED_COPIES_ENTRIES: Final[tuple[str, ...]] = (
    "caller_chunks.tsv[call_turn]",
    "caller_chunks.tsv[call_summary]",
)

#: The caller's own number on a call. `from_e164` inbound, `to_e164` outbound — the OTHER
#: party in both cases, never our client's line. Getting this backwards would file every
#: projection of an outbound campaign under the tenant's own DID, which is one `subject_ref`
#: for every campaign call and an erasure that matches a whole campaign or nothing.
_CALLER_NUMBER: Final = "CASE WHEN c.direction = 'inbound' THEN c.from_e164 ELSE c.to_e164 END"

#: `retention._call_clock('c')`, spelled again rather than imported, and the duplication is
#: deliberate: `apps/workers/retention.py` imports this module's siblings, and reaching back
#: into the worker for a SQL fragment is the cycle `compliance/dnc.py` already routes
#: around. `tests/caller_chunk_erasure_test.py` pins the two against each other.
#:
#: WHY IT IS NOT SIMPLY `ended_at`: that column is nullable and VENDOR-SUPPLIED, so a call
#: the engine never dated has a NULL clock, matches no cutoff, and would keep its vector for
#: ever with nothing to see. The fallback assumes the LATEST moment the call plausibly
#: ended, which retains slightly too long rather than expiring too early.
_CLOCK: Final = (
    "COALESCE(c.ended_at, c.created_at + make_interval(secs => COALESCE(c.duration_s, 0)))"
)

#: Calls whose projection is missing or older than the call itself, oldest first.
#:
#: **SELF-HEALING RATHER THAN ENQUEUED**, for `kb_embeddings.py`'s reason: a lost job, a
#: provider outage, a call ingested before this feature existed and a call whose transcript
#: was corrected later all converge on the next tick with no reconciliation code of their
#: own. `content_sha256` is what stops that costing anything — an unchanged chunk does not
#: return to `pending`, so a nightly re-discovery over the whole corpus buys nothing.
#:
#: `NOT EXISTS (... k.updated_at >= c.updated_at)` and not `NOT EXISTS (... )`: a call whose
#: transcript was re-driven (the post-call pipeline is re-entrant by design, D-31) has to be
#: re-projected, and its projection's age is the only signal available that says so.
#: An ERASED call is excluded twice over — its turns are the marker, so `project_call`
#: yields nothing, and its number is NULL, so this statement does not return it at all.
_DISCOVER_SQL: Final = f"""
SELECT c.id, c.agent_id, {_CALLER_NUMBER} AS caller_number, {_CLOCK} AS occurred_at,
       c.summary
FROM calls c
WHERE {_CALLER_NUMBER} IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM transcript_turns t
    WHERE t.call_id = c.id AND t.text_redacted IS NOT NULL
      AND btrim(t.text_redacted) <> '' AND t.text_redacted <> :mark)
  AND NOT EXISTS (
    SELECT 1 FROM caller_chunks k
    WHERE k.call_id = c.id AND k.subject_kind = :kind
      AND k.updated_at >= c.updated_at)
ORDER BY {_CLOCK}
LIMIT :limit
"""

_TURNS_SQL: Final = (
    "SELECT call_id, idx, speaker, text_redacted FROM transcript_turns "
    "WHERE call_id = ANY(:ids) ORDER BY call_id, idx"
)

_CALLS_SQL: Final = f"""
SELECT c.id, c.agent_id, {_CALLER_NUMBER} AS caller_number, {_CLOCK} AS occurred_at,
       c.summary
FROM calls c WHERE c.id = ANY(:ids)
"""

#: The calls behind a set of claimed chunks. `content_for` cannot invert a uuid5, so it asks
#: the store which call each claimed row belongs to and re-projects that call — which is
#: also the only way to be sure the text it hands the sweep is the text the row's
#: `content_sha256` was computed from, rather than a second derivation that could drift.
_CLAIMED_CALLS_SQL: Final = (
    "SELECT DISTINCT call_id FROM caller_chunks "
    "WHERE subject_kind = ANY(:kinds) AND subject_id = ANY(:sids) AND call_id IS NOT NULL"
)

#: **THE ERASURE ARM.** Empties both retrieval keys and tombstones the row, for every
#: projection of these calls, in the caller's tenant session.
#:
#: `scrubbed_at` and `embed_state` move together with the keys in ONE statement, because the
#: window between "the vector is gone" and "the row says so" is a window in which the
#: discovery statement would re-project the call. There is no such window here.
#:
#: IDEMPOTENT — `scrubbed_at IS NULL` — for `scrub_quotes_for_calls`' reason: a re-run of an
#: erasure must not report a second, larger count for work the first one already did, and
#: an erasure IS re-run (the pipeline is re-entrant, and a certificate can be reissued).
_ERASE_SQL: Final = f"""
UPDATE caller_chunks
   SET embedding = NULL, embed_model = NULL, embed_dim = NULL, tsv = ''::tsvector,
       content_sha256 = '', embed_state = '{EMBED_ERASED}', scrubbed_at = now(),
       updated_at = now()
 WHERE call_id = ANY(:ids) AND subject_kind = ANY(:kinds) AND scrubbed_at IS NULL
"""

#: **THE RETENTION ARM.** The same emptying, on the transcript clock, batched.
#:
#: KEYED ON `occurred_at` AND `retention_category`, which is the index the migration built
#: (`ix_caller_chunks_retention`) — NOT on a join to `calls`. The clock is carried on the
#: row precisely so this statement does not have to know which of four tables a row projects,
#: and so a row whose call was deleted still expires.
#:
#: `embed_state = 'expired'` and not `'erased'`: the two are different facts about the same
#: emptied row, and an operator asking "did this age out or did somebody ask" cannot answer
#: it from one value.
_EXPIRE_SQL: Final = f"""
UPDATE caller_chunks
   SET embedding = NULL, embed_model = NULL, embed_dim = NULL, tsv = ''::tsvector,
       content_sha256 = '', embed_state = '{EMBED_EXPIRED}', scrubbed_at = now(),
       updated_at = now()
 WHERE id IN (
   SELECT id FROM caller_chunks
    WHERE retention_category = :category AND subject_kind = ANY(:kinds)
      AND occurred_at < :cutoff AND scrubbed_at IS NULL
    ORDER BY occurred_at LIMIT :batch)
"""


async def _projected(
    session: AsyncSession, call_ids: Sequence[UUID]
) -> dict[UUID, list[tuple[CallChunk, UUID, UUID, str, datetime]]]:
    """Re-project these calls: chunk → (chunk, call_id, agent_id, number, clock)."""
    if not call_ids:
        return {}
    ids = list(call_ids)
    heads = {
        UUID(str(row[0])): (UUID(str(row[1])), str(row[2]), row[3], row[4])
        for row in (await session.execute(text(_CALLS_SQL), {"ids": ids})).all()
        if row[2] is not None
    }
    turns: dict[UUID, list[Turn]] = {call_id: [] for call_id in heads}
    for row in (await session.execute(text(_TURNS_SQL), {"ids": list(heads)})).all():
        turns[UUID(str(row[0]))].append(
            Turn(idx=int(row[1]), speaker=str(row[2]), text_redacted=row[3])
        )

    out: dict[UUID, list[tuple[CallChunk, UUID, UUID, str, datetime]]] = {}
    for call_id, (agent_id, number, occurred_at, summary) in heads.items():
        chunks = project_call(turns[call_id], summary=summary, mark=REDACTED_MARK)
        if chunks:
            out[call_id] = [(chunk, call_id, agent_id, number, occurred_at) for chunk in chunks]
    return out


async def _discover(session: AsyncSession, limit: int, kind: str) -> Sequence[ProjectedChunk]:
    """Every chunk of ONE kind this tenant owes the store, oldest call first, in budget.

    **PER KIND, and that is not a nicety.** `store_chunks` writes whatever a scope returns
    under THAT scope's `subject_kind`, so one discovery returning both kinds would file
    summaries under `call_turn` — a discriminator that lies, which is worse than a missing
    row because every reader downstream believes it.

    The budget is a CHUNK budget and calls are taken whole: half a call would be discovered
    again on the next tick as a call whose projection is older than it is, which is correct
    and pays the discovery twice. So the loop stops before the first call that would
    overrun rather than splitting one — unless nothing has been taken yet, in which case a
    single over-budget call is taken rather than never taken at all.
    """
    rows = (
        await session.execute(
            text(_DISCOVER_SQL), {"mark": REDACTED_MARK, "kind": kind, "limit": limit}
        )
    ).all()
    projected = await _projected(session, [UUID(str(row[0])) for row in rows])

    out: list[ProjectedChunk] = []
    for row in rows:
        entries = [
            entry for entry in projected.get(UUID(str(row[0])), ()) if entry[0].subject_kind == kind
        ]
        if not entries:
            continue
        if out and len(out) + len(entries) > limit:
            break
        out.extend(_as_projected(entry) for entry in entries)
    return out


async def discover_turns(session: AsyncSession, limit: int) -> Sequence[ProjectedChunk]:
    """`caller_projections.Discover` for `call_turn`."""
    return await _discover(session, limit, SUBJECT_KIND_TURNS)


async def discover_summaries(session: AsyncSession, limit: int) -> Sequence[ProjectedChunk]:
    """`caller_projections.Discover` for `call_summary`."""
    return await _discover(session, limit, SUBJECT_KIND_SUMMARY)


def _as_projected(
    entry: tuple[CallChunk, UUID, UUID, str, datetime],
) -> ProjectedChunk:
    chunk, call_id, agent_id, number, occurred_at = entry
    return ProjectedChunk(
        subject_id=subject_id_for(call_id, chunk),
        idx=chunk.idx,
        text=chunk.text,
        agent_id=agent_id,
        phone_e164=number,
        occurred_at=occurred_at,
        call_id=call_id,
        first_turn_idx=chunk.first_turn_idx,
        last_turn_idx=chunk.last_turn_idx,
    )


async def content_for(session: AsyncSession, keys: Sequence[ChunkKey]) -> Mapping[ChunkKey, str]:
    """The text behind claimed chunks — RE-DERIVED from the turns, never stored.

    A uuid5 does not invert, so this asks the store which calls the claimed rows belong to
    and re-runs the SAME pure projection over their turns. That is stronger than a lookup
    would be: the text handed to the embedding provider is produced by the one function
    whose output `content_sha256` was computed from, so the two cannot drift.

    A key with no entry in the result is a chunk whose source has changed or been erased
    since it was claimed. It is OMITTED rather than filled with anything — the sweep must
    not buy a vector for text that no longer exists.
    """
    if not keys:
        return {}
    wanted = set(keys)
    call_ids = [
        UUID(str(row[0]))
        for row in (
            await session.execute(
                text(_CLAIMED_CALLS_SQL),
                {"kinds": list(SUBJECT_KINDS), "sids": [key[0] for key in keys]},
            )
        ).all()
    ]
    out: dict[ChunkKey, str] = {}
    for call_id, entries in (await _projected(session, call_ids)).items():
        for chunk, *_ in entries:
            key = (subject_id_for(call_id, chunk), chunk.idx)
            if key in wanted:
                out[key] = chunk.text
    return out


#: One line per hit, for a reader. `lead_id` is LEFT JOINed because most inbound callers
#: have no lead row and a hit that vanished for want of a name would be the truncation
#: `copilot/tools._listing` exists to make impossible.
_HEADS_SQL: Final = f"""
SELECT c.id, to_char({_CLOCK} AT TIME ZONE '{IST_ZONE}', 'DD Mon YYYY'), c.summary, l.name
FROM calls c LEFT JOIN leads l ON l.id = c.lead_id
WHERE c.id = ANY(:ids)
"""


async def describe_hits(
    session: AsyncSession, hits: Sequence[CallerHit], *, max_chars: int
) -> list[str]:
    """Search hits as lines a person (and a model) can read. NEVER `transcript_turns.text`.

    **THE HIT CARRIES NO TEXT AND THAT IS THE DESIGN** (`caller_search.CallerHit`): the
    store holds no content, so the words come back through THIS reader, over the same
    `text_redacted` column every other derived surface reads (hard rule 5). A search result
    therefore cannot become a side door onto the raw transcript, because the raw column is
    not named anywhere on this path.

    Ordered as the hits are — RRF order — and never re-sorted by date: the caller asked a
    question, and the best answer to it is the top line.
    """
    if not hits:
        return []
    call_ids = [hit.call_id for hit in hits if hit.call_id is not None]
    heads = {
        UUID(str(row[0])): (str(row[1]), row[2], row[3])
        for row in (await session.execute(text(_HEADS_SQL), {"ids": call_ids})).all()
    }
    turns: dict[UUID, dict[int, tuple[str, str]]] = {}
    for row in (await session.execute(text(_TURNS_SQL), {"ids": call_ids})).all():
        body = (row[3] or "").strip()
        if body and body != REDACTED_MARK:
            turns.setdefault(UUID(str(row[0])), {})[int(row[1])] = (str(row[2]), body)

    lines: list[str] = []
    for hit in hits:
        head = heads.get(hit.call_id) if hit.call_id is not None else None
        if head is None:
            # The call is gone (a `SET NULL` on `call_id`, or a tenant's transcript policy
            # deleted it). A hit with nothing to show is DROPPED rather than rendered as an
            # empty quote — the row is already emptied of keys, so this is the rare race
            # between a search and a sweep, not a state a reader needs told about.
            continue
        when, summary, lead_name = head
        who = f"{lead_name} on {when}" if lead_name else when
        passage = _passage(hit, turns.get(hit.call_id or UUID(int=0), {}), summary)
        if passage is None:
            continue
        lines.append(f"- {who} (call {str(hit.call_id)[:8]}): {passage[:max_chars]}")
    return lines


def _passage(
    hit: CallerHit, turns: Mapping[int, tuple[str, str]], summary: str | None
) -> str | None:
    """What this hit actually matched, re-read from the source. None when it is gone."""
    if hit.subject_kind == SUBJECT_KIND_SUMMARY:
        body = (summary or "").strip()
        return f"Summary: {body}" if body and body != REDACTED_MARK else None
    if hit.first_turn_idx is None or hit.last_turn_idx is None:
        return None
    said = [
        label_turn(speaker, body)
        for idx in range(hit.first_turn_idx, hit.last_turn_idx + 1)
        if (pair := turns.get(idx)) is not None
        for speaker, body in (pair,)
    ]
    return " / ".join(said) if said else None


async def erase_projections_for_calls(session: AsyncSession, *, call_ids: Sequence[UUID]) -> int:
    """**Called by BOTH erasure paths.** Empties every transcript projection of these calls.

    THE SIGNATURE IS `insights/service.scrub_quotes_for_calls`' SIGNATURE, deliberately:
    `execute_deletion_request` and `_erase_tenant_calls` already call that function with a
    list of call ids in the same transaction as the transcript scrub, so this drops in
    beside it with no new shape to learn and no new place for a caller to get it wrong.
    There is no `mark` parameter because this row has no text to mark — it has keys, and
    the answer to a key is emptiness rather than a marker.

    Returns the number of projections forgotten, FOR THE PROOF CERTIFICATE. A copy of the
    caller's sentence that this erasure destroyed has to be counted where the data principal
    can see it; a count only this file knows is a count that cannot be audited.
    """
    if not call_ids:
        return 0
    result = await session.execute(
        text(_ERASE_SQL), {"ids": list(call_ids), "kinds": list(SUBJECT_KINDS)}
    )
    return int(rowcount_of(result) or 0)


async def expire_transcript_projections(
    session: AsyncSession, *, cutoff: datetime, batch: int
) -> int:
    """**Called by the `transcript` arm of the retention sweep.** One batch.

    Batched and returning a count so `retention._sweep_in_batches` drives it exactly as it
    drives every other arm — same loop, same `TENANT_ROW_BUDGET`, same deferral when a
    tenant has more than one tick's worth.
    """
    result = await session.execute(
        text(_EXPIRE_SQL),
        {
            "category": RETENTION_TRANSCRIPT,
            "kinds": list(SUBJECT_KINDS),
            "cutoff": cutoff,
            "batch": batch,
        },
    )
    return int(rowcount_of(result) or 0)


#: Registered at import, once, for BOTH kinds a call contributes.
#:
#: Two registrations and not one, because `CallerProjection` is keyed by `subject_kind` and
#: the two kinds are separately searchable — a client asking "which callers asked about
#: weekend appointments" wants windows, and a client asking "which calls were about a
#: refund" wants summaries. They share every function below, so there is one implementation
#: and two entries rather than two implementations.
TURN_PROJECTION: Final = register_projection(
    CallerProjection(
        subject_kind=SUBJECT_KIND_TURNS, discover=discover_turns, content_for=content_for
    )
)
SUMMARY_PROJECTION: Final = register_projection(
    CallerProjection(
        subject_kind=SUBJECT_KIND_SUMMARY, discover=discover_summaries, content_for=content_for
    )
)


__all__ = [
    "DERIVED_COPIES_ENTRIES",
    "REDACTED_MARK",
    "SUMMARY_PROJECTION",
    "TURN_PROJECTION",
    "content_for",
    "describe_hits",
    "discover_summaries",
    "discover_turns",
    "erase_projections_for_calls",
    "expire_transcript_projections",
]
