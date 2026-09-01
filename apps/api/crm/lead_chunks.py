"""The LEAD scope of the caller-chunk store: what it discovers, and how it is forgotten.

`crm/lead_projection.py` decides WHAT a lead contributes (a pure function, no SQL). This is
the seam between that decision and the shared machinery: the `CallerProjection` the sweep
runs, and the two statements that make a lead's vectors reachable by an erasure and by a
retention clock.

--------------------------------------------------------------------------------
ONE SWEEP, ONE CLAIM, ONE PRICE CHECK — SO THIS SCOPE OWNS NO SWEEP
--------------------------------------------------------------------------------
`register_projection` hands `apps/workers/caller_embeddings.py` two callables and nothing
else. The transaction, the `FOR UPDATE ... SKIP LOCKED` claim, the per-tick and per-tenant
budgets, `embedding_price_is_billable()` before any provider call and the `usage_events`
row all stay there, for every scope at once. A second sweep here would be a second place to
get hard rule 7 right and a second budget that does not know about the first.

--------------------------------------------------------------------------------
DISCOVERY: WHAT IS MISSING, AND HOW IT STOPS ASKING
--------------------------------------------------------------------------------
A lead needs projecting when it has no projection at all, or when it was edited after the
one it has (`occurred_at < leads.updated_at` — `occurred_at` IS the lead's own clock, so
the comparison is with the value the last projection copied).

**THE UNCHANGED-BUT-TOUCHED LEAD IS THE CASE THIS SECTION EXISTS FOR.** `leads.updated_at`
moves on a status change, an assignment, and every call that increments `call_count` — none
of which changes a single projected field. The shared upsert refuses to rewrite a row whose
`content_sha256` is unchanged (rightly: it would re-buy the corpus nightly), so that lead
would match the staleness predicate again on the next tick, and for ever — a fixed prefix
of leads that consumes the discovery budget and starves everything behind it.

So a candidate whose every chunk hashes to what is already stored is STAMPED rather than
re-projected: `_TOUCH_SQL` advances `occurred_at` to the lead's `updated_at` and writes no
key. It is `kb_documents.gloss_state = 'not_needed'`'s argument — a settled answer that the
absence of a value cannot express — and it is independently REQUIRED rather than a trick:
`occurred_at` is what the retention sweep dates this row by, `_LEAD_SQL` dates the lead by
`updated_at`, and the two must be the same instant or the projection outlives its source.

--------------------------------------------------------------------------------
THE FIELDS COME FROM THE SCHEMA THE LEAD WAS CAPTURED UNDER
--------------------------------------------------------------------------------
`leads.data` is keyed by `leads.schema_version`, and a client edits their capture list. So
this reads `extraction_schemas` at (agent_id, version) rather than taking the latest, and
falls back to the latest only when the lead names no version. Projecting a v3 field list
over a v1 payload would drop every key that was renamed — silently, since an unknown key
is dropped by design (`lead_projection`) — and the client's oldest leads would quietly stop
being searchable.

--------------------------------------------------------------------------------
HOW THESE ROWS ARE REACHED BY AN ERASURE, AND WHY THIS SCOPE OWNS NO ARM
--------------------------------------------------------------------------------
An embedding of a caller's words is a copy of those words, so emptying `leads.data` and
leaving the vector behind leaves the sentence on file in the one form nobody looks at. Two
facts make that a live hazard here rather than a theoretical one:

1. **A DPDP erasure does not DELETE a lead.** It anonymizes it in place — `phone_e164`
   prefixed, `name = NULL`, `data = '{}'::jsonb` — because `lead_events` and `calls`
   reference it. There is no delete for a `CASCADE` to follow, so a projection relying on
   one would survive every erasure this product performs.
2. **After that anonymisation the number is gone**, so a handle derived FROM the number
   can no longer be derived at all.

`retrieval/caller_erasure.py` answers both, for every scope at once, and this module's job
is to make sure a lead's rows are addressable by what it does rather than to write a second
copy of it. Three handles, and the lead scope needs all three to be filled correctly HERE:

* `subject_ref` — the keyed MAC of the caller's number, minted by `store_chunks` from the
  `phone_e164` this module puts on every `ProjectedChunk`. It is why the number is a
  REQUIRED field of the projection rather than an optional one.
* `subject_id = leads.id` under `subject_kind = 'lead'` — the belt for the anonymized lead
  above, which no ref can reach. `execute_deletion_request` resolves a number to lead ids
  and passes them to `erase_subject_vectors(lead_ids=...)`.
* the tenant-wide arm (`erase_tenant_vectors`), which needs no handle at all.

RETENTION is `caller_erasure.EXPIRE_CHUNKS_SQL` on the `lead` category — the clock this
scope's rows carry in `occurred_at`, which is the lead's own `updated_at` and therefore the
same instant `retention._LEAD_SQL` anonymizes the lead itself. Keeping those two in step is
what the "looked at, nothing owed" stamp above is for, and it is the reason that stamp is a
correctness requirement rather than an optimisation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.lead_projection import LEAD_SUBJECT_KIND, project_lead
from apps.api.retrieval.caller_projections import (
    CallerProjection,
    ChunkKey,
    ProjectedChunk,
    content_digest,
    register_projection,
)

#: How many leads one discovery pass may look at before it filters. Deliberately larger
#: than the sweep's own `limit`: most candidates in a busy account are unchanged-but-touched
#: rows that this pass stamps and drops, so a window equal to the limit would return almost
#: nothing on exactly the accounts that need it most.
_CANDIDATE_FANOUT: Final = 4

#: Candidates, oldest edit first. Two arms: never projected, or edited since it was.
#:
#: `l.data <> '{}'` is the BELT against re-projecting an erased lead (`lead_projection`
#: yields nothing for an empty payload anyway, and the shared upsert refuses to revive a
#: scrubbed row — three guards, deliberately, on the one property this store exists for).
#:
#: The stale arm requires `c.scrubbed_at IS NULL`: a lead whose projection was erased or
#: expired must NOT come back as "stale", which is what would happen if the predicate only
#: compared clocks.
_CANDIDATE_SQL: Final = f"""
SELECT l.id, l.agent_id, l.phone_e164, l.data, l.updated_at, l.schema_version
FROM leads l
WHERE l.deleted_at IS NULL
  AND l.data IS NOT NULL AND l.data <> '{{}}'::jsonb
  AND (
    NOT EXISTS (
      SELECT 1 FROM caller_chunks c
      WHERE c.subject_kind = '{LEAD_SUBJECT_KIND}' AND c.subject_id = l.id)
    OR EXISTS (
      SELECT 1 FROM caller_chunks c
      WHERE c.subject_kind = '{LEAD_SUBJECT_KIND}' AND c.subject_id = l.id
        AND c.scrubbed_at IS NULL AND c.occurred_at < l.updated_at)
  )
