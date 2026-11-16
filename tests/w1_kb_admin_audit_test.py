"""Wave 1 lane 5 (knowledge, Pip consent, admin console, integrations) audit findings.

W1L5-01: a `call.completed` body queued while a transcript opt-in was on carried the
transcript (redacted or raw) to the receiver on every later attempt, a scheduled retry or a
"Send again", after the owner had switched the opt-in off. The recording link already
honoured a withdrawn opt-in at delivery time; the transcripts now do too.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.webhook_call_completed_optin_test import (
    CALLER_NUMBER,
    RECORDING_KEY,
    _completed_call,
    _deliver,
    _endpoint,
    _fan_out,
)


async def _switch_off(tenant_id: uuid.UUID, endpoint_id: uuid.UUID, *, raw_only: bool) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE outbound_webhooks SET include_raw_transcript = false"
                + ("" if raw_only else ", include_transcript = false")
                + " WHERE id = :id"
            ),
            {"id": endpoint_id},
        )


async def test_a_queued_transcript_is_not_sent_after_its_opt_in_is_withdrawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_transcript=True, include_raw_transcript=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)
    (data,) = await _fan_out(tenant_id, call_id)
    assert "transcript" in data and "raw_transcript" in data

    await _switch_off(tenant_id, endpoint_id, raw_only=False)
    (delivered,) = await _deliver(monkeypatch, tenant_id, endpoint_id, data, times=1)

    assert "transcript" not in delivered
    assert "raw_transcript" not in delivered
    assert CALLER_NUMBER not in repr(delivered)
    assert delivered["summary"] == "A summary."


async def test_withdrawing_only_the_raw_opt_in_keeps_the_redacted_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_transcript=True, include_raw_transcript=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)
    (data,) = await _fan_out(tenant_id, call_id)

    await _switch_off(tenant_id, endpoint_id, raw_only=True)
    (delivered,) = await _deliver(monkeypatch, tenant_id, endpoint_id, data, times=1)

    assert "raw_transcript" not in delivered
    assert delivered["transcript"] == data["transcript"]
    assert CALLER_NUMBER not in repr(delivered)


async def test_an_endpoint_still_opted_in_gets_the_transcripts_it_was_queued_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_transcript=True, include_raw_transcript=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)
    (data,) = await _fan_out(tenant_id, call_id)

    (delivered,) = await _deliver(monkeypatch, tenant_id, endpoint_id, data, times=1)

    assert delivered["transcript"] == data["transcript"]
    assert delivered["raw_transcript"] == data["raw_transcript"]
