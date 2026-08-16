"""Outbound CRM sync (D-23) and the outbox claim it rides on.

What these tests are actually protecting:

- **A signature that survives replay.** The timestamp is inside the signed string, so a
  captured request cannot be replayed once the receiver's window closes, and a valid
  signature cannot be moved onto a fresh timestamp.
- **No delivery without a committed write.** The event is enqueued in the caller's
  transaction; a rollback takes the outbox row with it.
- **No un-redacted phone numbers leaving our boundary by default.**
- **A forensic row per delivery, not per attempt**, scoped to the tenant through their
  own endpoint rows.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from apps.api.reliability.service import claim_outbox_batch, enqueue_outbox
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from arq import Retry
from sqlalchemy import text

SECRET = "whsec_test_secret_value"


async def _tenant_with_endpoint(
    *, events: tuple[str, ...] = ("lead.created",), url: str = "https://crm.example/hook"
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Sync Clinic",
        slug=f"sync-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
                ":events, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": url,
                "secret": SECRET,
                "events": list(events),
            },
        )
    return tenant_id, endpoint_id


# ------------------------------------------------------------------- signature


def test_the_signature_covers_the_timestamp_so_a_replay_expires() -> None:
    body = json.dumps({"event": "lead.created"})
    now = str(int(datetime.now(UTC).timestamp()))
    header = service.sign_payload(SECRET, timestamp=now, body=body)

    assert service.verify_signature(SECRET, header=header, body=body)
    assert not service.verify_signature("wrong-secret", header=header, body=body)
    assert not service.verify_signature(SECRET, header=header, body=body + " ")

    # The captured request, replayed an hour later.
    old = str(int(datetime.now(UTC).timestamp()) - 3600)
    stale = service.sign_payload(SECRET, timestamp=old, body=body)
    assert not service.verify_signature(SECRET, header=stale, body=body)

    # And the signature cannot be moved onto a fresh timestamp, because the timestamp
    # is inside the signed string rather than beside it.
    forged = f"t={now},v1={stale.split('v1=')[1]}"
    assert not service.verify_signature(SECRET, header=forged, body=body)


def test_a_malformed_signature_header_is_rejected_not_crashed() -> None:
    body = "{}"
    for header in ("", "garbage", "t=abc,v1=zz", "v1=deadbeef", "t=123"):
        assert service.verify_signature(SECRET, header=header, body=body) is False


def test_the_envelope_keys_on_the_delivery_not_the_object() -> None:
    """A receiver deduplicating on `id` must collapse RETRIES, not two real updates."""
    lead_id, tenant_id = uuid7(), uuid7()
    first = service.build_envelope(
        event="lead.updated",
        tenant_id=tenant_id,
        delivery_id=uuid7(),
        data={"lead_id": str(lead_id)},
    )
    second = service.build_envelope(
        event="lead.updated",
        tenant_id=tenant_id,
        delivery_id=uuid7(),
        data={"lead_id": str(lead_id)},
    )
    assert first["id"] != second["id"], "two updates to one lead are two deliveries"
    assert first["data"]["lead_id"] == second["data"]["lead_id"]
    assert first["account_id"] == str(tenant_id)


def test_a_phone_number_does_not_leave_unmasked_by_default() -> None:
    masked = service.lead_payload(
        {"lead_id": "x", "phone": "+919876500001", "name": "Priya"}, include_raw_phone=False
    )
    raw = service.lead_payload(
        {"lead_id": "x", "phone": "+919876500001", "name": "Priya"}, include_raw_phone=True
    )
    assert masked["phone"] != "+919876500001"
    assert "9876500001" not in str(masked["phone"])
    assert raw["phone"] == "+919876500001", "the opt-in is a real opt-in"


def test_field_mapping_renames_and_never_invents_nulls() -> None:
    data = {"lead_id": "1", "name": "Priya", "phone": "+91…"}
    mapped = service.apply_mapping(data, {"name": "Full_Name", "budget": "Budget__c"})
    assert mapped == {"Full_Name": "Priya"}, "a mapped-but-absent field is omitted, not null"
    assert service.apply_mapping(data, {}) == data, "no mapping means our own names"


# ------------------------------------------------------------------ enqueue


async def test_an_event_fans_out_one_outbox_row_per_subscribed_endpoint() -> None:
    tenant_id, endpoint_id = await _tenant_with_endpoint(events=("lead.created", "call.completed"))
    async with tenant_session(tenant_id) as session:
        # A second endpoint that did NOT subscribe to this event.
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :s, "
                ":events, true, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "url": "https://other.example/hook",
                "s": SECRET,
                "events": ["campaign.completed"],
            },
        )
        fanned = await service.enqueue_event(
            session, tenant_id=tenant_id, event="lead.created", data={"lead_id": "1"}
        )

    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages "
                        "WHERE job = 'deliver_outbound_webhook' "
                        "AND payload->>'tenant_id' = :t"
                    ),
                    {"t": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )

    assert fanned == 1, "only the subscribed endpoint"
    assert len(rows) == 1
    assert rows[0]["endpoint_id"] == str(endpoint_id)
    assert rows[0]["delivery_id"], "the delivery id is minted at enqueue, not per attempt"


async def test_an_unknown_event_name_is_refused_rather_than_silently_dropped() -> None:
    tenant_id, _ = await _tenant_with_endpoint()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError):
            await service.enqueue_event(
                session, tenant_id=tenant_id, event="lead.exploded", data={}
            )


async def test_a_rolled_back_write_delivers_nothing() -> None:
    """The whole point of the outbox: the CRM cannot hear about a lead that does not
    exist, because the event row and the domain row share one transaction."""
    tenant_id, _ = await _tenant_with_endpoint()
    marker = uuid.uuid4().hex

    try:
        async with tenant_session(tenant_id) as session:
            await service.enqueue_event(
                session, tenant_id=tenant_id, event="lead.created", data={"marker": marker}
            )
            raise RuntimeError("the domain write failed after the event was enqueued")
    except RuntimeError:
        pass

    async with untenanted_session() as session:
        found = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE payload->'data'->>'marker' = :m"),
                {"m": marker},
            )
        ).scalar()
    assert found == 0, "the rollback took the pending delivery with it"


# ------------------------------------------------------------------ delivery


class _Recorder:
    """A stand-in receiver. Captures what we actually put on the wire."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json={"ok": True})


