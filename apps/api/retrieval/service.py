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
tenancy control and this module must never widen it), it does not write
`kb_retrieval_logs` (that table has no producer and cannot have one yet — see
`apps/api/kb/models.py::KbRetrievalLog`; inventing rows for a T0 lookup would be exactly
the invented `tier`/`top_score` that note refuses), and it does not call a model.
"""

from __future__ import annotations

import time
from uuid import UUID

from calevate_shared.retrieval import RetrievalProvider, RetrievalRequest, RetrievalResult
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import record_retrieval_ms
from apps.api.core.logging import get_logger
from apps.api.retrieval import cache
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.routing import RouteDecision, classify

log = get_logger(__name__)


def get_retriever(session: AsyncSession) -> RetrievalProvider:
    """THE selector. Every caller asks this; nothing constructs an adapter directly.

    One implementation today, and the selector exists anyway for `engine_capabilities`'
    reason: the day the D-28 bake-off names a winner, the branch that chooses it is written
    HERE and every caller is untouched. A `Settings` field naming the provider is what that
    branch will read; there is no such field yet and inventing one now would be a config
    key whose only value is the one thing we have.
    """
    return CompiledFactsRetriever(session)


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
    carries `unmet_capability`, the caller must surface it (`copilot/read_tools.py` puts it
    in front of the model as tool output), and the log line below names it. The refusal
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
