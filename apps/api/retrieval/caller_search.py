"""Hybrid search over `caller_chunks` — ONE retriever for all three caller-data scopes.

`pgvector.py` is this query over a client's own published KNOWLEDGE. This is the same query
over what their CALLERS said, and it is one function rather than three because two
retrievers over one table is the second-way-to-do-one-thing defect: the tenancy predicate,
the RRF constant, the `SET LOCAL` discipline and the "an unembedded row still answers"
property would each have to be right in every copy.

--------------------------------------------------------------------------------
IT RETURNS REFERENCES, NOT PASSAGES — AND SO IT IS NOT A `RetrievalProvider`
--------------------------------------------------------------------------------
The `calevate_shared.retrieval` port is the KNOWLEDGE port: a `Passage` carries `text`, a
`Provenance` carries a `source_id` and a KB source's own name, and a `RetrievalTier` is
T0-T4 over published knowledge. This store deliberately holds NO CONTENT, so it cannot
produce a `Passage` without re-reading the caller's sentence out of the source table and
copying it into a result object — which is precisely the second copy the store exists to
avoid, and would put a caller's words behind a port whose whole vocabulary is "the client's
approved knowledge".

So a hit is a REFERENCE: which subject, in which call, at which turns, and how well it
scored. The scope that asked joins it back to its own table under its own access rules —
so `transcript_turns.text_redacted` is still what a client sees, still through the reader
that already applies hard rule 5, rather than through a search result that quietly bypassed
it. `capabilities.RetrievalCapabilities` is not declared here for the same reason: this
adapter answers a different question, and declaring `hybrid_search` on the knowledge port
for a store the port cannot read would be a capability claim about the wrong corpus.

--------------------------------------------------------------------------------
THE QUERY — `pgvector._SEARCH_SQL`'s SHAPE, AND EVERY REASON TRANSFERS
--------------------------------------------------------------------------------
A dense arm (`embedding <=> $q`, cosine) and a sparse arm (`ts_rank_cd`), each to
`_ARM_DEPTH`, fused by RECIPROCAL RANK FUSION at `k = 60` (Cormack/Clarke/Buettcher, SIGIR
2009) and cut to the caller's `k`. RRF rather than a weighted blend because cosine distance
and `ts_rank_cd` are different quantities on different scales, and any weighted sum has two
magic constants nobody has tuned on this corpus.

**THE SPARSE ARM MATTERS MORE HERE THAN IT DOES ON KNOWLEDGE.** A caller says a scheme
name, a locality, a doctor's name, an order number — rare proper nouns whose embedding is
not close to the embedding of a question about them. The client asking "who mentioned
Aarogyasri" is asking a lexical question, and the dense arm alone would answer it with
semantically-adjacent conversations that never said the word.

**A ROW WITH NO VECTOR STILL ANSWERS**, and here that is a compliance property as well as
an availability one: `embedding IS NULL` is the state of a row the sweep has not reached
AND of a row an erasure has emptied. The first still answers from its lexemes; the second
answers nothing, because its lexemes are gone too and `scrubbed_at` is excluded outright.

--------------------------------------------------------------------------------
HARD RULES
--------------------------------------------------------------------------------
Rule 1: the statement runs under the CALLER's RLS session AND re-states `tenant_id` as a
predicate — belt over braces, defending the one mistake RLS cannot see, a caller passing
tenant A's id on tenant B's session. A vector query that leaks is the worst kind of leak to
detect: it returns the NEAREST row in the fleet and looks like an excellent result.

Rule 6: the question is a person's prose about a caller and never reaches a log line; ids,
counts, kinds and elapsed milliseconds only.

Rule 7: the question's embedding is not bought unless its price is billable, and what is
bought is metered — both inside `embedding.embed_query_vector`, which is the one
implementation of that obligation for every search surface.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.retrieval.caller_projections import TS_CONFIG
from apps.api.retrieval.embedding import embed_query_vector, vector_literal
from apps.api.retrieval.models import SUBJECT_KINDS

log = get_logger(__name__)

#: How deep each arm ranks before fusion. `pgvector._ARM_DEPTH`, and the same argument: it
#: must be comfortably above any `k` a caller may ask for, or RRF is handed two lists that
#: are already the answer and has nothing to fuse.
_ARM_DEPTH: Final = 40

#: RRF's smoothing constant. Cormack, Clarke and Buettcher, SIGIR 2009 — the value every
#: mainstream implementation uses and the one `pgvector.py` already fuses with. Spelled
#: again rather than imported so this statement reads whole; `caller_search_test.py` pins
#: the two together.
_RRF_K: Final = 60

#: `hnsw.ef_search` for a query that DOES enter the graph, and ALWAYS `SET LOCAL`.
#: Session-level would be a defect rather than a style choice: these connections come out of
#: a pool, so the setting would outlive the request and silently re-tune every later query
#: on that connection — including another tenant's.
_EF_SEARCH: Final = 100

#: The ceiling on `k`. Higher than the knowledge port's 20 because the questions differ:
#: "which callers asked about weekend appointments" wants a LIST a person works through,
#: not three passages to quote. A caller asking for more than this is a bug, and the
#: adapter is where it stops rather than where it silently clamps.
MAX_K: Final = 50


@dataclass(frozen=True, slots=True)
class CallerHit:
    """One row of the answer: WHERE the match is, never WHAT it says.

    No text field, deliberately — see the module docstring. The scope joins this back to
    its own table through its own reader, so the redaction and role rules that already
    govern a transcript are the ones a search result goes through too.
    """

    subject_kind: str
    subject_id: UUID
    idx: int
    call_id: UUID | None
    agent_id: UUID
    #: The turn span, on a transcript window only. What lets a client's screen show the
    #: passage in place instead of handing them a call id and a reading task.
    first_turn_idx: int | None
    last_turn_idx: int | None
    #: The FUSED score. Comparable only WITHIN one result: an RRF score is a sum of
    #: reciprocal ranks, not a similarity, and nothing outside this call may threshold it.
    score: float


#: THE ONE STATEMENT. Read it as: scope, then two arms over the scope, then fusion.
#:
#: `scope` is a CTE rather than a repeated predicate so the tenancy filter is written ONCE
#: and both arms provably see the same rows — the alternative is two WHERE clauses that can
#: drift, on the predicate that IS hard rule 1.
#:
#: `scrubbed_at IS NULL` is in the scope and not in an arm, for the same reason: a forgotten
#: row must be invisible to BOTH keys, and a condition that lived in one arm would leave the
#: other able to return it. It is belt over braces — the erasure arm already emptied both
#: keys, and `ck_caller_chunks_forgotten_has_no_keys` refuses a row where it did not — but
#: this is the cheap third guard on the property the whole table exists for.
#:
#: `CAST(:aid AS uuid)` and not `::aid` — SQLAlchemy's `text()` consumes the second colon
#: itself and what reaches Postgres is a syntax error. The cast is required rather than
#: decorative: an untyped placeholder inside `IS NULL` gives the planner nothing to infer
#: from and it refuses the statement outright.
_SEARCH_SQL: Final = f"""
WITH scope AS (
  SELECT c.id, c.subject_kind, c.subject_id, c.idx, c.call_id, c.agent_id,
         c.first_turn_idx, c.last_turn_idx, c.embedding, c.tsv
  FROM caller_chunks c
  WHERE c.tenant_id = :tid
    AND c.scrubbed_at IS NULL
    AND c.subject_kind = ANY(:kinds)
    AND (CAST(:aid AS uuid) IS NULL OR c.agent_id = CAST(:aid AS uuid))
),
dense AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:qvec AS vector)) AS rnk
  FROM scope
  WHERE CAST(:qvec AS vector) IS NOT NULL AND embedding IS NOT NULL
  ORDER BY embedding <=> CAST(:qvec AS vector)
  LIMIT {_ARM_DEPTH}
),
sparse AS (
  SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC, id) AS rnk
  FROM scope, plainto_tsquery('{TS_CONFIG}', :question) q
  WHERE tsv @@ q
  ORDER BY ts_rank_cd(tsv, q) DESC, id
  LIMIT {_ARM_DEPTH}
),
fused AS (
  SELECT id, sum(1.0 / ({_RRF_K} + rnk)) AS score
  FROM (SELECT id, rnk FROM dense UNION ALL SELECT id, rnk FROM sparse) arms
  GROUP BY id
)
SELECT s.subject_kind, s.subject_id, s.idx, s.call_id, s.agent_id,
       s.first_turn_idx, s.last_turn_idx, f.score
