"""A client's PDF or linked page, read into a copy of its words that we keep (D-893 L8, D-868).

The voice platform's knowledge API takes a web page `url` or pasted `text`; files are console
uploads, and its own PDF reading has no OCR (snapshots/2026-10-29/pages/api-reference/
knowledge/add-knowledge-document.md:7; pages/agent/knowledge.md:39-53). So a PDF's words are
read HERE and are what its agents are sent, while a link is sent as its address and the
platform fetches it. Both copies are stored where every other upload's text is —
`kb_documents`, through `kb.service.store_read_copy` — so the client's reader, Pip's find,
open and search, and the retrieval projection see a PDF as they see a Word file.

═══ HOW A PDF IS READ ═══

pypdf, page by page: `PdfReader(stream)`, `reader.pages`, `page.extract_text()`;
`reader.is_encrypted` and `reader.decrypt("")` for a PDF locked with an empty owner password
(pypdf docs "Extract Text", "Encryption and Decryption" and `PageObject`, pypdf.readthedocs.io
stable, read 26 Oct 2026; the installed version is 6.16.2 per `uv.lock`). pypdf "will never be
able to extract text from images", so a page with no text layer, or one too thin or garbled to
be the page's words (`_is_text_layer`), is a scan when it carries an image: its largest image
(`page.images`, each an `ImageFile` with `.name` and `.data`) is read by our Gemini reader
through `document_ocr.ocr_images`, one page per call, and each call is metered to the
client's AI usage in this transaction exactly as a photograph is (`kb_ingest._meter_ocr`).
At most `MAX_OCR_PAGES` scanned pages are read per document, the bound `MAX_OCR_IMAGES` puts
on a photograph upload, so one large scan cannot spend without limit.

The other pictures on a page — a price list pasted as an image beside ordinary text, a chart,
a menu photo — are read too (D-956, `document_pictures`), within what the scans left of that
bound, and their words follow the page's own in the same section.

═══ HOW A LINK IS READ ═══

That one page only (founder, 24 Oct 2026), through `kb_ingest.fetch_page` — the same SSRF
gate, byte ceiling and deadline the change sweep uses — and its visible text kept: scripts,
styles and markup dropped, block elements turned into paragraph breaks.

═══ WHAT IS NEVER DONE ═══

No document text reaches a log (hard rule 6): ids, counts and codes only. A failure lands on
the row as `read_state = 'failed'` with a sentence the client can act on. It never blocks a
link's publish, which goes as its address; a PDF with no words is withheld from the agents
(`kb.service._withheld_from_engine`) until "Read it again" finds some.
"""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Final
from uuid import UUID

