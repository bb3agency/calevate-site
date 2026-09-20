"""The Gnani TTS leg (D-618): the vendor's own Pipecat service, with our three gap-fills.

`docs/PIPECAT-MIGRATION.md` §5 staged this class as something we would WRITE. We do not:
**Gnani ship an official Pipecat plugin**, `pipecat-gnani`, and the vendor's own
`GnaniTTSService` already subclasses `InterruptibleTTSService` and speaks the documented
WebSocket protocol. Pipecat's own agent-authoring guide is unambiguous about which of the
two this repository is allowed to prefer — golden rule 1, *"Scaffold first. Never
hand-write boilerplate … Modify what it generates; don't rebuild it or invent your own
structure"* (`.venv/lib/python3.12/site-packages/pipecat/cli/agent_templates/AGENTS.md:12`).
So this module is a SUBCLASS and a factory, not a protocol implementation.

WHAT IS VERIFIED, AND HOW
-------------------------
* **The plugin.** `pipecat-gnani` 0.5.12, sdist+wheel, read from PyPI's JSON API in this
  container on 15 Sep 2026 (`pypi.org` is reachable; `docs.gnani.ai`, `gnani.ai` and
  `api.vachana.ai` are NOT — all three measured HTTP 000 the same day). The wheel was
  downloaded, its SHA-256 compared against the release digest
  (`8615710aa5131f44462d84d49877efadefa72e34814c1ddf10126cc291c6650d`) and every line of
  its 2 075 read BEFORE it was added to `pyproject.toml` (hard rule 9). Every claim below
  cites the INSTALLED source, which `uv.lock` pins by that same hash.
* **The protocol.** `wss://api.vachana.ai/api/v1/tts`, `X-API-Key-ID` on the upgrade,
  a JSON synthesis message, and JSON `start` / `audio` / `complete` replies carrying
  BASE64 audio rather than binary frames — VENDOR-PUBLISHED, `docs.gnani.ai/api/TTS/
  tts-websocket` (sitemap `lastmod` 2026-08-05), read by the founder on 15 Sep 2026 and
  relayed. The installed plugin implements exactly that shape
  (`pipecat_gnani/tts.py:938-1043`), which is corroboration from a second artefact rather
  than a second reading of the first.
* **The voices.** 42 names for `timbre-v2.5`, referenced BY NAME with no id — the same
  list in the founder's reading and in `gnani.tts.client.TIMBRE_V25_VOICES`. The
  catalogue half lives in `apps/api/agents/gnani_voices.py`; this module never enumerates
  a voice, it is handed one.

WHAT IS UNKNOWN AND IS NOT GUESSED HERE (each also in `docs/PIPECAT-MIGRATION.md` §7)
-------------------------------------------------------------------------------------
1. **No published price.** There is no per-character or per-second Gnani rate anywhere.
   A reseller's ₹27/10 000 figure exists and is THEIR platform's price, not Gnani's, and
   it must never reach `unit_cost_paid`. This module prices nothing; `meter.py` refuses an
   unattested leg exactly as it already does (§1.3).
2. **No documented cancel, flush or stop message.** The only interruption the vendor
   documents is "either side closes the connection" — see `_disconnect` below, which is
   where that costs us something real.
3. **No published rate limit.** §5 used to gate this work on *"whether Gnani's 60 req/min
   TTS cap counts a WebSocket session or each utterance"*. The current documentation does
   not state that number AT ALL, so the gate as written was answering a question about a
   figure nobody can now source. It is UNKNOWN — which is not "there is no limit".

THE THREE GAPS WE FILL, AND WHAT WOULD LET US DELETE EACH
----------------------------------------------------------
The plugin declares `pipecat-ai>=0.0.50` and its documentation says "tested with Pipecat
v1.5.0". We pin `1.10.0`. A floor that loose is not a compatibility claim, so every gap
below was found by RUNNING the thing against our pin (`tests/voice_worker_gnani_tts_test.py`
is that run, and each test fails if the gap closes upstream — which is how we learn to
delete the workaround rather than carrying it forever).

**GAP 1 — the package does not import at all on 1.10.0.** `pipecat_gnani/tts.py:40` and
`stt.py:30` import `_NotGiven` from `pipecat.services.settings`; 1.10.0 exports the
sentinel's type as the PUBLIC `NotGiven` (re-exported from `pipecat.utils.types` at
`pipecat/services/settings.py:47`) and has no underscore alias. `import pipecat_gnani`
raises `ImportError` before anything else can be tried. The name is used only in type
annotations that a dataclass field evaluates at class creation, so the alias below is
sufficient and changes no behaviour. **Delete when** a plugin release imports `NotGiven`.

**GAP 2 — "built-in interruption" is advertised and is not wired.**
`InterruptibleTTSService._handle_interruption` reconnects by calling `self._disconnect()`
then `self._connect()` (`pipecat/services/tts_service.py:2005-2013`), and those two are
the base class's FLAG-ONLY implementations whose docstrings tell a subclass to override
them and call `_connect_websocket` / `_disconnect_websocket`
(`pipecat/services/websocket_service.py:378-398`). The plugin implements the two
`_websocket` halves and overrides neither of the two the interruption path calls. The
consequence on a phone line is not subtle: a caller talks over the agent, Pipecat clears
the playout buffer, and the socket stays open with the vendor still synthesising and
still streaming the rest of a sentence nobody will hear — and on a vendor whose protocol
has no cancel message, closing the socket is the ONLY way to stop it. `_connect` and
`_disconnect` below are those two overrides. **Delete when** the plugin overrides them.

**GAP 3 — a socket that dies mid-call stays dead for the rest of the call.** The plugin
runs its receive loop as a bare `asyncio.create_task` (`tts.py:966`) rather than through
`WebsocketService._receive_task_handler`, which is the half of the base class that
reconnects with backoff (`websocket_service.py:338-375`). Its own loop catches every
exception, pushes an error frame and RETURNS, leaving `self._ws` pointing at a dead
socket — so the next utterance sends into it, raises, and the agent is mute until the
call ends. `_receive_messages` below drops the reference on that path only, which makes
`run_tts`'s existing `if not self._ws: await self._connect_websocket()` (`tts.py:911-912`)
the reconnect it was clearly meant to be. **Delete when** the plugin drives its receive
loop through `_receive_task_handler`.

**NOT FIXED, AND SAID PLAINLY**: `docs/PIPECAT-MIGRATION.md` §5 asks for one improvement
over the Neuphonic template — *"call `remove_audio_context()` from the receive loop and
save three seconds per turn"*. It does not apply to this plugin and is not a gap: the
three seconds were Neuphonic's idle-timeout close of an AUDIO CONTEXT, and
`GnaniTTSService` is not a context service at all (it is `InterruptibleTTSService`, whose
`Settings`, receive loop and `TTSStoppedFrame` on `complete` involve no context to
remove). There is no three seconds here to save. §5 is corrected to say so.

**THE COMMUNITY-MAINTAINED FACT, RECORDED RATHER THAN BURIED**: Pipecat's own service
page carries a banner that this integration is built and maintained by Gnani and that
*"Pipecat does not test or officially support it"* (VENDOR-PUBLISHED, relayed by the
founder 15 Sep 2026; `docs.pipecat.ai` is egress-blocked here). On a component that sits
on the call path that is a reliability fact the founder has weighed and accepted (D-618),
not an objection — and the three gaps above are what it looks like in practice.
"""

