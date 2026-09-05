"""The whole port end to end, against the real database, the real Redis and the real
approval gate: what is retrievable, what a hit means, and — the one that matters most —
that correcting a fact cannot be answered from yesterday's cache.
"""

from __future__ import annotations

import uuid

from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import cache
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.service import look_up
from calevate_shared.retrieval import RetrievalRequest
from tests.kb_workflow_test import _tenant_with_published_agent


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, name: str, body: str) -> None:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )


async def _tenant_knowing(name: str, body: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), name=name, body=body)
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def test_published_knowledge_is_retrievable_with_its_provenance() -> None:
    tenant_id, agent_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    async with tenant_session(tenant_id) as session:
        decision, result = await look_up(session, tenant_id=tenant_id, question="what does it cost")
    try:
        assert not result.is_empty()
        assert "500 rupees" in " ".join(passage.text for passage in result.passages)
        provenance = result.passages[0].provenance
        assert provenance.tier == "t0"
        assert provenance.agent_id == agent_id
        assert provenance.label, "a passage with no provenance cannot be cited or checked"
        assert decision.intent == "services_pricing"
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_knowledge_that_was_never_approved_is_not_retrievable() -> None:
    """THE GATE, asserted from the retrieval side. "Approved" is not a UI step, it is the
    definition of what may be retrieved — and this is the test that fails the day somebody
    makes the retriever read `kb_documents` directly to get better recall.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Secret pricing",
            body="A consultation costs 500 rupees.",
        )
        # Submitted only: pending_approval, never approved, never published.
    async with tenant_session(tenant_id) as session:
        _, result = await look_up(
            session, tenant_id=uuid.UUID(str(tenant_id)), question="what does it cost"
        )
    assert result.is_empty()


async def test_a_repeated_question_is_served_from_the_cache() -> None:
    tenant_id, _ = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        async with tenant_session(tenant_id) as session:
            _, first = await look_up(session, tenant_id=tenant_id, question="what does it cost")
            _, second = await look_up(session, tenant_id=tenant_id, question="what does it cost")
        assert first.cached is False
        assert second.cached is True
        assert [p.text for p in first.passages] == [p.text for p in second.passages]
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_a_correction_cannot_be_answered_from_the_cache() -> None:
    """**THE TEST THIS WHOLE CACHE DESIGN EXISTS FOR.** An owner corrects a published fact;
    the next caller must hear the correction, not the fifteen-minute-old answer.

    Nothing here deletes a key. The publish mints a new prompt version, the epoch moves, and
    every question lands on a key the old answer is not under. FAILS IF: somebody keys the
    cache on the question alone, or invalidation is moved to an event a writer must
    remember to fire.
    """
    tenant_id, agent_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        async with tenant_session(tenant_id) as session:
            _, before = await look_up(session, tenant_id=tenant_id, question="what does it cost")
        assert "500 rupees" in " ".join(p.text for p in before.passages)

        await _publish(tenant_id, agent_id, name="Fees", body="A consultation costs 900 rupees.")

        async with tenant_session(tenant_id) as session:
            _, after = await look_up(session, tenant_id=tenant_id, question="what does it cost")
        answer = " ".join(p.text for p in after.passages)
        assert "900 rupees" in answer, "the correction did not reach the caller"
        assert "500 rupees" not in answer, "a stale cached answer survived a correction"
        assert after.cached is False, "the corrected answer came off the old key"
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_the_epoch_moves_when_knowledge_is_published_and_not_otherwise() -> None:
    """The stamp's two required properties, asserted directly: stable while nothing changes,
    different the moment something does."""
    tenant_id, agent_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    request = RetrievalRequest(tenant_id=tenant_id, question="what does it cost")
    async with tenant_session(tenant_id) as session:
        provider = CompiledFactsRetriever(session)
        first = await provider.knowledge_epoch(request)
        again = await provider.knowledge_epoch(request)
    assert first == again

    await _publish(tenant_id, agent_id, name="Fees", body="A consultation costs 900 rupees.")
    async with tenant_session(tenant_id) as session:
        after = await CompiledFactsRetriever(session).knowledge_epoch(request)
    assert after != first


async def test_an_open_ended_question_is_answered_degraded_and_says_so() -> None:
    """The router asks for t3, no provider serves t3, and the answer carries the unmet
    capability rather than pretending a search happened."""
    tenant_id, _ = await _tenant_knowing(
        "Refunds", "Our refund policy is that deposits are returned within seven days."
    )
    try:
        async with tenant_session(tenant_id) as session:
            decision, result = await look_up(
                session, tenant_id=tenant_id, question="what is your refund policy"
            )
        assert decision.tier == "t3"
        assert result.served_tier == "t0"
        assert result.unmet_capability == "semantic_search"
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_an_empty_answer_is_not_cached() -> None:
    """Caching a miss would keep saying "we don't know" for a quarter of an hour after the
    client added the missing knowledge."""
    tenant_id, _ = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        async with tenant_session(tenant_id) as session:
            _, first = await look_up(session, tenant_id=tenant_id, question="do you sell bicycles")
            _, second = await look_up(session, tenant_id=tenant_id, question="do you sell bicycles")
        assert first.is_empty() and second.is_empty()
        assert second.cached is False
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_a_question_carrying_a_phone_number_is_answered_but_never_cached() -> None:
    """Hard rule 6 must not cost the person their answer: the retrieval happens, only the
    caching is refused."""
    tenant_id, _ = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        async with tenant_session(tenant_id) as session:
            _, first = await look_up(
                session, tenant_id=tenant_id, question="what does it cost, call me on 9876543210"
            )
            _, second = await look_up(
                session, tenant_id=tenant_id, question="what does it cost, call me on 9876543210"
            )
        assert not first.is_empty()
        assert second.cached is False, "a question carrying a phone number reached the keyspace"
    finally:
        await cache.invalidate_tenant(tenant_id)
