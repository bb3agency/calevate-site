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
   `word/document.xml`. `_parse_part` refuses the declaration outright on the bounded
   bytes before the parser sees them, which closes the class rather than one instance.
3. **Time.** There is no I/O here at all, so there is nothing to hang on: every loop is
   bounded by a ceiling above, and the worst input costs a bounded parse.

NOTHING IN THIS MODULE LOGS. It is handed a client's business document, routinely
carrying their customers' personal data (hard rule 6). It has no ids to log and its
refusals carry counts and codes, never content — so the caller, which does have ids,
does the logging.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from collections.abc import Iterator, Sequence
from typing import Final
from xml.etree import ElementTree

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

#: WordprocessingML's main namespace, and the only one this reader needs.
_W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: The one part of a .docx that holds the body text. Headers, footers and footnotes live
#: in sibling parts and are DELIBERATELY not read: a page header repeated on forty pages
#: becomes forty copies of the client's address in a retrieval corpus, which is noise the
#: chunker then has to be defended from.
_DOCX_BODY_PART: Final = "word/document.xml"

#: How much of an XML part is scanned for a DOCTYPE. A declaration is legal only in the
#: prolog, so anything past the first element is not one; 8 kB is generous for a prolog
#: and bounds the scan on a part we have not validated.
_PROLOG_SCAN_BYTES: Final = 8_192

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)

#: Characters a word processor emits as LAYOUT that the knowledge gate then refuses as
#: invisible controls (`kb/service._FORBIDDEN_CODEPOINTS` bans C0 except tab/LF/CR). They
#: are line and page breaks by definition, so they become newlines here rather than an
#: unexplainable refusal three steps later on a perfectly ordinary Word file.
_LAYOUT_CONTROLS: Final = str.maketrans({"\x0b": "\n", "\x0c": "\n", "\xa0": " "})


def extract_document(data: bytes, kind: IngestKind) -> ExtractedText:
    """One uploaded object → its text. Raises `DocumentRefusedError` and nothing else.

    The size gate is FIRST, before any parser sees the bytes, because every ceiling below
    it assumes an input of bounded size.
    """
    if len(data) > MAX_SOURCE_BYTES:
        raise DocumentTooLargeError(size=len(data), limit=MAX_SOURCE_BYTES)

    if kind == "txt":
        return _finish(_clean(_decode(data)), kind=kind, unit_count=1, unit_name="document")
    if kind == "csv":
        return _extract_csv(data)
    if kind == "docx":
        return _extract_docx(data)
    if kind == "xlsx":
        return _extract_xlsx(data)
    # `image` is the OCR lane's (`document_ocr.py`); anything else never had a reader.
    raise UnsupportedKindError(kind)


# --- SHARED PLUMBING -----------------------------------------------------------------


def _finish(text: str, *, kind: IngestKind, unit_count: int, unit_name: str) -> ExtractedText:
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
        needs_confirmation=False,
    )


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
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as failure:
        raise _encoding_refusal() from failure


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

    if _DOCTYPE.search(raw[:_PROLOG_SCAN_BYTES]):
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


def _extract_csv(data: bytes) -> ExtractedText:
    text = _decode(data)
    lines = text.splitlines()
    if not lines:
        raise DocumentEmptyError(kind="csv")
    delimiter = max(_CSV_DELIMITERS, key=lines[0].count)
    if lines[0].count(delimiter) == 0:
        # One column, or prose someone saved with a .csv extension. Either way there are
        # no headers to bind values to, so it is text and is treated as text.
        return _finish(_clean(text), kind="csv", unit_count=len(lines), unit_name="lines")

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
    return _finish(rendered, kind="csv", unit_count=kept, unit_name="rows")


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


def _extract_xlsx(data: bytes) -> ExtractedText:
    """Every visible sheet, each as a titled block of one line per row.

    HIDDEN SHEETS ARE SKIPPED, which is a content decision rather than a technical one: a
    hidden sheet is almost always the lookup table, the old prices or the working column
    somebody hid on purpose, and publishing it would put wording in front of callers that
    the client had deliberately taken out of view.
    """
    # Opened and closed for the bomb pre-flight ALONE, then handed to openpyxl as bytes.
    # openpyxl does its own `ZipFile` open and offers no hook to inspect the central
    # directory first, so the choice is this one extra directory read (microseconds, no
    # decompression) or trusting a stranger's archive. It is not a wasted parse: it is the
    # only place the declared expansion is ever seen.
    _open_ooxml(data, what="spreadsheet").close()
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

    try:
        blocks: list[str] = []
        sheets = 0
        rows_kept = 0
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            rows = [
                [_cell_text(value) for value in row]
                for row in sheet.iter_rows(max_row=MAX_ROWS_PER_TABLE + 1, values_only=True)
            ]
            rendered, kept = _render_table(rows)
            if not rendered:
                continue
            sheets += 1
            rows_kept += kept
            # The sheet name leads its block: a workbook's tabs are how the client
            # organised the knowledge ("Tiffins", "Biryani", "Delivery"), and the name is
            # the only thing that tells a retrieved row which section it came from.
            blocks.append(f"{str(sheet.title).strip()}\n{rendered}")
    finally:
        # `read_only` holds the archive open until this is called.
        workbook.close()

    if not blocks:
        raise DocumentEmptyError(kind="xlsx")
    return _finish(
        _clean("\n\n".join(blocks)),
        kind="xlsx",
        unit_count=rows_kept,
        unit_name="rows" if sheets == 1 else f"rows across {sheets} sheets",
    )


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


def _extract_docx(data: bytes) -> ExtractedText:
    """The body of a Word document, in document order, tables included."""
    archive = _open_ooxml(data, what="Word")
    try:
        root = _parse_part(archive, _DOCX_BODY_PART, what="Word")
    finally:
        archive.close()

    body = root.find(f"{_W}body")
    if body is None:
        raise DocumentEmptyError(kind="docx")

    blocks: list[str] = []
    paragraphs = 0
    for element in body:
        if element.tag == f"{_W}p":
            line = _paragraph_text(element)
            if line:
                blocks.append(line)
                paragraphs += 1
        elif element.tag == f"{_W}tbl":
            rendered, kept = _render_table(list(_table_rows(element)))
            if rendered:
                blocks.append(rendered)
                paragraphs += kept

    # A blank line between blocks: in a Word document the paragraph IS the semantic unit
    # the author chose, and `kb.service.chunk_text` splits on the blank line first — so
    # this is what makes a chunk boundary land where the client put a break.
    return _finish(
        _clean("\n\n".join(blocks)),
        kind="docx",
        unit_count=paragraphs,
        unit_name="paragraphs",
    )


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
__all__ = ["DocumentRefusedError", "extract_document"]
