"""A Meta event that fails to apply is retried, and its inbox row never sticks at enqueued."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import claim_inbox_event, mark_inbox_enqueued
from apps.workers import whatsapp_meta
from arq import Retry
from sqlalchemy import text


async def _inbox_row() -> UUID:
    key = uuid.uuid4().hex
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session, provider="meta_whatsapp_test", event_key=key, payload_hash=key
        )
        await mark_inbox_enqueued(session, row_id=claim.row_id)
    return claim.row_id


async def _status(row_id: UUID) -> str:
    async with untenanted_session() as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM webhook_inbox_events WHERE id = :id"), {"id": row_id}
                )
            ).scalar_one()
        )


@pytest.fixture
def failing(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"fails": 1, "alarms": []}

    async def _resolve(_waba: str) -> tuple[UUID, UUID]:
        return uuid.uuid4(), uuid.uuid4()

    async def _apply(*_a: Any) -> str:
        if state["fails"]:
            state["fails"] -= 1
            raise RuntimeError("database went away")
        return "account_recorded"

    monkeypatch.setattr(whatsapp_meta, "_resolve", _resolve)
    monkeypatch.setattr(whatsapp_meta, "_apply", _apply)
    monkeypatch.setattr(
        whatsapp_meta, "alert", lambda _st, code, **_kw: state["alarms"].append(code)
    )
    return state


def _payload(row_id: UUID) -> dict[str, Any]:
    event = {"waba_id": "1234567890", "kind": "account", "change": "account_update"}
    return {"event": event, "inbox_id": str(row_id)}


async def test_a_failed_apply_retries_and_the_retry_closes_the_row(
    failing: dict[str, Any],
) -> None:
    row_id = await _inbox_row()
    with pytest.raises(Retry):
        await whatsapp_meta.ingest_whatsapp_event({"job_try": 1}, _payload(row_id))
    assert await _status(row_id) == "enqueued"

    outcome = await whatsapp_meta.ingest_whatsapp_event({"job_try": 2}, _payload(row_id))
    assert outcome == "account_recorded"
    assert await _status(row_id) == "processed"
    assert failing["alarms"] == []


async def test_the_last_attempt_marks_the_row_failed_and_alarms(failing: dict[str, Any]) -> None:
    failing["fails"] = WORKER_MAX_TRIES
    row_id = await _inbox_row()
    outcome = await whatsapp_meta.ingest_whatsapp_event(
        {"job_try": WORKER_MAX_TRIES}, _payload(row_id)
    )
    assert outcome == "abandoned"
    assert await _status(row_id) == "failed"
    assert failing["alarms"] == ["whatsapp_event_not_applied"]
