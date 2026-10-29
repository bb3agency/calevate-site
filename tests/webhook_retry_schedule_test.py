"""A signed webhook's own retry schedule, "Send again", and in-place secret rotation.

1. A transient failure leaves the delivery `retrying` with a `next_attempt_at` on
   `service.WEBHOOK_RETRY_SCHEDULE`, waited out in the database, and the sweep
   `retry_outbound_deliveries` re-enqueues it from the outbox message that holds its body,
   under the same delivery id and with its attempt number.
2. A delivery that finally failed can be sent again by the client, once, and only while its
   body is still held.
3. A rotated endpoint signs every delivery with both secrets until the window closes, and
   a receiver holding either one verifies it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from apps.api.main import app
from apps.workers import outbound_webhooks
from apps.workers.outbound_webhooks import deliver_outbound_webhook, retry_outbound_deliveries
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.delivery_payload_route_test import _tenant


def _auth(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _endpoint(tenant_id: uuid.UUID, *, kind: str = "webhook") -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, :kind, "
                "'https://crm.example/h', 'whsec_old', ARRAY['lead.created'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id, "kind": kind},
        )
    return endpoint_id


async def _queued(tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> tuple[uuid.UUID, dict[str, Any]]:
    """The outbox message the fan-out would have written for one delivery."""
    message_id = uuid7()
    payload = {
        "tenant_id": str(tenant_id),
        "endpoint_id": str(endpoint_id),
        "event": "lead.created",
        "data": {"lead_id": str(uuid7()), "name": "Ravi"},
        "delivery_id": str(uuid7()),
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "created_at, updated_at) VALUES (:i, 'default', 'deliver_outbound_webhook', "
                "CAST(:p AS jsonb), 'published', 1, now(), now())"
            ),
            {"i": message_id, "p": json.dumps(payload)},
        )
    return message_id, payload


async def _row(delivery_id: str) -> Any:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at, outbox_message_id, reason "
                    "FROM webhook_deliveries WHERE id = :i"
                ),
                {"i": uuid.UUID(delivery_id)},
            )
        ).one()


def _answering(monkeypatch: pytest.MonkeyPatch, *statuses: int) -> list[dict[str, Any]]:
    """`service.deliver` answering each attempt with the next status; records the calls."""
    seen: list[dict[str, Any]] = []
    queue = list(statuses)

    async def deliver(**kwargs: Any) -> service.DeliveryResult:
        seen.append(kwargs)
        status = queue.pop(0)
        return service.DeliveryResult(
            delivered=200 <= status < 300,
            status_code=status,
            error=None if status < 300 else f"HTTP {status}",
        )

    monkeypatch.setattr(service, "deliver", deliver)
    monkeypatch.setattr(outbound_webhooks, "alert", lambda *a, **k: None)
    return seen


def _capture_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict[str, Any], str]]:
    enqueued: list[tuple[dict[str, Any], str]] = []

    async def enqueue(job: str, payload: dict[str, Any], *, job_id: str) -> str:
        assert job == "deliver_outbound_webhook"
        enqueued.append((payload, job_id))
        return job_id

    monkeypatch.setattr(outbound_webhooks, "enqueue", enqueue)
    return enqueued


def _mine(
    enqueued: list[tuple[dict[str, Any], str]], payload: dict[str, Any]
) -> list[tuple[dict[str, Any], str]]:
    return [item for item in enqueued if item[0]["delivery_id"] == payload["delivery_id"]]


async def _make_due(delivery_id: str) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE webhook_deliveries SET next_attempt_at = now() - interval '1 second' "
                "WHERE id = :i"
            ),
            {"i": uuid.UUID(delivery_id)},
        )


async def test_a_transient_failure_waits_as_a_row_and_the_sweep_sends_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    seen = _answering(monkeypatch, 503, 200)
    enqueued = _capture_enqueue(monkeypatch)

    before = datetime.now(UTC)
    outcome = await deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    assert outcome.startswith("retry 2 at"), outcome
    status, attempts, next_at, recorded_message, _reason = await _row(payload["delivery_id"])
    assert (status, attempts, recorded_message) == ("retrying", 1, message_id)
    wait = service.WEBHOOK_RETRY_SCHEDULE[0]
    assert before + wait <= next_at <= datetime.now(UTC) + wait

    # Not due yet: the sweep leaves it alone. (The sweep is global, so this file asserts
    # on its own delivery rather than on counts other tests' rows can move.)
    await retry_outbound_deliveries({})
    assert _mine(enqueued, payload) == []
    await _make_due(payload["delivery_id"])
    await retry_outbound_deliveries({})
    ((again, job_id),) = _mine(enqueued, payload)
    assert again == {**payload, "attempt": 2}, "same body, same delivery id, the next attempt"
    assert job_id == f"deliver_outbound_webhook:retry:{payload['delivery_id']}:2"
    await retry_outbound_deliveries({})
    assert len(_mine(enqueued, payload)) == 1, "claimed once"

    assert await deliver_outbound_webhook({"job_try": 1, "job_id": job_id}, again) == (
        "delivered 200"
    )
    status, attempts, next_at, _message, _reason = await _row(payload["delivery_id"])
    assert (status, attempts, next_at) == ("delivered", 2, None)
    assert len(seen) == 2


async def test_a_claimed_retry_whose_attempt_never_reports_is_claimed_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry attempt that dies without recording an outcome (a non-`Retry` exception, a
    `job_timeout`) must not leave the delivery `retrying` with no next attempt: no sweep
    would read it and "Send again" refuses anything but `failed`."""
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 503)
    enqueued = _capture_enqueue(monkeypatch)
    await deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    await _make_due(payload["delivery_id"])

    before = datetime.now(UTC)
    await retry_outbound_deliveries({})
    assert len(_mine(enqueued, payload)) == 1
    status, attempts, next_at, _message, _reason = await _row(payload["delivery_id"])
    assert (status, attempts) == ("retrying", 1)
    assert next_at is not None, "the claim is a lease, not a cleared slot"
    assert next_at >= before + service.RETRY_CLAIM_LEASE

    # The enqueued attempt is lost before it records anything; once the lease lapses the
    # sweep sends the same attempt again.
    await _make_due(payload["delivery_id"])
    await retry_outbound_deliveries({})
    first, second = _mine(enqueued, payload)
    assert first == second, "same body, same delivery id, same attempt, same job id"


