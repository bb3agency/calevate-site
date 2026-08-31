"""The retrieval capability seam: ONE selector, ONE refusal, authored reason codes.

The fifth instance of a shape this repo has settled four times — `billing/payments.
payment_capability`, `ingest/meta.lead_retrieval_capability`, `workers/sheets_sync.
get_sheets_transport`, and `engine/capabilities.py` (D-93), which this one is modelled on
line for line. It is deliberately not a fifth *design*.

WHY THE REFUSAL IS A `ProblemError` SUBCLASS. BACKEND-PATTERNS §3's error ladder is
`ProblemError`; a second exception hierarchy for one family of failures is two ways to do
one thing. Subclassing keeps every handler, status mapping and log site working and adds
the one thing a bare `ProblemError` could not carry — the capability NAME as a field, so a
test, a metric and an operator read the same token instead of parsing English prose.

ONE `code` FOR EVERY CAPABILITY, for `ENGINE_CAPABILITY_ABSENT`'s reason: `code` is the
stable machine identifier the frontend switches on and the last segment of the problem
`type` URL, so a per-capability code would mint six problem types for one condition.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.retrieval import (
    RetrievalCapabilityName,
    RetrievalProvider,
    RetrievalTier,
)

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: The one machine code for "the configured retrieval provider cannot do this".
RETRIEVAL_CAPABILITY_ABSENT: Final = "retrieval_capability_absent"

#: What a person is told about each absent capability, in one sentence they can act on.
#: Authored per capability rather than generated, because "we cannot do X" is useless
#: without "so do Y instead" — and the Y differs. None of these names a vendor or a tier
#: code: a client can act on "add it to your published knowledge", not on "t3".
_REMEDIATION: Final[dict[RetrievalCapabilityName, str]] = {
    "compiled_facts": (
        "This agent has no published knowledge yet. Add and approve a knowledge source, "
        "then publish the agent — approved knowledge is what the agent can answer from."
    ),
    "semantic_search": (
        "Searching across everything this account has published is not switched on yet. "
        "Your agent still answers from the facts compiled into its script; ask about "
        "those, or contact us."
    ),
    "hybrid_search": (
        "Keyword-plus-meaning search is not available on this account. A plain search of "
        "published knowledge is still available."
    ),
    "reranking": (
        "Re-ranking results is not available on this account. Results are returned in "
        "the order the search produced them."
    ),
    "per_tenant_namespace": (
        "Knowledge search is not available on this account. Contact us — this is a "
        "configuration problem on our side, not yours."
    ),
    "deletion_proof": (
        "Deleting knowledge from the search index cannot be confirmed on this account. "
        "Contact us before relying on a deletion — we will confirm it by hand."
    ),
}


class RetrievalCapabilityAbsentError(ProblemError):
    """The refusal for a capability the configured retrieval provider does not have.

    `kind="dependency"` for `EngineCapabilityAbsentError`'s reason: the ladder already maps
    that kind to the right status and marks it retryable-or-not consistently. Retrying will
    not help, but neither does inventing a kind — `remediation` is what tells them what to
    do.

    **NOT raised for a search that found nothing.** "We looked and there is nothing on
    file" is `RetrievalResult.is_empty()` and is TRD §6's T4 (refuse and escalate); this is
    "we never looked". Conflating them is how a client comes to be told their published
    knowledge is missing when the truth is that a provider was never wired up.
    """

    def __init__(self, capability: RetrievalCapabilityName, *, provider: str) -> None:
        self.capability: RetrievalCapabilityName = capability
        self.provider = provider
        super().__init__(
            kind="dependency",
            code=RETRIEVAL_CAPABILITY_ABSENT,
            title="That kind of search is not available",
            # Our vocabulary, no provider name (hard rule 2): which store is configured is
            # OUR deployment detail and a client cannot act on it.
            detail=f"Knowledge retrieval here does not provide: {capability}.",
            remediation=_REMEDIATION[capability],
        )


def retrieval_lacks(
    capability: RetrievalCapabilityName, *, provider: str
) -> RetrievalCapabilityAbsentError:
    """Build the refusal AND record it, so "which capability do clients keep hitting" is a
    log query rather than an investigation. Ids and our own vocabulary only (hard rule 6).
    """
    log.warning(
        "retrieval_capability_absent", extra={"capability": capability, "provider": provider}
    )
    return RetrievalCapabilityAbsentError(capability, provider=provider)


def require_tier(tier: RetrievalTier, *, provider: RetrievalProvider) -> None:
    """Raise unless `provider` can serve `tier`. THE guard, and the only one.

    Takes the provider rather than looking one up, for `require_capability`'s reason: a
    guard that checked a different instance from the one about to be called is a guard that
    passes on the wrong evidence.
    """
    missing = provider.capabilities.serves(tier)
    if missing is not None:
        raise retrieval_lacks(missing, provider=provider.name)


__all__ = [
    "RETRIEVAL_CAPABILITY_ABSENT",
    "RetrievalCapabilityAbsentError",
    "require_tier",
    "retrieval_lacks",
]
