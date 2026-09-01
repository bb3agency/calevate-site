"""Forgetting a caller from the vector store — the arm a CASCADE cannot be (D-503).

**THE ONE PROPERTY THIS MODULE EXISTS FOR.** An embedding of a caller's sentence is a COPY
of that sentence: it is derived from the text by a deterministic function of it and is
substantially invertible with the model, and the `tsv` beside it is literally the caller's
lexemes. So an erasure that scrubs `transcript_turns.text_redacted`, empties
`call_extractions.data` and NULLs `calls.summary` has NOT finished — the sentence is still
on file in the two forms nobody thinks to look at. Every arm here nulls the vector AND
empties the lexemes, and `ck_caller_chunks_forgotten_has_no_keys` refuses a row where one
of the two survived.

**AND IT CANNOT BE A CASCADE, WHICH IS THE TRAP THAT HAS BITTEN THIS REPOSITORY TWICE.**
A DPDP §12 erasure does not DELETE a call: it scrubs the call in place and keeps the row,
because the call is billing evidence (`usage_events` references it under FK RESTRICT). So
`ON DELETE CASCADE` on `call_id` reads like protection and never fires — the identical
sentence `insights/service.scrub_quotes_for_calls` had to be written to say about
`knowledge_gap_occurrences`. Both times the code looked correct and the arm was simply
absent. This module is the arm, and it is called EXPLICITLY from
`execute_deletion_request`, from `execute_tenant_erasure` and from the nightly sweep.

**THE PROJECTION AND ITS SOURCE ARE FORGOTTEN IN ONE PLACE, ON PURPOSE.** `caller_chunks`
holds the two derived keys and `caller_memories` holds the distilled fact they were built
from, and splitting their erasure across two modules is exactly the seam that goes missing:
one gets a new caller and the other does not, and the failure is silent for as long as
nobody looks. One module, one pair of statements, one count.

**THREE HANDLES, AND ALL THREE ARE NEEDED.** A §12 request holds a PHONE NUMBER.

* `subject_ref = ANY(caller_refs(tenant, number))` — the handle that always works, and the
  ONLY one caller memory has (its subject is a person across calls, not any one call).
  `caller_refs` returns EVERY KEK generation, newest first, so a key rotation costs one
  extra value in an index scan rather than costing the erasure every row written before it
  — a rotation must never be able to hide a row from a §12 request.
* `call_id = ANY(:calls)` — the belt for a projection whose ref was derived from the OTHER
  party's number on the same call.
* `subject_kind = 'lead' AND subject_id = ANY(:leads)` — the belt for a lead whose own
  number an earlier retention sweep already anonymized, so the ref no longer derives from
  anything the request can supply.

**IDEMPOTENT ON `scrubbed_at`.** Every statement here excludes rows it has already
scrubbed, so a re-run of an erasure (arq retries; `execute_deletion_request` re-enters
after a storage refusal rolled it back) counts the rows it actually changed rather than
reporting a second, larger figure for work the first run did. Same rule as
`call_extractions.scrubbed_at` and `scrub_quotes_for_calls`.

HARD RULE 6: nothing here logs a number, a ref or a sentence. A `subject_ref` is a pointer
to a person and is treated as personal data, not as a safe identifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_ref import caller_refs, ring_covers
from apps.api.db.result import rowcount_of
from apps.api.retrieval.models import (
    EMBED_ERASED,
    EMBED_EXPIRED,
    RETENTION_CALLER_MEMORY,
    SUBJECT_LEAD,
)


@dataclass(frozen=True, slots=True)
class CallerErasureCounts:
    """What one erasure actually forgot, in the two stores. Both go on the certificate.

    TWO NUMBERS AND NOT ONE, because they are two different facts a data principal is owed:
    `vectors` is how many searchable copies of their words were destroyed, `memories` is how
    many durable facts an agent had learned about them. A single total would let either be
    zero without a reader noticing.
    """

    vectors: int
    memories: int

    def total(self) -> int:
        return self.vectors + self.memories


#: THE PROJECTION SCRUB. Both keys go, `content_sha256` goes with them (it is derived from
#: text that no longer exists here, and leaving it would let a re-discovery of an
#: unchanged source decide nothing had changed), and `scrubbed_at` records the fact.
#:
#: The row is KEPT and emptied rather than deleted, for two reasons that both matter:
#: `scrub_quotes_for_calls`' — a delete would silently move a client's analytics as a side
#: effect of a stranger's erasure — and one this table has of its own: the ingestion sweep
#: DISCOVERS its own work, so a deleted row would be re-projected on the next tick and a
#: vector re-bought for text the erasure had just destroyed. The tombstone is what makes
#: the forgetting durable, and `caller_projections._UPSERT_SQL` refuses to revive it.
_SCRUB_CHUNKS_SQL: Final = f"""
UPDATE caller_chunks
   SET embedding = NULL, embed_model = NULL, embed_dim = NULL, tsv = ''::tsvector,
       content_sha256 = '', embed_state = :state, scrubbed_at = now(), updated_at = now()
 WHERE scrubbed_at IS NULL
   AND (:all_rows
        OR subject_ref = ANY(:refs)
        OR call_id = ANY(:calls)
        OR (subject_kind = '{SUBJECT_LEAD}' AND subject_id = ANY(:leads)))
