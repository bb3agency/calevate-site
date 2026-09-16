"""D-618: the Gnani TTS leg, exercised against the pinned `pipecat-ai==1.10.0`.

**WHAT THIS FILE IS FOR, AND IT IS NOT COVERAGE.** `pipecat-gnani` 0.5.12 declares
`pipecat-ai>=0.0.50` and its documentation says it was tested against Pipecat v1.5.0. We
pin 1.10.0. A floor five minor-versions wide is not a compatibility claim, so the only way
to know what works is to run it — and three things did not. Every test here is one of:

* **a PROOF** that a documented behaviour really happens on our pin, or
* **a TRIPWIRE** on a gap `voice_worker/gnani_tts.py` fills, written so it FAILS when the
  plugin fixes the gap upstream. That failure is the message "delete the workaround", which
  is the only mechanism that stops a shim outliving its reason.

**NO NETWORK, NO KEY, NO ACCOUNT.** `api.vachana.ai` is egress-blocked from this container
(HTTP 000, measured 15 Sep 2026) and nobody here holds a Gnani credential. Every socket
below is a fake driven by the message shapes the vendor documents
(`docs.gnani.ai/api/TTS/tts-websocket`, sitemap `lastmod` 2026-08-05, founder-relayed
15 Sep 2026): a JSON `start`, JSON `audio` frames carrying BASE64, and a JSON `complete`.
So this suite proves what we send and how we react — never that Gnani answers.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
import json
from typing import Any

import pytest
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.services.tts_service import InterruptibleTTSService
from pipecat.utils.types import NotGiven
from voice_worker import gnani_tts
from voice_worker.gnani_tts import (
    GNANI_TTS_CONTAINER,
    GNANI_TTS_ENCODING,
    GNANI_TTS_MODEL,
    GNANI_TTS_SAMPLE_WIDTH,
    TELEPHONY_SAMPLE_RATE_HZ,
    CalevateGnaniTTSService,
    build_gnani_tts,
)

# RESOLVED THROUGH `importlib`, AND THAT IS NOT STYLE. A plain `from pipecat_gnani import
# tts` raises ImportError on our pin until `voice_worker.gnani_tts` has installed the
# sentinel alias (GAP 1) — and isort sorts `pipecat_gnani` ABOVE `voice_worker`, so a plain
# import would be moved back above the thing it depends on by the next `ruff format .`.
# It was, once, and this whole file stopped collecting. A call cannot be reordered.
plugin_tts = importlib.import_module("pipecat_gnani.tts")


class FakeWebsocket:
    """The vendor's documented reply sequence, with no network.

    `send` enqueues this utterance's scripted replies, which is what makes the receive
    loop run only once there is something to synthesise — the real socket's shape.
    """

    def __init__(self, script: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._script = script or []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, message: str) -> None:
        self.sent.append(message)
        for reply in self._script:
            await self._queue.put(reply)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> FakeWebsocket:
        return self

    async def __anext__(self) -> str:
        return await self._queue.get()


def audio_reply(payload: bytes, *, index: int) -> str:
    return json.dumps(
        {
            "type": "audio",
            "data": {
                "chunk_index": index,
                "audio": base64.b64encode(payload).decode(),
                "is_final": False,
            },
        }
    )


COMPLETE_REPLY = json.dumps(
    {"type": "complete", "data": {"chunk_index": 9, "audio": "", "is_final": True}}
)
START_REPLY = json.dumps(
    {"type": "start", "message": "Streaming started", "request_id": "req_abc123"}
)


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A service plus the fake socket it opened, and the connect kwargs it opened it with."""

    def _build(script: list[str] | None = None) -> tuple[CalevateGnaniTTSService, Any, dict]:
        sockets: list[FakeWebsocket] = []
        opened: dict[str, Any] = {}

        async def fake_connect(url: str, **kwargs: Any) -> FakeWebsocket:
            opened["url"] = url
            opened["kwargs"] = kwargs
            socket = FakeWebsocket(script)
            sockets.append(socket)
            return socket

        monkeypatch.setattr(plugin_tts, "websocket_connect", fake_connect)
        service = build_gnani_tts(api_key="test-key", voice="Suhana", language="te-IN")
        return service, sockets, opened

    return _build


