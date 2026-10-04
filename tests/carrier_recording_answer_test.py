"""voice-runtime asks Vobiz to record a call, and only when the agent says so (D-668).

What this file catches:

1. **The document is the vendor's shape.** A self-closing `<Record>` BEFORE the bidirectional
   `<Stream>`, `recordSession="true"`, `redirect="false"`
   (`vobiz-findings/mirror/pages/xml/record/stream-with-record.md:11,19-22`), with both
   60-second defaults raised (`xml/record.md:19-20`), no beep, a single finish key, and
   `RecordStop` sent to the agent's own events route.
2. **Hard rule 5, the dangerous direction.** A call is recorded only when its answer URL
   carries the `recorded` segment, which the control plane writes only for an agent
   PUBLISHED announcing a recording. The plain URL never records, whatever the switch says.
3. **The switch stops recording at once** (`carrier_recording_enabled` off), and Plivo,
   whose recording grammar is unread, never records.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote
from xml.etree.ElementTree import fromstring

import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.carrier import RECORDED_SEGMENT, VOBIZ_CALLBACK_IPS, answer_path, events_path
from calevate_shared.engine import owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
HOOKS = "https://hooks.example.test"
VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]
CLAIM_KEY = "k" * 32

Env = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS)
    monkeypatch.setenv("CARRIER_CLAIM_SECRET", CLAIM_KEY)
    for name in (
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


async def _get(path: str) -> Any:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.get(path, headers={"cf-connecting-ip": VOBIZ_IP})


def _children(body: str) -> list[Any]:
    return list(fromstring(body))


# --- 1. the document ---------------------------------------------------------------------


def test_the_record_element_is_the_vendors_whole_session_shape() -> None:
    element = carrier_routes.record_element(
        carrier_routes.SessionRecording(callback_url=f"{HOOKS}/cb")
    )
    assert element.tag == "Record"
    assert list(element) == [] and not (element.text or "").strip(), "self-closing"
    assert element.attrib["recordSession"] == "true"
    assert element.attrib["redirect"] == "false"
    assert element.attrib["callbackUrl"] == f"{HOOKS}/cb"
    assert element.attrib["callbackMethod"] == "POST"
    assert "action" not in element.attrib, "recordSession needs callbackUrl alone"
    # Neither 60-second default may end a conversation's recording early.
    assert int(element.attrib["maxLength"]) >= 3600
    assert int(element.attrib["timeout"]) >= 3600
    assert element.attrib["fileFormat"] in {"mp3", "wav"}


def test_no_beep_and_one_finish_key_the_agent_never_asks_for() -> None:
    """Founder, 3 Oct 2026: no beep, and a keypress must not stop the recording.

    `playBeep` must be the literal `false`: absent means the vendor default, which is
    `true` (`xml/record.md:21`). `finishOnKey` must be present and exactly one documented
    key (digits, `#`, `*`, `:22`): absent means every key, and `#` is the key callers are
    taught to press after typing digits.
    """
    element = carrier_routes.record_element(carrier_routes.SessionRecording(callback_url=None))
    assert element.attrib["playBeep"] == "false"
    key = element.attrib["finishOnKey"]
    assert key == carrier_routes.RECORDING_FINISH_ON_KEY == "*"
    assert len(key) == 1 and key in "0123456789#*"
    assert key != "#"


def test_record_goes_before_the_stream_and_the_stream_is_unchanged() -> None:
    plain = carrier_routes.answer_document("wss://w/x")
    recorded = carrier_routes.answer_document(
        "wss://w/x", recording=carrier_routes.SessionRecording(callback_url=f"{HOOKS}/cb")
    )
    record, stream = _children(recorded)
    assert record.tag == "Record" and stream.tag == "Stream"
    (plain_stream,) = _children(plain)
    assert stream.attrib == plain_stream.attrib
    assert stream.text == plain_stream.text


def test_without_a_callback_base_the_call_is_still_recorded_and_alarmed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent has already told the caller it is recorded; dropping the recording would
    make that false. The sweep finds it by call id instead.

    `webhook_base_url` has a non-empty default and a scheme pattern, so unsetting the
    variable cannot produce an empty base; the settings object is copied without
    validation to put the route in the state this arm defends against."""
    env()
    blank = get_settings().model_copy(update={"webhook_base_url": ""})
    monkeypatch.setattr(carrier_routes, "get_settings", lambda: blank)
    raised: list[str] = []
    monkeypatch.setattr(carrier_routes, "alert", lambda _stage, code, **_kw: raised.append(code))
    contract = carrier_routes.CARRIER_ANSWER_CONTRACT["vobiz"]
    recording = carrier_routes.session_recording_for(contract, _ref(), call_id=None, recorded=True)
    assert recording is not None and recording.callback_url is None
    assert raised == ["carrier_recording_callback_unset"]
    element = carrier_routes.record_element(recording)
    assert "callbackUrl" not in element.attrib