from __future__ import annotations

import asyncio
from typing import Final

from pipecat.services import settings as _pipecat_settings
from pipecat.utils.types import NotGiven as _PipecatNotGiven

# GAP 1. Installed BEFORE `pipecat_gnani` is imported, because the name is evaluated while
# the plugin's settings dataclasses are being created. Guarded on absence so that a plugin
# release which stops needing it, or a Pipecat release which restores the private name,
# silently makes this a no-op instead of clobbering somebody else's symbol.
if not hasattr(_pipecat_settings, "_NotGiven"):
    _pipecat_settings._NotGiven = _PipecatNotGiven  # type: ignore[attr-defined]

from pipecat_gnani.tts import (
    GnaniTTSService,
    GnaniTTSSettings,
)

#: The model the 42-voice catalogue belongs to, and the one this product runs.
#:
#: **NOT THE PLUGIN'S DEFAULT.** `gnani.tts.client.DEFAULT_MODEL` is `timbre-v2.0`, which
#: has FOUR voices (`TIMBRE_V20_VOICES`: Pranav, Kaveri, Shubhra, Deepak) and no Telugu
#: among them — taking the default would silently put a Telugu-first product on an English
#: and Hindi voice set. `timbre-v2.5` is also the only model that accepts `language` at
#: all: `_validate_timbre_options` raises *"language is only supported for model
#: 'timbre-v2.5'"* (`gnani/tts/client.py:318-323`), and the plugin only puts `language`
#: on the wire for this model (`pipecat_gnani/tts.py:224-226`).
GNANI_TTS_MODEL: Final[str] = "timbre-v2.5"

