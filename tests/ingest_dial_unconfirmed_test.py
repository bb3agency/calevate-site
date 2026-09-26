"""Lead ingest when the engine may have dialled and cannot say so (`DialUnconfirmedError`).

The property: a delivery whose dial outcome is unknown COMMITS — the lead, the inbox
claim and a pointer to the possibly-ringing call — so the sender's retry of the same
submission is absorbed as a duplicate instead of ringing the person a second time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.ingest.routes import SECRET_HEADER
from sqlalchemy import text
from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling-hours rule is not what this file measures."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def test_an_unconfirmed_dial_is_kept_and_its_retry_never_rings_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    engine = get_engine()
    real_start = engine.start_outbound_call

    # Broken AT THE ENGINE so the real `dispatch_call` commits its intent row and raises
    # `DialUnconfirmedError` carrying that row's id.
    async def _timed_out(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("the vendor did not answer")

    monkeypatch.setattr(engine, "start_outbound_call", _timed_out)
    submission = {"phone_number": "9876508888", "full_name": "Maybe Rung"}
    async with _client() as http:
        first = await http.post(
            f"/hooks/v1/ingest/{webhook_id}", json=submission, headers={SECRET_HEADER: SECRET}
        )
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["status"] == "accepted"
    assert body["dispatched"] is None, "unknown is not `false`, which reads as nobody rung"
    assert body["blocked"] is None

    # The engine recovers and the form vendor retries the identical submission.
    monkeypatch.setattr(engine, "start_outbound_call", real_start)
    async with _client() as http:
        retry = await http.post(
            f"/hooks/v1/ingest/{webhook_id}", json=submission, headers={SECRET_HEADER: SECRET}
        )
    assert retry.status_code == 202, retry.text
    assert retry.json()["status"] == "duplicate"

    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(text("SELECT id FROM leads WHERE phone_e164 = '+919876508888'"))
        ).all()
        calls = (
            await session.execute(
                text("SELECT id, lead_id FROM calls WHERE to_e164 = '+919876508888'")
            )
        ).all()
        note = (
            await session.execute(
                text("SELECT payload FROM lead_events WHERE payload->>'kind' = 'call_unconfirmed'")
            )
        ).scalar()
    assert len(leads) == 1, "the enquiry survives an unknown dial outcome"
    assert len(calls) == 1, "one possible ring, never a second"
    assert calls[0][1] == leads[0][0], "the possible call is on the lead's call log"
    assert note is not None and note["call_id"] == str(calls[0][0])
