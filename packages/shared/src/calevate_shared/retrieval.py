"""The RetrievalProvider portability contract (TRD §6) — the seam the D-28 bake-off lands on.

WHY THIS FILE EXISTS BEFORE THE PROVIDER DOES. TRD §6's bake-off is still open: the
candidates are a managed vector cloud, a memory API, pgvector, or the engine's own KB, and
the scorecard has not been run. Everything in this module is true whichever of those wins,
so writing it now makes the decision a drop-in instead of a rewrite — the same trick
`calevate_shared.engine` plays on the voice vendor, and deliberately the same SHAPE:

* the vocabulary is OURS (`Passage`, `Provenance`, `RetrievalTier`), so nothing above the
  adapter ever sees a provider's payload — hard rule 2's argument, applied to retrieval;
* what an implementation CAN DO is DECLARED (`RetrievalCapabilities`), never discovered by
  calling and failing, because a screen that offers a control the provider will refuse is
  the exact defect `EngineCapabilities` was introduced to delete (D-93);
* an absent capability produces a **named refusal** carrying the capability as a field
  (`apps/api/retrieval/capabilities.py::retrieval_lacks`), never a silent empty list. An
  empty result and "this provider cannot search" are different facts, and a caller that
  cannot tell them apart tells a client "we have nothing on file" when the truth is "we
  never looked".

WHAT IS DIFFERENT FROM `VoiceEngine`, AND WHY IT IS NOT A DIFFERENT DESIGN. A voice engine
is one process-wide vendor selected by `ENGINE=`; a retrieval provider is selected the same
way but its only implementation today (`apps/api/retrieval/compiled_facts.py`) reads OUR
OWN Postgres under the caller's tenant session. So `retrieve` takes a request object and
the adapter is CONSTRUCTED with whatever it needs (a session, later a client), rather than
the session riding on every method. A managed-provider adapter ignores the session it is
handed; that is one unused constructor argument against a whole second calling convention.

WHAT THIS PORT DELIBERATELY DOES NOT HAVE:

* **No ingestion.** Writing, chunking, approving and versioning knowledge is `apps/api/kb`
  and stays ours whichever provider wins (TRD §6, "the preview-and-approve gate stays
  ours"). A port that also owned ingestion would make the bake-off a rewrite again.
* **No embedding vocabulary.** No vectors, no dimensions, no distance metric, no namespace
  string. Those are provider facts; a port that names them has already chosen one.
* **No in-call route.** `tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_
  on_our_side` pins `apps/voice-runtime`'s mounted routes as an EQUALITY, because putting a
  retrieval endpoint on the audio path reverses D-33 and needs TRD §6.2's round-trip
  measurement first. Nothing here mounts anything.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: The five tiers TRD §6 names, spelled exactly as `kb_retrieval_logs.tier`'s CHECK
#: constraint spells them — so a tier this port serves and a tier the knowledge-gap report
#: records can never be two vocabularies.
#:
#: * ``t0`` compiled context (0ms): hot facts already spliced into the agent's system
#:   prompt at publish (`apps/api/agents/t0.py`). Answers ~80% with zero retrieval.
#: * ``t1``/``t2`` cache + speculative: TRD §6 calls these "provider-side or thin-cache".
#:   `apps/api/retrieval/cache.py` is the thin cache; it is a WRAPPER over a tier, not a
#:   tier an adapter serves, so no adapter declares t1/t2 and `serves()` answers False.
#: * ``t3`` cold lookup: hybrid search, top_k=3. The tier the bake-off is about.
#: * ``t4`` refuse-and-escalate: a PROMPT instruction (PROMPT-GUIDE §1) with no store
#:   behind it. It is in the vocabulary because the router can decide a question is
#:   unanswerable, and because `kb_retrieval_logs` already admits it — not because an
#:   adapter can serve it.
RetrievalTier = Literal["t0", "t1", "t2", "t3", "t4"]

#: Every capability an adapter answers for, as a closed set — `EngineCapabilityName`'s
#: argument verbatim: each value is a refusal reason an operator reads, a metric label and
#: a test's assertion, so a free-form string would let a typo become a capability that is
#: silently always absent.
#:
#: The last two are not features, they are the two properties this product cannot ship
#: without, and they are declared here so the bake-off scores them as code rather than as
#: prose: TRD §6's criterion (b) "hard per-tenant namespace isolation" and (f) "deletion
#: with proof via API" (DPDP erasure has to be provable on BOTH copies —
#: `apps/api/kb/models.py::KbDocument` keeps provider ids for exactly that).
RetrievalCapabilityName = Literal[
    "compiled_facts",
    "semantic_search",
    "hybrid_search",
    "reranking",
    "per_tenant_namespace",
    "deletion_proof",
]


class RetrievalCapabilities(BaseModel):
    """What ONE retrieval implementation can actually do, declared by its adapter.

    NO DEFAULTS, deliberately — `EngineCapabilities`' rule and for its reason: a new
    provider must answer every question in writing rather than inherit today's answers by
    omission, which is exactly how a T0-shaped assumption would get everywhere. Frozen,
    because a capability two callers can disagree about is not a capability.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Can it answer from facts ALREADY COMPILED and approved (T0)? True for the compiled
    #: -facts adapter; a pure vector store would answer False and serve t3 instead.
    compiled_facts: bool
    #: Dense/embedding search (T3). The capability the bake-off exists to buy.
    semantic_search: bool
    #: Dense + sparse together, TRD §6's "hybrid search top_k=3" and bake-off criterion (c).
    #: Separate from `semantic_search` because a provider that has only dense search is a
    #: real option with a real quality cost, and one boolean would hide the difference.
    hybrid_search: bool
    #: A cross-encoder rerank pass. TRD §6 forbids it IN CALL ("no in-call cross-encoder
    #: rerank"); it is declared because the latency-tolerant CRM paths may want it.
    reranking: bool
    #: Is one tenant's knowledge in a namespace another tenant's query CANNOT address?
    #: Hard rule 1 in the provider's own terms. False is not a shrug — it means tenancy is
    #: enforced only by our filter, which is a different risk posture and has to be a
    #: decision somebody took, not a silence.
    per_tenant_namespace: bool
    #: Can a deletion be PROVEN through the API (DPDP erasure, bake-off criterion (f))?
    deletion_proof: bool
    #: The most passages one call may ask for. A ceiling, not a default: `top_k=3` is
    #: TRD §6's in-call number and the caller's business, but a caller asking for 500 is a
    #: bug and the adapter is where it stops.
    max_k: int = Field(ge=1)

    def has(self, name: RetrievalCapabilityName) -> bool:
        """The generic ask, for callers holding a capability NAME rather than a field."""
        return bool(getattr(self, name))

    def serves(self, tier: RetrievalTier) -> RetrievalCapabilityName | None:
        """The capability `tier` needs and this adapter LACKS, or None if it can serve it.

        Returning the missing capability rather than a bool is what lets the one refusal
        name it: "this provider cannot do semantic_search" is actionable, "tier t3 is
        unavailable" is not. t1/t2 are never served by an adapter (see `RetrievalTier`),
        and t4 needs no store — it is what the agent says when nothing scored.
        """
        if tier == "t0":
            return None if self.compiled_facts else "compiled_facts"
        if tier in ("t1", "t2"):
            # Not an adapter's tier. Ask for the tier the cache would be sitting in front
            # of instead; answering "semantic_search" here would let a caller believe a
            # cache tier had been served by a store.
            return "semantic_search" if not self.semantic_search else None
        if tier == "t3":
            return None if self.semantic_search else "semantic_search"
        return None


