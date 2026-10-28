"""A PDF or link with no text is never attached to a text-only knowledge base.

The engine's knowledge base takes text only (`EngineCapabilities.kb_text_only`), and while
`kb_send_extracted_files` is off a PDF's words are withheld, so the source has no text to
send. Each path that attaches knowledge — the publish fan-out and the per-agent catch-up —
skips it rather than posting a blank document named after the client's file, withdraws a
copy an agent already holds, and attaches the words once the switch is on again.

Driven through the real paths on the fake engine with the production adapter's
capabilities (`tests/thinnest_facts_in_knowledge_test._KbEngine`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_read_copy_test import PRICE_PAGE, _ingest, _pdf, _pdf_upload
from tests.kb_tenant_sharing_test import _more_agents, _routes, _titled
from tests.thinnest_facts_in_knowledge_test import (
    SCRIPT,
    _agent,
    _KbEngine,
    _priced_and_no_webhook,  # noqa: F401 - the autouse fixture the publish path needs
    _publish,
    _selected,
)


def _switch(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    monkeypatch.setattr(get_settings(), "kb_send_extracted_files", on)


def _menu_texts(engine: _KbEngine) -> list[str]:
    return [body for title, body in engine.attached if title == "Menu"]


_MADE: list[tuple[uuid.UUID, uuid.UUID]] = []


@pytest.fixture(autouse=True)
async def _archive_the_pdfs() -> AsyncIterator[None]:
    """Archive each PDF after its test. Left live and unattached, it is a source the
    knowledge sweep in a later test would try to attach on the default engine, reading a
    file the per-test object store no longer holds."""
    yield
    while _MADE:
        tenant_id, source_id = _MADE.pop()
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE kb_sources SET is_active = false, status = 'archived' WHERE id = :s"),
                {"s": source_id},
            )


async def _client_with_a_pdf(
    engine: _KbEngine,
) -> tuple[uuid.UUID, uuid.UUID, str, uuid.UUID]:
    """A client with one published agent and a PDF ingested (and auto-published)."""
    tenant_id, agent_id = await _agent(SCRIPT)
    ref = await _publish(tenant_id, agent_id, engine)
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    source_id = uuid.UUID(str(row["source_id"]))
    _MADE.append((tenant_id, source_id))
    with _selected(engine):
        outcome = await _ingest(tenant_id, source_id)
    assert outcome.startswith("published")
    return tenant_id, agent_id, ref, source_id


async def _publish_source(engine: _KbEngine, tenant_id: uuid.UUID, source_id: uuid.UUID) -> None:
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)


async def _catch_up(
    engine: _KbEngine, tenant_id: uuid.UUID, agent_id: uuid.UUID, ref: str
) -> kb_service.CatchUp:
    """The catch-up itself. `catch_up_agent` would first recompile T0, and the republish
    that triggers runs this same catch-up, leaving the outer call nothing to count."""
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            await kb_service.lock_tenant_knowledge(session, tenant_id=tenant_id)
            return await kb_service.converge_agent_knowledge(
                session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
            )


async def test_switch_off_the_publish_attaches_no_blank_document(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, False)
    engine = _KbEngine()
    assert engine.capabilities.kb_text_only
    tenant_id, _agent_id, ref, source_id = await _client_with_a_pdf(engine)

    assert _menu_texts(engine) == [], "a PDF with no text reached attach_kb"
    assert "Menu" not in _titled(engine, ref)
    assert await _routes(tenant_id, source_id) == {}
    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text("SELECT is_active FROM kb_sources WHERE id = :s"),
                {"s": source_id},
            )
        ).scalar()
    assert live is True, "a skipped source is not a failed publish: it still goes live"


async def test_switch_on_the_publish_sends_the_words_and_off_again_takes_them_back(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, False)
    engine = _KbEngine()
    tenant_id, agent_id, ref, source_id = await _client_with_a_pdf(engine)

    # The redelivery job is `publish_source` on each live PDF.
    _switch(monkeypatch, True)
    await _publish_source(engine, tenant_id, source_id)
    texts = _menu_texts(engine)
    assert len(texts) == 1 and "Thali costs 180 rupees" in texts[0]
    handle = (await _routes(tenant_id, source_id))[agent_id]
    assert handle in await engine.list_kb(ref)

    _switch(monkeypatch, False)
    await _publish_source(engine, tenant_id, source_id)
    assert len(_menu_texts(engine)) == 1, "nothing new was attached"
    assert handle in engine.detached
    assert "Menu" not in _titled(engine, ref)
    assert await _routes(tenant_id, source_id) == {}


async def test_the_catch_up_skips_it_while_off_and_attaches_it_once_on(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, False)
    engine = _KbEngine()
    tenant_id, _first, _ref, source_id = await _client_with_a_pdf(engine)

    # An agent published after the PDF: its publish runs the catch-up.
    (late,) = await _more_agents(tenant_id, 1)
    late_ref = await _publish(tenant_id, late, engine)
    assert _menu_texts(engine) == []
    done = await _catch_up(engine, tenant_id, late, late_ref)
    assert (done.attached, done.withdrawn) == (0, 0)
    assert "Menu" not in _titled(engine, late_ref)

    _switch(monkeypatch, True)
    done = await _catch_up(engine, tenant_id, late, late_ref)
    assert done.attached == 1
    assert "Menu" in _titled(engine, late_ref)
    assert late in await _routes(tenant_id, source_id)

    # Off again: the catch-up withdraws the copy as it would an archived one.
    _switch(monkeypatch, False)
    done = await _catch_up(engine, tenant_id, late, late_ref)
    assert (done.attached, done.withdrawn) == (0, 1)
    assert "Menu" not in _titled(engine, late_ref)
    assert late not in await _routes(tenant_id, source_id)
    settled = await _catch_up(engine, tenant_id, late, late_ref)
    assert (settled.attached, settled.withdrawn) == (0, 0)


async def test_an_engine_that_keeps_the_file_still_gets_it_with_the_switch_off(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The skip is the text-only engine's, not the switch's: an engine that ingests the
    document is handed the PDF as before."""
    _switch(monkeypatch, False)
    engine = _KbEngine()
    monkeypatch.setattr(
        engine, "capabilities", engine.capabilities.model_copy(update={"kb_text_only": False})
    )
    _tenant_id, _agent_id, ref, _source_id = await _client_with_a_pdf(engine)
    assert _menu_texts(engine) == [""]
    assert "Menu" in _titled(engine, ref)
