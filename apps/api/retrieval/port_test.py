"""The port's contract, asserted the way `packages/shared/tests/engine_conformance/` asserts
the VoiceEngine one: against the Protocol and against the declaration, never against an
implementation's internals.

These are the tests a SECOND implementation must also pass. When the D-28 bake-off names a
provider, its adapter is added to `PROVIDERS` below and everything here runs against it.
"""

from __future__ import annotations

import uuid

import pytest
from calevate_shared.retrieval import (
    RetrievalCapabilities,
    RetrievalProvider,
    RetrievalRequest,
)
from pydantic import ValidationError

from apps.api.retrieval.capabilities import (
    RETRIEVAL_CAPABILITY_ABSENT,
    RetrievalCapabilityAbsentError,
    require_tier,
)
from apps.api.retrieval.compiled_facts import T0_CAPABILITIES, CompiledFactsRetriever

#: Every implementation of the port. One today; the bake-off's winner joins it.
PROVIDERS: list[RetrievalProvider] = [CompiledFactsRetriever(session=None)]  # type: ignore[arg-type]


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.name)
def test_every_implementation_satisfies_the_protocol(provider: RetrievalProvider) -> None:
    assert isinstance(provider, RetrievalProvider)
    assert provider.name
    assert isinstance(provider.capabilities, RetrievalCapabilities)


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.name)
def test_every_implementation_declares_the_two_properties_this_product_cannot_ship_without(
    provider: RetrievalProvider,
) -> None:
    """TRD §6's bake-off criteria (b) hard per-tenant isolation and (f) deletion with proof.

    Asserted rather than scored: a provider that cannot isolate tenants is not a candidate
    with a low score, it is disqualified by hard rule 1. FAILS IF: an adapter is added that
    declares False for either — which is the moment somebody has to argue it in the
    decision log rather than in a config file.
    """
    assert provider.capabilities.per_tenant_namespace
    assert provider.capabilities.deletion_proof


def test_a_capability_declaration_cannot_be_mutated_at_runtime() -> None:
    """Frozen for `EngineCapabilities`' reason: a capability two callers can disagree about
    is not a capability."""
    with pytest.raises(ValidationError):
        T0_CAPABILITIES.semantic_search = True  # type: ignore[misc]


def test_a_tier_the_provider_cannot_serve_refuses_by_name() -> None:
    """THE PORT'S CENTRAL RULE. Not a crash and not a silent empty list — a refusal that
    carries the capability as a FIELD, so a metric, a test and an operator read one token.
    """
    provider = CompiledFactsRetriever(session=None)  # type: ignore[arg-type]
    with pytest.raises(RetrievalCapabilityAbsentError) as refused:
        require_tier("t3", provider=provider)
    assert refused.value.capability == "semantic_search"
    assert refused.value.code == RETRIEVAL_CAPABILITY_ABSENT
    problem = refused.value.as_problem()
    # Our vocabulary reaches the client; the provider's name does not (hard rule 2).
    assert provider.name not in str(problem)
    assert "remediation" in problem


def test_the_tier_it_can_serve_does_not_refuse() -> None:
    require_tier("t0", provider=CompiledFactsRetriever(session=None))  # type: ignore[arg-type]


def test_the_refusal_is_a_different_event_from_an_empty_result() -> None:
    """ "We looked and found nothing" is T4; "we never looked" is this. A caller that could
    not tell them apart would tell a client their published knowledge is missing."""
    assert T0_CAPABILITIES.serves("t0") is None
    assert T0_CAPABILITIES.serves("t3") == "semantic_search"
    # t4 needs no store at all: it is what the agent SAYS when nothing scored.
    assert T0_CAPABILITIES.serves("t4") is None


def test_a_request_is_bounded_at_its_edges() -> None:
    """Everything that reaches a store or a model is bounded (D-302)."""
    with pytest.raises(ValueError):
        RetrievalRequest(tenant_id=uuid.uuid4(), question="x" * 2001)
    with pytest.raises(ValueError):
        RetrievalRequest(tenant_id=uuid.uuid4(), question="hours", k=1000)
    with pytest.raises(ValueError):
        RetrievalRequest(tenant_id=uuid.uuid4(), question="")


def test_a_request_refuses_a_field_nobody_declared() -> None:
    """`extra="forbid"`: a caller that thinks it is passing a filter must find out here,
    not by watching it be ignored."""
    with pytest.raises(ValueError):
        RetrievalRequest(tenant_id=uuid.uuid4(), question="hours", namespace="x")  # type: ignore[call-arg]
