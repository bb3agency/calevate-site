"""T3 — hybrid retrieval over `kb_chunks` in the Postgres we already run (D-502).

WHAT THIS SERVES AND WHAT IT MUST NOT. The dashboard copilot, and later CRM semantic search
and caller memory — paths whose budget is seconds. **NOT the call.** `docs/evidence/
kb-retrieval-bakeoff.md` §5.1 is binding: in-call retrieval stays T0 and Bolna's own KB,
and `tests/kb_tiers_test.py:156` pins `apps/voice-runtime`'s route inventory as an equality
so a retrieval endpoint cannot appear on the audio path by accident. Nothing here is
imported by voice-runtime.

--------------------------------------------------------------------------------
THE QUERY: ONE STATEMENT, TWO ARMS, RECIPROCAL RANK FUSION
--------------------------------------------------------------------------------
A dense arm (`embedding <=> $q`, cosine) and a sparse arm (`ts_rank_cd`), each to
`_ARM_DEPTH`, fused by RRF at `k = 60` and cut to the caller's `k`. One statement and one
round trip, which is the shape the bake-off measured (§2.1) — so the numbers in that
document describe THIS query rather than a relative of it.

**RRF RATHER THAN A WEIGHTED SCORE BLEND, and the reason is that the two arms are not
commensurable.** Cosine distance and `ts_rank_cd` are different quantities on different
scales with different distributions; any weighted sum of them has two magic constants that
have never been tuned on this corpus and would silently favour one arm as the corpus grows.
RRF reads only the RANK each arm assigned, so it needs no normalisation and no tuning.
`k = 60` is Cormack/Clarke/Buettcher (SIGIR 2009) and every mainstream default, and it is
the constant the bake-off's own harness used.

**THE SPARSE ARM IS WHY THIS IS HYBRID AND NOT "SEMANTIC SEARCH".** Dense-only retrieval
misses exact tokens — a price, a phone extension, a drug name, a scheme called
"Aarogyasri" — because an embedding of a rare proper noun is not close to an embedding of a
question about it. The sparse arm carries the chunk's ENGLISH GLOSS as well as its original
text (D-489), which is the whole reason a Tenglish question can reach a Telugu-script chunk
at all.

**AN UNEMBEDDED CHUNK STILL ANSWERS.** `embedding IS NULL` until the sweep reaches it, so
the dense arm simply has fewer rows to rank and the sparse arm answers alone. That is a
weaker result and never a wrong one, and it is what lets publishing be independent of a
provider being up.

--------------------------------------------------------------------------------
HOW RLS AND THE INDEX INTERACT — THE FINDING THAT MADE pgvector VIABLE
--------------------------------------------------------------------------------
Every query here runs inside the CALLER's tenant session, so `kb_chunks`' FORCEd
`tenant_isolation` policy is applied by the planner as an extra qualification. RLS therefore
makes every vector query a FILTERED vector query, which is normally pgvector's weak spot:
before 0.8.0 an HNSW scan walks the graph and the filter is applied to whatever the walk
produced, so a scoped query can silently return fewer rows than asked for.

**It does not happen at our sizes, and that was MEASURED rather than reasoned**
(`kb-retrieval-bakeoff.md` §2.3(b), 500 trials at each of three corpus sizes, zero short
results). The `(tenant_id, agent_id, is_active)` btree is selective enough — one agent holds
~1% of a 50-tenant table — that Postgres prefers it and then sorts EXACTLY, never entering
the HNSW graph. The tenancy filter hard rule 1 requires and the recall hazard turn out to be
the same mechanism pointed in opposite directions.

⚠ **THE CONDITION, because it is a property of a RATIO and not of pgvector.** It holds while
one agent's corpus is small relative to the table. Index the resolved-call transcripts TRD
§6 contemplates, or give one agent a very large knowledge base, and the planner switches to
HNSW and the hazard is live again. Re-run `scripts/spike/kb_pgvector_latency.py` — it
reports the chosen plan and the row yield precisely so this is checkable — or upgrade past
pgvector 0.8.0, which removes it by construction.

**AND `hnsw.iterative_scan` IS NOT THE ANSWER TODAY, FOR A REASON WORSE THAN "TOO OLD".**
That GUC arrived in 0.8.0; this server has 0.6.0 (MEASURED-HERE 1 Sep 2026,
`pg_available_extensions`). On 0.6.0 `SET hnsw.iterative_scan = 'relaxed_order'` **succeeds
and does nothing** — it is an unvalidated GUC placeholder, exactly as `SET
hnsw.total_nonsense = 'banana'` is (both measured here the same day). So writing it would
put a safety control in the code that reads as applied, appears in review as protection,
and protects nothing. It is deliberately absent, and this paragraph is what a reader who
comes to add it should find first.

`hnsw.ef_search` IS set, and always with `SET LOCAL` inside the caller's transaction.
Session-level would be a defect rather than a style choice: these connections come out of a
pool, so a session-level `SET` outlives the request that made it and silently re-tunes every
later query on that connection, including ones belonging to another tenant.

--------------------------------------------------------------------------------
HARD RULES
--------------------------------------------------------------------------------
Rule 1: the statement runs under the caller's RLS session AND re-states `tenant_id` as a
predicate — belt over braces, defending the one mistake RLS cannot see, a caller passing
tenant A's id on tenant B's session. Rule 6: no question, no passage and no chunk text ever
reaches a log line; ids, counts and our own vocabulary only. Rule 7: the question's
embedding is metered before it can be forgotten, and is not bought at all unless its price
is billable.
"""

