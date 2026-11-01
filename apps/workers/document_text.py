"""DOCX / TXT / CSV / XLSX → the text a client's agent will learn from.

Pure and synchronous: bytes and a declared kind go in, `ExtractedText` or a
`DocumentRefusedError` comes out. No storage, no database, no network, no clock. The upload
lane owns the object-storage read either side of it; `calevate_shared.document_ingest`
carries the seam and the ceilings, and its module docstring carries the one thing worth
reading before this file — **the conversion is to TEXT, not to a PDF**, because
`kb/pdf_render.py` already owns text→PDF on the far side of the human approval gate.

WHY NO NEW SERVICE. The obvious way to convert Office documents is LibreOffice headless,
and it is refused before it is argued: it is a new deployable, a new image, a new restore
drill and a ~400 MB runtime in a worker whose slot budget is measured (CLAUDE.md's "Do
NOT"). Nothing here needs it — DOCX and XLSX are ZIP archives of XML, and the text is
already text inside them. What we would be renting LibreOffice for is LAYOUT, which is
the one thing a retrieval pipeline actively does not want (see `serialise_row`).

THE PARSERS, AND THE ONE DEPENDENCY

* **DOCX is read directly** — `zipfile` + `xml.etree`, about eighty lines. The rejected
  alternative is `python-docx`, which is the standard library for this and is the right
  default answer; it is refused here for a specific reason and not on principle. It
  requires `lxml`, a compiled C extension with a vendored libxml2, and the whole of what
  we need from it is "walk the paragraphs of `word/document.xml`". Buying a C parser and
  its supply-chain surface (hard rule 9) for an eight-element XML walk is the wrong trade
  — and, decisively, python-docx does its own `ZipFile.read()` with no bomb ceiling, so
  we would have to wrap it in exactly the pre-flight below anyway and would then own the
  safety property without owning the parse.
* **XLSX uses `openpyxl`** — and the asymmetry is deliberate. A spreadsheet cell is not
  text: its value is a number plus a FORMAT, and "is 45994 a quantity or is it 3 October
  2025" is decided by a number-format code and the 1900/1904 epoch flag. Getting that
  wrong turns a client's "offer valid until" column into a five-digit number, silently.
  openpyxl is pure Python, streams in `read_only` mode, and its only dependency is
  `et-xmlfile` — both wheels, neither with a build hook (lockfile diff read before
  adding, hard rule 9).

UNTRUSTED INPUT, WHICH IS THE POSTURE THROUGHOUT. These are files from the internet.
Three defences, none of them optional:

1. **Zip bombs.** Both OOXML formats are ZIP. `_open_ooxml` sums the DECLARED
   uncompressed sizes and the entry count before reading a byte, and refuses over
   `MAX_OOXML_EXPANDED_BYTES` / `MAX_OOXML_ENTRIES`. A header can lie about its size, so
   the readers are bounded on OUTPUT too (`MAX_EXTRACTED_CHARS`, `MAX_ROWS_PER_TABLE`) —
   a lie buys one bounded read, not a worker's memory.
2. **XML entity expansion** ("billion laughs"). `xml.etree.ElementTree` is documented as
   vulnerable to it, and the usual answer is `defusedxml` — a dependency for one check.
   Quadratic and exponential entity blowups both require entity DEFINITIONS, which
   require an internal DTD subset, and no word processor on earth emits a `<!DOCTYPE` in
   `word/document.xml`. `_parse_part` refuses the declaration outright, found by expat
   in a prolog-only pass (`_declares_doctype`) before the tree parser sees the part,
   which closes the class rather than one instance.
3. **Time.** There is no I/O here at all, so there is nothing to hang on: every loop is
   bounded by a ceiling above, and the worst input costs a bounded parse.

PICTURES (D-956). A DOCX's inline pictures and an XLSX's sheet pictures are found here too,
through the same pre-flighted archive and the same DOCTYPE-guarded parse, and handed to a
`document_pictures.PictureCollector` with the block they follow. `read_document` stops there,
still with no network: the worker reads the pictures (`document_pictures.read_pictures`) and
`assemble` puts their words after their paragraph or sheet. A picture is extra to the text,
so a damaged picture part costs that picture and never the document.

NOTHING IN THIS MODULE LOGS. It is handed a client's business document, routinely
carrying their customers' personal data (hard rule 6). It has no ids to log and its
refusals carry counts and codes, never content — so the caller, which does have ids,
does the logging.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import posixpath
import re
import zipfile
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final
from xml.etree import ElementTree
from xml.parsers import expat

import openpyxl
from calevate_shared.document_ingest import (
    MAX_EXTRACTED_CHARS,
    MAX_OOXML_ENTRIES,
    MAX_OOXML_EXPANDED_BYTES,
    MAX_ROWS_PER_TABLE,
    MAX_SOURCE_BYTES,
    DocumentBombError,
    DocumentEmptyError,
    DocumentRefusedError,
    DocumentTooLargeError,
    DocumentUnreadableError,
    ExtractedText,
    IngestKind,
    UnsupportedKindError,
    serialise_row,
)
from openpyxl.utils.exceptions import InvalidFileException

from apps.workers.document_pictures import PictureCollector

#: WordprocessingML's main namespace, the one the body text needs.
_W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
#: The namespaces a picture is reached through: a DrawingML `a:blip r:embed` (or a legacy
#: VML `v:imagedata r:id`) names a relationship, and the part's `.rels` names the media file.
_R: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A: Final = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V: Final = "{urn:schemas-microsoft-com:vml}"
_S: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_PACKAGE_REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"

#: The one part of a .docx that holds the body text. Headers, footers and footnotes live
#: in sibling parts and are DELIBERATELY not read: a page header repeated on forty pages
#: becomes forty copies of the client's address in a retrieval corpus, which is noise the
#: chunker then has to be defended from.
_DOCX_BODY_PART: Final = "word/document.xml"


class _DoctypeDeclaredError(Exception):
    """Raised from inside expat the moment the part opens a DOCTYPE."""


class _PrologEndedError(Exception):
    """Raised at the root element: no DOCTYPE can follow it, so the scan stops there."""


def _declares_doctype(raw: bytes) -> bool:
    """True if this XML part declares a DOCTYPE, decided by expat itself.

    A byte search for `<!DOCTYPE` was the earlier check, over the first 8 kB, and it
    missed two spellings expat accepts: a prolog padded past the window with a comment or
    a processing instruction, and a part encoded as UTF-16, where the declaration is not
    those bytes at all. Asking the parser that will read the part closes both, because
    it is the parser's own reading of the encoding and the prolog. The scan stops at the
    root element, so it costs a prolog, not a second parse of the document.
    """
    parser = expat.ParserCreate()

    def on_doctype(*_: object) -> None:
        raise _DoctypeDeclaredError

    def on_element(*_: object) -> None:
        raise _PrologEndedError

    parser.StartDoctypeDeclHandler = on_doctype
    parser.StartElementHandler = on_element
    try:
        parser.Parse(raw, True)
    except _DoctypeDeclaredError:
        return True
    except (_PrologEndedError, expat.ExpatError):
        # A malformed part is refused by the real parse below as `malformed_xml`.
        return False
    return False


#: Characters a word processor emits as LAYOUT that the knowledge gate then refuses as
#: invisible controls (`kb/service._FORBIDDEN_CODEPOINTS` bans C0 except tab/LF/CR). They
#: are line and page breaks by definition, so they become newlines here rather than an
#: unexplainable refusal three steps later on a perfectly ordinary Word file.
_LAYOUT_CONTROLS: Final = str.maketrans({"\x0b": "\n", "\x0c": "\n", "\xa0": " "})


@dataclass(slots=True)
class DocumentParts:
    """A document read as far as no network is needed: its blocks of text in order, and
    the pictures that sit among them, each anchored to the block it follows."""

    kind: IngestKind
    blocks: list[str]
    unit_count: int
    unit_name: str
    pictures: PictureCollector = field(default_factory=PictureCollector)
    #: For a block with no text of its own (a sheet holding only pictures): the line its
    #: pictures' words are put under, so a sheet name still leads them.
    headings: dict[int, str] = field(default_factory=dict)


def extract_document(data: bytes, kind: IngestKind) -> ExtractedText:
    """One uploaded object → its text, pictures left unread. Raises `DocumentRefusedError`
    and nothing else."""
    return assemble(read_document(data, kind), {})


def read_document(data: bytes, kind: IngestKind) -> DocumentParts:
    """One uploaded object → its blocks and pictures. Raises `DocumentRefusedError`.

    The size gate is FIRST, before any parser sees the bytes, because every ceiling below
    it assumes an input of bounded size.
    """
    if len(data) > MAX_SOURCE_BYTES:
        raise DocumentTooLargeError(size=len(data), limit=MAX_SOURCE_BYTES)

    if kind == "txt":
        return DocumentParts(kind, [_clean(_decode(data))], 1, "document")
    if kind == "csv":
        return _extract_csv(data)
    if kind == "docx":
        return _extract_docx(data)
    if kind == "xlsx":
        return _extract_xlsx(data)
    # `image` is the OCR lane's (`document_ocr.py`); anything else never had a reader.
    raise UnsupportedKindError(kind)


def assemble(parts: DocumentParts, pictures: Mapping[int, Sequence[str]]) -> ExtractedText:
    """The document's text with each picture's words (`document_pictures.picture_block`)
    after the block it follows; anchor -1 is before the first block."""
    out = list(pictures.get(-1, ()))
    for index, block in enumerate(parts.blocks):
        read = pictures.get(index, ())
        if block:
            out.append(block)
        elif read and index in parts.headings:
            out.append(parts.headings[index])
        out.extend(read)
    return _finish(
        _clean("\n\n".join(out)),
        kind=parts.kind,
        unit_count=parts.unit_count,
        unit_name=parts.unit_name,
        has_pictures=any(pictures.values()),
    )


# --- SHARED PLUMBING -----------------------------------------------------------------


def _finish(
    text: str, *, kind: IngestKind, unit_count: int, unit_name: str, has_pictures: bool = False
) -> ExtractedText:
    """The two checks every parser owes, in one place so none of them can skip one."""
    if not text:
        raise DocumentEmptyError(kind=kind)
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentTooLargeError(size=len(text), limit=MAX_EXTRACTED_CHARS, unit="characters")
    return ExtractedText(
        text=text,
        kind=kind,
        provenance="parsed",
        unit_count=unit_count,
        unit_name=unit_name,
        # A deterministic reader took text that was already text out of a container. There
        # is nothing for a human to CONFIRM that the approval gate does not already ask —
        # unlike OCR, where the question is "did the machine read this correctly at all".
        # Words read off a picture inside it are a model's reading, and say so.
        needs_confirmation=has_pictures,
    )


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """A part's relationships: id → (type, path in the archive). External targets (a linked
    picture on somebody's server) are left out: we read what is inside the file only."""
    folder, name = posixpath.split(part)
    rels = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels not in archive.namelist():
        return {}
    try:
        root = _parse_part(archive, rels, what="document")
    except DocumentRefusedError:
        return {}
    found: dict[str, tuple[str, str]] = {}
    for rel in root.iter(f"{_PACKAGE_REL}Relationship"):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External" or not target:
            continue
        path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(folder, target))
        )
        found[rel.get("Id") or ""] = (rel.get("Type") or "", path)
    return found


