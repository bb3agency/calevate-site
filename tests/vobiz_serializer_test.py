"""`voice_worker.vobiz_serializer`: Vobiz's media protocol both ways, with no network.

Every envelope asserted here is the one `vobiz-findings/mirror/pages/xml/stream/
stream-events.md` documents. The serializer's two promises beyond the envelopes are also
pinned: the call ends with exactly one in-band `stop` and no HTTP request, and nothing the
carrier sent ever reaches a log line.
"""

from __future__ import annotations

import base64
import inspect
import json
import socket
from dataclasses import dataclass
from typing import Any, cast

import aiohttp
import pytest
from loguru import logger
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from voice_worker import vobiz_serializer
from voice_worker.vobiz_serializer import (
    MULAW_CONTENT_TYPE,
    VOBIZ_SAMPLE_RATE_HZ,
    MediaFormat,
    VobizFrameSerializer,
    VobizMediaFormatError,
)

STREAM_ID = "c4dfd815-a92a-4140-ab85-5ff28c004116"
MULAW_8K = MediaFormat(encoding="audio/x-mulaw", sample_rate=8000)


@dataclass
class _Setup:
    """The one field `setup` reads."""

    audio_in_sample_rate: int = VOBIZ_SAMPLE_RATE_HZ


async def _serializer(stream_id: str = STREAM_ID) -> VobizFrameSerializer:
    serializer = VobizFrameSerializer(stream_id, media_format=MULAW_8K)
    await serializer.setup(cast(FrameProcessorSetup, _Setup()))
    return serializer


async def _ulaw_payload() -> str:
    pcm = b"\x10\x20" * 160
    ulaw = await pcm_to_ulaw(
        pcm, VOBIZ_SAMPLE_RATE_HZ, VOBIZ_SAMPLE_RATE_HZ, create_stream_resampler()
    )
    return base64.b64encode(ulaw).decode("ascii")


