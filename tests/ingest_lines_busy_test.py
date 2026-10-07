"""Lead ingest when the carrier account has no line or dial slot free (D-663).

The property: the lead lands and the call is not lost. `dispatch_call` refuses before any
row exists (`carrier_lines_busy`, `carrier_pacing`), and ingest books a call-back due now
for the dispatch tick to dial when a line frees, instead of rolling the enquiry back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.carrier_pacing import lines_busy, pacing_timed_out
from apps.api.ingest import service as ingest_service
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.ingest.service import INGEST_CALLBACK_PREFIX
from sqlalchemy import text
from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling-hours rule is not what this file measures."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.mark.parametrize(
    ("refusal", "phone"),
    [(lines_busy, "9876507701"), (pacing_timed_out, "9876507702")],
)
async def test_a_busy_account_books_the_call_back_and_keeps_the_lead(
    monkeypatch: pytest.MonkeyPatch, refusal: Any, phone: str
) -> None:
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest()

    async def _refuse(*_args: object, **_kwargs: object) -> str:
        raise refusal()

    monkeypatch.setattr(ingest_service, "dispatch_call", _refuse)
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": phone, "full_name": "Line Busy"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == refusal().code

    e164 = f"+91{phone}"
    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(text("SELECT id FROM leads WHERE phone_e164 = :p"), {"p": e164})
        ).all()
        booked = (
            await session.execute(
                text(
                    "SELECT agent_id, lead_id, status, source_execution_id, "
                    "requested_at <= now() FROM scheduled_callbacks WHERE phone_e164 = :p"
                ),
                {"p": e164},
            )
        ).all()
    assert len(leads) == 1, "the enquiry survives a busy account"
    assert len(booked) == 1, "one call-back, due now"
    row = booked[0]
    assert row[0] == agent_id
    assert row[1] == leads[0][0]
    assert row[2] == "scheduled"
    assert str(row[3]).startswith(INGEST_CALLBACK_PREFIX)
    assert row[4] is True


async def test_any_other_refusal_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core.errors import ProblemError

    async def _refuse(*_args: object, **_kwargs: object) -> str:
        raise ProblemError.business_rule("agent_not_published", "Not published.")

    monkeypatch.setattr(ingest_service, "dispatch_call", _refuse)
    _tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876507703", "full_name": "Not Deferred"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code >= 400


async def test_a_platform_opt_out_keeps_the_lead_and_books_no_call_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The voice platform refusing the person settles the delivery: nothing rang, the lead
    is kept, no call-back is booked, and the sender gets a 2xx so it does not retry."""
    from apps.api.engine.vendor_http import RECIPIENT_OPTED_OUT_CODE, recipient_opted_out_error

    async def _refuse(*_args: object, **_kwargs: object) -> str:
        raise recipient_opted_out_error()

    monkeypatch.setattr(ingest_service, "dispatch_call", _refuse)
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876507704", "full_name": "Opted Out"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == RECIPIENT_OPTED_OUT_CODE

    e164 = "+919876507704"
    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(text("SELECT id FROM leads WHERE phone_e164 = :p"), {"p": e164})
        ).all()
        booked = (
            await session.execute(
                text("SELECT count(*) FROM scheduled_callbacks WHERE phone_e164 = :p"),
                {"p": e164},
            )
        ).scalar_one()
    assert len(leads) == 1
    assert booked == 0
