"""The knowledge PDF renderer. No database and no engine: every property here is a
property of the BYTES, and the bytes are where the silent failure lives.

The centre of this file is `test_telugu_tenglish_and_english_survive_the_round_trip`:
it reads the text back out of the produced PDF with an independent parser (pypdf, not
our writer) and asserts the exact strings survive. Without that assertion the module is
untrustworthy in the one way that matters — a PDF with an empty text layer uploads
fine, reports `processed`, and retrieves nothing on a live call.
"""

from __future__ import annotations

import importlib.util
import io
import uuid

import pypdf
import pytest

from apps.api.kb.pdf_render import (
    MAX_UPLOAD_BYTES,
    RECOMMENDED_CHUNK_SIZE,
    RECOMMENDED_OVERLAP,
    ApprovedChunk,
    EmptyKnowledgeError,
    KnowledgePdfTooLargeError,
    UnapprovedChunkError,
    UnrenderableTextError,
    _charset_of,
    _new_document,
    render_knowledge_pdf,
)

SOURCE_A = uuid.UUID("018f3a2b-7c1d-7e4a-9b8c-0d1e2f3a4b5c")
SOURCE_B = uuid.UUID("018f3a2b-7c1d-7e4a-9b8c-0d1e2f3a4b6d")

# Real shapes of the three things a Telugu-first SMB knowledge base actually holds.
TELUGU = "మా షాప్ ఉదయం తొమ్మిది గంటలకు తెరుస్తాము మరియు రాత్రి ఎనిమిది గంటలకు మూసివేస్తాము."
TENGLISH = "Mee order ready ayyindi, pickup cheyyandi. Delivery ki extra 50 rupees."
ENGLISH = "We are open 9am to 8pm, Monday to Saturday. A consultation costs Rs 1,499."


def chunk(
    content: str,
    *,
    idx: int = 0,
    source_id: uuid.UUID = SOURCE_A,
    name: str = "Hours and fees",
    approved: bool = True,
    is_active: bool = True,
) -> ApprovedChunk:
    return ApprovedChunk(
        source_id=source_id,
        source_name=name,
        idx=idx,
        content=content,
        approved=approved,
        is_active=is_active,
    )


