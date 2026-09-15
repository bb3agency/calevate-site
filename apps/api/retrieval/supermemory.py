"""T3 out of a self-hosted Supermemory (box 3), behind the port D-502 left for it.

WHAT THE FOUNDER DECIDED, 14 Sep 2026 (`docs/PIPECAT-MIGRATION.md` §8). Supermemory becomes
the document store, index and caller-memory layer, running ON the Calevate VPS during
development. It sits BEHIND `calevate_shared.retrieval.RetrievalProvider` — dashboard
copilot, CRM search and caller memory read from it — and **it is never on the call path**.
The in-call knowledge pack is fetched once per session and searched in the worker's own
memory (§8.1, p50 0.31 ms, zero network per turn); nothing here is imported by
`apps/voice-runtime` or `apps/voice-worker`, and `tests/kb_tiers_test.py` pins the audio
path's route inventory as an equality so it cannot become one by accident.

--------------------------------------------------------------------------------
WHAT THIS ADAPTER IS NOT: A VERIFIED INTEGRATION
--------------------------------------------------------------------------------
**Supermemory is not installed here and `supermemory.ai` is egress-blocked from this
container** (§8.5, measured 14 Sep 2026). So this is a SEAM built against a contract nobody
in this repository has read: every path, request key and response key lives in
`supermemory_wire.ASSUMED_CONTRACT`, labelled ASSUMED, correctable in one object. Hard rule
11 is why they are gathered there rather than spelled inline, where the next reader would
inherit a guess as a finding.

Three vendor questions are open and each is answered by DEGRADING rather than by a premise:

* **Does the search surface look like the assumed contract?** UNKNOWN. A mismatch raises
  `SupermemoryWireMismatchError`, which is caught here beside the transport errors.
* **Does it report token usage?** UNKNOWN — so metering reads the usage block if it is
  there and logs at ERROR when it is not (`_meter`), rather than inventing a quantity.
* **Which release is safe to pin?** Three upstream issues bear on it (§8.5: #1336 custom
  embedding env vars ignored, #1315 searches empty on Linux in 0.0.6, #1320 segfault under
  concurrent embedding), and all three are UNVERIFIED as to current state. That is a
  version gate for an operator, not a code branch — and #1315 in particular is precisely
  the failure this adapter is built to survive: empty results and an unreachable host both
  end with the client's question answered out of our own Postgres.

--------------------------------------------------------------------------------
TENANCY IS OURS, AND THAT IS A DESIGN CONSTRAINT RATHER THAN A CAVEAT
--------------------------------------------------------------------------------
§8.4: the local build is single-tenant with ONE auto-generated API key; scoped per-tenant
keys are an Enterprise feature [VERIFIED-VENDOR-DOCS: /docs/self-hosting/local-vs-
enterprise, read by the founder 14 Sep 2026]. So `capabilities.per_tenant_namespace` is
**False** — which the port defines as "tenancy is enforced only by our filter, which is a
different risk posture and has to be a decision somebody took, not a silence". It was taken,
it is recorded, and three things follow from it:

1. A request body cannot be built without a `TenantScope` (`supermemory_wire.search_payload`
   takes one positionally and re-asserts the tag it wrote).
2. Every record that comes BACK is re-checked against the same scope and dropped if it does
   not carry the tag. The filter we send and the filter the server honoured are different
   facts, and against a single-tenant build only the second one is worth anything.
3. `kb_documents` stays ours (§8.4), so DPDP erasure remains one statement we can prove
   returned zero rows. `deletion_proof` is False here for the same reason
   `per_tenant_namespace` is: we cannot check their delete.

--------------------------------------------------------------------------------
HARD RULE 7: THE PRICE IS CHECKED BEFORE THE PROVIDER IS SELECTED
--------------------------------------------------------------------------------
A search embeds the question, and on box 2 that embedding must not be local (§8.3) — so it
is bought from a model vendor on OUR account, per question. `search_is_billable()` asks
`billing/rates.llm_price_is_billable` of the model an operator says the install is
configured with, BEFORE a request is made, exactly as `retrieval/embedding.
embedding_price_is_billable` and `kb/pack_vectors.pack_embedding_is_billable` do. No price,
no provider: `supermemory_t3` returns None and the Postgres retriever answers. No figure is
invented here and none is wired — the Gemini embedding price is UNVERIFIED in this tree
(§10.4) and becomes billable only when an operator enters their own invoice figure in the
ops console.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Final, Protocol
from uuid import UUID

import httpx
from calevate_shared.retrieval import (
    RetrievalCapabilities,
    RetrievalProvider,
    RetrievalRequest,
    RetrievalResult,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.billing.rates import llm_price_is_billable
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.retrieval.capabilities import require_tier
from apps.api.retrieval.supermemory_wire import (
    ASSUMED_CONTRACT,
    SupermemoryWireMismatchError,
    TenantScope,
    WireContract,
    delete_payload,
    ingest_payload,
    parse_search,
    search_payload,
)

log = get_logger(__name__)

#: OUR name for this implementation — a metric label, a log field and the value
#: `Settings.retrieval_provider` takes. Never shown to a client (hard rule 2's reasoning).
PROVIDER_NAME: Final = "supermemory"

#: `usage_events.meta.feature` for a dashboard question answered out of box 3.
#:
#: ITS OWN NAME, on `retrieval/embedding.ASSIST_FEATURE_KB_SEARCH`'s argument rather than a
#: new one: the same question asked of the same corpus costs a different amount through a
#: different store, and an operator comparing the two — which is the entire point of putting
#: a provider behind a switch — cannot do it from a merged number. It bills the CLIENT's AI
#: quota like every other thing their own click caused.
ASSIST_FEATURE_SUPERMEMORY_SEARCH: Final = "supermemory_search"

#: Wall clock for one search. Short because a person is waiting on it and because the
#: fallback is cheap: a hung box 3 must cost a slow tool call, not a hung copilot turn.
#: Not a vendor fact — a budget of ours, and the only number here that is not a guess about
#: somebody else's software.
SEARCH_TIMEOUT_S: Final = 8.0


#: Wall clock for one WRITE — an ingest or a withdrawal. Longer than the search budget and
#: for the opposite reason: nobody is waiting on it (it runs after a publish has already
#: been decided, or on a background sweep), and the vendor's own LLM extraction happens
#: inside this call on the way in (§10.4). What it still must not do is hold a publish
#: transaction open indefinitely, which is what a budget rather than "no timeout" buys.
WRITE_TIMEOUT_S: Final = 20.0


class SupermemoryTransport(Protocol):
    """The one thing that touches the network, so tests can be network-free.

    A PROTOCOL rather than an httpx client passed around, for the reason
    `engine/vendor_http.py` takes the same shape: the adapter's logic — scoping, parsing,
    metering, falling back — is the part worth testing, and it is worth testing against
    every response a vendor we cannot reach might produce. A fake transport gives all of
    them; a mocked httpx gives them with more ceremony and less clarity.
    """

    async def post(
        self, path: str, payload: dict[str, Any], *, timeout_s: float = SEARCH_TIMEOUT_S
    ) -> dict[str, Any]:
        """The decoded JSON object, or raise `httpx.HTTPError` / `TimeoutError`.

        ONE VERB FOR EVERY CALL, reads and writes alike. The vendor's delete surface is
        assumed to be a POST for the reason `WireContract.delete_path` gives — one guessed
        auth shape, one method to correct — so this protocol has no second method to keep
        in step with it.
        """
        ...


class HttpxTransport:
    """The real transport: one POST, bearer auth, our own timeout.

    **THE AUTH HEADER IS ASSUMED** like everything else about this surface — a bearer token
    is the overwhelmingly common shape and that is a prior, not a reading. It is here rather
    than in `ASSUMED_CONTRACT` because it is the only assumption whose correction changes a
    header and not a body; it is named in this docstring so a reader looking for the
    assumption list finds it from either end.
    """

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def post(
        self, path: str, payload: dict[str, Any], *, timeout_s: float = SEARCH_TIMEOUT_S
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise SupermemoryWireMismatchError(
                f"the response body was {type(body).__name__}, not a JSON object"
            )
        return body


class SupermemoryClient:
    """The wire, scoped. **Every method that reaches it takes a `TenantScope` first.**

    That is asserted rather than intended: `tests/retrieval_supermemory_test.py::
    test_no_wire_method_can_be_called_without_a_tenant_scope` reads the signatures, so a
    method added later without one fails the suite instead of shipping an unscoped query.
    """

    def __init__(
        self, transport: SupermemoryTransport, *, contract: WireContract = ASSUMED_CONTRACT
    ) -> None:
        self._transport = transport
        self._contract = contract

    async def search(self, scope: TenantScope, *, question: str, k: int) -> dict[str, Any]:
        """One scoped search. Returns the raw body; parsing is the adapter's job.

        The split is deliberate: this class owns "what went on the wire", `parse_search`
        owns "what our vocabulary makes of it", and the adapter owns "what to do when
        either was wrong". Three small things that can each be read in one sitting, rather
        than one method that is the whole integration.
        """
        return await self._transport.post(
            self._contract.search_path,
            search_payload(scope, question=question, k=k, contract=self._contract),
        )

    async def ingest(
        self,
        scope: TenantScope,
        *,
        document_id: UUID,
        content: str,
        source_id: UUID,
        source_label: str,
        document_version: int,
    ) -> dict[str, Any]:
        """Write ONE published chunk into box 3, under this tenant's tags.

        One document per call rather than a batch, and that is a decision rather than a
        simplification: a batch endpoint is one more shape nobody here has read, and a
        partial batch failure would leave `kb_index_documents` unable to say which half
        landed — which is the one question the ledger exists to answer. The cost is one
        round trip per chunk on a path where nobody is waiting, and the sweep's per-tick
        ceiling is what bounds it.
        """
        return await self._transport.post(
            self._contract.ingest_path,
            ingest_payload(
                scope,
                document_id=document_id,
                content=content,
                source_id=source_id,
                source_label=source_label,
                document_version=document_version,
                contract=self._contract,
            ),
            timeout_s=WRITE_TIMEOUT_S,
        )

    async def forget(
        self, scope: TenantScope, *, document_ids: Sequence[UUID] = ()
    ) -> dict[str, Any]:
        """Withdraw documents from box 3: the ids named, or — with none — the whole scope.

        The two callers are a withdrawal (ids, from the ledger) and a DPDP erasure (no ids,
        the tenant tag). Both end here so there is ONE place a delete body is built, which
        is what makes `delete_payload`'s tenant-tag assertion worth anything.
        """
        return await self._transport.post(
            self._contract.delete_path,
            delete_payload(scope, document_ids=document_ids, contract=self._contract),
            timeout_s=WRITE_TIMEOUT_S,
        )


def search_is_billable() -> bool:
    """May a Supermemory search's cost reach `unit_cost_paid`? **HARD RULE 7's PRE-FLIGHT.**

    Asked before the provider is SELECTED, not before each call, which is one step earlier
    than `retrieval/embedding.embedding_price_is_billable` manages and is the right place
    here: an unpriced leg is not a degraded search, it is a store we must not query at all,
    and `get_retriever` is where a store stops being queried.

    `billing/rates.llm_price_is_billable` is asked rather than a second rule written here —
    it is total, never raises, and already encodes the only two grounds this repository
    accepts (an operator attested it, or the catalogue figure was read from the vendor).
    False when no model is named, because a search whose cost we cannot even look up is the
    same unmetered spend as one whose price nobody entered.
    """
    model = (get_settings().supermemory_embedding_model or "").strip()
    return bool(model) and llm_price_is_billable(model)


class SupermemoryRetriever:
    """T3 from box 3, with the Postgres retriever underneath it. One `RetrievalProvider`.

    **IT DEGRADES, IT DOES NOT FAIL** (§8.5: "if it is down, calls do not notice and uploads
    do not notice — only dashboard search degrades to the Postgres fallback"). Unreachable
    host, timeout, HTTP error, a body the assumed contract does not describe: all four end
    in the fallback answering, because from the client's seat they are one event — box 3 did
    not answer — and the store we run ourselves still holds their approved knowledge.

    THE REJECTED ALTERNATIVE was raising a `ProblemError` and letting the copilot surface
    "knowledge search is unavailable". It is honest and it is worse: the passages exist in
    `kb_chunks` either way, so the client would be told we cannot answer a question we can
    answer, over an outage in a box that was added to make search better. A degraded answer
    with the provider named in the log is the version an operator can act on and a client
    never has to.
    """

    name = PROVIDER_NAME

    #: Declared, never discovered (the port's rule), and two of these are the decision §8.4
    #: forced rather than defaults:
    #:
    #: `per_tenant_namespace` is **False** — the local build is single-tenant with one API
    #: key, so a container tag is a filter we send and not a wall the server enforces. The
    #: port defines False as exactly that, and `tiered._union` ANDs this field, so a
    #: composite carrying this adapter truthfully reports False too.
    #:
    #: `deletion_proof` is **False** — there IS a second copy now, and we cannot prove a
    #: delete landed in it. `kb_documents` staying ours (§8.4 reason 2) is what keeps DPDP
    #: erasure provable; claiming the vendor's delete here would be the silence that rule
    #: exists to refuse.
    #:
    #: `hybrid_search` is **False** and that is an UNKNOWN rather than a measurement: nobody
    #: here has read what Supermemory's search does. Declaring a capability we have not seen
    #: is the precise defect `RetrievalCapabilities` was introduced to delete — and False
    #: costs only that `hybrid_search` callers are refused by name, which is recoverable,
    #: while a wrong True is not.
    capabilities = RetrievalCapabilities(
        compiled_facts=False,
        semantic_search=True,
        hybrid_search=False,
        reranking=False,
        per_tenant_namespace=False,
        deletion_proof=False,
        # The request model's own ceiling, so a `k` this adapter would have to clamp is a
        # `k` the port should have refused — `pgvector.py`'s rule, for its reason.
        max_k=20,
    )

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: SupermemoryClient,
        fallback: RetrievalProvider,
        contract: WireContract = ASSUMED_CONTRACT,
    ) -> None:
        self._session = session
        self._client = client
        self._fallback = fallback
        self._contract = contract

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Ask box 3; on any failure, answer from Postgres instead.

        A tier this adapter cannot serve refuses BY NAME before anything is asked, unless
        the caller opted into degrading — `pgvector.py`'s order, unchanged, because the two
        adapters are interchangeable and a caller must not be able to tell which one is
        configured from the shape of a refusal.
        """
        started = time.perf_counter()
        missing = self.capabilities.serves(request.tier)
        if missing is not None and not request.allow_degrade:
            require_tier(request.tier, provider=self)

        scope = TenantScope.for_request(request)
        try:
            body = await self._client.search(scope, question=request.question, k=request.k)
            passages, rejected = parse_search(body, scope=scope, contract=self._contract)
        except (httpx.HTTPError, TimeoutError, SupermemoryWireMismatchError) as failure:
            return await self._degrade(request, failure)

        if rejected:
            # THE TENANCY TELL. Records came back that did not carry the tenant tag we asked
            # for — the server ignored our filter, or a contract key is wrong, or the index
            # has untagged rows. Counts and ids only (hard rule 6); never what was in them.
            log.error(
                "supermemory_records_out_of_scope",
                extra={
                    "tenant_id": str(request.tenant_id),
                    "rejected": rejected,
                    "kept": len(passages),
                },
            )
        await self._meter(body, tenant_id=request.tenant_id)
        return RetrievalResult(
            passages=passages,
            requested_tier=request.tier,
            served_tier="t3",
            unmet_capability=missing,
            provider=self.name,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )

    async def _degrade(self, request: RetrievalRequest, failure: Exception) -> RetrievalResult:
        """Box 3 did not answer. Postgres does, and the RESULT NAMES POSTGRES.

        Reporting `self.name` on a result the fallback produced would make the one
        observability field that says where an answer came from a lie — `tiered.py` makes
        the same argument for the opposite case. So the fallback's own result is returned
        untouched, and the log line beside it is what says a degrade happened.

        Hard rule 6: the exception's TYPE, never its text. An HTTP error body quotes the
        request, and the request is a person's own question.
        """
        log.warning(
            "supermemory_degraded_to_postgres",
            extra={
                "tenant_id": str(request.tenant_id),
                "error": type(failure).__name__,
                "fallback": self._fallback.name,
            },
        )
        return await self._fallback.retrieve(request)

    async def _meter(self, body: dict[str, Any], *, tenant_id: UUID) -> None:
        """Record what the search cost, or say plainly that it could not be recorded.

        **WHETHER THE VENDOR REPORTS TOKEN USAGE AT ALL IS UNKNOWN** — nobody here has read
        a response — so this reads the assumed usage block and, when it is absent, writes
        nothing and logs at ERROR. The two rejected alternatives are both worse: a `0` would
        be a `usage_events` row asserting a search was free, and an estimate from the
        question's length would be a number we made up reaching `unit_cost_paid`, which is
        the exact thing hard rule 7 forbids. ERROR because unmetered spend is not a
        degradation an operator can leave running — the answer is to correct
        `ASSUMED_CONTRACT` from the vendor's docs, or to set `retrieval_provider` back.

        The price itself was settled before this provider was ever selected
        (`search_is_billable`), so `record_ai_assist_usage` cannot reach its raise here.
        """
        model = (get_settings().supermemory_embedding_model or "").strip()
        usage = body.get(self._contract.usage_key)
        tokens = usage.get(self._contract.usage_tokens_key) if isinstance(usage, dict) else None
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            log.error(
                "supermemory_search_unmetered",
                extra={
                    "tenant_id": str(tenant_id),
                    "model": model,
                    "usage_present": usage is not None,
                },
            )
            return
        await record_ai_assist_usage(
            self._session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=tokens,
            # An embedding has no output half — `retrieval/embedding.embed_query_vector`
            # says the same of its own usage block, and for the same reason: 0 is the truth
            # about what was bought, not a default.
            tokens_out=0,
            model=model,
            feature=ASSIST_FEATURE_SUPERMEMORY_SEARCH,
        )

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """THE FALLBACK'S STAMP, and that is not a shortcut — it is the more correct one.

        The port wants a token that changes whenever this tenant's retrievable knowledge
        changes. §8.4 keeps `kb_documents` ours precisely because it is the authority on
        what a tenant has published; box 3 is a projection of it. So the Postgres stamp
        moves on exactly the events that should invalidate a cached answer, and it moves
        whether or not box 3 is reachable — which a vendor-side index version would not.

        It also costs no vendor round trip on a path that runs BEFORE the cache, on every
        question. The rejected alternative — an index version read from Supermemory — would
        have put a network call in front of the cache hit that exists to avoid one, and
        would have needed a second endpoint this repository would have had to guess.
        """
        return await self._fallback.knowledge_epoch(request)


def supermemory_t3(
    session: AsyncSession, *, fallback: RetrievalProvider
) -> RetrievalProvider | None:
    """The configured adapter, or None with the reason logged. **The one constructor.**

    Four preconditions, each of which an operator sets in a different place and each of
    which is named in the log line rather than summarised: the base URL, the credential, the
    model the install embeds with, and that model having a price hard rule 7 will stand
    behind. Nothing is invented for a missing one and nothing half-works — `get_retriever`
    answers the question from Postgres and says why, which is BACKEND-PATTERNS §2's tolerant
    boot applied to a store rather than to a credential.
    """
    settings = get_settings()
    base_url = (settings.supermemory_base_url or "").strip()
    api_key = (settings.supermemory_api_key or "").strip()
    billable = search_is_billable()
    if not base_url or not api_key or not billable:
        log.error(
            "retrieval_supermemory_unconfigured",
            # Which precondition failed, and never the credential or the URL itself.
            extra={
                "base_url": bool(base_url),
                "credential": bool(api_key),
                "model": bool((settings.supermemory_embedding_model or "").strip()),
                "priced": billable,
            },
        )
        return None
    return SupermemoryRetriever(
        session,
        client=SupermemoryClient(HttpxTransport(base_url=base_url, api_key=api_key)),
        fallback=fallback,
    )


__all__ = [
    "ASSIST_FEATURE_SUPERMEMORY_SEARCH",
    "PROVIDER_NAME",
    "SEARCH_TIMEOUT_S",
    "WRITE_TIMEOUT_S",
    "HttpxTransport",
    "SupermemoryClient",
    "SupermemoryRetriever",
    "SupermemoryTransport",
    "search_is_billable",
    "supermemory_t3",
]
