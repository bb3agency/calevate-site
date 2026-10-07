"""The shared secret on every Vobiz callback URL (D-673, OPERATIONS §2 gate 55).

Vobiz's published source addresses are shared by every Vobiz customer, so the address check
alone admits anyone who points their own Vobiz number at one of our agent refs. Driven here:
the route refuses a request without the secret, with a wrong one, with two, and from a
non-Vobiz address even when the secret is right; it admits the current secret and the
previous one only while it is configured; a present-but-invalid signature is still refused;
every URL we hand Vobiz carries the secret; the secret is never forwarded into the job
payload nor printed by any log line or Sentry event; and the deploy gate refuses a Vobiz
host without it.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import carrier_routes
import httpx
import pytest
import webhook_routes
from apps.api.agents.transfer_providers import TransferRefusedError, TransferRequest
from apps.api.agents.transfer_providers.vobiz import VobizTransfers
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter, redact_text
from apps.api.core.observability import scrub_event
from apps.api.core.settings import get_settings
from calevate_shared.carrier import (
    CALLBACK_SECRET_PARAM,
    VOBIZ_CALLBACK_IPS,
    answer_path,
    events_path,
    transfer_path,
    with_callback_secret,
)
from calevate_shared.engine import ProvisionedNumber, owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from scripts.check_deploy_env import REFUSE, evaluate
from starlette.requests import Request
from tests.deploy_env_preflight_test import good_env
from tests.vobiz_dial_test import REF, _ctx, _engine, _Vobiz

#: Base64-shaped on purpose (`openssl rand -base64 48` is what the founder may type): `+`,
#: `/` and `=` must survive the round trip through the URL. Not a real secret.
SECRET = "Zq8+/kW3xT0vLm9pN2rB7cY4hJ6dF1sA5gE+oU/iP8tR=="
PREVIOUS = "an-older-callback-secret-0123456789abcdef"
WRONG = "not-the-callback-secret-0123456789abcdef!"
STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
HOOKS = "https://hooks.example.test"
VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]
STRANGER_IP = "203.0.113.9"
CLAIM_KEY = "callback-secret-test-claim-key-0123456789"

Env = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS)
    monkeypatch.setenv("CARRIER_CLAIM_SECRET", CLAIM_KEY)
    monkeypatch.setenv("VOBIZ_CALLBACK_SECRET", SECRET)
    for name in (
        "VOBIZ_CALLBACK_SECRET_RETIRED",
        "VOBIZ_AUTH_TOKEN",
        "VOBIZ_SIGNATURE_REQUIRED",
        "VOBIZ_CALLBACK_IPS",
        "CARRIER_RECORDING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    def apply(**values: str | None) -> None:
        for name, value in values.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _ref() -> str:
    return owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))


def _with(path: str, *secrets: str) -> str:
    if not secrets:
        return path
    query = "&".join(f"{CALLBACK_SECRET_PARAM}={quote(s, safe='')}" for s in secrets)
    return f"{path}?{query}"


async def _post(
    path: str,
    *,
    source_ip: str = VOBIZ_IP,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> Any:
    sent = {"cf-connecting-ip": source_ip, **(headers or {})}
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime:8100") as client:
        return await client.post(path, headers=sent, content=content)


# --- the route ------------------------------------------------------------------------


async def test_the_right_secret_from_a_vobiz_address_is_served(env: Env) -> None:
    response = await _post(_with(answer_path("vobiz", _ref()), SECRET))
    assert response.status_code == 200
    assert "<Stream" in response.text


@pytest.mark.parametrize(
    ("secrets", "reason"),
    [
        ((), "callback secret missing"),
        ((WRONG,), "callback secret invalid"),
        ((SECRET, SECRET), "callback secret invalid"),
    ],
    ids=["missing", "wrong", "repeated"],
)
async def test_a_request_without_exactly_the_secret_is_refused(
    env: Env, caplog: pytest.LogCaptureFixture, secrets: tuple[str, ...], reason: str
) -> None:
    caplog.set_level(logging.WARNING)
    for path in (answer_path("vobiz", _ref()), events_path("vobiz", _ref())):
        response = await _post(_with(path, *secrets))
        assert response.status_code == 404
        assert response.json()["type"].endswith("/carrier_ref_unknown")
    reasons = {
        getattr(record, "reason", None)
        for record in caplog.records
        if record.getMessage() == "carrier_request_refused"
    }
    assert reasons == {reason}


async def test_the_right_secret_from_outside_vobiz_is_still_refused(env: Env) -> None:
    response = await _post(_with(answer_path("vobiz", _ref()), SECRET), source_ip=STRANGER_IP)
    assert response.status_code == 404


async def test_a_present_but_invalid_signature_is_refused_whatever_secret_came_with_it(
    env: Env,
) -> None:
    env(VOBIZ_AUTH_TOKEN="vobiz-test-auth-token")
    forged = {"X-Vobiz-Signature-V3": "forged", "X-Vobiz-Signature-V3-Nonce": "1"}
    response = await _post(_with(answer_path("vobiz", _ref()), SECRET), headers=forged)
    assert response.status_code == 404


async def test_the_previous_secret_is_admitted_only_while_it_is_configured(env: Env) -> None:
    path = _with(answer_path("vobiz", _ref()), PREVIOUS)
    assert (await _post(path)).status_code == 404

    env(VOBIZ_CALLBACK_SECRET_RETIRED=PREVIOUS)
    assert (await _post(path)).status_code == 200
    assert (await _post(_with(answer_path("vobiz", _ref()), SECRET))).status_code == 200

    env(VOBIZ_CALLBACK_SECRET_RETIRED=None)
    assert (await _post(path)).status_code == 404


async def test_a_secret_under_the_floor_is_no_secret(env: Env) -> None:
    """Set but short looks configured; it is treated as absent, so in `local` the route
    admits without it and a request carrying it is checked against nothing."""
    env(VOBIZ_CALLBACK_SECRET="short")
    assert (await _post(answer_path("vobiz", _ref()))).status_code == 200


def _request(query: bytes) -> Request:
    return Request({"type": "http", "method": "POST", "query_string": query, "headers": []})


def test_outside_local_no_configured_secret_refuses_and_local_admits(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env(VOBIZ_CALLBACK_SECRET=None)
    assert carrier_routes._callback_secret_verdict("vobiz", _request(b"")) is None

    monkeypatch.setattr(get_settings(), "app_env", "prod", raising=False)
    verdict = carrier_routes._callback_secret_verdict("vobiz", _request(b""))
    assert verdict is not None
    assert (verdict.ok, verdict.reason) == (False, "callback secret not configured")


def test_plivo_carries_no_secret_and_is_not_asked_for_one(env: Env) -> None:
    assert carrier_routes._callback_secret_verdict("plivo", _request(b"")) is None


async def test_the_secret_is_not_forwarded_into_the_job_payload(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    async def _stub(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        seen.append(payload)
        return job_id or "stub"

    monkeypatch.setattr(webhook_routes, "enqueue", _stub)
    call_uuid = str(uuid.uuid4())
    response = await _post(
        _with(events_path("vobiz", _ref()), SECRET),
        headers={"content-type": "application/x-www-form-urlencoded"},
        content=f"CallUUID={call_uuid}&Event=Hangup&HangupCause=NORMAL_CLEARING".encode(),
    )
    assert response.status_code == 200
    (payload,) = seen
    assert CALLBACK_SECRET_PARAM not in payload["fields"]
    assert SECRET not in json.dumps(payload)


# --- the URLs we register ---------------------------------------------------------------


def _secret_of(url: str) -> list[str]:
    return parse_qs(urlsplit(url).query).get(CALLBACK_SECRET_PARAM, [])


def test_the_url_encoding_survives_base64() -> None:
    url = with_callback_secret(f"{HOOKS}/carrier/v1/vobiz/events/x", SECRET)
    assert "+" not in urlsplit(url).query and "/" not in urlsplit(url).query
    assert _secret_of(url) == [SECRET]
    assert with_callback_secret(url, None) == url


async def test_a_dial_registers_answer_hangup_and_ring_urls_carrying_the_secret(
    env: Env,
) -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "vz-1"}))
    engine, _ = _engine(stub)
    await engine.start_outbound_call(REF, "+919876543210", _ctx())
    body = json.loads(stub.requests[0].content)
    for field in ("answer_url", "hangup_url", "ring_url"):
        assert _secret_of(body[field]) == [SECRET], field
        assert urlsplit(body[field]).path.startswith("/carrier/v1/vobiz/")


async def test_a_binding_writes_the_secret_onto_the_application(env: Env) -> None:
    stub = _Vobiz(
        httpx.Response(200, json={"objects": []}),
        httpx.Response(200, json={"app_id": "app-1"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    engine, _ = _engine(stub)
    await engine.bind_inbound_number(
        REF, ProvisionedNumber(e164="+911140000001", engine_number_ref="n-1")
    )
    created = json.loads(stub.requests[1].content)
    assert _secret_of(created["answer_url"]) == [SECRET]
    assert _secret_of(created["hangup_url"]) == [SECRET]


async def test_outside_local_a_dial_or_binding_without_a_secret_is_refused_before_any_request(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env(VOBIZ_CALLBACK_SECRET=None)
    monkeypatch.setattr(get_settings(), "app_env", "prod", raising=False)
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    engine, _ = _engine(stub)
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert raised.value.code == "carrier_dial_precondition_failed"
    assert "callback secret" in str(raised.value.detail)
    with pytest.raises(ProblemError):
        await engine.bind_inbound_number(
            REF, ProvisionedNumber(e164="+911140000001", engine_number_ref="n-1")
        )
    assert stub.requests == []


def test_the_recording_callback_carries_the_secret(env: Env) -> None:
    ref = _ref()
    recording = carrier_routes.session_recording_for(
        carrier_routes.CARRIER_ANSWER_CONTRACT["vobiz"], ref, call_id=None, recorded=True
    )
    assert recording is not None and recording.callback_url is not None
    assert recording.callback_url.startswith(HOOKS + events_path("vobiz", ref) + "?")
    assert _secret_of(recording.callback_url) == [SECRET]


class _Carrier:
    def __init__(self) -> None:
        self.redirects: list[str] = []

    async def transfer(self, carrier_call_id: str, *, redirect_url: str) -> None:
        self.redirects.append(redirect_url)


_TRANSFER = TransferRequest(
    call_ref="vz-call-1",
    to_e164="+919000000042",
    present_as="+911140000000",
    whisper="w",
    accept_key="1",
    ring_timeout_s=25,
    whisper_timeout_s=10,
)


async def test_the_transfer_redirect_carries_the_secret(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env(CARRIER_TRANSFER_ENABLED="true")
    carrier = _Carrier()
    await VobizTransfers(carrier=carrier).start_transfer(_TRANSFER)  # type: ignore[arg-type]
    (redirect,) = carrier.redirects
    assert urlsplit(redirect).path.startswith(transfer_path("vobiz", ""))
    assert _secret_of(redirect) == [SECRET]

    env(VOBIZ_CALLBACK_SECRET=None)
    monkeypatch.setattr(get_settings(), "app_env", "prod", raising=False)
    with pytest.raises(TransferRefusedError, match="VOBIZ_CALLBACK_SECRET"):
        await VobizTransfers(carrier=_Carrier()).start_transfer(_TRANSFER)  # type: ignore[arg-type]


# --- the secret never reaches a log line ----------------------------------------------


async def test_no_log_line_prints_the_secret(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    ref = _ref()
    await _post(_with(answer_path("vobiz", ref), SECRET))
    await _post(_with(answer_path("vobiz", ref), WRONG))
    await _post(_with(answer_path("vobiz", ref), SECRET), source_ip=STRANGER_IP)
    # What uvicorn's access logger emits for the same request: the full target, query and
    # all, rendered into the message rather than carried as an extra. Built directly
    # because `configure_logging` stops that logger propagating to `caplog`'s handler.
    access = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        (VOBIZ_IP, "POST", _with(answer_path("vobiz", ref), SECRET), "1.1", 200),
        None,
    )
    formatter = JsonFormatter()
    assert caplog.records, "nothing was logged, so nothing was checked"
    rendered = "\n".join(formatter.format(record) for record in [*caplog.records, access])
    for value in (SECRET, quote(SECRET, safe=""), WRONG, quote(WRONG, safe="")):
        assert value not in rendered
    assert f"{CALLBACK_SECRET_PARAM}=[redacted]" in rendered


def test_the_redactor_masks_the_secret_wherever_it_appears() -> None:
    hex_secret = "0123456789abcdef" * 4
    line = f"POST /carrier/v1/vobiz/events/x?{CALLBACK_SECRET_PARAM}={hex_secret}&a=1 200"
    masked = redact_text(line)
    assert hex_secret not in masked
    assert f"{CALLBACK_SECRET_PARAM}=[redacted]&a=1" in masked


def test_a_sentry_event_carries_no_secret() -> None:
    event: dict[str, Any] = {
        "request": {
            "url": f"{HOOKS}/carrier/v1/vobiz/answer/x",
            "query_string": f"{CALLBACK_SECRET_PARAM}={quote(SECRET, safe='')}",
        }
    }
    scrubbed = scrub_event(event)
    assert scrubbed is not None
    assert quote(SECRET, safe="") not in json.dumps(scrubbed)


# --- the deploy gate ------------------------------------------------------------------


def _codes(env: dict[str, str]) -> set[str]:
    return {f.code for f in evaluate(env, None) if f.severity == REFUSE}


def test_the_deploy_gate_refuses_a_vobiz_host_without_the_secret() -> None:
    env = good_env()
    env.pop("VOBIZ_CALLBACK_SECRET", None)
    assert "vobiz_callback_secret_unusable" in _codes(env)
    assert "vobiz_callback_secret_unusable" in _codes(env | {"CARRIER": "vobiz"})
    assert "vobiz_callback_secret_unusable" not in _codes(env | {"CARRIER": "plivo"})
    assert "vobiz_callback_secret_unusable" not in _codes(env | {"APP_ENV": "local"})


def test_the_deploy_gate_refuses_a_short_or_reused_secret_and_prints_neither() -> None:
    env = good_env()
    for bad in ("too-short", env["CARRIER_CLAIM_SECRET"], env["VOBIZ_AUTH_TOKEN"]):
        findings = [
            f
            for f in evaluate(env | {"VOBIZ_CALLBACK_SECRET": bad}, None)
            if f.code == "vobiz_callback_secret_unusable"
        ]
        assert findings, bad
        assert bad not in "\n".join(f.render() for f in findings)


def test_the_deploy_gate_refuses_a_retired_secret_equal_to_the_current_one() -> None:
    env = good_env()
    same = env | {"VOBIZ_CALLBACK_SECRET_RETIRED": env["VOBIZ_CALLBACK_SECRET"]}
    assert "retired_key_equals_active" in _codes(same)


async def test_the_answer_and_the_hangup_log_their_signature_outcome(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate 55 records, per route, whether Vobiz signed (`runbooks/vobiz-first-live-call.md`
    §6). Both admissions must say so in `auth_reason`; neither may carry the secret."""

    async def _stub(job: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        return job_id or "stub"

    monkeypatch.setattr(webhook_routes, "enqueue", _stub)
    caplog.set_level(logging.INFO)
    ref = _ref()
    assert (await _post(_with(answer_path("vobiz", ref), SECRET))).status_code == 200
    hangup = await _post(
        _with(events_path("vobiz", ref), SECRET),
        headers={"content-type": "application/x-www-form-urlencoded"},
        content=f"CallUUID={uuid.uuid4()}&HangupCause=NORMAL_CLEARING".encode(),
    )
    assert hangup.status_code == 200

    by_message = {record.getMessage(): record for record in caplog.records}
    served = by_message["carrier_answer_served"]
    admitted = by_message["carrier_event_admitted"]
    for record in (served, admitted):
        assert getattr(record, "auth_method", None) == "callback_secret"
        assert getattr(record, "auth_reason", None) == "unsigned"
    assert getattr(admitted, "event", None) == "unknown"
    assert all(SECRET not in str(vars(record)) for record in (served, admitted))
