"""A client's PDFs and links held in full readable text, and Pip's access to it (D-893 L8).

What must hold, each driven through the real path:

1. A PDF's words are read page by page into `kb_documents` (pypdf), a scanned page is read
   by the OCR leg and METERED, and the row says how it went (`read_state`, `page_count`).
   A link's one page is read into its visible text.
2. With `kb_send_extracted_files` OFF the agents receive exactly what they did before: no
   text in the engine document, nothing in the T0 block, the same publish digest. ON, the
   words go out and the digest moves so the re-upload guard re-sends.
3. Pip can find every item, open one a page at a time, and search the words of everything,
   each hit saying whether the agents use it; "what my agents tell callers" never quotes a
   PDF the agents do not get.
4. Pip's edits go through the page's own functions: rename (with Undo), a note, a
   correction, remove and restore.
5. The routes: the reader's text, Rename and "Read it again", within role.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest
from apps.api.copilot.actions import ToolActor, UndoRecord, WriteRefusedError
from apps.api.copilot.knowledge_actions import (
    KNOWLEDGE_NOTE_SAVE,
    KNOWLEDGE_REMOVE,
    KNOWLEDGE_RENAME,
)
from apps.api.copilot.tools import ToolContext, run_read_tool
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb import store, uploads
from apps.api.kb.reading import READ_KB_UPLOAD_JOB, queue_read
from apps.workers import document_ocr, kb_ingest, kb_read
from calevate_shared.document_ingest import ExtractedText
from fpdf import FPDF
from PIL import Image
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_staff_curation_test import _client, _h, _member
from tests.kb_workflow_test import _tenant_with_published_agent

# --- fixtures ------------------------------------------------------------------------


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (240, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf(*pages: str | bytes | None) -> bytes:
    """A real PDF: a text page per string, a scanned page per image, a blank page per None."""
    pdf = FPDF()
    for page in pages:
        pdf.add_page()
        if isinstance(page, str):
            pdf.set_font("helvetica", size=12)
            pdf.multi_cell(0, 8, page)
        elif isinstance(page, bytes):
            pdf.image(io.BytesIO(page), x=10, y=10, w=120)
    return bytes(pdf.output())


PRICE_PAGE = "Thali costs 180 rupees. Biryani costs 240 rupees on weekdays."
HOURS_PAGE = "We are open from 11 in the morning to 10 at night, all seven days."


async def _pdf_upload(tenant_id: uuid.UUID, data: bytes, *, name: str = "Menu") -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=name,
            filename="menu.pdf",
            content_type="application/pdf",
            data=data,
            submitted_by=None,
            auto_approve=True,
        )


async def _ingest(tenant_id: uuid.UUID, source_id: object) -> str:
    return await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "source_id": str(source_id), "may_self_approve": True},
    )


async def _upload_row(tenant_id: uuid.UUID, upload_id: object) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.get_upload(session, uuid.UUID(str(upload_id)))


def _no_ocr(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stand in for the paid OCR leg, and record every meter call it causes."""
    metered: list[dict[str, Any]] = []

    async def _read(images: Any, **_: Any) -> ExtractedText:
        return ExtractedText(
            text="Scanned page: dosa costs 80 rupees.",
            kind="image",
            provenance="ocr",
            unit_count=1,
            unit_name="images",
            needs_confirmation=True,
            model="gemini-test",
            prompt_tokens=1290,
            output_tokens=20,
        )

    async def _meter(session: Any, **kwargs: Any) -> None:
        metered.append(kwargs)

    monkeypatch.setattr(document_ocr, "ocr_images", _read)
    monkeypatch.setattr(kb_ingest, "_meter_ocr", _meter)
    return metered


# --- 1. reading ----------------------------------------------------------------------


def test_pypdf_reads_the_text_pages_and_hands_the_scans_to_the_reader() -> None:
    reading = kb_read.read_pdf(_pdf(PRICE_PAGE, None, _png()))
    assert reading.page_count == 3
    assert [number for number, _ in reading.pages] == [1]
    assert "Thali costs 180 rupees" in reading.pages[0][1]
    assert reading.blank == 1
    assert [number for number, _data, _mime in reading.scans] == [3]


