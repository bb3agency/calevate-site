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
from apps.api.billing.plans import IST
from apps.api.core.envelope import Envelope
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_webhooks import ThinnestWebhooks, set_thinnest_webhooks
from apps.api.reliability import engine_webhooks as registration_module
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
        #: Agents the vendor answers `404 That agent was not found.` for on create
        #: (`snapshots/2026-10-15/pages/api-reference/webhooks/create-webhook.md:510-517`).
        self.absent_agents: set[str] = set()
        #: `500 internal_error` "Could not save the endpoint.", as production answered a
        #: `PATCH /webhooks/{id}` (and possibly a create) on 17 Oct 2026.
        self.patch_fails = False
        self.create_fails = False
        self.get_fails = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ta_live_test"
        path = request.url.path.removeprefix("/api/v1")
        self.calls.append((request.method, path))
        could_not_save = httpx.Response(
            500, json={"error": "Could not save the endpoint.", "code": "internal_error"}
        )
        if path == "/webhooks" and request.method == "POST":
            if self.create_fails:
                return could_not_save
            body = json.loads(request.content)
            if body["agent"] in self.absent_agents:
                return httpx.Response(404, json={"error": "That agent was not found."})
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
            if self.get_fails:
                return httpx.Response(500, json={"error": "Try again.", "code": "internal_error"})
            return httpx.Response(200, json=row)
        if request.method == "PATCH":
            if self.patch_fails and "events" in json.loads(request.content):
                return could_not_save
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
        "byok.changed",
        "call.analysed",
        "call.completed",
        "call.problem",
        "contact.erased",
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
        skipped = await ensure_agent_webhook(session, engine="fake", engine_agent_ref=ref)
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
    monkeypatch.setattr(
        registration_module, "alert", lambda _s, code, **kw: alerts.append((code, kw))
    )
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
    monkeypatch.setattr(get_settings(), "engine", "fake")
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
    monkeypatch.setattr(registration_module, "alert", lambda *_a, **_k: None)
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
    monkeypatch.setattr(
        registration_module, "alert", lambda _s, code, **kw: alerts.append((code, kw))
    )
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
        "byok.changed",
        "call.analysed",
        "call.completed",
        "call.problem",
        "contact.erased",
        "contact.opted_out",
        "conversation.escalated",
        "lead.captured",
    ]
    assert (await _held(tenant_id, ref)) == (webhook_id, secret_before)
    vendor.endpoints[webhook_id]["events"] = ["*"]
    assert (await _ensure(tenant_id, ref)).outcome == "healthy"


def test_the_redelivery_window_is_always_the_whole_window_the_vendor_keeps() -> None:
    """Audit fix 5: never "since we last looked", which every sweep refreshes while failures
    build up; always back to the vendor's 7 days, a margin inside them."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    assert registration_module.redelivery_since(now=now) == now - (
        timedelta(days=7) - timedelta(minutes=30)
    )


async def test_an_endpoint_still_on_but_failing_is_asked_to_resend(
    vendor: FakeThinnest,
) -> None:
    """Audit fix 5: `failuresInARow > 0` means events are running out of attempts."""
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["delivery"]["failuresInARow"] = 2

    result = await _ensure(tenant_id, ref)

    assert (result.outcome, result.redelivered) == ("healthy", True)
    ours = [body for wid, body in vendor.redelivered if wid == webhook_id]
    since = datetime.fromisoformat(ours[0]["since"].replace("Z", "+00:00"))
    assert timedelta(days=6) < datetime.now(UTC) - since < timedelta(days=7)


async def test_a_publish_that_reenables_an_endpoint_resends_and_alarms(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit fix 6: the re-enable branch itself re-sends and alarms, so a publish (which calls
    `ensure_agent_webhook` directly, not the sweep) drops nothing."""
    tenant_id, ref = await _route()
    webhook_id = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[webhook_id]["enabled"] = False
    alerts: list[str] = []
    monkeypatch.setattr(registration_module, "alert", lambda _s, code, **_k: alerts.append(code))

    result = await _ensure(tenant_id, ref)

    assert (result.outcome, result.redelivered) == ("reenabled", True)
    assert "engine_webhook_reenabled" in alerts
    assert [wid for wid, _ in vendor.redelivered] == [webhook_id]