def _pictures_in(
    element: ElementTree.Element, rels: Mapping[str, tuple[str, str]]
) -> Iterator[str]:
    """The media parts `element` shows, in document order."""
    for node in element.iter():
        if node.tag == f"{_A}blip":
            rel_id = node.get(f"{_R}embed")
        elif node.tag == f"{_V}imagedata":
            rel_id = node.get(f"{_R}id")
        else:
            continue
        kind, path = rels.get(rel_id or "", ("", ""))
        if kind.endswith("/image"):
            yield path


def _offer_media(
    archive: zipfile.ZipFile,
    paths: Iterator[str] | Sequence[str],
    parts: DocumentParts,
    *,
    seen: set[str],
    where: str,
) -> None:
    """Each media part, read once per document however many places show it — a logo on
    every page is one part referenced many times, so this read is what the bomb pre-flight's
    declared total bounds — and offered to the collector with the block it follows."""
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            data = archive.read(path)
        except (
            KeyError,
            zipfile.BadZipFile,
            zlib.error,
            EOFError,
            RuntimeError,
            NotImplementedError,
            OSError,
        ):
            continue
        parts.pictures.offer(data, anchor=len(parts.blocks) - 1, where=where)


def _decode(data: bytes) -> str:
    """Bytes → str, or a refusal that names the fix.

    UTF-8 AND UTF-16-WITH-A-BOM, AND THEN WE STOP. The tempting third arm is a cp1252
    fallback, because Excel's plain "CSV" export on a Windows machine still writes it —
    and it is refused, because a silent fallback mojibakes rather than fails. Telugu
    cannot survive cp1252 at all, so the fallback would produce a knowledge base full of
    question marks that uploaded cleanly, passed review by a reviewer who assumed we knew
    what we were doing, and was read out on a phone call. The remediation names the exact
    menu item ("CSV UTF-8"), which is one dropdown for the client and no ambiguity for us.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as failure:
            raise _encoding_refusal() from failure
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as failure:
        raise _encoding_refusal() from failure
    # A NUL SURVIVING UTF-8 DECODING MEANS THE DECODE WAS WRONG, and this arm exists
    # because it silently was: UTF-16 WITHOUT a byte-order mark is what a lot of Windows
    # tooling writes, every second byte of it is 0x00, and 0x00 is a perfectly legal
    # UTF-8 codepoint — so `decode("utf-8")` SUCCEEDS and hands back "I\x00t\x00e\x00m".
    # Nothing downstream would have said so usefully either: `kb/service` refuses C0
    # controls, so the client would have got "your wording contains an invisible
    # character" for a file whose only problem is how it was saved.
    if "\x00" in text:
        raise _encoding_refusal()
    return text


def _encoding_refusal() -> DocumentUnreadableError:
    return DocumentUnreadableError(
        reason="not_utf8",
        detail=(
            "The characters in that file are not in a format we can read, so we would "
            "have shown your agent the wrong words."
        ),
        remediation=(
            "Save it again choosing 'CSV UTF-8' in Excel, or 'Unicode (UTF-8)' in "
            "Notepad or Google Sheets, and upload it once more."
        ),
    )


def _clean(text: str) -> str:
    """Whitespace a document format brings in, normalised away.

    Nothing here changes a word. Line endings become `\\n`, a word processor's break
    characters and non-breaking spaces become the ordinary ones (see `_LAYOUT_CONTROLS`),
    trailing spaces go, and runs of blank lines collapse to one — which matters more than
    it looks, because `kb.service.chunk_text` splits on the blank line, so a document
    with a blank line between every row would chunk into one fact per chunk and lose the
    paragraph structure the client wrote.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_LAYOUT_CONTROLS)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _open_ooxml(data: bytes, *, what: str) -> zipfile.ZipFile:
    """A .docx/.xlsx opened only after its own headers say it is not a bomb.

    The declared uncompressed total and the entry count are read from the central
    directory, which costs no decompression at all. See the module docstring, defence 1.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as failure:
        raise DocumentUnreadableError(
            reason="not_a_zip_container",
            detail=(
                f"That does not open as a {what} file. It may be damaged, or it may be "
                "password-protected."
            ),
            remediation=(
                "Open it on your computer, remove any password, save a fresh copy and "
                "upload that one."
            ),
        ) from failure

    declared = sum(entry.file_size for entry in entries)
    if len(entries) > MAX_OOXML_ENTRIES or declared > MAX_OOXML_EXPANDED_BYTES:
        archive.close()
        raise DocumentBombError(declared=declared, entries=len(entries))
    return archive


def _parse_part(archive: zipfile.ZipFile, name: str, *, what: str) -> ElementTree.Element:
    """One XML part of an OOXML container, with the DOCTYPE class closed first."""
    try:
        raw = archive.read(name)
    except KeyError as failure:
        raise DocumentUnreadableError(
            reason="part_missing",
            detail=f"That {what} file is missing the part that holds its text.",
            remediation="Open it, save a fresh copy, and upload that one.",
        ) from failure
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError) as failure:
        # The central directory opened, but the member itself does not decompress: a bad
        # CRC or a broken deflate stream (`BadZipFile`, `zlib.error`, `EOFError`), an
        # encrypted member (`RuntimeError`) or a compression method `zipfile` lacks
        # (`NotImplementedError`). Escaping as a raw exception left the upload at
        # "received" while arq retried it and every sweep re-drove it for ever.
        raise DocumentUnreadableError(
            reason="damaged_part",
            detail=f"That {what} file is damaged or password-protected, so we could not read it.",
            remediation=(
                "Open it on your computer, remove any password, save a fresh copy and "
                "upload that one."
            ),
        ) from failure

    if _declares_doctype(raw):
        raise DocumentUnreadableError(
            reason="doctype_declared",
            detail="That file contains an instruction we do not process, so we stopped.",
            remediation="Open it, save a fresh copy from your word processor, and upload that.",
        )

    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as failure:
        raise DocumentUnreadableError(
            reason="malformed_xml",
            detail=f"The inside of that {what} file is damaged, so we could not read it.",
            remediation="Open it, save a fresh copy, and upload that one.",
        ) from failure


# --- CSV -----------------------------------------------------------------------------

#: Delimiters worth guessing between. `csv.Sniffer` is the standard answer and is not
#: used: it decides from a sample and raises on files it cannot call, which turns a
#: readable price list into a refusal — counting candidates on the header line is both
#: more predictable and explainable to a client if it ever goes wrong.
_CSV_DELIMITERS: Final = (",", ";", "\t", "|")


def _extract_csv(data: bytes) -> DocumentParts:
    text = _decode(data)
    lines = text.splitlines()
    if not lines:
        raise DocumentEmptyError(kind="csv")
    delimiter = max(_CSV_DELIMITERS, key=lines[0].count)
    if lines[0].count(delimiter) == 0:
        # One column, or prose someone saved with a .csv extension. Either way there are
        # no headers to bind values to, so it is text and is treated as text.
        return DocumentParts("csv", [_clean(text)], len(lines), "lines")

    try:
        rows = list(csv.reader(lines, delimiter=delimiter))
    except csv.Error as failure:
        raise DocumentUnreadableError(
            reason="malformed_csv",
            detail="We could not line up the columns in that file.",
            remediation=(
                "Open it in Excel or Google Sheets, save it again as 'CSV UTF-8', and "
                "upload the new copy."
            ),
        ) from failure

    rendered, kept = _render_table(rows)
    return DocumentParts("csv", [rendered], kept, "rows")


def _render_table(rows: Sequence[Sequence[object]]) -> tuple[str, int]:
    """Header row + body rows → one self-describing line per row. See `serialise_row`.

    Returns the text and the number of rows that produced one, which is not `len(rows)`:
    a wholly blank row (a spacer between two sections of a price list) contributes
    nothing and is not counted, so the number an operator sees is rows of CONTENT.
    """
    body = list(rows)
    headers: list[str] = []
    while body and not headers:
        candidate = body.pop(0)
        headers = [str(cell).strip() if cell is not None else "" for cell in candidate]
        if not any(headers):
            headers = []
    if not headers:
        return "", 0

    lines: list[str] = []
    for row in body[:MAX_ROWS_PER_TABLE]:
        line = serialise_row(headers, row)
        if line:
            lines.append(line)
    # One row per LINE and a blank line between none of them: `kb.service.chunk_text`
    # splits on the blank line first and then packs to its 700-character cap, so
    # consecutive rows pack into one chunk and a chunk boundary still falls between two
    # whole rows. Blank-separating every row would force one row per chunk.
    return _clean("\n".join(lines)), len(lines)


# --- XLSX ----------------------------------------------------------------------------


def _extract_xlsx(data: bytes) -> DocumentParts:
    """Every visible sheet, each as a titled block of one line per row, and its pictures.

    HIDDEN SHEETS ARE SKIPPED, which is a content decision rather than a technical one: a
    hidden sheet is almost always the lookup table, the old prices or the working column
    somebody hid on purpose, and publishing it would put wording in front of callers that
    the client had deliberately taken out of view. Their pictures are skipped with them.
    """
    # Opened for the bomb pre-flight, then handed to openpyxl as bytes. openpyxl does its
    # own `ZipFile` open and offers no hook to inspect the central directory first, so the
    # choice is this one extra directory read (microseconds, no decompression) or trusting
    # a stranger's archive. The same pre-flighted archive is where the pictures are found:
    # openpyxl's `read_only` mode, which keeps a large workbook streaming, loads none.
    archive = _open_ooxml(data, what="spreadsheet")
    try:
        return _read_xlsx(data, archive)
    finally:
        archive.close()


def _read_xlsx(data: bytes, archive: zipfile.ZipFile) -> DocumentParts:
    sheet_pictures = _sheet_pictures(archive)
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data),
            read_only=True,
            data_only=True,
        )
    except (InvalidFileException, KeyError, ValueError, zipfile.BadZipFile) as failure:
        raise DocumentUnreadableError(
            reason="malformed_xlsx",
            detail="We could not open that spreadsheet.",
            remediation=(
                "Open it in Excel or Google Sheets, save it again as .xlsx, and upload "
                "the new copy. Older .xls files need saving as .xlsx first."
            ),
        ) from failure

    parts = DocumentParts("xlsx", [], 0, "rows")
    seen: set[str] = set()
    try:
        sheets = 0
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            title = str(sheet.title).strip()
            rows = [
                [_cell_text(value) for value in row]
                for row in sheet.iter_rows(max_row=MAX_ROWS_PER_TABLE + 1, values_only=True)
            ]
            rendered, kept = _render_table(rows)
            pictures = sheet_pictures.get(str(sheet.title), [])
            if not rendered and not pictures:
                continue
            if rendered:
                sheets += 1
                parts.unit_count += kept
                # The sheet name leads its block: a workbook's tabs are how the client
                # organised the knowledge ("Tiffins", "Biryani", "Delivery"), and the name
                # is the only thing that tells a retrieved row which section it came from.
                parts.blocks.append(f"{title}\n{rendered}")
            else:
                parts.blocks.append("")
                parts.headings[len(parts.blocks) - 1] = title
            _offer_media(archive, pictures, parts, seen=seen, where=title)
    finally:
        # `read_only` holds the archive open until this is called.
        workbook.close()

    if not parts.blocks:
        raise DocumentEmptyError(kind="xlsx")
    parts.unit_name = "rows" if sheets <= 1 else f"rows across {sheets} sheets"
    return parts


def _sheet_pictures(archive: zipfile.ZipFile) -> dict[str, list[str]]:
    """Each sheet's picture parts by sheet name: workbook → sheet → drawing → media."""
    try:
        workbook = _parse_part(archive, "xl/workbook.xml", what="spreadsheet")
    except DocumentRefusedError:
        return {}
    sheets = _relationships(archive, "xl/workbook.xml")
    found: dict[str, list[str]] = {}
    for sheet in workbook.iter(f"{_S}sheet"):
        name = sheet.get("name")
        _kind, sheet_part = sheets.get(sheet.get(f"{_R}id") or "", ("", ""))
        if not name or not sheet_part:
            continue
        for kind, drawing in _relationships(archive, sheet_part).values():
            if not kind.endswith("/drawing"):
                continue
            try:
                root = _parse_part(archive, drawing, what="spreadsheet")
            except DocumentRefusedError:
                continue
            found.setdefault(name, []).extend(_pictures_in(root, _relationships(archive, drawing)))
    return found


