"""Backend audit 10 Nov 2026, lane Z8 (knowledge and files)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.api.teach import facts as fact_store
from apps.api.teach.facts import FACTS_SOURCE_NAME
from apps.workers import kb_ingest
from arq import Retry
from sqlalchemy import text
from tests.conftest import FakeS3, create_org_with_receptionist
from tests.kb_read_copy_test import _slug
from tests.kb_staff_curation_test import _client, _h, _member
from tests.kb_structured_text_test import GUIDE

pytestmark = [pytest.mark.rls]


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Z8 Stores",
        slug=f"z8-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _facts_versions(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT kind FROM kb_sources WHERE name = :n ORDER BY version"),
            {"n": FACTS_SOURCE_NAME},
        )
        return [str(r[0]) for r in rows]


# Z8-01 ---------------------------------------------------------------------------------


async def test_nothing_new_may_take_the_taught_facts_name(s3: FakeS3) -> None:
    del s3
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["Parking is free behind the shop."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
    slug = await _slug(tenant_id)
    _owner, owner = await _member(tenant_id, "owner")
    async with _client() as http:
        typed = await http.post(
            "/v1/kb/sources",
            headers=_h(owner, slug),
            json={"name": FACTS_SOURCE_NAME, "body": "We open at nine every day.", "kind": "text"},
        )
    assert typed.status_code == 409, typed.text
    assert typed.json()["type"].endswith("/kb_name_taken")

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await uploads.create_upload(
                session,
                tenant_id=tenant_id,
                name=FACTS_SOURCE_NAME,
                filename="hours.txt",
                content_type="text/plain",
                data=b"We open at nine every day.",
                submitted_by=None,
                auto_approve=True,
            )
    assert refused.value.code == "kb_name_taken"
    assert await _facts_versions(tenant_id) == ["text"], "the taught facts keep their name"


# Z8-02 ---------------------------------------------------------------------------------


async def _text_upload(
    tenant_id: uuid.UUID, body: bytes, filename: str
) -> tuple[uuid.UUID, uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        made = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename=filename,
            content_type="text/plain",
            data=body,
            submitted_by=None,
            auto_approve=True,
        )
    return uuid.UUID(str(made["id"])), uuid.UUID(str(made["source_id"]))


async def test_an_owners_file_whose_first_reading_raises_is_retried_not_left_for_review(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    del s3
    tenant_id = await _tenant()
    _upload, source_id = await _text_upload(
        tenant_id, b"Rice 50 kg costs Rs 2,400 at our Guntur shop.", "prices.txt"
    )
    payload = {"tenant_id": str(tenant_id), "source_id": str(source_id), "may_self_approve": True}
    real = kb_ingest.read_document

    def _drop(*_a: Any, **_k: Any) -> Any:
        raise ConnectionResetError("connection reset")

    monkeypatch.setattr(kb_ingest, "read_document", _drop)
    with pytest.raises(Retry):
        await kb_ingest.ingest_kb_source({"job_try": 1}, payload)
    # The sweep's re-drive carries no approval and must not start retrying for it.
    with pytest.raises(ConnectionResetError):
        await kb_ingest.ingest_kb_source({"job_try": 1}, payload | {"may_self_approve": False})

    monkeypatch.setattr(kb_ingest, "read_document", real)
    outcome = await kb_ingest.ingest_kb_source({"job_try": 2}, payload)
    assert outcome.startswith("published"), outcome
    async with tenant_session(tenant_id) as session:
        status, active = (
            await session.execute(
                text("SELECT status, is_active FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).one()
    assert (status, active) == ("approved", True)


async def test_the_last_attempt_raises_the_fault_itself(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    del s3
    tenant_id = await _tenant()
    _upload, source_id = await _text_upload(
        tenant_id, b"Open nine to six, Monday to Saturday.", "hours.txt"
    )

    def _drop(*_a: Any, **_k: Any) -> Any:
        raise ConnectionResetError("connection reset")

    monkeypatch.setattr(kb_ingest, "read_document", _drop)
    with pytest.raises(ConnectionResetError):
        await kb_ingest.ingest_kb_source(
            {"job_try": 3},
            {"tenant_id": str(tenant_id), "source_id": str(source_id), "may_self_approve": True},
        )


# Z8-03 ---------------------------------------------------------------------------------


async def _suggested(tenant_id: uuid.UUID) -> set[str]:
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT payload->>'upload_id' FROM outbox_messages "
                "WHERE job = 'suggest_scripts_from_document' AND payload->>'tenant_id' = :t"
            ),
            {"t": str(tenant_id)},
        )
        return {str(r[0]) for r in rows}


async def test_a_file_read_again_is_not_suggested_to_the_scripts_a_second_time(
    s3: FakeS3,
) -> None:
    del s3
    tenant_id = await _tenant()
    upload_id, source_id = await _text_upload(tenant_id, GUIDE.encode(), "guide.md")
    async with tenant_session(tenant_id) as session:
        # As the file was held before the current reading: raw text, live.
        await kb_service.store_extracted_text(
            session, tenant_id=tenant_id, source_id=source_id, body=GUIDE
        )
        await session.execute(
            text(
                "UPDATE kb_sources SET status = 'approved', approved_at = now(), "
                "published_at = now(), is_active = true WHERE id = :s"
            ),
            {"s": source_id},
        )
    assert await kb_ingest.reparse_kb_upload(tenant_id=tenant_id, upload_id=upload_id) == (
        "new_version"
    )
    async with tenant_session(tenant_id) as session:
        new_upload, new_source = (
            await session.execute(
                text(
                    "SELECT u.id, s.id FROM kb_sources s JOIN kb_uploads u ON u.source_id = s.id "
                    "WHERE s.name = 'guide.md' AND s.version = 2"
                )
            )
        ).one()
    outcome = await kb_ingest.ingest_kb_source(
        {}, {"tenant_id": str(tenant_id), "source_id": str(new_source), "may_self_approve": True}
    )
    assert outcome == "published:v2", outcome
    assert str(new_upload) not in await _suggested(tenant_id)

    # A different file is still suggested.
    _other, other_source = await _text_upload(
        tenant_id, b"Delivery is free above Rs 500 in Guntur town.", "delivery.txt"
    )
    await kb_ingest.ingest_kb_source(
        {}, {"tenant_id": str(tenant_id), "source_id": str(other_source), "may_self_approve": True}
    )
    assert str(_other) in await _suggested(tenant_id)
