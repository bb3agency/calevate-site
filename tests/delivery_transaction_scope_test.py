"""No pooled connection is held while a client's own CRM is answering (D-182, R-5).

THE DEFECT. `deliver_outbound_webhook` opened one `tenant_session` and did everything
inside it: load the endpoint, POST to the client's endpoint (`DELIVERY_TIMEOUT_S = 10`),
PUT the retained body to object storage, write the delivery row. A receiver that answers
in nine seconds — overloaded, not down, which is the ordinary shape — therefore parked one
connection per in-flight job, inside an OPEN TRANSACTION, for nine seconds. arq's default
`max_jobs` is 10 against a 16-connection pool whose overflow is 1, so ten slow deliveries
starve everything else the worker fleet owes: the post-call pipeline, the nightly sweeps,
and the 30-second campaign dispatch tick, which then overruns and fires
`dispatch_tick_overrun`. The alarm names the dispatcher; the cause is one client's CRM.

WHY THE POOL'S OWN COUNTER IS THE ASSERTION. The property is "nothing is checked out while
we wait", and `pool.checkedout()` is that sentence in the pool's own words — a test that
asserted on elapsed time or on statement order would pass a restructure that still held
the connection. The counter is process-wide, which is safe here and nowhere near safe in
general: these tests hold no session of their own across the call they measure, and the
suite runs one coroutine at a time.

The behaviour these tests must not buy: every existing delivery assertion — the row, the
retained body, the retry ladder, the sheets duplicate guard — still holds, and lives where
it already lived (`delivery_body_retention_test`, `sheets_sync_test`, `outbound_sync_test`).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import get_engine, tenant_session
from apps.api.integrations import service
from apps.workers import storage
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from sqlalchemy import text
from tests.conftest import FakeS3

SECRET = "whsec_transaction_scope_secret"
ENDPOINT_URL = "https://crm.example/hook"


def _checked_out() -> int:
    """Connections this process currently holds off the pool."""
    return int(get_engine().pool.checkedout())


async def _tenant_with_endpoint(kind: str = "webhook") -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Scope Clinic",
        slug=f"scope-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, :kind, :url, :secret, "
                ":events, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "kind": kind,
                "url": ENDPOINT_URL,
                "secret": SECRET,
                "events": ["lead.created"],
            },
        )
    return tenant_id, endpoint_id


async def _run(tenant_id: UUID, endpoint_id: UUID, *, delivery_id: UUID | None = None) -> str:
    return await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": "lead.created",
            "data": {"lead_id": str(uuid7()), "name": "Priya"},
            "delivery_id": str(delivery_id or uuid7()),
        },
    )


async def _delivery_row(tenant_id: UUID, delivery_id: UUID) -> tuple[str, int] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts FROM webhook_deliveries WHERE id = :id "
                    "AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
                ),
                {"id": delivery_id},
            )
        ).first()
    return (str(row[0]), int(row[1])) if row is not None else None


async def test_nothing_is_checked_out_while_the_receiver_is_answering(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT, as the one fact that decides it: what the pool says mid-POST."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    held: list[int] = []

    async def slow_receiver(**kwargs: Any) -> service.DeliveryResult:
        held.append(_checked_out())
        return service.DeliveryResult(
            delivered=True,
            status_code=200,
            error=None,
            channel="http",
            sent_body=json.dumps({"ok": True}),
        )

    monkeypatch.setattr(service, "deliver", slow_receiver)

    delivery_id = uuid7()
    outcome = await _run(tenant_id, endpoint_id, delivery_id=delivery_id)

    assert held == [0], (
        "a pooled connection was held across the POST to the client's CRM — ten slow "
        "receivers park ten of the worker's sixteen connections and the campaign dispatch "
        "tick starves behind them"
    )
    # And the outcome still lands: a fix that dropped the write would pass the line above.
    assert outcome == "delivered 200"
    assert await _delivery_row(tenant_id, delivery_id) == ("delivered", 1)


async def test_nothing_is_checked_out_while_the_body_is_being_stored(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The object-store PUT is the second network leg, and it was inside the same
    transaction. Best-effort work must not hold a connection any more than the delivery
    it documents."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    held: list[int] = []
    real_store = storage.store_delivery_body

    async def watching_store(**kwargs: Any) -> str | None:
        held.append(_checked_out())
        return await real_store(**kwargs)

    monkeypatch.setattr(storage, "store_delivery_body", watching_store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    real_deliver = service.deliver

    async def routed(**kwargs: Any) -> service.DeliveryResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await real_deliver(**{**kwargs, "client": client})

    monkeypatch.setattr(service, "deliver", routed)

    await _run(tenant_id, endpoint_id)

    assert held == [0]


async def test_a_failed_delivery_still_records_its_reason(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure path writes in the SECOND transaction, and the retry ladder reads that
    row. Splitting the session is only safe if the row still arrives on this branch."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()

    async def refusing(**kwargs: Any) -> service.DeliveryResult:
        return service.DeliveryResult(
            delivered=False,
            status_code=404,
            error="http_404",
            channel="http",
            sent_body=json.dumps({"ok": False}),
        )

    monkeypatch.setattr(service, "deliver", refusing)

    delivery_id = uuid7()
    outcome = await _run(tenant_id, endpoint_id, delivery_id=delivery_id)

    assert outcome == "rejected 404"
    assert await _delivery_row(tenant_id, delivery_id) == ("failed", 1)


async def test_an_endpoint_that_vanished_is_recorded_as_skipped(s3: FakeS3) -> None:
    """The early return now opens its OWN session — the read's transaction has closed by
    then. A restructure that forgot it would leave the client's delivery screen empty for
    an event that was genuinely dropped."""
    tenant_id, endpoint_id = await _tenant_with_endpoint()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE outbound_webhooks SET active = false WHERE id = :id"), {"id": endpoint_id}
        )

    delivery_id = uuid7()
    outcome = await _run(tenant_id, endpoint_id, delivery_id=delivery_id)

    assert outcome == "endpoint_inactive"
    assert await _delivery_row(tenant_id, delivery_id) == ("skipped", 1)
