"""The pictures inside a client's document, read into words beside the page they sit on (D-956).

A price list pasted into a Word file as a screenshot, a menu photo on page 2 of a PDF, a chart
of rates on a spreadsheet tab: their words are the knowledge, and a text parser sees none of
them. So while a PDF, DOCX or XLSX is read, every picture worth reading is collected here
(`PictureCollector`), sent to the same reader as a photograph (`document_ocr.ocr_pictures`,
metered as `ASSIST_FEATURE_KB_OCR` exactly as a photograph is), and its words placed right
after the text of the page, paragraph or sheet it came from, under `PICTURE_LABEL`. The words
then live in the document's stored text, which is what every other flow reads: the reader,
Pip, chunks and embeddings, the T0 block, the copy the agents are sent, onboarding and the
script suggestions.

WHAT IS NOT SENT, and why each is skipped before any money is spent:

* **Small pictures** (`MIN_PICTURE_SHORT_SIDE_PX`, `MIN_PICTURE_LONG_SIDE_PX`): bullets,
  icons, rules and spacer images. A line of words worth reading needs ~10 px per character
  and ~24 px of height, so below 24 px on the short side or 100 px on the long side there is
  no line of words to read; on Gemini 3 every picture costs the same 1,120 input tokens
  whatever its size (ai.google.dev/gemini-api/docs/media-resolution), so a bullet would cost
  what a price list does.
* **Repeats**: the same bytes twice (a logo or a watermark on every page) are read once, at
  their first place, and never again. pypdf re-encodes one shared image object identically on
  every page, and an OOXML file references one media part from every place it appears.
* **The scanned page itself**: a page with no words is read whole by `kb_read`'s scan path,
  so its picture is excluded here rather than read twice.
* **Past the cap**: a document's model reads, scanned pages and pictures together, stop at
  `MAX_OCR_IMAGES`, the bound `document_ocr.MAX_SOURCE_OCR_COST_USD` is asserted over. The
  pictures left are named to the client, never silently dropped.

Nothing here logs a picture, its words or a sheet name (hard rule 6).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from uuid import UUID

from calevate_shared.document_ingest import (
    MAX_IMAGE_BYTES,
    MAX_OCR_IMAGES,
    OCR_IMAGE_MIME_TYPES,
    OcrUnavailableError,
)

from apps.api.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

#: The line that opens a picture's words in the stored text, so a reader, Pip and the agent
#: can tell words read off a picture from words typed on the page. No provider is named.
PICTURE_LABEL: Final = "[Picture]"

MIN_PICTURE_SHORT_SIDE_PX: Final = 24
MIN_PICTURE_LONG_SIDE_PX: Final = 100

#: A picture is re-encoded past this longer side. On Gemini 3 a picture is one 1,120-token
#: budget at the default resolution whatever its size (media-resolution page above), so more
#: pixels add bytes to the request and nothing to the reading.
MAX_PICTURE_SIDE_PX: Final = 3072

#: A picture past this many pixels is skipped rather than decoded: it is past any phone
#: camera, decoding it would hold ~256 MB of RGBA in a worker, and it is under Pillow's own
#: decompression-bomb warning (`Image.MAX_IMAGE_PIXELS`, about 89 million).
MAX_PICTURE_PIXELS: Final = 64_000_000

#: Pillow's format names for the types the reader takes as they are. Anything else that
#: Pillow can decode (GIF, BMP, TIFF, JPEG 2000) is re-encoded as PNG.
_SENT_AS_IS: Final[dict[str, str]] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

#: Why a picture was not read, in the client's words.
NOT_READ_OVER_CAP: Final = "over_cap"
NOT_READ_FORMAT: Final = "format"
NOT_READ_FAILED: Final = "failed"
#: The reader's codes that mean "nothing to read here", which is an answer, not a failure: a
#: photograph with no writing, or a logo's one word.
_NOTHING_TO_READ: Final = frozenset({"no_text", "too_little_text"})


@dataclass(frozen=True, slots=True)
class Picture:
    """One picture to read. `anchor` is where its words go: a PDF's page number, or the index
    of the block (paragraph, table or sheet) it follows. `where` names the place for the
    client ("page 3", a sheet's name), or "" in a document without pages."""

    data: bytes
    mime_type: str
    anchor: int
    where: str


@dataclass(slots=True)
class PictureCollector:
    """The pictures of one document worth reading, in document order. Holds bytes for at
    most `cap` of them; past that it keeps only where the others were."""

    cap: int = MAX_OCR_IMAGES
    kept: list[Picture] = field(default_factory=list)
    #: `(where, NOT_READ_…)` for every picture that will not be read and the client must hear
    #: about. Small pictures and repeats are not here: they are not a loss.
    not_read: list[tuple[str, str]] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)

    def exclude(self, data: bytes) -> None:
        """Treat these bytes as read already: the scanned page `kb_read` reads whole."""
        self._seen.add(hashlib.sha256(data).hexdigest())

    def offer(self, data: bytes, *, anchor: int, where: str) -> None:
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._seen:
            return
        self._seen.add(digest)
        measured = _measure(data)
        if measured is None:
            self.not_read.append((where, NOT_READ_FORMAT))
            return
        width, height = measured
        if (
            min(width, height) < MIN_PICTURE_SHORT_SIDE_PX
            or max(width, height) < MIN_PICTURE_LONG_SIDE_PX
        ):
            return
        if len(self.kept) >= self.cap:
            self.not_read.append((where, NOT_READ_OVER_CAP))
            return
        sendable = _sendable(data)
        if sendable is None:
            self.not_read.append((where, NOT_READ_FORMAT))
            return
        self.kept.append(
            Picture(data=sendable[0], mime_type=sendable[1], anchor=anchor, where=where)
        )

    def trim(self, budget: int) -> list[Picture]:
        """The pictures inside `budget` reads; the rest are named as over the cap."""
        budget = max(0, budget)
        for picture in self.kept[budget:]:
            self.not_read.append((picture.where, NOT_READ_OVER_CAP))
        return self.kept[:budget]