from __future__ import annotations

import time
from typing import Final
from uuid import UUID

import httpx
from calevate_shared.retrieval import (
    Passage,
    Provenance,
    RetrievalCapabilities,
    RetrievalRequest,
    RetrievalResult,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.core.logging import get_logger
from apps.api.kb.models import EMBED_READY
from apps.api.retrieval.capabilities import require_tier
from apps.api.retrieval.embedding import (
    ASSIST_FEATURE_KB_SEARCH,
    EMBED_TIMEOUT_S,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    embedding_leg,
    embedding_price_is_billable,
)
from apps.workers import chat

log = get_logger(__name__)

#: OUR name for this implementation. A metric label and a log field, never shown to a client
#: (hard rule 2's reasoning applied to the store).
PROVIDER_NAME: Final = "pgvector"

#: How deep each arm ranks before fusion. Twenty is the bake-off harness's depth, so the
#: measured latency describes this query; it is also comfortably more than any `k` the port
#: admits (`RetrievalRequest.k` is capped at 20), which is what gives RRF something to fuse
#: rather than two lists that are already the answer.
_ARM_DEPTH: Final = 20

#: RRF's smoothing constant. Cormack, Clarke and Buettcher, SIGIR 2009 — the value every
#: mainstream implementation uses, and the one the bake-off measured with. It damps the
#: difference between rank 1 and rank 2 so a single arm cannot dominate the fusion.
_RRF_K: Final = 60

#: `hnsw.ef_search` for a query that DOES enter the graph. 100 rather than pgvector's
#: default 40 because the port's `k` can be 20 and a candidate list of 40 leaves almost no
#: headroom for the filter — and at our corpus sizes the graph is usually not entered at
#: all, so the extra work is bounded by how rarely it is paid.
#:
#: ⚠ ALWAYS `SET LOCAL`. See the module docstring: a pooled connection makes a session-level
#: set a cross-request side effect.
_EF_SEARCH: Final = 100

#: The text-search configuration. It MUST equal migration `dc1aaeeeff02.TS_CONFIG`: a
#: `tsvector` stored under one configuration and a `tsquery` built under another do not
#: match, and the symptom is an empty sparse arm rather than an error. Spelled here as a
#: constant so the two are greppable together.
TS_CONFIG: Final = "english"

#: THE ONE STATEMENT. Read it as: scope, then two arms over the scope, then fusion.
#:
#: `scope` is a CTE rather than a repeated predicate so the tenancy filter is written ONCE
#: and both arms provably see the same rows — the alternative is two WHERE clauses that can
#: drift, on the predicate that is hard rule 1.
#:
#: The dense arm is skipped entirely when no question vector was bought (`:qvec IS NULL`),
#: which is what makes the sparse-only degradation a data path rather than a second query.
#:
#: `CAST(:aid AS uuid)` and not `::aid` — SQLAlchemy's `text()` consumes the second colon
#: itself and what reaches Postgres is a syntax error (`compiled_facts.py` records the same
#: trap). The cast is required, not decoration: an untyped placeholder inside `IS NULL`
#: gives the planner nothing to infer from and it refuses the statement outright.
_SEARCH_SQL: Final = f"""
WITH scope AS (
  SELECT c.id, c.document_id, c.source_id, c.agent_id, c.embedding, c.tsv
  FROM kb_chunks c
  WHERE c.tenant_id = :tid
    AND c.is_active
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
SELECT d.content, s.name, c.agent_id, c.source_id, f.score
FROM fused f
JOIN scope c ON c.id = f.id
JOIN kb_documents d ON d.id = c.document_id
JOIN kb_sources s ON s.id = c.source_id
ORDER BY f.score DESC, d.id
LIMIT :k
"""

#: The invalidation stamp. `count(*)` of live chunks plus the highest live source version in
#: scope, plus how many of them are embedded — the third term because a chunk gaining its
#: vector CHANGES what the same question returns while neither of the first two moves, and a
#: cache that could not see that would keep serving the sparse-only answer for its whole TTL
#: after the sweep landed.
_EPOCH_SQL: Final = f"""
SELECT count(*), coalesce(max(c.version), 0),
       count(*) FILTER (WHERE c.embed_state = '{EMBED_READY}')
FROM kb_chunks c
WHERE c.tenant_id = :tid AND c.is_active
  AND (CAST(:aid AS uuid) IS NULL OR c.agent_id = CAST(:aid AS uuid))
"""


class PgVectorRetriever:
    """The T3 adapter. Constructed with the caller's tenant-scoped session.

    Holding the session rather than taking one per call is the port's shape and the reason
    it survives a managed vendor: that adapter is constructed with a client instead, and
    neither leaks into `RetrievalRequest`. It also means the RLS context is the CALLER's —
    this class never opens a session of its own and so can never widen the tenancy of the
    code that used it.
    """

    name = PROVIDER_NAME

    #: What this adapter can do, declared rather than discovered (the port's rule).
    #:
    #: `hybrid_search` is TRUE and it is earned: a dense arm and a sparse arm are fused, in
    #: this port's own vocabulary. `compiled_facts` is FALSE — T0 is a different corpus and
    #: `KnowledgeRetriever` is what puts the two together. `reranking` is FALSE: no
    #: cross-encoder exists here and declaring one we do not have is the exact thing
    #: `RetrievalCapabilities` was introduced to forbid.
    #:
    #: `per_tenant_namespace` is TRUE for the strongest available reason — a FORCEd RLS
    #: policy, so a query that forgets the tenant returns zero rows rather than a
    #: neighbour's. `deletion_proof` is TRUE because there is no second copy to prove
    #: anything about: `kb_chunks` CASCADEs from `kb_documents`, which retention genuinely
    #: DELETEs (`workers/retention._KB_EXPIRE_SQL`).
    capabilities = RetrievalCapabilities(
        compiled_facts=False,
        semantic_search=True,
        hybrid_search=True,
        reranking=False,
        per_tenant_namespace=True,
        deletion_proof=True,
        # Equal to the request model's own ceiling by intent: a `k` this adapter would have
        # to clamp is a `k` the port should have refused, and clamping silently is the
        # no-op the port forbids.
        max_k=20,
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _question_vector(self, request: RetrievalRequest) -> list[float] | None:
        """The question as a vector, metered — or None, and then the dense arm is skipped.

        **THE PRICE IS CHECKED BEFORE THE PROVIDER IS CALLED (hard rule 7).** Buying an
        embedding this repository cannot price would either write a made-up
        `unit_cost_paid` on an append-only row or record nothing at all; both are worse than
        answering from the sparse arm. `embedding_price_is_billable` is total and never
        raises, so this is a branch and not a failure.

        Returning None on EVERY failure — no leg, no price, a provider error, a width the
        column will not hold — is deliberate. A dashboard question is not the place to
        surface a provider outage as an exception: the sparse arm still answers, the caller
        still gets the client's own approved words, and the operator gets the log line.
        """
        if not embedding_price_is_billable():
            log.info("kb_search_embedding_unpriced", extra={"model": EMBEDDING_MODEL})
            return None
        leg = embedding_leg()
        if leg is None:
            log.info("kb_search_embedding_no_provider")
            return None
        try:
            outcome = await chat.embed(
                leg, [request.question], dimensions=EMBEDDING_DIMS, timeout_s=EMBED_TIMEOUT_S
            )
        except (httpx.HTTPError, TimeoutError) as failure:
            # `type(failure).__name__` and nothing else: a provider's error body quotes the
            # request, and the request is a client's own question (hard rule 6).
            log.warning("kb_search_embedding_failed", extra={"error": type(failure).__name__})
            return None

        # METERED WHETHER OR NOT THE VECTOR IS USABLE. We paid for the turn; a refused width
        # is our problem, not a discount. `tokens_out=0` is the truth about an embedding
        # rather than a default — the vendor's `usage` block has no output half at all.
        if outcome.usage is not None:
            await record_ai_assist_usage(
                self._session,
                tenant_id=request.tenant_id,
                ref=new_assist_ref(),
                tokens_in=outcome.usage.prompt_tokens,
                tokens_out=0,
                model=EMBEDDING_MODEL,
                feature=ASSIST_FEATURE_KB_SEARCH,
            )
        vector = outcome.vectors[0] if outcome.vectors else None
        if vector is None or len(vector) != EMBEDDING_DIMS:
            log.warning(
                "kb_search_embedding_width",
                extra={"want": EMBEDDING_DIMS, "got": 0 if vector is None else len(vector)},
            )
            return None
        return list(vector)

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Hybrid RRF over this tenant's published chunks.

        A tier this adapter cannot serve refuses BY NAME first, before a row is read —
        unless the caller opted into degrading, in which case the result says which
        capability was missing and the caller must surface it.
        """
        started = time.perf_counter()
        missing = self.capabilities.serves(request.tier)
        if missing is not None and not request.allow_degrade:
            require_tier(request.tier, provider=self)

        vector = await self._question_vector(request)
        # `SET LOCAL`, inside the caller's transaction, for the pooled-connection reason in
        # the module docstring. It reverts at COMMIT or ROLLBACK whichever way this goes.
        await self._session.execute(text(f"SET LOCAL hnsw.ef_search = {_EF_SEARCH}"))
        rows = (
            await self._session.execute(
                text(_SEARCH_SQL),
                {
                    "tid": request.tenant_id,
                    "aid": request.agent_id,
                    "question": request.question,
                    # psycopg renders a Python list as a Postgres array, which `vector`
                    # will not accept; the type's own text form is the bracketed literal,
                    # and the statement casts it.
                    "qvec": None if vector is None else "[" + ",".join(map(repr, vector)) + "]",
                    "k": request.k,
                },
            )
        ).all()

        passages = tuple(
            Passage(
                text=str(row[0])[:4000],
                provenance=Provenance(
                    # The SOURCE's own name — what the client called this thing when they
                    # uploaded it, which is what makes a citation checkable by them. Bounded
                    # to the `Provenance.label` ceiling rather than assumed to fit.
                    label=str(row[1])[:200],
                    tier="t3",
                    agent_id=UUID(str(row[2])),
                    source_id=UUID(str(row[3])),
                ),
                # The FUSED score. Comparable only within one result — the port says so, and
                # an RRF score is a sum of reciprocal ranks, not a similarity.
                score=float(row[4]),
            )
            for row in rows
        )
        return RetrievalResult(
            passages=passages,
            requested_tier=request.tier,
            served_tier="t3",
            unmet_capability=missing,
            provider=self.name,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """`<live chunks>:<max version>:<embedded>` for this tenant and scope.

        A STAMP DERIVED FROM THE DATA, not an event, for the port's stated reason: a cache
        invalidated by a publish HOOK is correct only while every writer remembers to call
        it, and the failure is silent and lands as a stale answer. All three terms are
        needed — a republish moves the version, an archive or a new source moves the count,
        and the sweep landing a vector moves neither while changing every answer.
        """
        row = (
            await self._session.execute(
                text(_EPOCH_SQL), {"tid": request.tenant_id, "aid": request.agent_id}
            )
        ).first()
        if row is None:  # pragma: no cover - an aggregate always returns one row
            return "0:0:0"
        return f"{int(row[0])}:{int(row[1])}:{int(row[2])}"


__all__ = ["PROVIDER_NAME", "TS_CONFIG", "PgVectorRetriever"]
