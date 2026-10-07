"""Reading a Vobiz recording: the callback, the adapter, and the authenticated fetch (D-668).

What this file catches:

1. **`RecordStop` is a recording, never a call status.** It arrives after the hangup
   (`vobiz-findings/mirror/pages/xml/record/stream-with-record.md:54-78`); reading it as one
   would rewrite a finished call.
2. **The adapter resolves by id and checks the call.** `GET …/Recording/{id}/` is a flat
   object (`recording/retrieve-recording.md:36-59`); a recording the carrier attributes to
   another call is refused, a 404 is "gone", and the file URL is the API's, not the wire's.
3. **The credential goes only to the carrier's hosts.** Vobiz requires `X-Auth-ID` and
   `X-Auth-Token` on the download (`recording/download-recording.md:39-41`); a redirect
   elsewhere is followed WITHOUT them.
4. **The content type is the bytes'.** The container may not match the extension
   (`recording.md:24-37`), including an MPEG-2.5 sync of `0xFF 0xE3`.
5. **Delete is the documented route** (`root-site/openapi.json:8459-8484`): 204 deleted, 404
   already gone. Plivo refuses all three by name.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.carrier import CarrierRecording
from apps.api.engine.plivo_carrier import PlivoCarrier
from apps.api.engine.vobiz import (
    RECORDING_AUTH_HOSTS,
    RECORDING_ENDED_WITH_CALL,
    VobizCarrier,
    parse_event,
)
from apps.workers import storage
from apps.workers.storage import copy_recording, sniff_audio_content_type
from tests.conftest import FakeS3

BASE = "https://api.vobiz.ai/api/v1"
CALL_UUID = "5a9fd4a0-3d4c-11ef-bef9-0242ac110005"
RECORDING_ID = "d7801b2e-e76d-4dd8-be9c-9e015a7267b8"


class _Stub:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _vobiz(stub: _Stub) -> VobizCarrier:
    return VobizCarrier(
        auth_id="MA_X",
        auth_token="tok",
        base_url=BASE,
        client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(stub)),
    )


def _object(**overrides: object) -> dict[str, object]:
    found: dict[str, object] = {
        "call_uuid": CALL_UUID,
        "recording_id": RECORDING_ID,
        "recording_format": "mp3",
        "recording_url": f"https://media.vobiz.ai/api/v1/Account/MA_X/Recording/{RECORDING_ID}.mp3",
    }
    found.update(overrides)
    return found


# --- 1. the callback --------------------------------------------------------------------


def test_record_stop_is_a_recording_event_with_no_status() -> None:
    event = parse_event(
        {
            "Event": "RecordStop",
            "CallUUID": CALL_UUID,
            "RecordingID": RECORDING_ID,
            "RecordingDuration": "42",
            "RecordingEndReason": "HungUp",
        }
    )
    assert event is not None
    assert event.kind == "recording"
    assert event.status is None, "a recording callback must never move a call's status"
    assert event.recording == CarrierRecording(
        recording_id=RECORDING_ID, duration_s=42, end_reason="HungUp", ended_with_call=True
    )
    assert RECORDING_ENDED_WITH_CALL == "HungUp"


@pytest.mark.parametrize("reason", ["FinishedOnKey", "RecordingTimeout", "maxLength"])
def test_a_recording_that_stopped_before_the_call_says_so(reason: str) -> None:
    event = parse_event(
        {
            "Event": "RecordStop",
            "CallUUID": CALL_UUID,
            "RecordingID": RECORDING_ID,
            "RecordingEndReason": reason,
        }
    )
    assert event is not None and event.recording is not None
    assert event.recording.ended_with_call is False


def test_an_absent_end_reason_is_not_evidence_of_an_early_stop() -> None:
    """The stream-with-record table lists no `RecordingEndReason` (`:58-78`)."""
    event = parse_event({"Event": "RecordStop", "CallUUID": CALL_UUID, "RecordingID": RECORDING_ID})
    assert event is not None and event.recording is not None
    assert event.recording.ended_with_call is True


def test_a_record_stop_naming_no_recording_is_not_a_recording() -> None:
    event = parse_event({"Event": "RecordStop", "CallUUID": CALL_UUID})
    assert event is not None
    assert event.kind == "other" and event.recording is None


# --- 2. the adapter ---------------------------------------------------------------------


async def test_the_source_is_the_apis_url_with_both_headers_scoped_to_vobiz() -> None:
    stub = _Stub(httpx.Response(200, json=_object()))
    source = await _vobiz(stub).recording_source(RECORDING_ID, carrier_call_id=CALL_UUID)
    assert source is not None
    assert stub.requests[0].method == "GET"
    assert stub.requests[0].url.path == f"/api/v1/Account/MA_X/Recording/{RECORDING_ID}/"
    assert source.url == _object()["recording_url"]
    assert dict(source.auth_headers) == {"X-Auth-ID": "MA_X", "X-Auth-Token": "tok"}
    assert source.auth_hosts == RECORDING_AUTH_HOSTS == frozenset({"vobiz.ai"})


async def test_a_recording_of_another_call_is_refused_before_any_fetch() -> None:
    stub = _Stub(httpx.Response(200, json=_object(call_uuid=str(uuid.uuid4()))))
    with pytest.raises(ProblemError) as raised:
        await _vobiz(stub).recording_source(RECORDING_ID, carrier_call_id=CALL_UUID)
    assert raised.value.code == "carrier_recording_call_mismatch"


async def test_a_recording_the_carrier_no_longer_holds_is_none() -> None:
    stub = _Stub(httpx.Response(404, json={"error": "Recording not found"}))
    assert await _vobiz(stub).recording_source(RECORDING_ID, carrier_call_id=CALL_UUID) is None


async def test_a_non_https_file_url_is_refused() -> None:
    stub = _Stub(httpx.Response(200, json=_object(recording_url="http://media.vobiz.ai/x.mp3")))
    with pytest.raises(ProblemError):
        await _vobiz(stub).recording_source(RECORDING_ID, carrier_call_id=CALL_UUID)


async def test_find_recording_lists_by_call_and_an_empty_list_is_none() -> None:
    stub = _Stub(httpx.Response(200, json={"meta": {}, "objects": [_object()]}))
    assert await _vobiz(stub).find_recording(CALL_UUID) == RECORDING_ID
    assert stub.requests[0].url.params["call_uuid"] == CALL_UUID
    empty = _Stub(httpx.Response(200, json={"meta": {}, "objects": []}))
    assert await _vobiz(empty).find_recording(CALL_UUID) is None


async def test_delete_is_the_documented_route_and_404_is_already_gone() -> None:
    deleted = _Stub(httpx.Response(204))
    assert await _vobiz(deleted).delete_recording(RECORDING_ID) is True
    assert deleted.requests[0].method == "DELETE"
    assert deleted.requests[0].url.path == f"/api/v1/Account/MA_X/Recording/{RECORDING_ID}/"
    gone = _Stub(httpx.Response(404, json={"error": "Recording not found"}))
    assert await _vobiz(gone).delete_recording(RECORDING_ID) is False


async def test_plivo_refuses_every_recording_operation_by_name() -> None:
    carrier = PlivoCarrier()
    for call in (
        carrier.recording_source(RECORDING_ID, carrier_call_id=CALL_UUID),
        carrier.find_recording(CALL_UUID),
        carrier.delete_recording(RECORDING_ID),
    ):
        with pytest.raises(ProblemError) as raised:
            await call
        assert raised.value.code == "engine_capability_unverified"


# --- 3. the authenticated fetch ---------------------------------------------------------


def test_the_credential_goes_only_to_https_on_a_listed_domain() -> None:
    hosts = frozenset({"vobiz.ai"})
    assert storage._carries_auth("https://media.vobiz.ai/r.mp3", hosts)
    assert storage._carries_auth("https://vobiz.ai/r.mp3", hosts)
    assert not storage._carries_auth("http://media.vobiz.ai/r.mp3", hosts)
    assert not storage._carries_auth("https://notvobiz.ai/r.mp3", hosts)
    assert not storage._carries_auth("https://vobiz.ai.evil.example/r.mp3", hosts)
    assert not storage._carries_auth("https://bucket.s3.amazonaws.com/r.mp3", hosts)


async def test_a_redirect_off_the_carrier_is_followed_without_the_credential(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("X-Auth-Token")))
        if request.url.host == "media.recordings.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/r.mp3"})
        return httpx.Response(200, content=b"ID3\x04" + b"\x00" * 64)

    real_client = httpx.AsyncClient

    def _factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.httpx, "AsyncClient", _factory)
    tenant, call = uuid.uuid4(), uuid.uuid4()
    key = await copy_recording(
        source_url="https://media.recordings.example/r.mp3",
        tenant_id=tenant,
        call_id=call,
        auth_headers={"X-Auth-ID": "MA_X", "X-Auth-Token": "tok"},
        auth_hosts=frozenset({"recordings.example"}),
    )
    assert seen == [("media.recordings.example", "tok"), ("cdn.example", None)]
    assert key == storage.recording_key(tenant, call), "the key never depends on the container"
    assert key in s3.objects


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/wav"),
        (b"ID3\x04\x00\x00\x00\x00", "audio/mpeg"),
        (b"\xff\xfb\x90\x00", "audio/mpeg"),
        (b"\xff\xe3\x18\xc4", "audio/mpeg"),  # MPEG-2.5 Layer III, `recording.md:34-37`
        (b"\x00\x00\x00\x00", "audio/wav"),
        (b"", "audio/wav"),
    ],
)
def test_the_content_type_is_decided_from_the_bytes(head: bytes, expected: str) -> None:
    assert sniff_audio_content_type(head) == expected


def test_the_event_fields_drop_the_file_url_and_keep_the_recording_ids() -> None:
    """voice-runtime's filter: an epoch in ms is thirteen digits and a uuid can hold a
    seven-digit run, so without the allowlist the copy would lose the fields it needs."""
    import carrier_events

    kept = carrier_events.event_fields(
        {
            "Event": "RecordStop",
            "CallUUID": CALL_UUID,
            "RecordingID": "a1234567-89ab-4cde-8f01-234567890abc",
            "RecordingStartMs": "1716112335000",
            "RecordingEndMs": "1716112377120",
            "RecordingDurationMs": "42120",
            "RecordingEndReason": "HungUp",
            "RecordUrl": f"https://media.vobiz.ai/recordings/{RECORDING_ID}.mp3",
            "RecordFile": f"https://media.vobiz.ai/recordings/{RECORDING_ID}.mp3",
            "From": "919876500011",
            "To": "918000000001",
        }
    )
    assert "RecordUrl" not in kept and "RecordFile" not in kept
    assert "From" not in kept and "To" not in kept
    assert kept["RecordingID"] == "a1234567-89ab-4cde-8f01-234567890abc"
    assert kept["RecordingStartMs"] == "1716112335000"
    assert json.dumps(kept)  # serialisable into the job payload as is


async def test_an_empty_recording_is_refused_and_never_stored(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """A 200 with no body is not a recording. Stored, it would set `recording_url`, and a day
    later the carrier's copy, the only real one, would be deleted on the strength of it."""

    async def _empty(*_args: object, **_kwargs: object) -> bytes:
        return b""

    monkeypatch.setattr(storage, "_fetch_recording", _empty)
    with pytest.raises(storage.StorageUnavailableError):
        await copy_recording(
            source_url="https://media.vobiz.ai/r.mp3", tenant_id=uuid.uuid4(), call_id=uuid.uuid4()
        )
    assert s3.objects == {}
