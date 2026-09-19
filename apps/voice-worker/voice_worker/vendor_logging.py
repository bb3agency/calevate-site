"""Hard rule 6 at the vendor's own log calls: Pipecat logs transcripts by default.

**THIS IS NOT A PRECAUTION, IT IS A MEASURED DEFECT IN THE DEFAULT CONFIGURATION.**
Pipecat logs through `loguru`, whose out-of-the-box handler writes DEBUG and above to
stderr — verified in this venv, not recalled: `logger.debug(...)` prints, `logger.trace(...)`
does not. Five call sites in the code paths this worker runs interpolate caller or agent
CONTENT into that stream (line numbers are `pipecat-ai==1.10.0` as installed, read
13 Sep 2026):

    pipecat/services/sarvam/stt.py:667   logger.debug(f"Received response: {message}")
                                         — the raw Sarvam frame, which carries the
                                           caller's transcript
    pipecat/services/tts_service.py:139  logger.debug(f"TTS request: {context_id} - {text}")
    pipecat/services/tts_service.py:821  logger.debug(f"{self}: Generating TTS [...]")
    pipecat/services/tts_service.py:1307 logger.trace(f"{self}: Generating TTS [...]")
    pipecat/services/tts_service.py:1309 logger.debug(f"{self}: Generating TTS [...]")

So a Pipecat process that nobody configured writes both halves of every conversation to
stdout, where the container runtime ships it. Hard rule 6 says never log transcript text;
"we did not write that line" is not a defence when we chose the library and shipped the
default.

**A LEVEL FLOOR IS NOT ENOUGH, WHICH IS THE WHOLE REASON THIS MODULE EXISTS.** Raising
the floor to INFO removes all five above. It does NOT remove:

    pipecat/services/tts_service.py:1318
        logger.warning(f"{self}: service is no longer usable, not speaking [{prepared_text}]")

which is a WARNING and carries the agent's sentence.

⚠ **THIS LIST IS ONLY AS COMPLETE AS THE LAST SWEEP OF THE WORKER'S IMPORT GRAPH** (swept
13 Sep 2026 over the SERVICE modules, re-swept 19 Sep 2026 after `carrier.py` pulled in
`pipecat.serializers.plivo`, `pipecat.transports.websocket.fastapi` and transitively
`pipecat.transports.base_output`). A new vendor import is a new sweep: the second one found
two more INFO-or-above call sites that interpolate CONTENT, both WARNINGs, so the level
floor does not reach them either:

    pipecat/serializers/plivo.py:221
        logger.warning(f"Failed to parse JSON message: {data}")

    — `data` is the RAW websocket frame as the carrier sent it. On a Plivo media stream
      that is `{"event": "media", "media": {"payload": "<base64 PCM>"}}`, so a single
      truncated or half-delivered frame writes the CALLER'S AUDIO to stdout. It is worse
      than the transcript leak this module was built for, on the one leg that carries
      audio at all, and it is reachable by anything that corrupts one frame on the wire.

    pipecat/transports/base_output.py:377
        logger.warning(f"{self} destination [...] not registered for frame {frame}")

    — `{frame}` renders through `Frame.__str__`, and `TextFrame.__str__` is
      `f"{self.name}(pts: {pts}, text: [{self.text}])"` (`pipecat/frames/frames.py:337`),
      which every spoken frame inherits. It fires only when a frame carries a
      `transport_destination` the output transport has no sender for — rare, and a
      misconfiguration rather than a routine event — but the rule is not "rarely log
      transcript text".

Everything else read in the new modules carries ids, sizes, exception types or our own
configuration. `pipecat/transports/base_output.py:918` looks like the same defect and is
not: it is guarded by `isinstance(frame, OutputAudioRawFrame)` (`:915`) and that frame's
`__str__` prints a byte COUNT (`frames.py:213`). `pipecat/services/sarvam/stt.py:1228`
does log a raw Sarvam message, but it lives in `SarvamRealtimeSTTService` (`stt.py:915`),
which `_build_stt` deliberately does not construct — an entry for it would be a guess
about a code path this worker cannot reach. Read 19 Sep 2026 against the installed
`pipecat-ai==1.10.0`; the pins below are what keeps that reading honest across a bump.

**WHY A PINNED (module, line) PAIR RATHER THAN A MESSAGE MATCH.** A substring match on
"not speaking" is a guess about a string the vendor may reword; the record's own origin is
not a guess. Pinning a line number across versions would normally be indefensible — but
`apps/voice-worker/pyproject.toml` pins `pipecat-ai==1.10.0` exactly and argues at length
that a floor would move the lines its evidence cites. The pin is what makes this legible,
and `tests/voice_worker_pipeline_test.py` re-reads the installed file and fails if that
line stops being the call it is pinned to — so a version bump surfaces as a red test
rather than as a silent leak.

**REJECTED — a redacting sink that rewrites the message.** `apps/workers/redaction.py`
exists and is good, but running it over every vendor log line is a per-record regex pass on
a latency-critical process, and a redactor that fails open turns a hard rule into a
best-effort. Dropping the record loses one operator signal that is reconstructible (the
service reports itself unusable through `on_pipeline_error` and `is_usable`, which carry no
text); leaking a caller's sentence is not reconstructible in the other direction.
"""