# --- 2. only an agent published announcing it ---------------------------------------------


def test_the_callback_is_the_agents_own_events_route(env: Env) -> None:
    contract = carrier_routes.CARRIER_ANSWER_CONTRACT["vobiz"]
    ref = _ref()
    call_id = str(uuid.uuid4())
    inbound = carrier_routes.session_recording_for(contract, ref, call_id=None, recorded=True)
    outbound = carrier_routes.session_recording_for(contract, ref, call_id=call_id, recorded=True)
    assert inbound is not None and outbound is not None
    assert inbound.callback_url == HOOKS + events_path("vobiz", ref)
    assert outbound.callback_url == HOOKS + events_path("vobiz", ref, call_id=call_id)


def test_an_agent_not_published_announcing_it_is_never_recorded(env: Env) -> None:
    contract = carrier_routes.CARRIER_ANSWER_CONTRACT["vobiz"]
    assert (
        carrier_routes.session_recording_for(contract, _ref(), call_id=None, recorded=False) is None
    )


def test_the_recorded_segment_is_the_last_path_segment_and_signed_with_the_path() -> None:
    ref = _ref()
    call_id = str(uuid.uuid4())
    assert answer_path("vobiz", ref, recorded=True) == (
        answer_path("vobiz", ref) + f"/{RECORDED_SEGMENT}"
    )
    assert answer_path("vobiz", ref, call_id=call_id, recorded=True) == (
        answer_path("vobiz", ref, call_id=call_id) + f"/{RECORDED_SEGMENT}"
    )
    assert "?" not in answer_path("vobiz", ref, call_id=call_id, recorded=True)


async def test_the_recorded_routes_serve_a_record_element_and_the_plain_ones_do_not(
    env: Env,
) -> None:
    ref = _ref()
    call_id = str(uuid.uuid4())
    for recorded, expected in ((True, ["Record", "Stream"]), (False, ["Stream"])):
        inbound = await _get(answer_path("vobiz", ref, recorded=recorded))
        outbound = await _get(answer_path("vobiz", ref, call_id=call_id, recorded=recorded))
        assert inbound.status_code == 200, inbound.text
        assert outbound.status_code == 200, outbound.text
        assert [c.tag for c in _children(inbound.text)] == expected
        assert [c.tag for c in _children(outbound.text)] == expected
    record = _children(
        (await _get(answer_path("vobiz", ref, call_id=call_id, recorded=True))).text
    )[0]
    assert record.attrib["callbackUrl"] == HOOKS + events_path("vobiz", ref, call_id=call_id)


async def test_a_recorded_route_still_refuses_a_stranger(env: Env) -> None:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        response = await client.get(
            answer_path("vobiz", _ref(), recorded=True),
            headers={"cf-connecting-ip": "203.0.113.9"},
        )
    assert response.status_code == 404


# --- 3. the switch, and the carrier whose grammar is unread --------------------------------


async def test_switching_recording_off_stops_it_on_the_next_call(env: Env) -> None:
    env(CARRIER_RECORDING_ENABLED="false")
    response = await _get(answer_path("vobiz", _ref(), recorded=True))
    assert response.status_code == 200
    assert [c.tag for c in _children(response.text)] == ["Stream"]


async def test_plivo_never_records(env: Env) -> None:
    assert carrier_routes.CARRIER_ANSWER_CONTRACT["plivo"].session_recording is False
    response = await _get(f"/carrier/v1/plivo/answer/{quote(_ref(), safe='')}/{RECORDED_SEGMENT}")
    assert response.status_code == 200
    assert [c.tag for c in _children(response.text)] == ["Stream"]