# --------------------------------------------------------------------------------------
# GAP 1 — the package does not import on 1.10.0 without our alias.
# --------------------------------------------------------------------------------------


def test_the_plugin_still_reaches_for_a_private_name_pipecat_no_longer_has() -> None:
    """TRIPWIRE. Delete the shim in `gnani_tts.py` when this fails.

    Two halves, because either one closing removes the need: the plugin still IMPORTS
    `_NotGiven`, and 1.10.0 still exports only the public `NotGiven`.
    """
    source = inspect.getsource(plugin_tts)
    assert "from pipecat.services.settings import" in source
    assert "_NotGiven" in source, (
        "pipecat-gnani no longer imports the private sentinel name — delete GAP 1's alias "
        "from voice_worker/gnani_tts.py and this test with it."
    )
    # The alias our module installed IS the public type, not a stand-in: the plugin's
    # settings dataclasses annotate their fields with it, so a different object here would
    # be a second sentinel type and `is_given()` would stop recognising it.
    assert gnani_tts._pipecat_settings._NotGiven is NotGiven  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------
# GAP 2 — interruption. The one that matters on a phone call.
# --------------------------------------------------------------------------------------


def test_the_plugin_does_not_wire_the_interruption_path_itself() -> None:
    """TRIPWIRE. Delete our `_connect`/`_disconnect` overrides when this fails.

    `InterruptibleTTSService._handle_interruption` calls `_connect`/`_disconnect`; the
    plugin implements only `_connect_websocket`/`_disconnect_websocket`, so on the vendor's
    class the reconnect resolves to the base class's flag-only implementations and closes
    nothing.
    """
    assert issubclass(plugin_tts.GnaniTTSService, InterruptibleTTSService)
    assert "_connect" not in plugin_tts.GnaniTTSService.__dict__, (
        "pipecat-gnani now overrides _connect — check whether it closes the socket, and "
        "delete our override if it does."
    )
    assert "_disconnect" not in plugin_tts.GnaniTTSService.__dict__
    # Ours does both, which is the whole of the fix.
    assert "_connect" in CalevateGnaniTTSService.__dict__
    assert "_disconnect" in CalevateGnaniTTSService.__dict__


async def test_barge_in_closes_the_socket_and_the_next_turn_opens_a_new_one(
    connected: Any,
) -> None:
    """PROOF that our override does what Gnani's protocol leaves no other way to do.

    Their API documents no cancel, flush or stop message: closing the connection is the
    only interruption there is. So `_handle_interruption`'s disconnect/connect pair has to
    reach the socket, and this is the assertion that it does.
    """
    service, sockets, _ = connected([START_REPLY, COMPLETE_REPLY])
    await service._connect_websocket()
    assert len(sockets) == 1

    await service._disconnect()
    assert sockets[0].closed is True
    assert service._ws is None

    await service._connect()
    assert len(sockets) == 2, "a barge-in must leave the service able to speak again"
    assert service._ws is sockets[1]


# --------------------------------------------------------------------------------------
# GAP 3 — a socket the vendor's loop gave up on.
# --------------------------------------------------------------------------------------


def test_the_plugin_still_runs_its_receive_loop_outside_the_reconnecting_handler() -> None:
    """TRIPWIRE. Delete our `_receive_messages` override when this fails.

    `WebsocketService._receive_task_handler` is the half of the base class that reconnects
    with backoff. The plugin never calls it — it starts `_receive_messages` as a bare
    `asyncio.create_task` — so a dropped socket is permanent for the call.
    """
    source = inspect.getsource(plugin_tts.GnaniTTSService._connect_websocket)
    assert "asyncio.create_task" in source
    assert "_receive_task_handler" not in source, (
        "pipecat-gnani now drives its receive loop through the base class's reconnecting "
        "handler — delete GAP 3's override."
    )