from __future__ import annotations

import sys
from typing import Any, Final

from loguru import logger

#: Records at or above this level are allowed through from `pipecat.*`.
#: DEBUG and TRACE are where four of the five content leaks live.
VENDOR_LOG_LEVEL: Final[str] = "INFO"

#: `(loguru record name, line)` pairs that interpolate caller or agent CONTENT at
#: `VENDOR_LOG_LEVEL` or above, and are therefore dropped whatever the level. Pinned to
#: `pipecat-ai==1.10.0`; see this module's docstring for why a line number is the right
#: key here and for the test that keeps it honest.
CONTENT_BEARING_RECORDS: Final[frozenset[tuple[str, int]]] = frozenset(
    {
        ("pipecat.services.tts_service", 1318),
        ("pipecat.serializers.plivo", 221),
        ("pipecat.transports.base_output", 377),
    }
)

#: The source text each pinned record must still be, so a dependency bump cannot move the
#: line out from under the denylist without failing a test. Read from the installed file.
#:
#: **A TUPLE OF LINES, NOT A LINE, BECAUSE ONE OF THE THREE CALLS IS WRAPPED.** loguru
#: attributes a record to the line the CALL starts on — measured, not recalled: a
#: `logger.warning(` whose message sits on the next line reports the `logger.warning(`
#: line. So the key is that line, and pinning only its text would pin the string
#: `logger.warning(`, which is true of a hundred call sites and would not notice the
#: vendor rewording the very message that makes the entry necessary. Each value is the
#: whole statement, stripped line by line; `tests/voice_worker_pipeline_test.py` compares
#: it against the installed file.
CONTENT_BEARING_SOURCE: Final[dict[tuple[str, int], tuple[str, ...]]] = {
    ("pipecat.services.tts_service", 1318): (
        'logger.warning(f"{self}: service is no longer usable, not speaking [{prepared_text}]")',
    ),
    ("pipecat.serializers.plivo", 221): (
        'logger.warning(f"Failed to parse JSON message: {data}")',
    ),
    ("pipecat.transports.base_output", 377): (
        "logger.warning(",
        'f"{self} destination [{frame.transport_destination}] not registered for frame {frame}"',
        ")",
    ),
}

_installed = False


def _guard(record: Any) -> bool:
    """loguru filter: True keeps the record.

    Applied to EVERY record, not only Pipecat's, because a filter that only inspected
    `pipecat.*` would be one `logger.remove()` away from letting our own DEBUG lines out
    too — and this process has the caller's audio in memory. Our own modules are held to
    the same floor; they log ids, so nothing is lost.
    """
    name = record["name"] or ""
    if (name, record["line"]) in CONTENT_BEARING_RECORDS:
        return False
    return bool(record["level"].no >= logger.level(VENDOR_LOG_LEVEL).no)


def install_vendor_log_guard(*, sink: Any | None = None) -> None:
    """Replace loguru's default handler with one that cannot emit conversation content.

    Idempotent, and called from `pipeline.build_vendor_legs` and `pipeline.assemble_call`
    rather than left to a `main()` to remember. A guard whose installation is the caller's
    responsibility is a guard that is absent on the one code path nobody re-read, and the
    failure mode is silent: the call still works, the transcript is just in the log.
    """
    global _installed
    if _installed:
        return
    logger.remove()
    logger.add(sink or sys.stderr, level=VENDOR_LOG_LEVEL, filter=_guard)
    _installed = True


def _reset_for_tests() -> None:
    """Let a test install the guard over its own sink. Not used in production."""
    global _installed
    _installed = False


__all__ = [
    "CONTENT_BEARING_RECORDS",
    "CONTENT_BEARING_SOURCE",
    "VENDOR_LOG_LEVEL",
    "install_vendor_log_guard",
]
