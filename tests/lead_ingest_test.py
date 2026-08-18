"""Instant lead callback (FLOWS §4): webhook-in → lead → gate → outbound.

The property under test throughout: **the lead always lands, the dial only happens
when it is lawful.** A fast call to a DNC number is not a feature, and a lost enquiry
because the gate said no is not acceptable either.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.service import add_to_dnc
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.ingest.routes import SECRET_HEADER
from apps.api.ingest.service import normalize_phone
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

SECRET = "ingest-secret-for-tests"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate's clock to 11:00 IST.

    Found the honest way: this suite ran at 05:39 IST and the compliance gate
    correctly refused to dial — which is the gate working and the tests depending on
    wall-clock. The DNC/consent cases below still exercise their own rules because the
    gate checks credits and hours BEFORE the consent/DNC branches under test.
    """
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant_with_ingest(
    *, mapping: dict | None = None, live_agent: bool = True
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant_id, agent_id, webhook_id) with a live outbound agent and one source."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Ingest Estates",
        slug=f"ing-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    webhook_id = uuid.uuid4()
    ref = f"fakeagent_ing_{uuid.uuid4().hex[:8]}"

    async with tenant_session(tenant_id) as session:
        if live_agent:
            await session.execute(
                text(
                    "UPDATE agents SET status = 'live', direction = 'outbound', "
                    "engine_agent_ref = :r WHERE id = :a"
                ),
                {"r": ref, "a": agent_id},
            )
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, agent_id, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, 'website_form', :s, "
                ":a, CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "i": webhook_id,
                "t": tenant_id,
                "s": SECRET,
                "a": agent_id,
                "m": json.dumps(
                    mapping
                    if mapping is not None
                    else {"phone": "phone_number", "name": "full_name", "budget": "budget_lakhs"}
                ),
            },
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id, webhook_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def test_phone_normalization_never_guesses_a_country() -> None:
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    assert normalize_phone("12345") is None, "too short to dial, too risky to guess"
    assert normalize_phone("5551234567") is None, "not an Indian mobile shape; no guessing"


async def test_a_form_submission_becomes_a_lead_and_an_outbound_call() -> None:
    tenant_id, agent_id, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876501234", "full_name": "Priya", "budget_lakhs": "45"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dispatched"] is True

    async with tenant_session(tenant_id) as session:
        lead = (
            await session.execute(
                text("SELECT phone_e164, name, source, data FROM leads WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).first()
        call = (
            await session.execute(
                text("SELECT direction, status, to_e164 FROM calls WHERE lead_id IS NOT NULL")
            )
        ).first()
    assert lead is not None
    assert lead[0] == "+919876501234", "the 10-digit form number is normalized to E.164"
    assert lead[1] == "Priya"
    assert lead[2] == "webhook"
    assert lead[3].get("budget") == "45", "mapped extra fields ride along in data"
    assert call is not None and call[0] == "outbound" and call[2] == "+919876501234"

    # The context reaches the engine so the agent opens with "you enquired about…".
    engine = get_engine()
    dispatched = next(iter(engine._calls.values()))  # type: ignore[attr-defined]
    assert dispatched["context"]["lead_name"] == "Priya"


async def test_a_dnc_number_gets_a_lead_but_never_a_call() -> None:
    """The order of operations the module exists for."""
    tenant_id, _agent_id, webhook_id = await _tenant_with_ingest()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876505555", source="request")

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876505555", "full_name": "Blocked Caller"},
            headers={SECRET_HEADER: SECRET},
        )
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == "dnc"

    async with tenant_session(tenant_id) as session:
        lead_count = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE phone_e164 = '+919876505555'")
            )
        ).scalar()
        call_count = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        note = (
            await session.execute(
                text("SELECT payload FROM lead_events WHERE type = 'note' LIMIT 1")
            )
        ).scalar()
    assert lead_count == 1, "the enquiry is kept — it is the client's data"
    assert call_count == 0, "the dial never happened"
    assert note and note.get("rule") == "dnc", "the timeline says exactly why"


