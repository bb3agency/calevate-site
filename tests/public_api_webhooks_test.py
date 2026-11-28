"""The events feed and key-made webhooks on the public API (D-1047, D-1049; MASTER-PLAN W2.6,
W2.7): a key with `org:read` reads the feed and moves only its own cursor, with numbers
masked; a key with `org:manage` adds a destination with no call content and removes only
destinations a key made; a key without the scope is refused."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service
from sqlalchemy import text
from tests.api_keys_test import bearer, make_key
from tests.lead_dial_routes_test import _client, _dialable_tenant

PHONE = "+919845012345"


@pytest.fixture(autouse=True)
def _public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _public(url: str) -> SimpleNamespace:
        return SimpleNamespace(host="example.com", port=443, url=url)

    monkeypatch.setattr(service, "assert_public_http_url", _public)


async def _emit(tenant_id: object) -> None:
    async with tenant_session(tenant_id) as session:  # type: ignore[arg-type]
        await service.enqueue_events(
            session,
            tenant_id=tenant_id,  # type: ignore[arg-type]
            event="lead.created",
            rows=[{"lead_id": str(uuid7()), "phone": PHONE, "name": "Sita", "status": "new"}],
        )


async def test_a_key_reads_the_feed_masked_and_acks_its_own_cursor() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    key = bearer(await make_key(headers, slug, scopes=["org:read"]))
    await _emit(tenant_id)
    async with _client() as http:
        page = await http.get("/api/v1/events/next", headers=key)
        assert page.status_code == 200, page.text
        (event,) = page.json()["events"]
        assert event["data"]["phone"] == "[redacted]"
        acked = await http.post(
            "/api/v1/events/next/ack", json={"event_id": event["id"]}, headers=key
        )
        assert acked.status_code == 200, acked.text
        assert acked.json()["after_event_id"] == event["id"]
        after = await http.get("/api/v1/events/next", headers=key)
    assert after.json()["events"] == []


async def test_a_key_adds_and_removes_only_its_own_destination() -> None:
    tenant_id, _agent, slug, headers = await _dialable_tenant()
    key = bearer(await make_key(headers, slug, scopes=["org:read", "org:manage"]))
    reader = bearer(await make_key(headers, slug, scopes=["org:read"]))
    body = {"url": "https://example.com/hook", "events": ["*"]}
    async with _client() as http:
        refused = await http.post("/api/v1/webhooks", json=body, headers=reader)
        recording = await http.post(
            "/api/v1/webhooks",
            json={**body, "events": [service.RECORDING_READY_EVENT]},
            headers=key,
        )
        made = await http.post("/api/v1/webhooks", json=body, headers=key)
    assert refused.status_code == 403 and refused.json()["type"].endswith("scope_missing")
    assert recording.status_code == 403
    assert made.status_code == 201, made.text
    created = made.json()
    assert created["secret"] and service.RECORDING_READY_EVENT not in created["events"]

    async with tenant_session(tenant_id) as session:
        person_made = (
            await session.execute(
                text(
                    "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                    "active, created_at, updated_at) VALUES (gen_random_uuid(), :t, 'webhook', "
                    "'https://crm.example/hook', 'whsec_x', ARRAY['lead.created'], true, now(), "
                    "now()) RETURNING id"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    async with _client() as http:
        theirs = await http.delete(f"/api/v1/webhooks/{person_made}", headers=key)
        mine = await http.delete(f"/api/v1/webhooks/{created['id']}", headers=key)
    assert theirs.status_code == 403
    assert mine.status_code == 204, mine.text