ORDER BY l.updated_at
LIMIT :limit
"""

#: What is already stored for these leads, so an unchanged chunk is neither re-hashed
#: downstream nor re-offered to the sweep.
_STORED_SQL: Final = f"""
SELECT subject_id, idx, content_sha256 FROM caller_chunks
WHERE subject_kind = '{LEAD_SUBJECT_KIND}' AND subject_id = ANY(:ids) AND scrubbed_at IS NULL
"""

#: "Looked at, nothing owed." See the module docstring — this is what stops a lead whose
#: `updated_at` moved without its captured fields changing from being re-discovered for
#: ever. It writes no retrieval key, so it cannot resurrect anything.
_TOUCH_SQL: Final = f"""
UPDATE caller_chunks SET occurred_at = :occurred_at, updated_at = now()
WHERE subject_kind = '{LEAD_SUBJECT_KIND}' AND subject_id = :sid
  AND scrubbed_at IS NULL AND occurred_at < :occurred_at
"""

#: The schema the lead was CAPTURED under, by version; the latest when it names none.
_SCHEMA_SQL: Final = """
SELECT fields FROM extraction_schemas
WHERE agent_id = :aid AND (:ver IS NULL OR version = :ver)
ORDER BY version DESC LIMIT 1
"""


async def _fields_for(
    session: AsyncSession, agent_id: UUID, version: int | None
) -> list[ExtractionField]:
    row = (await session.execute(text(_SCHEMA_SQL), {"aid": agent_id, "ver": version})).first()
    if row is None or not row[0]:
        return []
    return [ExtractionField.model_validate(f) for f in row[0]]


async def _project(
    session: AsyncSession, rows: Sequence[Any]
) -> dict[UUID, tuple[Any, list[tuple[int, str, tuple[str, ...]]]]]:
    """Every candidate lead's chunks, keyed by lead id. One schema read per (agent, version)."""
    schemas: dict[tuple[UUID, int | None], list[ExtractionField]] = {}
    out: dict[UUID, tuple[Any, list[tuple[int, str, tuple[str, ...]]]]] = {}
    for row in rows:
        agent_id = UUID(str(row[1]))
        version = None if row[5] is None else int(row[5])
        key = (agent_id, version)
        if key not in schemas:
            schemas[key] = await _fields_for(session, agent_id, version)
        projection = project_lead(schemas[key], row[3])
        out[UUID(str(row[0]))] = (
            row,
            [(chunk.idx, chunk.text, chunk.keys) for chunk in projection.chunks],
        )
    return out