async def _active(tenant_id: uuid.UUID, ref: str) -> bool:
    async with tenant_session(tenant_id) as session:
        return bool(
            (
                await session.execute(
                    text(
                        "SELECT active FROM engine_agent_routes "
                        "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
                    ),
                    {"ref": ref},
                )
            ).scalar_one()
        )


async def test_a_route_whose_vendor_agent_is_gone_and_unnamed_is_switched_off(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No agent or arm of ours names this vendor agent any more (`_route`'s agent publishes
    under a different ref), and the vendor no longer has it: nothing can report through the
    route, so it is switched off instead of failing every sweep. The failure line carries
    the vendor's status so the cause is in the log, not behind a re-run."""
    tenant_id, ref = await _route()
    vendor.absent_agents.add(ref)
    await _aged(tenant_id, ref, "2000-01-01")
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **kw: alerts.append((code, kw["detail"])))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    summary = await sweep.reconcile_engine_webhooks({})

    assert not await _active(tenant_id, ref)
    assert "retired=" in summary and "retired=0" not in summary
    failed = [
        r
        for r in caplog.records
        if r.getMessage() == "engine_webhook_check_failed" and r.tenant_id == str(tenant_id)
    ]
    assert [(r.vendor_status, r.code) for r in failed] == [(404, "engine_rejected")]

    await _aged(tenant_id, ref, "2000-01-01")
    caplog.clear()
    await sweep.reconcile_engine_webhooks({})
    assert not [
        r
        for r in caplog.records
        if r.getMessage() == "engine_webhook_check_failed" and r.tenant_id == str(tenant_id)
    ], "a switched-off route was swept again"


