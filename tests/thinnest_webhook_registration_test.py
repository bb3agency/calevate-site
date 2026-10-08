"""Per-agent webhook endpoints: registered once, sealed, re-enabled by the sweep (D-678).

The vendor is an `httpx.MockTransport` built from `thinnest-findings/mirror/pages/
api-reference/webhooks.md`: create returns `signingSecret` once (:23-40), `enabled` and
`delivery.failuresInARow` on read (:30, :48), `PATCH {enabled}` (:49, :78-80), DELETE (:50).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.core.envelope import Envelope
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_webhooks import ThinnestWebhooks, set_thinnest_webhooks
from apps.api.reliability.engine_intake_keys import open_webhook_secret
from apps.api.reliability.engine_webhooks import agent_webhook_url, ensure_agent_webhook
from apps.workers import engine_webhooks as sweep
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

ENGINE = "thinnest"


class FakeThinnest:
    """Their `/webhooks` collection, in memory."""

    def __init__(self) -> None:
        self.endpoints: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.redelivered: list[tuple[str, dict[str, Any]]] = []
        self.redeliver_status = 202

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ta_live_test"
        path = request.url.path.removeprefix("/api/v1")
        self.calls.append((request.method, path))
        if path == "/webhooks" and request.method == "POST":
            body = json.loads(request.content)
            webhook_id = f"wh_{uuid.uuid4().hex[:10]}"
            row = {
                "id": webhook_id,
                "agent": body["agent"],
                "url": body["url"],
                "events": body["events"],
                "enabled": True,
                "delivery": {"failuresInARow": 0, "lastStatus": None, "lastError": None},
                "createdAt": "2026-10-06T09:41:00Z",
            }
            self.endpoints[webhook_id] = row
            return httpx.Response(201, json={**row, "signingSecret": f"sec-{webhook_id}"})
        if path == "/webhooks" and request.method == "GET":
            agent = request.url.params.get("agent")
            items = [r for r in self.endpoints.values() if r["agent"] == agent]
            return httpx.Response(200, json={"items": items})
        if path.endswith("/redeliver") and request.method == "POST":
            # redeliver-webhook-events.md:7: `{since}` queues what failed, `202 {queued}`.
            self.redelivered.append((path.split("/")[2], json.loads(request.content)))
            if self.redeliver_status != 202:
                return httpx.Response(self.redeliver_status, json={"error": "switched off"})
            return httpx.Response(202, json={"queued": 3})
        webhook_id = path.removeprefix("/webhooks/")
        row = self.endpoints.get(webhook_id)
        if row is None:
            return httpx.Response(404, json={"error": "Not found"})
        if request.method == "GET":
            return httpx.Response(200, json=row)
        if request.method == "PATCH":
            row.update(json.loads(request.content))
            row["delivery"]["failuresInARow"] = 0
            return httpx.Response(200, json=row)
        if request.method == "DELETE":
            del self.endpoints[webhook_id]
            return httpx.Response(204)
        return httpx.Response(405)


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeThinnest()
    client = ThinnestWebhooks(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler),
            base_url="https://app.thinnest.ai/api/v1",
            headers={"Authorization": "Bearer ta_live_test"},
        ),
    )
    set_thinnest_webhooks(client)
    monkeypatch.setattr(get_settings(), "webhook_base_url", "https://hooks.calevate.example")
    yield fake
    set_thinnest_webhooks(None)


async def _route() -> tuple[uuid.UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, ref


async def _ensure(tenant_id: uuid.UUID, ref: str) -> Any:
    async with tenant_session(tenant_id) as session:
        return await ensure_agent_webhook(session, engine=ENGINE, engine_agent_ref=ref)


async def _held(tenant_id: uuid.UUID, ref: str) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT webhook_id, webhook_secret_ciphertext, webhook_secret_nonce, "
                    "webhook_secret_dek_wrapped, webhook_secret_dek_nonce, "
                    "webhook_secret_kek_version FROM engine_agent_routes "
                    "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
                ),
                {"ref": ref},
            )
        ).one()
    if row[0] is None:
        return None, None
    secret = open_webhook_secret(
        Envelope(
            ciphertext=bytes(row[1]),
            nonce=bytes(row[2]),
            dek_wrapped=bytes(row[3]),
            dek_nonce=bytes(row[4]),
            kek_id=int(row[5]),
        ),
        engine=ENGINE,
        engine_agent_ref=ref,
    )
    return row[0], secret


async def test_publish_registers_once_and_stores_the_secret_sealed(vendor: FakeThinnest) -> None:
    tenant_id, ref = await _route()

    first = await _ensure(tenant_id, ref)
    assert first.outcome == "registered"
    webhook_id, secret = await _held(tenant_id, ref)
    assert webhook_id == first.webhook_id
    assert secret == f"sec-{webhook_id}"
    row = vendor.endpoints[webhook_id]
    assert row["url"] == agent_webhook_url(ENGINE, ref)
    assert row["url"].startswith("https://hooks.calevate.example/hooks/v1/engine/thinnest?agent=")
    assert row["events"] == [
        "call.analysed",
        "call.completed",
        "contact.opted_out",
        "conversation.escalated",
        "lead.captured",
    ]

    again = await _ensure(tenant_id, ref)
    assert again.outcome == "healthy"
    assert again.webhook_id == webhook_id
    assert [c for c in vendor.calls if c[0] == "POST"] == [("POST", "/webhooks")]


async def test_a_switched_off_endpoint_is_switched_back_on(vendor: FakeThinnest) -> None:
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["enabled"] = False

    result = await _ensure(tenant_id, ref)
    assert result.outcome == "reenabled"
    assert vendor.endpoints[webhook_id]["enabled"] is True
    assert ("PATCH", f"/webhooks/{webhook_id}") in vendor.calls


async def test_an_endpoint_deleted_on_their_side_is_replaced(vendor: FakeThinnest) -> None:
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    del vendor.endpoints[old]

    result = await _ensure(tenant_id, ref)
    assert result.outcome == "replaced"
    assert result.webhook_id != old
    assert (await _held(tenant_id, ref))[0] == result.webhook_id


async def test_an_endpoint_whose_secret_we_lost_is_deleted_not_kept(vendor: FakeThinnest) -> None:
    """A create whose response never reached our commit leaves an endpoint we can never
    verify. It is removed before a fresh one is made, so there is exactly one."""
    tenant_id, ref = await _route()
    orphan = (await _ensure(tenant_id, ref)).webhook_id
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET webhook_id = NULL, webhook_secret_ciphertext = "
                "NULL, webhook_secret_nonce = NULL, webhook_secret_dek_wrapped = NULL, "
                "webhook_secret_dek_nonce = NULL, webhook_secret_kek_version = NULL "
                "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
            ),
            {"ref": ref},
        )

    result = await _ensure(tenant_id, ref)
    assert result.outcome == "registered"
    assert orphan not in vendor.endpoints
    assert [r["id"] for r in vendor.endpoints.values() if r["agent"] == ref] == [result.webhook_id]


async def test_other_engines_and_private_addresses(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, ref = await _route()
    async with tenant_session(tenant_id) as session:
        skipped = await ensure_agent_webhook(session, engine="pipecat", engine_agent_ref=ref)
    assert skipped.outcome == "not_applicable"

    monkeypatch.setattr(get_settings(), "webhook_base_url", "http://localhost:8100")
    with pytest.raises(ProblemError) as refused:
        await _ensure(tenant_id, ref)
    assert refused.value.code == "engine_webhook_url_not_public"
    assert vendor.calls == []


async def test_the_sweep_reenables_and_alarms(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["enabled"] = False
    alerts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **kw: alerts.append((code, kw)))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)
    # Older routes in this database first: the sweep orders by last check.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET webhook_checked_at = '2000-01-01' "
                "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
            ),
            {"ref": ref},
        )

    await sweep.reconcile_engine_webhooks({})

    assert vendor.endpoints[webhook_id]["enabled"] is True
    assert any(
        code == "engine_webhook_reenabled" and kw.get("engine_agent_ref") == ref
        for code, kw in alerts
    )


async def test_the_sweep_is_a_no_op_on_other_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    assert await sweep.reconcile_engine_webhooks({}) == "engine_without_webhooks"


async def _aged(tenant_id: uuid.UUID, ref: str, checked_at: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET webhook_checked_at = CAST(:at AS timestamptz) "
                "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
            ),
            {"ref": ref, "at": checked_at},
        )


async def test_the_sweep_asks_for_what_failed_to_be_sent_again_after_reenabling(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-691: re-enable, then `POST /webhooks/{id}/redeliver {since}` once, never further back
    than the vendor keeps payloads (`webhooks/redeliver-webhook-events.md:7`)."""
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["enabled"] = False
    await _aged(tenant_id, ref, "2000-01-01")
    monkeypatch.setattr(sweep, "alert", lambda *_a, **_k: None)
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    summary = await sweep.reconcile_engine_webhooks({})

    ours = [body for wid, body in vendor.redelivered if wid == webhook_id]
    assert len(ours) == 1
    since = datetime.fromisoformat(ours[0]["since"].replace("Z", "+00:00"))
    assert datetime.now(UTC) - since < timedelta(days=7)
    assert "redelivered=" in summary

    # Healthy on the next pass: nothing is re-sent again.
    await _aged(tenant_id, ref, "2000-01-01")
    await sweep.reconcile_engine_webhooks({})
    assert len([wid for wid, _ in vendor.redelivered if wid == webhook_id]) == 1