async def test_a_delivered_event_is_signed_verifiable_and_logged() -> None:
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    recorder = _Recorder()
    delivery_id = uuid7()

    envelope = service.build_envelope(
        event="lead.created",
        tenant_id=tenant_id,
        delivery_id=delivery_id,
        data={"lead_id": "1", "phone": "+91XXXXXXXX01"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)) as client:
        result = await service.deliver(
            url="https://crm.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope=envelope,
            client=client,
        )

    assert result.delivered and result.status_code == 200
    request = recorder.requests[0]
    body = request.content.decode()
    assert service.verify_signature(
        SECRET, header=request.headers[service.SIGNATURE_HEADER], body=body
    ), "the receiver can verify exactly what we sent"
    assert request.headers[service.EVENT_HEADER] == "lead.created"
    assert request.headers[service.DELIVERY_HEADER] == str(delivery_id)

    async with tenant_session(tenant_id) as session:
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            status="delivered",
            attempts=1,
            status_code=200,
        )
        # A retry of the SAME delivery updates the row rather than adding one.
        await service.record_delivery(
            session,
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            event="lead.created",
            status="delivered",
            attempts=2,
            status_code=200,
        )
        rows = (
            await session.execute(
                text("SELECT status, attempts FROM webhook_deliveries WHERE id = :id"),
                {"id": delivery_id},
            )
        ).all()
    assert rows == [("delivered", 2)], "one forensic row per delivery, not per attempt"


async def test_a_non_2xx_response_is_a_failure_the_outbox_will_retry() -> None:
    recorder = _Recorder(status_code=500)
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)) as client:
        result = await service.deliver(
            url="https://crm.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7())},
            client=client,
        )
    assert not result.delivered
    assert result.status_code == 500