def test_a_damaged_pdf_is_refused_with_a_sentence_the_owner_can_act_on() -> None:
    with pytest.raises(kb_read.UnreadablePdfError) as refused:
        kb_read.read_pdf(b"%PDF-1.4 this is not a pdf at all")
    assert "save it again" in refused.value.detail


def test_a_page_keeps_its_visible_words_and_drops_scripts_and_styles() -> None:
    html = (
        b"<html><head><title>x</title><style>p{color:red}</style></head><body>"
        b"<script>steal()</script><h1>Prices</h1><p>Thali &amp; curd: 180</p>"
        b"<div>Open daily</div></body></html>"
    )
    assert kb_read.page_text(html) == "Prices\n\nThali & curd: 180\n\nOpen daily"


async def test_an_uploaded_pdf_is_read_page_by_page_and_the_scan_is_metered(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    metered = _no_ocr(monkeypatch)
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE, HOURS_PAGE, _png()))
    await _ingest(tenant_id, row["source_id"])

    after = await _upload_row(tenant_id, row["id"])
    assert after["read_state"] == "ready"
    assert after["page_count"] == 3
    assert after["is_live"] is True
    async with tenant_session(tenant_id) as session:
        pages = (
            await session.execute(
                text(
                    "SELECT (meta->>'page')::int FROM kb_documents WHERE source_id = :s "
                    "ORDER BY idx"
                ),
                {"s": row["source_id"]},
            )
        ).scalars()
        assert list(pages) == [1, 2, 3]
    assert len(metered) == 1 and metered[0]["model"] == "gemini-test"


async def test_a_pdf_that_cannot_be_read_still_goes_to_the_platform_as_its_file(
    s3: FakeS3,
) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    outcome = await _ingest(tenant_id, row["source_id"])
    after = await _upload_row(tenant_id, row["id"])
    assert outcome.startswith("published")
    assert after["read_state"] == "failed"
    assert after["read_detail"]
    assert after["reaches_agents"] is False


async def test_a_link_is_read_into_its_visible_text_and_sets_the_change_baseline(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _page(url: str) -> bytes:
        return b"<html><body><h1>Delivery</h1><p>Free above 500 rupees.</p></body></html>"

    monkeypatch.setattr(kb_ingest, "fetch_page", _page)
    tenant_id, _agent = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            name="Delivery page",
            url="https://shop.example/delivery",
            submitted_by=None,
            auto_approve=True,
        )
    await _ingest(tenant_id, row["source_id"])
    async with tenant_session(tenant_id) as session:
        found = await store.read_item(session, tenant_id=tenant_id, ref=f"link:{row['id']}")
        digest = (
            await session.execute(
                text("SELECT content_digest FROM kb_uploads WHERE id = :u"), {"u": row["id"]}
            )
        ).scalar()
    assert found.sections == [("", "Delivery\n\nFree above 500 rupees.")]
    assert digest == kb_ingest.page_digest(
        b"<html><body><h1>Delivery</h1><p>Free above 500 rupees.</p></body></html>"
    )


# --- 2. what the agents receive --------------------------------------------------------


async def test_off_the_agents_receive_exactly_what_they_did_before(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "kb_send_extracted_files", False)
    tenant_id, _agent = await _tenant_with_published_agent()
    data = _pdf(PRICE_PAGE)
    row = await _pdf_upload(tenant_id, data)
    await _ingest(tenant_id, row["source_id"])
    source_id = uuid.UUID(str(row["source_id"]))

    async with tenant_session(tenant_id) as session:
        assert await kb_service._chunks_of(session, source_id) == []
        names = [k.name for k in await kb_service.active_knowledge(session, tenant_id=tenant_id)]
        _document, _url, digest = await kb_service._publish_payload(session, source_id, name="Menu")
    assert "Menu" not in names
    # The publish identity of the file alone, as before its words were read.
    import hashlib

    assert digest == hashlib.sha256(data).hexdigest()
    assert (await _upload_row(tenant_id, row["id"]))["reaches_agents"] is False