def extract(pdf_bytes: bytes) -> str:
    """Everything the vendor's parser would see, as one string."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


# --- the round trip: the whole point of this module ------------------------------------


def test_telugu_tenglish_and_english_survive_the_round_trip() -> None:
    """Render all three scripts, then read them back out of the produced bytes.

    Asserting on EXACT strings, not on "the text is non-empty": a font with no Telugu
    glyphs still produces a PDF with the Latin lines in it, so a length check would pass
    on exactly the file this module exists to prevent.
    """
    rendered = render_knowledge_pdf(
        [
            chunk(TELUGU, idx=0),
            chunk(TENGLISH, idx=1),
            chunk(ENGLISH, idx=2),
        ]
    )
    text = extract(rendered.content)

    assert TELUGU in text
    assert TENGLISH in text
    assert ENGLISH in text


def test_the_pdf_is_a_text_layer_and_not_a_picture_of_one() -> None:
    """The vendor parses the file. An image of text yields nothing, so assert there is
    no image XObject at all — a rasterising regression would still pass the round-trip
    test above if it also left the text behind, and would double the file size in
    silence.
    """
    rendered = render_knowledge_pdf([chunk(TELUGU)])
    # No image XObject anywhere. (`/ImageB` etc. appear in every PDF's `/ProcSet` and
    # are not images, so the assertion has to name the subtype.)
    assert b"/Subtype /Image" not in rendered.content
    # The font PROGRAM is embedded (`/FontFile2`), and the `/ToUnicode` CMap that maps
    # its glyphs back to codepoints is present — that CMap is precisely what makes the
    # Telugu extractable, so its absence is the bug this module is written against.
    assert b"/FontFile2" in rendered.content
    assert b"/ToUnicode" in rendered.content


def test_telugu_codepoints_reach_the_text_layer_individually() -> None:
    """Every Telugu character of the input is extractable on its own.

    The failure mode this guards is partial: shaping (or a fallback font) can drop or
    mangle a conjunct while leaving the rest of the line intact, which reads as success
    to anything checking a substring of the whole paragraph.
    """
    rendered = render_knowledge_pdf([chunk(TELUGU)])
    text = extract(rendered.content)
    telugu_in = {c for c in TELUGU if 0x0C00 <= ord(c) <= 0x0C7F}
    assert telugu_in, "fixture must actually contain Telugu"
    assert telugu_in <= set(text)


# --- determinism: the uploader's skip-if-unchanged depends on it -----------------------


def test_same_chunks_render_byte_identical() -> None:
    chunks = [chunk(TELUGU, idx=0), chunk(ENGLISH, idx=1)]
    first = render_knowledge_pdf(chunks)
    second = render_knowledge_pdf(chunks)
    assert first.content == second.content
    assert first.sha256 == second.sha256


def test_no_wall_clock_leaks_into_the_bytes() -> None:
    """The pinned creation date is the one that makes determinism hold; fpdf2 stamps
    `now()` otherwise and folds it into the document `/ID` too.
    """
    content = render_knowledge_pdf([chunk(ENGLISH)]).content
    assert b"D:20000101000000" in content


def test_changed_content_changes_the_hash() -> None:
    """The other half of the skip-if-unchanged contract: an edit MUST be visible, or the
    uploader skips a re-upload the client asked for.
    """
    before = render_knowledge_pdf([chunk(ENGLISH)])
    after = render_knowledge_pdf([chunk(ENGLISH + " Closed on public holidays.")])
    assert before.sha256 != after.sha256


def test_cosmetic_whitespace_does_not_change_the_hash() -> None:
    """A re-paste with CRLF endings or trailing spaces is the same knowledge, and must
    not cost a re-upload.
    """
    plain = render_knowledge_pdf([chunk("First fact.\n\nSecond fact.")])
    noisy = render_knowledge_pdf([chunk("First fact.  \r\n\r\n\r\nSecond fact.\r\n")])
    assert plain.sha256 == noisy.sha256


# --- the approval gate -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("approved", "is_active"),
    [(False, True), (True, False), (False, False)],
)
def test_an_unapproved_or_inactive_chunk_cannot_reach_the_bytes(
    approved: bool, is_active: bool
) -> None:
    """The gate is a product property (`kb/__init__.py`): a client cannot put text in
    their agent's mouth without a human seeing it first. Refused, not filtered — see
    `UnapprovedChunkError`.
    """
    secret = "Unreviewed claim: we guarantee a full refund within 90 days."
    with pytest.raises(UnapprovedChunkError):
        render_knowledge_pdf(
            [chunk(ENGLISH, idx=0), chunk(secret, idx=1, approved=approved, is_active=is_active)]
        )


def test_the_unapproved_chunk_is_absent_even_when_it_is_rendered_alone() -> None:
    """Belt and braces: prove no partial file escapes with the text in it."""
    with pytest.raises(UnapprovedChunkError):
        render_knowledge_pdf([chunk("Unreviewed.", approved=False)])


def test_the_refusal_names_the_chunk_but_not_its_text() -> None:
    """Hard rule 6: the message is an operator's, and client content is not log fodder."""
    body = "Unreviewed claim about a refund."
    with pytest.raises(UnapprovedChunkError) as caught:
        render_knowledge_pdf([chunk(body, idx=7, approved=False)])
    assert "#0007" in str(caught.value)
    assert body not in str(caught.value)


# --- the font coverage guard: fpdf2 warns and drops, we refuse -------------------------


