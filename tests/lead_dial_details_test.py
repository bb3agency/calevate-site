"""A new lead's first call carries what the form told us about them (D-940): the lead's stored
details ride the dial as its `contact_details`, the same path a campaign row takes, and a
campaign row, when the dial has one, is not mixed with the lead's."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.campaigns.contact_details import lead_details
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.ingest.routes import SECRET_HEADER
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist
from tests.lead_ingest_test import SECRET, _client, _tenant_with_ingest


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the gate's calling-hours rule is not what this file measures."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def test_a_new_leads_dial_carries_its_form_details(monkeypatch: pytest.MonkeyPatch) -> None:
    _tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    engine = get_engine()
    original = engine.start_outbound_call
    seen: list[CallContext] = []

    async def _spy(ref: str, to: str, ctx: CallContext):  # type: ignore[no-untyped-def]
        seen.append(ctx)
        return await original(ref, to, ctx)

    monkeypatch.setattr(engine, "start_outbound_call", _spy)
    submission = {"phone_number": "9876507777", "full_name": "Asha", "budget_lakhs": "80"}
    async with _client() as http:
        answer = await http.post(
            f"/hooks/v1/ingest/{webhook_id}", json=submission, headers={SECRET_HEADER: SECRET}
        )
    assert answer.status_code == 202, answer.text
    assert answer.json()["dispatched"] is True
    details = seen[0].contact_details
    assert list(details.values()) == ["80"]
    assert seen[0].lead_name == "Asha"
    assert seen[0].context_note == "Enquiry via website_form"


async def test_a_deleted_or_missing_lead_has_no_details() -> None:
    created = await create_org_with_receptionist(
        name="Empty Estates",
        slug=f"empty-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        assert await lead_details(session, lead_id=uuid7()) == {}
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, deleted_at, created_at, updated_at) VALUES (:id, :t, :a, "
                "'+919876501111', 'Gone', 'webhook', 'new', '{\"need\": \"x\"}', now(), now(), "
                "now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id},
        )
        assert await lead_details(session, lead_id=lead_id) == {}
