"""An endpoint's full-phone-number opt-in can be switched off (lead decision 17 Nov 2026,
rememory 05574e5d), and is applied at delivery time as the transcript opt-ins are
(W1L5-01): a body queued while the endpoint was opted in reaches the receiver masked once the
owner has switched the opt-in off, on a retry or a "Send again" too.

Every test mints its own tenant.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.integrations import service
from sqlalchemy import text
from tests.account_settings_routes_test import _client, _code, _headers
from tests.api_security_test import _make_tenant

LEAD_NUMBER = "+919876500123"


async def _opted_in_endpoint(tenant_id: uuid.UUID) -> uuid.UUID:
    endpoint_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, "
                ":secret, :events, CAST(:mapping AS jsonb), true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": "https://crm.example/hook",
                "secret": "whsec_test",
                "events": ["lead.created"],
                "mapping": json.dumps({"include_raw_phone": True}),
            },
        )
    return endpoint_id


async def _queued_lead(tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        await service.enqueue_event(
            session,
            tenant_id=tenant_id,
            event="lead.created",
            data={"lead_id": str(uuid.uuid4()), "phone": LEAD_NUMBER, "name": "Ravi"},
        )
        row = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE payload->>'endpoint_id' = :e "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"e": str(endpoint_id)},
            )
        ).scalar_one()
    return dict(row)


async def _deliver(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    from apps.workers.outbound_webhooks import deliver_outbound_webhook

    sent: list[dict[str, Any]] = []

    async def fake_deliver(**kwargs: Any) -> service.DeliveryResult:
        sent.append(kwargs["envelope"]["data"])
        return service.DeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(service, "deliver", fake_deliver)
    await deliver_outbound_webhook({"job_try": 1}, dict(payload))
    (data,) = sent
    return data


async def test_a_queued_number_is_masked_once_the_owner_switches_the_opt_in_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a body queued while the endpoint was opted in carries the full number to
    the receiver after the owner switched the opt-in off."""
    tenant_id, slug, token = await _make_tenant()
    endpoint_id = await _opted_in_endpoint(tenant_id)
    queued = await _queued_lead(tenant_id, endpoint_id)
    assert queued["data"]["phone"] == LEAD_NUMBER, "the opt-in was on at fan-out"

    async with _client() as http:
        listed = await http.get("/v1/integrations/endpoints", headers=_headers(slug, token))
        off = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.created"], "include_raw_phone": False},
            headers=_headers(slug, token),
        )
    assert listed.json()[0]["include_raw_phone"] is True
    # Switching off sends nothing new, so it needs no emailed code.
    assert off.status_code == 200, off.text
    assert off.json()["include_raw_phone"] is False

    delivered = await _deliver(monkeypatch, queued)
    assert delivered["phone"] == "[redacted]"
    assert LEAD_NUMBER not in repr(delivered)
    later = await _queued_lead(tenant_id, endpoint_id)
    assert later["data"]["phone"] == "[redacted]", "new events are masked at fan-out too"


async def test_an_endpoint_still_opted_in_gets_the_number_and_an_edit_leaves_it_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _make_tenant()
    endpoint_id = await _opted_in_endpoint(tenant_id)
    async with _client() as http:
        edited = await http.patch(
            f"/v1/integrations/endpoints/{endpoint_id}",
            json={"events": ["lead.created", "lead.updated"]},
            headers=_headers(slug, token),
        )
    assert edited.status_code == 200, edited.text
    assert edited.json()["include_raw_phone"] is True, "left out, the opt-in stays"
    delivered = await _deliver(monkeypatch, await _queued_lead(tenant_id, endpoint_id))
    assert delivered["phone"] == LEAD_NUMBER


async def test_full_numbers_are_not_switched_on_from_the_dashboard() -> None:
    tenant_id, slug, token = await _make_tenant()
    endpoint_id = await _opted_in_endpoint(tenant_id)
    async with _client() as http:
        url = f"/v1/integrations/endpoints/{endpoint_id}"
        await http.patch(
            url,
            json={"events": ["lead.created"], "include_raw_phone": False},
            headers=_headers(slug, token),
        )
        again = await http.patch(
            url,
            json={"events": ["lead.created"], "include_raw_phone": True},
            headers=_headers(slug, token, "endpoint_opt_in"),
        )
        listed = await http.get("/v1/integrations/endpoints", headers=_headers(slug, token))
    assert again.status_code == 422, again.text
    assert _code(again) == "raw_phone_opt_in_with_us"
    assert listed.json()[0]["include_raw_phone"] is False