from calevate_shared.document_ingest import (
    MAX_IMAGE_BYTES,
    MAX_OCR_IMAGES,
    OCR_IMAGE_MIME_TYPES,
    DocumentRefusedError,
    OcrUnavailableError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.models import READ_COPY_KINDS, READ_FAILED, READ_READING, READ_READY
from apps.workers.document_pictures import PictureCollector, read_pictures

log = get_logger(__name__)

#: The most pages of one PDF we read. A price list or a menu is a few pages; past this a
#: document is a book, and the copy would be a cost nobody asked for.
MAX_PDF_PAGES: Final = 500
#: The most characters kept from one page. pypdf parses a page's whole content stream to
#: extract it, and a page built to be huge would otherwise set our memory.
MAX_PAGE_CHARS: Final = 20_000
#: Scanned pages read by the Gemini reader per document: the photograph upload's own bound.
#: Pictures on the other pages share it (`document_pictures`).
MAX_OCR_PAGES: Final = MAX_OCR_IMAGES
#: The wall-clock seconds one PDF's pages may take, checked before each page. `read_pdf` runs
#: in a thread, which `asyncio` cannot cancel: when the job overruns `job_timeout` (300 s) the
#: thread keeps parsing, and arq's retry starts a second one on the same file. A crafted page
#: costs at most one page past this, not the remaining pages times the retries.
MAX_PDF_READ_S: Final = 60.0
#: Read through the module so a test can move time instead of waiting for it.
_clock = time.monotonic

_IMAGE_TYPES: Final[dict[str, str]] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class UnreadablePdfError(Exception):
    """The PDF could not be opened at all. `detail` is the client's sentence."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(slots=True)
class PdfReading:
    """What pypdf found: the pages with words, and the scans that need the reader."""

    page_count: int
    #: `(page number, text)`, 1-based, for every page with a text layer.
    pages: list[tuple[int, str]] = field(default_factory=list)
    #: `(page number, image bytes, mime type)` for a page with no words and one image.
    scans: list[tuple[int, bytes, str]] = field(default_factory=list)
    #: Pages with neither words nor an image we can hand the reader.
    blank: int = 0
    #: Pages looked at before `MAX_PDF_PAGES` or `MAX_PDF_READ_S` stopped the reading.
    examined: int = 0
    #: Every other picture worth reading, anchored to its page (D-956): a price list pasted
    #: as an image on a page of ordinary text is read beside that page's words.
    pictures: PictureCollector = field(default_factory=PictureCollector)


def read_pdf(data: bytes) -> PdfReading:
    """The words of every page of a PDF, and the scanned pages to read. CPU-bound: the
    caller runs it in a thread. Raises `UnreadablePdfError` with the client's sentence."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnreadablePdfError(
                "This PDF is locked with a password. Save a copy without the password and "
                "send that."
            )
        pages = list(reader.pages)
    except UnreadablePdfError:
        raise
    except Exception as exc:  # pypdf raises many shapes on a damaged file
        log.info("kb_read_pdf_unopenable", extra={"error": type(exc).__name__})
        raise UnreadablePdfError(
            "We could not open this PDF. It may be damaged: save it again and send it."
        ) from None
    reading = PdfReading(page_count=len(pages))
    deadline = _clock() + MAX_PDF_READ_S
    for number, page in enumerate(pages[:MAX_PDF_PAGES], start=1):
        if _clock() >= deadline:
            log.info("kb_read_pdf_out_of_time", extra={"pages": reading.examined})
            break
        reading.examined = number
        try:
            words = (page.extract_text() or "").strip()[:MAX_PAGE_CHARS]
        except Exception as exc:
            log.info("kb_read_page_failed", extra={"page": number, "error": type(exc).__name__})
            words = ""
        images = _page_images(page)
        scan = None if words and _is_text_layer(words) else _largest_image(images)
        if scan is not None:
            reading.scans.append((number, *scan))
            # Read whole as the page; the reader is not asked about it twice.
            reading.pictures.exclude(scan[0])
        elif words:
            # A text layer, or thin or garbled with nothing better: keep what pypdf found.
            reading.pages.append((number, words))
        else:
            reading.blank += 1
        for data, _mime in images:
            reading.pictures.offer(data, anchor=number, where=f"page {number}")
    return reading


#: A page whose text layer is shorter than this (non-whitespace characters) is read as a
#: scan when it carries an image: a phone scanner's "Scanned by …" footer or a page number
#: is a text layer, and treating it as the page's words left the scan itself unread.
MIN_TEXT_LAYER_CHARS: Final = 40
#: The share of replacement or private-use characters past which a text layer is a font
#: pypdf could not map (common with legacy Indic fonts) rather than words.
MAX_UNMAPPED_SHARE: Final = 0.05


def _is_text_layer(words: str) -> bool:
    """Whether pypdf's text is the page's words, rather than a footer or unmapped glyphs."""
    dense = "".join(words.split())
    if len(dense) < MIN_TEXT_LAYER_CHARS:
        return False
    unmapped = sum(1 for ch in dense if ch == "�" or 0xE000 <= ord(ch) <= 0xF8FF)
    return unmapped <= len(dense) * MAX_UNMAPPED_SHARE