#: The telephony leg's rate. Same constant and same reason as `pipeline.py`'s: Plivo is
#: 8 kHz, and 8000 is one of the six rates the vendor accepts
#: (`gnani/tts/client.py:128`).
TELEPHONY_SAMPLE_RATE_HZ: Final[int] = 8000

#: **LINEAR PCM, NOT µ-LAW, AND THE BRIEF THIS WAS BUILT FROM SAID THE OPPOSITE.**
#:
#: Gnani's documentation is right that `container=mulaw` is what a G.711 telephony
#: endpoint wants, and it forces 8 kHz. It is the wrong thing to ask for HERE, because the
#: bytes do not go to the carrier from this service — they go into a `TTSAudioRawFrame`,
#: and `PlivoFrameSerializer.serialize` calls `pcm_to_ulaw(data, frame.sample_rate,
#: 8000, ...)` on every audio frame before it reaches Plivo
#: (`pipecat/serializers/plivo.py:145-146`, read 15 Sep 2026). Handing it µ-law would
#: µ-law-encode µ-law: the carrier would receive a byte stream that decodes to noise, on a
#: path with no type to catch it because both are `bytes`. The vendor's advice is for a
#: client that writes the socket's output straight to the line; ours does not.
#:
#: `raw` rather than `wav` for the container: the plugin's `_TtsPcmProcessor` strips a
#: RIFF header when it sees one and passes anything else through (`pipecat_gnani/
#: tts.py:122-154`), so BOTH work — and `raw` is the one that does not spend a
#: split-header reassembly path on the call path for 44 bytes we would discard.
#:
#: ⚠ `sample_width: 2` is what the vendor's own example sends beside `linear_pcm`. What it
#: would MEAN beside a µ-law container is not stated anywhere, which is one more reason
#: not to be there.
GNANI_TTS_ENCODING: Final[str] = "linear_pcm"
GNANI_TTS_CONTAINER: Final[str] = "raw"
GNANI_TTS_SAMPLE_WIDTH: Final[int] = 2


