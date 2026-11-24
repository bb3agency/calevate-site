"""The operator's per-agent knowledge list reads every engine agent carrying the agent's work
(D-868 under D-1019): an agent with no engine agent of its own still shows what its Inbound
line holds, and a document on the line we did not send can be removed there."""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import agent_view
from calevate_shared.engine import KBSourceRef
from sqlalchemy import text
from tests.kb_inbound_line_holder_test import (
    FEES,
    _fake,
    _publish,
    _published_line,
)
from tests.kb_workflow_test import _tenant_with_published_agent


async def _without_own_engine_agent(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """The agent as D-1019 leaves it: no engine agent of its own and no claims of its own."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "DELETE FROM engine_kb_routes WHERE agent_id = :a AND variant_id IS NULL "
                "AND NOT test_copy AND inbound_line_id IS NULL AND campaign_id IS NULL"
            ),
            {"a": agent_id},
        )
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )


async def _view(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> agent_view.AgentKnowledge:
    async with tenant_session(tenant_id) as session:
        return await agent_view.agent_knowledge(
            session, _fake(), tenant_id=tenant_id, agent_id=agent_id
        )


async def test_an_agent_with_no_engine_agent_shows_what_its_line_holds() -> None:
    """FAILS IF: the list reads only the agent's own engine agent, and so calls a source its
    line already holds "not on this agent", waiting for a sweep that never comes."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)
    line_id, line_ref = await _published_line(tenant_id, agent_id)
    await _without_own_engine_agent(tenant_id, agent_id)
    stray = await _fake().attach_kb(
        line_ref, KBSourceRef(kb_id="console", title="Hand-made", text="x")
    )

    view = await _view(tenant_id, agent_id)
    assert view.listed
    on_line = [i for i in view.items if i.holder is not None and i.holder.id == line_id]
    assert {i.verdict for i in on_line if i.source_id == source_id} == {"held"}
    assert all(i.holder is not None and i.holder.kind == "line" for i in on_line)
    assert [i.handle for i in on_line if i.verdict == "not_ours"] == [stray]
    assert not [i for i in view.items if i.verdict == "not_sent" and i.source_id == source_id]

    async with tenant_session(tenant_id) as session:
        await agent_view.remove_unrecorded(
            session, _fake(), tenant_id=tenant_id, agent_id=agent_id, handle=stray
        )
    assert stray not in await _fake().list_kb(line_ref)


async def test_a_line_copy_we_sent_is_refused_removal() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)
    line_id, line_ref = await _published_line(tenant_id, agent_id)
    await _without_own_engine_agent(tenant_id, agent_id)
    view = await _view(tenant_id, agent_id)
    ours = next(i.handle for i in view.items if i.source_id == source_id and i.holder)
    assert ours is not None
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agent_view.remove_unrecorded(
                session, _fake(), tenant_id=tenant_id, agent_id=agent_id, handle=ours
            )
    assert refused.value.code == "kb_document_is_ours"
    assert ours in await _fake().list_kb(line_ref)
    assert line_id is not None
