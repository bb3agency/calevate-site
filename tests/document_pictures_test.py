"""Pictures inside a client's document are read into its words (D-956).

What must hold, each driven through the real reading path with a fake reader (no network):

1. A picture on a PDF page of ordinary text, a DOCX inline picture and an XLSX sheet picture
   are read, and their words land right after the text of their page, paragraph or sheet.
2. What is not worth a paid read is never sent: a picture too small to hold a line of words,
   a repeat of one already read (a logo on every page), the scan a page is read as.
3. Past the per-file cap, and when the reader is off (no attested price), the pictures not
   read are named on the row for the client, and no call is made when the reader is off.
4. Every flow that reads the stored words gets them: onboarding's `documents_block`, and the
   chunker keeps a table read off a picture as whole rows.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.first_run.documents import document_words
from apps.api.kb import uploads
from apps.api.kb.service import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS, chunk_text
from apps.workers import chat, document_ocr, document_pictures, kb_ingest, kb_read
from apps.workers.document_ocr import OcrImage, PictureText, PictureTranscripts
from apps.workers.document_pictures import PICTURE_LABEL, PictureCollector, picture_block
from apps.workers.document_text import assemble, read_document
from apps.workers.first_run import documents_block
from calevate_shared.document_ingest import MAX_OCR_IMAGES
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.drawing.image import Image as SheetImage
from PIL import Image
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

PRICE_PAGE = "Our tiffin centre is open every day from seven in the morning till eleven."
TABLE_ROWS = "Item: Idli; Price: 40\nItem: Dosa; Price: 60"


def _png(width: int = 400, height: int = 200, colour: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf(*pages: tuple[str | None, list[bytes]]) -> bytes:
    """A page per `(words, pictures)`: the words as a text layer, the pictures below them."""
    pdf = FPDF()
    for words, pictures in pages:
        pdf.add_page()
        if words:
            pdf.set_font("helvetica", size=12)
            pdf.multi_cell(0, 8, words)
        for offset, picture in enumerate(pictures):
            pdf.image(io.BytesIO(picture), x=10, y=60 + offset * 60, w=80)
    return bytes(pdf.output())


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _docx(*paragraphs: str | bytes) -> bytes:
    """A Word body: a paragraph of text per string, a paragraph holding an inline picture
    per bytes — the `w:drawing` → `a:blip r:embed` → relationship → media chain Word writes."""
    body: list[str] = []
    rels: list[str] = []
    media: dict[str, bytes] = {}
    for item in paragraphs:
        if isinstance(item, str):
            body.append(f"<w:p><w:r><w:t>{item}</w:t></w:r></w:p>")
            continue
        rel_id = f"rId{len(rels) + 10}"
        name = f"media/image{len(media) + 1}.png"
        media[f"word/{name}"] = item
        rels.append(f'<Relationship Id="{rel_id}" Type="{_R}/image" Target="{name}"/>')
        body.append(
            f'<w:p><w:r><w:drawing><a:graphic><a:graphicData><a:blip r:embed="{rel_id}"/>'
            "</a:graphicData></a:graphic></w:drawing></w:r></w:p>"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:a="{_A}">'
            f"<w:body>{''.join(body)}</w:body></w:document>",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            f'package/2006/relationships">{"".join(rels)}</Relationships>',
        )
        for path, data in media.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def _fake_reader(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[OcrImage], str] = lambda _: TABLE_ROWS
) -> tuple[list[list[OcrImage]], list[dict[str, Any]]]:
    """Stand in for the paid reader. Records each call's pictures and each meter call."""
    calls: list[list[OcrImage]] = []
    metered: list[dict[str, Any]] = []

    async def _read(images: Any, **_: Any) -> PictureTranscripts:
        calls.append(list(images))
        return PictureTranscripts(
            pictures=tuple(PictureText(i.position, answer(i), None) for i in images),
            model="gemini-test",
            prompt_tokens=1120 * len(images),
            output_tokens=40,
        )

    async def _meter(session: Any, **kwargs: Any) -> None:
        metered.append(kwargs)

    monkeypatch.setattr(document_ocr, "ocr_pictures", _read)
    monkeypatch.setattr(kb_ingest, "_meter_ocr", _meter)
    return calls, metered


