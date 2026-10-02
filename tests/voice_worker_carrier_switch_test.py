"""Which carrier a socket is, which serializer it gets, and which call it is.

The carrier is chosen by our control plane's `carrier=` claim on the stream URL, or by the
worker's `CARRIER` setting when there is none; Pipecat's detection only checks it, because
a Vobiz `start` is the shape Pipecat names "plivo" (`calevate_shared.carrier.WIRE_FAMILY`).
The call claim decides direction and call id, and nothing unsigned does.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast
from urllib.parse import quote, urlencode

import bot
import pytest
from calevate_shared.engine import owned_runtime_agent_ref
from calevate_shared.worker_api import (
    CALL_CLAIM_EXPIRES_PARAM,
    CALL_CLAIM_MAC_PARAM,
    CALL_DIRECTION_PARAM,
    CALL_ID_PARAM,
    CALLER_SEAL_PARAM,
    UnverifiedCallClaim,
    call_claim_mac,
    seal_caller_claim,
)
from loguru import logger
from pipecat.serializers.plivo import PlivoFrameSerializer
from voice_worker import carrier
from voice_worker.vobiz_serializer import VobizFrameSerializer, VobizMediaFormatError

SECRET = "k" * 32
KEY = SECRET.encode()
CALL_UUID = "5401fd2e-6344-40df-a22c-c8ffea7a92e7"
STREAM_ID = "c4dfd815-a92a-4140-ab85-5ff28c004116"
PLIVO_CREDENTIALS = carrier.PlivoCredentials(auth_id="MA-test", auth_token="token-test")


def _vobiz_start(media_format: dict[str, Any] | bool | None = None) -> str:
    """The documented `start` (`stream-events.md:81-97`), in our `<Stream>`'s format."""
    start: dict[str, Any] = {
        "callId": CALL_UUID,
        "streamId": STREAM_ID,
        "accountId": "500025",
        "tracks": ["inbound"],
    }
    if media_format is not False:
        start["mediaFormat"] = media_format or {"encoding": "audio/x-mulaw", "sampleRate": 8000}
    # `False` leaves the format out, which the vendor's documentation never does.
    return json.dumps(
        {"sequenceNumber": 0, "event": "start", "start": start, "extra_headers": "{}"}
    )


PLIVO_START = json.dumps({"event": "start", "start": {"streamId": "s-1", "callId": "c-1"}})
TWILIO_START = json.dumps(
    {"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1", "customParameters": {}}}
)
VOBIZ_MEDIA = json.dumps({"event": "media", "media": {"track": "inbound", "payload": "//8="}})


class _Socket:
    """A carrier socket: a URL, and the frames the carrier sends first."""

    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, *frames: str, url: str = "") -> None:
        self._frames = frames
        self.url = _UrlAt(url)
        self.reads = 0

    def iter_text(self) -> Any:
        async def _messages() -> Any:
            for frame in self._frames:
                self.reads += 1
                yield frame

        return _messages()


@dataclass
class _UrlAt:
    raw: str

    @property
    def path(self) -> str:
        without_query = self.raw.split("?", 1)[0]
        return "/" + without_query.split("://", 1)[-1].split("/", 1)[-1]

    def __str__(self) -> str:
        return self.raw


def _ref() -> str:
    return owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))


def _stream_url(ref: str, **query: str) -> str:
    base = f"wss://worker.example/ws/{quote(ref, safe='')}"
    return f"{base}?{urlencode(query)}" if query else base


def _call_claim(
    ref: str,
    *,
    call_id: str,
    direction: str = "outbound",
    expires_at: int | None = None,
    key: bytes = KEY,
) -> dict[str, str]:
    expiry = expires_at if expires_at is not None else int(time.time()) + 60
    return {
        CALL_ID_PARAM: call_id,
        CALL_DIRECTION_PARAM: direction,
        CALL_CLAIM_EXPIRES_PARAM: str(expiry),
        CALL_CLAIM_MAC_PARAM: call_claim_mac(
            key,
            ref=ref,
            call_id=call_id,
            direction=direction,
            expires_at=expiry,  # type: ignore[arg-type]
        ),
    }


# --------------------------------------------------------------------------------------
# 1. The switch: claim first, configured default second, detection always checks.
# --------------------------------------------------------------------------------------


