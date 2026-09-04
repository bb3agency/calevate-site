"""`apps/workers/document_text.py` — what a client uploads becomes text, or a refusal.

The suite is organised around the two things that can go wrong, because they need
different kinds of test:

* **The text is wrong.** A date published as `45994`, a price list whose rows lost their
  column headers, a tracked-changes deletion an agent then quotes. These are asserted on
  the OUTPUT STRING, exactly, because "it contains the price somewhere" would pass on a
  rendering that retrieves badly — and retrieval is the whole point of the format choice.
* **The file is hostile.** A zip bomb, a DOCTYPE, mojibake, something that is not a zip
  at all. These assert the refusal CODE and, every time, that nothing from inside the
  document reached the message (hard rule 6).
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest
from apps.workers import document_text
from apps.workers.document_text import extract_document
from calevate_shared.document_ingest import (
    MAX_EXTRACTED_CHARS,
    MAX_OOXML_ENTRIES,
    MAX_SOURCE_BYTES,
    DocumentBombError,
    DocumentEmptyError,
    DocumentRefusedError,
    DocumentTooLargeError,
    DocumentUnreadableError,
    UnsupportedKindError,
    serialise_row,
)
from openpyxl import Workbook

# --- FIXTURE BUILDERS ----------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body: str, *, part: str = "word/document.xml") -> bytes:
    """The smallest thing Word would recognise: one part holding the body we want.

    A real .docx carries `[Content_Types].xml`, rels and a dozen other parts. None of
    them is read (`_DOCX_BODY_PART`), so a fixture that shipped them would be asserting
    that our reader ignores parts it never opens.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            part,
            f'<?xml version="1.0"?><w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


def _para(*runs: str) -> str:
    inner = "".join(f"<w:r><w:t>{run}</w:t></w:r>" for run in runs)
    return f"<w:p>{inner}</w:p>"


def _xlsx(*sheets: tuple[str, list[list[object]], str]) -> bytes:
    """`(title, rows, sheet_state)` per sheet, as real bytes through openpyxl's writer."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows, state in sheets:
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
        sheet.sheet_state = state
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- THE ROW RENDERING, WHICH IS THE DECISION THIS LANE IS ABOUT ---------------------


def test_a_row_carries_its_own_headers_so_a_chunk_can_answer_from_it_alone() -> None:
    """The property the whole `serialise_row` argument rests on.

    Everything a caller could ask about one row — the dish AND the word "Price" AND the
    number — is on ONE line, so wherever the chunker cuts, no chunk holds a value whose
    column name is a hundred rows above it.
    """
    line = serialise_row(["Item", "Price"], ["Paneer butter masala", 260])
    assert line == "Item: Paneer butter masala; Price: 260"


def test_a_blank_cell_contributes_nothing_rather_than_a_fact_about_nothing() -> None:
    assert serialise_row(["Item", "Notes"], ["Idli", ""]) == "Item: Idli"
    assert serialise_row(["Item", "Notes"], ["Idli", None]) == "Item: Idli"


def test_a_value_past_the_last_header_survives_without_one() -> None:
    """A ragged row is a real spreadsheet, not a defect: the value is kept bare rather
    than dropped, because dropping it would silently lose a client's price."""
    assert serialise_row(["Item"], ["Idli", "40"]) == "Item: Idli; 40"


def test_an_entirely_blank_row_renders_to_nothing_and_is_dropped() -> None:
    assert serialise_row(["Item", "Price"], [None, ""]) == ""


# --- XLSX ----------------------------------------------------------------------------


