"""Backend audit 10 Nov 2026, lane Z8 (knowledge and files)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import uploads
from apps.api.teach import facts as fact_store
from apps.api.teach.facts import FACTS_SOURCE_NAME
from apps.workers import kb_ingest
from arq import Retry
from sqlalchemy import text
from tests.conftest import FakeS3, create_org_with_receptionist
from tests.kb_read_copy_test import _slug
from tests.kb_staff_curation_test import _client, _h, _member

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