async def test_a_vobiz_claim_builds_the_vobiz_serializer_with_no_credential() -> None:
    claim = carrier.claim_from_stream_url("?carrier=vobiz")

    leg = await carrier.open_carrier_leg(
        _Socket(_vobiz_start(), VOBIZ_MEDIA), claim=claim, default_carrier="plivo"
    )

    assert leg.handshake.carrier == "vobiz"
    assert leg.handshake.stream_id == STREAM_ID
    assert leg.handshake.carrier_call_id == CALL_UUID
    serializer = leg.transport._params.serializer
    assert isinstance(serializer, VobizFrameSerializer)
    assert serializer.stream_id == STREAM_ID
    assert leg.transport._params.audio_in_sample_rate == carrier.TELEPHONY_SAMPLE_RATE_HZ
    assert leg.transport._params.add_wav_header is False


async def test_a_plivo_claim_builds_the_plivo_serializer_with_its_credentials() -> None:
    claim = carrier.claim_from_stream_url("?carrier=plivo")

    leg = await carrier.open_carrier_leg(
        _Socket(PLIVO_START, "{}"),
        claim=claim,
        default_carrier="vobiz",
        plivo_credentials=PLIVO_CREDENTIALS,
    )

    assert leg.handshake.carrier == "plivo"
    assert isinstance(leg.transport._params.serializer, PlivoFrameSerializer)


async def test_a_plivo_call_on_a_worker_with_no_plivo_credentials_is_refused() -> None:
    claim = carrier.claim_from_stream_url("?carrier=plivo")

    with pytest.raises(carrier.CarrierCredentialsMissingError):
        await carrier.open_carrier_leg(
            _Socket(PLIVO_START, "{}"), claim=claim, default_carrier="vobiz"
        )


@pytest.mark.parametrize(
    ("default", "expected"), [("vobiz", VobizFrameSerializer), ("plivo", PlivoFrameSerializer)]
)
async def test_with_no_claim_the_workers_carrier_setting_decides(
    default: str, expected: type
) -> None:
    """Both carriers' starts detect as the same wire family, so the setting is what picks."""
    leg = await carrier.open_carrier_leg(
        _Socket(_vobiz_start(), VOBIZ_MEDIA),
        claim=carrier.claim_from_stream_url(""),
        default_carrier=default,
        plivo_credentials=PLIVO_CREDENTIALS,
    )

    assert leg.handshake.carrier == default
    assert isinstance(leg.transport._params.serializer, expected)


async def test_a_claim_the_socket_does_not_speak_is_refused_as_a_mismatch() -> None:
    claim = carrier.claim_from_stream_url("?carrier=vobiz")

    with pytest.raises(carrier.CarrierClaimMismatchError) as refused:
        await carrier.open_carrier_leg(
            _Socket(TWILIO_START, "{}"), claim=claim, default_carrier="vobiz"
        )

    assert "vobiz" in str(refused.value) and "twilio" in str(refused.value)


async def test_a_carrier_with_no_serializer_is_refused_even_when_detection_agrees() -> None:
    """The claim is unsigned, so a socket claiming and speaking Twilio is still not served."""
    claim = carrier.claim_from_stream_url("?carrier=twilio")

    with pytest.raises(carrier.UnroutableCallError, match="no serializer"):
        await carrier.open_carrier_leg(
            _Socket(TWILIO_START, "{}"), claim=claim, default_carrier="vobiz"
        )


async def test_a_vobiz_stream_in_another_format_is_refused_before_any_audio() -> None:
    claim = carrier.claim_from_stream_url("?carrier=vobiz")
    l16 = _vobiz_start({"encoding": "audio/x-l16", "sampleRate": 16000})

    with pytest.raises(VobizMediaFormatError):
        await carrier.open_carrier_leg(
            _Socket(l16, VOBIZ_MEDIA), claim=claim, default_carrier="vobiz"
        )


async def test_a_vobiz_start_with_no_media_format_is_refused() -> None:
    claim = carrier.claim_from_stream_url("?carrier=vobiz")
    bare = _vobiz_start(False)

    with pytest.raises(carrier.UnroutableCallError, match="mediaFormat"):
        await carrier.open_carrier_leg(
            _Socket(bare, VOBIZ_MEDIA), claim=claim, default_carrier="vobiz"
        )


def test_the_wire_family_is_the_shared_contracts() -> None:
    assert carrier.wire_family_of("vobiz") == "plivo"
    assert carrier.wire_family_of("plivo") == "plivo"
    assert carrier.wire_family_of("twilio") == "twilio"


# --------------------------------------------------------------------------------------
# 2. Who is calling, on Vobiz: only the signed claim can say.
# --------------------------------------------------------------------------------------


async def test_on_vobiz_a_sealed_caller_claim_is_the_verdict() -> None:
    ref = _ref()
    number = "+919876500001"
    url = _stream_url(
        ref,
        carrier="vobiz",
        caller_state="known",
        **{CALLER_SEAL_PARAM: seal_caller_claim(SECRET, ref=ref, e164=number)},
    )
    assert number.lstrip("+") not in url
    claim = carrier.claim_from_stream_url(url, ref=ref, claim_secret=SECRET)

    leg = await carrier.open_carrier_leg(
        _Socket(_vobiz_start(), VOBIZ_MEDIA), claim=claim, default_carrier="vobiz"
    )

    assert leg.handshake.caller.is_known
    assert leg.handshake.caller.e164 == number