def _page_images(page: Any) -> list[tuple[bytes, str | None]]:
    """Every image on a page as `(bytes, mime)`, the mime None when the reader does not take
    the type as it is. One at a time by key, as pypdf advises: iterating `page.images`
    "will raise an exception on the first issue" (pypdf docs, "Extract Images", stable), so
    one damaged image would have cost the page's others."""
    found: list[tuple[bytes, str | None]] = []
    try:
        keys = list(page.images.keys())
    except Exception as exc:
        log.info("kb_read_images_failed", extra={"error": type(exc).__name__})
        return found
    for key in keys:
        try:
            image = page.images[key]
            data = bytes(image.data)
        except Exception as exc:
            log.info("kb_read_image_failed", extra={"error": type(exc).__name__})
            continue
        mime = _IMAGE_TYPES.get(str(image.name).rsplit(".", 1)[-1].lower())
        found.append((data, mime if mime in OCR_IMAGE_MIME_TYPES else None))
    return found


def _largest_image(images: list[tuple[bytes, str | None]]) -> tuple[bytes, str] | None:
    """The biggest image on a page with no words, as `(bytes, mime)`, when the reader takes
    its type. A scanned page is one image the size of the page; the largest is that one."""
    best: tuple[bytes, str] | None = None
    for data, mime in images:
        if mime is None or len(data) > MAX_IMAGE_BYTES:
            continue
        if best is None or len(data) > len(best[0]):
            best = (data, mime)
    return best


#: Elements whose text is never shown on a page.
_HIDDEN_TAGS: Final = frozenset({"script", "style", "noscript", "template", "svg", "head"})
#: Elements that start a new block, so their text is a paragraph of its own.
_BLOCK_TAGS: Final = frozenset(
    {
        "p", "div", "section", "article", "li", "ul", "ol", "table", "tr", "br", "hr",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "main", "nav", "aside",
        "blockquote", "pre", "dd", "dt", "figcaption", "address",
    }
)  # fmt: skip


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[list[str]] = [[]]
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden += 1
        elif tag in _BLOCK_TAGS:
            self.blocks.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCK_TAGS:
            self.blocks.append([])

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.blocks[-1].append(data)


def page_text(body: bytes) -> str:
    """The visible text of an HTML page, one paragraph per block element."""
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    paragraphs = (" ".join("".join(block).split()) for block in parser.blocks)
    return "\n\n".join(p for p in paragraphs if p)


_ROW_SQL = """
SELECT u.id, u.source_kind, u.original_key, u.source_url, u.read_state, u.content_digest,
       s.is_active
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
WHERE u.source_id = :sid
"""

_MARK_SQL = """
UPDATE kb_uploads
   SET read_state = :state,
       read_detail = :detail,
       page_count = COALESCE(:pages, page_count),
       updated_at = now()
 WHERE id = :id
"""


async def _mark(
    session: AsyncSession,
    upload_id: UUID,
    state: str,
    *,
    detail: str | None = None,
    pages: int | None = None,
) -> None:
    await session.execute(
        text(_MARK_SQL), {"id": upload_id, "state": state, "detail": detail, "pages": pages}
    )


@dataclass(slots=True)
class ScanReading:
    """What the Gemini reader made of a PDF's scanned pages."""

    pages: list[tuple[int, str]] = field(default_factory=list)
    #: Scanned pages not read: unreadable, refused, past `MAX_OCR_PAGES`, or no reader.
    missed: int = 0
    #: The reader is switched off on this deployment (no key, or its price not attested),
    #: so no scanned page was read at all. The client is told, and "Read it again" retries.
    unavailable: bool = False


#: Said when a PDF has scanned pages and the reader is off: the truth, no vendor named.
OCR_OFF_DETAIL: Final = (
    "Some pages are pictures of text, and we cannot read pictures right now. Try "
    '"Read it again" later, or send those pages typed.'
)