async def test_a_receive_loop_that_ends_releases_the_socket(connected: Any) -> None:
    """PROOF of gap 3. Without the override the next utterance writes into a dead socket.

    The plugin's loop swallows the failure and RETURNS, so "ended" is what a dropped
    connection looks like from here.
    """
    service, sockets, _ = connected()
    await service._connect_websocket()

    # End the loop the way a closed connection does: the iterator stops.
    await sockets[0]._queue.put("")  # unparseable → the plugin's except arm → return
    await asyncio.sleep(0.05)

    assert service._ws is None, "a finished receive loop must not leave a dead socket in place"


async def test_cancelling_the_receive_loop_leaves_the_socket_for_the_disconnect(
    connected: Any,
) -> None:
    """PROOF that gap 3's fix does not break gap 2's.

    Teardown cancels the receive task and THEN closes the socket. Clearing the reference on
    the cancellation path would leak the connection we close precisely in order to
    interrupt — the failure would be invisible and would cost money on a metered vendor.
    """
    service, sockets, _ = connected()
    await service._connect_websocket()

    await service._disconnect_websocket()

    assert sockets[0].closed is True


# --------------------------------------------------------------------------------------
# The wire: what we send, and what we do with what comes back.
# --------------------------------------------------------------------------------------


async def test_the_upgrade_carries_the_key_in_the_documented_header(connected: Any) -> None:
    service, _, opened = connected()
    await service._connect_websocket()

    assert opened["url"] == "wss://api.vachana.ai/api/v1/tts"
    headers = opened["kwargs"].get("additional_headers") or opened["kwargs"].get("extra_headers")
    assert headers["X-API-Key-ID"] == "test-key"
    # The vendor's own JS example sends this too, and headers cannot be changed
    # mid-session — which is why a settings change costs a reconnect on this vendor.
    assert headers["Content-Type"] == "application/json"


async def test_the_synthesis_request_is_the_documented_shape(connected: Any) -> None:
    """Every field we send, including the three the plugin would have defaulted wrongly."""
    service, sockets, _ = connected([START_REPLY, COMPLETE_REPLY])
    await service._connect_websocket()

    async for _ in service.run_tts("హలో", "ctx-1"):
        pass

    payload = json.loads(sockets[0].sent[0])
    assert payload == {
        "text": "హలో",
        "voice": "Suhana",
        # NOT the plugin's `timbre-v2.0` default, which has four voices and no Telugu.
        "model": "timbre-v2.5",
        # `timbre-v2.5` is the only model that accepts it, and the voices are tuned per
        # locale — so it is sent explicitly rather than left to the vendor.
        "language": "te-IN",
        "audio_config": {
            "sample_rate": TELEPHONY_SAMPLE_RATE_HZ,
            "encoding": GNANI_TTS_ENCODING,
            "num_channels": 1,
            "sample_width": GNANI_TTS_SAMPLE_WIDTH,
            "container": GNANI_TTS_CONTAINER,
        },
    }
    # No client-supplied request id is documented, and we invent none: the vendor mints
    # `request_id` on its `start` message.
    assert "request_id" not in payload


def test_the_telephony_audio_is_pcm_because_the_carrier_leg_encodes_mulaw_itself() -> None:
    """THE format decision, pinned to the reason for it.

    Gnani's docs recommend `container=mulaw` for G.711 telephony, and that is right for a
    client writing the socket's output straight to the line. Ours does not: the bytes go
    into a `TTSAudioRawFrame` and Plivo's serializer µ-law-encodes every audio frame on the
    way out. Asking Gnani for µ-law would encode it twice and put noise on the line — with
    no type to catch it, because both are `bytes`.
    """
    from pipecat.serializers import plivo

    assert "pcm_to_ulaw" in inspect.getsource(plivo.PlivoFrameSerializer.serialize), (
        "the Plivo serializer no longer encodes µ-law itself — re-decide the container, "
        "because the reason for linear PCM was that it did."
    )
    assert GNANI_TTS_ENCODING == "linear_pcm"
    assert GNANI_TTS_CONTAINER == "raw"