"""

#: THE SOURCE SCRUB. `fact = ''` and never NULL: the column is NOT NULL and
#: `ck_caller_memories_scrubbed_is_empty` pairs the two, so a reader has ONE empty value to
#: test rather than two. `source_call_id` is provenance and is deliberately NOT cleared —
#: it names no person, and keeping it is what lets an auditor see WHICH call a forgotten
#: fact came from without the fact itself surviving.
_SCRUB_MEMORIES_SQL: Final = """
UPDATE caller_memories
   SET fact = '', scrubbed_at = now(), updated_at = now()
 WHERE scrubbed_at IS NULL
   AND (:all_rows OR subject_ref = ANY(:refs) OR source_call_id = ANY(:calls))
"""


async def _scrub(
    session: AsyncSession,
    *,
    refs: Sequence[str],
    call_ids: Sequence[UUID],
    lead_ids: Sequence[UUID],
    all_rows: bool,
    state: str,
) -> CallerErasureCounts:
    """Both statements, one transaction, one pair of counts. The only writer of either."""
    params = {
        "refs": list(refs),
        "calls": list(call_ids),
        "leads": list(lead_ids),
        "all_rows": all_rows,
    }
    chunks = await session.execute(text(_SCRUB_CHUNKS_SQL), {**params, "state": state})
    memories = await session.execute(text(_SCRUB_MEMORIES_SQL), params)
    return CallerErasureCounts(
        vectors=int(rowcount_of(chunks) or 0), memories=int(rowcount_of(memories) or 0)
    )


async def erase_subject_vectors(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone: str,
    call_ids: Sequence[UUID] = (),
    lead_ids: Sequence[UUID] = (),
) -> CallerErasureCounts:
    """Forget ONE data principal from both caller stores. Returns what was forgotten.

    RAISES `CallerRefError` for a number that is not canonical E.164, and that is the right
    direction rather than a rough edge: the alternative is deriving no ref, matching
    nothing, and letting `execute_deletion_request` write a certificate saying "removed"
    over a durable profile that is still there. The raise rolls the erasure's whole
    transaction back, `completed_at` stays NULL and the idempotency guard lets the retry
    redo it — the shape `_erase_delivery_bodies` already uses for the same reason.

    The refs come from `caller_refs`, which walks EVERY key generation. A deployment that
    dropped an undecodable `PLATFORM_KEK_RETIRED` can no longer derive the refs its older
    rows are filed under — that is a real hole and it is NOT papered over here; it is
    surfaced by `unreachable_generations()` on every nightly sweep, because an erasure is
    the wrong moment to discover it and a count is the only thing anyone can act on.
    """
    return await _scrub(
        session,
        refs=caller_refs(tenant_id, phone),
        call_ids=call_ids,
        lead_ids=lead_ids,
        all_rows=False,
        state=EMBED_ERASED,
    )


async def erase_tenant_vectors(session: AsyncSession, *, tenant_id: UUID) -> CallerErasureCounts:
    """Forget EVERY caller this tenant holds, at the end of the engagement.

    UNCONDITIONAL — every row, not a match-and-scrub — for `execute_tenant_erasure`'s
    `copilot_memories` reason: there is no subject to match on when the subject is "all of
    them", and a predicate would leave behind exactly the rows whose number some earlier
    sweep had already anonymized. `tenant_id` is not in the statement because the session's
    FORCEd `tenant_isolation` policy is the scope (hard rule 1); it is taken as an argument
    so the caller's scope is explicit at the call site and reaches the log line.
    """
    return await _scrub(
        session, refs=(), call_ids=(), lead_ids=(), all_rows=True, state=EMBED_ERASED
    )


#: THE RETENTION ARM for the projection, batched by `retention._sweep_in_batches` — one
#: category at a time, oldest first, so a batch is an index range on
#: `ix_caller_chunks_retention` rather than a sort of everything the tenant holds.
#:
#: `embed_state = 'expired'` rather than `'erased'`: both are terminal and both empty the
#: same two keys, and they are two values because an operator asking "did this account's
#: data age out, or did somebody ask to be forgotten" cannot answer it from one.
EXPIRE_CHUNKS_SQL: Final = f"""
UPDATE caller_chunks
   SET embedding = NULL, embed_model = NULL, embed_dim = NULL, tsv = ''::tsvector,
       content_sha256 = '', embed_state = '{EMBED_EXPIRED}', scrubbed_at = now(),
       updated_at = now()
 WHERE id IN (
   SELECT id FROM caller_chunks
    WHERE retention_category = :category AND scrubbed_at IS NULL AND occurred_at < :cutoff
    ORDER BY occurred_at LIMIT :batch)
