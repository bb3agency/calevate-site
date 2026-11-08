"""An inbox row whose job was lost, or whose job succeeded on a retry, still closes.

Two holes in `reliability/service.py` (audit 8 Nov 2026, lane C):

* the engine-event jobs mark their row `failed` before raising `arq.Retry`, and the close
  on the retry that then succeeds was a CAS on `processing`/`enqueued` only, so the row
  stayed `failed` for good — re-run on the next re-send and never pruned;
* an `enqueued` row was never re-claimable, so a job arq lost (cancelled on timeout, its
  tries exhausted) left the event answered `duplicate` forever, a vendor re-send included.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import (
    ENQUEUED_LEASE,
    InboxClaim,
    body_hash,
    claim_inbox_event,
    mark_inbox_enqueued,
    mark_inbox_failed,
    mark_inbox_processed,
)
from sqlalchemy import text

PROVIDER = f"lost-job-{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM webhook_inbox_events WHERE provider = :p"), {"p": PROVIDER}
        )


async def _claim(event_key: str) -> InboxClaim:
    async with untenanted_session() as session:
        return await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_key,
            payload_hash=body_hash({"execution": event_key}),
            event_name="call.completed",
        )


async def _status(row_id: uuid.UUID) -> tuple[str, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT status, last_error FROM webhook_inbox_events WHERE id = :id"),
                {"id": row_id},
            )
        ).one()
    return str(row[0]), row[1]


@pytest.mark.asyncio
async def test_a_job_that_succeeds_on_its_retry_closes_its_row() -> None:
    claim = await _claim(f"exec-{uuid.uuid4().hex}")
    async with untenanted_session() as session:
        await mark_inbox_enqueued(session, row_id=claim.row_id)
    async with untenanted_session() as session:
        await mark_inbox_failed(session, row_id=claim.row_id, error="OperationalError")
    async with untenanted_session() as session:
        await mark_inbox_processed(session, row_id=claim.row_id)

    assert await _status(claim.row_id) == ("processed", None)


@pytest.mark.asyncio
async def test_a_lost_enqueued_job_does_not_dedupe_its_event_forever() -> None:
    event_key = f"exec-{uuid.uuid4().hex}"
    claim = await _claim(event_key)
    async with untenanted_session() as session:
        await mark_inbox_enqueued(session, row_id=claim.row_id)

    assert (await _claim(event_key)).state == "duplicate", "a live job must not be doubled"

    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE webhook_inbox_events SET enqueued_at = now() - :age WHERE id = :id"),
            {"age": ENQUEUED_LEASE + timedelta(minutes=1), "id": claim.row_id},
        )
    retaken = await _claim(event_key)
    assert retaken.state == "claimed"
    assert retaken.row_id == claim.row_id