async def test_a_connection_error_reports_the_type_and_never_the_body() -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
        result = await service.deliver(
            url="https://crm.example/hook",
            secret=SECRET,
            event="lead.created",
            envelope={"id": str(uuid7()), "data": {"phone": "+919876500001"}},
            client=client,
        )
    assert not result.delivered
    assert result.error == "ConnectTimeout"
    assert "9876500001" not in str(result.error)


async def test_a_deactivated_endpoint_is_skipped_not_retried_forever() -> None:
    """The client turned it off between enqueue and delivery. That is a decision, not
    an outage — retrying against it would be noise until the DLQ."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE outbound_webhooks SET active = false WHERE id = :id"),
            {"id": endpoint_id},
        )

    delivery_id = uuid7()
    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": "1"},
            "delivery_id": str(delivery_id),
        },
    )
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM webhook_deliveries WHERE id = :id"), {"id": delivery_id}
            )
        ).scalar()
    assert outcome == "endpoint_inactive"
    assert status == "skipped", "recorded, so the client can see why nothing arrived"


async def test_delivery_rows_are_scoped_to_the_tenants_own_endpoints() -> None:
    """`webhook_deliveries` has no RLS policy by design (engine events arrive before a
    tenant is known), so the client-facing query has to scope THROUGH the endpoint
    table, which does. This test is that guarantee."""
    tenant_a, endpoint_a = await _tenant_with_endpoint()
    tenant_b, endpoint_b = await _tenant_with_endpoint()

    for tenant_id, endpoint_id in ((tenant_a, endpoint_a), (tenant_b, endpoint_b)):
        async with tenant_session(tenant_id) as session:
            await service.record_delivery(
                session,
                delivery_id=uuid7(),
                endpoint_id=endpoint_id,
                event="lead.created",
                status="delivered",
                attempts=1,
                status_code=200,
            )

    scoped_sql = (
        "SELECT count(*) FROM webhook_deliveries d WHERE d.direction = 'out' "
        "AND d.endpoint_id IN (SELECT id FROM outbound_webhooks)"
    )
    async with tenant_session(tenant_a) as session:
        seen_by_a = (await session.execute(text(scoped_sql))).scalar()
    async with tenant_session(tenant_b) as session:
        seen_by_b = (await session.execute(text(scoped_sql))).scalar()

    assert seen_by_a == 1 and seen_by_b == 1, "each tenant sees exactly its own"


# ------------------------------------------------------------------ outbox claim


async def test_the_outbox_claim_respects_its_limit_when_timestamps_tie() -> None:
    """Regression, same shape as the campaign claim: rows enqueued in ONE transaction
    share `created_at` to the microsecond, and `WHERE id IN (SELECT ... LIMIT n)` let
    the planner rescan the subquery and return more than n."""
    async with untenanted_session() as session:
        for _ in range(12):
            await enqueue_outbox(
                session,
                job="deliver_outbound_webhook",
                payload={"marker": "batch-limit-test"},
            )

    async with untenanted_session() as session:
        claimed = await claim_outbox_batch(session, limit=5)
    assert len(claimed) == 5, f"the batch limit is a limit, got {len(claimed)}"


async def test_two_dispatchers_running_at_once_never_claim_the_same_message() -> None:
    """SKIP LOCKED's actual promise, which is about CONCURRENT transactions.

    Sequential claims legitimately re-see a row — nothing has marked it published yet,
    and that is the retry path working. The guarantee worth testing is that two
    dispatchers whose transactions OVERLAP cannot both take the same message, because
    that is the case that would double-deliver to a client's CRM.
    """
    async with untenanted_session() as session:
        for _ in range(6):
            await enqueue_outbox(
                session,
                job="deliver_outbound_webhook",
                payload={"marker": "concurrent"},
            )

    started = asyncio.Event()

    async def claimer(first: bool) -> set[Any]:
        async with untenanted_session() as session:
            batch = await claim_outbox_batch(session, limit=3)
            if first:
                # Hold the transaction open so the second claimer runs against our locks.
                started.set()
                await asyncio.sleep(0.25)
            else:
                await started.wait()
            return {m.id for m in batch}

    left, right = await asyncio.gather(claimer(True), claimer(False))
    assert not (left & right), "overlapping dispatchers took the same message"
    assert left and right, "both dispatchers should still find work to do"


async def test_the_last_allowed_try_knows_it_is_the_last(monkeypatch) -> None:
    """Regression from the runbook audit: the worker's exhaustion threshold said 5
    while ARQ's real budget said 3, so ARQ stopped retrying before the worker ever
    considered itself exhausted — and the `outbound_webhook_exhausted` alert could
    not fire. The two numbers must be the same object, not coincidentally equal.

    The earlier version of this test then handed the worker `{"job_try": 3}` directly,
    which is the one thing it must never do. `job_try` is arq's to write, and injecting
    it asserted only that an `if` compares two integers — it could not, and did not,
    notice that arq never retried the job at all, so the branch it was "covering" was
    unreachable in production. The real ladder is exercised in
    `tests/reliability_audit_test.py::test_a_raising_job_is_actually_retried_by_a_real_worker`,
    on a real worker with a real attempt count. What is left here is the part that IS a
    pure unit question: given that this is the last try, does the job give up loudly?
    """
    from apps.api.core.queue import WORKER_MAX_TRIES
    from apps.workers.settings import WorkerSettings

    assert service.MAX_ATTEMPTS is WORKER_MAX_TRIES, "one budget, one source"
    assert WorkerSettings.max_tries is WORKER_MAX_TRIES
    assert WorkerSettings.retry_jobs is True, "max_tries means nothing without retries on"

    # The budget must leave room for the backoff curve to have a step per retry.
    from apps.workers.outbound_webhooks import RETRY_BACKOFF_S

    assert len(RETRY_BACKOFF_S) == WORKER_MAX_TRIES - 1, "one wait per retry, none after the last"

    tenant_id, endpoint_id = await _tenant_with_endpoint(url="https://down.example/hook")
    fired: list[str] = []
    monkeypatch.setattr(
        "apps.workers.outbound_webhooks.alert",
        lambda stage, code, **kw: fired.append(code),
    )

    async def refuse(**kwargs: Any) -> service.DeliveryResult:
        return service.DeliveryResult(delivered=False, status_code=503, error="HTTP 503")

    monkeypatch.setattr("apps.api.integrations.service.deliver", refuse)

    from apps.workers.outbound_webhooks import deliver_outbound_webhook

    payload = {
        "tenant_id": str(tenant_id),
        "endpoint_id": str(endpoint_id),
        "event": "lead.created",
        "data": {"lead_id": "1"},
        "delivery_id": str(uuid7()),
    }

    # Not the last try: the job must ASK for a retry, in the only way arq honours.
    with pytest.raises(Retry):
        await deliver_outbound_webhook({"job_try": 1}, payload)
    assert fired == [], "a retryable failure is not an incident yet"

    # The last try: alert and STOP, rather than ask for a retry that will never come.
    outcome = await deliver_outbound_webhook({"job_try": WORKER_MAX_TRIES}, payload)
    assert outcome == f"exhausted after {WORKER_MAX_TRIES}"
    assert fired == ["outbound_webhook_exhausted"], "the alert fires on the real last try"


async def test_a_rejected_delivery_is_not_retried_at_all(monkeypatch) -> None:
    """A 400 is a verdict on the request, not a blip. Retrying it three times only
    delays the `failed` row the webhook-activity screen shows and hammers an endpoint
    that has already said no — but giving up silently would be worse than either."""
    tenant_id, endpoint_id = await _tenant_with_endpoint(url="https://picky.example/hook")
    fired: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "apps.workers.outbound_webhooks.alert",
        lambda stage, code, **kw: fired.append((code, kw.get("detail"))),
    )

    async def reject(**kwargs: Any) -> service.DeliveryResult:
        return service.DeliveryResult(delivered=False, status_code=400, error="HTTP 400")

    monkeypatch.setattr("apps.api.integrations.service.deliver", reject)

    from apps.workers.outbound_webhooks import deliver_outbound_webhook

    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": "1"},
            "delivery_id": str(uuid7()),
        },
    )
    assert outcome == "rejected 400", "a permanent rejection returns rather than retrying"
    assert [code for code, _ in fired] == ["outbound_webhook_exhausted"]
    assert "permanent" in (fired[0][1] or ""), "and the alert says WHY we stopped"