def _measure(data: bytes) -> tuple[int, int] | None:
    """`(width, height)` from the picture's header, or None when Pillow cannot identify it
    (EMF/WMF drawings, a damaged part) or it is past `MAX_PICTURE_PIXELS`."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception as exc:  # Pillow raises many shapes on a damaged or exotic file
        log.info("document_picture_unidentified", extra={"error": type(exc).__name__})
        return None
    if width * height > MAX_PICTURE_PIXELS:
        return None
    return width, height


def _sendable(data: bytes) -> tuple[bytes, str] | None:
    """The picture as the reader takes it: as it is when its type and size already fit,
    else re-encoded as PNG at most `MAX_PICTURE_SIDE_PX` on its longer side."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            mime = _SENT_AS_IS.get(str(image.format))
            if (
                mime in OCR_IMAGE_MIME_TYPES
                and len(data) <= MAX_IMAGE_BYTES
                and max(image.size) <= MAX_PICTURE_SIDE_PX
            ):
                return data, str(mime)
            image.seek(0)
            frame = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            frame.thumbnail((MAX_PICTURE_SIDE_PX, MAX_PICTURE_SIDE_PX))
            out = io.BytesIO()
            frame.save(out, format="PNG", optimize=True)
    except Exception as exc:
        log.info("document_picture_unconvertible", extra={"error": type(exc).__name__})
        return None
    encoded = out.getvalue()
    return (encoded, "image/png") if len(encoded) <= MAX_IMAGE_BYTES else None


