"""One provider that answers every tier, by delegating each to the adapter that owns it.

WHY THIS EXISTS RATHER THAN A CHOICE BETWEEN TWO ADAPTERS. `retrieval/routing.py` decides
per QUESTION which tier is earned: "what are your hours" is t0 (the fact is already compiled
into the agent's prompt, 0ms, no store touched) and "what do we tell people about refunds
and returns" is t3 (a cold lookup). Both arrive at the same `look_up` call, so a selector
that returned ONE adapter would have to return the wrong one for half the traffic.

The alternative — teaching `service.look_up` to pick an adapter per tier — was rejected
because it puts the dispatch outside the port, where a second caller (the in-call endpoint
TRD §6.2 may one day allow, or CRM search) would have to reimplement it. Here the dispatch
IS a `RetrievalProvider`, so every caller keeps the one contract and nothing above the port
learns that there are two stores.

WHY THE COMPILED-FACTS TIER IS STILL FIRST FOR THE QUESTIONS IT OWNS, now that a real store
exists. It is not a fallback and it is not slower-but-safer: T0 answers out of the block the
AGENT ACTUALLY SPEAKS FROM, so a dashboard answer and what a caller hears are the same
sentence. `kb_chunks` holds every approved chunk, including ones the T0 compiler left out of
the prompt — a strictly wider corpus, and therefore the WRONG corpus for "what does my agent
say about X". Retiring T0 into the store would have been the tidy-looking change and would
have made the copilot answer a different question from the one it is asked.

WHAT A CAPABILITY MEANS ON A COMPOSITE. `capabilities` is the UNION, because the port's
contract is "what can this provider do for a caller", and the answer is genuinely both. It
is computed from the members rather than typed out, so an adapter that loses a capability
cannot leave a promise behind here.
"""

from __future__ import annotations

from calevate_shared.retrieval import (
    RetrievalCapabilities,
    RetrievalProvider,
    RetrievalRequest,
    RetrievalResult,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.retrieval.capabilities import require_tier
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.pgvector import PgVectorRetriever


def _union(*members: RetrievalCapabilities) -> RetrievalCapabilities:
    """The OR of every boolean and the MIN of `max_k`.

    `max_k` is a MINIMUM and not a maximum, deliberately: it is a ceiling the composite must
    honour whichever member ends up serving, so promising the larger of two would be
    promising a `k` one member would have to clamp — the silent truncation the port forbids.
    """
    return RetrievalCapabilities(
        compiled_facts=any(m.compiled_facts for m in members),
        semantic_search=any(m.semantic_search for m in members),
        hybrid_search=any(m.hybrid_search for m in members),
        reranking=any(m.reranking for m in members),
        # AND, not OR, and this is the one field where the difference is a security
        # property: the composite isolates tenants only if EVERY member does. A union that
        # ORed this would let one adapter's guarantee vouch for another's.
        per_tenant_namespace=all(m.per_tenant_namespace for m in members),
        deletion_proof=all(m.deletion_proof for m in members),
        max_k=min(m.max_k for m in members),
    )


class KnowledgeRetriever:
    """T0 from the compiled block, T3 from `kb_chunks`. One `RetrievalProvider`.

    `name` is the composite's own, not a member's: it labels a metric and a log field, and
    reporting "compiled-facts" for a query that ran in Postgres would make the one
    observability field that says WHERE an answer came from a lie.
    """

    name = "knowledge"

    def __init__(self, session: AsyncSession) -> None:
        self._t0: RetrievalProvider = CompiledFactsRetriever(session)
        self._t3: RetrievalProvider = PgVectorRetriever(session)
        self.capabilities = _union(self._t0.capabilities, self._t3.capabilities)

    def _member(self, request: RetrievalRequest) -> RetrievalProvider:
        """Which adapter owns this request's tier.

        t3 is the store. Everything else is T0: t0 by definition; t1/t2 are CACHE tiers no
        adapter serves (`RetrievalTier`) and the cache sits in front of whatever answers; t4
        is "refuse and escalate", a prompt instruction with no store behind it, so the
        cheapest member is the honest one to ask.
        """
        return self._t3 if request.tier == "t3" else self._t0

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Delegate, and REPORT THE COMPOSITE'S OWN NAME on the way out.

        The refusal is raised HERE, against the composite's union capabilities, before the
        member is asked. Letting the member refuse would name ITS gap — "compiled-facts
        cannot do semantic_search" — for a provider that demonstrably can, which is a
        refusal an operator would chase into the wrong module.
        """
        missing = self.capabilities.serves(request.tier)
        if missing is not None and not request.allow_degrade:
            require_tier(request.tier, provider=self)
        result = await self._member(request).retrieve(request)
        # `unmet_capability` is re-derived from the UNION rather than passed through: a
        # member that degraded because IT could not serve the tier has not degraded the
        # composite if the other member could have. Here the dispatch already sent the
        # request to the member that owns the tier, so the union's answer is the true one.
        return result.model_copy(update={"provider": self.name, "unmet_capability": missing})

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """BOTH members' stamps, joined.

        Both, not the serving member's, because the cache key must change when EITHER
        corpus changes: the tier a question earns is decided by `routing.classify` from the
        question's own words, so the same cache namespace holds answers from both members
        and a stamp that tracked only one would keep serving the other's stale rows.
        """
        t0 = await self._t0.knowledge_epoch(request)
        return f"{t0}|{await self._t3.knowledge_epoch(request)}"


__all__ = ["KnowledgeRetriever"]