def test_a_script_the_font_cannot_draw_is_refused_not_silently_dropped() -> None:
    """Devanagari in a Telugu knowledge base extracted back as the empty string, because
    fpdf2 prints a warning to stderr and carries on. That is the silent failure wearing
    a different hat.
    """
    with pytest.raises(UnrenderableTextError) as caught:
        render_knowledge_pdf([chunk("నమస్తే " + "नमस्ते")])
    assert 0x0928 in caught.value.codepoints  # DEVANAGARI LETTER NA
    assert "U+0928" in str(caught.value)


def test_an_emoji_is_refused() -> None:
    with pytest.raises(UnrenderableTextError):
        render_knowledge_pdf([chunk("We are open \U0001f600")])


def test_the_source_name_is_checked_too() -> None:
    """The name is printed on the page, so it can break the text layer exactly as the
    body can — and it is the half a caller is least likely to have validated.
    """
    with pytest.raises(UnrenderableTextError):
        render_knowledge_pdf([chunk(ENGLISH, name="नमस्ते")])


def test_the_rupee_sign_and_curly_quotes_render() -> None:
    """A price list is the most common knowledge a client uploads; ₹ dropping out of it
    silently would be the worst possible version of this bug.
    """
    body = "Consultation ₹500. “Walk-ins welcome” — no appointment."
    text = extract(render_knowledge_pdf([chunk(body)]).content)
    assert "₹500" in text


def test_newlines_and_tabs_are_layout_not_missing_glyphs() -> None:
    """The font has no glyph for either and does not need one. Without the exemption
    every multi-paragraph chunk — which is most of them — would be refused.
    """
    rendered = render_knowledge_pdf([chunk("First line.\n\tIndented second line.")])
    assert "Indented second line." in extract(rendered.content)


# --- traceability markers --------------------------------------------------------------


def test_each_block_carries_its_marker_into_the_text_layer() -> None:
    rendered = render_knowledge_pdf(
        [chunk(TELUGU, idx=0), chunk(ENGLISH, idx=1, source_id=SOURCE_B)]
    )
    text = extract(rendered.content)
    assert rendered.markers == ("[[KB 018f3a2b#0000]]", "[[KB 018f3a2b#0001]]")
    for marker in rendered.markers:
        assert marker in text


def test_blocks_are_separated_so_two_facts_do_not_read_as_one() -> None:
    text = extract(render_knowledge_pdf([chunk(ENGLISH, idx=0), chunk(TENGLISH, idx=1)]).content)
    assert "-----" in text
    assert text.index(ENGLISH) < text.index("-----") < text.index(TENGLISH)


def test_the_recommended_chunking_is_reported_to_the_uploader() -> None:
    """The uploader must not re-derive these: the layout and the request parameters are
    one decision, and 512 (the vendor default) would cut our 700-character chunks in two.
    """
    rendered = render_knowledge_pdf([chunk(ENGLISH)])
    assert rendered.chunk_size == RECOMMENDED_CHUNK_SIZE == 768
    assert rendered.overlapping == RECOMMENDED_OVERLAP == 128


# --- ordering, empties and the ceiling -------------------------------------------------


def test_chunks_render_in_the_order_given() -> None:
    text = extract(render_knowledge_pdf([chunk(ENGLISH, idx=0), chunk(TENGLISH, idx=1)]).content)
    assert text.index(ENGLISH) < text.index(TENGLISH)
    reversed_text = extract(
        render_knowledge_pdf([chunk(TENGLISH, idx=1), chunk(ENGLISH, idx=0)]).content
    )
    assert reversed_text.index(TENGLISH) < reversed_text.index(ENGLISH)


def test_nothing_to_render_is_refused_rather_than_shipped_as_an_empty_pdf() -> None:
    with pytest.raises(EmptyKnowledgeError):
        render_knowledge_pdf([])


