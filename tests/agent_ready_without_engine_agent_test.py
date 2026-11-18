"""An agent is ready by its status, never by holding an engine agent of its own (D-1019).

Only its assignments, live inbound lines and going campaigns, need hold engine agents. So an
agent whose own `engine_agent_ref` is NULL, with a live line that answers in its voice, must
still have every change sent to that line, be protected and shown as ready, and have the
line's numbers detached when the account closes and re-attached when it reopens.

Driven through the real paths on the shared fake engine; the agent's own ref is cleared by
hand, which is the state the adoption job leaves.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import reply_length, roster
from apps.api.agents import service as agent_service
from apps.api.agents.lifecycle import release_account_numbers, restore_account_numbers
from apps.api.agents.live_apply import converge_agent
from apps.api.agents.models import is_published
from apps.api.agents.t0 import recompile_t0
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.healer.protection import live_answering_agents
from apps.api.inbound import lines
from apps.api.kb.service import active_knowledge
from sqlalchemy import text
from tests.caller_id_and_inbound_routing_test import _number
from tests.kb_inbound_line_holder_test import _published_line
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = [pytest.mark.rls]


def _fake() -> FakeEngine:
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return engine


async def _ref_less_agent_with_live_line() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    line_id, line_ref = await _published_line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    return tenant_id, agent_id, line_id, line_ref


def test_readiness_is_the_status_alone() -> None:
    assert is_published("live")
    assert is_published("paused")
    assert not is_published("draft")
    assert not is_published("archived")


async def test_a_setting_change_on_a_ref_less_agent_reaches_its_live_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _line_id, line_ref = await _ref_less_agent_with_live_line()
    queued: list[dict[str, Any]] = []

    async def _queue(session: object, **kwargs: Any) -> uuid.UUID:
        queued.append(kwargs)
        return uuid.uuid4()

    monkeypatch.setattr(reply_length, "queue_live_apply", _queue)
    async with tenant_session(tenant_id) as session:
        _state, moved = await reply_length.set_reply_length(
            session, tenant_id=tenant_id, agent_id=agent_id, tokens=180
        )
    assert moved
    assert [q["agent_id"] for q in queued] == [agent_id], "a ready agent's change was not queued"

    outcome, _name = await converge_agent(tenant_id=tenant_id, agent_id=agent_id)

    assert outcome == "applied", "the live apply passed over an agent without a ref of its own"
    assert _fake()._agents[line_ref].max_reply_tokens == 180, "the line kept the old ceiling"


async def test_a_t0_recompile_of_a_ref_less_agent_republishes_its_live_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _line_id, _line_ref = await _ref_less_agent_with_live_line()
    fanned: list[uuid.UUID] = []
    original = agent_service.republish_lines

    async def _record(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int:
        fanned.append(agent_id)
        return await original(session, tenant_id=tenant_id, agent_id=agent_id)

    monkeypatch.setattr(agent_service, "republish_lines", _record)
    async with tenant_session(tenant_id) as session:
        knowledge = await active_knowledge(session, tenant_id=tenant_id)
        await session.execute(
            text(
                "UPDATE prompt_versions SET body = body || :extra WHERE id = "
                "(SELECT system_prompt_id FROM agents WHERE id = :a)"
            ),
            {"extra": "\n[T0 FACTS]\nstale\n[/T0 FACTS]\n", "a": agent_id},
        )
        version = await recompile_t0(
            session, tenant_id=tenant_id, agent_id=agent_id, knowledge=knowledge
        )

    assert version is not None
    assert fanned == [agent_id], "the recompile did not reach the agent's live line"


async def test_a_ref_less_agent_reads_as_published_and_is_protected() -> None:
    tenant_id, agent_id, _line_id, _line_ref = await _ref_less_agent_with_live_line()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"), {"a": agent_id}
        )
        row = await roster.agent_by_id(session, agent_id)
        answering = await live_answering_agents(session)

    assert row is not None and row.published, "a ready agent without a ref reads as a draft"
    assert agent_id in answering, "its live line is left out of a platform-wide hold"


async def test_closing_detaches_a_ref_less_agents_line_numbers_and_reopening_reattaches() -> None:
    tenant_id, agent_id, line_id, line_ref = await _ref_less_agent_with_live_line()
    handle = f"num_line_{uuid.uuid4().hex[:8]}"
    number_id, _e164 = await _number(tenant_id, agent_id=agent_id, engine_number_ref=handle)
    async with tenant_session(tenant_id) as session:
        await lines.assign_number(session, line_id, number_id)
        await agent_service.route_line_numbers(session, line_id=line_id)
    engine = _fake()
    assert engine.inbound_agent_for(handle) == line_ref

    async with tenant_session(tenant_id) as session:
        released = await release_account_numbers(session)
    assert released.moved == 1
    assert engine.inbound_agent_for(handle) is None, "a closed account's line still answers"

    async with tenant_session(tenant_id) as session:
        restored = await restore_account_numbers(session)
    assert restored.moved == 1
    assert engine.inbound_agent_for(handle) == line_ref, "the reopen left the line dark"
