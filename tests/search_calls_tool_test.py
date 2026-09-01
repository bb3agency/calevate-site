"""`search_calls`: the copilot finds what a CALLER said, and never reads the raw column.

END TO END OVER REAL ROWS, on the SPARSE ARM ALONE. No embedding provider is configured in
tests, so `embed_query_vector` returns None and the dense arm is skipped — which is not a
weaker version of this test, it is the degradation the store is designed for
(`caller_search`: an unembedded chunk still answers) and it means these assertions do not
depend on a vendor being reachable from CI.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from apps.api.copilot.tools import ToolContext, run_read_tool
from apps.api.db.session import tenant_session
from apps.api.insights.service_test import _tenant
from apps.api.retrieval import call_chunks
from apps.api.retrieval.caller_projections import store_chunks
from sqlalchemy import text
from tests.caller_chunk_erasure_test import (
    AGENT_WORDS,
    CALLER_WORDS,
    _scrub_the_call_as_an_erasure_does,
    _seed_call,
)

pytestmark = pytest.mark.anyio


async def _seed() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant()
    call_id = await _seed_call(tenant_id, agent_id, ended_at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        for projection in (call_chunks.TURN_PROJECTION, call_chunks.SUMMARY_PROJECTION):
            chunks = await projection.discover(session, 100)
            await store_chunks(session, tenant_id=tenant_id, projection=projection, chunks=chunks)
    return tenant_id, call_id


async def _ask(tenant_id: uuid.UUID, question: str, *, role: str = "owner") -> str:
    return await run_read_tool(
        "search_calls",
        json.dumps({"question": question, "limit": None}),
        context=ToolContext(tenant_id=tenant_id, role=role),
    )


async def test_it_finds_the_exchange_and_marks_who_said_what() -> None:
    """The question the scope exists for, answered — with the speaker attached, which is
    what separates a caller ASKING from the agent MENTIONING."""
    tenant_id, _ = await _seed()
    answer = await _ask(tenant_id, "weekend appointments")
    assert f"Caller: {CALLER_WORDS}" in answer
    assert f"Agent: {AGENT_WORDS}" in answer


async def test_a_question_that_matches_nothing_says_so_in_a_sentence() -> None:
    """An empty tool result reads to a model as a failure, and the two empty answers here
    are different: nobody said it, or retention took the words."""
    tenant_id, _ = await _seed()
    answer = await _ask(tenant_id, "helicopter finance in Reykjavik")
    assert "retention" in answer and "guess" in answer


async def test_an_erased_call_is_not_findable_through_the_tool() -> None:
    """The erasure arm, seen from the surface a client actually uses."""
    tenant_id, call_id = await _seed()
    await _scrub_the_call_as_an_erasure_does(tenant_id, call_id)
    async with tenant_session(tenant_id) as session:
        await call_chunks.erase_projections_for_calls(session, call_ids=[call_id])

    answer = await _ask(tenant_id, "weekend appointments")
    assert CALLER_WORDS not in answer


async def test_it_reads_the_redacted_column_and_not_the_raw_one() -> None:
    """HARD RULE 5, proven rather than asserted in prose. The raw and redacted columns are
    made to DIFFER, and the tool must return the redacted one — a reader that had reached
    for `transcript_turns.text` would return the other string and pass every other test in
    this file."""
    tenant_id, call_id = await _seed()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE transcript_turns SET text = :raw WHERE call_id = :c AND speaker = 'caller'"
            ),
            {
                "raw": "Ring me back on nine eight seven six five four three two one zero",
                "c": call_id,
            },
        )
    answer = await _ask(tenant_id, "weekend appointments")
    assert "nine eight seven" not in answer
    assert CALLER_WORDS in answer


async def test_a_caller_without_the_permission_is_refused_by_name() -> None:
    """The access control is in code, not in the prompt — and it is the permission the
    transcript SCREEN declares, so this cannot be a way around that screen."""
    tenant_id, _ = await _seed()
    answer = await _ask(tenant_id, "weekend appointments", role="nobody")
    assert "Refused" in answer and "calls:read" in answer


async def test_no_account_open_is_a_different_refusal_from_no_permission() -> None:
    """An operator on the admin console has no tenant. The tool must say "open an account",
    never fall back to some default one."""
    answer = await run_read_tool(
        "search_calls",
        json.dumps({"question": "weekend appointments", "limit": None}),
        context=ToolContext(tenant_id=None, role="owner"),
    )
    assert "no account is open" in answer
