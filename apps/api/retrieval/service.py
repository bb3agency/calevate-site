"""The one entry point: route the question, try the cache, ask the provider, measure.

Every caller of retrieval — the dashboard copilot today, an in-call tool endpoint the day
TRD §6.2's round-trip measurement allows one — comes through `look_up`. One function, so
the routing decision, the cache and the measurement cannot be half-applied by a second
caller that reimplemented two of the three.

ORDER, AND WHY IT IS THIS ORDER:

1. **Route first** (`routing.classify`), because the tier is part of the cache key: the
   same question at t0 and at t3 has two different right answers.
2. **Epoch, then cache** (`compiled_facts.knowledge_epoch`, `cache.get`). The epoch read is
   what makes a hit safe rather than fast — see `cache.py`'s invalidation argument. It
   costs one small indexed read on the hit path and that cost is measured, not asserted.
3. **Provider, then store.** A miss pays the store; a degraded answer is stored WITH its
   `unmet_capability` so a later hit still discloses it.

WHAT THIS FUNCTION DOES NOT DO: it does not open a session (the caller's RLS context is the
tenancy control and this module must never widen it), it does not write the knowledge-gap
log (`apps/api/kb/models.py::KbRetrievalLog` — that table has no producer and cannot have
one yet; inventing rows for a T0 lookup would be exactly the invented `tier`/`top_score`
its dated GAP note refuses), and it does not call a model.

The log is named by its MODEL CLASS and not by its table, deliberately:
`tests/kb_tiers_test.py::test_the_knowledge_gap_report_has_no_producer_and_cannot_yet`
greps `apps/` for the raw table name to prove nothing produces it, and a docstring saying
"we do not write this" would otherwise trip the very guard it agrees with.
"""

from __future__ import annotations

import time
from uuid import UUID

from calevate_shared.retrieval import RetrievalProvider, RetrievalRequest, RetrievalResult
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import record_retrieval_ms
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.retrieval import cache
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.embedding import embedding_leg, embedding_price_is_billable
from apps.api.retrieval.pgvector import PROVIDER_NAME as PGVECTOR_PROVIDER
from apps.api.retrieval.routing import RouteDecision, classify
from apps.api.retrieval.tiered import KnowledgeRetriever

log = get_logger(__name__)


def get_retriever(session: AsyncSession) -> RetrievalProvider:
    """THE selector. Every caller asks this; nothing constructs an adapter directly.

    THE BRANCH THE PORT WAS BUILT FOR (D-502). `Settings.retrieval_provider` names it:
    `compiled-facts` is T0 alone (what shipped before the bake-off ran) and `pgvector` adds
    the T3 store in the Postgres we already run. Adding a managed vendor later is a third
    branch here and a new module beside `pgvector.py` — no caller changes, because every
    caller holds a `RetrievalProvider` and nothing above this line knows a store exists.

    **A MISCONFIGURED `pgvector` FALLS BACK RATHER THAN FAILING, and the fallback is loud.**
    The store is useless without an embedding leg (no vector for the question, and nothing
    filling the column either), so a deployment that names the provider without configuring
    the credential would serve every t3 question out of an empty dense arm. Tolerant boot
    (BACKEND-PATTERNS §2) says a deployment missing one credential runs everything else, so
    it degrades to T0 — which is a strictly working system — and says so at ERROR, because
    unlike a missing credential this is a CONTRADICTION between two settings an operator set
    and only they can resolve it.
    """
    if get_settings().retrieval_provider != PGVECTOR_PROVIDER:
        return CompiledFactsRetriever(session)
    if embedding_leg() is None or not embedding_price_is_billable():
        log.error(
            "retrieval_pgvector_unconfigured",
            # Which precondition failed, and never the credential itself.
            extra={
                "leg": embedding_leg() is not None,
                "priced": embedding_price_is_billable(),
            },
        )
        return CompiledFactsRetriever(session)
    return KnowledgeRetriever(session)


async def look_up(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    question: str,
    agent_id: UUID | None = None,
    k: int = 3,
) -> tuple[RouteDecision, RetrievalResult]:
    """Answer one question about a tenant's own approved knowledge.

    Returns the ROUTING DECISION alongside the result, because the caller has to be able to
    say why: "we answered from the compiled facts" and "we searched" are different sentences
    to a client, and a caller that only got passages would have to guess.

    `allow_degrade=True` is passed unconditionally and deliberately. The router will ask for
    t3 on any open-ended question, and no provider serves t3 today — refusing outright would
    make the copilot fail at the thing it exists to do, on exactly the questions a client
    most wants help with. Degrading is the alternative and it is not silent: the result
    carries `unmet_capability`, the caller must surface it (`copilot/tools.py::
    _search_knowledge` puts it in front of the model as tool output), and the log line
    below names it. The refusal
    machinery is still real and still reachable — a caller that must not be answered from a
    lower tier passes `allow_degrade=False` on the request it builds and gets
    `RetrievalCapabilityAbsentError` by name.
    """
    started = time.perf_counter()
    decision = classify(question)
    request = RetrievalRequest(
        tenant_id=tenant_id,
        agent_id=agent_id,
        question=question,
        k=k,
        tier=decision.tier,
        allow_degrade=True,
    )
    provider = get_retriever(session)

    epoch = await provider.knowledge_epoch(request)
    result = await cache.get(request, epoch=epoch)
    if result is None:
        result = await provider.retrieve(request)
        await cache.put(request, epoch=epoch, result=result)

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    record_retrieval_ms(
        elapsed_ms, provider=provider.name, tier=result.served_tier, cached=result.cached
    )
    log.info(
        "retrieval_served",
        # Ids, counts and our own vocabulary. Never the question, never a passage
        # (hard rule 6) — the question is a client's prose and the passages are their
        # business knowledge, and neither belongs in a log line.
        extra={
            "tenant_id": str(tenant_id),
            "intent": decision.intent,
            "requested_tier": decision.tier,
            "served_tier": result.served_tier,
            "unmet": result.unmet_capability,
            "passages": len(result.passages),
            "cached": result.cached,
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )
    # The result's own `elapsed_ms` is the store-or-cache leg; this one is the whole port,
    # epoch read included, which is the number a budget is actually spent against.
    return decision, result.model_copy(update={"elapsed_ms": elapsed_ms})


__all__ = ["get_retriever", "look_up"]