async def test_a_route_an_agent_still_publishes_under_is_kept_and_named_in_the_alarm(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vendor says the agent we sell is missing (or it was asked for in the wrong
    workspace). Switching its route off would hide that; the alarm says to republish."""
    ref = f"ag_{uuid.uuid4()}"
    tenant_id, agent_id = await _seed_tenant(ref)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "'2000-01-01', now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    vendor.absent_agents.add(ref)
    await _aged(tenant_id, ref, "2000-01-01")
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **kw: alerts.append((code, kw["detail"])))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    await sweep.reconcile_engine_webhooks({})

    assert await _active(tenant_id, ref)
    [(code, detail)] = alerts
    assert code == "engine_webhook_sweep_incomplete"
    assert "republish that agent" in detail


_ALL_EVENTS = [
    "byok.changed",
    "call.analysed",
    "call.completed",
    "call.problem",
    "contact.erased",
    "contact.opted_out",
    "conversation.escalated",
    "lead.captured",
]


async def test_an_endpoint_the_vendor_cannot_resubscribe_is_replaced_create_first(
    vendor: FakeThinnest,
) -> None:
    """Production, 17 Oct 2026: `PATCH /webhooks/{id}` with the new events answered `500
    internal_error` on every sweep. A healthy endpoint is replaced by one created with every
    event, and the old one is deleted only after the new secret is stored."""
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[old]["events"] = ["call.analysed", "call.completed"]
    vendor.patch_fails = True
    vendor.calls.clear()

    result = await _ensure(tenant_id, ref)

    assert result.outcome == "replaced"
    assert result.webhook_id != old
    assert old not in vendor.endpoints
    assert vendor.endpoints[result.webhook_id]["events"] == _ALL_EVENTS
    held, secret = await _held(tenant_id, ref)
    assert (held, secret) == (result.webhook_id, f"sec-{result.webhook_id}")
    writes = [c for c in vendor.calls if c[0] in ("POST", "DELETE")]
    assert writes == [("POST", "/webhooks"), ("DELETE", f"/webhooks/{old}")]


async def test_when_the_vendor_cannot_create_either_the_old_endpoint_is_kept(
    vendor: FakeThinnest,
) -> None:
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[old]["events"] = ["call.analysed", "call.completed"]
    _, secret_before = await _held(tenant_id, ref)
    vendor.patch_fails = vendor.create_fails = True

    result = await _ensure(tenant_id, ref)

    assert (result.outcome, result.webhook_id) == ("events_pending", old)
    assert old in vendor.endpoints
    assert (await _held(tenant_id, ref)) == (old, secret_before)


async def test_a_failing_endpoint_is_resent_before_it_is_replaced(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An endpoint switched off still owes deliveries; deleting it would drop them. This sweep
    re-enables and re-sends on it, and the next one replaces it."""
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[old]["events"] = ["call.analysed", "call.completed"]
    vendor.endpoints[old]["enabled"] = False
    vendor.patch_fails = True
    monkeypatch.setattr(registration_module, "alert", lambda *_a, **_k: None)

    first = await _ensure(tenant_id, ref)
    assert (first.outcome, first.webhook_id, first.redelivered) == ("reenabled", old, True)
    assert vendor.endpoints[old]["enabled"] is True

    second = await _ensure(tenant_id, ref)
    assert second.outcome == "replaced"
    assert old not in vendor.endpoints
    assert vendor.endpoints[second.webhook_id]["events"] == _ALL_EVENTS


async def test_the_sweep_names_a_vendor_side_failure(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, ref = await _route()
    await _ensure(tenant_id, ref)
    vendor.get_fails = True
    await _aged(tenant_id, ref, "2000-01-01")
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **kw: alerts.append((code, kw["detail"])))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    await sweep.reconcile_engine_webhooks({})

    [(code, detail)] = alerts
    assert code == "engine_webhook_sweep_incomplete"
    assert "voice platform's side" in detail


async def test_events_the_vendor_cannot_add_alarm_once_a_day_not_as_unchecked(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Production, 17 Oct 2026: the endpoint was on and delivering, and only the newer events
    could not be added. That is not an unchecked endpoint, and a vendor fault is not worth
    an alarm every twenty minutes."""
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[old]["events"] = ["call.analysed", "call.completed"]
    vendor.patch_fails = vendor.create_fails = True
    today = datetime.now(UTC).astimezone(IST).date().isoformat()
    await get_redis().delete(sweep._EVENTS_PENDING_KEY.format(engine=ENGINE, day=today))
    alerts: list[str] = []
    monkeypatch.setattr(sweep, "alert", lambda _s, code, **_kw: alerts.append(code))
    monkeypatch.setattr(get_settings(), "engine", ENGINE)

    for _ in range(2):
        await _aged(tenant_id, ref, "2000-01-01")
        summary = await sweep.reconcile_engine_webhooks({})
        assert "events_pending=0" not in summary

    # Other tests' routes share this database and the vendor fails their creates too, so
    # only this route's own lines and the once-a-day alarm are asserted.
    assert alerts.count("engine_webhook_events_pending") == 1
    assert not [
        r
        for r in caplog.records
        if r.getMessage() == "engine_webhook_check_failed" and r.tenant_id == str(tenant_id)
    ], "an endpoint that is on and delivering was reported as unchecked"
    assert old in vendor.endpoints


async def test_a_failed_patch_names_which_change_and_the_endpoint_state(
    vendor: FakeThinnest, caplog: pytest.LogCaptureFixture
) -> None:
    """`PATCH /webhooks/{id}` carries both the event list and the on switch, so the line says
    which one failed and what the vendor had just reported for the endpoint."""
    tenant_id, ref = await _route()
    old = (await _ensure(tenant_id, ref)).webhook_id
    vendor.endpoints[old]["events"] = ["call.analysed", "call.completed"]
    vendor.patch_fails = vendor.create_fails = True

    assert (await _ensure(tenant_id, ref)).outcome == "events_pending"

    [line] = [r for r in caplog.records if r.getMessage() == "engine_webhook_patch_failed"]
    assert (line.op, line.vendor_status, line.vendor_code) == ("subscribe", 500, "internal_error")
    assert (line.endpoint_enabled, line.failures_in_a_row) == (True, 0)
    assert line.events_held == "call.analysed,call.completed"