def test_a_price_list_becomes_one_self_describing_line_per_row_under_its_sheet_name() -> None:
    data = _xlsx(
        (
            "Tiffins",
            [
                ["Item", "Price", "Valid till"],
                ["Idli", 40.0, dt.datetime(2026, 10, 3)],
                [None, None, None],
                ["Dosa", 60, None],
            ],
            "visible",
        )
    )
    out = extract_document(data, "xlsx")
    assert out.text == (
        "Tiffins\nItem: Idli; Price: 40; Valid till: 2026-10-03\nItem: Dosa; Price: 60"
    )
    # Rows of CONTENT, not rows in the file: the spacer row is not something to bill,
    # count or show an operator.
    assert (out.unit_count, out.unit_name) == (2, "rows")
    assert out.provenance == "parsed"
    # A deterministic parse of text that was already text. The OCR question — "did the
    # machine read this correctly at all" — does not arise, so no confirmation screen.
    assert out.needs_confirmation is False


def test_a_date_cell_is_published_as_a_date_and_not_as_its_serial_number() -> None:
    """THE REASON `openpyxl` IS A DEPENDENCY. A hand-rolled OOXML reader gets the integer
    and an agent tells a caller the offer is valid until 45994."""
    data = _xlsx(("S", [["Offer", "Valid till"], ["Diwali", dt.datetime(2026, 10, 3)]], "visible"))
    assert "Valid till: 2026-10-03" in extract_document(data, "xlsx").text


def test_a_price_stored_as_a_float_is_said_without_its_storage_artefact() -> None:
    data = _xlsx(("S", [["Item", "Price"], ["Idli", 40.0]], "visible"))
    assert "Price: 40" in extract_document(data, "xlsx").text
    assert "40.0" not in extract_document(data, "xlsx").text


def test_a_hidden_sheet_stays_hidden() -> None:
    """A hidden sheet is the old prices or the cost column somebody hid on purpose.
    Publishing it would put wording in front of callers the client took out of view."""
    data = _xlsx(
        ("Menu", [["Item", "Price"], ["Idli", 40]], "visible"),
        ("Costs", [["Item", "Our cost"], ["Idli", 12]], "hidden"),
    )
    text = extract_document(data, "xlsx").text
    assert "Idli" in text
    assert "Our cost" not in text and "12" not in text


def test_a_workbook_with_no_content_is_refused_rather_than_published_empty() -> None:
    """An empty knowledge source uploads cleanly, reports success and retrieves nothing —
    the failure `kb/pdf_render.py` exists to prevent, caught one step earlier."""
    with pytest.raises(DocumentEmptyError) as refusal:
        extract_document(_xlsx(("S", [], "visible")), "xlsx")
    assert refusal.value.code == "ingest_empty"


def test_something_that_is_not_a_workbook_is_refused_with_a_fix_the_client_can_apply() -> None:
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document(b"this is not a spreadsheet", "xlsx")
    assert refusal.value.reason == "not_a_zip_container"
    assert "password" in refusal.value.detail


# --- CSV -----------------------------------------------------------------------------


def test_a_semicolon_separated_export_is_read_as_columns_not_as_prose() -> None:
    data = b"Item;Price\nIdli;40\nDosa;60\n"
    assert extract_document(data, "csv").text == "Item: Idli; Price: 40\nItem: Dosa; Price: 60"


def test_telugu_survives_the_round_trip_unchanged() -> None:
    """The product is Telugu-first; a converter that mangled the script would be useless
    here however well it read English."""
    data = "Item,Price\nఇడ్లీ,40\n".encode()
    assert extract_document(data, "csv").text == "Item: ఇడ్లీ; Price: 40"


def test_a_single_column_file_is_treated_as_text_because_there_is_nothing_to_bind() -> None:
    data = b"We open at nine\nWe close at ten\n"
    out = extract_document(data, "csv")
    assert out.text == "We open at nine\nWe close at ten"


def test_a_file_that_is_not_utf8_is_refused_rather_than_silently_mojibaked() -> None:
    """The rejected alternative is a cp1252 fallback. It would produce a knowledge base
    full of question marks that uploaded cleanly and was read out on a phone call."""
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document("Idli,₹40\n".encode("utf-16-le"), "csv")
    assert refusal.value.reason == "not_utf8"
    assert "UTF-8" in refusal.value.remediation