async def _read_scans(
    session: AsyncSession, *, tenant_id: UUID, scans: list[tuple[int, bytes, str]]
) -> ScanReading:
    """Read scanned pages with the Gemini reader, metering each call to the client's AI
    usage (`kb_ingest._meter_ocr`, priced by `billing/rates.llm_inr_per_ktok`, which refuses
    an unattested model, so the reader is `unavailable` rather than unbilled)."""
    from apps.workers.document_ocr import OcrImage, PaidOcrUnusableError, ocr_images
    from apps.workers.kb_ingest import _meter_ocr

    reading = ScanReading(missed=max(0, len(scans) - MAX_OCR_PAGES))
    read = reading.pages
    for number, data, mime in scans[:MAX_OCR_PAGES]:
        try:
            extracted = await ocr_images([OcrImage(data=data, mime_type=mime, position=number)])
        except OcrUnavailableError as unavailable:
            # No reader on this deployment: an operator's fix, so stop asking per page.
            log.error("kb_read_ocr_unavailable", extra={"reason": unavailable.reason})
            reading.missed += len(scans[:MAX_OCR_PAGES]) - len(read)
            reading.unavailable = True
            return reading
        except DocumentRefusedError as refused:
            if isinstance(refused, PaidOcrUnusableError):
                await _meter_ocr(
                    session,
                    tenant_id=tenant_id,
                    model=refused.model,
                    prompt_tokens=refused.prompt_tokens,
                    output_tokens=refused.output_tokens,
                    cached_tokens_in=refused.cached_prompt_tokens,
                    usage_incomplete=refused.usage_incomplete,
                )
            log.info("kb_read_scan_refused", extra={"page": number, "code": refused.code})
            reading.missed += 1
            continue
        if extracted.model is not None:
            await _meter_ocr(
                session,
                tenant_id=tenant_id,
                model=extracted.model,
                prompt_tokens=extracted.prompt_tokens,
                output_tokens=extracted.output_tokens,
                cached_tokens_in=extracted.cached_prompt_tokens,
                usage_incomplete=extracted.usage_incomplete,
            )
        read.append((number, extracted.text))
    return reading


def _with_pictures(
    pages: list[tuple[int, str]], pictures: dict[int, list[str]]
) -> list[tuple[int | None, str]]:
    """Each page's words, then the words of the pictures on it, as one section per page:
    a section is chunked on its own and its chunks carry the page (`store_read_copy`)."""
    words = dict(pages)
    return [
        (
            number,
            "\n\n".join([*([words[number]] if number in words else []), *pictures.get(number, [])]),
        )
        for number in sorted({*words, *pictures})
    ]


def _partial_detail(*, read: int, total: int) -> str | None:
    if read >= total:
        return None
    missing = total - read
    return (
        f"We read {read} of {total} pages. {missing} "
        f"{'page has' if missing == 1 else 'pages have'} no words we could read."
    )