async def test_the_schedule_spans_about_a_day_and_the_last_attempt_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert service.WEBHOOK_MAX_ATTEMPTS == 8
    assert sum(service.WEBHOOK_RETRY_SCHEDULE, timedelta()) > timedelta(hours=24)
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    _message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 503)
    fired: list[str] = []
    monkeypatch.setattr(outbound_webhooks, "alert", lambda stage, code, **k: fired.append(code))

    outcome = await deliver_outbound_webhook(
        {"job_try": 1}, {**payload, "attempt": service.WEBHOOK_MAX_ATTEMPTS}
    )
    assert outcome == f"exhausted after {service.WEBHOOK_MAX_ATTEMPTS}"
    assert fired == ["outbound_webhook_exhausted"]
    status, _attempts, next_at, _message, _reason = await _row(payload["delivery_id"])
    assert (status, next_at) == ("failed", None)


async def test_a_due_retry_whose_body_was_erased_ends_failed_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 503)
    enqueued = _capture_enqueue(monkeypatch)
    await deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM outbox_messages WHERE id = :i"), {"i": message_id})
    await _make_due(payload["delivery_id"])

    await retry_outbound_deliveries({})
    assert _mine(enqueued, payload) == []
    status, _attempts, _next, _message, reason = await _row(payload["delivery_id"])
    assert (status, reason) == ("failed", "delivery_body_not_held")


async def test_a_failed_delivery_can_be_sent_again_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, slug, token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    message_id, payload = await _queued(tenant_id, endpoint_id)
    _answering(monkeypatch, 400)
    enqueued = _capture_enqueue(monkeypatch)
    # A 400 is not retried: it fails at once.
    await deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"deliver_outbound_webhook:{message_id}"}, payload
    )
    delivery_id = payload["delivery_id"]

    async with _client() as http:
        listed = await http.get("/v1/integrations/deliveries", headers=_auth(slug, token))
        (row,) = [d for d in listed.json() if d["id"] == delivery_id]
        assert row["status"] == "failed" and row["resendable"] is True

        sent = await http.post(
            f"/v1/integrations/deliveries/{delivery_id}/resend", headers=_auth(slug, token)
        )
        assert sent.status_code == 202, sent.text
        twice = await http.post(
            f"/v1/integrations/deliveries/{delivery_id}/resend", headers=_auth(slug, token)
        )
        assert twice.status_code == 409 and twice.json()["type"].endswith("/delivery_not_failed")

        listed = await http.get("/v1/integrations/deliveries", headers=_auth(slug, token))
        (row,) = [d for d in listed.json() if d["id"] == delivery_id]
        assert row["status"] == "retrying" and row["resendable"] is False

    await retry_outbound_deliveries({})
    ((again, _job_id),) = _mine(enqueued, payload)
    assert again["delivery_id"] == delivery_id and again["attempt"] == 2
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'webhook_delivery.resent' "
                    "AND object_id = :i"
                ),
                {"i": delivery_id},
            )
        ).scalar_one()
    assert audited == 1