class Provenance(BaseModel):
    """Where one passage came from, in OUR vocabulary — never the provider's.

    THIS IS THE HALF THAT MAKES A PASSAGE USABLE. A model handed anonymous text will
    paraphrase it as its own knowledge; a model handed "Fees (published knowledge for
    Sunrise Dental)" can cite it, and a human reading a transcript can check it. It is
    also what the knowledge-gap report needs and what a dispute asks for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: What a person would call this — a KB source name, or the compiled block. Never a
    #: provider document id and never a chunk hash: those are debugging aids that mean
    #: nothing to the client whose knowledge it is.
    label: str = Field(min_length=1, max_length=200)
    #: The tier that produced it, so a caller can tell a compiled fact from a cold lookup.
    tier: RetrievalTier
    #: The agent whose published knowledge this is. `None` only where a passage is
    #: tenant-wide rather than agent-scoped, which no implementation produces today.
    agent_id: UUID | None = None
    #: `kb_sources.id`, where the passage is traceable to one. `None` for the compiled T0
    #: block, which is an ARTIFACT of many sources plus the intake answers — claiming one
    #: source id for it would be a citation that does not check out.
    source_id: UUID | None = None


class Passage(BaseModel):
    """One retrieved span of APPROVED knowledge, with its provenance and its score.

    Bounded at 4000 characters because everything that reaches a model is bounded (D-302)
    and because a passage longer than that is a chunking failure, not a passage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    provenance: Provenance
    #: Higher is better, comparable only WITHIN one result. Deliberately not normalised to
    #: a probability: cosine similarity, BM25 and the compiled-facts overlap score below
    #: are three different quantities, and a caller that thresholds across providers on a
    #: number this port pretended was universal would be tuning against noise. `None` where
    #: an implementation ranks without scoring.
    score: float | None = None


