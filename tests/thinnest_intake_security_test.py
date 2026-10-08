"""The ThinnestAI webhook intake: HMAC per agent, freshness, event-id dedupe, a sealed body.

Suffix `_security_test` per BACKEND-PATTERNS §9. Shapes are the mirror's:
`thinnest-findings/mirror/pages/api-reference/get-call.md:14-47` (the call object) and
`snapshots/2026-10-08/pages/api-reference/webhooks.md:94-147` (the `{id, event, sentAt, data}`
envelope, `x-thinnest-signature-v2` over `<delivered-at>.<body>`, freshness on the delivery
time, dedupe on the event id; D-678, D-691).
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
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
from calevate_shared.webhook_signature import sha256_signature, timestamped_sha256_signature
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from signed_intake import (
    ENGINE_NOTICE_JOB,
    ENGINE_OPT_OUT_JOB,
    SIGNED_INTAKES,
    delivery_attempt,
    keyed_event,
)
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


def _analysed(
    ref: str,
    call_id: str | None = None,
    *,
    event_id: str | None = None,
    sent_at: datetime | None = None,
) -> bytes:
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
        {
            "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
            "event": "call.analysed",
            # When the event HAPPENED: every retry repeats it unchanged (webhooks.md:115-116).
            "sentAt": (sent_at or datetime.now(UTC)).isoformat(),
            "data": data,
        }
    ).encode()


def _signed(
    body: bytes,
    secret: str,
    *,
    at: datetime | None = None,
    attempt: int = 1,
    event_id: str | None = None,
) -> dict[str, str]:
    """The headers ThinnestAI puts on an attempt (webhooks.md:100-108)."""
    delivered_at = (at or datetime.now(UTC)).isoformat()
    decoded = json.loads(body) if body.startswith(b"{") else {}
    return {
        "x-thinnest-signature-v2": timestamped_sha256_signature(
            body, secret, signed_at=delivered_at
        ),
        "x-thinnest-signature": sha256_signature(body, secret),
        "x-thinnest-delivered-at": delivered_at,
        "x-thinnest-event-id": event_id or str(decoded.get("id", "")),
        "x-thinnest-attempt": str(attempt),
    }


async def _post(body: bytes, *, ref: str | None, signed: dict[str, str] | None) -> Any:
    headers = {"content-type": "application/json", **(signed or {})}
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


async def _attempts_recorded(event_name: str) -> list[int]:
    async with untenanted_session() as session:
        return [
            int(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT attempts FROM webhook_deliveries "
                        "WHERE source = 'thinnest' AND event_type = :e"
                    ),
                    {"e": event_name},
                )
            ).all()
        ]


async def test_a_signed_delivery_is_accepted_once_with_its_body_sealed(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    first = await _post(body, ref=ref, signed=_signed(body, secret))
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "accepted"
    assert int(float(first.headers["X-Ack-Ms"])) < 500

    [job] = captured
    assert job["job"] == "ingest_engine_event"
    payload = job["payload"]
    assert payload["execution_id"] == call_id
    assert payload["engine_agent_ref"] == ref
    # The caller's number and words cross Redis only as ciphertext (hard rule 6).
    assert CALLER not in json.dumps(payload)
    assert "Appointment" not in json.dumps(payload)
    assert open_delivery(payload["delivery"], engine=ENGINE, execution_id=call_id) == body

    replay = await _post(body, ref=ref, signed=_signed(body, secret))
    assert replay.status_code == 202
    assert replay.json()["status"] == "duplicate"
    assert len(captured) == 1
    assert await _inbox_count(call_id) == 1


async def test_a_retry_hours_later_with_its_old_sent_at_is_accepted_and_its_attempt_kept(
    captured: list[dict[str, Any]],
) -> None:
    """Every retry sends the SAME bytes, so `sentAt` is hours old by design; only the
    delivery time is fresh (webhooks.md:112-117, :129-131). The first attempt never arrived
    (our receiver was down), so the retry is the delivery that counts."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref, sent_at=datetime.now(UTC) - timedelta(hours=2, minutes=36))
    event_id = json.loads(body)["id"]

    retried = await _post(body, ref=ref, signed=_signed(body, secret, attempt=4))

    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "accepted"
    [job] = captured
    assert job["job_id"].endswith(f"call.analysed:{event_id}")
    assert await _attempts_recorded(f"call.analysed:{event_id}") == [4]


