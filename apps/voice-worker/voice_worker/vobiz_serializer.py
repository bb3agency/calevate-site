"""Vobiz's WebSocket media protocol as a Pipecat `FrameSerializer`.

Written from the vendor's documented protocol rather than adopted from `pipecat-vobiz`
(`docs/evidence/vobiz-integration-plan.md` §3a: an alpha single-maintainer package that
installs into `pipecat-ai`'s own package directory, sends a credentialed REST hangup by
default and logs raw wire messages). Every envelope below is cited to the hash-pinned mirror
`vobiz-findings/mirror/pages/xml/stream/stream-events.md` (fetched 2 Oct 2026).

What differs from `PlivoFrameSerializer`, whose envelopes are otherwise the same
(`pipecat/serializers/plivo.py:139-163`):

* The call is ended IN-BAND with `{"event":"stop","streamId":…}`. With no XML after
  `<Stream>`, Vobiz hangs the call up itself (cause 4010, `stream-events.md:226-236`,
  `:262-293`), so this worker holds no carrier credential and makes no REST call.
* Nothing from the wire is logged: not a payload, not a raw message, not a vendor value.
  A frame we cannot parse is dropped and counted.
* `dtmf` is recognised and dropped: the event exists (`integrations/gemini-live.md:27`) but
  no page in the mirror shows its body, and guessing Plivo's shape would be a guess.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.serializers.base_serializer import FrameSerializer

#: The only inbound format this serializer decodes: what our `<Stream contentType=
#: "audio/x-mulaw;rate=8000">` asks for, and the PSTN codec, so no transcoding happens on
#: the carrier side (`xml/stream.md:47`).
MULAW_CONTENT_TYPE: Final = "audio/x-mulaw"
VOBIZ_SAMPLE_RATE_HZ: Final = 8000

#: Formats the vendor documents for inbound media (`stream-events.md:105`). Used only to
#: decide whether a refused format may be NAMED in the error; anything outside this set is
#: reported as undocumented rather than echoed.
_DOCUMENTED_ENCODINGS: Final = frozenset({"audio/x-l16", MULAW_CONTENT_TYPE})
_DOCUMENTED_RATES: Final = frozenset({8000, 16000})

#: The track carrying the caller. With `bidirectional="true"` it is the only one sent
#: (`stream-events.md:104`); anything else is not caller audio.
_INBOUND_TRACK: Final = "inbound"


class VobizMediaFormatError(ValueError):
    """The stream's inbound format is not 8 kHz μ-law, so its audio cannot be decoded.

    Raised rather than decoded anyway: L16 bytes read as μ-law are loud noise, and a call
    that sounds connected but carries noise is worse than a refused one. The message never
    carries a value the vendor sent unless it is one of the documented format names.
    """


@dataclass(frozen=True, slots=True)
class MediaFormat:
    """`start.mediaFormat`: the encoding and rate of every inbound `media` payload."""

    encoding: str
    sample_rate: int | None

    @classmethod
    def from_start(cls, start: Mapping[str, Any]) -> MediaFormat | None:
        """Read it off a `start` event's inner object, or `None` when absent or malformed."""
        raw = start.get("mediaFormat")
        if not isinstance(raw, Mapping):
            return None
        encoding = raw.get("encoding")
        if not isinstance(encoding, str):
            return None
        rate = raw.get("sampleRate")
        try:
            sample_rate = int(rate) if rate is not None else None
        except (TypeError, ValueError):
            sample_rate = None
        return cls(encoding=encoding, sample_rate=sample_rate)

    @property
    def media_type(self) -> str:
        """The encoding without parameters, lower-cased: `audio/x-mulaw;rate=8000` reads
        as `audio/x-mulaw`, because `start.mediaFormat` mirrors the `<Stream contentType>`
        we chose (`stream-events.md:107`) and that attribute carries a `;rate=` suffix."""
        return self.encoding.split(";", 1)[0].strip().lower()

    def require_mulaw_8k(self) -> None:
        """Refuse anything but 8 kHz μ-law."""
        if self.media_type == MULAW_CONTENT_TYPE and self.sample_rate == VOBIZ_SAMPLE_RATE_HZ:
            return
        if self.media_type in _DOCUMENTED_ENCODINGS and self.sample_rate in _DOCUMENTED_RATES:
            described = f"{self.media_type} at {self.sample_rate} Hz"
        else:
            described = "a format the vendor's documentation does not list"
        raise VobizMediaFormatError(
            f"the Vobiz stream reports {described}; this worker decodes only "
            f"{MULAW_CONTENT_TYPE} at {VOBIZ_SAMPLE_RATE_HZ} Hz. Check the <Stream "
            'contentType="audio/x-mulaw;rate=8000"> attribute in the answer document.'
        )