async def discover_lead_chunks(session: AsyncSession, limit: int) -> Sequence[ProjectedChunk]:
    """Leads whose projection is missing or out of date, oldest edit first.

    Runs inside the tenant's RLS session (the sweep opens it), so tenancy is the session and
    never a predicate here — the one exception being that every statement above names
    `subject_kind`, which is scope and not tenancy.
    """
    rows = (
        await session.execute(text(_CANDIDATE_SQL), {"limit": max(1, limit) * _CANDIDATE_FANOUT})
    ).all()
    if not rows:
        return []
    projected = await _project(session, rows)
    stored = {
        (UUID(str(r[0])), int(r[1])): str(r[2])
        for r in (await session.execute(text(_STORED_SQL), {"ids": list(projected)})).all()
    }

    chunks: list[ProjectedChunk] = []
    for lead_id, (row, produced) in projected.items():
        changed = [
            (idx, body)
            for idx, body, _keys in produced
            if stored.get((lead_id, idx)) != content_digest(body)
        ]
        if not changed:
            # Looked at, nothing owed — stamp the clock so this lead stops being a
            # candidate, and so its projection expires on the same instant it does.
            await session.execute(text(_TOUCH_SQL), {"sid": lead_id, "occurred_at": row[4]})
            continue
        chunks.extend(
            ProjectedChunk(
                subject_id=lead_id,
                idx=idx,
                text=body,
                agent_id=UUID(str(row[1])),
                # The number reaches `store_chunks` and is discarded there, having minted
                # the keyed `subject_ref` an erasure addresses this row by. It is never
                # stored and never logged.
                phone_e164=str(row[2]),
                occurred_at=row[4],
            )
            for idx, body in changed
        )
        if len(chunks) >= limit:
            break
    return chunks[:limit]


async def lead_chunk_content(
    session: AsyncSession, keys: Sequence[ChunkKey]
) -> Mapping[ChunkKey, str]:
    """The text for chunks the sweep has CLAIMED, re-read from `leads`.

    A second read rather than a value carried through the claim, because the store holds no
    content and the claim happens on `caller_chunks` — which is where `FOR UPDATE ... SKIP
    LOCKED` belongs, so two ticks cannot buy one vector twice. Re-reading also means a lead
    edited between discovery and the claim is embedded as it is NOW rather than as it was,
    which is the safe direction: the alternative buys a vector for a sentence that no longer
    exists.
    """
    lead_ids = sorted({subject_id for subject_id, _idx in keys})
    if not lead_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT l.id, l.agent_id, l.phone_e164, l.data, l.updated_at, l.schema_version "
                "FROM leads l WHERE l.id = ANY(:ids) AND l.deleted_at IS NULL "
                "AND l.data IS NOT NULL AND l.data <> '{}'::jsonb"
            ),
            {"ids": lead_ids},
        )
    ).all()
    projected = await _project(session, rows)
    wanted = set(keys)
    return {
        (lead_id, idx): body
        for lead_id, (_row, produced) in projected.items()
        for idx, body, _keys in produced
        if (lead_id, idx) in wanted
    }


#: THE REGISTRATION. Import this module and the lead scope is in the sweep; there is no
#: second place to add it and no flag that can leave it half-wired.
LEAD_PROJECTION: Final = register_projection(
    CallerProjection(
        subject_kind=LEAD_SUBJECT_KIND,
        discover=discover_lead_chunks,
        content_for=lead_chunk_content,
    )
)


__all__ = [
    "LEAD_PROJECTION",
    "discover_lead_chunks",
    "lead_chunk_content",
]
