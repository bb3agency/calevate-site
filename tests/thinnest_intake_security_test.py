"""The ThinnestAI webhook intake: HMAC per agent, keyed dedupe, a sealed body (D-678).

Suffix `_security_test` per BACKEND-PATTERNS §9. Shapes are the mirror's:
`thinnest-findings/mirror/pages/api-reference/get-call.md:14-47` (the call object),
`:60-66` (the `{event, sentAt, data}` envelope) and `webhooks.md:36-40` / `mcp/own-database
.md:74-86` (`x-thinnest-signature: sha256=<hex HMAC-SHA256 of the raw body>`).
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import webhook_routes
from apps.api.core.envelope import KekRing
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.engine_intake_keys import (
    build_intake_ring,
    open_delivery,
    seal_webhook_secret,
)
from calevate_shared.webhook_signature import sha256_signature
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from signed_intake import SIGNED_INTAKES, STALE_DELIVERY, keyed_event
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

ENGINE = "thinnest"
EDGE = "127.0.0.1"
CALLER = "919876543210"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    async def _capture(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        jobs.append({"job": job, "payload": payload, "job_id": job_id})
        return job_id or "job"

    monkeypatch.setattr(webhook_routes, "enqueue", _capture)
    monkeypatch.setattr(get_settings(), "engine", ENGINE)
    return jobs


async def _agent_with_secret(secret: str, *, ring: KekRing | None = None) -> str:
    """A route row for a ThinnestAI agent holding `secret`, sealed as registration stores it."""
    seed_ref = f"fakeagent_{uuid.uuid4().hex[:10]}"
    tenant_id, agent_id = await _seed_tenant(seed_ref)
    ref = f"ag_{uuid.uuid4()}"
    envelope = seal_webhook_secret(secret, engine=ENGINE, engine_agent_ref=ref, ring=ring)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, webhook_id, webhook_secret_ciphertext, webhook_secret_nonce, "
                "webhook_secret_dek_wrapped, webhook_secret_dek_nonce, "
                "webhook_secret_kek_version, created_at, updated_at) VALUES ('thinnest', :ref, "
                ":tid, :aid, true, :wid, :ct, :n, :dw, :dn, :kek, now(), now())"
            ),
            {
                "ref": ref,
                "tid": tenant_id,
                "aid": agent_id,
                "wid": f"wh_{uuid.uuid4().hex[:8]}",
                "ct": envelope.ciphertext,
                "n": envelope.nonce,
                "dw": envelope.dek_wrapped,
                "dn": envelope.dek_nonce,
                "kek": envelope.kek_id,
            },
        )
    return ref


def _analysed(ref: str, call_id: str | None = None) -> bytes:
    data = {
        "id": call_id or f"in_{uuid.uuid4().hex[:12]}",
        "reference": None,
        "attempt": 1,
        "status": "completed",
        "direction": "inbound",
        "phone": CALLER,
        "from": "918045678901",
        "agent": {"id": ref, "name": "Front desk"},
        "startedAt": "2026-10-06T04:30:02Z",
        "answeredAt": "2026-10-06T04:30:09Z",
        "endedAt": "2026-10-06T04:33:11Z",
        "seconds": 182,
        "hangup": "answered",
        "summary": "Asked for an appointment.",
        "fields": {"intent": "booking"},
        "transcript": [
            {"speaker": "agent", "text": "Namaskaram!", "at": "2026-10-06T04:30:10Z"},
            {"speaker": "customer", "text": "Appointment kavali", "at": "2026-10-06T04:30:14Z"},
        ],
        "recording": {"url": "https://app.thinnest.ai/api/v1/recordings/3b7e", "ready": True},
        "analysedAt": "2026-10-06T04:33:20Z",
        "error": None,
    }
    return json.dumps(
        # Sent now: a delivery outside the five-minute replay window is ignored.
        {"event": "call.analysed", "sentAt": datetime.now(UTC).isoformat(), "data": data}
    ).encode()


async def _post(body: bytes, *, ref: str | None, signature: str | None) -> Any:
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["x-thinnest-signature"] = signature
    url = f"/hooks/v1/engine/{ENGINE}" + (f"?agent={ref}" if ref else "")
    async with AsyncClient(
        transport=ASGITransport(app=voice_app, client=(EDGE, 44444)), base_url="http://runtime"
    ) as http:
        return await http.post(url, content=body, headers=headers)


async def _inbox_count(execution_id: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM webhook_inbox_events "
                        "WHERE provider = 'thinnest' AND event_key LIKE :k"
                    ),
                    {"k": f"{execution_id}:%"},
                )
            ).scalar_one()
        )


async def test_a_signed_delivery_is_accepted_once_with_its_body_sealed(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    first = await _post(body, ref=ref, signature=sha256_signature(body, secret))
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "accepted"
    assert int(float(first.headers["X-Ack-Ms"])) < 500

    [job] = captured
    payload = job["payload"]
    assert payload["execution_id"] == call_id
    assert payload["engine_agent_ref"] == ref
    # The caller's number and words cross Redis only as ciphertext (hard rule 6).
    assert CALLER not in json.dumps(payload)
    assert "Appointment" not in json.dumps(payload)
    assert open_delivery(payload["delivery"], engine=ENGINE, execution_id=call_id) == body

    replay = await _post(body, ref=ref, signature=sha256_signature(body, secret))
    assert replay.status_code == 202
    assert replay.json()["status"] == "duplicate"
    assert len(captured) == 1
    assert await _inbox_count(call_id) == 1


async def test_a_forged_or_misaddressed_delivery_is_refused_and_files_nothing(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    wrong_key = await _post(body, ref=ref, signature=sha256_signature(body, "not-the-secret"))
    unsigned = await _post(body, ref=ref, signature=None)
    tampered = await _post(body + b" ", ref=ref, signature=sha256_signature(body, secret))
    no_agent = await _post(body, ref=None, signature=sha256_signature(body, secret))
    stranger = await _post(body, ref=f"ag_{uuid.uuid4()}", signature=sha256_signature(body, secret))

    for response in (wrong_key, unsigned, tampered, no_agent, stranger):
        assert response.status_code == 401, response.text
    assert captured == []
    assert await _inbox_count(call_id) == 0


async def test_a_delivery_for_an_engine_this_deployment_does_not_run_is_refused(
    captured: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    monkeypatch.setattr(get_settings(), "engine", "fake")
    body = _analysed(ref)
    response = await _post(body, ref=ref, signature=sha256_signature(body, secret))
    assert response.status_code == 401
    assert captured == []


async def test_a_signed_event_we_do_not_consume_is_acked_and_ignored(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = json.dumps(
        {"event": "lead.captured", "test": True, "data": {"id": "lead_1", "agent": {"id": ref}}}
    ).encode()
    response = await _post(body, ref=ref, signature=sha256_signature(body, secret))
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "event not consumed"}
    assert captured == []


async def test_a_body_naming_another_agent_is_not_processed(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(f"ag_{uuid.uuid4()}")
    response = await _post(body, ref=ref, signature=sha256_signature(body, secret))
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "agent mismatch"}
    assert captured == []


def test_each_try_and_each_event_is_its_own_unit() -> None:
    """Dedupe on (id, event, attempt, analysedAt|endedAt) — THINNEST-INTEGRATION §3.2."""
    intake = SIGNED_INTAKES[ENGINE]
    data: dict[str, Any] = {"id": "out_1", "attempt": 1, "endedAt": "T1", "analysedAt": "T2"}
    analysed = keyed_event(intake, {"event": "call.analysed", "data": data}, engine_agent_ref="a")
    completed = keyed_event(intake, {"event": "call.completed", "data": data}, engine_agent_ref="a")
    retried = keyed_event(
        intake,
        {"event": "call.analysed", "data": {**data, "attempt": 2}},
        engine_agent_ref="a",
    )
    assert not isinstance(analysed, str)
    assert not isinstance(completed, str)
    assert not isinstance(retried, str)
    assert analysed.event_name == "call.analysed:1:T2"
    assert completed.event_name == "call.completed:1:T1"
    assert retried.event_name == "call.analysed:2:T2"
    # The `call.completed` body is documented only as "outcome and duration"
    # (webhooks.md:74): an id with no attempt or stamp is still keyed, not dropped.
    bare = keyed_event(
        intake, {"event": "call.completed", "data": {"id": "in_9"}}, engine_agent_ref="a"
    )
    assert not isinstance(bare, str)
    assert bare.event_name == "call.completed:-:-"
    assert keyed_event(intake, {"event": "call.analysed", "data": {}}, engine_agent_ref="a") == (
        "unusable execution key"
    )


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    raised: list[tuple[str, str, dict[str, Any]]] = []

    def _record(kind: str, reason: str, **fields: Any) -> None:
        raised.append((kind, reason, fields))

    monkeypatch.setattr(webhook_routes, "alert", _record)
    return raised


async def test_an_oversized_delivery_is_refused_before_any_secret_is_read(
    captured: list[dict[str, Any]],
    alerts: list[tuple[str, str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[str] = []

    async def _lookup(engine: str, ref: str, **_: Any) -> str | None:
        looked_up.append(ref)
        return None

    monkeypatch.setattr(webhook_routes, "signing_secret", _lookup)
    body = b"{" + b" " * webhook_routes.WEBHOOK_ACK.max_body_bytes + b"}"
    response = await _post(body, ref=f"ag_{uuid.uuid4()}", signature="sha256=00")

    assert response.status_code == 413, response.text
    assert response.json()["title"] == "Event too large"
    assert response.json()["type"].endswith("/payload_too_large")
    assert looked_up == []
    assert captured == []
    assert ("ROUTE_HANDLER", "webhook_payload_too_large") in [(k, r) for k, r, _ in alerts]


async def test_a_secret_our_intake_key_cannot_open_is_an_outage_not_a_forgery(
    captured: list[dict[str, Any]], alerts: list[tuple[str, str, dict[str, Any]]]
) -> None:
    """A route row sealed under a key this deployment does not hold: 503, never 401, so the
    vendor counts a failed delivery and the reconciliation sweep settles the call."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    foreign = build_intake_ring(base64.b64encode(os.urandom(32)).decode(), None, "local")
    ref = await _agent_with_secret(secret, ring=foreign)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    response = await _post(body, ref=ref, signature=sha256_signature(body, secret))

    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/webhook_intake_unavailable")
    assert response.json()["retryable"] is True
    assert captured == []
    assert await _inbox_count(call_id) == 0
    [(kind, _, fields)] = [a for a in alerts if a[1] == "webhook_intake_unavailable"]
    assert kind == "ROUTE_HANDLER"
    assert fields["detail"] == "platform_secret_unwrappable"