# `type: ignore[misc]` — `disallow_subclassing_any` under mypy strict, because the plugin
# ships no `py.typed` and every name in it is `Any` (see the `pipecat_gnani.*` override in
# the root `pyproject.toml`). Narrowed to this one line rather than turned off for the
# module: the three overrides below are annotated and checked, and the factory's return
# type is this class, so nothing untyped escapes the file.
class CalevateGnaniTTSService(GnaniTTSService):  # type: ignore[misc]
    """`pipecat-gnani`'s WebSocket TTS, with gaps 2 and 3 of the module docstring filled.

    Subclassed rather than forked: a fork would take the vendor's 2 075 lines into this
    repository and end the possibility of an upgrade, while each of the three overrides
    below is deleted by a plugin release and nothing else moves.
    """

    async def _connect(self) -> None:
        """GAP 2, the reconnect half.

        `WebsocketService._connect` only clears the disconnecting flag and asks the
        subclass to open the socket (`websocket_service.py:378-386`); `super()` does the
        first and this line does the second. Reached on every barge-in, and on nothing
        else — `start()` opens the socket directly.
        """
        await super()._connect()
        await self._connect_websocket()

    async def _disconnect(self) -> None:
        """GAP 2, the half that actually stops the vendor talking.

        ⚠ **THIS IS THE ONLY DOCUMENTED WAY TO INTERRUPT GNANI, AND IT COSTS A CONNECTION
        PER BARGE-IN.** Their protocol has no cancel, flush or stop message: the
        documentation's only interruption is that either side closes the connection. So
        every time a caller talks over the agent we throw away the TCP connection and the
        TLS handshake and open both again — on a phone product, where barge-in happens
        constantly, several times a call.

        **WHAT IT DOES NOT COST IS DEAD AIR, AND THAT IS WORTH STATING BECAUSE THE SHAPE
        INVITES THE OPPOSITE READING.** The interruption is broadcast when the user turn
        STARTS, not when it ends (`llm_response_universal.py:1328-1329`), so this reconnect
        runs while the caller is still talking and finishes concurrently with endpointing,
        STT finalisation and the LLM's first token. The next `run_tts` cannot arrive until
        all three have, so the handshake is off the voice-to-voice path rather than added
        to it. `tests/voice_worker_gnani_tts_test.py` pins that ordering.

        Two things about that are UNKNOWN and are not guessed: whether closing the socket
        actually stops synthesis SERVER-SIDE, and whether we are billed for the text the
        vendor had already accepted. Both are commercial questions for the founder to put
        to Gnani (OPERATIONS §2 gate 56), and the second one reaches money.

        The alternative — leaving the socket open and letting Pipecat discard the audio —
        was rejected: it is the plugin's current behaviour, it is what makes the advertised
        interruption support untrue, and on a metered vendor it means paying for every
        syllable of every sentence a caller cut off.
        """
        await super()._disconnect()
        await self._disconnect_websocket()

    async def _receive_messages(self) -> None:
        """GAP 3: a socket the vendor's loop gave up on stops being this service's socket.

        The plugin's loop returns rather than raising on a dropped connection, so without
        this the next `run_tts` writes into a dead socket for the rest of the call. On
        CANCELLATION we re-raise and touch nothing: that path is `_disconnect_websocket`
        cancelling the task and then closing the socket itself, and clearing the reference
        there would leak the connection we are closing precisely to interrupt.
        """
        try:
            await super()._receive_messages()
        except asyncio.CancelledError:
            raise
        self._ws = None


def build_gnani_tts(
    *,
    api_key: str,
    voice: str,
    language: str,
    sample_rate: int = TELEPHONY_SAMPLE_RATE_HZ,
) -> CalevateGnaniTTSService:
    """THE one construction of a Gnani TTS leg. `pipeline._build_tts` is the only caller.

    Every setting is passed EXPLICITLY, none inherited: the plugin's defaults are
    `timbre-v2.0`, the voice `Pranav`, `container="wav"` and a 16 kHz sample rate
    (`pipecat_gnani/tts.py:279-295`, `:66`), and all four are wrong for a Telugu-first
    telephony product. `language` likewise is not optional — `timbre-v2.5` is the model
    that takes it, the voices are documented as optimised for one locale each, and the
    vendor says a mismatched language "may reduce quality".

    The key is a CONSTRUCTOR ARGUMENT and never an ambient read. The plugin's own examples
    take `GNANI_API_KEY` out of the environment; this container reads its environment once
    in `boot.py` and hands the value down, which is the same discipline every other leg
    here follows and the reason a test can build this service with no secret set.

    Raises `ValueError` from the vendor's own validators for a voice that is not a
    `timbre-v2.5` voice or a language it does not serve — deliberately NOT re-implemented
    here (`gnani/tts/client.py:262-332` is the enumeration, and a second copy in this file
    would be the one that goes stale).
    """
    return CalevateGnaniTTSService(
        api_key=api_key,
        model=GNANI_TTS_MODEL,
        voice_id=voice,
        sample_rate=sample_rate,
        settings=GnaniTTSSettings(
            language=language,
            encoding=GNANI_TTS_ENCODING,
            container=GNANI_TTS_CONTAINER,
            sample_width=GNANI_TTS_SAMPLE_WIDTH,
        ),
    )


__all__ = [
    "GNANI_TTS_CONTAINER",
    "GNANI_TTS_ENCODING",
    "GNANI_TTS_MODEL",
    "GNANI_TTS_SAMPLE_WIDTH",
    "TELEPHONY_SAMPLE_RATE_HZ",
    "CalevateGnaniTTSService",
    "build_gnani_tts",
]
