"""`call.recording_ready` (D-670, docs/WEBHOOKS.md §1.1 and §1.2).

`call.completed` fires when the post-call pipeline finishes, which is usually before the
carrier reports the recording, so its recording link is usually absent. This event fires
once our copy is stored and exists to carry that link.

- **Signed per delivery, read from the call as it is now.** The body carries `call_id`,
  `lead_id`, `duration_s` and a fresh short-TTL `recording_url`, and never a phone number.
- **No link, no delivery.** An opt-in withdrawn after the event was queued, or a recording
  erased in between, is a `skipped` delivery with its reason, not a POST of nothing.
- **The registration gate** refuses the subscription without `include_recording_url`.

The producer half (fired once per call and endpoint, from the copy) is pinned in
`tests/carrier_recording_copy_test.py` §6.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from apps.api.integrations.routes import CreateEndpointIn, assert_recording_ready_has_its_opt_in
from apps.workers import storage
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.webhook_call_completed_optin_test import RECORDING_KEY, _completed_call


async def _endpoint(tenant_id: uuid.UUID, *, include_recording_url: bool) -> uuid.UUID:
    endpoint_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "include_recording_url, active, created_at, updated_at) VALUES (:id, :tid, "
                "'webhook', 'https://crm.example/hook', 'whsec_test', :events, :inc, true, "
                "now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "events": [service.RECORDING_READY_EVENT],
                "inc": include_recording_url,
            },
        )
    return endpoint_id


async def _deliver(
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    call_id: uuid.UUID,
) -> tuple[str, list[dict], uuid.UUID]:
    from apps.workers.outbound_webhooks import deliver_outbound_webhook

    sent: list[dict] = []

    async def fake_deliver(**kwargs: object) -> service.DeliveryResult:
        envelope = kwargs["envelope"]
        assert isinstance(envelope, dict)
        sent.append(envelope["data"])
        return service.DeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(service, "deliver", fake_deliver)
    delivery_id = uuid.uuid4()
    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": service.RECORDING_READY_EVENT,
            "data": {"call_id": str(call_id)},
            "delivery_id": str(delivery_id),
        },
    )
    return outcome, sent, delivery_id


async def _delivery_row(delivery_id: uuid.UUID) -> tuple[str | None, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT status, reason FROM webhook_deliveries WHERE id = :id"),
                {"id": delivery_id},
            )
        ).first()
    assert row is not None
    return row[0], row[1]


@pytest.fixture
def presign(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []

    def fake(key: str, *, ttl_s: int = storage.PRESIGN_TTL_S) -> str:
        seen.append(ttl_s)
        return f"https://store.example/{key}?X-Amz-Expires={ttl_s}"

    monkeypatch.setattr(storage, "presigned_url", fake)
    return seen


def test_the_event_is_offered() -> None:
    assert service.RECORDING_READY_EVENT == "call.recording_ready"
    assert service.RECORDING_READY_EVENT in service.EVENT_TYPES
    assert service.RECORDING_READY_EVENT in service.RECORDING_LINK_EVENTS
    # A spreadsheet cannot hold a link that dies in minutes: no column layout, so the
    # Sheets route refuses the subscription.
    assert service.RECORDING_READY_EVENT not in service.DEFAULT_SHEET_COLUMNS
    assert service.RECORDING_READY_EVENT in service.WEBHOOK_ONLY_EVENTS


async def test_the_delivery_carries_a_fresh_link_and_the_call_as_it_is_now(
    monkeypatch: pytest.MonkeyPatch, presign: list[int]
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_recording_url=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)

    outcome, (body,), _ = await _deliver(monkeypatch, tenant_id, endpoint_id, call_id)

    assert outcome == "delivered 200"
    assert body["call_id"] == str(call_id)
    assert body["duration_s"] == 42
    assert body["lead_id"] is None
    assert body["recording_url"].startswith(f"https://store.example/{RECORDING_KEY}")
    assert presign == [storage.PRESIGN_TTL_S]
    assert "phone" not in body and "from_e164" not in body


async def test_a_withdrawn_opt_in_skips_the_delivery_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, presign: list[int]
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_recording_url=False)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)

    outcome, sent, delivery_id = await _deliver(monkeypatch, tenant_id, endpoint_id, call_id)

    assert outcome == "skipped recording_opt_in_withdrawn"
    assert sent == []
    assert await _delivery_row(delivery_id) == ("skipped", "recording_opt_in_withdrawn")


async def test_a_recording_gone_since_the_event_skips_the_delivery(
    monkeypatch: pytest.MonkeyPatch, presign: list[int]
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_recording_url=True)
    call_id = await _completed_call(tenant_id, recording_key=None)

    outcome, sent, delivery_id = await _deliver(monkeypatch, tenant_id, endpoint_id, call_id)

    assert outcome == "skipped recording_unavailable"
    assert sent == []
    assert presign == [], "no key, so nothing is signed"
    assert await _delivery_row(delivery_id) == ("skipped", "recording_unavailable")


def test_the_dedupe_key_names_the_call_and_the_endpoint() -> None:
    endpoint_id = uuid.uuid4()
    call_id = str(uuid.uuid4())
    key = service.recording_ready_dedupe_key(call_id=call_id, endpoint_id=endpoint_id)
    assert key == f"recording-ready:{call_id}:{endpoint_id}"
    with pytest.raises(ValueError):
        service.recording_ready_dedupe_key(call_id="", endpoint_id=endpoint_id)


# --- the registration gate (unit, no live request) -------------------------------------


def _body(events: list[str], **kw: bool) -> CreateEndpointIn:
    return CreateEndpointIn.model_validate(
        {"url": "https://crm.example/hook", "events": events, **kw}
    )


def test_recording_ready_without_the_link_opt_in_is_refused() -> None:
    with pytest.raises(ProblemError) as exc:
        assert_recording_ready_has_its_opt_in(_body(["call.recording_ready"]))
    assert exc.value.code == "recording_ready_requires_recording_url"


def test_recording_ready_with_the_link_opt_in_is_accepted() -> None:
    assert_recording_ready_has_its_opt_in(
        _body(["call.recording_ready"], include_recording_url=True)
    )


def test_other_events_need_no_link_opt_in() -> None:
    assert_recording_ready_has_its_opt_in(_body(["lead.created", "call.completed"]))