async def test_on_the_words_go_out_and_the_digest_moves_so_the_copy_is_sent_again(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    data = _pdf(PRICE_PAGE)
    row = await _pdf_upload(tenant_id, data)
    await _ingest(tenant_id, row["source_id"])
    source_id = uuid.UUID(str(row["source_id"]))
    async with tenant_session(tenant_id) as session:
        _d, _u, off_digest = await kb_service._publish_payload(session, source_id, name="Menu")

    monkeypatch.setattr(get_settings(), "kb_send_extracted_files", True)
    async with tenant_session(tenant_id) as session:
        chunks = await kb_service._chunks_of(session, source_id)
        knowledge = await kb_service.active_knowledge(session, tenant_id=tenant_id)
        _d, _u, on_digest = await kb_service._publish_payload(session, source_id, name="Menu")
    assert any("Thali costs 180 rupees" in chunk for chunk in chunks)
    assert any(k.name == "Menu" for k in knowledge)
    assert on_digest != off_digest
    assert (await _upload_row(tenant_id, row["id"]))["reaches_agents"] is True


async def test_saving_the_switch_queues_the_redelivery_of_every_live_pdf_and_link() -> None:
    from apps.api.db.session import untenanted_session
    from apps.api.ops.config_service import _apply_to_live_agents

    async with untenanted_session() as session:
        assert await _apply_to_live_agents(session, "kb_send_extracted_files", uuid.uuid4()) is None
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = 'redeliver_extracted_knowledge' AND status = 'pending'"
                )
            )
        ).scalar()
        await session.rollback()
    assert queued and queued >= 1


async def test_redelivery_republishes_each_live_pdf(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    await _ingest(tenant_id, row["source_id"])
    published: list[uuid.UUID] = []

    async def _publish(session: Any, *, tenant_id: uuid.UUID, source_id: uuid.UUID) -> int:
        published.append(source_id)
        return 1

    monkeypatch.setattr(kb_service, "publish_source", _publish)
    await kb_read.redeliver_extracted_knowledge({}, {})
    assert uuid.UUID(str(row["source_id"])) in published


# --- 3. Pip reads --------------------------------------------------------------------


async def _tool(name: str, arguments: str, *, context: ToolContext) -> str:
    """A read tool through its real entry point and the client realm's own registry."""
    from apps.api.copilot import service as copilot_service

    return await run_read_tool(
        name,
        arguments,
        context=context,
        registry=copilot_service._read_tool_registry("client"),
    )


def _ctx(tenant_id: uuid.UUID, role: str = "owner") -> ToolContext:
    return ToolContext(tenant_id=tenant_id, role=role)


async def test_pip_finds_opens_and_searches_a_pdf_and_says_the_agents_do_not_use_it(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "kb_send_extracted_files", False)
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE, HOURS_PAGE))
    await _ingest(tenant_id, row["source_id"])
    ref = f"file:{row['id']}"

    found = await _tool(
        "knowledge_sources",
        json.dumps(
            {"kind": "file", "state": "not_used_yet", "find": "menu", "detail": "full",
             "page": None}
        ),
        context=_ctx(tenant_id),
    )  # fmt: skip
    assert f"[{ref}]" in found and "agents don't use it yet" in found and "2 pages" in found

    opened = await _tool(
        "knowledge_sources",
        json.dumps({"kind": None, "state": None, "find": ref, "detail": None, "page": 2}),
        context=_ctx(tenant_id),
    )
    assert "page 2 of 2" in opened and "seven days" in opened and "Thali" not in opened

    everything = await _tool(
        "search_knowledge",
        json.dumps({"question": "thali price", "scope": "everything"}),
        context=_ctx(tenant_id),
    )
    assert "Thali costs 180 rupees" in everything
    assert "agents do NOT use this yet" in everything

    agents = await _tool(
        "search_knowledge",
        json.dumps({"question": "thali price", "scope": None}),
        context=_ctx(tenant_id),
    )
    assert "Thali costs 180 rupees" not in agents
    assert "Menu" in agents  # named as saved but not used, never quoted as an answer


async def test_pip_reads_are_refused_without_the_agents_read_permission() -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    answer = await _tool("knowledge_sources", "{}", context=_ctx(tenant_id, role="nobody"))
    assert answer.startswith("Refused")