async def read_saved_copy(
    session: AsyncSession, *, tenant_id: UUID, source_id: UUID, force: bool = False
) -> str:
    """Read one saved PDF or link into its copy, in the caller's transaction. Returns an
    outcome word. Idempotent: a copy already read (or a reading that failed) is left alone
    unless `force`, because a scanned PDF's reading is paid for."""
    row = (await session.execute(text(_ROW_SQL), {"sid": source_id})).first()
    if row is None:
        return "gone"
    upload_id, kind, key, url = UUID(str(row[0])), str(row[1]), row[2], row[3]
    state, known_digest, is_active = row[4], row[5], bool(row[6])
    if kind not in READ_COPY_KINDS:
        return "not_a_copy"
    if state in (READ_READY, READ_FAILED) and not force:
        return f"already_{state}"
    await _mark(session, upload_id, READ_READING)

    detail: str | None = None
    pages: int | None = None
    if kind == "pdf":
        from apps.workers.storage import read_kb_object

        data = await read_kb_object(str(key)) if key else None
        if not data:
            await _mark(
                session,
                upload_id,
                READ_FAILED,
                detail="We can no longer find that file. Send it again.",
            )
            return "failed"
        try:
            reading = await asyncio.to_thread(read_pdf, data)
        except UnreadablePdfError as unreadable:
            await _mark(session, upload_id, READ_FAILED, detail=unreadable.detail)
            return "failed"
        scanned = await _read_scans(session, tenant_id=tenant_id, scans=reading.scans)
        # Scanned pages and pictures share one document's reads (`MAX_OCR_IMAGES`, the
        # bound the OCR cost assertion is stated over); the scans are the pages' own words,
        # so they come first.
        pictures = await read_pictures(
            session,
            tenant_id=tenant_id,
            collector=reading.pictures,
            budget=MAX_OCR_IMAGES - min(len(reading.scans), MAX_OCR_PAGES),
        )
        sections = _with_pictures([*reading.pages, *scanned.pages], pictures.blocks)
        pages = reading.page_count
        detail = _partial_detail(
            read=len({*(n for n, _ in reading.pages), *(n for n, _ in scanned.pages)}),
            total=reading.examined,
        )
        if reading.examined < pages:
            detail = f"We read the first {reading.examined} pages of {pages}."
        if scanned.unavailable:
            detail = OCR_OFF_DETAIL
        if (said := pictures.detail()) is not None and not scanned.unavailable:
            detail = f"{detail} {said}" if detail else said
        empty = (
            OCR_OFF_DETAIL
            if scanned.unavailable
            else "There are no words we could read in this PDF. If it is a scan, send the "
            "pages as photos."
        )
    else:
        from apps.workers.kb_ingest import fetch_page, page_digest

        body = await fetch_page(str(url))
        if body is None:
            await _mark(
                session,
                upload_id,
                READ_FAILED,
                detail="We could not open that page. Check the address works in a browser.",
            )
            return "failed"
        if known_digest is None:
            # The first reading is also the change sweep's baseline, so the next check
            # compares against what was read here rather than flagging a change.
            await session.execute(
                text("UPDATE kb_uploads SET content_digest = :d WHERE id = :id"),
                {"d": page_digest(body), "id": upload_id},
            )
        sections = [(None, page_text(body))]
        empty = "There are no words we could read on that page."

    try:
        stored = await kb_service.store_read_copy(
            session, tenant_id=tenant_id, source_id=source_id, sections=sections
        )
    except ProblemError:
        stored = 0
    if not stored:
        await _mark(session, upload_id, READ_FAILED, detail=empty, pages=pages)
        return "failed"
    await _mark(session, upload_id, READ_READY, detail=detail, pages=pages)
    if is_active:
        # Live already (a re-read, or a version published before its words were read):
        # project now, as the publish would have, so it is searchable at once.
        await kb_service.project_chunks(session, tenant_id=tenant_id, source_id=source_id)
    log.info(
        "kb_read_copy",
        extra={"source_id": str(source_id), "kind": kind, "chunks": stored, "pages": pages},
    )
    return "read"


async def read_kb_upload(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Read one saved PDF or link into its copy, and re-send a live one to the agents.

    Enqueued by `kb.reading.queue_read`: "Read it again" on the reader, and
    `scripts/read_saved_files.py` for uploads saved before their words were read. A new
    upload is read inside `ingest_kb_source` instead, before its publish.
    """
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    source_id = UUID(str(payload["source_id"]))
    force = bool(payload.get("force"))
    async with tenant_session(tenant_id) as session:
        outcome = await read_saved_copy(
            session, tenant_id=tenant_id, source_id=source_id, force=force
        )
        live = (
            await session.execute(
                text("SELECT is_active FROM kb_sources WHERE id = :sid"), {"sid": source_id}
            )
        ).scalar()
    if outcome == "read" and live:
        # A PDF's new words go to its agents; a link's publish identity is its address and
        # the page we first read, so the re-upload guard makes this a no-op for one. Its
        # own transaction: a publish takes the knowledge lock and makes vendor calls, and a
        # slow vendor must not roll back a paid reading.
        async with tenant_session(tenant_id) as session:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
        return "read:sent"
    return outcome


__all__ = [
    "MAX_OCR_PAGES",
    "MAX_PDF_PAGES",
    "PdfReading",
    "ScanReading",
    "UnreadablePdfError",
    "page_text",
    "read_kb_upload",
    "read_pdf",
    "read_saved_copy",
]