def test_utf16_without_a_byte_order_mark_is_caught_instead_of_decoding_to_nuls() -> None:
    """The silent one. Every second byte of BOM-less UTF-16 is 0x00, which is a LEGAL
    UTF-8 codepoint — so the decode succeeds and returns "I\x00t\x00e\x00m". Without
    this arm the client's first sign of trouble is `kb/service` refusing their wording
    for containing an invisible character, which names neither the cause nor the fix."""
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document("Item,Price\nIdli,40\n".encode("utf-16-le"), "csv")
    assert refusal.value.reason == "not_utf8"


def test_a_utf16_file_with_a_byte_order_mark_is_read() -> None:
    assert "Idli" in extract_document("Item,Price\nIdli,40\n".encode("utf-16"), "csv").text


# --- TXT -----------------------------------------------------------------------------


def test_a_word_processors_break_characters_become_newlines_the_knowledge_gate_accepts() -> None:
    """`kb/service._FORBIDDEN_CODEPOINTS` bans every C0 control but tab/LF/CR, so a
    vertical tab out of Word would be an unexplainable refusal three steps later on a
    perfectly ordinary document. It is a line break by definition; it becomes one."""
    out = extract_document("hello\r\nworld\x0bnext\x0cpage\xa0end".encode(), "txt")
    assert out.text == "hello\nworld\nnext\npage end"


def test_text_over_the_reading_ceiling_is_refused_in_characters_not_bytes() -> None:
    """The ceiling is derived from the APPROVAL GATE — someone reads this before it can
    be said on a call — so it is counted in what a person reads."""
    with pytest.raises(DocumentTooLargeError) as refusal:
        extract_document(("x" * (MAX_EXTRACTED_CHARS + 1)).encode(), "txt")
    assert refusal.value.limit == MAX_EXTRACTED_CHARS


# --- DOCX ----------------------------------------------------------------------------


def test_paragraphs_are_separated_by_the_blank_line_the_chunker_splits_on() -> None:
    out = extract_document(_docx(_para("We open at nine.") + _para("We deliver.")), "docx")
    assert out.text == "We open at nine.\n\nWe deliver."
    assert out.unit_count == 2


def test_a_word_table_is_serialised_by_row_exactly_as_a_spreadsheet_is() -> None:
    """ONE renderer for tables wherever they come from. Two spellings of a row would be
    two retrieval behaviours for the same client fact."""
    table = (
        f"<w:tbl><w:tr><w:tc>{_para('Item')}</w:tc><w:tc>{_para('Price')}</w:tc></w:tr>"
        f"<w:tr><w:tc>{_para('Idli')}</w:tc><w:tc>{_para('40')}</w:tc></w:tr></w:tbl>"
    )
    assert extract_document(_docx(table), "docx").text == "Item: Idli; Price: 40"


def test_text_a_tracked_change_deleted_is_not_published() -> None:
    """It is still in the file; it is not in the document. Publishing it would have an
    agent quote the sentence the client took out."""
    body = (
        "<w:p><w:r><w:t>We deliver.</w:t></w:r>"
        "<w:del><w:r><w:delText>We do not deliver.</w:delText></w:r></w:del></w:p>"
    )
    text = extract_document(_docx(body), "docx").text
    assert text == "We deliver."


def test_a_field_instruction_is_not_published_but_its_rendered_result_is() -> None:
    body = (
        "<w:p><w:r><w:instrText>HYPERLINK http://example.invalid</w:instrText></w:r>"
        "<w:r><w:t>our website</w:t></w:r></w:p>"
    )
    assert extract_document(_docx(body), "docx").text == "our website"


def test_a_line_break_inside_a_paragraph_stays_a_line_break() -> None:
    body = "<w:p><w:r><w:t>Idli</w:t><w:br/><w:t>Dosa</w:t></w:r></w:p>"
    assert extract_document(_docx(body), "docx").text == "Idli\nDosa"


