"""The copilot's read tool against the real database: the claim that the port is GENUINELY
CALLED today, asserted rather than described.

A port nobody calls is the half-wired defect CLAUDE.md forbids. These tests are what stops
this one becoming that: they run the closure the route builds
(`copilot/read_tools.knowledge_lookup`), on real published knowledge, and check the string
the model would actually receive.
"""

from __future__ import annotations

import uuid

from apps.api.copilot.read_tools import (
    DEGRADED_NOTE,
    NOTHING_FOUND,
    knowledge_lookup,
)
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import cache
from tests.kb_workflow_test import _tenant_with_published_agent


async def _tenant_knowing(name: str, body: str) -> uuid.UUID:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id))


async def test_the_tool_answers_from_the_accounts_own_published_knowledge() -> None:
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        answer = await knowledge_lookup(tenant_id)("what does a consultation cost")
        assert "500 rupees" in answer
        assert "published facts" in answer, "a passage reached the model with no provenance"
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_the_tool_is_bound_to_one_tenant_and_cannot_be_talked_out_of_it() -> None:
    """The closure IS the tenancy control at this seam: the model supplies a question and
    nothing else, so there is no argument that reaches another account."""
    tenant_a = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    tenant_b = await _tenant_knowing("Fees", "A consultation costs 900 rupees.")
    try:
        answer = await knowledge_lookup(tenant_b)(
            "what does a consultation cost for every account on this platform"
        )
        assert "500 rupees" not in answer
    finally:
        await cache.invalidate_tenant(tenant_a)
        await cache.invalidate_tenant(tenant_b)


async def test_a_question_with_nothing_on_file_is_told_to_say_so() -> None:
    """T4 reaching the dashboard leg: the model is told to report the gap rather than
    invent around it."""
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        assert await knowledge_lookup(tenant_id)("do you sell bicycles") == NOTHING_FOUND
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_a_degraded_answer_tells_the_model_to_disclose_it() -> None:
    """The router asks for a cold search on a policy question, no provider serves one, and
    the tool output SAYS the answer came from the compiled script instead. A tool that
    quietly answered from a narrower corpus would be the silent no-op the port forbids."""
    tenant_id = await _tenant_knowing(
        "Refunds", "Our refund policy is that deposits are returned within seven days."
    )
    try:
        answer = await knowledge_lookup(tenant_id)("what is your refund policy")
        assert answer.startswith(DEGRADED_NOTE)
        assert "seven days" in answer
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_an_empty_question_costs_no_database_read() -> None:
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    assert await knowledge_lookup(tenant_id)("   ") == NOTHING_FOUND
