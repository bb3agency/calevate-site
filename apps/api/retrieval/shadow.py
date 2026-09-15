"""Ask the other store the same question, record how far apart they were, serve NEITHER.

**THIS IS HOW A RETRIEVAL PATH IS RETIRED**, and it is the industry's answer rather than an
invention here: run the challenger in the dark against live traffic, compare it with what
was actually served, and only cut over once the divergence is understood. The alternative —
flipping `retrieval_provider` and watching the copilot — makes every client a test subject
and makes the first evidence a complaint.

`docs/PIPECAT-MIGRATION.md` §6 step 15 retires `kb_chunks` and its lexical arm in favour of
Supermemory. §8.6 is the plan; this module is the instrument that plan is argued from, and
it is the thing that can be built TODAY while the two facts step 15 actually depends on —
an install that answers, and an ingestion path that has run — are still outside this repo.

THE ONE PROMISE, AND IT IS STRUCTURAL RATHER THAN CAREFUL. `retrieve` returns the primary
arm's `RetrievalResult` **object**, unmodified: not a copy, not a merge, not a re-ranked
union. The shadow arm's answer reaches exactly two places, a log line and nothing else. A
reader checking "can this change what a client sees" has one `return` to read, and
`tests/retrieval_shadow_test.py::test_the_served_result_is_the_primary_arms_own_object`
asserts identity, not equality, so a future edit that rebuilds the result fails there.

ORDER, AND WHY IT IS NOT CONCURRENT:

* **Primary first, then the shadow, sequentially.** Both arms may be holding the CALLER'S
  ONE `AsyncSession` — `PgVectorRetriever` queries on it and `SupermemoryRetriever` meters
  on it — and a SQLAlchemy `AsyncSession` is not concurrency-safe. `asyncio.gather` over
  two arms sharing one session is a corrupted session, not a faster request.
* **No `wait_for` around the shadow leg**, for the same session. Cancelling a coroutine
  mid-INSERT leaves the caller's session in a state the caller did not ask for, and the
  request that pays for it is a client's. The shadow leg's budget lives in the adapter that
  owns the socket (`supermemory.SEARCH_TIMEOUT_S`), which is where a timeout can be applied
  without cancelling anything of ours.
* **Fire-and-forget was rejected outright.** It is the textbook shadow-read shape and it is
  wrong here for a mechanical reason: the session closes when the request ends, so a
  detached task would query a closed session and the comparison would measure our own
  teardown.

So a shadow read costs the client's question one extra store round trip. That is the price,
it is paid by the enrolled tenants below and nobody else, and it is why this is OFF by
default.

--------------------------------------------------------------------------------
MONEY: A SHADOW SEARCH IS REAL SPEND, SO IT IS OPTED INTO PER TENANT
--------------------------------------------------------------------------------
Both arms buy an embedding per question on OUR vendor account, and both meter it against
the tenant whose question it was — `retrieval/embedding.ASSIST_FEATURE_KB_SEARCH` for the
Postgres arm, `supermemory.ASSIST_FEATURE_SUPERMEMORY_SEARCH` for box 3. A shadow read
therefore spends a client's AI quota on an experiment they did not ask for, and a
platform-wide switch that did that silently would be indefensible.

Hence TWO settings and not one. `retrieval_shadow_arm` names the store; `Settings.
retrieval_shadow_tenant_ids` names WHOSE questions may be shadowed, and an empty list means
nobody — so turning the arm on by itself spends nothing and changes nothing. Enrolling a
tenant is an operator act against a named account (ours, or one that agreed), visible in
the ops console beside the switch.

**THE SPEND IS ALREADY SEPARABLE AND NOTHING NEW IS METERED HERE.** The two arms already
write different `usage_events.meta.feature` keys, for the reason
`ASSIST_FEATURE_SUPERMEMORY_SEARCH` records: an operator comparing two stores cannot do it
from a merged number. So the shadow leg's cost is already its own line, and adding a third
feature key here would have split one store's spend across two names depending on which
switch caused it.

--------------------------------------------------------------------------------
WHAT IS RECORDED
--------------------------------------------------------------------------------
One `retrieval_shadow_compared` line per shadowed question, carrying `compare.Disagreement`
— counts, a Jaccard over DOCUMENT ids, whether the top document matched, and the class name
of whatever stopped the shadow arm. Hard rule 6: no question, no passage, no label. The
questions are clients' own prose and the passages are their business knowledge, and neither
belongs in a log line however useful it would be to a comparison.

Every shadowed question is logged, not only the ones that disagreed, because the number the
retirement is argued from is an AGREEMENT RATE and a log holding only failures has no
denominator.
"""

from __future__ import annotations

from uuid import UUID

from calevate_shared.retrieval import (
    RetrievalCapabilities,
    RetrievalProvider,
    RetrievalRequest,
    RetrievalResult,
)

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.retrieval.compare import disagreement

log = get_logger(__name__)

#: `Settings.retrieval_shadow_arm` when nothing is being compared. The DEFAULT, and the
#: value an operator sets back to when they have their number.
SHADOW_OFF = "off"


class ShadowArmUnavailableError(RuntimeError):
    """The shadow arm could not be asked. Never raised at a caller — see `retrieve`."""


