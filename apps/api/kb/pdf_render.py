"""Approved knowledge chunks → one PDF the engine's knowledgebase endpoint will accept.

**Why a PDF at all.** `POST /knowledgebase` takes `multipart/form-data` carrying `file`
(PDF, max 20 MB) *or* `url`, "not both", and there is no text field
(`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:36-51`, read
2026-09-01). Our knowledge is approved PROSE in `kb_documents`. So the only way to reach
the engine's in-call RAG is to render our chunks into a PDF and upload that. This module
is the renderer, and nothing more: it is pure, synchronous, takes no session and does no
I/O beyond reading the vendored font off disk.

**The failure this module exists to prevent is SILENT.** A PDF whose text layer is empty
still uploads, still reports `processed`, and the agent then retrieves nothing — first
observed on a live call. Three ways to produce one, all measured against fpdf2 2.8.8 and
pypdf 6.16.2 on 2026-09-01, and all closed here:

1. *No Telugu glyphs.* The PDF base-14 fonts have none, so Telugu renders as nothing at
   all. We embed a font that covers the script (see `FONT_PATH`).
2. *A character the embedded font does not cover.* fpdf2 does **not** raise: it prints
   "Font ... is missing the following glyphs" to stderr and drops them. A Hindi
   paragraph pasted into a Telugu knowledge base extracted back as the empty string.
   `_require_font_coverage` refuses instead, naming the codepoints.
3. *Text shaping.* fpdf2 can shape complex scripts through uharfbuzz, which renders
   Telugu conjuncts correctly for a human eye — and corrupts the text layer, because a
   ligature glyph gets no faithful `ToUnicode` entry: `తెరుస్తాము` extracted back as
   `'తెరుస్తా\\x11 ము'`. **Shaping stays OFF and uharfbuzz is deliberately not a
   dependency.** The vendor PARSES this file; no human reads it. Correct bytes out of
   the text layer beat correct-looking conjuncts on a page nobody opens, and the
   trade-off is only available in that direction. `tests/..._test.py` pins both halves.

**Determinism.** Same chunks in → byte-identical PDF out, so a content hash can tell the
uploader that nothing changed and a re-upload can be skipped. Verified byte-equal across
processes and across `PYTHONHASHSEED`. Two things make it hold and both are load-bearing:
the creation date is pinned to `_EPOCH` (fpdf2 otherwise stamps `now()`), and fpdf2's
`/ID` is derived from the document content plus that date rather than from randomness.
Font subsetting is a pure function of the characters used, so it varies with the input
and never between runs on the same input. Nothing here reads a clock, a UUID or an
environment variable.

**Layout, against the vendor's `chunk_size`.** `chunk_size` (default 512), `overlapping`
(default 128) and `similarity_top_k` (default 15) are request parameters we control
(`create.md:52-70`). Our own approved chunks are already semantic units capped at
`service.MAX_CHUNK_CHARS` (700), so the layout puts **one approved chunk per block**,
each block opening with its marker line and separated by a blank line and a rule of
`_SEPARATOR`. We therefore ask the uploader for `RECOMMENDED_CHUNK_SIZE` (768) rather
than the 512 default: at 512 every one of our 700-character chunks would be cut in two,
which is precisely the "split one fact mid-sentence" the block layout exists to avoid,
whereas 768 holds our largest ordinary chunk whole. `RECOMMENDED_OVERLAP` stays at the
vendor's 128 — overlap is what re-attaches a fact that does get cut.

⚠ **UNVERIFIED, and it decides whether 768 is right:** the vendor documents `overlapping`
in characters but says only "Chunk size for embedding model" for `chunk_size`, so whether
it counts characters or tokens is not stated on that page and is not asserted here. 768
is correct under the character reading. Under a token reading a 768-token node would weld
several of our facts together, which degrades retrieval precision but loses no text and
breaks nothing. Settle it by uploading and reading back what the vendor stored.

**Traceability is BEST-EFFORT and is not claimed as a guarantee.** Each block opens with
`[[KB <source-8>#<idx>]]`, so a retrieved passage can usually be traced to the approved
chunk it came from. What we cannot promise: the vendor re-chunks the extracted text with
its own splitter, and we do not know where it cuts. A block that survives whole carries
its marker; a block the vendor splits leaves the tail piece with no marker on it, and two
short adjacent blocks may be welded into one node carrying two markers. The marker is an
aid to an operator reading a retrieved passage, not an identifier the vendor preserves.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import TTFFont

#: The engine refuses a file over 20 MB (`create.md:41`).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

#: What the uploader should send as `chunk_size` / `overlapping`. See the module
#: docstring on why 768 and not the vendor's 512 default.
#:
#: ⚠ **THE WIRE DOES NOT SEND 768 TODAY, AND THAT IS DELIBERATE RATHER THAN DRIFT.**
#: `engine/bolna.py::KB_CHUNK_SIZE` sends the vendor's documented default, 512. The
#: argument for 768 above is sound under the reading that `chunk_size` counts
#: CHARACTERS — our chunks are capped at 700 (`kb/service.MAX_CHUNK_CHARS`), so 512
#: cuts every one of them in two — but the vendor's page says only *"Chunk size for
#: embedding model"* and never states the unit, while documenting `overlapping` in
#: characters. Under a TOKEN reading, 768 tokens is ~3,000 characters and welds several
#: approved facts into one node, which costs retrieval precision in the other direction.
#: Neither reading has been observed: `api.bolna.ai` is egress-blocked here and there is
#: no account (hard rule 12 — the premise is not verifiable from this container, so the
#: wire keeps the vendor's own default rather than moving on an inference).
#:
#: OPERATIONS §2 gate 43a settles it in one upload: send a document whose block
#: boundaries are known, read back what the vendor stored, and see where it cut. Whoever
#: runs that gate changes BOTH constants or neither.
RECOMMENDED_CHUNK_SIZE = 768
RECOMMENDED_OVERLAP = 128

#: Noto Sans Telugu Regular, the `full` build from the Noto project's own release repo
#: (github.com/notofonts/notofonts.github.io at 2ad4e55, path
#: `fonts/NotoSansTelugu/full/ttf/`), SIL Open Font License 1.1 — the licence text ships
#: beside it as `LICENSE-OFL-1.1.txt`.
#:
#: The `full` build, NOT the `hinted`/`unhinted` ones, and the difference is the whole
#: reason this file works. Measured with fontTools on 2026-09-01: `hinted` covers all 100
#: Telugu codepoints but only 39 of the 95 printable ASCII — it has **no Latin letters at
#: all**, so English and Tenglish ("Mee order ready ayyindi") would have vanished from
#: the text layer while Telugu looked fine. `full` covers 95/95 ASCII and 100/100 Telugu
#: in one file, plus ₹ (U+20B9), curly quotes and the punctuation a price list uses. One
#: font with both scripts also avoids a fallback chain, whose glyph resolution is one
#: more thing that could differ between runs.
FONT_PATH = Path(__file__).parent / "fonts" / "NotoSansTelugu-Regular.ttf"
_FONT_FAMILY = "notosanstelugu"

#: Any fixed instant works; it only has to be the SAME one every run. Chosen rather than
#: dropping the key because fpdf2 folds the creation date into the document `/ID`.
_EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)

# A4 at 72dpi, in points, with a generous margin: the geometry is fixed here rather than
# left to fpdf2's defaults so a library default change cannot silently reflow the text
# and move the content hash.
_PAGE_WIDTH_PT = 595.0
_PAGE_HEIGHT_PT = 842.0
_MARGIN_PT = 54.0
_LINE_HEIGHT_PT = 14.0
_FONT_SIZE_PT = 10.0

#: Between blocks. A visible rule rather than whitespace alone: whatever splitter the
#: vendor uses, a line of punctuation between two facts is a stronger hint of a boundary
#: than a blank line, and it costs one line per chunk.
_SEPARATOR = "-----"

#: Codepoints every renderable text may contain regardless of the font's cmap. The font
#: has no glyph for a newline or a tab and does not need one — fpdf2 consumes them as
#: layout, never as a glyph — so they must be exempt from the coverage check.
_LAYOUT_CODEPOINTS = frozenset({0x09, 0x0A, 0x0D})


class KnowledgePdfError(Exception):
    """Base for every refusal this module raises.

    Plain exceptions rather than `ProblemError`s: this module is pure and is called from
    a worker as readily as from a request, so it does not decide what a client is shown.
    The caller maps these to a problem+json response or to a failed job.
    """


class UnapprovedChunkError(KnowledgePdfError):
    """A chunk that is not approved-and-active was handed to the renderer.

    **Refused, not filtered.** Silently dropping it would be the same defect in a
    friendlier costume: the client's knowledge would be quietly short a fact and the
    upload would still report success. Reaching this means the caller's query is wrong,
    which is a bug to fix rather than a state to tolerate.
    """

    def __init__(self, marker: str) -> None:
        self.marker = marker
        super().__init__(
            f"chunk {marker} is not approved and active; only published knowledge may be rendered"
        )


class UnrenderableTextError(KnowledgePdfError):
    """The text contains characters the embedded font cannot draw.

    Raised rather than letting fpdf2 warn-and-drop them (module docstring, failure 2).
    Carries the offending codepoints so an operator can tell a client exactly which
    characters to remove — "your Hindi paragraph" is actionable, "upload failed" is not.
    The text itself is NOT carried and never logged: it is client content (hard rule 6).
    """

    def __init__(self, marker: str, codepoints: Sequence[int]) -> None:
        self.marker = marker
        self.codepoints = tuple(codepoints)
        rendered = ", ".join(f"U+{cp:04X}" for cp in self.codepoints)
        super().__init__(
            f"chunk {marker} contains {len(self.codepoints)} character(s) the Telugu "
            f"knowledge font cannot render: {rendered}. The knowledge base font covers "
            "Telugu and Latin; text in another script must be removed or transliterated."
        )


class KnowledgePdfTooLargeError(KnowledgePdfError):
    """The rendered PDF exceeds the engine's 20 MB ceiling (`create.md:41`).

    **Nothing is truncated.** Dropping the tail would hand the client an agent that
    silently does not know its own last N facts, which is the failure this whole module
    is written against. The caller's answer is to split the agent's knowledge across
    more than one knowledgebase — the engine addresses knowledgebases by `rag_id`, so
    several are attachable — and the operator-facing remediation says so.
    """

    def __init__(self, size_bytes: int, chunk_count: int) -> None:
        self.size_bytes = size_bytes
        self.chunk_count = chunk_count
        super().__init__(
            f"rendered knowledge PDF is {size_bytes} bytes over {chunk_count} approved "
            f"chunk(s), above the engine's {MAX_UPLOAD_BYTES}-byte limit. Nothing was "
            "truncated: split this agent's knowledge into more than one source so each "
            "renders under the ceiling."
        )


class EmptyKnowledgeError(KnowledgePdfError):
    """There is nothing approved to render.

    A zero-fact PDF is accepted by the engine and retrieves nothing, so it is
    indistinguishable on the wire from the silent failure above. Refusing here means the
    caller never attaches an empty knowledgebase to a live agent.
    """

    def __init__(self) -> None:
        super().__init__("no approved, active knowledge chunks to render")


@dataclass(frozen=True, slots=True)
class ApprovedChunk:
    """One row of `kb_documents` with the two facts about its source that gate it.

    Deliberately not an ORM row and deliberately carrying `approved`/`is_active` rather
    than trusting the caller's WHERE clause: the gate is a product property (`kb/
    __init__.py`), so the renderer re-asserts it on data it can see instead of inheriting
    it from a query it cannot.
    """

    source_id: UUID
    source_name: str
    idx: int
    content: str
    approved: bool
    is_active: bool

    @property
    def marker(self) -> str:
        """The stable per-chunk marker. `source_id` is a uuid_v7, whose first 8 hex
        characters are a timestamp prefix and therefore NOT unique on their own — the
        marker is unique within one agent's PDF (where a source appears once) and is a
        pointer for a human, not a key. `idx` is zero-padded so the markers sort.
        """
        return f"[[KB {self.source_id.hex[:8]}#{self.idx:04d}]]"


@dataclass(frozen=True, slots=True)
class RenderedKnowledgePdf:
    """The bytes plus everything the uploader needs and must not re-derive."""

    content: bytes
    #: Over `content`. The uploader compares this against what it last pushed and skips
    #: an unchanged re-upload — which is the reason determinism is a hard requirement
    #: here rather than a nicety.
    sha256: str
    #: In document order, so a retrieved marker can be looked up.
    markers: tuple[str, ...]
    chunk_size: int
    overlapping: int

    @property
    def size_bytes(self) -> int:
        return len(self.content)


def _charset_of(pdf: FPDF) -> frozenset[int]:
    """Codepoints the loaded font can actually draw.

    Read from THE FONT OBJECT THIS DOCUMENT WILL DRAW WITH, not from a second parse of
    the file on disk. Asking fontTools separately would answer a subtly different
    question — "what does the file contain" rather than "what will fpdf2 draw" — and the
    two could drift apart on a library upgrade without anything failing, which is the
    class of silent divergence this whole module is written against. It also keeps
    fontTools (which ships no `py.typed`) out of our import graph.
    """
    font = pdf.fonts[_FONT_FAMILY.lower()]
    # Two invariants of `_new_document`, asserted rather than branched on because neither
    # is a state to recover from — each means the document would draw text that does not
    # survive extraction, and each is invisible until someone reads the PDF back.
    # A `CoreFont` would mean the embedded TrueType never loaded and we are about to draw
    # with a base-14 font that has no Telugu at all: the original silent failure exactly.
    # Shaping mangles the `ToUnicode` mapping for Telugu conjuncts (docstring, failure 3);
    # `text_shaping` is None when it is off, and a feature dict once enabled.
    assert isinstance(font, TTFFont), "the embedded Telugu font did not load"
    assert pdf.text_shaping is None, "text shaping corrupts the extracted text"
    return frozenset(font.cmap)


def _require_font_coverage(covered: frozenset[int], marker: str, text: str) -> None:
    missing = sorted({ord(ch) for ch in text} - covered - _LAYOUT_CODEPOINTS)
    if missing:
        raise UnrenderableTextError(marker, missing)


def _normalise(text: str) -> str:
    """Collapse the whitespace a paste brings in, keeping paragraph breaks.

    Runs of blank lines become one, trailing spaces go, and CRLF becomes LF — all three
    are invisible on a page and all three change the byte hash, so a client re-pasting
    the same text with different line endings would otherwise force a needless re-upload.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _new_document() -> FPDF:
    pdf = FPDF(orientation="portrait", format=(_PAGE_WIDTH_PT, _PAGE_HEIGHT_PT), unit="pt")
    pdf.set_creation_date(_EPOCH)
    pdf.set_margins(left=_MARGIN_PT, top=_MARGIN_PT, right=_MARGIN_PT)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_PT)
    pdf.add_font(_FONT_FAMILY, style="", fname=str(FONT_PATH))
    pdf.set_font(_FONT_FAMILY, size=_FONT_SIZE_PT)
    # Not set: title, author, subject, producer. They would carry a tenant's name into a
    # file that leaves our infrastructure, and the vendor indexes the page text, not the
    # metadata — so they would cost privacy surface and buy nothing.
    return pdf


def render_knowledge_pdf(chunks: Sequence[ApprovedChunk]) -> RenderedKnowledgePdf:
    """Render approved, active chunks into one PDF for the engine's knowledgebase.

    Pure and deterministic: no clock, no randomness, no DB, no network. Chunks are
    rendered in the order given — the caller decides reading order (the KB's own
    accessors order by source name, then `idx`) so this function has no opinion to
    disagree with.

    Raises `UnapprovedChunkError`, `UnrenderableTextError`, `EmptyKnowledgeError` or
    `KnowledgePdfTooLargeError`; every one of them is a refusal to produce a file that
    would upload cleanly and then under-serve a live call.
    """
    # The document is built before anything is validated, because the font it loads is
    # what the coverage check has to be asked about. Nothing is drawn until every chunk
    # has passed, so a refusal never leaves a half-written file behind.
    pdf = _new_document()
    covered = _charset_of(pdf)

    renderable: list[tuple[ApprovedChunk, str]] = []
    for chunk in chunks:
        if not (chunk.approved and chunk.is_active):
            raise UnapprovedChunkError(chunk.marker)
        body = _normalise(chunk.content)
        if not body:
            # An empty approved chunk is not an error — `submit_source` can produce one
            # from a source that is all whitespace — but it must not become a block, or
            # the PDF grows a marker with no fact under it for retrieval to return.
            continue
        _require_font_coverage(covered, chunk.marker, chunk.source_name)
        _require_font_coverage(covered, chunk.marker, body)
        renderable.append((chunk, body))

    if not renderable:
        raise EmptyKnowledgeError()

    pdf.add_page()
    width = _PAGE_WIDTH_PT - (2 * _MARGIN_PT)
    for position, (chunk, body) in enumerate(renderable):
        if position:
            _write(pdf, width, "")
            _write(pdf, width, _SEPARATOR)
            _write(pdf, width, "")
        # Marker and source name on their own lines above the fact: the vendor's
        # splitter, whatever it is, cuts on text order, so anything that must travel
        # with the fact has to sit immediately before it.
        _write(pdf, width, f"{chunk.marker} {chunk.source_name}")
        _write(pdf, width, body)

    content = bytes(pdf.output())
    if len(content) > MAX_UPLOAD_BYTES:
        raise KnowledgePdfTooLargeError(len(content), len(renderable))

    return RenderedKnowledgePdf(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        markers=tuple(chunk.marker for chunk, _ in renderable),
        chunk_size=RECOMMENDED_CHUNK_SIZE,
        overlapping=RECOMMENDED_OVERLAP,
    )


def _write(pdf: FPDF, width: float, text: str) -> None:
    """One block of text, wrapped, cursor left at the start of the next line.

    `multi_cell` with an empty string draws nothing and does not advance, so a blank
    spacer line is written as a space.
    """
    pdf.multi_cell(
        w=width,
        h=_LINE_HEIGHT_PT,
        text=text or " ",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
