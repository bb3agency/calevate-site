"""The operator's per-agent knowledge list (D-868, `kb/agent_view.py`), on the fake engine
with the production adapter's capabilities: every copy is accounted for per engine agent
carrying the agent (D-1019), a document we did not send is the only one an operator may
remove, and another client's agent is invisible."""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.kb import agent_view
from calevate_shared.engine import KBSourceRef
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_inbound_line_holder_test import FEES, _publish, _published_line
from tests.kb_read_copy_test import PRICE_PAGE, _pdf
from tests.kb_text_only_engine_test import (
    _added_pdf,
    _archive_what_was_made,  # noqa: F401 - archives each upload after its test
    _client,
    _page_served,  # noqa: F401 - serves the page a link reads
)
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.thinnest_facts_in_knowledge_test import (
    _KbEngine,
    _priced_and_no_webhook,  # noqa: F401 - the autouse fixture the publish path needs
    _selected,
)


async def _view(
    engine: FakeEngine, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> agent_view.AgentKnowledge:
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            return await agent_view.agent_knowledge(
                session, engine, tenant_id=tenant_id, agent_id=agent_id
            )


def _own(view: agent_view.AgentKnowledge) -> agent_view.HolderKnowledge:
    return next(holder for holder in view.holders if holder.kind == "agent")


async def test_every_copy_is_accounted_for(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    pdf_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))
    blank_id = await _added_pdf(engine, tenant_id, _pdf(None), name="Blank")
    stray = await engine.attach_kb(ref, KBSourceRef(kb_id="console", title="Hand-made", text="x"))

    own = _own(await _view(engine, tenant_id, agent_id))
    by_source = {item.source_id: item for item in own.items if item.source_id}
    assert own.listed and own.engine_agent_ref == ref
    assert by_source[pdf_id].verdict == "held" and by_source[pdf_id].kind == "pdf"
    assert by_source[blank_id].verdict == "not_sent"
    assert by_source[blank_id].detail
    assert [i.handle for i in own.items if i.verdict == "not_ours"] == [stray]

    # A copy the platform lost reads as missing.
    held = by_source[pdf_id].handle
    assert held is not None
    await engine.detach_kb(ref, held)
    again = _own(await _view(engine, tenant_id, agent_id))
    assert {i.source_id: i.verdict for i in again.items}[pdf_id] == "missing"


async def test_only_a_document_we_did_not_send_may_be_removed(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    pdf_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))
    stray = await engine.attach_kb(ref, KBSourceRef(kb_id="console", title="Hand-made", text="x"))
    own = _own(await _view(engine, tenant_id, agent_id))
    ours_handle = next(i.handle for i in own.items if i.source_id == pdf_id)
    assert ours_handle is not None

    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as refused:
                await agent_view.remove_unrecorded(
                    session,
                    engine,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    holder_ref=ref,
                    handle=ours_handle,
                )
            assert refused.value.code == "kb_document_is_ours"
        async with tenant_session(tenant_id) as session:
            await agent_view.remove_unrecorded(
                session,
                engine,
                tenant_id=tenant_id,
                agent_id=agent_id,
                holder_ref=ref,
                handle=stray,
            )
    assert stray not in await engine.list_kb(ref)
    assert ours_handle in await engine.list_kb(ref)


async def test_another_clients_agent_is_not_found(s3: FakeS3) -> None:
    engine = _KbEngine()
    _tenant_a, agent_a, _ref = await _client(engine)
    tenant_b, _agent_b, _ = await _client(engine)
    with _selected(engine):
        async with tenant_session(tenant_b) as session:
            with pytest.raises(ProblemError) as hidden:
                await agent_view.agent_knowledge(
                    session, engine, tenant_id=tenant_b, agent_id=agent_a
                )
    assert hidden.value.status == 404


async def test_an_agent_with_no_engine_agent_shows_what_its_line_holds() -> None:
    """D-1019: the agent holds no engine agent and its published line holds the client's
    knowledge. Read off the agent's own ref, every live item read "not on this agent"."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    source_id = await _publish(tenant_id, "Fees", FEES)
    _line_id, line_ref = await _published_line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    stray = await engine.attach_kb(
        line_ref, KBSourceRef(kb_id="console", title="Hand-made", text="x")
    )

    async with tenant_session(tenant_id) as session:
        view = await agent_view.agent_knowledge(
            session, engine, tenant_id=tenant_id, agent_id=agent_id
        )
    assert [holder.kind for holder in view.holders if holder.kind == "agent"] == []
    line = next(holder for holder in view.holders if holder.kind == "line")
    assert line.name == "Appointments" and line.engine_agent_ref == line_ref
    assert {i.source_id: i.verdict for i in line.items if i.source_id}[source_id] == "held"

    # A document on the line's engine agent that we did not send is removed from that one;
    # a ref that is not one of this agent's engine agents is not found.
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as foreign:
            await agent_view.remove_unrecorded(
                session,
                engine,
                tenant_id=tenant_id,
                agent_id=agent_id,
                holder_ref="fakeagent_not_this_agents",
                handle=stray,
            )
    assert foreign.value.status == 404
    async with tenant_session(tenant_id) as session:
        await agent_view.remove_unrecorded(
            session,
            engine,
            tenant_id=tenant_id,
            agent_id=agent_id,
            holder_ref=line_ref,
            handle=stray,
        )
    assert stray not in await engine.list_kb(line_ref)
