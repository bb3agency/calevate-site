"""What the knowledge page can show of a file: how many things were read out of it, and each
one under the heading it sat under (founder, 6 Nov 2026: the page showed a guide as one row
and none of what it taught the agents)."""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.api.kb.routes import ChunkOut, UploadOut
from apps.api.kb.structured_text import with_title, without_title
from tests.conftest import FakeS3
from tests.first_run_test import _tenant
from tests.kb_structured_text_test import GUIDE, _md_upload


def test_without_title_undoes_with_title_and_leaves_other_text_whole() -> None:
    assert without_title("Opening hours", with_title("Opening hours", ["9 to 6"])) == "9 to 6"
    assert without_title("Is it free?", with_title("Is it free?", ["Yes."])) == "Yes."
    assert without_title(None, "9 to 6") == "9 to 6"
    # A chunk that does not start with its title is not cut.
    assert without_title("Hours", "Open 9 to 6") == "Open 9 to 6"


async def test_an_upload_counts_what_was_read_out_of_it_and_lists_it_by_heading(
    s3: FakeS3,
) -> None:
    tenant_id = await _tenant()
    upload_id, source_id = await _md_upload(tenant_id, GUIDE.encode())
    async with tenant_session(tenant_id) as session:
        before = await uploads.get_upload(session, upload_id)
        stored = await kb_service.store_document_text(
            session, tenant_id=tenant_id, source_id=source_id, body=GUIDE, structured=True
        )
        listed = [row for row in await uploads.list_uploads(session) if row["id"] == upload_id]
        one = await uploads.get_upload(session, upload_id)
        chunks = await kb_service.preview(session, source_id)

    assert before["facts_count"] == 0
    assert listed[0]["facts_count"] == one["facts_count"] == stored.chunks == len(chunks) == 4
    assert UploadOut.model_validate(one).facts_count == 4
    out = [ChunkOut.model_validate(c) for c in chunks]
    assert [c.section for c in out] == [
        "Key details",
        "Installing on Android",
        "The Play Store question — this will come up in almost every call",
        "Opening hours",
    ]
    for chunk in out:
        assert chunk.section is not None
        assert chunk.body and not chunk.body.startswith(chunk.section)
        assert chunk.content.endswith(chunk.body)


async def test_another_tenant_sees_neither_the_count_nor_the_chunks(s3: FakeS3) -> None:
    tenant_a = await _tenant()
    tenant_b = await _tenant()
    upload_id, source_id = await _md_upload(tenant_a, GUIDE.encode())
    async with tenant_session(tenant_a) as session:
        await kb_service.store_document_text(
            session, tenant_id=tenant_a, source_id=source_id, body=GUIDE, structured=True
        )
    async with tenant_session(tenant_b) as session:
        assert await uploads.list_uploads(session) == []
        with pytest.raises(ProblemError):
            await uploads.get_upload(session, upload_id)
        with pytest.raises(ProblemError):
            await kb_service.preview(session, source_id)