async def test_a_refused_redelivery_alarms_and_the_endpoint_stays_on(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["enabled"] = False
    vendor.redeliver_status = 409
    await _aged(tenant_id, ref, "2000-01-01")
    alerts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **kw: alerts.append((code, kw)))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    await sweep.reconcile_engine_webhooks({})

    assert vendor.endpoints[webhook_id]["enabled"] is True
    assert any(
        code == "engine_webhook_redelivery_failed" and kw.get("engine_agent_ref") == ref
        for code, kw in alerts
    )


async def test_an_endpoint_registered_before_the_opt_out_event_is_resubscribed_in_place(
    vendor: FakeThinnest,
) -> None:
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["events"] = ["call.completed", "call.analysed"]
    _, secret_before = await _held(tenant_id, ref)

    result = await _ensure(tenant_id, ref)

    assert (result.outcome, result.webhook_id) == ("resubscribed", webhook_id)
    assert sorted(vendor.endpoints[webhook_id]["events"]) == [
        "call.analysed",
        "call.completed",
        "contact.opted_out",
        "conversation.escalated",
        "lead.captured",
    ]
    assert (await _held(tenant_id, ref)) == (webhook_id, secret_before)
    vendor.endpoints[webhook_id]["events"] = ["*"]
    assert (await _ensure(tenant_id, ref)).outcome == "healthy"


@pytest.mark.parametrize(
    ("last_checked_ago", "expected_ago"),
    [
        (None, sweep.REDELIVERY_FLOOR),
        (timedelta(minutes=20), timedelta(minutes=20) + sweep.REDELIVERY_TAIL),
        (timedelta(days=30), sweep.REDELIVERY_FLOOR),
    ],
)
def test_the_redelivery_window_reaches_past_the_retry_tail_but_never_past_seven_days(
    last_checked_ago: timedelta | None, expected_ago: timedelta
) -> None:
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    last = None if last_checked_ago is None else now - last_checked_ago
    assert sweep.redelivery_since(last, now=now) == now - expected_ago
