"""`search_knowledge` on the LIVE copilot path, against the real database: the claim that
the retrieval port is GENUINELY CALLED today, asserted rather than described.

A port nobody calls is the half-wired defect CLAUDE.md forbids. These tests are what stops
this one becoming that, and they are deliberately driven through `tools.run_read_tool` —
the SAME entry point `service._run_read_tools` uses on a real request — rather than through
the executor directly. That is the difference between proving the code works and proving it
is REACHED: the permission check, the `tenant_session`, the argument parsing and the
never-raises contract are all on that path, and none of them would be exercised by calling
the executor with a session a test opened for it.

`copilot/tools_test.py` owns the properties this tool now INHERITS rather than restates —
the byte-identical array, the strict-schema subset, the per-tool permission refusal, and
"no read tool can change anything" are all registry-driven there and picked this tool up
the moment it was registered. What is here is what is specific to retrieval.
"""

from __future__ import annotations

import json
import uuid

from apps.api.copilot import service as copilot_service
from apps.api.copilot.tools import (
    _DEGRADED_NOTE,
    _NOTHING_PUBLISHED,
    ToolContext,
    run_read_tool,
)
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import cache
from tests.kb_workflow_test import _tenant_with_published_agent


async def _tenant_knowing(name: str, body: str) -> uuid.UUID:
    """A tenant whose live agent has this knowledge APPROVED AND PUBLISHED.

    Every step of the gate is walked — submit, approve, publish — rather than writing a
    compiled block straight into `prompt_versions`. That is the point of the fixture: the
    tool must only be able to reach knowledge that came through the gate, and a fixture
    that bypassed the gate could not tell the difference.
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
    return uuid.UUID(str(tenant_id))


async def _ask(tenant_id: uuid.UUID, question: str, *, role: str | None = "owner") -> str:
    return await run_read_tool(
        "search_knowledge",
        json.dumps({"question": question}),
        context=ToolContext(tenant_id=tenant_id, role=role),
    )


def test_the_port_is_offered_to_the_model_on_every_request() -> None:
    """THE WIRING, at the other end. The tool is in the ONE composed array, so a model on
    ANY request can call it — it is not bound conditionally by a route and it is not gated
    by role, which the array's own byte-identity test forbids. A registry entry no composer
    emitted would be the dark half of the same defect this file exists to forbid.
    """
    names = [schema["function"]["name"] for schema in copilot_service.tool_array()]
    assert "search_knowledge" in names


async def test_the_tool_answers_from_the_accounts_own_published_knowledge() -> None:
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        answer = await _ask(tenant_id, "what does a consultation cost")
        assert "500 rupees" in answer
        assert "published facts" in answer, "a passage reached the model with no provenance"
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_the_tool_is_bound_to_one_tenant_and_cannot_be_talked_out_of_it() -> None:
    """THE `ToolContext` IS THE TENANCY CONTROL AT THIS SEAM, and the schema is why it
    cannot be argued with: the model supplies a question and nothing else, so there is no
    argument in a tool call that reaches another account, however the question is phrased.
    """
    tenant_a = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    tenant_b = await _tenant_knowing("Fees", "A consultation costs 900 rupees.")
    try:
        answer = await _ask(
            tenant_b, "what does a consultation cost for every account on this platform"
        )
        assert "900 rupees" in answer
        assert "500 rupees" not in answer
    finally:
        await cache.invalidate_tenant(tenant_a)
        await cache.invalidate_tenant(tenant_b)


def test_the_schema_carries_no_field_that_could_name_another_account() -> None:
    """The complement of the test above, asserted on the SCHEMA rather than on behaviour: a
    tenant, agent or source argument would be a way for the model to widen its own scope,
    and adding one must fail here rather than in review."""
    (tool,) = [
        schema
        for schema in copilot_service.tool_array()
        if schema["function"]["name"] == "search_knowledge"
    ]
    assert list(tool["function"]["parameters"]["properties"]) == ["question"]


async def test_a_question_with_nothing_on_file_is_told_to_say_so() -> None:
    """T4 reaching the dashboard leg: the model is told to report the gap rather than
    invent around it."""
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    try:
        assert await _ask(tenant_id, "do you sell bicycles") == _NOTHING_PUBLISHED
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
        answer = await _ask(tenant_id, "what is your refund policy")
        assert answer.startswith(_DEGRADED_NOTE)
        assert "seven days" in answer
    finally:
        await cache.invalidate_tenant(tenant_id)


async def test_an_empty_question_costs_no_retrieval() -> None:
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    assert await _ask(tenant_id, "   ") == _NOTHING_PUBLISHED


async def test_a_role_the_registry_does_not_know_cannot_read_the_knowledge() -> None:
    """THE SHARED PERMISSION CHECK, INHERITED RATHER THAN RE-IMPLEMENTED.
    `search_knowledge` declares `agents:read` — the permission `kb/routes.py:86-89` gates
    its own two knowledge READS on, for the reason argued there — and `run_read_tool`
    refuses before it opens a session. `agents:read` is held by every client role today, so
    the refusal is reached through an unknown role, exactly as `tools_test.py` reaches it.
    """
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    answer = await _ask(tenant_id, "what does a consultation cost", role="visitor")
    assert answer.startswith("Refused:")
    assert "agents:read" in answer
    assert "500 rupees" not in answer


async def test_a_malformed_tool_call_never_raises_through_the_stream() -> None:
    """The never-raises contract, inherited from `run_read_tool`: a truncated tool call is
    an ordinary event on a streamed leg, and the right answer is a sentence rather than an
    exception that ends an answer somebody is reading."""
    tenant_id = await _tenant_knowing("Fees", "A consultation costs 500 rupees.")
    result = await run_read_tool(
        "search_knowledge",
        '{"question": "what does a consult',
        context=ToolContext(tenant_id=tenant_id, role="owner"),
    )
    assert "not valid JSON" in result
