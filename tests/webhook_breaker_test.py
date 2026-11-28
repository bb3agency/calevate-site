"""The webhook breaker, the test delivery and the delivery-log filters (D-1049, W2.5, W2.6).

- Three days of nothing but failures pauses the endpoint, once, with one notice promised.
- A short or one-off failure, a recent success, or test deliveries never trip it.
- A paused endpoint's deliveries are held, not sent; Resume replays them oldest first,
  and the failures of the streak with them.
- A test delivery is signed, says `"test": true`, is tried once and is marked in the log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import breaker, events, service
from apps.api.integrations.routes import list_deliveries
from apps.api.reliability.service import enqueue_outbox
from apps.workers import webhooks_breaker
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from sqlalchemy import text
from tests.api_security_test import _make_tenant


async def _endpoint(tenant_id: uuid.UUID, *, kind: str = "webhook") -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, :kind, "
                "'https://crm.example/hook', 'whsec_x', ARRAY['lead.created'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id, "kind": kind},
        )
    return endpoint_id


async def _delivery(
    tenant_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    *,
    status: str,
    hours_ago: float,
    last_hours_ago: float | None = None,
    test: bool = False,
    body: bool = True,
) -> uuid.UUID:
    """One recorded delivery with its outbox body, `hours_ago` old."""
    delivery_id = uuid7()
    first = datetime.now(UTC) - timedelta(hours=hours_ago)
    last = datetime.now(UTC) - timedelta(
        hours=hours_ago if last_hours_ago is None else last_hours_ago
    )
    async with tenant_session(tenant_id) as session:
        message_id = await enqueue_outbox(
            session,
            job=service.OUTBOUND_WEBHOOK_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "endpoint_id": str(endpoint_id),
                "event": "lead.created",
                "data": {"lead_id": str(uuid7())},
                "delivery_id": str(delivery_id),
            }
            if body
            else {},
        )
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, direction, event_type, status, attempts, "
                "endpoint_id, outbox_message_id, is_test, first_at, last_at, created_at) "
                "VALUES (:id, 'out', 'lead.created', :status, 8, :eid, :mid, :test, :first, "
                ":last, :first)"
            ),
            {
                "id": delivery_id,
                "status": status,
                "eid": endpoint_id,
                "mid": message_id,
                "test": test,
                "first": first,
                "last": last,
            },
        )
    return delivery_id


async def _endpoint_state(tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> tuple[Any, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT paused_at, failing_since FROM outbound_webhooks WHERE id = :id"),
                {"id": endpoint_id},
            )
        ).one()
    return row[0], row[1]


async def _notices(endpoint_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'endpoint_id' = :eid"
                    ),
                    {"job": breaker.PAUSED_NOTICE_JOB, "eid": str(endpoint_id)},
                )
            ).scalar()
            or 0
        )


async def _pause(tenant_id: uuid.UUID) -> list[breaker.Paused]:
    async with tenant_session(tenant_id) as session:
        return await breaker.pause_tripped(session, tenant_id=tenant_id)


async def test_three_days_of_failures_pause_the_endpoint_once_with_one_notice() -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    await _delivery(tenant_id, endpoint_id, status="delivered", hours_ago=100)
    first = await _delivery(tenant_id, endpoint_id, status="failed", hours_ago=80)
    await _delivery(tenant_id, endpoint_id, status="retrying", hours_ago=30, last_hours_ago=1)

    (paused,) = await _pause(tenant_id)
    assert await _pause(tenant_id) == []  # a second sweep pauses nothing twice

    paused_at, since = await _endpoint_state(tenant_id, endpoint_id)
    assert paused_at is not None
    async with untenanted_session() as session:
        first_at = (
            await session.execute(
                text("SELECT first_at FROM webhook_deliveries WHERE id = :id"), {"id": first}
            )
        ).scalar()
    assert since == first_at == paused.failing_since
    assert await _notices(endpoint_id) == 1


@pytest.mark.parametrize(
    "shape",
    [
        # A success inside the window: the endpoint works.
        [("failed", 80, None), ("delivered", 10, None)],
        # One failure, however old: not a streak.
        [("failed", 90, None)],
        # Failures that began two days ago: not three days yet.
        [("failed", 48, None), ("failed", 2, None)],
        # Old failures, quiet since: nothing has failed in the last day.
        [("failed", 100, None), ("failed", 80, None)],
    ],
)
async def test_a_short_or_stale_streak_does_not_pause(
    shape: list[tuple[str, float, float | None]],
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    for status, hours, last in shape:
        await _delivery(tenant_id, endpoint_id, status=status, hours_ago=hours, last_hours_ago=last)
    assert await _pause(tenant_id) == []


async def test_test_deliveries_never_count_toward_the_streak() -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    await _delivery(tenant_id, endpoint_id, status="failed", hours_ago=80, test=True)
    await _delivery(tenant_id, endpoint_id, status="failed", hours_ago=2, test=True)
    assert await _pause(tenant_id) == []


async def test_a_paused_endpoint_holds_and_resume_replays_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    streak = await _delivery(tenant_id, endpoint_id, status="failed", hours_ago=80)
    await _delivery(tenant_id, endpoint_id, status="failed", hours_ago=20, last_hours_ago=1)
    await _pause(tenant_id)

    posted: list[str] = []

    async def fake_deliver(**kwargs: Any) -> service.DeliveryResult:
        posted.append(kwargs["envelope"]["id"])
        return service.DeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(service, "deliver", fake_deliver)
    held = uuid7()
    async with tenant_session(tenant_id) as session:
        message_id = await enqueue_outbox(
            session,
            job=service.OUTBOUND_WEBHOOK_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "endpoint_id": str(endpoint_id),
                "event": "lead.created",
                "data": {"lead_id": str(uuid7())},
                "delivery_id": str(held),
            },
        )
    outcome = await deliver_outbound_webhook(
        {"job_try": 1, "job_id": f"{service.OUTBOUND_WEBHOOK_JOB}:{message_id}"},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": str(uuid7())},
            "delivery_id": str(held),
        },
    )
    assert outcome == "held"
    assert posted == []

    async with tenant_session(tenant_id) as session:
        result = await breaker.resume_endpoint(session, endpoint_id=endpoint_id)
    assert result == breaker.Resumed(resumed=True, replayed=3)
    async with tenant_session(tenant_id) as session:
        again = await breaker.resume_endpoint(session, endpoint_id=endpoint_id)
    assert again == breaker.Resumed(resumed=False, replayed=0)
    assert await _endpoint_state(tenant_id, endpoint_id) == (None, None)

    async with untenanted_session() as session:
        order = [
            uuid.UUID(str(r[0]))
            for r in (
                await session.execute(
                    text(
                        "SELECT id FROM webhook_deliveries WHERE endpoint_id = :eid "
                        "AND status = 'retrying' ORDER BY next_attempt_at"
                    ),
                    {"eid": endpoint_id},
                )
            ).all()
        ]
    assert order[0] == streak and order[-1] == held


async def test_resume_refuses_a_deactivated_endpoint() -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    async with tenant_session(tenant_id) as session:
        await service.deactivate_endpoint(session, endpoint_id=endpoint_id)
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await breaker.resume_endpoint(session, endpoint_id=endpoint_id)
    assert refused.value.code == "endpoint_inactive"


def test_the_notice_names_the_host_never_the_address() -> None:
    words = webhooks_breaker.destination_words("webhook", "https://crm.example/in?key=SECRET")
    subject, body = webhooks_breaker.compose(business="Ravi Motors", destination=words, since=None)
    assert "crm.example" in subject and "SECRET" not in subject + body
    assert "Resume" in body
    assert webhooks_breaker.destination_words("google_sheets", None) == "your Google Sheet"


async def test_a_test_delivery_is_signed_marked_and_tried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    async with tenant_session(tenant_id) as session:
        delivery_id, event = await events.queue_test_delivery(
            session, tenant_id=tenant_id, endpoint_id=endpoint_id, event=None
        )
        payload = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE payload->>'delivery_id' = :d"),
                {"d": str(delivery_id)},
            )
        ).scalar_one()
    assert event == "lead.created" and payload["test"] is True

    sent: list[dict[str, Any]] = []

    async def failing(**kwargs: Any) -> service.DeliveryResult:
        sent.append(kwargs["envelope"])
        return service.DeliveryResult(delivered=False, status_code=503, error="HTTP 503")

    monkeypatch.setattr(service, "deliver", failing)
    outcome = await deliver_outbound_webhook({"job_try": 1}, dict(payload))
    assert outcome == "test failed"
    (envelope,) = sent
    assert envelope["test"] is True and envelope["event"] == "lead.created"
    assert envelope["data"]["name"] == "Test Lead"

    async with tenant_session(tenant_id) as session:
        rows = await list_deliveries(
            session, limit=50, _=None, endpoint_id=endpoint_id, status=None, event=None
        )
        failed = await list_deliveries(
            session, limit=50, _=None, endpoint_id=None, status="failed", event=None
        )
        none = await list_deliveries(
            session, limit=50, _=None, endpoint_id=None, status=None, event="dnc.added"
        )
    (row,) = rows
    # Failed, but no retry and no "Send again": a test is pressed again, not resent.
    assert (row.status, row.is_test, row.resendable, row.next_attempt_at) == (
        "failed",
        True,
        False,
        None,
    )
    assert [r.id for r in failed] == [delivery_id]
    assert none == []


async def test_a_test_goes_to_a_webhook_only() -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, kind="google_sheets")
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await events.queue_test_delivery(
                session, tenant_id=tenant_id, endpoint_id=endpoint_id, event="lead.created"
            )
    assert refused.value.code == "endpoint_test_webhook_only"