async def test_missing_form_consent_keeps_the_lead_and_refuses_the_call() -> None:
    """FLOWS §4 step 2: the form must state a call will be made. If the config names a
    consent field and the payload does not affirm it, no dial."""
    tenant_id, _, webhook_id = await _tenant_with_ingest(
        mapping={"phone": "phone", "name": "name", "consent_field": "agree_to_call"}
    )
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone": "9876506666", "name": "No Consent", "agree_to_call": "false"},
            headers={SECRET_HEADER: SECRET},
        )
    body = response.json()
    assert body["dispatched"] is False
    assert body["blocked"] == "no_form_consent"
    async with tenant_session(tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM leads"))).scalar() == 1
        assert (await session.execute(text("SELECT count(*) FROM calls"))).scalar() == 0


async def test_wrong_secret_is_401_and_unknown_endpoint_is_404() -> None:
    _, _, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        bad_secret = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"phone_number": "9876507777"},
            headers={SECRET_HEADER: "wrong"},
        )
        unknown = await http.post(
            f"/hooks/v1/ingest/{uuid.uuid4()}",
            json={"phone_number": "9876507777"},
            headers={SECRET_HEADER: SECRET},
        )
    assert bad_secret.status_code == 401
    assert unknown.status_code == 404


async def test_a_vendor_retry_does_not_ring_the_customer_twice() -> None:
    """Form vendors retry on timeout; an identical payload is one enquiry, one call."""
    tenant_id, _, webhook_id = await _tenant_with_ingest()
    payload = {"phone_number": "9876508888", "full_name": "Retry Kumar"}
    async with _client() as http:
        first = await http.post(
            f"/hooks/v1/ingest/{webhook_id}", json=payload, headers={SECRET_HEADER: SECRET}
        )
        second = await http.post(
            f"/hooks/v1/ingest/{webhook_id}", json=payload, headers={SECRET_HEADER: SECRET}
        )
    assert first.json()["dispatched"] is True
    assert second.json()["status"] == "duplicate"
    async with tenant_session(tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM calls"))).scalar() == 1


async def test_a_payload_with_no_phone_is_a_422_not_a_lead() -> None:
    _, _, webhook_id = await _tenant_with_ingest()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/{webhook_id}",
            json={"full_name": "No Phone"},
            headers={SECRET_HEADER: SECRET},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/ingest_no_phone")


async def test_the_activity_view_shows_accepted_and_deduplicated_honestly() -> None:
    """SURFACES §2b: a vendor that retried five times must show as ONE accepted
    delivery with a dedup count, not five quiet nothings."""
    tenant_id, _, webhook_id = await _tenant_with_ingest()
    payload = {"phone_number": "9876509990", "full_name": "Retry Fifteen"}
    async with _client() as http:
        for _ in range(4):
            await http.post(
                f"/hooks/v1/ingest/{webhook_id}", json=payload, headers={SECRET_HEADER: SECRET}
            )

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, duplicate_count FROM webhook_inbox_events WHERE provider = :p"
                ),
                {"p": f"ingest:{webhook_id}"},
            )
        ).all()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()

    assert rows == [("processed", 3)], "one arrival accepted, three retries counted"
    assert calls == 1, "and still only one phone rang"


async def test_the_dry_run_reports_every_decision_and_does_nothing() -> None:
    """The test-webhook button (SURFACES §2b). Not a gate bypass: the gate is
    CONSULTED — same function, same live DNC read — and its verdict is reported
    instead of acted on. Nothing is written, nobody is called."""
    from apps.api.compliance.service import add_to_dnc

    tenant_id, _, webhook_id = await _tenant_with_ingest()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876509991", source="req")
        config = await __import__("apps.api.ingest.service", fromlist=["load_config"]).load_config(
            session, webhook_id
        )
        assert config is not None

    from apps.api.core.context import Principal
    from apps.api.ingest.routes import TestWebhookIn, test_webhook

    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )
    async with tenant_session(tenant_id) as session:
        blocked = await test_webhook(
            webhook_id,
            TestWebhookIn(payload={"phone_number": "9876509991", "full_name": "DNC Person"}),
            session,
            principal,
        )
        clean = await test_webhook(
            webhook_id,
            TestWebhookIn(payload={"phone_number": "9876509992", "full_name": "Clean Person"}),
            session,
            principal,
        )
        malformed = await test_webhook(
            webhook_id,
            TestWebhookIn(payload={"phone_number": "12345"}),
            session,
            principal,
        )
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()

    # Attribute access, not subscripts: the handler answers `LeadSourceDryRunOut` now
    # rather than a bare dict — see `tests/response_shape_test.py` for why that matters
    # on a handler that holds a normalized caller number in scope.
    assert blocked.would_call is False
    gate_step = next(s for s in blocked.steps if s.step == "compliance_gate")
    assert gate_step.rule == "dnc", "the dry run consulted the LIVE DNC list"

    assert clean.would_call is True
    assert malformed.would_call is False
    phone_step = next(s for s in malformed.steps if s.step == "phone_number")
    assert phone_step.ok is False

    assert leads == 0, "a dry run writes nothing"
    assert calls == 0, "and dials nobody"