@dataclass(slots=True)
class PictureReading:
    """What the reader made of a document's pictures."""

    #: anchor → the words of each picture there, in order, each opened by `PICTURE_LABEL`.
    blocks: dict[int, list[str]] = field(default_factory=dict)
    read: int = 0
    not_read: list[tuple[str, str]] = field(default_factory=list)
    #: The reader is off on this deployment (no key, price or data-use attestation): no
    #: picture was sent, nothing was spent, and the client is told.
    unavailable: OcrUnavailableError | None = None

    def detail(self) -> str | None:
        """The client's sentence about pictures that were not read, or None."""
        if self.unavailable is not None:
            return "We can't read pictures right now. Their words are not in use yet."
        if not self.not_read:
            return None
        over = [where for where, why in self.not_read if why == NOT_READ_OVER_CAP]
        other = [where for where, why in self.not_read if why != NOT_READ_OVER_CAP]
        said: list[str] = []
        if over:
            said.append(
                f"{_count(len(over)).capitalize()} {_were(len(over))} not read{_places(over)}: "
                f"we read up to {MAX_OCR_IMAGES} pictures and scanned pages in one file."
            )
        if other:
            said.append(f"{_count(len(other)).capitalize()} could not be read{_places(other)}.")
        return " ".join(said)


def _count(n: int) -> str:
    return "1 picture" if n == 1 else f"{n} pictures"


def _were(n: int) -> str:
    return "was" if n == 1 else "were"


def _places(wheres: list[str]) -> str:
    named = list(dict.fromkeys(w for w in wheres if w))
    if not named:
        return ""
    shown = ", ".join(named[:5]) + (" and more" if len(named) > 5 else "")
    return f" ({shown})"


def picture_block(words: str) -> str:
    """One picture's words as they are stored: the label, then the words, with no blank line
    inside, so `kb.service.chunk_text` keeps a table read off a picture as whole rows."""
    from apps.api.kb.service import without_invisible_characters

    lines = [line.rstrip() for line in without_invisible_characters(words).strip().splitlines()]
    return "\n".join([PICTURE_LABEL, *(line for line in lines if line.strip())])


async def read_pictures(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    collector: PictureCollector,
    budget: int = MAX_OCR_IMAGES,
) -> PictureReading:
    """Read the collected pictures within `budget`, metering what the reader was paid for in
    the caller's transaction (`kb_ingest._meter_ocr`, priced by
    `billing/rates.llm_inr_per_ktok`; an unattested price keeps the reader `unavailable`)."""
    from apps.workers import document_ocr
    from apps.workers.kb_ingest import _meter_ocr

    pictures = collector.trim(budget)
    reading = PictureReading(not_read=list(collector.not_read))
    if not pictures:
        return reading
    images = [
        document_ocr.OcrImage(data=p.data, mime_type=p.mime_type, position=i)
        for i, p in enumerate(pictures, start=1)
    ]
    try:
        transcripts = await document_ocr.ocr_pictures(images)
    except OcrUnavailableError as unavailable:
        log.error("document_pictures_reader_unavailable", extra={"reason": unavailable.reason})
        reading.unavailable = unavailable
        return reading
    if transcripts.model is not None:
        await _meter_ocr(
            session,
            tenant_id=tenant_id,
            model=transcripts.model,
            prompt_tokens=transcripts.prompt_tokens,
            output_tokens=transcripts.output_tokens,
            cached_tokens_in=transcripts.cached_prompt_tokens,
            usage_incomplete=transcripts.usage_incomplete,
        )
    for result in transcripts.pictures:
        picture = pictures[result.position - 1]
        if result.reason is None:
            reading.blocks.setdefault(picture.anchor, []).append(picture_block(result.text))
            reading.read += 1
        elif result.reason not in _NOTHING_TO_READ:
            reading.not_read.append((picture.where, NOT_READ_FAILED))
    return reading


__all__ = [
    "PICTURE_LABEL",
    "Picture",
    "PictureCollector",
    "PictureReading",
    "picture_block",
    "read_pictures",
]