class RetrievalRequest(BaseModel):
    """Given a tenant and a question, up to `k` passages. The whole port, in one object.

    An OBJECT rather than five arguments so a provider that needs a filter we have not
    invented yet is a field addition rather than a signature change at every call site.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    #: Whose knowledge. `None` = every live agent this tenant has, which is what a
    #: dashboard question means ("what do we tell callers about refunds?").
    agent_id: UUID | None = None
    question: str = Field(min_length=1, max_length=2000)
    #: TRD §6's in-call `top_k=3` is the default because it is the only k in this repo that
    #: was chosen rather than picked.
    k: int = Field(default=3, ge=1, le=20)
    #: The tier the ROUTER decided this question earns (`apps/api/retrieval/routing.py`).
    #: Not a hint: an adapter that cannot serve it must refuse by name, unless —
    tier: RetrievalTier = "t0"
    #: — the caller explicitly accepts a LOWER tier instead. Then the result carries
    #: `unmet_capability` and the caller MUST surface it. This is the one alternative to a
    #: refusal, and it is opt-in, typed, and visible in the result: a provider quietly
    #: answering a cold-lookup question out of compiled facts, with no field saying so, is
    #: precisely the silent no-op this port exists to forbid.
    allow_degrade: bool = False


class RetrievalResult(BaseModel):
    """What came back, and — as much as it matters — what did not.

    `requested_tier` and `served_tier` are both here because they can differ, and the
    difference is the answer to "why did the agent say it did not know?".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    passages: tuple[Passage, ...] = ()
    requested_tier: RetrievalTier
    served_tier: RetrievalTier
    #: Set when `allow_degrade` was honoured: the capability that would have been needed
    #: for `requested_tier`. `None` on every ordinary answer.
    unmet_capability: RetrievalCapabilityName | None = None
    #: The adapter's own name (`RetrievalProvider.name`), for logs and metric labels.
    provider: str
    #: Did this answer come out of the semantic cache rather than the store? Measured, not
    #: assumed — `apps/api/retrieval/cache.py` sets it.
    cached: bool = False
    #: Wall clock inside the port, milliseconds. Every latency number in this repo is
    #: MEASURED (hard rule 11); this is where the retrieval one is measured.
    elapsed_ms: float = Field(default=0.0, ge=0.0)

    def is_empty(self) -> bool:
        """Nothing scored. T4's condition (refuse and escalate) — and NOT the same event
        as a refusal, which raises."""
        return not self.passages


@runtime_checkable
class RetrievalProvider(Protocol):
    """The port. One method, and everything else is declaration.

    `runtime_checkable` for `VoiceEngine`'s reason: the conformance-style tests assert an
    adapter satisfies it without importing the adapter's module into the assertion.
    """

    #: OUR name for this implementation ("compiled-facts", later "qdrant", "pgvector").
    #: A config value and a metric label, never shown to a client.
    name: str

    #: What it can do. Read through `apps/api/retrieval/capabilities.py`'s selector, never
    #: off the attribute — one place asks, so "we are configured" and "we can actually do
    #: it" cannot disagree.
    capabilities: RetrievalCapabilities

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Up to `request.k` passages of APPROVED knowledge for `request.tenant_id`.

        Contract every implementation owes, and the conformance test asserts:

        1. **Tenant scoping is the implementation's job and is never optional.** Ours runs
           under an RLS session; a managed provider must filter on its own namespace. A
           passage belonging to another tenant is a hard-rule-1 breach, not a bug.
        2. **Only APPROVED knowledge.** Whatever a client has uploaded but not had approved
           is invisible here. The preview-and-approve gate is not a UI step, it is the
           definition of what is retrievable.
        3. **A tier it cannot serve RAISES a named refusal**, unless `allow_degrade`, in
           which case it serves the highest tier it can and says so in `unmet_capability`.
        4. **No caller PII.** A passage is business knowledge; a phone number in one means
           the ingestion gate let it through, and this is not the layer that fixes that.
        """
        ...

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        """A short token that CHANGES whenever this tenant's retrievable knowledge changes.

        THIS IS THE INVALIDATION STORY, and it is on the port rather than in the cache
        because only an implementation knows what "changed" means for the store it reads.

        Why a stamp and not an event. A cache invalidated by a publish HOOK is correct only
        while every writer remembers to call it — and the failure is silent, unbounded, and
        lands as a WRONG ANSWER ON A LIVE CALL after an owner corrects their hours. A cache
        keyed on a stamp derived from the data cannot go stale: a change mints a new key
        and every entry under the old one becomes unreachable, whether or not anybody
        remembered anything. The stale entries then age out on their TTL.

        The token is opaque, must be cheap (it is read BEFORE the cache, on every question),
        must be stable while nothing changes, and must never contain PII — it goes into a
        Redis key. Ours is the live prompt version, because publishing knowledge mints one
        (`apps/api/agents/t0.py`); a vector provider's would be its index version or the
        max `kb_sources.version` it has ingested.
        """
        ...


__all__ = [
    "Passage",
    "Provenance",
    "RetrievalCapabilities",
    "RetrievalCapabilityName",
    "RetrievalProvider",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalTier",
]