async def _upload(tenant_id: uuid.UUID, data: bytes, filename: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename=filename,
            content_type=None,
            data=data,
            submitted_by=None,
            auto_approve=True,
        )


async def _ingest(tenant_id: uuid.UUID, row: dict[str, Any]) -> dict[str, Any]:
    await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "source_id": str(row["source_id"]), "may_self_approve": True},
    )
    async with tenant_session(tenant_id) as session:
        return await uploads.get_upload(session, uuid.UUID(str(row["id"])))


async def _stored(tenant_id: uuid.UUID, upload_id: object) -> str:
    async with tenant_session(tenant_id) as session:
        return await document_words(session, uuid.UUID(str(upload_id)))


# --- 1. read, and placed beside their own page ----------------------------------------


async def test_a_table_pictured_on_a_text_page_follows_that_pages_words(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page WITH a text layer used to skip every image on it, so a price list pasted as a
    picture beside a paragraph never reached the agents."""
    calls, metered = _fake_reader(monkeypatch)
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _upload(
        tenant_id, _pdf((PRICE_PAGE, [_png()]), ("Page two words " * 5, [])), "m.pdf"
    )
    after = await _ingest(tenant_id, row)

    assert after["read_state"] == "ready"
    assert after["read_detail"] is None
    words = await _stored(tenant_id, row["id"])
    assert words.index("open every day") < words.index(PICTURE_LABEL) < words.index("Page two")
    assert f"{PICTURE_LABEL}\n{TABLE_ROWS}" in words
    async with tenant_session(tenant_id) as session:
        page = (
            await session.execute(
                text(
                    "SELECT (meta->>'page')::int FROM kb_documents WHERE source_id = :s "
                    "AND content LIKE '%Idli%'"
                ),
                {"s": row["source_id"]},
            )
        ).scalar_one()
    assert page == 1
    assert len(calls) == 1 and len(calls[0]) == 1
    assert metered and metered[0]["model"] == "gemini-test"


async def test_a_word_files_inline_picture_is_read_after_its_paragraph(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_reader(monkeypatch)
    tenant_id, _agent = await _tenant_with_published_agent()
    data = _docx("Our menu:", _png(), "Delivery is free above 300 rupees.")
    row = await _upload(tenant_id, data, "menu.docx")
    await _ingest(tenant_id, row)
    assert await _stored(tenant_id, row["id"]) == (
        f"Our menu:\n\n{PICTURE_LABEL}\n{TABLE_ROWS}\n\nDelivery is free above 300 rupees."
    )


def test_a_spreadsheets_picture_follows_its_sheet_and_a_picture_only_sheet_keeps_its_name() -> None:
    workbook = Workbook()
    prices = workbook.active
    assert prices is not None
    prices.title = "Prices"
    prices.append(["Item", "Price"])
    prices.append(["Vada", 30])
    menu = workbook.create_sheet("Menu photo")
    menu.add_image(SheetImage(io.BytesIO(_png(colour="red"))), "B2")
    prices.add_image(SheetImage(io.BytesIO(_png(colour="blue"))), "D2")
    buffer = io.BytesIO()
    workbook.save(buffer)

    parts = read_document(buffer.getvalue(), "xlsx")
    assert [p.where for p in parts.pictures.kept] == ["Prices", "Menu photo"]
    blocks = {p.anchor: [picture_block(f"from {p.where}")] for p in parts.pictures.kept}
    assert assemble(parts, blocks).text == (
        "Prices\nItem: Vada; Price: 30\n\n"
        f"{PICTURE_LABEL}\nfrom Prices\n\nMenu photo\n\n{PICTURE_LABEL}\nfrom Menu photo"
    )
    # Unread, the picture-only sheet adds nothing: not even its name.
    assert assemble(parts, {}).text == "Prices\nItem: Vada; Price: 30"


# --- 2. what is never sent -------------------------------------------------------------


def test_a_logo_on_every_page_is_read_once_and_a_bullet_never() -> None:
    logo = _png(300, 120, "navy")
    bullet = _png(16, 16, "black")
    reading = kb_read.read_pdf(
        _pdf((PRICE_PAGE, [logo, bullet]), (PRICE_PAGE, [logo]), (PRICE_PAGE, [logo, _png()]))
    )
    assert [(p.anchor, p.where) for p in reading.pictures.kept] == [
        (1, "page 1"),
        (3, "page 3"),
    ]
    assert reading.pictures.not_read == []


def test_the_scanned_page_is_read_whole_and_not_again_as_a_picture() -> None:
    reading = kb_read.read_pdf(_pdf((None, [_png(800, 1000)])))
    assert [number for number, _data, _mime in reading.scans] == [1]
    assert reading.pictures.kept == []


# --- 3. caps and an unattested reader --------------------------------------------------


async def test_past_the_cap_the_pictures_left_are_named_for_the_client(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = _fake_reader(monkeypatch)
    tenant_id, _agent = await _tenant_with_published_agent()
    paragraphs: list[str | bytes] = ["Our photo menu."]
    paragraphs += [_png(200 + i, 200) for i in range(MAX_OCR_IMAGES + 2)]
    row = await _upload(tenant_id, _docx(*paragraphs), "photos.docx")
    after = await _ingest(tenant_id, row)

    assert sum(len(c) for c in calls) == MAX_OCR_IMAGES
    assert after["read_detail"] == (
        f"2 pictures were not read: we read up to {MAX_OCR_IMAGES} pictures and scanned "
        "pages in one file."
    )
    assert (await _stored(tenant_id, row["id"])).count(PICTURE_LABEL) == MAX_OCR_IMAGES


async def test_a_reader_with_no_attested_price_makes_no_call_and_says_so(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _never(*_: Any, **__: Any) -> Any:
        raise AssertionError("the reader was called without an attested price")

    monkeypatch.setattr(document_ocr, "client_content_data_use_reason", lambda _p: None)
    monkeypatch.setattr(document_ocr, "unofferable_reason", lambda _m, **_k: "price_unattested")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gk-test", raising=False)
    monkeypatch.setattr(chat, "complete", _never)
    metered: list[Any] = []

    async def _meter(session: Any, **kwargs: Any) -> None:
        metered.append(kwargs)

    monkeypatch.setattr(kb_ingest, "_meter_ocr", _meter)
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _upload(tenant_id, _docx("Our menu:", _png()), "menu.docx")
    after = await _ingest(tenant_id, row)

    assert (
        after["read_detail"] == "We can't read pictures right now. Their words are not in use yet."
    )
    assert await _stored(tenant_id, row["id"]) == "Our menu:"
    assert metered == []


def test_a_picture_the_reader_could_not_read_is_named_and_one_with_no_words_is_not() -> None:
    reading = document_pictures.PictureReading(
        not_read=[("page 4", document_pictures.NOT_READ_FAILED)]
    )
    assert reading.detail() == "1 picture could not be read (page 4)."
    assert document_pictures.PictureReading().detail() is None


# --- 4. every flow reads the stored words ----------------------------------------------


async def test_onboarding_documents_carry_the_words_of_an_uploads_pictures(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_reader(monkeypatch)
    tenant_id, _agent = await _tenant_with_published_agent()
    row = await _upload(tenant_id, _docx("Price list below.", _png()), "prices.docx")
    await _ingest(tenant_id, row)
    block = documents_block([("prices.docx", await _stored(tenant_id, row["id"]))])
    assert "Item: Dosa; Price: 60" in block


def test_a_table_read_off_a_picture_is_chunked_a_whole_row_at_a_time() -> None:
    rows = [f"Item: Special thali number {n} with curd; Price: {100 + n}" for n in range(40)]
    body = f"{PRICE_PAGE}\n\n{picture_block(chr(10).join(rows))}"
    chunks = chunk_text(body)
    assert len(chunks) > 1
    # `chunk_text` may fold a stub tail into the last chunk, its one allowed overrun.
    assert all(len(chunk) <= MAX_CHUNK_CHARS + MIN_CHUNK_CHARS + 2 for chunk in chunks)
    for row in rows:
        assert sum(row in chunk.split("\n") for chunk in chunks) == 1
    assert "".join("".join(c.split()) for c in chunks) == "".join(body.split())


def test_the_collector_holds_at_most_its_cap_of_pictures() -> None:
    collector = PictureCollector(cap=2)
    for width in (200, 201, 202):
        collector.offer(_png(width, 200), anchor=1, where="page 1")
    assert len(collector.kept) == 2
    assert collector.not_read == [("page 1", document_pictures.NOT_READ_OVER_CAP)]