def _cell_text(value: object) -> str:
    """One cell as the words an agent would say.

    THE WHOLE REASON `openpyxl` IS A DEPENDENCY IS THESE SIX LINES. A date cell arrives
    as a `datetime` only because the library resolved a number-format code and the
    workbook's epoch; a hand-rolled reader gets the integer 45994 and publishes it.
    `float` is normalised so that a price stored as 260.0 is said as "260" — the trailing
    zero is an artefact of the storage, not of the client's price list.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time.min else value.isoformat(" ")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# --- DOCX ----------------------------------------------------------------------------


def _extract_docx(data: bytes) -> DocumentParts:
    """The body of a Word document, in document order, tables and pictures included."""
    archive = _open_ooxml(data, what="Word")
    try:
        return _read_docx(archive)
    finally:
        archive.close()


def _read_docx(archive: zipfile.ZipFile) -> DocumentParts:
    root = _parse_part(archive, _DOCX_BODY_PART, what="Word")
    body = root.find(f"{_W}body")
    if body is None:
        raise DocumentEmptyError(kind="docx")

    # A blank line between blocks (`assemble`): in a Word document the paragraph IS the
    # semantic unit the author chose, and `kb.service.chunk_text` splits on the blank line
    # first — so this is what makes a chunk boundary land where the client put a break.
    parts = DocumentParts("docx", [], 0, "paragraphs")
    rels = _relationships(archive, _DOCX_BODY_PART)
    seen: set[str] = set()
    for element in body:
        if element.tag == f"{_W}p":
            line = _paragraph_text(element)
            if line:
                parts.blocks.append(line)
                parts.unit_count += 1
        elif element.tag == f"{_W}tbl":
            rendered, kept = _render_table(list(_table_rows(element)))
            if rendered:
                parts.blocks.append(rendered)
                parts.unit_count += kept
        else:
            continue
        # A picture's words follow the paragraph or table that holds it.
        _offer_media(archive, _pictures_in(element, rels), parts, seen=seen, where="")
    return parts


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    """One `w:p` as a string, breaks and tabs preserved.

    TWO ELEMENTS ARE DELIBERATELY NOT READ, and both would be wrong in the direction that
    puts words in an agent's mouth that nobody wrote:

    * `w:delText` — text a tracked-changes DELETION removed. It is still in the file; it
      is not in the document. Publishing it would have an agent quote the sentence the
      client took out.
    * `w:instrText` — field instructions (`PAGE`, `HYPERLINK ...`), which are code rather
      than content. The field's rendered RESULT is a normal `w:t` and is kept.
    """
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            parts.append("\t" if node.tag == f"{_W}tab" else "\n")
    return "".join(parts).strip()


def _table_rows(table: ElementTree.Element) -> Iterator[list[str]]:
    """A `w:tbl` as rows of cell strings, ready for `_render_table`.

    A cell holds paragraphs, not text; they are joined with a space rather than a newline
    because a newline inside a cell would break the one-row-one-line property that makes
    the row retrievable as a unit.
    """
    for row in table.findall(f"{_W}tr"):
        yield [
            " ".join(filter(None, (_paragraph_text(p) for p in cell.findall(f"{_W}p")))).strip()
            for cell in row.findall(f"{_W}tc")
        ]


# Re-exported so a caller catching refusals imports the base class from the module it
# called, rather than reaching past it into the shared package for one name.
__all__ = [
    "DocumentParts",
    "DocumentRefusedError",
    "assemble",
    "extract_document",
    "read_document",
]