"""

#: THE RETENTION ARM for the source. On the TRANSCRIPT clock and no other: a memory is
#: distilled from what the caller said, so it belongs to the clock of the words it was
#: distilled from — `calls.summary`'s argument, one table over — and the category is
#: asserted by the caller rather than parameterised so a future `lead` sweep cannot reach
#: this table by passing its own name.
EXPIRE_MEMORIES_SQL: Final = """
UPDATE caller_memories
   SET fact = '', scrubbed_at = now(), updated_at = now()
 WHERE id IN (
   SELECT id FROM caller_memories
    WHERE scrubbed_at IS NULL AND occurred_at < :cutoff
    ORDER BY occurred_at LIMIT :batch)
"""

#: The category `EXPIRE_MEMORIES_SQL` may be run under. Named here so the sweep's arm reads
#: as a decision rather than as a coincidence of which branch it sits in.
#:
#: **D-507 MOVED IT OFF THE TRANSCRIPT CLOCK**, and this line used to say
#: `RETENTION_TRANSCRIPT`. Riding the transcript's tenant-set default (365 days) meant a
#: distilled fact about a caller outlived the conversation it was distilled from as a
#: matter of design; `copilot_memory` had already answered the same question at 180 days
#: and `delete`, for reasons that transfer intact — nothing depends on these rows, use
#: regenerates them, and there is no anonymised form of a sentence. What does not transfer
#: is who the subject is: a copilot memory is about the client's own staff using a product
#: they bought, and this is about a caller who never chose us, which is the argument for
#: taking the shorter clock rather than the longer one when the two disagreed.
MEMORY_RETENTION_CATEGORY: Final = RETENTION_CALLER_MEMORY

_UNREACHABLE_SQL: Final = """
SELECT DISTINCT subject_ref_kek_id FROM caller_chunks WHERE scrubbed_at IS NULL
UNION
SELECT DISTINCT subject_ref_kek_id FROM caller_memories WHERE scrubbed_at IS NULL
"""


async def unreachable_generations(session: AsyncSession) -> tuple[int, ...]:
    """KEK generations this deployment can no longer derive refs under. Empty is healthy.

    **A NON-EMPTY ANSWER MEANS ROWS ARE UNREACHABLE BY ERASURE**, and it has exactly one
    cause: `envelope.build_ring` DROPS an undecodable `PLATFORM_KEK_RETIRED` with a log
    line rather than refusing to boot — right for a deployment that must keep serving, and
    fatal here, because the dropped generation is precisely the one whose rows a §12
    request can no longer address. `caller_refs` would derive the wrong values, the
    predicate would match nothing, and the certificate would report zero.

    A DISTINCT over a partial index rather than a per-row check: there are as many values
    as there have been rotations, so this is a handful of rows however large the store is,
    which is what makes it affordable on every nightly tick — and the tick is the right
    moment, because an erasure is the wrong one to discover it in.
    """
    rows = (await session.execute(text(_UNREACHABLE_SQL))).scalars().all()
    return tuple(sorted(int(kek) for kek in rows if not ring_covers(int(kek))))


def erasure_sentence(counts: CallerErasureCounts, *, scrubbed_at: datetime | None = None) -> str:
    """The `actions` line the erasure certificate carries, in words a client can act on.

    Written HERE rather than in the worker so the two erasure paths cannot describe the
    same work differently — and phrased around the SENTENCE rather than around the vector,
    because "6 embeddings were nulled" tells a data principal nothing about whether their
    words are gone.
    """
    when = "" if scrubbed_at is None else f" on {scrubbed_at.isoformat()}"
    return (
        f"{counts.vectors} searchable projection(s) of this person's words destroyed"
        f"{when}: the embedding and the keyword index were both emptied, so the sentence "
        "survives in neither form; "
        f"{counts.memories} remembered fact(s) about them erased from the agent's "
        "cross-call memory"
    )


__all__ = [
    "EXPIRE_CHUNKS_SQL",
    "EXPIRE_MEMORIES_SQL",
    "MEMORY_RETENTION_CATEGORY",
    "CallerErasureCounts",
    "erase_subject_vectors",
    "erase_tenant_vectors",
    "erasure_sentence",
    "unreachable_generations",
]
