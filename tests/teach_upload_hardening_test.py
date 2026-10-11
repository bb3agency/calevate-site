"""What a teaching upload may store: our type, and a key the client's filename cannot shape."""

from __future__ import annotations

import pytest
from apps.api.teach.routes import PHOTO_SUFFIXES, safe_key_suffix


@pytest.mark.parametrize("hostile", ["x/../y", "..", "p/q", "a b", "verylongext", "", "ÄÖ"])
def test_a_filename_extension_never_adds_a_segment_to_the_object_key(hostile: str) -> None:
    assert safe_key_suffix(hostile) == "bin"


def test_an_ordinary_extension_is_kept() -> None:
    assert safe_key_suffix("docx") == "docx"


def test_an_svg_is_not_a_photo() -> None:
    """`image/*` admitted `image/svg+xml`, a script-bearing document, stored under the
    client's own Content-Type."""
    assert "image/svg+xml" not in PHOTO_SUFFIXES
    assert all(t.startswith("image/") for t in PHOTO_SUFFIXES)