class VobizFrameSerializer(FrameSerializer):
    """Pipecat frames to and from Vobiz's bidirectional `<Stream>` WebSocket."""

    class InputParams(FrameSerializer.InputParams):
        """`sample_rate` overrides the pipeline input rate `setup` would otherwise read."""

        sample_rate: int | None = None

    def __init__(
        self,
        stream_id: str,
        *,
        media_format: MediaFormat | None = None,
        params: InputParams | None = None,
    ) -> None:
        """`stream_id` comes from the `start` event the handshake reader consumed.

        `media_format` is that same event's format, checked here so that a wrong
        `<Stream contentType>` refuses the call before any audio is decoded. An empty
        `stream_id` is allowed and is adopted from the next in-band `start`.
        """
        params = params or VobizFrameSerializer.InputParams()
        super().__init__(params)
        self._params: VobizFrameSerializer.InputParams = params
        if media_format is not None:
            media_format.require_mulaw_8k()
        self._stream_id = stream_id
        self._sample_rate = 0
        self._input_resampler = create_stream_resampler(
            clear_after_secs=params.resampler_clear_after_secs
        )
        self._output_resampler = create_stream_resampler(
            clear_after_secs=params.resampler_clear_after_secs
        )
        self._stop_sent = False
        self._dropped = 0

    @property
    def stream_id(self) -> str:
        return self._stream_id

    @property
    def dropped_messages(self) -> int:
        """Inbound messages that were not JSON objects or carried undecodable audio."""
        return self._dropped

    # The signature is `FrameSerializer.setup`'s own (`base_serializer.py:76`); mypy flags
    # it against `BaseObject.setup`, which the vendor's base class already overrides alike.
    async def setup(self, setup: FrameProcessorSetup) -> None:  # type: ignore[override]
        self._sample_rate = self._params.sample_rate or setup.audio_in_sample_rate

    # -- outbound -------------------------------------------------------------------------

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """`playAudio`, `clearAudio`, or the one `stop` that ends the call.

        Nothing is sent after `stop`: the stream is over on Vobiz's side
        (`stream-events.md:288`) and the transport is about to close the socket. Transport
        messages (`OutputTransportMessageFrame`) are not forwarded, because the carrier
        documents no command we would send that way.
        """
        if self._stop_sent:
            return None
        if isinstance(frame, (EndFrame, CancelFrame)):
            return self._stop()
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"event": "clearAudio", "streamId": self._stream_id})
        if isinstance(frame, AudioRawFrame):
            encoded = await pcm_to_ulaw(
                frame.audio, frame.sample_rate, VOBIZ_SAMPLE_RATE_HZ, self._output_resampler
            )
            if not encoded:
                return None
            return json.dumps(
                {
                    "event": "playAudio",
                    "streamId": self._stream_id,
                    "media": {
                        "contentType": MULAW_CONTENT_TYPE,
                        "sampleRate": VOBIZ_SAMPLE_RATE_HZ,
                        "payload": base64.b64encode(encoded).decode("ascii"),
                    },
                }
            )
        return None

    def _stop(self) -> str | None:
        """The in-band hangup, at most once per stream.

        With no `streamId` there is nothing to address it to; the transport closing the
        socket is then the only end signal, and Vobiz treats a closed socket as the end of
        the stream too (`stream-events.md:244-248`).
        """
        self._stop_sent = True
        if not self._stream_id:
            logger.error("vobiz stream has no streamId; ending by socket close only")
            return None
        return json.dumps({"event": "stop", "streamId": self._stream_id})

    # -- inbound --------------------------------------------------------------------------

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._drop("not JSON")
            return None
        if not isinstance(message, dict):
            self._drop("not a JSON object")
            return None

        event = message.get("event")
        if event == "media":
            return await self._media(message.get("media"))
        if event == "start":
            self._start(message.get("start"))
            return None
        if event == "dtmf":
            # The body is undocumented, so it is neither parsed nor logged.
            logger.info("vobiz dtmf event ignored: its body is not documented")
            return None
        # `playedStream` and `clearedAudio` are acknowledgements of commands we send; no
        # pipeline state depends on them. Unknown events are ignored the same way.
        return None

    def _start(self, start: Any) -> None:
        """A `start` that reaches the transport rather than the handshake reader.

        Validated the same way the handshake's was. The stream id is adopted only when we
        have none: a socket carries one stream (`xml/stream/initiate.md:148-153`), so a
        second, different id is not ours to switch to.
        """
        if not isinstance(start, Mapping):
            return
        media_format = MediaFormat.from_start(start)
        if media_format is not None:
            media_format.require_mulaw_8k()
        stream_id = start.get("streamId")
        if not self._stream_id and isinstance(stream_id, str):
            self._stream_id = stream_id

    async def _media(self, media: Any) -> Frame | None:
        if not isinstance(media, Mapping):
            return None
        track = media.get("track")
        if track is not None and track != _INBOUND_TRACK:
            return None
        payload = media.get("payload")
        if not isinstance(payload, str) or not payload:
            return None
        try:
            ulaw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            self._drop("undecodable audio payload")
            return None
        pcm = await ulaw_to_pcm(
            ulaw, VOBIZ_SAMPLE_RATE_HZ, self._sample_rate, self._input_resampler
        )
        if not pcm:
            return None
        return InputAudioRawFrame(audio=pcm, num_channels=1, sample_rate=self._sample_rate)

    def _drop(self, reason: str) -> None:
        """Count a message we could not use. Logged by count, never by content, and only
        at powers of two so a corrupted stream cannot flood the log at 50 frames a second."""
        self._dropped += 1
        if self._dropped & (self._dropped - 1) == 0:
            logger.warning("vobiz message dropped", reason=reason, dropped=self._dropped)


__all__ = [
    "MULAW_CONTENT_TYPE",
    "VOBIZ_SAMPLE_RATE_HZ",
    "MediaFormat",
    "VobizFrameSerializer",
    "VobizMediaFormatError",
]