async def test_on_vobiz_with_no_claim_the_caller_is_unparsed_citing_the_vendors_page() -> None:
    leg = await carrier.open_carrier_leg(
        _Socket(_vobiz_start(), VOBIZ_MEDIA),
        claim=carrier.claim_from_stream_url(""),
        default_carrier="vobiz",
    )

    assert leg.handshake.caller.state == "unparsed_by_client"
    assert "stream-events.md" in leg.handshake.caller.ground


# --------------------------------------------------------------------------------------
# 3. The call claim: direction and our call id.
# --------------------------------------------------------------------------------------


@dataclass
class _Args:
    websocket: Any


async def test_a_valid_call_claim_gives_the_claimed_id_and_direction() -> None:
    ref = _ref()
    call_id = str(uuid.uuid4())
    url = _stream_url(ref, carrier="vobiz", **_call_claim(ref, call_id=call_id))

    identity = await bot.resolve_call_identity(cast(Any, _Args(_Socket(url=url))), claim_key=KEY)

    assert (identity.call_id, identity.direction) == (call_id, "outbound")
    assert identity.unverified_claim is None


@pytest.mark.parametrize(
    "tamper",
    ["expired", "far_future", "other_agent", "other_key", "changed_id", "bad_direction", "no_key"],
)
async def test_an_unverifiable_call_claim_falls_back_to_a_fresh_inbound_call(
    tamper: str,
) -> None:
    ref = _ref()
    call_id = str(uuid.uuid4())
    now = int(time.time())
    claim = {
        "expired": lambda: _call_claim(ref, call_id=call_id, expires_at=now - 1),
        "far_future": lambda: _call_claim(ref, call_id=call_id, expires_at=now + 3600),
        "other_agent": lambda: _call_claim(_ref(), call_id=call_id),
        "other_key": lambda: _call_claim(ref, call_id=call_id, key=b"z" * 32),
        "changed_id": lambda: {**_call_claim(ref, call_id=call_id), CALL_ID_PARAM: "other"},
        "bad_direction": lambda: _call_claim(ref, call_id=call_id, direction="sideways"),
        "no_key": lambda: _call_claim(ref, call_id=call_id),
    }[tamper]()
    url = _stream_url(ref, **claim)

    identity = await bot.resolve_call_identity(
        cast(Any, _Args(_Socket(url=url))), claim_key=None if tamper == "no_key" else KEY
    )

    assert identity.direction == "inbound"
    assert identity.call_id != call_id
    assert uuid.UUID(identity.call_id).version == 7
    # Reported on the settlement, so the server can tell a forgery from a dialled call this
    # worker could not verify (`carrier_call_claim_mismatch`).
    expected = None if tamper == "changed_id" else uuid.UUID(call_id)
    assert identity.unverified_claim == UnverifiedCallClaim(claimed_call_id=expected)


async def test_no_call_claim_is_an_inbound_call_and_logs_nothing() -> None:
    ref = _ref()
    lines: list[str] = []
    handler = logger.add(lambda m: lines.append(str(m)), level="WARNING")
    try:
        identity = await bot.resolve_call_identity(
            cast(Any, _Args(_Socket(url=_stream_url(ref, carrier="vobiz")))), claim_key=KEY
        )
    finally:
        logger.remove(handler)

    assert identity.direction == "inbound"
    assert identity.unverified_claim is None
    assert not [line for line in lines if "call claim" in line]


async def test_a_rejected_call_claim_is_logged_without_any_query_value() -> None:
    ref = _ref()
    call_id = "attacker-chosen-id-123"
    lines: list[str] = []
    handler = logger.add(lambda m: lines.append(str(m) + repr(m.record["extra"])), level="DEBUG")
    try:
        await bot.resolve_call_identity(
            cast(Any, _Args(_Socket(url=_stream_url(ref, **_call_claim(_ref(), call_id=call_id))))),
            claim_key=KEY,
        )
    finally:
        logger.remove(handler)

    blob = "\n".join(lines)
    assert "did not verify" in blob
    assert call_id not in blob


# --------------------------------------------------------------------------------------
# 4. The shipped entrypoint wires all of it into `run_call`.
# --------------------------------------------------------------------------------------