async def test_a_neighbours_item_cannot_be_opened() -> None:
    tenant_a, _ = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    async with tenant_session(tenant_a) as session:
        note = await kb_service.submit_source(
            session, tenant_id=tenant_a, name="Secret recipe", body="Two spoons of ghee always."
        )
    answer = await _tool(
        "knowledge_sources",
        json.dumps({"find": f"note:{note['id']}", "page": None}),
        context=_ctx(tenant_b),
    )
    assert "There is no such item" in answer


# --- 4. Pip edits -------------------------------------------------------------------


def _actor(tenant_id: uuid.UUID) -> ToolActor:
    return ToolActor(tenant_id=tenant_id, user_id=uuid.uuid4(), role="owner", impersonating=False)


async def test_rename_is_immediate_and_undo_puts_the_old_name_back(s3: FakeS3) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    actor = _actor(tenant_id)
    args = {"item": f"file:{row['id']}", "name": "Lunch menu"}
    assert KNOWLEDGE_RENAME.undo is not None
    async with tenant_session(tenant_id) as session:
        prior = await KNOWLEDGE_RENAME.undo.capture(session, actor, args)
        done = await KNOWLEDGE_RENAME.execute(session, actor, args)
        result = await KNOWLEDGE_RENAME.undo.capture(session, actor, args)
    assert done.applied and (await _upload_row(tenant_id, row["id"]))["name"] == "Lunch menu"
    async with tenant_session(tenant_id) as session:
        said = await KNOWLEDGE_RENAME.undo.invert(
            session,
            actor,
            UndoRecord(object_id="", args=args, prior_state=prior, result_state=result),
        )
    assert "old name" in said
    assert (await _upload_row(tenant_id, row["id"]))["name"] == "Menu"


async def test_a_name_another_item_uses_is_refused_and_so_is_the_facts_source() -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        first = await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Parking", body="Parking is behind the shop."
        )
        await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Payments", body="We take UPI and cash."
        )
        with pytest.raises(ProblemError) as taken:
            await store.rename_source(
                session, tenant_id=tenant_id, source_id=first["id"], name="Payments"
            )
    assert taken.value.code == "kb_name_taken"


async def test_a_note_is_written_replaced_removed_and_put_back_through_the_page_functions(
    s3: FakeS3,
) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    actor = _actor(tenant_id)
    # A NEW note is `propose_knowledge`'s; it lands through the same `submit_source`.
    async with tenant_session(tenant_id) as session:
        created = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            name="Parking",
            body="Parking is free behind the shop.",
            auto_approve=True,
        )
    source_id = uuid.UUID(str(created["id"]))
    await kb_ingest.publish_kb_source(
        {}, {"tenant_id": str(tenant_id), "source_id": str(source_id)}
    )
    ref = f"note:{source_id}"

    replace = {"item": ref, "text": "Parking is free for two hours behind the shop."}
    async with tenant_session(tenant_id) as session:
        plan = await KNOWLEDGE_NOTE_SAVE.plan(session, actor, replace)
        assert plan.current and "free behind" in plan.current
        await KNOWLEDGE_NOTE_SAVE.execute(session, actor, plan.args)
        versions = (
            await session.execute(text("SELECT count(*) FROM kb_sources WHERE name = 'Parking'"))
        ).scalar()
    assert versions == 2

    async with tenant_session(tenant_id) as session:
        removal = await KNOWLEDGE_REMOVE.plan(session, actor, {"item": ref, "put_back": None})
        assert "versions are kept" in removal.summary
        await KNOWLEDGE_REMOVE.execute(session, actor, removal.args)
        items, _total = await store.find_items(session, tenant_id=tenant_id, kinds=["note"])
    assert all(item.name != "Parking" for item in items)

    async with tenant_session(tenant_id) as session:
        back = await KNOWLEDGE_REMOVE.plan(session, actor, {"item": ref, "put_back": True})
        await KNOWLEDGE_REMOVE.execute(session, actor, back.args)
        items, _total = await store.find_items(session, tenant_id=tenant_id, kinds=["note"])
    assert any(item.name == "Parking" and item.state == "in_use" for item in items)