async def test_a_duplicate_event_id_is_deduped_whatever_the_attempt(
    captured: list[dict[str, Any]],
) -> None:
    """A retry after a timeout can reach us after the first attempt was handled
    (webhooks.md:133-134), and a console re-send carries the same event id (:184-185)."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]
    event_id = json.loads(body)["id"]

    first = await _post(body, ref=ref, signed=_signed(body, secret, attempt=1))
    later = datetime.now(UTC) + timedelta(seconds=40)
    retry = await _post(body, ref=ref, signed=_signed(body, secret, at=later, attempt=2))

    assert first.json()["status"] == "accepted"
    assert retry.status_code == 202
    assert retry.json()["status"] == "duplicate"
    assert len(captured) == 1
    assert await _inbox_count(call_id) == 1
    assert await _attempts_recorded(f"call.analysed:{event_id}") == [1]


async def test_a_second_event_for_the_same_call_is_its_own_unit(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    call_id = f"in_{uuid.uuid4().hex[:12]}"
    for body in (_analysed(ref, call_id), _analysed(ref, call_id)):
        response = await _post(body, ref=ref, signed=_signed(body, secret))
        assert response.json()["status"] == "accepted"
    assert len(captured) == 2
    assert await _inbox_count(call_id) == 2


async def test_a_stale_or_restamped_delivery_time_is_refused_even_with_a_good_signature(
    captured: list[dict[str, Any]],
    alerts: list[tuple[str, str, dict[str, Any]]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    stale = _signed(body, secret, at=datetime.now(UTC) - timedelta(minutes=6))
    early = _signed(body, secret, at=datetime.now(UTC) + timedelta(minutes=6))
    # A captured attempt restamped with a fresh time no longer verifies: the time is signed.
    restamped = {**stale, "x-thinnest-delivered-at": datetime.now(UTC).isoformat()}

    for headers in (stale, early, restamped):
        response = await _post(body, ref=ref, signed=headers)
        assert response.status_code == 401, response.text
    assert captured == []
    assert await _inbox_count(call_id) == 0
    reasons = [f["detail"] for _, r, f in alerts if r == "webhook_source_rejected"]
    assert reasons == ["stale delivery", "stale delivery", "signature does not verify"]


async def test_the_v1_signature_alone_is_not_accepted(captured: list[dict[str, Any]]) -> None:
    """v1 signs the body without the time, so a captured body would replay for ever."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    headers = _signed(body, secret)
    del headers["x-thinnest-signature-v2"]

    response = await _post(body, ref=ref, signed=headers)

    assert response.status_code == 401
    assert captured == []


async def test_a_forged_or_misaddressed_delivery_is_refused_and_files_nothing(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]

    wrong_key = await _post(body, ref=ref, signed=_signed(body, "not-the-secret"))
    unsigned = await _post(body, ref=ref, signed=None)
    tampered = await _post(body + b" ", ref=ref, signed=_signed(body, secret))
    no_agent = await _post(body, ref=None, signed=_signed(body, secret))
    stranger = await _post(body, ref=f"ag_{uuid.uuid4()}", signed=_signed(body, secret))

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
    response = await _post(body, ref=ref, signed=_signed(body, secret))
    assert response.status_code == 401
    assert captured == []


async def test_a_signed_event_we_do_not_consume_is_acked_and_ignored(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = json.dumps(
        {"id": "evt_c1", "event": "campaign.finished", "data": {"agent": {"id": ref}}}
    ).encode()
    response = await _post(body, ref=ref, signed=_signed(body, secret))
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "event not consumed"}
    assert captured == []


async def test_a_notice_is_queued_for_its_own_job_keyed_on_its_event_id(
    captured: list[dict[str, Any]],
) -> None:
    """`lead.captured` / `conversation.escalated` (webhooks.md:79-80) need not name a call."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    body = json.dumps(
        {"id": event_id, "event": "conversation.escalated", "data": {"agent": {"id": ref}}}
    ).encode()

    response = await _post(body, ref=ref, signed=_signed(body, secret))

    assert response.json()["status"] == "accepted"
    [job] = captured
    assert job["job"] == ENGINE_NOTICE_JOB
    assert job["payload"]["execution_id"] == event_id


async def test_the_endpoint_test_delivery_is_acked_and_ignored(
    captured: list[dict[str, Any]],
    alerts: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """`POST /webhooks/{id}/test` sends a sample marked `"test": true` (webhooks.md:199-200)."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = json.dumps(
        {"id": "evt_t1", "event": "call.analysed", "test": True, "data": {"id": "out_x"}}
    ).encode()
    response = await _post(body, ref=ref, signed=_signed(body, secret))
    assert response.json() == {"status": "ignored", "reason": "test delivery"}
    assert captured == []
    assert [r for _, r, _ in alerts if r == "webhook_unkeyable"] == []


async def test_an_opt_out_is_queued_for_its_own_job_keyed_on_the_call(
    captured: list[dict[str, Any]],
) -> None:
    """`contact.opted_out` carries `data.callId` and `data.phone` (webhooks.md:85)."""
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    call_id = f"out_{uuid.uuid4().hex[:12]}"
    body = json.dumps(
        {
            "id": f"evt_{uuid.uuid4().hex[:8]}",
            "event": "contact.opted_out",
            "sentAt": datetime.now(UTC).isoformat(),
            "data": {
                "phone": CALLER,
                "callId": call_id,
                "source": "call",
                "optedOutAt": "2026-10-08T09:00:00Z",
            },
        }
    ).encode()

    response = await _post(body, ref=ref, signed=_signed(body, secret))

    assert response.json()["status"] == "accepted"
    [job] = captured
    assert job["job"] == ENGINE_OPT_OUT_JOB
    assert job["payload"]["execution_id"] == call_id
    assert CALLER not in json.dumps(job["payload"])
    assert open_delivery(job["payload"]["delivery"], engine=ENGINE, execution_id=call_id) == body