def test_a_whitespace_only_chunk_is_skipped_not_marked() -> None:
    """It must not become a marker with no fact under it — retrieval would return the
    marker alone.
    """
    rendered = render_knowledge_pdf([chunk("   \n\n  ", idx=0), chunk(ENGLISH, idx=1)])
    assert rendered.markers == ("[[KB 018f3a2b#0001]]",)


def test_a_knowledge_base_of_only_whitespace_is_refused() -> None:
    with pytest.raises(EmptyKnowledgeError):
        render_knowledge_pdf([chunk("   "), chunk("\n\n")])


def test_a_realistic_knowledge_base_stays_far_under_the_ceiling() -> None:
    """200 full-size Telugu chunks — larger than any pilot client's KB — so the ceiling
    is known to be a guard against pathology, not a limit clients will meet.
    """
    body = (TELUGU + " ") * 8
    rendered = render_knowledge_pdf([chunk(body, idx=i) for i in range(200)])
    assert rendered.size_bytes < MAX_UPLOAD_BYTES


def test_the_ceiling_is_enforced_and_nothing_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Driven by shrinking the limit rather than by rendering 20 MB of Telugu, which
    would take minutes. What is asserted is the branch and its refusal — the error names
    the split-into-more-sources remediation and does NOT hand back a shortened file.
    """
    monkeypatch.setattr("apps.api.kb.pdf_render.MAX_UPLOAD_BYTES", 4096)
    with pytest.raises(KnowledgePdfTooLargeError) as caught:
        render_knowledge_pdf([chunk(TELUGU, idx=i) for i in range(20)])
    assert caught.value.chunk_count == 20
    assert caught.value.size_bytes > 4096
    assert "split" in str(caught.value)


def test_long_knowledge_paginates_rather_than_falling_off_the_page() -> None:
    """Auto page break on, so chunk 100 is as retrievable as chunk 1."""
    rendered = render_knowledge_pdf(
        [chunk(f"Fact number {i}. " + ENGLISH, idx=i) for i in range(60)]
    )
    reader = pypdf.PdfReader(io.BytesIO(rendered.content))
    assert len(reader.pages) > 1
    assert "Fact number 59." in extract(rendered.content)


# --- the shaping guard is live, not vacuous --------------------------------------------


def test_the_shaping_guard_actually_fires() -> None:
    """Pins the guard against the mistake that was already made once here: it was first
    written against `perform_harfbuzz_shaping`, which is a METHOD and so always truthy,
    making the assertion vacuous. A guard nobody can trip is not a guard, and this one
    protects the property the whole module is for — shaping silently corrupts the
    extracted Telugu (`తెరుస్తాము` came back as `'తెరుస్తా\x11 ము'`).
    """
    pdf = _new_document()
    assert _charset_of(pdf)  # off by default: passes and returns a real charset

    # Set on the attribute rather than through `set_text_shaping(True)`, which raises
    # here for the OTHER reason shaping cannot happen: uharfbuzz is deliberately not a
    # dependency (asserted below). The guard has to hold even if some future transitive
    # dependency drags uharfbuzz in and removes that first line of defence.
    pdf.text_shaping = {"use_shaping_engine": True}
    with pytest.raises(AssertionError, match="shaping"):
        _charset_of(pdf)


def test_uharfbuzz_is_not_installed() -> None:
    """The first line of defence, and a dependency-discipline assertion: shaping cannot
    be switched on at all while uharfbuzz is absent. If a future lockfile change pulls it
    in, this fails and whoever did it has to read why shaping is refused here.
    """
    assert importlib.util.find_spec("uharfbuzz") is None


def test_the_font_actually_covers_both_scripts() -> None:
    """The `full` Noto build, not the script-only one — whose 39-of-95 ASCII coverage
    would have dropped every English and Tenglish letter while Telugu looked fine.
    """
    covered = _charset_of(_new_document())
    assert all(ord(c) in covered for c in TELUGU)
    assert all(ord(c) in covered for c in TENGLISH)
    assert set(range(0x20, 0x7F)) <= covered
