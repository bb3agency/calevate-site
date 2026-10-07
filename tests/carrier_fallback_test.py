"""The carrier's fallback answer URL, the answer and hangup legs' correlation and latency
lines, and the hangup readings added with them (D-675).

Vobiz invokes a fallback "only if `answer_url` is unreachable, times out, or returns invalid
VobizXML"; with none set "the call drops" (`vobiz-findings/mirror/pages/applications/
create-application.md:34`, `call/make-call.md:44`). What is driven here: the document is a
busy rejection; the route serves it and alarms for an authentic request, and serves it
without an alarm to anything else; nginx's static copy is the same document; every dial and
every Application registers it with the callback secret; and the answer and events routes
log the carrier's call id and the ack latency.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit
from xml.etree.ElementTree import fromstring

import carrier_routes
import httpx
import pytest
import webhook_routes
from apps.api.core.settings import get_settings
from apps.api.engine.carrier import RING_TIMEOUT_S, build_carrier
from apps.api.engine.vobiz import VobizCarrier, fallback_url_for, parse_event
from calevate_shared.carrier import (
    CALLBACK_SECRET_PARAM,
    VOBIZ_CALLBACK_IPS,
    answer_path,
    events_path,
    fallback_path,
)
from calevate_shared.engine import owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

ROOT = Path(__file__).resolve().parents[1]
NGINX_TEMPLATE = ROOT / "infra" / "nginx" / "calevate.conf.template"

SECRET = "fallback-test-callback-secret-0123456789abcdef"
HOOKS = "https://hooks.example.test"
STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
CLAIM_KEY = "fallback-test-claim-key-0123456789abcdefgh"
VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]
STRANGER_IP = "203.0.113.9"
FORM = {"content-type": "application/x-www-form-urlencoded"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS)
    monkeypatch.setenv("CARRIER_CLAIM_SECRET", CLAIM_KEY)
    monkeypatch.setenv("VOBIZ_CALLBACK_SECRET", SECRET)
    for name in (
        "VOBIZ_CALLBACK_SECRET_RETIRED",
        "VOBIZ_AUTH_TOKEN",
        "VOBIZ_SIGNATURE_REQUIRED",
        "VOBIZ_CALLBACK_IPS",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ref() -> str:
    return owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))


def _keyed(path: str) -> str:
    return f"{path}?{CALLBACK_SECRET_PARAM}={quote(SECRET, safe='')}"


def _form(**fields: str) -> bytes:
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items()).encode()


async def _post(path: str, *, content: bytes = b"", source_ip: str = VOBIZ_IP) -> Any:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime:8100") as client:
        return await client.post(
            path, headers={"cf-connecting-ip": source_ip, **FORM}, content=content
        )


def _alert_codes(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [str(r.__dict__.get("code")) for r in caplog.records if r.message == "alert"]


def _record(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    (found,) = [r for r in caplog.records if r.message == message]
    return found


# --- the document -----------------------------------------------------------------------


def test_the_fallback_document_rejects_the_call_busy_before_answering_it() -> None:
    """`<Hangup>` first, `reason="busy"` (`xml/hangup.md:13-21`): not answered, not billed."""
    root = fromstring(carrier_routes.fallback_document())
    assert root.tag == "Response"
    (hangup,) = list(root)
    assert hangup.tag == "Hangup"
    assert hangup.attrib == {"reason": "busy"}


def test_nginx_serves_the_same_document_when_voice_runtime_cannot() -> None:
    template = NGINX_TEMPLATE.read_text(encoding="utf-8")
    exact = re.search(
        rf"location\s+=\s+{re.escape(fallback_path('vobiz'))}\s*\{{([^}}]*)\}}", template
    )
    assert exact is not None, "nginx no longer routes the fallback path to voice-runtime"
    body = exact.group(1)
    assert "proxy_pass http://calevate_hooks;" in body
    assert re.search(r"error_page\s+502 503 504\s+=\s+@carrier_fallback_document;", body)
    static = re.search(
        r"location\s+@carrier_fallback_document\s*\{[^}]*return\s+200\s+'([^']*)';", template
    )
    assert static is not None, "nginx no longer carries the static fallback document"
    ours, theirs = fromstring(carrier_routes.fallback_document()), fromstring(static.group(1))
    assert (ours.tag, [(c.tag, c.attrib) for c in ours]) == (
        theirs.tag,
        [(c.tag, c.attrib) for c in theirs],
    )


# --- the route --------------------------------------------------------------------------


async def test_an_authentic_fallback_is_served_and_alarms_with_the_call_id(
    env: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    call_uuid = str(uuid.uuid4())

    response = await _post(
        _keyed(fallback_path("vobiz")),
        content=_form(CallUUID=call_uuid, Direction="inbound", From="+919876500011"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["cache-control"] == "no-store"
    assert float(response.headers["X-Ack-Ms"]) >= 0
    assert fromstring(response.text).find("Hangup") is not None
    assert "carrier_answer_fallback_served" in _alert_codes(caplog)
    alarm = [
        r for r in caplog.records if r.__dict__.get("code") == "carrier_answer_fallback_served"
    ]
    assert alarm[0].__dict__["carrier_call_id"] == call_uuid
    assert alarm[0].__dict__["direction"] == "inbound"
    assert "+919876500011" not in caplog.text


async def test_an_inauthentic_fallback_gets_the_same_document_and_no_alarm(
    env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The commonest reason a real answer fails (a rotated secret, a renumbered carrier)
    would fail this request too; a busy tone beats a dropped call, and the document names
    nothing a stranger could use."""
    caplog.set_level(logging.INFO)
    for path, ip in (
        (fallback_path("vobiz"), VOBIZ_IP),
        (_keyed(fallback_path("vobiz")), STRANGER_IP),
    ):
        response = await _post(path, source_ip=ip)
        assert response.status_code == 200
        assert response.text == carrier_routes.fallback_document()
    assert "carrier_answer_fallback_served" not in _alert_codes(caplog)
    assert [r for r in caplog.records if r.message == "carrier_request_refused"]


