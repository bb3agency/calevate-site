"""What a text-only knowledge base that fetches pages is handed for a PDF and a link (D-868).

ThinnestAI's knowledge base takes pasted text or a web page address, and no file
(`EngineCapabilities.kb_text_only`, `kb_fetches_url`). So a PDF goes as the words we read out
of it, and one with no words is never attached (no blank document named after the client's
file) until a reading finds some; a link goes as its address; and a page the platform refuses
is recorded on the client's item without keeping the agent's other knowledge off it.

Driven through the real paths on the fake engine with the production adapter's
capabilities (`tests/thinnest_facts_in_knowledge_test._KbEngine`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.workers import kb_ingest
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

PAGE = b"<html><body><p>Free delivery above 500 rupees.</p></body></html>"


def _menu_texts(engine: _KbEngine) -> list[str]:
    return [body for title, body in engine.attached if title == "Menu"]


_MADE: list[tuple[uuid.UUID, uuid.UUID]] = []


@pytest.fixture(autouse=True)
async def _archive_what_was_made() -> AsyncIterator[None]:
    """Archive each upload after its test. Left live, it is a source the knowledge sweep in a
    later test would try to attach on the default engine, reading a file the per-test object
    store no longer holds."""
    yield
    while _MADE:
        tenant_id, source_id = _MADE.pop()
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE kb_sources SET is_active = false, status = 'archived' WHERE id = :s"),
                {"s": source_id},
            )


@pytest.fixture(autouse=True)
def _page_served(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _page(url: str) -> bytes:
        return PAGE

    monkeypatch.setattr(kb_ingest, "fetch_page", _page)


async def _client(engine: _KbEngine) -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _agent(SCRIPT)
    return tenant_id, agent_id, await _publish(tenant_id, agent_id, engine)


async def _added_pdf(
    engine: _KbEngine, tenant_id: uuid.UUID, data: bytes, *, name: str = "Menu"
) -> uuid.UUID:
    row = await _pdf_upload(tenant_id, data, name=name)
    source_id = uuid.UUID(str(row["source_id"]))
    _MADE.append((tenant_id, source_id))
    with _selected(engine):
        assert (await _ingest(tenant_id, source_id)).startswith("published")
    return source_id


async def _added_link(engine: _KbEngine, tenant_id: uuid.UUID, url: str) -> tuple[str, uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_link(
            session, tenant_id=tenant_id, name="Delivery", url=url, submitted_by=None,
            auto_approve=True,
        )  # fmt: skip
    source_id = uuid.UUID(str(row["source_id"]))
    _MADE.append((tenant_id, source_id))
    with _selected(engine):
        outcome = await _ingest(tenant_id, source_id)
    return outcome, source_id


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


async def _upload_of(tenant_id: uuid.UUID, source_id: uuid.UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT ingest_status, ingest_detail FROM kb_uploads WHERE source_id = :s"),
                {"s": source_id},
            )
        ).one()
    return str(row[0]), row[1]


async def test_a_read_pdf_reaches_the_agent_as_its_words(s3: FakeS3) -> None:
    engine = _KbEngine()
    assert engine.capabilities.kb_text_only and engine.capabilities.kb_fetches_url
    tenant_id, agent_id, ref = await _client(engine)
    source_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))

    texts = _menu_texts(engine)
    assert len(texts) == 1 and "Thali costs 180 rupees" in texts[0]
    assert (await _routes(tenant_id, source_id))[agent_id] in await engine.list_kb(ref)


async def test_a_pdf_with_no_words_is_withheld_until_a_reading_finds_some(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    source_id = await _added_pdf(engine, tenant_id, _pdf(None))

    assert _menu_texts(engine) == [], "a PDF with no words reached attach_kb"
    assert "Menu" not in _titled(engine, ref)
    assert await _routes(tenant_id, source_id) == {}
    settled = await _catch_up(engine, tenant_id, agent_id, ref)
    assert (settled.attached, settled.withdrawn) == (0, 0)

    # "Read it again" found words: the next catch-up attaches them.
    async with tenant_session(tenant_id) as session:
        await kb_service.store_read_copy(
            session, tenant_id=tenant_id, source_id=source_id, sections=[(1, PRICE_PAGE)]
        )
        await session.execute(
            text("UPDATE kb_uploads SET read_state = 'ready' WHERE source_id = :s"),
            {"s": source_id},
        )
    done = await _catch_up(engine, tenant_id, agent_id, ref)
    assert done.attached == 1
    assert "Thali costs 180 rupees" in _menu_texts(engine)[0]
    assert agent_id in await _routes(tenant_id, source_id)


async def test_a_link_is_sent_as_its_address_with_no_words_of_ours(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, agent_id, ref = await _client(engine)
    url = f"https://shop.example/{uuid.uuid4().hex}"
    outcome, source_id = await _added_link(engine, tenant_id, url)

    assert outcome.startswith("published")
    assert engine.linked == [url]
    assert [body for title, body in engine.attached if title == "Delivery"] == [""]
    assert (await _routes(tenant_id, source_id))[agent_id] in await engine.list_kb(ref)


async def test_a_refused_page_is_recorded_with_its_reason_and_not_published(s3: FakeS3) -> None:
    engine = _KbEngine()
    tenant_id, _agent_id, _ref = await _client(engine)
    url = f"https://shop.example/{uuid.uuid4().hex}"
    engine.unreadable_urls.add(url)
    outcome, source_id = await _added_link(engine, tenant_id, url)

    assert outcome == "failed:engine_kb_link_unreadable"
    status, detail = await _upload_of(tenant_id, source_id)
    assert status == "error"
    assert detail and "could not read that page" in detail and "without a login" in detail


async def test_a_page_refused_on_a_late_agent_keeps_no_other_source_off_it(s3: FakeS3) -> None:
    """The catch-up meets a live link the platform now refuses: the reason goes on the item,
    the PDF beside it is still attached, and the page is not posted again next sweep."""
    engine = _KbEngine()
    tenant_id, _first, _ref = await _client(engine)
    url = f"https://shop.example/{uuid.uuid4().hex}"
    outcome, link_id = await _added_link(engine, tenant_id, url)
    assert outcome.startswith("published")
    pdf_id = await _added_pdf(engine, tenant_id, _pdf(PRICE_PAGE))

    engine.unreadable_urls.add(url)
    (late,) = await _more_agents(tenant_id, 1)
    late_ref = await _publish(tenant_id, late, engine)
    await _catch_up(engine, tenant_id, late, late_ref)

    assert late in await _routes(tenant_id, pdf_id)
    assert late not in await _routes(tenant_id, link_id)
    assert (await _upload_of(tenant_id, link_id))[0] == "error"
    posted = engine.linked.count(url)
    settled = await _catch_up(engine, tenant_id, late, late_ref)
    assert settled.attached == 0
    assert engine.linked.count(url) == posted, "a refused page was posted again"