async def test_a_body_naming_another_agent_is_not_processed(
    captured: list[dict[str, Any]],
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = _analysed(f"ag_{uuid.uuid4()}")
    response = await _post(body, ref=ref, signed=_signed(body, secret))
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "agent mismatch"}
    assert captured == []


def test_the_unit_is_the_event_id_on_every_retry() -> None:
    """Dedupe on the event id (webhooks.md:107, :133-134), not on the call's own fields."""
    intake = SIGNED_INTAKES[ENGINE]
    data: dict[str, Any] = {"id": "out_1", "attempt": 1, "endedAt": "T1", "analysedAt": "T2"}
    analysed = keyed_event(
        intake, {"id": "evt_a", "event": "call.analysed", "data": data}, engine_agent_ref="a"
    )
    completed = keyed_event(
        intake, {"id": "evt_c", "event": "call.completed", "data": data}, engine_agent_ref="a"
    )
    assert not isinstance(analysed, str)
    assert not isinstance(completed, str)
    assert (analysed.execution_id, analysed.event_name) == ("out_1", "call.analysed:evt_a")
    assert (completed.execution_id, completed.event_name) == ("out_1", "call.completed:evt_c")
    mismatched = keyed_event(
        intake,
        {"id": "evt_a", "event": "call.analysed", "data": data},
        engine_agent_ref="a",
        event_id_header="evt_other",
    )
    assert mismatched == "event id mismatch"
    no_id = keyed_event(intake, {"event": "call.analysed", "data": data}, engine_agent_ref="a")
    assert no_id == "unusable event id"
    no_call = keyed_event(
        intake, {"id": "evt_a", "event": "call.analysed", "data": {}}, engine_agent_ref="a"
    )
    assert no_call == "unusable execution key"


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
    forged = {"x-thinnest-signature-v2": "sha256=00"}
    response = await _post(body, ref=f"ag_{uuid.uuid4()}", signed=forged)

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

    response = await _post(body, ref=ref, signed=_signed(body, secret))

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
    forged = {"x-thinnest-signature-v2": "sha256=00"}
    response = await _post(body, ref=f"ag_{uuid.uuid4()}", signed=forged)

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
    response = await _post(body, ref=ref, signed=_signed(body, secret))

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "ignored", "reason": "unreadable payload"}
    assert captured == []
    assert ("ROUTE_HANDLER", "webhook_unkeyable") in [(k, r) for k, r, _ in alerts]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), ("1", 1), (None, 1), ("0", 1), ("abc", 1), ("-2", 1), ("99999999", 1)],
)
def test_the_attempt_header_is_recorded_only_when_it_is_a_plain_count(
    value: str | None, expected: int
) -> None:
    headers = {} if value is None else {"x-thinnest-attempt": value}
    assert delivery_attempt(SIGNED_INTAKES[ENGINE], headers) == expected


def test_a_delivery_whose_data_is_not_an_object_is_unkeyable() -> None:
    intake = SIGNED_INTAKES[ENGINE]
    for data in (None, "in_1", ["in_1"]):
        payload = {"id": "evt_1", "event": "call.analysed", "data": data}
        assert keyed_event(intake, payload, engine_agent_ref="a") == "unusable execution key", data


def test_a_unit_too_long_for_the_inbox_key_is_unkeyable_rather_than_a_500() -> None:
    """Each part fits the 128-character key ceiling on its own; joined, they do not."""
    intake = SIGNED_INTAKES[ENGINE]
    payload = {"id": "evt_" + "e" * 120, "event": "call.analysed", "data": {"id": "in_1"}}
    assert keyed_event(intake, payload, engine_agent_ref="a") == "unusable execution key"


def test_the_receivers_job_names_are_the_routes_and_the_workers() -> None:
    """Spelled twice so `scripts/check_job_wiring` can read each at its enqueue site."""
    import signed_intake
    from apps.workers import engine_signals

    assert webhook_routes.INGEST_JOB == signed_intake.INGEST_JOB
    assert webhook_routes.ENGINE_OPT_OUT_JOB == signed_intake.ENGINE_OPT_OUT_JOB
    assert webhook_routes.ENGINE_NOTICE_JOB == signed_intake.ENGINE_NOTICE_JOB
    assert signed_intake.ENGINE_NOTICE_JOB == engine_signals.ENGINE_NOTICE_JOB