async def test_a_file_is_corrected_by_a_note_and_never_rewritten(s3: FakeS3) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    actor = _actor(tenant_id)
    args = {"item": f"file:{row['id']}", "name": None, "text": "Biryani is 260 rupees now."}
    async with tenant_session(tenant_id) as session:
        plan = await KNOWLEDGE_NOTE_SAVE.plan(session, actor, args)
        again = await KNOWLEDGE_NOTE_SAVE.plan(session, actor, plan.args)
    assert plan.args["name"] == "Correction to Menu"
    assert plan.args["text"].startswith("This corrects “Menu”: ")
    assert again.args["text"] == plan.args["text"]  # the approval re-plan adds nothing


async def test_facts_and_identifiers_are_refused_with_a_reason_pip_can_act_on() -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    actor = _actor(tenant_id)
    async with tenant_session(tenant_id) as session:
        note = await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Owner", body="Ask for the owner at the counter."
        )
        with pytest.raises(WriteRefusedError, match="facts tools"):
            await KNOWLEDGE_REMOVE.plan(session, actor, {"item": f"fact:{uuid.uuid4()}"})
        with pytest.raises(WriteRefusedError, match="phone number"):
            await KNOWLEDGE_NOTE_SAVE.plan(
                session,
                actor,
                # A synthetic number in the reserved-looking 98765 range, never a real one.
                {"item": f"note:{note['id']}", "text": "Call the owner on 9876543210 any time."},
            )
        with pytest.raises(ProblemError) as gone:
            await KNOWLEDGE_REMOVE.plan(session, actor, {"item": f"file:{uuid.uuid4()}"})
        assert gone.value.status == 404


# --- 5. routes ------------------------------------------------------------------------


async def _slug(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
        )


async def test_the_reader_rename_and_read_again_routes(s3: FakeS3) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE, HOURS_PAGE))
    await _ingest(tenant_id, row["source_id"])
    slug = await _slug(tenant_id)
    _owner, owner = await _member(tenant_id, "owner")
    _staff, staff = await _member(tenant_id, "staff")
    async with _client() as http:
        words = await http.get(f"/v1/kb/uploads/{row['id']}/text?page=2", headers=_h(owner, slug))
        assert words.status_code == 200
        body = words.json()
        assert body["page"] == 2 and body["pages"] == 2
        assert body["sections"][0]["label"] == "Page 2"
        assert body["reaches_agents"] is False

        renamed = await http.patch(
            f"/v1/kb/uploads/{row['id']}", json={"name": "Dinner menu"}, headers=_h(owner, slug)
        )
        assert renamed.status_code == 200 and renamed.json()["name"] == "Dinner menu"
        refused = await http.patch(
            f"/v1/kb/uploads/{row['id']}", json={"name": "Nope"}, headers=_h(staff, slug)
        )
        assert refused.status_code == 403

        again = await http.post(f"/v1/kb/uploads/{row['id']}/read", headers=_h(owner, slug))
        assert again.status_code == 202 and again.json()["read_state"] == "reading"


async def test_queue_read_marks_the_row_and_promises_the_job(s3: FakeS3) -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    async with tenant_session(tenant_id) as session:
        await queue_read(session, tenant_id=tenant_id, source_id=row["source_id"], force=True)
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = :j AND payload->>'source_id' = :s"
                ),
                {"j": READ_KB_UPLOAD_JOB, "s": str(row["source_id"])},
            )
        ).scalar()
    assert queued == 1
    assert (await _upload_row(tenant_id, row["id"]))["read_state"] == "reading"


async def test_readiness_counts_a_pdf_only_while_its_words_reach_the_agents(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.agents.readiness import knowledge_items

    tenant_id, _agent = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        before = await knowledge_items(session)
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    await _ingest(tenant_id, row["source_id"])
    async with tenant_session(tenant_id) as session:
        off = await knowledge_items(session)
        monkeypatch.setattr(get_settings(), "kb_send_extracted_files", True)
        on = await knowledge_items(session)
    assert off == before
    assert on == before + 1
