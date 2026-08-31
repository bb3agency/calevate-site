"""Hard rule 1, on both halves of this package: the store and the cache.

A CACHE IS A CLASSIC CROSS-TENANT LEAK — one keyspace, many tenants, and a key that
forgets whose question it was answers the wrong business. So the proof here is in two
directions, not one: tenant B cannot READ what tenant A cached, and a caller that names
tenant A on tenant B's session gets nothing rather than B's rows.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import cache
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.service import look_up
from calevate_shared.retrieval import Passage, Provenance, RetrievalRequest, RetrievalResult
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls


async def _tenant_knowing(name: str, body: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A live agent whose compiled T0 block carries `body`, through the REAL path.

    Submitted, approved and published — never inserted — because what makes a fact
    retrievable is the approval gate, and a fixture that wrote the block directly would
    prove the ranker works on knowledge no human ever approved.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def test_a_tenant_retrieves_only_its_own_published_knowledge() -> None:
    """Two clinics, the same question, two different answers — and neither can see the
    other's price."""
    tenant_a, _ = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    tenant_b, _ = await _tenant_knowing("Fees", "A consultation costs 900 rupees.")

    async with tenant_session(tenant_a) as session:
        _, result_a = await look_up(session, tenant_id=tenant_a, question="what does it cost")
    async with tenant_session(tenant_b) as session:
        _, result_b = await look_up(session, tenant_id=tenant_b, question="what does it cost")

    text_a = " ".join(passage.text for passage in result_a.passages)
    text_b = " ".join(passage.text for passage in result_b.passages)
    assert "500 rupees" in text_a and "900 rupees" not in text_a
    assert "900 rupees" in text_b and "500 rupees" not in text_b


async def test_naming_another_tenant_on_this_session_returns_zero_rows() -> None:
    """THE BELT BESIDE RLS. `compiled_facts._live_blocks` filters on `tenant_id` as well as
    running under an RLS session, and this is the mistake that predicate defends: a caller
    holding tenant A's id on a session opened for tenant B. Without it the call returns B's
    knowledge and looks like a successful answer about A.
    """
    tenant_a, _ = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    tenant_b, _ = await _tenant_knowing("Fees", "A consultation costs 900 rupees.")

    async with tenant_session(tenant_b) as session:
        result = await CompiledFactsRetriever(session).retrieve(
            RetrievalRequest(tenant_id=tenant_a, question="what does it cost")
        )
    assert result.passages == (), "a mismatched tenant id must return nothing, not B's rows"


async def test_a_cached_answer_is_not_readable_by_another_tenant() -> None:
    """THE CACHE PROOF. Same question, same words, same epoch, same tier, same k — the only
    difference is whose it is, and that is enough."""
    question = "what are your opening hours"
    request_a = RetrievalRequest(tenant_id=uuid.uuid4(), question=question)
    request_b = RetrievalRequest(tenant_id=uuid.uuid4(), question=question)
    answer = RetrievalResult(
        passages=(
            Passage(
                text="Hours: mon-sat 09:30-18:00",
                provenance=Provenance(label="A — published facts", tier="t0"),
            ),
        ),
        requested_tier="t0",
        served_tier="t0",
        provider="compiled-facts",
    )

    assert await cache.put(request_a, epoch="1:1", result=answer)
    try:
        assert await cache.get(request_b, epoch="1:1") is None, "tenant B read tenant A's answer"
        hit = await cache.get(request_a, epoch="1:1")
        assert hit is not None and hit.cached
    finally:
        await cache.invalidate_tenant(request_a.tenant_id)


async def test_invalidating_one_tenant_leaves_the_other_alone() -> None:
    """The operator/erasure path is scoped by the key layout and cannot be widened by a
    caller — there is no argument that means "all tenants"."""
    question = "what are your opening hours"
    request_a = RetrievalRequest(tenant_id=uuid.uuid4(), question=question)
    request_b = RetrievalRequest(tenant_id=uuid.uuid4(), question=question)
    answer = RetrievalResult(
        passages=(
            Passage(
                text="Hours: mon-sat 09:30-18:00",
                provenance=Provenance(label="A — published facts", tier="t0"),
            ),
        ),
        requested_tier="t0",
        served_tier="t0",
        provider="compiled-facts",
    )
    await cache.put(request_a, epoch="1:1", result=answer)
    await cache.put(request_b, epoch="1:1", result=answer)
    try:
        assert await cache.invalidate_tenant(request_a.tenant_id) == 1
        assert await cache.get(request_a, epoch="1:1") is None
        assert await cache.get(request_b, epoch="1:1") is not None
    finally:
        await cache.invalidate_tenant(request_b.tenant_id)