async def test_base64_audio_is_decoded_in_order_and_complete_ends_the_turn(
    connected: Any,
) -> None:
    """The vendor streams JSON TEXT carrying base64, not binary frames."""
    first, second = b"\x01\x02\x03\x04", b"\x05\x06\x07\x08"
    service, _, _ = connected(
        [START_REPLY, audio_reply(first, index=1), audio_reply(second, index=2), COMPLETE_REPLY]
    )
    pushed: list[Frame] = []

    async def capture(frame: Frame, direction: Any = None) -> None:
        pushed.append(frame)

    service.push_frame = capture  # type: ignore[method-assign]
    await service._connect_websocket()

    async for _ in service.run_tts("హలో", "ctx-1"):
        pass
    await asyncio.sleep(0.05)

    audio = b"".join(f.audio for f in pushed if isinstance(f, TTSAudioRawFrame))
    assert audio == first + second
    assert all(
        f.sample_rate == TELEPHONY_SAMPLE_RATE_HZ for f in pushed if isinstance(f, TTSAudioRawFrame)
    )
    # `complete` is an EXPLICIT end of synthesis, which is why this service needs no idle
    # timeout — see the module docstring on why §5's "save three seconds" does not apply.
    assert any(isinstance(f, TTSStoppedFrame) for f in pushed)


# --------------------------------------------------------------------------------------
# What the vendor's own validators refuse, which we deliberately do not re-implement.
# --------------------------------------------------------------------------------------


def test_a_voice_that_is_not_a_timbre_v25_voice_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="Unsupported voice"):
        build_gnani_tts(api_key="k", voice="Anushka", language="te-IN")


def test_a_language_the_vendor_does_not_serve_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        build_gnani_tts(api_key="k", voice="Suhana", language="fr-FR")


def test_none_of_the_plugins_defaults_are_inherited() -> None:
    """Each default below is one this product must not take, named with its reason."""
    from gnani.tts.client import DEFAULT_MODEL, TIMBRE_V20_VOICES

    assert DEFAULT_MODEL == "timbre-v2.0", "the vendor's default model moved — re-read"
    assert GNANI_TTS_MODEL == "timbre-v2.5"
    # The default model's four voices contain no Telugu voice at all, which is what taking
    # the default would silently do to a Telugu-first product.
    assert set(TIMBRE_V20_VOICES) == {"Pranav", "Kaveri", "Shubhra", "Deepak"}
    assert "Suhana" not in TIMBRE_V20_VOICES
    # And the plugin's default sample rate is 16 kHz, against a carrier leg that is 8.
    assert plugin_tts._DEFAULT_TTS_SAMPLE_RATE == 16000
    assert TELEPHONY_SAMPLE_RATE_HZ == 8000


# --------------------------------------------------------------------------------------
# The seam: how a call reaches this leg at all. Kept here rather than in
# `voice_worker_pipeline_test.py` so that one lane's work is one file to review.
# --------------------------------------------------------------------------------------


def _gnani_config(**overrides: Any) -> Any:
    from uuid import uuid4

    from calevate_shared.engine import ModelConfig, azure_openai_base_url
    from voice_worker import pipeline

    prompt = "You are Calevate's receptionist. You are an AI. This call is recorded."
    models = ModelConfig(
        stt_model="saaras:v4",
        tts_provider="gnani",
        tts_model="timbre-v2.5",
        tts_voice="Suhana",
        llm_provider="azure_openai",
        llm_model="calevate-gpt-4o-mini",
        llm_base_url=azure_openai_base_url("calevate-eastus2"),
    )
    base: dict[str, Any] = {
        "call_id": "call-gnani",
        "tenant_id": uuid4(),
        "agent_id": uuid4(),
        "agent_config_version_id": uuid4(),
        "direction": "inbound",
        "system_prompt": prompt,
        "prompt_sha256": pipeline.recompute_prompt_sha256(prompt),
        "models": models,
        "language": "te-IN",
    }
    base.update(overrides)
    return pipeline.SessionConfig(**base)


