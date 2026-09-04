"""What a client actually has → text the knowledge pipeline already knows how to publish.

THE SEAM, IN ONE SENTENCE: an uploaded object plus a declared kind goes in, and either
`ExtractedText` comes out or a `DocumentRefusedError` a client can act on does. Nothing here
touches storage, the database, a route or the engine — the modules that do are
`apps/workers/document_text.py` (DOCX / TXT / CSV / XLSX) and
`apps/workers/document_ocr.py` (photographs, through a model leg we already hold).

⚠ **THIS SEAM PRODUCES TEXT, NOT A PDF, AND THE BRIEF THAT ASKED FOR A PDF WAS WORKING
FROM A PREMISE THIS REPOSITORY HAD ALREADY CLOSED.** The reasoning is recorded here
rather than in a report because the next reader will re-derive it otherwise.

The engine's knowledge-base API does accept exactly a PDF (max 20 MB) or a URL
(VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/knowledgebase/
create.md:29-52`). But **the client's file is not what we send it.** The pipeline is
`kb/service.py`'s, and it has an approval gate in the middle of it:

    client submits TEXT → chunk (`kb.service.chunk_text`) → PREVIEW → a human approves
    → version bump → `kb/pdf_render.render_knowledge_pdf` → engine → T0 → live

`render_knowledge_pdf` is where this repository's ONE text→PDF conversion lives, it is
deterministic so the uploader can skip an unchanged re-upload, it embeds a Telugu+Latin
font and it refuses text the font cannot draw. Converting a DOCX to a PDF at INGEST would
therefore do two wrong things at once:

1. **A second way to make a PDF**, when the repo already has one that the whole publish
   path (digest guard, size ceiling, marker traceability) is built around. Two ways to do
   one thing is a defect here even when both work.
2. **Worse: it would route the client's own bytes around the human approval gate.** The
   gate is not decoration — an agent speaks on the client's behalf under their PE
   registration, so a person reads the wording before it can be said on a phone call. A
   PDF made from an unread upload and pushed to the engine is knowledge nobody approved.

So the conversion this lane owns is `→ text`, and the PDF stays where it is. What the
upload lane needs from us is a string it can hand to `kb.service.submit_source(body=...)`.

WHAT THE REFUSALS ARE FOR. Every failure here is reachable by a client uploading a file,
so each one carries `title` / `detail` / `remediation` written for a shop owner rather
than an engineer, and the API lane maps them onto RFC-9457 problem+json. They are plain
exceptions rather than `ProblemError` because this package may not import app code
(import-linter contract "shared package imports no app code").

WHAT IS NEVER IN A REFUSAL, A LOG LINE OR A FIELD HERE: the document's text, a cell's
contents, or the uploaded filename. An uploaded document is the client's business data
and routinely carries their customers' names and numbers (hard rule 6). Counts, sizes,
kinds and outcomes are what these objects carry, and that is deliberate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

__all__ = [
    "CONVERTIBLE_KINDS",
    "MAX_EXTRACTED_CHARS",
    "MAX_IMAGE_BYTES",
    "MAX_OCR_IMAGES",
    "MAX_OOXML_ENTRIES",
    "MAX_OOXML_EXPANDED_BYTES",
    "MAX_ROWS_PER_TABLE",
    "MAX_SOURCE_BYTES",
    "OCR_IMAGE_MIME_TYPES",
    "DocumentBombError",
    "DocumentEmptyError",
    "DocumentRefusedError",
    "DocumentTooLargeError",
    "DocumentUnreadableError",
    "ExtractedText",
    "IngestKind",
    "OcrUnavailableError",
    "OcrUnusableError",
    "TextProvenance",
    "UnsupportedKindError",
    "serialise_row",
]

#: The kinds this lane converts. NOT a list of what a client may upload — `pdf` and `url`
#: are things the upload lane handles without us, and are absent here for that reason
#: rather than by oversight.
IngestKind = Literal["docx", "txt", "csv", "xlsx", "image"]

CONVERTIBLE_KINDS: Final[frozenset[str]] = frozenset(
    {"docx", "txt", "csv", "xlsx", "image"},
)

#: How the text was obtained, and it is the field the confirmation gate turns on.
#: `parsed` means a deterministic reader took it out of a file format that stores it as
#: text; `ocr` means a model looked at a picture and told us what it thought it said.
#: Those are different epistemic states and the product treats them differently.
TextProvenance = Literal["parsed", "ocr"]


# --- CEILINGS ------------------------------------------------------------------------
#
# Every one of these is OURS, derived from something in this tree, and none is a vendor
# limit dressed up as one. They exist because these are files from the internet: a
# malformed or hostile document has to fail closed with a message rather than crash a
# worker or hold one forever (hard rule 3's discipline, applied to a worker's slot).

#: The largest upload this lane will read at all. Matched to the engine's own 20 MB
#: knowledge-base ceiling — not because this file is sent there (it is not, see the
#: module docstring) but because a source that could never fit the published document is
#: one to refuse at the door rather than after a model call.
MAX_SOURCE_BYTES: Final = 20 * 1024 * 1024

#: DOCX and XLSX are ZIP containers, so both are decompression-bomb shaped: a 40 kB file
#: whose entries declare 4 GB is a worker's memory, and `ZipFile.read()` will happily
#: try. The pre-flight sums the DECLARED uncompressed sizes and refuses over this before
#: a single entry is read. A lying header does not defeat it: the readers are also
#: bounded on what they produce (`MAX_EXTRACTED_CHARS`, `MAX_ROWS_PER_TABLE`), so the
#: worst a lie buys is one bounded read.
MAX_OOXML_EXPANDED_BYTES: Final = 256 * 1024 * 1024

#: Entry count is the OTHER zip bomb: a few million tiny members costs nothing to
#: declare and everything to enumerate. A real Word document has tens of entries and a
#: heavily-illustrated workbook a few hundred.
MAX_OOXML_ENTRIES: Final = 4_096

#: Rows read from ONE sheet or ONE table. Above this the source is a database export
#: rather than knowledge an agent should recite, and a human is being asked to approve
#: something they cannot read.
MAX_ROWS_PER_TABLE: Final = 5_000

#: The extracted text a single source may carry.
#:
#: DERIVED FROM THE APPROVAL GATE, not from a byte budget, and that is why it is this
#: small. Someone has to READ this before it reaches a phone call (`kb/service.py`'s
#: preview → approve step); 200,000 characters is already something like seventy pages of
#: prose. A ceiling that let a client submit a novel would produce a gate everybody
#: rubber-stamps, which is worse than no gate. It also keeps the eventual rendered PDF
#: comfortably under the engine's 20 MB without anyone having to reason about fonts.
MAX_EXTRACTED_CHARS: Final = 200_000

#: Images sent to the OCR leg for ONE source, and the COST bound of this lane. See
#: `apps/workers/document_ocr.py` for the per-page arithmetic this number is set from.
MAX_OCR_IMAGES: Final = 20

#: One photograph. Phone cameras produce 3-8 MB JPEGs; 12 MB is a comfortable ceiling
#: that still leaves the request well inside anything a provider is likely to accept, and
#: refusing above it costs a client one retry with a smaller photo rather than an opaque
#: provider error.
MAX_IMAGE_BYTES: Final = 12 * 1024 * 1024

#: Image types the OCR leg accepts.
#:
#: EVIDENCE: VERIFIED-VENDOR-API. Google's own Gemini Developer API discovery document
#: (`https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta`,
#: revision 20260904, fetched from this container 4 Sep 2026) documents `Blob.mimeType`
#: as accepting `image/png, image/jpeg, image/jpg, image/webp, image/heic, image/heif,
#: image/gif, image/avif`.
#:
#: `image/gif` IS DELIBERATELY EXCLUDED from what we offer even though the vendor takes
#: it: an animated GIF is a video wearing an image's MIME type, and "which frame did it
#: read" is a question a client cannot answer about their own upload. `image/heic` and
#: `image/heif` ARE included — that is what an iPhone produces by default, and refusing
#: it would refuse the single most likely photograph in this market.
OCR_IMAGE_MIME_TYPES: Final[frozenset[str]] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/avif",
    },
)


# --- WHAT COMES OUT ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """One converted upload: the text, how we got it, and whether a human must confirm it.

    `needs_confirmation` IS THE PRODUCT DECISION, and it is a field rather than a
    computed property so that a future provenance cannot quietly default to False.
    Everything read by OCR requires the person who uploaded it to look at the extracted
    text and say "yes, that is my menu" before it can be submitted as knowledge — see
    `apps/workers/document_ocr.py` for why no heuristic is allowed to stand in for that.

    `unit_count` / `unit_name` are what a cost line and an operator screen need ("4
    pages", "312 rows", "2 sheets") without anybody having to look at the content.

    THE TOKEN COUNTS ARE HERE AND THE RUPEES ARE NOT. Money is `apps/api/billing`'s, it
    is NUMERIC INR (hard rule 7), and the price of a model comes from
    `billing/rates.llm_inr_per_ktok`, which raises on a model nobody has attested. This
    dataclass reports what was consumed; the caller that owns the ledger prices it.
    `prompt_tokens is None` means the provider did not tell us, which throughout this
    repository means "we do not know what this cost" and never "it was free".
    """

    text: str
    kind: IngestKind
    provenance: TextProvenance
    unit_count: int
    unit_name: str
    needs_confirmation: bool
    #: The model identifier, when a model was involved. `None` for a deterministic parse.
    model: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    #: Per-image outcomes for a multi-image source, so an operator can see that page 3 of
    #: 5 was discarded without anyone opening the document. Codes only, never text.
    discarded: tuple[str, ...] = field(default_factory=tuple)


# --- REFUSALS ------------------------------------------------------------------------


class DocumentRefusedError(Exception):
    """A refusal a client can act on, in the four parts a problem+json response needs.

    `code` is the stable machine string (it becomes problem+json's `code`), and it is
    what a test asserts on; the three prose fields are what a shop owner reads. Written
    for them: "We could not read that spreadsheet" and not "XLSX parse error".
    """

    def __init__(self, *, code: str, title: str, detail: str, remediation: str) -> None:
        self.code = code
        self.title = title
        self.detail = detail
        self.remediation = remediation
        super().__init__(f"{code}: {title}")


class UnsupportedKindError(DocumentRefusedError):
    """A kind this lane does not convert."""

    def __init__(self, kind: str) -> None:
        super().__init__(
            code="ingest_kind_unsupported",
            title="We cannot read that kind of file",
            detail=("That file type is not one we can turn into knowledge for your agent yet."),
            remediation=(
                "Word documents, plain text, spreadsheets, CSV files and photographs of "
                "printed pages all work. Save it as one of those and upload it again."
            ),
        )
        self.kind = kind


class DocumentTooLargeError(DocumentRefusedError):
    """Over a ceiling. Carries the numbers, never the file."""

    def __init__(self, *, size: int, limit: int, unit: str = "bytes") -> None:
        super().__init__(
            code="ingest_too_large",
            title="That file is too big",
            detail=(f"We read up to {limit:,} {unit} in one upload and this one is {size:,}."),
            remediation=(
                "Split it into smaller documents — one per topic works best, because "
                "your agent finds an answer faster in a short document than a long one."
            ),
        )
        self.size = size
        self.limit = limit


class DocumentBombError(DocumentRefusedError):
    """A container whose declared contents are far larger than the file itself.

    SEPARATE FROM `DocumentTooLargeError` because they are different events with the same
    symptom. A large file is a client with a lot to say; a 40 kB file declaring 4 GB of
    contents is not, and an operator reading a log wants to be able to tell them apart.
    """

    def __init__(self, *, declared: int, entries: int) -> None:
        super().__init__(
            code="ingest_container_refused",
            title="We could not open that file safely",
            detail=(
                "The file says it contains far more than a document of its size should, "
                "so we stopped rather than open it."
            ),
            remediation=(
                "Open it in Word or Excel, save a fresh copy, and upload that. If it "
                "still fails, send us the file and we will look at it."
            ),
        )
        self.declared = declared
        self.entries = entries


class DocumentUnreadableError(DocumentRefusedError):
    """Malformed, encrypted, or not the format its kind claims.

    `reason` is an OPERATOR string (a short code, never content) so a log line can say
    which of a dozen ways it failed without the client's prose reaching a log.
    """

    def __init__(self, *, reason: str, detail: str, remediation: str) -> None:
        super().__init__(
            code="ingest_unreadable",
            title="We could not read that file",
            detail=detail,
            remediation=remediation,
        )
        self.reason = reason


class DocumentEmptyError(DocumentRefusedError):
    """The file opened and held no text.

    A REFUSAL AND NOT AN EMPTY SUCCESS, for `kb/pdf_render`'s reason one level down: an
    empty knowledge source uploads cleanly, reports success and retrieves nothing, and
    the client discovers it on a live call.
    """

    def __init__(self, *, kind: str) -> None:
        super().__init__(
            code="ingest_empty",
            title="There was no text in that file",
            detail=(
                "We opened it and found nothing your agent could say. It may be a "
                "picture-only document, or the text may be inside an image."
            ),
            remediation=(
                "If it is a scan or a photograph, upload it as a photo instead and we "
                "will read the text out of it for you."
            ),
        )
        self.kind = kind


class OcrUnusableError(DocumentRefusedError):
    """The OCR ran and what came back must not be shown to anybody as their document.

    This is the founder's rule — *"if the OCR is not accurate we will discard that image
    file"* — as a closed set of machine-checkable conditions. It is a FILTER IN FRONT OF
    the human confirmation, never a substitute for it: see `document_ocr.py`.
    """

    def __init__(self, *, reason: str, images: int) -> None:
        super().__init__(
            code="ingest_ocr_unusable",
            title="We could not read the writing in that photo",
            detail=(
                "We looked at the photo and could not get text out of it we would trust "
                "your agent to repeat, so we have not kept it."
            ),
            remediation=(
                "Take the photo again in better light, straight on and close enough that "
                "the writing fills the frame. Typed or printed pages read best."
            ),
        )
        self.reason = reason
        self.images = images


class OcrUnavailableError(DocumentRefusedError):
    """No leg is configured to read photographs on this deployment.

    OPERATOR-CAUSED, CLIENT-FACING, and the two audiences get different sentences.
    `reason` says which of the three conditions failed (the credential, the price
    attestation, the model) so an operator can fix it in the ops console; the client is
    told the truth without being told our vendor arrangements.
    """

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            code="ingest_ocr_unavailable",
            title="Reading photographs is switched off right now",
            detail=("We cannot read text out of photographs on this account at the moment."),
            remediation=(
                "Type the wording in, or upload it as a Word document, a spreadsheet or "
                "a text file. We will let you know when photographs are available."
            ),
        )
        self.reason = reason


# --- THE ONE ROW RENDERER ------------------------------------------------------------

#: Between a column's name and its value, and between one column and the next.
#:
#: ASCII, DELIBERATELY. The published document is drawn by `kb/pdf_render.py` with one
#: embedded font, and a character that font has no glyph for is a hard refusal at publish
#: time — the pretty separators (`·`, `—`, `→`) are exactly the ones a Telugu font is
#: least likely to carry. A semicolon costs nothing and cannot fail.
_FIELD_JOIN: Final = ": "
_COLUMN_JOIN: Final = "; "


def serialise_row(headers: Sequence[str], values: Iterable[object]) -> str:
    """One table row as ONE self-describing line: `Idli: 40; Category: Tiffins`.

    **THIS IS THE MOST CONSEQUENTIAL DECISION IN THIS LANE, so the argument is here and
    not in a commit message.** A price list is the thing an Indian SMB most wants their
    agent to know, and it arrives as a spreadsheet. The obvious move — render it as a
    table, in a PDF, looking like the client's file — retrieves badly, and the reason is
    structural rather than aesthetic.

    Retrieval happens over CHUNKS. Ours are paragraph-aware with a 700-character cap
    (`kb/service.MAX_CHUNK_CHARS`), and the engine then re-chunks our published document
    again with a splitter of its own we do not control (`kb/pdf_render.py` on
    `chunk_size`). A table survives neither pass: the header row appears ONCE, at the
    top, and every chunk after the first is a grid of bare values. "Paneer butter masala"
    and "260" end up in different chunks from the word "Price", so the one question the
    client actually cares about — *how much is the paneer butter masala* — retrieves a
    fragment that cannot answer it. Nothing is lost in the file; the association is lost
    in the CHUNKING, which is where retrieval lives.

    A row rendered as its own line carries its own headers, so every chunk boundary falls
    between two complete facts and each retrieved unit is answerable on its own. It is
    also what the agent has to SAY: the reply is "paneer butter masala is 260 rupees",
    which is nearer to this line than to a column of digits.

    REJECTED, and why each:

    * **A visual table in the PDF** (fpdf2 has one) — the failure above, plus it makes
      the document's usefulness depend on the vendor's splitter, which we cannot see.
    * **A Markdown pipe table** — same header-binding failure, and it spends tokens on
      pipes and dashes in a document whose size is capped.
    * **The raw CSV lines** — same again; `40,Tiffins,yes` is not a fact.
    * **One line per CELL** (`Idli price: 40`) — self-describing, but it explodes a 300-row
      sheet into 1,500 chunks and separates a dish's price from its availability, which
      is the same association failure in the other direction.

    Values are stringified and blanks are dropped: an empty cell contributes nothing
    rather than `Notes: `, which would be a fact about nothing for the retriever to match
    on. A row whose values are ALL blank returns the empty string, and the caller skips it.
    """
    parts: list[str] = []
    for index, value in enumerate(values):
        rendered = "" if value is None else str(value).strip()
        if not rendered:
            continue
        header = headers[index].strip() if index < len(headers) else ""
        parts.append(f"{header}{_FIELD_JOIN}{rendered}" if header else rendered)
    return _COLUMN_JOIN.join(parts)