def test_a_docx_with_no_readable_body_is_refused() -> None:
    with pytest.raises(DocumentEmptyError):
        extract_document(_docx(""), "docx")


def test_a_docx_missing_its_body_part_is_refused_with_an_operator_reason() -> None:
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document(_docx(_para("hi"), part="word/other.xml"), "docx")
    assert refusal.value.reason == "part_missing"


def test_damaged_xml_inside_a_docx_is_a_refusal_and_not_a_traceback() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><unclosed>")
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document(buffer.getvalue(), "docx")
    assert refusal.value.reason == "malformed_xml"


# --- HOSTILE INPUT -------------------------------------------------------------------


def test_a_doctype_is_refused_before_the_xml_parser_is_handed_the_bytes() -> None:
    """The billion-laughs class, closed by refusing the DECLARATION rather than by
    adding `defusedxml` for one check. No word processor emits one."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><w:document/>',
        )
    with pytest.raises(DocumentUnreadableError) as refusal:
        extract_document(buffer.getvalue(), "docx")
    assert refusal.value.reason == "doctype_declared"


def test_an_archive_with_too_many_entries_is_refused_without_reading_one() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(MAX_OOXML_ENTRIES + 1):
            archive.writestr(f"part{index}.xml", "x")
    with pytest.raises(DocumentBombError) as refusal:
        extract_document(buffer.getvalue(), "docx")
    assert refusal.value.entries == MAX_OOXML_ENTRIES + 1


def test_an_archive_declaring_more_than_it_should_is_refused_on_the_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read from the central directory, so it costs NO decompression: the bomb never
    gets to expand. The ceiling is lowered here rather than building a 256 MB fixture —
    what is under test is that the sum is consulted before `read()`, not the number."""
    monkeypatch.setattr(document_text, "MAX_OOXML_EXPANDED_BYTES", 16)
    with pytest.raises(DocumentBombError) as refusal:
        extract_document(_docx(_para("a fairly ordinary sentence")), "docx")
    assert refusal.value.declared > 16


def test_an_upload_over_the_size_ceiling_never_reaches_a_parser() -> None:
    with pytest.raises(DocumentTooLargeError) as refusal:
        extract_document(b"\0" * (MAX_SOURCE_BYTES + 1), "docx")
    assert refusal.value.limit == MAX_SOURCE_BYTES


def test_a_kind_this_lane_does_not_convert_is_named_and_refused() -> None:
    with pytest.raises(UnsupportedKindError) as refusal:
        extract_document(b"", "image")  # type: ignore[arg-type]
    assert refusal.value.kind == "image"


# --- HARD RULE 6 ---------------------------------------------------------------------


def test_no_refusal_carries_a_single_word_of_the_document() -> None:
    """A refusal is shown to a client, logged by the caller and may reach an operator's
    screen. An uploaded document carries the client's customers' personal data, so the
    refusal is allowed counts, codes and ceilings — and nothing that was inside the file.
    """
    secret = "Ravi Kumar 9876543210"
    hostile: list[tuple[bytes, str]] = [
        (f"Item,Price\n{secret},40\n".encode("utf-16-le"), "csv"),  # not_utf8
        (_docx(_para(secret), part="word/other.xml"), "docx"),  # part_missing
        (b"PK not a zip " + secret.encode(), "xlsx"),  # not_a_zip_container
        (_docx(_para(secret) * 2000 + _para("x" * 200_000)), "docx"),  # too many characters
    ]
    for data, kind in hostile:
        with pytest.raises(DocumentRefusedError) as refusal:
            extract_document(data, kind)  # type: ignore[arg-type]
        rendered = " ".join(
            [
                refusal.value.code,
                refusal.value.title,
                refusal.value.detail,
                refusal.value.remediation,
                str(refusal.value),
            ]
        )
        assert "Ravi" not in rendered
        assert "9876543210" not in rendered
