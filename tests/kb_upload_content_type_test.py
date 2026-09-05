"""The Content-Type a knowledge upload is STORED under is ours, never the uploader's.

The attack this file pins, end to end. `POST /v1/kb/uploads` is a multipart request, and a
multipart part carries its OWN `Content-Type` header alongside the filename. The filename
is checked (`classify_upload` refuses an extension we cannot read); the header never was,
and it was written straight onto the object in storage. Two things then read it back:

1. `GET /v1/kb/uploads/{id}/original` hands a REVIEWER a presigned URL to that object, and
   an object store replays the type it was given. `price-list.pdf` uploaded with
   `Content-Type: text/html` is therefore an HTML document served from the storage origin,
   under a link our own console asks a human to click — stored XSS on a body nobody parses
   and so nobody sanitises. It is the client's own reviewer today and an operator through
   the approval queue tomorrow, which is what makes it worth a test rather than a note.
2. `apps/workers/kb_ingest.py` fills Google's `Blob.mimeType` from the same column for a
   photograph, so the untrusted string was also an assertion WE made to a vendor about
   bytes we had never opened.

One fix closes both — `uploads.stored_content_type`, derived from the extension the
classifier already accepted — so the properties are asserted together here.
"""

from __future__ import annotations

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import uploads
from apps.workers import storage
from calevate_shared.document_ingest import OCR_IMAGE_MIME_TYPES
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_every_accepted_extension_has_a_type_of_ours() -> None:
    """Totality, which is what makes the `application/octet-stream` fallback unreachable.

    Asserted over the classifier's OWN table rather than a list retyped here: an extension
    added to `_EXTENSION_KINDS` without a type beside it would otherwise be accepted at the
    door and stored as a generic blob, which is the state this whole file exists to end.
    """
    missing = sorted(set(uploads._EXTENSION_KINDS) - set(uploads._EXTENSION_CONTENT_TYPES))
    assert not missing, f"accepted extensions with no Content-Type of ours: {missing}"


def test_the_image_types_are_ones_the_ocr_leg_accepts() -> None:
    """The photograph half of the fix. `image/jpg` is deliberately not emitted — the
    registered type is `image/jpeg` — so this is containment, not equality."""
    image_types = {
        uploads._EXTENSION_CONTENT_TYPES[ext]
        for ext, kind in uploads._EXTENSION_KINDS.items()
        if kind == "image"
    }
    assert image_types <= OCR_IMAGE_MIME_TYPES


async def test_a_lying_content_type_is_not_what_the_object_is_stored_under(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE REGRESSION. A `.pdf` declared as `text/html` must reach the store as a PDF.

    `store_kb_object` is recorded rather than the fake bucket read, because the fake
    discards the type — and the type is the entire subject of this test.
    """
    recorded: dict[str, str] = {}
    real = storage.store_kb_object

    async def _record(*, key: str, data: bytes, content_type: str) -> str:
        recorded["content_type"] = content_type
        return await real(key=key, data=data, content_type=content_type)

    monkeypatch.setattr(storage, "store_kb_object", _record)

    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Price list",
            filename="price-list.pdf",
            # The hostile header. A browser would send `application/pdf`.
            content_type="text/html",
            data=PDF,
            submitted_by=None,
            auto_approve=False,
        )
    assert recorded["content_type"] == "application/pdf"

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT content_type FROM kb_uploads WHERE id = :id"),
                {"id": row["id"]},
            )
        ).scalar()
    # The COLUMN too, because that is what the OCR leg reads back.
    assert stored == "application/pdf"


def test_a_photograph_declared_as_a_pdf_is_stored_as_the_image_it_is() -> None:
    """The other direction of the same lie, at the one function that decides it."""
    assert uploads.classify_upload(filename="menu.jpg", content_type="application/pdf") == "image"
    assert uploads.stored_content_type("menu.jpg") == "image/jpeg"
    assert uploads.stored_content_type("menu.HEIC") == "image/heic"


def test_a_filename_with_no_extension_never_reaches_a_stored_type() -> None:
    """Unreachable-by-construction, stated: `classify_upload` refuses it first, so the
    fallback below is a refusal to invent rather than a default anything relies on."""
    assert uploads.stored_content_type("noextension") == "application/octet-stream"