@dataclass
class _Config:
    carrier: str = "vobiz"
    plivo_credentials: carrier.PlivoCredentials | None = None
    caller_claim_key: bytes | None = KEY
    carrier_claim_secret: str | None = SECRET

    def credentials_for(self, _provider: str | None) -> Any:  # pragma: no cover - not called
        raise AssertionError("credentials are resolved inside run_call")


@dataclass
class _Calls:
    seen: dict[str, Any] = field(default_factory=dict)

    async def run_call(self, **kwargs: Any) -> None:
        self.seen.update(kwargs)


@dataclass
class _Runtime:
    config: _Config
    calls: _Calls = field(default_factory=_Calls)


@dataclass
class _Registry:
    reserved: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)

    def reserve(self, call_id: str) -> None:
        self.reserved.append(call_id)

    def release(self, call_id: str) -> None:
        self.released.append(call_id)

    def attach(self, *_args: Any) -> None:  # pragma: no cover - run_call is faked
        return None


async def test_the_entrypoint_runs_an_outbound_vobiz_call_on_the_claimed_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref()
    call_id = str(uuid.uuid4())
    url = _stream_url(ref, carrier="vobiz", **_call_claim(ref, call_id=call_id))
    runtime, registry = _Runtime(config=_Config()), _Registry()

    async def _container() -> tuple[_Runtime, _Registry]:
        return runtime, registry

    monkeypatch.setattr(bot, "container", _container)

    await bot.bot(cast(Any, _Args(_Socket(_vobiz_start(), VOBIZ_MEDIA, url=url))))

    seen = runtime.calls.seen
    assert seen["call_id"] == call_id and seen["direction"] == "outbound"
    assert seen["engine_agent_ref"] == ref
    assert seen["carrier_call_id"] == CALL_UUID
    assert isinstance(seen["transport"]._params.serializer, VobizFrameSerializer)
    assert seen["caller"].state == "unparsed_by_client"
    assert seen["call_claim_unverified"] is None
    assert registry.reserved == registry.released == [call_id]


async def test_the_entrypoint_runs_an_inbound_vobiz_call_with_its_sealed_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inbound live path: the answer leg's sealed `From` opens in the worker and reaches
    `run_call` as a known caller, under an id the worker minted."""
    ref = _ref()
    number = "+919876500001"
    url = _stream_url(
        ref,
        carrier="vobiz",
        caller_state="known",
        **{CALLER_SEAL_PARAM: seal_caller_claim(SECRET, ref=ref, e164=number)},
    )
    runtime, registry = _Runtime(config=_Config()), _Registry()

    async def _container() -> tuple[_Runtime, _Registry]:
        return runtime, registry

    monkeypatch.setattr(bot, "container", _container)

    await bot.bot(cast(Any, _Args(_Socket(_vobiz_start(), VOBIZ_MEDIA, url=url))))

    seen = runtime.calls.seen
    assert seen["direction"] == "inbound"
    assert uuid.UUID(seen["call_id"]).version == 7
    assert seen["caller"].is_known and seen["caller"].e164 == number
    assert seen["carrier_call_id"] == CALL_UUID
    assert seen["call_claim_unverified"] is None
    assert isinstance(seen["transport"]._params.serializer, VobizFrameSerializer)


async def test_the_entrypoint_reports_a_call_claim_that_did_not_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dialled call whose secret differs between voice-runtime and this worker runs as
    inbound; the claim it carried rides the settlement so the api can page."""
    ref = _ref()
    call_id = str(uuid.uuid4())
    url = _stream_url(ref, carrier="vobiz", **_call_claim(ref, call_id=call_id, key=b"z" * 32))
    runtime, registry = _Runtime(config=_Config()), _Registry()

    async def _container() -> tuple[_Runtime, _Registry]:
        return runtime, registry

    monkeypatch.setattr(bot, "container", _container)

    await bot.bot(cast(Any, _Args(_Socket(_vobiz_start(), VOBIZ_MEDIA, url=url))))

    seen = runtime.calls.seen
    assert seen["direction"] == "inbound" and seen["call_id"] != call_id
    assert seen["call_claim_unverified"] == UnverifiedCallClaim(claimed_call_id=uuid.UUID(call_id))


async def test_the_entrypoint_releases_the_slot_when_the_carrier_leg_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref()
    runtime, registry = _Runtime(config=_Config(carrier="plivo")), _Registry()

    async def _container() -> tuple[_Runtime, _Registry]:
        return runtime, registry

    monkeypatch.setattr(bot, "container", _container)

    with pytest.raises(carrier.CarrierCredentialsMissingError):
        await bot.bot(cast(Any, _Args(_Socket(PLIVO_START, "{}", url=_stream_url(ref)))))

    assert runtime.calls.seen == {}
    assert registry.reserved == registry.released