async def test_a_fallback_for_an_unknown_carrier_is_refused(env: None) -> None:
    response = await _post("/carrier/v1/nonesuch/fallback")
    assert response.status_code == 404


def test_the_shared_path_is_the_one_nginx_and_the_route_spell() -> None:
    """The route answering at all is the tests above; this pins the literal both read."""
    assert fallback_path("vobiz") == "/carrier/v1/vobiz/fallback"


# --- every URL we register carries it ---------------------------------------------------


def test_the_fallback_url_carries_the_callback_secret(env: None) -> None:
    url = fallback_url_for(get_settings())
    assert url is not None
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == HOOKS
    assert parts.path == fallback_path("vobiz")
    assert parse_qs(parts.query)[CALLBACK_SECRET_PARAM] == [SECRET]
    built = build_carrier(get_settings(), "vobiz")
    assert isinstance(built, VobizCarrier)


def test_no_fallback_is_registered_on_a_base_the_carrier_cannot_reach(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEBHOOK_BASE_URL", "http://localhost:8100")
    get_settings.cache_clear()
    assert fallback_url_for(get_settings()) is None


class _Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def _carrier(stub: _Recorder, fallback: str | None) -> VobizCarrier:
    base = "https://api.vobiz.ai/api/v1"
    return VobizCarrier(
        auth_id="MA_TEST",
        auth_token="tok",
        base_url=base,
        client=httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(stub)),
        fallback_url=fallback,
    )


