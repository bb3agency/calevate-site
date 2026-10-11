"""A filename somebody else chose can neither break the header nor 500 the download."""

from __future__ import annotations

from apps.api.core.disposition import attachment_disposition
from starlette.responses import Response


def test_a_non_latin_filename_still_produces_a_sendable_header() -> None:
    value = attachment_disposition("సమ్మతి పత్రం.pdf", fallback="consent")
    # Starlette encodes header values as latin-1; the raw name raised UnicodeEncodeError.
    Response(content=b"x", headers={"Content-Disposition": value})
    assert value.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in value


def test_quotes_and_line_breaks_cannot_end_the_parameter_or_the_header() -> None:
    value = attachment_disposition('a"b\r\nSet-Cookie: x=1.pdf')
    assert "\r" not in value and "\n" not in value
    ascii_part = value.split(";")[1]
    assert ascii_part.count('"') == 2


def test_an_ordinary_name_reads_as_itself() -> None:
    assert attachment_disposition("consent-form.pdf").startswith(
        'attachment; filename="consent-form.pdf"'
    )