FROM fused f
JOIN scope s ON s.id = f.id
ORDER BY f.score DESC, s.id
LIMIT :k
"""


async def search_caller_chunks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    question: str,
    kinds: Sequence[str],
    feature: str,
    agent_id: UUID | None = None,
    k: int = 10,
) -> tuple[CallerHit, ...]:
    """Hybrid RRF over one tenant's caller chunks, in the kinds the caller names.

    `kinds` is REQUIRED and has no default, which is the one place this signature is
    deliberately inconvenient. A default of "all kinds" would let a Leads screen silently
    return transcript windows, and a caller-memory search silently return CRM fields —
    three corpora with three different things a client expects to be looking at, merged by
    an omission. Naming them is one line at each call site and it is the line that says
    which data the screen is about.

    `feature` is likewise required: it is the `usage_events.meta.feature` the question's
    embedding is billed under, and the three query-time names already exist
    (`embedding.ASSIST_FEATURE_CALL_SEARCH`, `ASSIST_FEATURE_LEAD_SEARCH`). A default would
    make one scope's spend land under another's name in the only ledger that has it.

    Returns an EMPTY TUPLE for a question that matched nothing — which is an answer and not
    a failure. `capabilities.RetrievalCapabilityAbsentError` is deliberately not raised
    here: that refusal means "we never looked", and this looked.
    """
    if not kinds:
        raise ValueError("caller search needs at least one subject kind to search")
    unknown = sorted(set(kinds) - set(SUBJECT_KINDS))
    if unknown:
        raise ValueError(f"unknown caller-chunk subject kind(s): {', '.join(unknown)}")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"caller search k must be between 1 and {MAX_K}")

    started = time.perf_counter()
    # Bought and metered inside, or None and the dense arm is skipped — one implementation
    # of hard rule 7's pre-flight for every search surface (`embed_query_vector`).
    vector = await embed_query_vector(
        session, tenant_id=tenant_id, question=question, feature=feature
    )
    # `SET LOCAL`, inside the caller's transaction, for the pooled-connection reason in the
    # module docstring. It reverts at COMMIT or ROLLBACK whichever way this goes.
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {_EF_SEARCH}"))
    rows = (
        await session.execute(
            text(_SEARCH_SQL),
            {
                "tid": tenant_id,
                "kinds": list(kinds),
                "aid": agent_id,
                "question": question,
                "qvec": vector_literal(vector),
                "k": k,
            },
        )
    ).all()

    hits = tuple(
        CallerHit(
            subject_kind=str(row[0]),
            subject_id=UUID(str(row[1])),
            idx=int(row[2]),
            call_id=None if row[3] is None else UUID(str(row[3])),
            agent_id=UUID(str(row[4])),
            first_turn_idx=None if row[5] is None else int(row[5]),
            last_turn_idx=None if row[6] is None else int(row[6]),
            score=float(row[7]),
        )
        for row in rows
    )
    log.info(
        "caller_search_served",
        # Ids, counts and our own vocabulary. Never the question — it is a person's prose
        # about their caller (hard rule 6) — and never a subject ref, which is a pointer to
        # a person.
        extra={
            "tenant_id": str(tenant_id),
            "kinds": sorted(set(kinds)),
            "dense": vector is not None,
            "hits": len(hits),
            "feature": feature,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        },
    )
    return hits


__all__ = ["MAX_K", "CallerHit", "search_caller_chunks"]
