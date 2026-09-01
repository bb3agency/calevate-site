"""The publisher actually hands the engine a rendered document — the seam, end to end.

**WHY THIS FILE EXISTS.** `publish_source` renders the approved chunks to a PDF and puts
the bytes on `KBSourceRef.document`; an adapter whose knowledge base ingests files (the
real one) refuses with `engine_kb_document_missing` when handed `None`. That seam shipped
BROKEN and every test in this repository passed: the publisher resolved the renderer by
name through `importlib`, the name it looked for was `apps.api.kb.render.
render_knowledge_pdf(*, title, chunks: list[str], language) -> bytes`, and what actually
shipped was `apps.api.kb.pdf_render.render_knowledge_pdf(chunks: Sequence[ApprovedChunk])
-> RenderedKnowledgePdf`. `import_module` raised `ImportError`, the seam logged
`kb_renderer_unavailable` and returned `None`, and publishing knowledge to the engine was
dead on arrival — invisible, because the FAKE adapter accepts `document=None` and every KB
test runs on the fake.

So the assertions here are deliberately about the BYTES and not about the call graph. A
test that mocked the renderer would have passed against the broken seam too.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import service
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.anyio


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, name: str, body: str) -> uuid.UUID:
    """Submit, approve and publish one source, returning its id."""
    async with tenant_session(tenant_id) as session:
        result = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=result["id"], approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=result["id"])
    return uuid.UUID(str(result["id"]))


def _attached(agent_ref: str):  # type: ignore[no-untyped-def]
    engine = get_engine()
    attached = engine._kb.get(agent_ref, [])
    assert attached, "premise: the publish attached something"
    return attached[-1]


async def test_a_publish_hands_the_engine_a_real_pdf_and_not_none() -> None:
    """THE REGRESSION. `document` is bytes that begin with the PDF magic number.

    `%PDF-` rather than "is not None", because the seam's failure mode was not a crash —
    it was a plausible-looking `None` that only the real adapter would ever object to.
    Asserting the magic number means a renderer that starts returning text, or an empty
    document, fails here rather than at a vendor that indexes it and retrieves nothing.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                service.text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    await _publish(tenant_id, agent_id, name="Hours", body="We are open 9am to 8pm.")

    source = _attached(str(agent_ref))
    assert source.document is not None, "the publisher rendered nothing — the seam is broken"
    assert source.document.startswith(b"%PDF-")
    assert len(source.document) > 0


async def test_the_digest_on_the_wire_is_the_digest_of_the_bytes_on_the_wire() -> None:
    """`content_sha256` is the re-upload guard's whole basis.

    A digest computed over anything but the exact bytes handed to the vendor would make
    the guard skip an upload the vendor never received, or repeat one it did — so it is
    asserted against `hashlib` here rather than trusted from the renderer's return value.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                service.text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    await _publish(tenant_id, agent_id, name="Fees", body="A consultation is 500 rupees.")

    source = _attached(str(agent_ref))
    assert source.document is not None
    assert source.content_sha256 == hashlib.sha256(source.document).hexdigest()


async def test_the_same_approved_text_renders_to_the_same_bytes_twice() -> None:
    """Determinism, asserted through the publisher rather than on the renderer alone.

    `pdf_render` has its own determinism test. This one is different and is the one that
    protects the guard: it proves the PUBLISHER feeds the renderer the same input for the
    same approved content — same order, same markers, nothing derived from a clock, a row
    id or the source's own uuid leaking into the bytes. A renderer that is pure and a
    caller that is not still uploads a duplicate on every republish.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                service.text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    body = "We are open 9am to 8pm.\n\nSunday is closed."
    source_id = await _publish(tenant_id, agent_id, name="Timings", body=body)
    first = _attached(str(agent_ref))
    assert first.document is not None
    first_bytes = first.document

    # Republish the SAME source. The re-upload guard should recognise it, which it can
    # only do if the digest it recomputes matches the one it stored.
    async with tenant_session(tenant_id) as session:
        await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    second = _attached(str(agent_ref))
    assert second.document == first_bytes
    assert second.content_sha256 == first.content_sha256


async def test_text_the_knowledge_font_cannot_draw_is_refused_by_name() -> None:
    """A script the embedded font does not cover is a REFUSAL, not a silent drop.

    fpdf2 does not raise on a missing glyph: it warns on stderr and omits the character,
    so a Hindi paragraph pasted into a Telugu knowledge base uploads as a PDF whose text
    layer is missing it entirely — accepted, indexed, and retrieving nothing. The renderer
    refuses; this asserts the publisher turns that into a client-actionable problem
    instead of a 500, and that nothing was attached.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                service.text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    async with tenant_session(tenant_id) as session:
        result = await service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            # Devanagari: a real thing a client pastes, and outside the Telugu+Latin font.
            name="Nirdesh",
            body="हम सुबह नौ बजे से रात आठ बजे तक खुले हैं।",
        )
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=result["id"], approved_by=None)
        with pytest.raises(ProblemError) as exc:
            await service.publish_source(session, tenant_id=tenant_id, source_id=result["id"])
    assert exc.value.code == "kb_render_refused"

    engine = get_engine()
    assert not engine._kb.get(str(agent_ref)), "a refused render must attach nothing"