async def test_a_secret_lookup_past_the_durable_deadline_is_an_outage(
    captured: list[dict[str, Any]],
    alerts: list[tuple[str, str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stalled(engine: str, ref: str, **_: Any) -> str | None:
        await asyncio.sleep(30)
        return None

    monkeypatch.setattr(webhook_routes, "signing_secret", _stalled)
    monkeypatch.setattr(
        webhook_routes,
        "WEBHOOK_ACK",
        dataclasses.replace(webhook_routes.WEBHOOK_ACK, durable_deadline_s=0.05),
    )
    body = _analysed(f"ag_{uuid.uuid4()}")
    response = await _post(body, ref=f"ag_{uuid.uuid4()}", signature="sha256=00")

    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/webhook_intake_unavailable")
    assert captured == []
    details = [f["detail"] for _, r, f in alerts if r == "webhook_intake_unavailable"]
    assert details == ["signing secret lookup timed out"]


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[1, 2, 3]",
        # Valid JSON to `json.loads` (it detects UTF-16), but not UTF-8: never sealed.
        json.dumps({"event": "call.analysed"}).encode("utf-16"),
    ],
    ids=["not-json", "not-an-object", "not-utf8"],
)
async def test_a_signed_but_unreadable_delivery_is_acked_and_ignored(
    body: bytes,
    captured: list[dict[str, Any]],
    alerts: list[tuple[str, str, dict[str, Any]]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    response = await _post(body, ref=ref, signature=sha256_signature(body, secret))

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "ignored", "reason": "unreadable payload"}
    assert captured == []
    assert ("ROUTE_HANDLER", "webhook_unkeyable") in [(k, r) for k, r, _ in alerts]


def test_a_send_time_that_is_not_a_timestamp_string_is_stale() -> None:
    """The vendor signed what it sent, so an epoch number is not a missing `sentAt`."""
    intake = SIGNED_INTAKES[ENGINE]
    for sent_at in (1_759_725_000, 1_759_725_000.5, ["2026-10-06T04:33:20Z"], True):
        assert (
            keyed_event(
                intake,
                {"event": "call.analysed", "sentAt": sent_at, "data": {"id": "in_1"}},
                engine_agent_ref="a",
            )
            == STALE_DELIVERY
        ), sent_at


def test_a_delivery_whose_data_is_not_an_object_is_unkeyable() -> None:
    intake = SIGNED_INTAKES[ENGINE]
    for data in (None, "in_1", ["in_1"]):
        assert (
            keyed_event(intake, {"event": "call.analysed", "data": data}, engine_agent_ref="a")
            == "unusable execution key"
        ), data


def test_a_unit_too_long_for_the_inbox_key_is_unkeyable_rather_than_a_500() -> None:
    """Each part fits the 128-character key ceiling on its own; joined, they do not."""
    intake = SIGNED_INTAKES[ENGINE]
    long_stamp = {"id": "in_1", "attempt": 1, "analysedAt": "T" * 128}
    huge_attempt = {"id": "in_1", "attempt": 10**150, "analysedAt": "T2"}
    for data in (long_stamp, huge_attempt):
        assert (
            keyed_event(intake, {"event": "call.analysed", "data": data}, engine_agent_ref="a")
            == "unusable execution key"
        )