def _credentials(**overrides: Any) -> Any:
    from voice_worker.pipeline import VendorCredentials

    base: dict[str, Any] = {
        "sarvam_api_key": "sarvam",
        "llm_api_key": "llm",
        "gnani_api_key": "gnani",
    }
    base.update(overrides)
    return VendorCredentials(**base)


def test_an_agent_that_names_gnani_gets_the_gnani_leg() -> None:
    from voice_worker.pipeline import _build_tts

    service = _build_tts(_gnani_config(), _credentials())

    assert isinstance(service, CalevateGnaniTTSService)
    # The agent's own voice and language, not the vendor's defaults.
    assert service._settings.voice == "Suhana"
    assert service._settings.model == GNANI_TTS_MODEL


def test_a_container_with_no_gnani_key_refuses_that_call_by_name() -> None:
    """Not a fallback to Sarvam: a client's caller would hear a voice their agent does not
    name, which is the one thing `credentials_for` already refuses for the LLM leg."""
    from voice_worker.pipeline import _build_tts

    with pytest.raises(ValueError, match="GNANI_API_KEY"):
        _build_tts(_gnani_config(), _credentials(gnani_api_key=None))


def test_a_gnani_agent_with_no_voice_or_no_language_refuses() -> None:
    from calevate_shared.engine import ModelConfig, azure_openai_base_url
    from voice_worker.pipeline import _build_tts

    voiceless = ModelConfig(
        tts_provider="gnani",
        tts_voice=None,
        llm_provider="azure_openai",
        llm_base_url=azure_openai_base_url("calevate-eastus2"),
    )
    with pytest.raises(ValueError, match="names no voice"):
        _build_tts(_gnani_config(models=voiceless), _credentials())

    with pytest.raises(ValueError, match="names no language"):
        _build_tts(_gnani_config(language=None), _credentials())


def test_the_container_reads_the_key_from_its_own_secret_set() -> None:
    """`GNANI_API_KEY` in the Pipecat Cloud secret set, and OPTIONAL: a deployment with no
    Gnani key still starts and still serves every Sarvam call."""
    from voice_worker.boot import GNANI_KEY_ENV, load_worker_config

    env = {
        "VOICE_WORKER_API_BASE_URL": "https://api.example",
        "VOICE_WORKER_API_TOKEN": "t",
        "OBJECT_STORE_BUCKET": "b",
        "OBJECT_STORE_ENDPOINT": "https://s3.example",
        "AWS_ACCESS_KEY_ID": "a",
        "AWS_SECRET_ACCESS_KEY": "b",
        "SARVAM_API_KEY": "s",
        "PLIVO_AUTH_ID": "p",
        "PLIVO_AUTH_TOKEN": "t",
        "AZURE_OPENAI_API_KEY": "k",
    }
    assert GNANI_KEY_ENV == "GNANI_API_KEY"
    assert load_worker_config(env).gnani_api_key is None
    assert load_worker_config({**env, GNANI_KEY_ENV: "  gk  "}).gnani_api_key == "gk"
    assert load_worker_config({**env, GNANI_KEY_ENV: "gk"}).credentials_for(None).gnani_api_key


def test_the_ops_console_offers_the_key_where_it_is_actually_read() -> None:
    """D-614's shape, not `cartesia_api_key`'s, and the difference is that NOTHING on this
    host holds a Gnani client to give a stored value to."""
    from apps.api.core.settings import (
        ENV_ONLY_DISPLAY,
        ENV_ONLY_FOREIGN_ENV,
        ENV_ONLY_KEYS,
        env_var_for,
    )
    from apps.api.ops.secret_service import manageable_secret_keys
    from calevate_shared.config import Settings

    assert "gnani_api_key" in Settings.model_fields
    assert env_var_for("gnani_api_key") == "GNANI_API_KEY"
    assert "gnani_api_key" in ENV_ONLY_KEYS
    assert "calevate-voice-worker" in ENV_ONLY_FOREIGN_ENV["gnani_api_key"]
    assert "GNANI_API_KEY" in ENV_ONLY_DISPLAY["gnani_api_key"]
    # A box the console would let an operator type into would store a value nothing reads.
    assert "gnani_api_key" not in manageable_secret_keys()
