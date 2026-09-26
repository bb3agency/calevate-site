"""An extracted upload that waits for a person: it can be confirmed, it is read ONCE, and
the confirm publishes what the reviewer read.

A `.txt`/`.docx`/spreadsheet or a photograph is read into text by the ingest job and then,
unless its submitter may self-approve (and never for a photograph), waits for the owner's
confirm. Driven end to end through the outbox job and the confirm, because each half passes
on its own: the defect was in what the first half left on the row for the second to read.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session
from apps.api.kb import uploads
from apps.workers import kb_ingest
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

BODY = "Refunds are given within fourteen days of purchase, with the receipt."


def _owner(tenant_id: uuid.UUID) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")


async def _ingest(tenant_id: uuid.UUID, source_id: uuid.UUID) -> str:
    return await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "source_id": str(source_id), "may_self_approve": False},
    )


async def _staff_upload(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Refund policy",
            filename="refund-policy.txt",
            content_type="text/plain",
            data=BODY.encode(),
            submitted_by=None,
            auto_approve=False,
        )


async def _upload_row(tenant_id: uuid.UUID, upload_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await uploads.get_upload(session, upload_id)


async def _chunk_ids(tenant_id: uuid.UUID, source_id: uuid.UUID) -> list[object]:
    async with tenant_session(tenant_id) as session:
        return [
            r[0]
            for r in (
                await session.execute(
                    text("SELECT id FROM kb_documents WHERE source_id = :s ORDER BY idx"),
                    {"s": source_id},
                )
            ).all()
        ]


async def test_an_extracted_upload_can_be_confirmed_and_is_then_published(s3: FakeS3) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _staff_upload(tenant_id, agent_id)
    upload_id, source_id = uuid.UUID(str(row["id"])), uuid.UUID(str(row["source_id"]))

    assert await _ingest(tenant_id, source_id) == "awaiting_review"

    async with tenant_session(tenant_id) as session:
        confirmed = await uploads.confirm_upload(
            session, tenant_id=tenant_id, upload_id=upload_id, principal=_owner(tenant_id)
        )
    assert confirmed["review_state"] == "approved"

    # The job the confirm enqueued.
    outcome = await _ingest(tenant_id, source_id)
    assert outcome.startswith("published"), outcome
    assert (await _upload_row(tenant_id, upload_id))["ingest_status"] == "processed"


async def test_a_redrive_of_an_upload_awaiting_review_does_not_read_it_again(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-reading is a paid model call for a photograph, and it replaces the chunks a
    reviewer may be reading with a second, possibly different, reading of the same page."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    row = await _staff_upload(tenant_id, agent_id)
    source_id = uuid.UUID(str(row["source_id"]))
    assert await _ingest(tenant_id, source_id) == "awaiting_review"
    before = await _chunk_ids(tenant_id, source_id)
    assert before

    async with tenant_session(tenant_id) as session:
        # Past `RETRY_STALLED_AFTER`, so the sweep considers it.
        await session.execute(
            text(
                "UPDATE kb_uploads SET updated_at = now() - interval '2 hours' WHERE source_id = :s"
            ),
            {"s": source_id},
        )

    reads: list[object] = []
    real_extract = kb_ingest._extract

    async def _counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(kwargs.get("upload_id"))
        return await real_extract(*args, **kwargs)

    monkeypatch.setattr(kb_ingest, "_extract", _counting)
    await kb_ingest.sweep_kb_uploads({})
    assert await _ingest(tenant_id, source_id) == "awaiting_review"

    assert reads == [], "an upload already read and awaiting review was read again"
    assert await _chunk_ids(tenant_id, source_id) == before, (
        "the chunks a reviewer is reading were replaced"
    )
