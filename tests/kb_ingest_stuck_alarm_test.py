"""A knowledge upload the voice platform keeps refusing is re-driven, and alarmed in time."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from apps.workers import kb_ingest


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    raised: list[str] = []

    @asynccontextmanager
    async def _session(_tenant_id: uuid.UUID) -> AsyncIterator[None]:
        yield None

    async def _mark(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(kb_ingest, "tenant_session", _session)
    monkeypatch.setattr(kb_ingest, "_mark", _mark)
    monkeypatch.setattr(kb_ingest, "alert", lambda _st, code, **_kw: raised.append(code))
    return raised


async def _fail(tenant_id: uuid.UUID, upload_id: uuid.UUID, *, retryable: bool = True) -> None:
    await kb_ingest._fail(
        tenant_id, upload_id, code="engine_unavailable", detail="busy", retryable=retryable
    )


async def test_a_row_failing_every_redrive_alarms_at_the_threshold(alarms: list[str]) -> None:
    tenant_id, upload_id = uuid.uuid4(), uuid.uuid4()
    for _ in range(kb_ingest.STUCK_AFTER_FAILURES - 1):
        await _fail(tenant_id, upload_id)
    assert alarms == []
    await _fail(tenant_id, upload_id)
    assert alarms == ["kb_ingest_stuck"]


async def test_a_publish_in_between_starts_the_count_again(alarms: list[str]) -> None:
    tenant_id, upload_id = uuid.uuid4(), uuid.uuid4()
    for _ in range(kb_ingest.STUCK_AFTER_FAILURES - 1):
        await _fail(tenant_id, upload_id)
    await kb_ingest._clear_failures(upload_id)
    await _fail(tenant_id, upload_id)
    assert alarms == []


async def test_a_permanent_failure_is_not_counted(alarms: list[str]) -> None:
    tenant_id, upload_id = uuid.uuid4(), uuid.uuid4()
    for _ in range(kb_ingest.STUCK_AFTER_FAILURES):
        await _fail(tenant_id, upload_id, retryable=False)
    assert alarms == []