async def test_a_delivery_whose_body_is_gone_cannot_be_sent_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    delivery_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            status="failed",
            attempts=8,
            status_code=503,
        )
    async with _client() as http:
        refused = await http.post(
            f"/v1/integrations/deliveries/{delivery_id}/resend", headers=_auth(slug, token)
        )
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/delivery_body_not_held")


async def test_a_neighbour_cannot_send_my_delivery_again() -> None:
    tenant_id, _slug, _token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    delivery_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            status="failed",
            attempts=1,
            status_code=400,
        )
    _other, slug_b, token_b = await _tenant()
    async with _client() as http:
        refused = await http.post(
            f"/v1/integrations/deliveries/{delivery_id}/resend", headers=_auth(slug_b, token_b)
        )
    assert refused.status_code == 404


# --- in-place secret rotation ----------------------------------------------------


def test_both_secrets_sign_during_a_rotation_and_either_verifies() -> None:
    timestamp = str(int(datetime.now(UTC).timestamp()))
    header = service.sign_payload(
        "whsec_new", timestamp=timestamp, body="{}", previous_secret="whsec_old"
    )
    assert header.count("v1=") == 2 and header.startswith(f"t={timestamp},v1=")
    assert service.verify_signature("whsec_new", header=header, body="{}")
    assert service.verify_signature("whsec_old", header=header, body="{}")
    assert not service.verify_signature("whsec_other", header=header, body="{}")
    assert not service.verify_signature("whsec_old", header=header, body='{"x":1}')
    # Outside a rotation, one signature, as before.
    assert service.sign_payload("whsec_new", timestamp=timestamp, body="{}").count("v1=") == 1


async def test_rotation_signs_with_both_secrets_until_the_window_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    async with _client() as http:
        rotated = await http.post(
            f"/v1/integrations/endpoints/{endpoint_id}/rotate-secret",
            headers=_auth(slug, token),
            json={},
        )
        assert rotated.status_code == 200, rotated.text
        body = rotated.json()
        listed = await http.get("/v1/integrations/endpoints", headers=_auth(slug, token))

    new_secret = body["secret"]
    assert new_secret != "whsec_old"
    expires = datetime.fromisoformat(body["previous_secret_expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)
    (endpoint,) = [e for e in listed.json() if e["id"] == str(endpoint_id)]
    assert endpoint["secret_fingerprint"] == service.secret_fingerprint(new_secret)
    assert endpoint["previous_secret_expires_at"] is not None

    async with tenant_session(tenant_id) as session:
        loaded = await service.load_endpoint(session, endpoint_id)
    assert loaded is not None
    assert (loaded["secret"], loaded["previous_secret"]) == (new_secret, "whsec_old")

    # The window closed: the old secret signs nothing.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE outbound_webhooks SET previous_secret_expires_at = now() - "
                "interval '1 minute' WHERE id = :i"
            ),
            {"i": endpoint_id},
        )
        loaded = await service.load_endpoint(session, endpoint_id)
    assert loaded is not None and loaded["previous_secret"] is None

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = "
                    "'integration_endpoint.secret_rotated' AND object_id = :i"
                ),
                {"i": str(endpoint_id)},
            )
        ).scalar_one()
    assert audited == 1


async def test_a_zero_grace_rotation_retires_the_old_secret_at_once() -> None:
    tenant_id, slug, token = await _tenant()
    endpoint_id = await _endpoint(tenant_id)
    async with _client() as http:
        rotated = await http.post(
            f"/v1/integrations/endpoints/{endpoint_id}/rotate-secret",
            headers=_auth(slug, token),
            json={"grace_minutes": 0},
        )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["previous_secret_expires_at"] is None
    async with tenant_session(tenant_id) as session:
        loaded = await service.load_endpoint(session, endpoint_id)
    assert loaded is not None and loaded["previous_secret"] is None


async def test_a_sheets_destination_has_no_secret_to_rotate() -> None:
    tenant_id, slug, token = await _tenant()
    endpoint_id = await _endpoint(tenant_id, kind="google_sheets")
    async with _client() as http:
        refused = await http.post(
            f"/v1/integrations/endpoints/{endpoint_id}/rotate-secret",
            headers=_auth(slug, token),
            json={},
        )
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"].endswith("/endpoint_secret_not_rotatable")