class UnavailableArm:
    """A `RetrievalProvider` that refuses instead of answering. The shadow arm's floor.

    WHY THIS EXISTS RATHER THAN REUSING THE REAL FALLBACK. `supermemory.supermemory_t3`
    takes a fallback and degrades into it, which is right on the SERVING path (§8.5: a
    client's question gets answered out of our own Postgres) and destroys the measurement
    here — a shadow arm that quietly answers out of pgvector would report that box 3 agrees
    with pgvector perfectly, on every request box 3 did not handle.

    So the shadow copy of a degrading adapter is given this as its fallback: box 3 not
    answering becomes a named exception, `retrieve` records it as `shadow_error`, and the
    agreement rate counts it as a disagreement rather than as a match.
    """

    name = "unavailable"
    #: Nothing, honestly declared. It is never selected to serve anybody and never composed
    #: into a union — `RetrievalCapabilities` has no defaults on purpose, so every field is
    #: answered rather than inherited.
    capabilities = RetrievalCapabilities(
        compiled_facts=False,
        semantic_search=False,
        hybrid_search=False,
        reranking=False,
        per_tenant_namespace=False,
        deletion_proof=False,
        max_k=1,
    )

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        raise ShadowArmUnavailableError("the shadow arm did not answer")

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        raise ShadowArmUnavailableError("the shadow arm did not answer")


def shadowed_tenants() -> frozenset[UUID]:
    """Whose questions may be shadowed. **Empty means nobody, and that is the default.**

    A malformed entry is DROPPED rather than raising, and the drop is logged: this is read
    on the request path, and a typo in an ops-console list must cost a tenant their
    comparison, never their answer. The count is logged rather than the ids — a tenant id
    is not PII, but a log line naming every enrolled account on every request is noise the
    operator has to read past to find the one line that matters.
    """
    raw = (get_settings().retrieval_shadow_tenant_ids or "").strip()
    if not raw:
        return frozenset()
    enrolled: set[UUID] = set()
    dropped = 0
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            enrolled.add(UUID(candidate))
        except ValueError:
            dropped += 1
    if dropped:
        log.error("retrieval_shadow_tenant_unparseable", extra={"dropped": dropped})
    return frozenset(enrolled)


class ShadowReadRetriever:
    """Serves `primary`. Also asks `shadow`, and records only the difference.

    It IS a `RetrievalProvider` rather than a branch inside `service.look_up`, so the
    comparison composes wherever a store does — today the T3 member of `KnowledgeRetriever`,
    tomorrow whatever else the port grows. Nothing above it learns that two stores were
    asked.
    """

    def __init__(
        self,
        primary: RetrievalProvider,
        *,
        shadow: RetrievalProvider,
        tenants: frozenset[UUID],
    ) -> None:
        self._primary = primary
        self._shadow = shadow
        self._tenants = tenants
        #: **THE PRIMARY'S OWN NAME AND CAPABILITIES, DELIBERATELY.** `name` labels a metric
        #: and a log field that answer "where did this come from", and the answer is the
        #: primary — a wrapper name here would make `record_retrieval_ms` report a store
        #: nobody queried. The capabilities are the primary's for the stronger reason: they
        #: are what a caller is refused or served against, and the shadow arm must not be
        #: able to widen or narrow a single promise made to a client.
        self.name = primary.name
        self.capabilities = primary.capabilities

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """The primary's result, unchanged, whatever the shadow arm did or did not do."""
        served = await self._primary.retrieve(request)
        if request.tenant_id not in self._tenants:
            return served
        shadow: RetrievalResult | None = None
        failure: Exception | None = None
        try:
            shadow = await self._shadow.retrieve(request)
        except Exception as error:
            # EVERY exception, and that is the point of a shadow read: the challenger is
            # not trusted yet, so nothing it does — a timeout, a shape we guessed wrong, a
            # bug in an adapter nobody has run against a live vendor — may reach a client
            # who asked a question the primary already answered.
            failure = error
        difference = disagreement(served, shadow, error=failure)
        log.info(
            "retrieval_shadow_compared",
            # Ids, counts and our own vocabulary (hard rule 6). The question and the
            # passages are the client's, and a comparison is not a reason to log them.
            extra={
                "tenant_id": str(request.tenant_id),
                "tier": request.tier,
                "k": request.k,
                "served_arm": self._primary.name,
                "shadow_arm": self._shadow.name,
                "agreed": difference.agreed,
                **difference.model_dump(),
            },
        )
        return served

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """The PRIMARY's stamp alone. The shadow arm is never on the cache key.

        Two reasons, and the second is the one that would have bitten. (a) It runs before
        the cache on every question, so asking two stores here would double the cost of a
        cache HIT — the path that exists to be cheap. (b) Mixing the challenger into the key
        would invalidate every cached answer the moment the shadow arm was switched on or
        off, which is a visible change in what clients are served by a switch whose entire
        promise is that it changes nothing.
        """
        return await self._primary.knowledge_epoch(request)


__all__ = [
    "SHADOW_OFF",
    "ShadowArmUnavailableError",
    "ShadowReadRetriever",
    "UnavailableArm",
    "shadowed_tenants",
]
