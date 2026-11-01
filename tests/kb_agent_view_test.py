"""The operator's per-agent knowledge list (D-868, `kb/agent_view.py`), on the fake engine
with the production adapter's capabilities: every copy is accounted for, a document we did
not send is the only one an operator may remove, and another client's agent is invisible."""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import agent_view
from calevate_shared.engine import KBSourceRef
from tests.conftest import FakeS3
from tests.kb_read_copy_test import PRICE_PAGE, _pdf
from tests.kb_text_only_engine_test import (
    _added_pdf,
    _archive_what_was_made,  # noqa: F401 - archives each upload after its test
    _client,
    _page_served,  # noqa: F401 - serves the page a link reads
)
from tests.thinnest_facts_in_knowledge_test import (
    _KbEngine,
    _priced_and_no_webhook,  # noqa: F401 - the autouse fixture the publish path needs
    _selected,
)


async def _view(
    engine: _KbEngine, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> agent_view.AgentKnowledge:
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            return await agent_view.agent_knowledge(
                session, engine, tenant_id=tenant_id, agent_id=agent_id
            )


async def test_every_copy_is_accounted_for(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    pdf_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))
    blank_id = await _added_pdf(engine, tenant_id, _pdf(None), name="Blank")
    stray = await engine.attach_kb(ref, KBSourceRef(kb_id="console", title="Hand-made", text="x"))

    view = await _view(engine, tenant_id, agent_id)
    by_source = {item.source_id: item for item in view.items if item.source_id}
    assert view.listed
    assert by_source[pdf_id].verdict == "held" and by_source[pdf_id].kind == "pdf"
    assert by_source[blank_id].verdict == "not_sent"
    assert by_source[blank_id].detail
    assert [i.handle for i in view.items if i.verdict == "not_ours"] == [stray]

    # A copy the platform lost reads as missing.
    held = by_source[pdf_id].handle
    assert held is not None
    await engine.detach_kb(ref, held)
    again = await _view(engine, tenant_id, agent_id)
    assert {i.source_id: i.verdict for i in again.items}[pdf_id] == "missing"


async def test_only_a_document_we_did_not_send_may_be_removed(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    pdf_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))
    stray = await engine.attach_kb(ref, KBSourceRef(kb_id="console", title="Hand-made", text="x"))
    view = await _view(engine, tenant_id, agent_id)
    ours_handle = next(i.handle for i in view.items if i.source_id == pdf_id)
    assert ours_handle is not None

    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as refused:
                await agent_view.remove_unrecorded(
                    session, engine, tenant_id=tenant_id, agent_id=agent_id, handle=ours_handle
                )
            assert refused.value.code == "kb_document_is_ours"
        async with tenant_session(tenant_id) as session:
            await agent_view.remove_unrecorded(
                session, engine, tenant_id=tenant_id, agent_id=agent_id, handle=stray
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