@pytest.mark.anyio
async def test_a_dial_registers_the_fallback_url() -> None:
    """`fallback_url` / `fallback_method` (`call/make-call.md:44-45`)."""
    stub = _Recorder(httpx.Response(200, json={"request_uuid": "u-1"}))
    await _carrier(stub, "https://hooks.example/carrier/v1/vobiz/fallback?k=1").place_call(
        from_e164="+911140000000",
        to_e164="+919876543210",
        answer_url="https://a",
        hangup_url="https://e",
        ring_url="https://e",
        time_limit_s=660,
        ring_timeout_s=RING_TIMEOUT_S,
    )
    body = json.loads(stub.requests[0].content)
    assert body["fallback_url"] == "https://hooks.example/carrier/v1/vobiz/fallback?k=1"
    assert body["fallback_method"] == "POST"


@pytest.mark.anyio
async def test_an_application_registers_the_fallback_answer_url() -> None:
    """`fallback_answer_url` / `fallback_method` (`applications/create-application.md:34-35`)."""
    stub = _Recorder(
        httpx.Response(200, json={"objects": []}),
        httpx.Response(201, json={"app_id": "9"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    await _carrier(stub, "https://hooks.example/fb").bind_number(
        "+911140000000", answer_url="https://a", hangup_url="https://e", label="agent-1"
    )
    created = json.loads(stub.requests[1].content)
    assert created["fallback_answer_url"] == "https://hooks.example/fb"
    assert created["fallback_method"] == "POST"


# --- correlation and latency on the answer and hangup legs ------------------------------


async def test_the_answer_line_carries_the_carrier_call_id_and_its_latency(
    env: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    call_uuid = str(uuid.uuid4())

    response = await _post(
        _keyed(answer_path("vobiz", _ref())),
        content=_form(CallUUID=call_uuid, From="+919876500011", To="+918000000001"),
    )

    assert response.status_code == 200
    served = _record(caplog, "carrier_answer_served")
    assert served.__dict__["carrier_call_id"] == call_uuid
    assert served.__dict__["ack_ms"] == float(response.headers["X-Ack-Ms"])


async def test_the_events_route_logs_each_delivery_with_its_outcome(
    env: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _stub(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        return job_id or "stub"

    monkeypatch.setattr(webhook_routes, "enqueue", _stub)
    caplog.set_level(logging.INFO)
    call_uuid, ref = str(uuid.uuid4()), _ref()
    hangup = _form(CallUUID=call_uuid, Event="Hangup", HangupCause="NORMAL_CLEARING")

    first = await _post(_keyed(events_path("vobiz", ref)), content=hangup)
    again = await _post(_keyed(events_path("vobiz", ref)), content=hangup)

    assert (first.status_code, again.status_code) == (200, 200)
    acked = [r for r in caplog.records if r.message == "carrier_event_acked"]
    assert [r.__dict__["status"] for r in acked] == ["accepted", "duplicate"]
    assert {r.__dict__["carrier_call_id"] for r in acked} == {call_uuid}
    admitted = _record_first(caplog, "carrier_event_admitted")
    assert admitted.__dict__["carrier_call_id"] == call_uuid
    assert uuid.UUID(admitted.__dict__["tenant_id"]) and uuid.UUID(admitted.__dict__["agent_id"])


def _record_first(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    return next(r for r in caplog.records if r.message == message)


# --- the hangup readings ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "kind", "status"),
    [
        # A machine verdict of `false` is a person (`call/machine-detection.md:162`).
        ({"CallUUID": "c", "Event": "MachineDetection", "Machine": "false"}, "other", None),
        ({"CallUUID": "c", "Event": "MachineDetection", "Machine": "true"}, "machine", "voicemail"),
        # 6000 is an answered call cut at our `time_limit` (`concepts/hangup-causes.md:118`).
        ({"CallUUID": "c", "Event": "Hangup", "HangupCauseCode": "6000"}, "hangup", "completed"),
        ({"CallUUID": "c", "Event": "Hangup", "HangupCauseCode": "9100"}, "hangup", "voicemail"),
    ],
)
def test_hangup_and_machine_readings(fields: dict[str, str], kind: str, status: str | None) -> None:
    event = parse_event(fields)
    assert event is not None
    assert (event.kind, event.status) == (kind, status)