@pytest.fixture
def captured_logs() -> Any:
    lines: list[str] = []
    handler = logger.add(
        lambda message: lines.append(str(message) + repr(message.record["extra"])),
        level="TRACE",
    )
    yield lines
    logger.remove(handler)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """An HTTP session or connection opened by the serializer fails the test: the hangup is
    in-band. `aiohttp` is what Pipecat's Plivo serializer hangs up with
    (`serializers/plivo.py:172-192`)."""

    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the Vobiz serializer opened a network connection")

    monkeypatch.setattr(aiohttp, "ClientSession", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def test_the_serializer_module_imports_no_http_client() -> None:
    source = inspect.getsource(vobiz_serializer)
    for client in ("aiohttp", "httpx", "requests", "urllib.request"):
        assert f"import {client}" not in source and f"from {client}" not in source


# --------------------------------------------------------------------------------------
# Inbound
# --------------------------------------------------------------------------------------


async def test_media_becomes_caller_audio_at_the_pipeline_rate() -> None:
    serializer = await _serializer()
    message = {
        "sequenceNumber": 2,
        "streamId": STREAM_ID,
        "event": "media",
        "media": {
            "track": "inbound",
            "timestamp": "1778597597091",
            "chunk": 2,
            "payload": await _ulaw_payload(),
        },
        "extra_headers": "{}",
    }

    frame = await serializer.deserialize(json.dumps(message))

    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == VOBIZ_SAMPLE_RATE_HZ
    assert frame.num_channels == 1
    assert len(frame.audio) == 320  # 160 μ-law samples, 16-bit PCM


async def test_media_from_a_track_other_than_the_callers_is_not_caller_audio() -> None:
    serializer = await _serializer()
    message = {"event": "media", "media": {"track": "outbound", "payload": await _ulaw_payload()}}

    assert await serializer.deserialize(json.dumps(message)) is None


async def test_a_start_reaching_the_transport_is_validated_and_produces_no_frame() -> None:
    serializer = await _serializer()
    start = {
        "sequenceNumber": 0,
        "event": "start",
        "start": {
            "callId": "5401fd2e-6344-40df-a22c-c8ffea7a92e7",
            "streamId": "another-stream",
            "accountId": "500025",
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
        },
        "extra_headers": "{}",
    }

    assert await serializer.deserialize(json.dumps(start)) is None
    # One socket carries one stream: the id we already hold is kept.
    assert serializer.stream_id == STREAM_ID


async def test_an_in_band_start_supplies_the_stream_id_when_none_was_known() -> None:
    serializer = await _serializer(stream_id="")
    start = {
        "event": "start",
        "start": {
            "streamId": STREAM_ID,
            "mediaFormat": {"encoding": "audio/x-mulaw;rate=8000", "sampleRate": "8000"},
        },
    }

    await serializer.deserialize(json.dumps(start))

    assert serializer.stream_id == STREAM_ID


async def test_an_in_band_start_in_another_format_is_refused() -> None:
    serializer = await _serializer()
    start = {
        "event": "start",
        "start": {
            "streamId": STREAM_ID,
            "mediaFormat": {"encoding": "audio/x-l16", "sampleRate": 16000},
        },
    }

    with pytest.raises(VobizMediaFormatError, match="audio/x-l16 at 16000 Hz"):
        await serializer.deserialize(json.dumps(start))


@pytest.mark.parametrize(
    "message",
    [
        {"event": "playedStream", "name": "response-3"},
        {"event": "clearedAudio", "streamId": STREAM_ID},
        {"event": "something-new", "streamId": STREAM_ID},
        {"streamId": STREAM_ID},
    ],
    ids=["playedStream", "clearedAudio", "unknown-event", "no-event"],
)
async def test_acknowledgements_and_unknown_events_are_ignored(message: dict[str, Any]) -> None:
    serializer = await _serializer()

    assert await serializer.deserialize(json.dumps(message)) is None
    assert serializer.dropped_messages == 0


async def test_dtmf_is_dropped_and_only_its_name_is_logged(captured_logs: list[str]) -> None:
    """Its body is undocumented, so nothing is parsed out of it and nothing of it is logged."""
    serializer = await _serializer()
    secret = "4111111111111111"

    frame = await serializer.deserialize(json.dumps({"event": "dtmf", "dtmf": {"digit": secret}}))

    assert frame is None
    blob = "\n".join(captured_logs)
    assert "dtmf" in blob
    assert secret not in blob


@pytest.mark.parametrize(
    "raw",
    ["not json at all {", b"\xff\xfe\x00", "[1, 2, 3]", '"a string"'],
    ids=["garbage", "undecodable-bytes", "array", "scalar"],
)
async def test_a_message_that_is_not_a_json_object_is_dropped_and_counted(
    raw: str | bytes, captured_logs: list[str]
) -> None:
    serializer = await _serializer()

    assert await serializer.deserialize(raw) is None

    assert serializer.dropped_messages == 1
    blob = "\n".join(captured_logs)
    assert "vobiz message dropped" in blob
    text = raw if isinstance(raw, str) else raw.decode("latin-1")
    assert text not in blob


async def test_an_undecodable_payload_is_dropped_without_logging_it(
    captured_logs: list[str],
) -> None:
    serializer = await _serializer()
    payload = "!!!not-base64-caller-audio!!!"

    frame = await serializer.deserialize(
        json.dumps({"event": "media", "media": {"track": "inbound", "payload": payload}})
    )

    assert frame is None
    assert serializer.dropped_messages == 1
    assert payload not in "\n".join(captured_logs)


async def test_a_flood_of_bad_frames_logs_at_powers_of_two_only(captured_logs: list[str]) -> None:
    serializer = await _serializer()

    for _ in range(100):
        await serializer.deserialize("{")

    assert serializer.dropped_messages == 100
    dropped_lines = [line for line in captured_logs if "vobiz message dropped" in line]
    assert len(dropped_lines) == 7  # 1, 2, 4, 8, 16, 32, 64


async def test_no_media_payload_is_ever_logged(captured_logs: list[str]) -> None:
    serializer = await _serializer()
    payload = await _ulaw_payload()

    await serializer.deserialize(
        json.dumps({"event": "media", "media": {"track": "inbound", "payload": payload}})
    )

    assert payload not in "\n".join(captured_logs)


# --------------------------------------------------------------------------------------
# Outbound
# --------------------------------------------------------------------------------------


async def test_agent_audio_leaves_as_play_audio_in_8k_mulaw() -> None:
    serializer = await _serializer()

    out = await serializer.serialize(
        OutputAudioRawFrame(audio=b"\x00\x01" * 160, sample_rate=8000, num_channels=1)
    )

    assert isinstance(out, str)
    envelope = json.loads(out)
    assert envelope["event"] == "playAudio"
    assert envelope["streamId"] == STREAM_ID
    assert envelope["media"]["contentType"] == MULAW_CONTENT_TYPE
    assert envelope["media"]["sampleRate"] == VOBIZ_SAMPLE_RATE_HZ
    assert base64.b64decode(envelope["media"]["payload"])


async def test_a_barge_in_flushes_the_carriers_queue() -> None:
    serializer = await _serializer()

    out = await serializer.serialize(InterruptionFrame())

    assert json.loads(cast(str, out)) == {"event": "clearAudio", "streamId": STREAM_ID}


@pytest.mark.parametrize("ending", [EndFrame, CancelFrame])
async def test_the_call_ends_with_exactly_one_stop_and_no_network(
    ending: type[EndFrame] | type[CancelFrame], no_network: None
) -> None:
    serializer = await _serializer()

    first = await serializer.serialize(ending())
    again_end = await serializer.serialize(EndFrame())
    again_cancel = await serializer.serialize(CancelFrame())
    audio_after = await serializer.serialize(
        OutputAudioRawFrame(audio=b"\x00\x01" * 160, sample_rate=8000, num_channels=1)
    )

    assert json.loads(cast(str, first)) == {"event": "stop", "streamId": STREAM_ID}
    assert again_end is None and again_cancel is None
    assert audio_after is None, "nothing may be sent on a stream we have stopped"


async def test_a_stream_with_no_id_cannot_be_stopped_in_band_and_says_so(
    captured_logs: list[str],
) -> None:
    serializer = await _serializer(stream_id="")

    assert await serializer.serialize(EndFrame()) is None
    assert "no streamId" in "\n".join(captured_logs)


async def test_frames_the_carrier_has_no_command_for_are_not_sent() -> None:
    serializer = await _serializer()

    assert await serializer.serialize(TextFrame(text="hello")) is None
    assert (
        await serializer.serialize(OutputTransportMessageFrame(message={"event": "custom"})) is None
    )


# --------------------------------------------------------------------------------------
# Construction and format
# --------------------------------------------------------------------------------------


def test_the_serializer_calls_the_base_initialiser() -> None:
    """`resampler_clear_after_secs` and `ignore_rtvi_messages` live on the base params
    (`base_serializer.py:46-54`); a serializer that skipped `super().__init__` would carry
    neither."""
    params = VobizFrameSerializer.InputParams(resampler_clear_after_secs=None)
    serializer = VobizFrameSerializer(STREAM_ID, params=params)

    assert serializer._params is params
    assert serializer._params.ignore_rtvi_messages is True
    assert serializer.name  # set by `BaseObject.__init__`


@pytest.mark.parametrize(
    ("encoding", "rate"),
    [("audio/x-mulaw", 8000), ("audio/x-mulaw;rate=8000", 8000), ("AUDIO/X-MULAW", 8000)],
)
def test_8k_mulaw_is_accepted_in_every_spelling_the_stream_attribute_allows(
    encoding: str, rate: int
) -> None:
    VobizFrameSerializer(STREAM_ID, media_format=MediaFormat(encoding=encoding, sample_rate=rate))


@pytest.mark.parametrize(
    ("encoding", "rate", "named"),
    [
        ("audio/x-l16", 8000, True),
        ("audio/x-l16", 16000, True),
        ("audio/x-mulaw", 16000, True),
        ("audio/x-mulaw", None, False),
        ("audio/evil-codec-name", 8000, False),
    ],
)
def test_any_other_format_is_refused_and_only_a_documented_one_is_named(
    encoding: str, rate: int | None, named: bool
) -> None:
    with pytest.raises(VobizMediaFormatError) as refused:
        VobizFrameSerializer(
            STREAM_ID, media_format=MediaFormat(encoding=encoding, sample_rate=rate)
        )
    message = str(refused.value)
    assert (f"reports {encoding}" in message) is named
    if not named:
        assert "does not list" in message


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ({"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}}, MULAW_8K),
        ({"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": "8000"}}, MULAW_8K),
        (
            {"mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": "fast"}},
            MediaFormat(encoding="audio/x-mulaw", sample_rate=None),
        ),
        ({"mediaFormat": {"sampleRate": 8000}}, None),
        ({"mediaFormat": "audio/x-mulaw"}, None),
        ({}, None),
    ],
)
def test_the_media_format_is_read_defensively(
    start: dict[str, Any], expected: MediaFormat | None
) -> None:
    assert MediaFormat.from_start(start) == expected
