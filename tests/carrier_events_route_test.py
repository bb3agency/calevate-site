"""The carrier status/hangup callback route: inbox, queue, ack — and no phone number.

`/carrier/v1/{carrier}/events/{ref}[/outbound/{call_id}]` reuses the engine receiver's
machinery (`webhook_routes.settle`) rather than a copy of it, so what is driven here is
what is carrier-specific: the key (`CallUUID` + `Event`), the 200 the vendor's retry
policy needs (`vobiz-findings/mirror/pages/concepts/callbacks.md:125-126`), the payload
handed to `ingest_carrier_event`, and hard rule 6 on that payload.

Runs against the real Postgres inbox and Redis fast path, like the engine receiver's own
tests. The enqueue is stubbed: the job belongs to `apps/workers`, and a real enqueue
would hand a test payload to whatever worker happens to be running.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import carrier_events
import pytest
import webhook_routes
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from calevate_shared.carrier import CARRIER_EVENT_JOB, VOBIZ_CALLBACK_IPS, events_path
from calevate_shared.engine import owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from loguru import logger
from main import app as voice_app
from sqlalchemy import text

VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]
CALLER = "+919876500011"
OUR_NUMBER = "+918000000001"
FORM = {"content-type": "application/x-www-form-urlencoded"}

Enqueued = list[tuple[str, dict[str, Any], str | None]]


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> Iterator[Enqueued]:
    seen: Enqueued = []

    async def _stub(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        seen.append((job, payload, job_id))
        return job_id or "stub"

    for name in ("VOBIZ_AUTH_TOKEN", "VOBIZ_SIGNATURE_REQUIRED", "VOBIZ_CALLBACK_IPS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(webhook_routes, "enqueue", _stub)
    yield seen
    get_settings.cache_clear()


def _ref() -> str:
    return owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))


def _form(**fields: str) -> bytes:
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items()).encode()


async def _send(
    path: str,
    *,
    method: str = "POST",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    source_ip: str = VOBIZ_IP,
) -> Any:
    sent = {"cf-connecting-ip": source_ip, **(headers if headers is not None else FORM)}
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.request(method, path, headers=sent, content=content)


def _hangup(call_uuid: str, **extra: str) -> bytes:
    return _form(
        CallUUID=call_uuid,
        Event="Hangup",
        From=CALLER,
        To=OUR_NUMBER,
        CallStatus="completed",
        Direction="inbound",
        HangupCause="NORMAL_CLEARING",
        Duration="62",
        BillDuration="60",
        **extra,
    )


# --- accepted, duplicate, a new event on the same call -----------------------------------


async def test_a_hangup_is_claimed_queued_and_acked_with_200(enqueued: Enqueued) -> None:
    call_uuid, ref = str(uuid.uuid4()), _ref()

    response = await _send(events_path("vobiz", ref), content=_hangup(call_uuid))

    assert response.status_code == 200
    assert float(response.headers["X-Ack-Ms"]) >= 0
    assert response.json()["status"] == "accepted"
    assert response.json()["execution_id"] == call_uuid
    ((job, payload, job_id),) = enqueued
    assert job == CARRIER_EVENT_JOB
    assert job_id == f"{CARRIER_EVENT_JOB}:vobiz:{call_uuid}:Hangup"
    assert payload["carrier"] == "vobiz"
    assert payload["carrier_call_id"] == call_uuid
    assert payload["event"] == "Hangup"
    assert payload["engine_agent_ref"] == ref
    assert payload["call_id"] is None
    assert uuid.UUID(payload["inbox_row_id"])
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT provider, event_key, status FROM webhook_inbox_events WHERE id = :id"),
                {"id": payload["inbox_row_id"]},
            )
        ).one()
    assert tuple(row) == ("vobiz", f"{call_uuid}:Hangup", "enqueued")


async def test_a_vendor_retry_is_a_duplicate_and_a_new_event_is_not(enqueued: Enqueued) -> None:
    call_uuid, path = str(uuid.uuid4()), events_path("vobiz", _ref())

    first = await _send(path, content=_hangup(call_uuid))
    retry = await _send(path, content=_hangup(call_uuid))
    ring = await _send(path, content=_form(CallUUID=call_uuid, Event="Ring"))

    assert first.json()["status"] == "accepted"
    assert retry.status_code == 200 and retry.json()["status"] == "duplicate"
    assert ring.json()["status"] == "accepted"
    assert [payload["event"] for _job, payload, _id in enqueued] == ["Hangup", "Ring"]


async def test_a_get_callback_is_read_from_its_query(enqueued: Enqueued) -> None:
    call_uuid = str(uuid.uuid4())

    response = await _send(
        f"{events_path('vobiz', _ref())}?CallUUID={call_uuid}&Event=Ring",
        method="GET",
        headers={},
    )

    assert response.json()["status"] == "accepted"
    assert enqueued[0][1]["event"] == "Ring"


async def test_a_json_callback_is_read_too(enqueued: Enqueued) -> None:
    """The callbacks page prints JSON under a form-encoded label (`callbacks.md:37-55`)."""
    call_uuid = str(uuid.uuid4())
    body = {"CallUUID": call_uuid, "Event": "StartApp", "Nested": {"a": 1}}

    response = await _send(
        events_path("vobiz", _ref()),
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.json()["status"] == "accepted"
    assert "Nested" not in enqueued[0][1]["fields"]


async def test_an_outbound_callback_carries_our_call_id(enqueued: Enqueued) -> None:
    call_id = str(uuid.uuid4())

    response = await _send(
        events_path("vobiz", _ref(), call_id=call_id), content=_hangup(str(uuid.uuid4()))
    )

    assert response.json()["status"] == "accepted"
    assert enqueued[0][1]["call_id"] == call_id


# --- hard rule 6 ------------------------------------------------------------------------


async def test_no_party_number_reaches_the_job_or_the_logs(enqueued: Enqueued) -> None:
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="DEBUG")

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record) + repr(record.__dict__))

    handler = _Capture()
    logging.getLogger().addHandler(handler)
    try:
        response = await _send(
            events_path("vobiz", _ref()),
            content=_hangup(
                str(uuid.uuid4()),
                CallerName="Ravi",
                ForwardedFrom=CALLER,
                DialBLegTo="919876500012",
                DialBLegFrom=OUR_NUMBER,
                XPHContact="+91 98765 00013",
                TransferNumber="12345",
                Timestamp="1696245600",
                StartTime="2026-10-02 10:00:00",
            ),
        )
    finally:
        logging.getLogger().removeHandler(handler)
        logger.remove(sink)

    assert response.status_code == 200
    fields = enqueued[0][1]["fields"]
    assert set(fields) == {
        "CallUUID",
        "Event",
        "CallStatus",
        "Direction",
        "HangupCause",
        "Duration",
        "BillDuration",
        "Timestamp",
        "StartTime",
    }
    rendered = repr(enqueued) + "".join(lines)
    for number in (CALLER, OUR_NUMBER, "9876500012", "98765 00013"):
        assert number not in rendered and number.lstrip("+") not in rendered


def test_the_field_filter_bounds_what_it_keeps() -> None:
    many = {f"Field{i}": "x" for i in range(100)}
    assert len(carrier_events.event_fields(many)) == 64
    assert carrier_events.event_fields({"Error": "y" * 300, "z" * 300: "1"}) == {}


# --- what is acked without being queued ---------------------------------------------------


@pytest.mark.parametrize(
    ("content", "headers", "reason"),
    [
        (_form(Event="Hangup"), FORM, "unusable call key"),
        (_form(CallUUID="c\x01d", Event="Hangup"), FORM, "unusable call key"),
        (_form(CallUUID="c", Event="E" * 200), FORM, "unusable call key"),
        (b"{not json", {"content-type": "application/json"}, "unreadable payload"),
        (b"[1, 2]", {"content-type": "application/json"}, "unreadable payload"),
        (b"CallUUID=c", {"content-type": "text/plain"}, "unreadable payload"),
    ],
    ids=["no-call-uuid", "control-chars", "event-too-long", "bad-json", "json-array", "other-type"],
)
async def test_an_unkeyable_callback_is_acked_ignored(
    content: bytes, headers: dict[str, str], reason: str, enqueued: Enqueued
) -> None:
    response = await _send(events_path("vobiz", _ref()), content=content, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": reason}
    assert "X-Ack-Ms" in response.headers
    assert enqueued == []


# --- refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "source_ip"),
    [
        ("/carrier/v1/vobiz/events/not-a-ref", VOBIZ_IP),
        (
            events_path("vobiz", owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))),
            "203.0.113.9",
        ),
        ("/carrier/v1/twilio/events/x", VOBIZ_IP),
        (
            events_path(
                "vobiz", owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4())), call_id="x"
            ),
            VOBIZ_IP,
        ),
        # Plivo's callback grammar is unread, so its worker job could only refuse; the
        # route must not turn an unauthenticated POST into an inbox row and an alarm.
        (
            events_path("plivo", owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))),
            "203.0.113.9",
        ),
    ],
    ids=["unknown-ref", "stranger", "unknown-carrier", "bad-call-id", "unread-carrier"],
)
async def test_a_refused_callback_queues_nothing_and_still_reports_its_ack(
    path: str, source_ip: str, enqueued: Enqueued
) -> None:
    response = await _send(path, content=_hangup(str(uuid.uuid4())), source_ip=source_ip)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/carrier_ref_unknown")
    assert "X-Ack-Ms" in response.headers
    assert enqueued == []


async def test_an_oversized_callback_is_refused_with_413(enqueued: Enqueued) -> None:
    response = await _send(events_path("vobiz", _ref()), content=b"CallUUID=" + b"a" * 70_000)

    assert response.status_code == 413
    assert enqueued == []
