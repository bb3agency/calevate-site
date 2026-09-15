"""The conversation loop, assembled: `docs/PIPECAT-MIGRATION.md` §4, step 4 of §6.

    transport.input() -> STT -> user aggregator -> LLM -> TTS -> transport.output()
                                                             -> assistant aggregator

That ordering is the shipped one, not a guess: `examples/voice/voice-cartesia.py:86-96`
in the `pipecat-ai==1.10.0` tree, with the ASSISTANT aggregator after `transport.output()`
so it records what was actually spoken rather than what was generated.

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns a `SessionConfig` — plain data, no
vendor types, no secrets — plus three vendor legs into a runnable `PipelineWorker`, and it
is the only place in this repository that knows how those legs are configured.

**HARD RULE 2 AT ITS NEW BOUNDARY (D-592).** This package may import Pipecat. What it
HANDS OUT may not be a Pipecat object, and there is exactly one class here that converts:
`NormalizedEventBoundary`. Everything the rest of the system ever sees comes out of that
class as a `calevate_shared.events.CallEvent` or `TranscriptTurn`. Nothing else in this
module touches the sink, and a reviewer checking the rule has one class to read.

**WHAT IS DELIBERATELY NOT HERE.**

- **No database.** `config.py` LOADS the config version and `session.py` orders the start
  (config, then pack, then this); `attest.py` (§1.1) is still to come. `assemble_call`
  takes its configuration as an argument and reads no row itself, which is what keeps this
  module runnable with no database at all — see `SessionConfig` for the shape it expects.
- **No `GnaniTTSService`.** §5 stages it behind an unanswered vendor question (whether
  Gnani's 60 req/min cap counts a session or an utterance) and building before the answer
  is building for nothing.
- **No metering.** `meter.py` (§1.3) is another stream's file. `PipelineParams` below
  turns the metrics it needs ON, which is this module's whole obligation to it.
- **No carrier.** The Plivo transport is step 6 and needs an account in the India data
  region (BLOCKER-1). `assemble_call` takes the transport as an argument, so the same
  assembly runs against `FastAPIWebsocketTransport` in production and a fake in tests.

Every default changed below is changed against a line of source read in the installed
package on 13 Sep 2026, cited at the point of use. Nothing here is measured on real
Telugu PSTN audio — `docs/evidence/pre-build-blockers-2026-09-13.md` §3.6 M-1..M-5 is that
open item, and the settings that need a measurement say so where they are set.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from calevate_shared.engine import (
    INHERITED_TURN_DETECTION_MS,
    ModelConfig,
    fill_caller_memory_slot,
    google_openai_compat_base_url,
)
from calevate_shared.events import CallDirection, CallEvent, CallStatus, TranscriptTurn
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from voice_worker.knowledge import DEFAULT_TOP_K, QueryEmbedder, SessionKnowledge
from voice_worker.vendor_logging import install_vendor_log_guard

# ---------------------------------------------------------------------------------------
# The numbers we set deliberately, each against the source line that gave us the default.
# ---------------------------------------------------------------------------------------

#: `engine` on every `CallEvent` this worker emits. OUR vocabulary, not a vendor's: the
#: adapter that reads these rows is `apps/api/engine/pipecat.py` (§6 step 3).
ENGINE_NAME: Final[str] = "pipecat"

#: Smart turn v3's hard silence fallback, in seconds.
#:
#: **THE DEFAULT IS 3 SECONDS** — `SmartTurnParams.stop_secs: float = STOP_SECS` with
#: `STOP_SECS = 3` (`pipecat/audio/turn/smart_turn/base_smart_turn.py:41` and `:27`, read
#: 13 Sep 2026). What it does is not a model parameter: `append_audio` accumulates silence
#: and at `stop_secs` returns `EndOfTurnState.COMPLETE` **without running the model at
#: all** (`base_smart_turn.py:129-138`). It is the CEILING on a turn, the case where smart
#: turn never got to have an opinion.
#:
#: **SET TO THE NUMBER WE ALREADY RUN WITH, WHICH IS THE ONLY HONEST CHOICE AVAILABLE.**
#: `INHERITED_TURN_DETECTION_MS` is 650 ms — Bolna's `transcriber.endpointing` (250) plus
#: `incremental_delay` (400), the fixed-timeout endpointing this migration exists to beat
#: (`packages/shared/src/calevate_shared/engine.py:3904`,
#: `docs/evidence/orchestrator-livekit-vs-pipecat-2026-09-12.md:151-156`). Pinning the
#: ceiling there means the worst case of the new pipeline is the typical case of the old
#: one, while smart turn can end a turn EARLIER whenever it is confident. Three seconds
#: would have made our worst case 4.6x the thing we are replacing.
#:
#: ⚠ **THIS IS A STARTING POINT TO BE MEASURED, NOT A MEASUREMENT.** Nobody has run Telugu
#: PSTN audio through this analyzer — `docs/evidence/pre-build-blockers-2026-09-13.md`
#: §3.6 M-1 (decision latency on 8 kHz Telugu), M-2 (false endpoints on అవును/సరే/హా/ఓకే),
#: M-3 (code-switch false interruptions) and M-5 (whether the 650 ms actually falls) are
#: all open. The number to change when they close is this one, and the measurement is what
#: replaces this comment.
#:
#: The 0.5 decision threshold beside it is hardcoded — `probability > 0.5` at
#: `pipecat/audio/turn/smart_turn/local_smart_turn_v3.py:174` — and is not a parameter;
#: changing sensitivity means subclassing `_predict_endpoint`.
SMART_TURN_STOP_SECS: Final[float] = INHERITED_TURN_DETECTION_MS / 1000.0

#: Global tool-call timeout, in seconds.
#:
#: **THE DEFAULT IS `None` — NO TIMEOUT AT ALL** (`pipecat/services/llm_service.py:309`).
#: A handler that hangs holds the turn open forever, which on a phone call is dead air with
#: no end.
#:
#: **2.0 s, AND IT IS DERIVED FROM OUR OWN ENDPOINT RATHER THAN PICKED.** The in-call tool
#: surface is ours and already declares its worst case: `_TOOL_BODY_DEADLINE_S = 0.5` plus
#: `_TOOL_DURABLE_DEADLINE_S = 1.0` (`apps/voice-runtime/webhook_routes.py:253-254`), after
#: which it does not hang — it returns a problem+json refusal written for the agent to SAY.
#: So the caller-side timeout has to sit ABOVE 1.5 s or we would cancel the handler in the
#: moment it was about to hand us a sentence, and Pipecat's cancellation tells the LLM only
#: that "the function failed and returned no result"
#: (`llm_service.py:301-303`) — strictly worse for the caller than the refusal we wrote.
#: 2.0 s leaves 500 ms for the HTTP round trip over the container bridge and stays well
#: under the "four seconds of dead air" that same file names as the thing to avoid
#: (`webhook_routes.py:248-251`).
#:
#: Note this is the LLM-side ceiling, not the retrieval budget: `RETRIEVAL_BUDGET_MS` is
#: 100 ms and is what the endpoint is held to (CLAUDE.md, "measure it"). A ceiling equal to
#: the budget would fire on every slow-but-successful lookup.
FUNCTION_CALL_TIMEOUT_SECS: Final[float] = 2.0

#: The telephony leg's rate. Plivo is 8 kHz; Silero VAD supports 8 kHz and 16 kHz natively
#: (`pipecat/audio/vad/silero.py:134-135`) so nothing resamples for VAD, and smart turn v3
#: resamples to its own 16 kHz with `soxr` once per turn
#: (`local_smart_turn_v3.py:123-136`), not once per frame.
TELEPHONY_SAMPLE_RATE_HZ: Final[int] = 8000

#: The STT model our declared leg names. See `_build_stt` for why this constant decides
#: which of Pipecat's two Sarvam STT classes we can use at all.
STT_MODEL: Final[str] = "saaras:v4"

#: Today's Sarvam TTS model. `bulbul:v2` is withdrawn — Pipecat's own docstring says
#: "Sarvam's API rejects it" (`pipecat/services/sarvam/tts.py:648`).
TTS_MODEL: Final[str] = "bulbul:v3"


# ---------------------------------------------------------------------------------------
# The seam: what `config.py` and the secrets manager must hand this module.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """One call's configuration, as `config.py` will load it from `agent_config_versions`.

    **NO SECRETS AND NO VENDOR TYPES.** Both exclusions are load-bearing:

    - Secrets live in `VendorCredentials`, separately, because §1.1 makes the config
      version CONTENT-ADDRESSED — `prompt_sha256` and a hash of the resolved `ModelConfig`
      are what the worker attests it loaded, and a structure carrying an API key can never
      be hashed, logged or compared.
    - Vendor types (Pipecat's `Language`, a Sarvam speaker enum) stay out so this dataclass
      is exactly what a row in our own tables holds. The mapping to a vendor spelling
      happens in `_build_stt`/`_build_tts` and nowhere else.

    `models` is `calevate_shared.engine.ModelConfig` rather than a new set of fields:
    that model is already the portability contract, already carries `llm_provider` in OUR
    closed vocabulary, already knows that `llm_model` on an Azure leg is a DEPLOYMENT id,
    and already carries `llm_traps`. A second shape for the same facts would be the drift
    the quality bar forbids.
    """

    #: Ours, not a vendor's. On the Plivo leg this will be our own id for the session, and
    #: the carrier's CDR is reconciled against it (§1.2) rather than being its source.
    call_id: str
    tenant_id: UUID
    agent_id: UUID
    #: §1.1 — the immutable version this process loaded. `attest.py` reports it back, and
    #: `get_agent` returns the attestation rather than the control plane's intention.
    agent_config_version_id: UUID
    direction: CallDirection
    #: Already composed by `compose_engine_prompt` on the control-plane side, so the hard
    #: rule 5 sentences are in it before it reaches this container. This worker does not
    #: compose and must never edit it.
    system_prompt: str
    #: sha256 of `system_prompt`, as the control plane computed it. The worker RECOMPUTES
    #: it (`recompute_prompt_sha256`) rather than trusting it — that disagreement is the
    #: whole point of §1.1's attestation.
    prompt_sha256: str
    models: ModelConfig
    #: `pipecat:<tenant>:<agent>`, as `engine/pipecat.engine_agent_ref_for` minted it and
    #: `agents.engine_agent_ref` holds it. READ rather than rebuilt: this container must not
    #: import the monolith, and a restated format string is two spellings of one handle.
    #:
    #: It is here because `memory.ApiCallerMemoryReader` needs it — the caller-data endpoint
    #: resolves `engine_agent_ref → (tenant, agent)` through `engine_agent_routes` and that
    #: is the contract the rented engine already calls, so this leg reuses it rather than
    #: adding a second door taking ids. `None` for an agent whose publish predates the
    #: column being read here, which is an agent that recalls nothing rather than an error.
    engine_agent_ref: str | None = None
    #: BCP-47, e.g. `te-IN`. `None` means let Sarvam auto-detect, which is what
    #: `ModelConfig.stt_autodetect` asks for and the only path that model leaves us.
    language: str | None = None
    #: Whether the agent speaks first. Queued as an `LLMRunFrame` from the transport's
    #: connect event — the shipped pattern (`examples/voice/voice-cartesia.py:112-119`).
    greet_first: bool = True
    #: Which published knowledge pack this agent answers out of — the CONTENT DIGEST, which
    #: with `tenant_id` and `agent_id` is the whole object key (`pack_object_key`). It is a
    #: digest and not a URL because the pack is content-addressed and immutable (D-599): a
    #: version can be named, fetched, cached across sessions and compared, and a config
    #: version that carries it names exactly the words this call could have quoted.
    #:
    #: **`None` MEANS THE AGENT HAS NO PUBLISHED KNOWLEDGE BASE, WHICH IS AN ORDINARY
    #: STATE AND NOT AN ERROR.** Most agents on day one have none — an appointment-taking
    #: receptionist needs a calendar, not a corpus — and the search tool is still
    #: advertised, still answers, and says which of the two silences it is (see
    #: `knowledge_tool_payload`: `no_knowledge_base` is not `temporarily_unavailable`).
    knowledge_pack_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class VendorCredentials:
    """The container's vendor keys, from its secret set. Never persisted, hashed or logged.

    The founder holds every vendor account and installs the keys; clients bring no BYOK.
    `cartesia_api_key` is optional because it is only needed on the Studio tier, and
    `gnani_api_key` for the same shape of reason (D-618) — it is needed only by an agent
    whose `ModelConfig.tts_provider` names Gnani, and `_build_tts` refuses that call by
    name rather than letting the container fail to start for every other client.

    ⚠ **THE GNANI KEY REACHES THIS CONTAINER FROM ITS OWN ENVIRONMENT, NOT FROM THE OPS
    CONSOLE**, and that is why `Settings.gnani_api_key` is classified `env_only` there.
    `apps/api` holds no Gnani client at all; a console box storing a value nothing reads
    is the defect `core/platform_config.ENV_ONLY` exists to name.
    """

    sarvam_api_key: str
    llm_api_key: str
    cartesia_api_key: str | None = None
    gnani_api_key: str | None = None


@dataclass(frozen=True, slots=True)
class VendorLegs:
    """The three constructed vendor services, as processors.

    Typed as `FrameProcessor` rather than as their concrete classes so a test can put a
    stub in any slot without subclassing a websocket service. That is the same seam
    `docs/BACKEND-PATTERNS.md` §9 asks for ("worker/job factories accept a deps object").
    """

    stt: FrameProcessor
    llm: FrameProcessor
    tts: FrameProcessor


# ---------------------------------------------------------------------------------------
# The boundary. ONE class, and it is the only thing here that touches the sink.
# ---------------------------------------------------------------------------------------


class NormalizedEventSink(Protocol):
    """Where normalized events go. Implemented by the DB writer in the next wave.

    Deliberately two narrow methods rather than one `emit(Any)`: the type of what crosses
    this boundary is the guarantee, and a union would let a Pipecat frame through the day
    somebody widened it.
    """

    async def on_call_event(self, event: CallEvent) -> None: ...

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None: ...


def recompute_prompt_sha256(prompt: str) -> str:
    """§1.1: the worker's own reading of what it loaded, not the value it was handed.

    `get_agent` returns what the worker attested; the control plane's intention is the
    other side of a comparison that is only meaningful if the two are computed
    independently. Echoing `SessionConfig.prompt_sha256` back would agree by construction —
    the exact defect §1.1 says `control_plane` hosting has.
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class NormalizedEventBoundary:
    """**THE** place a Pipecat object becomes a Calevate model. Hard rule 2 lives here.

    It takes vendor types IN (`UserTurnStoppedMessage`, `AssistantTurnStoppedMessage` — the
    framework's own "a turn ended" payloads) and hands OUT `TranscriptTurn` and
    `CallEvent`. Nothing downstream of the sink learns Pipecat exists.

    **WHY THE AGGREGATORS' EVENTS AND NOT FRAMES, WHICH IS THE DESIGN DECISION HERE.**
    Three placements were possible and two are wrong:

    - **A processor at the tail of the pipeline** cannot see the caller at all. The user
      aggregator CONSUMES `TranscriptionFrame` and does not push it downstream —
      `pipecat/processors/aggregators/llm_response_universal.py:824-838`, where the branch
      calls `_handle_transcription(frame)` with no `push_frame`, and the comment says
      interim, translation and eager frames are consumed "same as final
      TranscriptionFrame". A tail tap would emit agent turns and silently never emit a
      caller turn.
    - **A `BaseObserver`** does see everything, but `on_push_frame` fires once per HOP, so
      the same frame arrives two or three times and has to be de-duplicated by `frame.id`
      in an unbounded set for the life of the call. It also sees `TTSTextFrame`, which is
      one aggregated CHUNK of speech, not a turn — reassembling turns from chunks would be
      re-implementing the aggregator that is already in the pipeline.
    - **The aggregators' own turn events** are the framework's answer to "what was one turn
      of this conversation", fire exactly once, and carry the already-aggregated text plus
      whether the turn was interrupted. `UserTurnStoppedMessage` and
      `AssistantTurnStoppedMessage` (`llm_response_universal.py:284-305`, `:331-348`) map
      onto `TranscriptTurn` field for field.

    **`text_redacted` IS LEFT `None` ON PURPOSE.** Redaction is step 2 of the post-call
    pipeline and `apps/workers/redaction.py` is the one pass that produces that column,
    validators and Telugu spoken-digit handling included. A second redactor running here
    would be two ways of doing one thing, and the weaker of the two would be the one on the
    latency-critical path.
    """

    def __init__(self, *, config: SessionConfig, sink: NormalizedEventSink) -> None:
        self._config = config
        self._sink = sink
        self._idx = 0
        self._started_at: datetime | None = None
        self._ended = False

    # -- call lifecycle ------------------------------------------------------------------

    async def call_started(self) -> None:
        """Emit `in_progress`. Idempotent — a re-`StartFrame` must not restart the clock."""
        if self._started_at is not None:
            return
        self._started_at = datetime.now(UTC)
        await self._sink.on_call_event(self._event("in_progress", ended_at=None))

    async def call_ended(self, *, status: CallStatus = "completed") -> None:
        """Emit a terminal event exactly once.

        ⚠ **THIS IS THE WORKER'S VIEW, NOT THE BILLABLE FACT.** §1.2 splits the record:
        connected/answered/duration/disposition are the CARRIER's, witnessed by the party
        that billed the minute, and `list_executions` reconciles against the Plivo CDR. What
        this worker is the sole author of is CONTENT. A `completed` here means "our
        pipeline drained", never "the call connected and lasted N seconds".
        """
        if self._ended:
            return
        self._ended = True
        await self._sink.on_call_event(self._event(status, ended_at=datetime.now(UTC)))

    def _event(self, status: CallStatus, *, ended_at: datetime | None) -> CallEvent:
        return CallEvent(
            call_id=self._config.call_id,
            tenant_id=self._config.tenant_id,
            agent_id=self._config.agent_id,
            direction=self._config.direction,
            status=status,
            started_at=self._started_at,
            ended_at=ended_at,
            engine=ENGINE_NAME,
        )

    # -- turns ---------------------------------------------------------------------------

    async def user_turn(self, message: UserTurnStoppedMessage) -> None:
        """A caller turn. `content` is `None` in realtime mode, which we do not run."""
        if not message.content:
            return
        await self._emit_turn("caller", message.content, message.timestamp)

    async def assistant_turn(self, message: AssistantTurnStoppedMessage) -> None:
        """An agent turn.

        An empty `content` is a real outcome, not an error: the docstring on
        `AssistantTurnStoppedMessage` says it happens when a turn is interrupted before any
        token was pushed. There is nothing the CRM can do with an empty turn, so it is
        dropped rather than stored as a blank row.
        """
        if not message.content:
            return
        await self._emit_turn("agent", message.content, message.timestamp)

    async def _emit_turn(self, speaker: str, text: str, started_iso: str) -> None:
        idx = self._idx
        self._idx += 1
        await self._sink.on_transcript_turn(
            TranscriptTurn(
                call_id=self._config.call_id,
                idx=idx,
                speaker="caller" if speaker == "caller" else "agent",
                text=text,
                text_redacted=None,
                lang=self._config.language,
                start_ms=self._offset_ms(started_iso),
                end_ms=self._offset_ms(None),
            )
        )

    def _offset_ms(self, iso: str | None) -> int | None:
        """Milliseconds from call start. `None` rather than a guess when either end is absent.

        Both instants come from the same clock: Pipecat stamps turns with
        `datetime.now(datetime.UTC).isoformat(timespec="milliseconds")`
        (`pipecat/utils/time.py:17-23`) and `call_started` uses `datetime.now(UTC)`.
        """
        if self._started_at is None:
            return None
        try:
            at = datetime.now(UTC) if iso is None else datetime.fromisoformat(iso)
        except ValueError:
            return None
        return max(0, round((at - self._started_at).total_seconds() * 1000))

    # -- wiring --------------------------------------------------------------------------

    def attach(self, *, worker: PipelineWorker, aggregators: LLMContextAggregatorPair) -> None:
        """Register the handlers. Called by `assemble_call`; no reason to call it yourself."""

        async def _on_user(
            _aggregator: Any, _strategy: Any, message: UserTurnStoppedMessage
        ) -> None:
            await self.user_turn(message)

        async def _on_assistant(_aggregator: Any, message: AssistantTurnStoppedMessage) -> None:
            await self.assistant_turn(message)

        async def _on_started(_worker: Any, _frame: Any) -> None:
            await self.call_started()

        async def _on_finished(_worker: Any, _frame: Any) -> None:
            await self.call_ended()

        aggregators.user().add_event_handler("on_user_turn_stopped", _on_user)
        aggregators.assistant().add_event_handler("on_assistant_turn_stopped", _on_assistant)
        worker.add_event_handler("on_pipeline_started", _on_started)
        worker.add_event_handler("on_pipeline_finished", _on_finished)


# ---------------------------------------------------------------------------------------
# Vendor legs.
# ---------------------------------------------------------------------------------------


def _language(config: SessionConfig) -> Language | None:
    """Our BCP-47 string to Pipecat's enum. `None` means auto-detect.

    `Language` is a `StrEnum` whose members hold exactly these codes
    (`pipecat/transcriptions/language.py:19`, `TE_IN = "te-IN"` at `:516`), so the lookup
    is a constructor call. An unrecognised code is a configuration error and raises rather
    than silently falling back to English, which is what `SarvamRealtimeSTTService` would
    do with its `language_code` default of `en-IN`.
    """
    if config.language is None:
        return None
    return Language(config.language)


def _build_stt(config: SessionConfig, credentials: VendorCredentials) -> FrameProcessor:
    """Sarvam STT.

    **`SarvamSTTService`, AND THE CHOICE IS DECIDED BY OUR DECLARED MODEL, NOT BY TASTE.**
    Pipecat ships two Sarvam STT classes and they are not interchangeable:

    - `SarvamSTTService` (`pipecat/services/sarvam/stt.py:173`) accepts exactly the keys of
      `MODEL_CONFIGS` — `saaras:v3` and `saaras:v4` (`stt.py:114-127`), anything else
      raising `ValueError` at construction (`stt.py:303-306`). Its hardcoded default is
      `saaras:v4` (`stt.py:267`). It runs over Sarvam's own SDK websocket.
    - `SarvamRealtimeSTTService` (`stt.py:915`) is fixed at `_REALTIME_MODEL =
      "saaras:v3-realtime"` (`stt.py:799`) and accepts no other id.

    **REJECTED — `SarvamRealtimeSTTService`, and it was the tempting one.** It is the only
    one of the two that emits `InterimTranscriptionFrame` (`stt.py:1362`; the non-realtime
    class imports the type and never constructs it), it validates 8 kHz explicitly —
    `SUPPORTED_SAMPLE_RATES = {8000, 16000}` at `stt.py:829`, which is the Plivo rate — and
    Pipecat's own benchmark figure for it is lower: `SARVAM_REALTIME_TTFS_P99 = 1.00` s
    against `SARVAM_TTFS_P99 = 1.17` s (`pipecat/services/stt_latency.py:60,62`). On a live
    phone call that 170 ms is real money, because `TurnAnalyzerUserTurnStopStrategy` uses
    the STT's declared P99 as its safety-net timeout, so it feeds straight into end-of-turn
    latency. It loses anyway on one fact that outranks all of that: **it cannot run
    `saaras:v4`**, and `saaras:v4` is the model our declared leg names and the only Sarvam
    model the vendor has left us for Telugu auto-detect
    (`calevate_shared.engine.ModelConfig.stt_autodetect`, which records four live refusals).
    Choosing the faster class would mean silently changing which transcriber a client's
    Telugu call runs on. Both P99 figures are Pipecat's REPORTED benchmark numbers anyway —
    neither is measured by us on our leg, and M-1..M-4 are what would settle it.

    **`vad_signals` IS LEFT UNSET, AND THAT IS A TURN-ARCHITECTURE DECISION.** With it on,
    `service_metadata_frame()` returns `ExternalUserTurnStrategies()` (`stt.py:387-399`),
    which tells the user aggregator to stop running local VAD and smart turn and to take
    Sarvam's server-side speech boundaries instead. Smart turn v3 is the whole reason for
    this migration, so we keep it; the cost is that Sarvam's socket is flushed from
    Pipecat's own `VADUserStoppedSpeakingFrame` instead (`stt.py:401-413`). These are two
    mutually exclusive architectures and this is the deliberate half.
    """
    # `language=None` is a REAL value on this settings class, not an omission: "set
    # unsupported fields to None (e.g. language=None if the service auto-detects
    # language)" (`pipecat/services/settings.py:381-383`). That is exactly what
    # `ModelConfig.stt_autodetect` asks for, so it is passed through rather than dropped.
    settings = SarvamSTTService.Settings(
        model=config.models.stt_model or STT_MODEL,
        language=_language(config),
    )
    return SarvamSTTService(
        api_key=credentials.sarvam_api_key,
        settings=settings,
        sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
    )


def _build_tts(config: SessionConfig, credentials: VendorCredentials) -> FrameProcessor:
    """Sarvam TTS today; Cartesia on the Studio tier; Gnani where an agent names it.

    ⚠ **`SarvamTTSSpeakerV3` (`pipecat/services/sarvam/tts.py:101`) IS A CLOSED `StrEnum`
    OF 25 SPEAKER NAMES.** That is the structural fact behind D-593 and it is recorded here
    rather than acted on: a vendor whose speaker set is an enum has no place to put a voice
    cloned from a client's own recording, so Sarvam cannot serve the Clear tier's cloned
    voices however good its Telugu is. Gnani replaces Sarvam on that tier and Cartesia
    stays on Studio. Nothing in this function implements that — `GnaniTTSService` is §5,
    staged behind Gnani's unanswered rate-limit question, and building it now would be
    building for nothing.

    ⚠ **THE GNANI HALF OF THAT PARAGRAPH IS SUPERSEDED BY D-618 AND THE LEG IS BUILT**
    (`voice_worker/gnani_tts.py`). Two things changed. The rate limit is not an "unanswered
    question" with a known number — the current vendor documentation does not state a
    60 req/min cap at all, so what §5 gated on could not be answered as asked; it is
    re-stated as UNKNOWN. And Gnani ship an official Pipecat plugin, so the work was a
    subclass filling three measured gaps rather than a protocol implementation.

    **WHAT DID NOT CHANGE IS WHO SPEAKS THE CLEAR TIER.** `bulbul:v3` is still what an
    agent that chose nothing runs on, and nothing here flips a tier: §6 step 9 gates that
    on an ATTESTED PRICE, and Gnani publish none. A Gnani call happens only where an
    agent's own `ModelConfig.tts_provider` says so, and a Gnani voice is not offerable
    until its price is attested (`agents/gnani_voices.py`).

    `bulbul:v2` is not offered: Pipecat's own docstring says "Sarvam's API rejects it"
    (`tts.py:648`), which agrees with CLAUDE.md's correction that v2 is WITHDRAWN rather
    than a value tier.
    """
    provider = (config.models.tts_provider or "sarvam").lower()
    # A settings field left ABSENT keeps the vendor class's own default; a field set to
    # `None` overwrites it (these are delta dataclasses whose unset marker is `NOT_GIVEN`,
    # `pipecat/services/settings.py`). `tts_voice` is nullable on `ModelConfig`, so it is
    # only passed when we actually have one — sending `voice=None` would blank Sarvam's
    # "shubh" default and leave the agent with no speaker at all.
    voice = config.models.tts_voice
    if provider == "cartesia":
        if credentials.cartesia_api_key is None:
            raise ValueError("tts_provider is 'cartesia' but no Cartesia key was supplied")
        # Imported here, not at module scope: the Studio tier is a minority of calls and
        # this keeps a websocket client out of the import graph of every Sarvam call.
        from pipecat.services.cartesia.tts import CartesiaTTSService

        cartesia_settings = CartesiaTTSService.Settings(language=_language(config))
        if config.models.tts_model is not None:
            cartesia_settings.model = config.models.tts_model
        if voice is not None:
            cartesia_settings.voice = voice
        return CartesiaTTSService(
            api_key=credentials.cartesia_api_key,
            settings=cartesia_settings,
            sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        )
    if provider == "gnani":
        if credentials.gnani_api_key is None:
            raise ValueError(
                "tts_provider is 'gnani' but this container has no Gnani key: set "
                "GNANI_API_KEY in the Pipecat Cloud secret set"
            )
        if voice is None:
            # The vendor references a voice BY NAME and has no default that serves this
            # product: the plugin would fall back to `Pranav`, an Indian-English voice on
            # `timbre-v2.0`. A Telugu call must not silently become an English one.
            raise ValueError("tts_provider is 'gnani' but the agent names no voice")
        if config.language is None:
            # `timbre-v2.5` requires `language`, and the vendor says a voice used outside
            # the locale it is optimised for "may reduce quality". Neither is a default we
            # are entitled to invent.
            raise ValueError("tts_provider is 'gnani' but the agent names no language")
        # Imported here, not at module scope, for the reason the Cartesia branch gives:
        # this keeps a second vendor websocket client out of the import graph of every
        # Sarvam call. The model is the module's constant, never `config.models.tts_model`
        # blindly — see `gnani_tts.GNANI_TTS_MODEL` for why the vendor default is wrong.
        from voice_worker.gnani_tts import build_gnani_tts

        return build_gnani_tts(
            api_key=credentials.gnani_api_key,
            voice=voice,
            language=config.language,
            sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        )
    if provider != "sarvam":
        raise ValueError(f"unsupported tts_provider {provider!r}")
    sarvam_settings = SarvamTTSService.Settings(
        model=config.models.tts_model or TTS_MODEL,
        language=_language(config),
    )
    if voice is not None:
        sarvam_settings.voice = voice
    return SarvamTTSService(
        api_key=credentials.sarvam_api_key,
        settings=sarvam_settings,
        sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
    )


def _build_llm(config: SessionConfig, credentials: VendorCredentials) -> FrameProcessor:
    """The BYOK LLM leg, on whichever of our three declared providers the config names.

    **NO `temperature` IS SENT, AND THAT IS WHY THERE IS NO TRAP LAYER HERE.** Pipecat has
    no equivalent of `LlmModelSpec.traps`; `temperature` simply defaults to `NOT_GIVEN`
    (`pipecat/services/settings.py:337`) and an unset field is not serialised. The GPT-5
    trap that `engine/bolna.py::_llm_trap_settings` exists for was caused by that adapter
    sending `temperature: 0.1` UNCONDITIONALLY — a thing this leg does not do. If a future
    change wants a temperature, `ModelConfig.llm_traps` is already on `SessionConfig` and
    that is where the decision belongs.

    **THE `google` LEG GOES OVER THE OPENAI-COMPAT SURFACE, NOT `google-genai`, AND THAT IS
    A CHOICE WITH TWO GROUNDS RATHER THAN A WORKAROUND.**

    Pipecat's own Gemini service is unreachable here: `import pipecat.services.google.llm`
    raises `ImportError("Missing module: No module named 'google.genai'")` (measured in this
    venv, 13 Sep 2026), because `apps/voice-worker/pyproject.toml` declares no `google`
    extra. The obvious repair — add the extra — is the WRONG one twice over. It would pull
    `google-cloud-speech` and `google-cloud-texttospeech` alongside `google-genai` for a leg
    that wants none of them, and, more importantly, it would be a SECOND way for this
    codebase to talk to Gemini. `copilot/service._google_leg` and `workers/document_ocr.py`
    already reach it over `google_openai_compat_base_url()`, the same OpenAI-shaped wire
    `workers/chat.py` speaks to Azure — so the leg below is the way this repo already has,
    not a new one beside it.

    **D-478 SCOPED THAT BUILDER TO "THE DASHBOARD LEG ONLY", AND THE REASON IT GAVE IS GONE.**
    Its ground was that the in-call Google leg talked the NATIVE `:generateContent` protocol
    through Bolna's own `genai.Client` and read no base URL of ours. This migration deletes
    Bolna from the in-call path, so there is no longer a native in-call leg for the
    restriction to protect — the worker IS the engine, and the only Gemini endpoint this
    product may address is the one that builder emits. The scope note on
    `calevate_shared.engine.google_openai_compat_base_url` is stale as a consequence and is
    the follow-up this change owes.

    **THE WIRE SHAPE IS VERIFIED-LIVE, THE SEMANTICS ARE NOT, AND THE DIFFERENCE MATTERS.**
    Probed from this container on 13 Sep 2026 against
    `POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` with
    `Authorization: Bearer INVALID_KEY_PROBE`, using the two-request discrimination
    `copilot/service.py` documents (the body parser runs BEFORE the credential, so an
    accepted field fails on the key and an unknown one is named):

        {... "zzz_not_a_param": true}                  -> 400 Unknown name "zzz_not_a_param"
        {... "stream": true}                           -> 400 Please pass a valid API key
        {... "stream": true, "tools": [...],
             "tool_choice": "auto"}                    -> 400 Please pass a valid API key

    So the endpoint ACCEPTS streaming and tool calling in the body — which upgrades the
    `tools`/`tool_choice` claim in that builder's docstring from SECONDARY (web search) to
    VERIFIED-LIVE, and adds `stream`. It does NOT prove streamed tool-calling behaves
    correctly end to end; a body the parser accepts is not a semantics guarantee, and
    nothing here has run a real turn. That remains to be measured on the first live call.
    """
    provider = config.models.llm_provider or "azure_openai"
    model = config.models.llm_model
    if model is None:
        raise ValueError("SessionConfig.models.llm_model is required: this worker IS the engine")
    # NOT a field of our own: `ModelConfig` already carries `llm_base_url` AND already
    # refuses an `azure_openai` leg without one (its own validator raises
    # "llm_provider 'azure_openai' requires llm_base_url" — measured, 13 Sep 2026). A
    # second copy on `SessionConfig` would be a second place for the endpoint a third party
    # sends a client's caller's words to, which is the one value D-127's argument turns on.
    base_url = config.models.llm_base_url
    if provider == "azure_openai":
        if base_url is None:  # pragma: no cover - ModelConfig's validator gets here first
            raise ValueError("the azure_openai leg needs llm_base_url (azure_openai_base_url())")
        return AzureLLMService(
            endpoint=base_url,
            api_key=credentials.llm_api_key,
            # On Azure this is the DEPLOYMENT id an operator chose, never a model name —
            # `ModelConfig.llm_model` says so at the field.
            settings=AzureLLMService.Settings(model=model),
            function_call_timeout_secs=FUNCTION_CALL_TIMEOUT_SECS,
        )
    if provider == "openai":
        return OpenAILLMService(
            api_key=credentials.llm_api_key,
            base_url=base_url,
            settings=OpenAILLMService.Settings(model=model),
            function_call_timeout_secs=FUNCTION_CALL_TIMEOUT_SECS,
        )
    if provider == "google":
        # NO `base_url` FROM CONFIG, and that asymmetry with the two legs above is the
        # point. `google_openai_compat_base_url()` takes no argument on purpose — there is
        # exactly one endpoint this product may address for Gemini, and a parameter would
        # be a caller's chance to vary the one value that decides where a caller's words
        # are sent. Azure's endpoint is per-resource and therefore config; Google's is not.
        return OpenAILLMService(
            api_key=credentials.llm_api_key,
            base_url=google_openai_compat_base_url(),
            settings=OpenAILLMService.Settings(model=model),
            function_call_timeout_secs=FUNCTION_CALL_TIMEOUT_SECS,
        )
    raise ValueError(f"unknown llm_provider {provider!r}")


def build_vendor_legs(config: SessionConfig, credentials: VendorCredentials) -> VendorLegs:
    """Construct the three real vendor services. No network happens here."""
    install_vendor_log_guard()
    return VendorLegs(
        stt=_build_stt(config, credentials),
        llm=_build_llm(config, credentials),
        tts=_build_tts(config, credentials),
    )


# ---------------------------------------------------------------------------------------
# The in-call knowledge base, as a tool the model may call. §6 step 11, §9.1 step 2.
# ---------------------------------------------------------------------------------------

#: The tool's name as the model sees it. A VERB and its object, because that is what the
#: model is choosing between — `knowledge_base` alone reads like a place rather than an
#: action, and every other name in the turn ("end the call", "book a slot") is a verb.
KNOWLEDGE_TOOL_NAME: Final[str] = "search_knowledge_base"

#: The tool's one parameter.
KNOWLEDGE_TOOL_QUESTION_PARAM: Final[str] = "question"

#: **THIS STRING IS A PROMPT, NOT A COMMENT.** It is the only instruction the model gets
#: about how to use the index, it is read on every turn, and the sentence that matters most
#: is the one about English.
#:
#: **WHY ENGLISH IS AN INSTRUCTION AND NOT A TRANSLATION HOP.** The index is English-only
#: (§9.2), and that is measured rather than assumed: word-matching a Tenglish query against
#: a Telugu-script corpus scored **0.042** recall@1 and against an English one **0.625**
#: (`docs/evidence/telugu-embedding-quality.md` §4, n=24). So a query that arrives in Telugu
#: script retrieves approximately nothing. The cheap repair everybody reaches for — a
#: translation call before the search — is rejected: it is a second model on a 100 ms
#: budget for a thing the model in the loop is already doing, since writing an English
#: query is part of its own reading of the turn (§9.1 step 2). The model answers the caller
#: in the caller's language; only the QUERY is English.
#:
#: The rest of the string is there because the failure it prevents is a confident lie: a
#: model that does not know `temporarily_unavailable` from `not_found` will tell a caller
#: "we don't offer that" when the truth is "I could not check". The payload carries the
#: distinction (`knowledge_tool_payload`) and this tells the model to honour it.
KNOWLEDGE_TOOL_DESCRIPTION: Final[str] = (
    "Search this business's published knowledge base for facts about its services, "
    "prices, timings, location, policies and offers. Call this before answering any "
    "question of fact about the business; never answer one from memory. "
    "WRITE THE QUESTION IN ENGLISH even when the caller spoke Telugu, Hindi or a mix — "
    "the index is English-only and a non-English query will find nothing. "
    "Reply to the caller in the language the caller used. "
    "The result carries an 'outcome' you must respect: 'found' means answer only from the "
    "passages given; 'ambiguous' means two different documents match, so ask the caller "
    "one short clarifying question instead of guessing; 'not_found' means this business "
    "has published nothing about it, so say you do not have that information and offer to "
    "take a message; 'temporarily_unavailable' and 'no_knowledge_base' mean you could not "
    "check at all, so say you cannot look it up right now — never say the business has no "
    "answer when you were unable to look."
)

#: The word the payload carries when this agent has no pack at all, as distinct from a pack
#: that failed to load. It sits BESIDE `RetrievalOutcome`'s four rather than inside them,
#: and the extra word is deliberate: `RetrievalOutcome` is the contract of a SEARCH, and no
#: search ran here. Folding it into `not_found` would tell the model the business has
#: published nothing on the subject, which is a claim about the client's knowledge base
#: made on the strength of it not existing; folding it into `temporarily_unavailable` would
#: promise the caller a later answer that no retry will ever produce.
KNOWLEDGE_OUTCOME_NO_PACK: Final[str] = "no_knowledge_base"

#: What the model should DO about each outcome, carried in the payload beside the outcome
#: word. Duplicating the tool description's guidance on purpose: the description is read
#: once when tools are advertised, the payload is read in the same breath as the result,
#: and the failure being guarded against (an agent that invents an answer after a failed
#: lookup) is a live compliance problem rather than a cosmetic one.
_KNOWLEDGE_GUIDANCE: Final[dict[str, str]] = {
    "found": (
        "Answer using only these passages. Do not add facts that are not in them. "
        "Reply in the caller's language."
    ),
    "ambiguous": (
        "Two different published documents match this question about equally. Do not pick "
        "one. Ask the caller one short question that tells them apart."
    ),
    "not_found": (
        "This business has published nothing about this. Say you do not have that "
        "information, and offer to take a message or pass it to a person."
    ),
    "temporarily_unavailable": (
        "The knowledge base could not be consulted for this call. Say you are unable to "
        "check that right now. Do NOT say the business has no answer — you did not look."
    ),
    KNOWLEDGE_OUTCOME_NO_PACK: (
        "This agent has no published knowledge base, so there is nothing to search. Say "
        "you do not have that information and offer to take a message or pass it to a "
        "person. Do NOT claim the business does not offer the thing asked about."
    ),
}


async def knowledge_tool_payload(
    knowledge: SessionKnowledge | None,
    question: str,
    *,
    pack_configured: bool,
    k: int = DEFAULT_TOP_K,
    embedder: QueryEmbedder | None = None,
) -> dict[str, Any]:
    """What the model gets back from one lookup: the outcome word, what to do, the passages.

    **THE OUTCOME WORD IS THE PAYLOAD'S REASON FOR EXISTING.** A bare list of passages
    collapses four different silences into one — and an empty list, to a model, reads as
    "the business has nothing on this", which is a statement about a client's business that
    we would be making on the strength of a failed S3 fetch. `SessionKnowledge.search`
    already distinguishes them and never raises (its own docstring), so the distinction
    exists; this function's job is to carry it rather than flatten it.

    **`pack_configured` IS WHY THERE ARE FIVE WORDS AND NOT FOUR.** `knowledge is None` has
    two causes that must not be confused: this agent published no knowledge base (ordinary,
    permanent, `no_knowledge_base`), or the entrypoint was supposed to load one and did not
    (a wiring defect, and from the caller's seat indistinguishable from an outage, so
    `temporarily_unavailable`). `SessionConfig.knowledge_pack_sha256` is what tells them
    apart, and `assemble_call` logs the second case for an operator.

    **NOTHING HERE LOGS (HARD RULE 6).** The question, the passages and the glosses are all
    conversation content. The one log line on this path is `knowledge._log_answer`, which
    emits ids, the outcome word, a count and `elapsed_ms` and nothing else; a second log
    call here would be a second author of the rule's compliance. Pipecat's own
    `"Calling function [...] with arguments {...}"` DOES carry the question, and is
    inaudible for the same reason every vendor line is: it is DEBUG, and
    `vendor_logging.install_vendor_log_guard` floors the vendor at INFO
    (`pipecat/services/llm_service.py:1616`, read 14 Sep 2026).

    **IT IS ASYNC BECAUSE THE SECOND ARM IS**, and `knowledge.answer` is the only thing it
    calls — never `knowledge.search`, which is the lexical half and would silently drop the
    dense one. `embedder=None` is the complete off state: same payload, same words, no
    request and no spend.
    """
    if knowledge is None:
        outcome = "temporarily_unavailable" if pack_configured else KNOWLEDGE_OUTCOME_NO_PACK
        return {"outcome": outcome, "guidance": _KNOWLEDGE_GUIDANCE[outcome], "passages": []}

    answer = await knowledge.answer(question, k=k, embedder=embedder)
    return {
        "outcome": answer.outcome,
        "guidance": _KNOWLEDGE_GUIDANCE[answer.outcome],
        # The entry's own published words, never the gloss — `SessionKnowledge._passage`
        # makes that choice and this just carries it. `document_version` travels because a
        # pack is frozen at publish, so an answer can name the exact revision it quoted,
        # which is what a dispute asks for.
        "passages": [
            {
                "text": passage.text,
                "source_id": str(passage.provenance.source_id),
                "document_version": passage.provenance.document_version,
            }
            for passage in answer.passages
        ],
    }


def build_knowledge_tool(
    knowledge: SessionKnowledge | None,
    *,
    pack_configured: bool,
    k: int = DEFAULT_TOP_K,
    embedder: QueryEmbedder | None = None,
) -> FunctionSchema:
    """The search, as a tool the LLM may call. ALWAYS built, even with no pack to search.

    **A `FunctionSchema` CARRYING ITS OWN `handler`, WHICH IS THE 1.10.0 WAY AND NOT THE
    ONE MOST EXAMPLES SHOW.** Three registration paths exist in the installed package and
    two are wrong here:

    - `LLMService.register_function(name, handler)` (`pipecat/services/llm_service.py:917`)
      needs a concrete `LLMService`, and `VendorLegs.llm` is typed `FrameProcessor` on
      purpose so a test can put a stub in the slot. Reaching through that type to register
      would undo the seam the dataclass exists for.
    - `register_direct_function` (`llm_service.py:1024`) is DEPRECATED since 1.4.0 and its
      own docstring says to list tools in `LLMContext(tools=[...])` instead.
    - A schema with a handler is registered automatically for any context that advertises
      it (`llm_service.py:1256-1265`), so ONE object both advertises the tool to the
      provider and carries what runs — there is no second place to forget.

    **WHY IT IS ADVERTISED EVEN WHEN THERE IS NOTHING TO SEARCH.** A tool that appears only
    when a pack loaded makes the outage invisible to the model: with no tool, it answers
    from the prompt and its own priors, which on a phone call is an invented fact told to a
    caller in a client's name. Advertised-and-honest is the whole of hard rule 5's posture
    applied to the client's facts, and it is why `load_session_knowledge` returns a STATE
    rather than raising.

    `k` is fixed at assembly rather than exposed as a parameter: how many passages an
    answer rests on is ours to decide, and a model asking for twenty would be a model
    choosing its own context budget.

    **`embedder` IS FIXED HERE FOR THE SAME REASON AND ONE STRONGER ONE.** It decides whether
    a turn may spend money, which is never a model's choice to make in a tool argument. It is
    bound at assembly, from the bootstrap, and the handler cannot see past it.

    **THE DENSE ARM IS BOUNDED BY `FUNCTION_CALL_TIMEOUT_SECS` FROM THE OUTSIDE AS WELL AS BY
    `embedding.EMBED_BUDGET_S` FROM THE INSIDE, AND BOTH BOUNDS ARE REAL.** The inner one is
    the smaller (1.2 s against 2.0 s) so that a hung encoder still returns the honest
    `temporarily_unavailable` INSIDE the tool call; the outer one is what stops a defective
    embedder that ignores its own budget from extending a turn indefinitely
    (`llm_service.py:301-303` — the model then sees "the function failed and returned no
    result", which is worse than the word but is still bounded).
    """

    async def _search(params: FunctionCallParams) -> None:
        # Absent, non-string or blank all become "": `SessionKnowledge.search` handles an
        # empty question (no query forms -> `not_found`) and a `TypeError` raised inside a
        # tool handler would reach the model as "the function failed and returned no
        # result" (`llm_service.py:301-303`) — strictly less useful than the honest word.
        raw = params.arguments.get(KNOWLEDGE_TOOL_QUESTION_PARAM)
        question = raw if isinstance(raw, str) else ""
        await params.result_callback(
            await knowledge_tool_payload(
                knowledge,
                question,
                pack_configured=pack_configured,
                k=k,
                embedder=embedder,
            )
        )

    return FunctionSchema(
        name=KNOWLEDGE_TOOL_NAME,
        description=KNOWLEDGE_TOOL_DESCRIPTION,
        properties={
            KNOWLEDGE_TOOL_QUESTION_PARAM: {
                "type": "string",
                "description": (
                    "The caller's question, rewritten in ENGLISH as a short search query. "
                    "Keep the specific words (service, product, document or place names); "
                    "drop greetings and filler."
                ),
            }
        },
        required=[KNOWLEDGE_TOOL_QUESTION_PARAM],
        handler=_search,
    )


# ---------------------------------------------------------------------------------------
# Assembly.
# ---------------------------------------------------------------------------------------


def build_user_aggregator_params(
    stop_secs: float = SMART_TURN_STOP_SECS,
) -> LLMUserAggregatorParams:
    """VAD and turn detection, both of which live HERE and not where you would look for them.

    ⚠ **`TransportParams` HAS NO `vad_analyzer` AND NO `turn_analyzer` FIELD IN 1.10.0** —
    verified by reading the whole model (`pipecat/transports/base_transport.py:25-93`), not
    by trying it. The obvious place is the wrong place; the analyzer goes on the user
    context aggregator (`LLMUserAggregatorParams.vad_analyzer`,
    `pipecat/processors/aggregators/llm_response_universal.py:178`).

    **THE STOP STRATEGY IS SPELLED OUT EVEN THOUGH IT IS THE DEFAULT.**
    `default_user_turn_stop_strategies()` already returns a
    `TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())` and
    `UserTurnStrategies.__post_init__` installs it when none is given
    (`pipecat/turns/user_turn_strategies.py:45-53`, `:76-80`). Writing it out is what lets
    `SmartTurnParams(stop_secs=...)` be OURS — the default constructs the analyzer with
    `stop_secs=3` and gives no other way in. A pipeline that inherited it would be a
    pipeline whose most important number was chosen by a library.

    `wait_for_transcript` is left at its default `True`: the turn ends when the analyzer
    says COMPLETE **and** a finalized transcript has landed (or the STT's own P99 elapses).
    Setting it `False` takes transcripts off the latency path, which is tempting on a
    650 ms budget — rejected because it would let the LLM answer a turn whose words we do
    not have yet, and Sarvam's `saaras:v4` emits no interim transcripts to fall back on.
    """
    return LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(sample_rate=TELEPHONY_SAMPLE_RATE_HZ),
        user_turn_strategies=UserTurnStrategies(
            stop=[
                TurnAnalyzerUserTurnStopStrategy(
                    turn_analyzer=LocalSmartTurnAnalyzerV3(
                        params=SmartTurnParams(stop_secs=stop_secs),
                    ),
                )
            ],
        ),
    )


@dataclass(slots=True)
class AssembledCall:
    """Everything one call needs, assembled and not yet running."""

    worker: PipelineWorker
    pipeline: Pipeline
    context: LLMContext
    aggregators: LLMContextAggregatorPair
    boundary: NormalizedEventBoundary
    #: What the worker attests it loaded (§1.1). Recomputed here, never echoed.
    observed_prompt_sha256: str
    #: Whether the prompt this process holds is the one the config version names. `attest.py`
    #: reports the disagreement; it is not this module's job to refuse on it.
    prompt_matches_config_version: bool = field(default=False)
    #: Carried from `SessionConfig` so `start_conversation` reads one object.
    greet_first: bool = field(default=True)
    #: The pack this call answers out of, or `None` when there is none to answer out of.
    #: Held so an entrypoint can log `knowledge.unavailable_reason` without re-deriving it,
    #: and so a test can assert which session the advertised tool closed over.
    knowledge: SessionKnowledge | None = field(default=None)

    async def start_conversation(self) -> bool:
        """Make the agent speak first, if this agent does.

        **CALLED FROM THE TRANSPORT'S CONNECT EVENT, WHICH IS WHY IT IS A METHOD AND NOT
        SOMETHING `assemble_call` WIRES.** The shipped pattern adds a developer message and
        queues an `LLMRunFrame` from `on_client_connected`
        (`examples/voice/voice-cartesia.py:112-119`), and that event belongs to a real
        transport — `FastAPIWebsocketTransport` registers exactly three handlers
        (`pipecat/transports/websocket/fastapi.py:674-678`). Registering it here would make
        `assemble_call` fail on any transport without that event, which includes every fake,
        so the entrypoint (step 6, with the carrier) does the one-line registration and this
        method holds the decision.

        Returns whether it spoke, so a caller can log the branch without re-reading config.
        """
        if not self.greet_first:
            return False
        # A DEVELOPER message, not a scripted line: what the agent opens with is the
        # agent's prompt (and, per hard rule 5 / D-163, its disclosure toggles), composed
        # on the control-plane side. A greeting hardcoded here would be a second author of
        # the first sentence of every call.
        self.context.add_message(
            {"role": "developer", "content": "Greet the caller as your instructions direct."}
        )
        await self.worker.queue_frames([LLMRunFrame()])
        return True


def assemble_call(
    *,
    config: SessionConfig,
    legs: VendorLegs,
    transport: BaseTransport,
    sink: NormalizedEventSink,
    knowledge: SessionKnowledge | None = None,
    embedder: QueryEmbedder | None = None,
    caller_memory: Sequence[str] = (),
    observers: Sequence[BaseObserver] | None = None,
    stop_secs: float = SMART_TURN_STOP_SECS,
) -> AssembledCall:
    """Assemble the §4 pipeline for one call.

    `transport` is an argument rather than something built here because the Plivo leg is
    step 6 and gated on an account in the India data region — and because a pipeline that
    can only be exercised with a carrier is a pipeline nobody can test (§6 step 4 asks for
    exactly this: a local run against a fake transport).

    **`knowledge` IS AN ARGUMENT FOR THE SAME REASON `transport` IS, AND THAT IS WHY THIS
    FUNCTION STAYED SYNCHRONOUS.** `load_session_knowledge` is the one awaitable on this
    path (it reads object storage once), and the obvious move — make the assembler `async`
    and let it load — would buy nothing and cost the property that makes step 4 testable:
    a synchronous assembler can be exercised with no network, no event loop and no object
    store, which is exactly what `transport` being an argument bought and what a carrier-
    free local run needs. The entrypoint — `session.open_session` — awaits the load WHILE
    THE PHONE IS RINGING, wall clock nobody is waiting on
    (`load_session_knowledge`'s own docstring), and hands the result in. `None` is a
    complete state, not an omission: see `build_knowledge_tool`.

    **`caller_memory` IS AN ARGUMENT FOR `knowledge`'s REASON, AND IT FILLS THE PROMPT'S ONE
    PER-SESSION SLOT.** `session.open_session` awaits the read while the phone rings and
    hands the facts in. The default `()` is a first-time caller, an agent that does not
    remember its callers, and every test — one state, rendered one way, because that is
    exactly what `CALLER_MEMORY_GUIDANCE` already tells the model an empty block means.

    **`embedder` IS AN ARGUMENT FOR A THIRD REASON ON TOP OF THOSE TWO: IT IS THE SWITCH
    THAT DECIDES WHETHER A TURN MAY SPEND MONEY.** `None` — the default, and what every test
    and every local run gets — means the dense arm never runs and nothing is bought. A
    bootstrap supplies one only where hard rule 7's pre-flight has been answered (the same
    question `apps/api/kb/pack_vectors.pack_embedding_is_billable()` asks, of the same model
    id), which is a question this container cannot ask for itself because it deliberately
    does not carry the billing module — `voice_worker/embedding.py`'s docstring has that
    argument and the structural reason the arm is unreachable without it anyway.
    """
    install_vendor_log_guard()

    pack_configured = config.knowledge_pack_sha256 is not None
    if pack_configured and knowledge is None:
        # A WIRING defect, not a runtime one: this agent published a pack and the entrypoint
        # did not load it. It is logged here, once, rather than on every lookup — and the
        # tool still answers, as `temporarily_unavailable`, because from the caller's seat
        # an unloaded pack and an unreachable one are the same silence. The digest is an id
        # (hard rule 6) and is logged so an operator can find the object.
        logger.error(
            "knowledge pack configured but not loaded",
            call_id=config.call_id,
            tenant_id=str(config.tenant_id),
            agent_id=str(config.agent_id),
            digest=config.knowledge_pack_sha256,
        )

    # THE SLOT IS FILLED HERE AND THE ATTESTED DIGEST IS STILL TAKEN OVER THE UNFILLED
    # STRING, which is `agents/config_versions.py`'s documented in/out list rather than a
    # convenience: the composed prompt is agent state minted once at publish, and
    # `caller_memory` is explicitly OUT of `prompt_sha256` because it is "facts about ONE
    # caller, assembled per session — in the digest, every attestation would mismatch". So
    # `config.system_prompt` stays the artefact this worker attests, and this is the
    # per-call rendering of it that the model actually reads.
    #
    # IT RUNS UNCONDITIONALLY, INCLUDING WITH NO FACTS, AND THAT IS THE DEFECT IT CLOSES.
    # `_caller_memory_section` leaves the literal `{caller_memory}` token in the prompt for
    # an ENGINE to substitute; on `owned_runtime` there is no engine, so until this line
    # every memory-enabled agent on this worker was handed a placeholder as part of its
    # instructions and recalled nothing. A prompt with no slot comes back unchanged —
    # nothing here APPENDS a section, because an agent whose client never switched memory on
    # has nothing to fill and must not acquire a memory section from a caller.
    spoken_prompt = fill_caller_memory_slot(config.system_prompt, caller_memory)

    context = LLMContext(
        messages=[{"role": "system", "content": spoken_prompt}],
        # ONE tool, always advertised. `LLMContext` normalises a plain list into a
        # `ToolsSchema` itself (`pipecat/processors/aggregators/llm_context.py:493-499`),
        # and the LLM service registers a schema's own handler when it sees the context
        # (`pipecat/services/llm_service.py:1256-1265`) — so nothing else has to be wired.
        tools=[build_knowledge_tool(knowledge, pack_configured=pack_configured, embedder=embedder)],
    )
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=build_user_aggregator_params(stop_secs),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            legs.stt,
            aggregators.user(),
            legs.llm,
            legs.tts,
            transport.output(),
            # AFTER the output, per the shipped ordering — placing it before would record
            # assistant text that was never spoken (`examples/voice/voice-cartesia.py:93-94`).
            aggregators.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        # **AN ARGUMENT FOR `transport`'s AND `sink`'s REASON, AND IT IS WHAT THE METER
        # RIDES IN ON.** `PipelineParams` above turns the usage metrics ON, which is this
        # module's whole obligation to §1.3 — but a metric nobody subscribes to is a metric
        # nobody meters, and `meter.CallMeter.attach` takes a `ServiceMetricsObserver` that
        # has to be registered HERE because `observers` is a constructor argument of
        # `PipelineWorker` (`pipecat/pipeline/worker.py:310`) and there is no adding one
        # afterwards. Building the observer inside this function was the alternative and is
        # worse: it would put the meter — which owns a rate card and refuses on money — into
        # the one module whose property is that it runs with no database and no rates.
        # `runtime.py` constructs both and hands them in.
        observers=list(observers) if observers else None,
        params=PipelineParams(
            # Both default to False (`pipecat/pipeline/worker.py:198-199`). Hard rule 7
            # needs a real cost per usage_event and §1.3 meters five legs independently;
            # with these off there is nothing to meter. `meter.py` is the consumer.
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
            audio_out_sample_rate=TELEPHONY_SAMPLE_RATE_HZ,
        ),
        # Default is CONTINUE, which keeps a pipeline alive after (say) a TTS key is
        # rejected — i.e. a live call with a permanently silent agent. END ends the call so
        # the caller hears a disconnect rather than nothing, and the shipped telephony
        # example makes the same choice (`voice-cartesia.py:98-104`).
        processor_unusable_policy=ProcessorUnusablePolicy.END,
        # Default 300 s cancels a silent call AND the whole runner with it
        # (`worker.py:356-368`). A phone call has its own end; we do not want a five-minute
        # timer deciding it, and under one-worker-per-call the runner cancellation would be
        # a second, invisible way for a session to die.
        idle_timeout_secs=None,
        conversation_id=config.call_id,
    )

    boundary = NormalizedEventBoundary(config=config, sink=sink)
    boundary.attach(worker=worker, aggregators=aggregators)

    observed = recompute_prompt_sha256(config.system_prompt)
    return AssembledCall(
        worker=worker,
        pipeline=pipeline,
        context=context,
        aggregators=aggregators,
        boundary=boundary,
        observed_prompt_sha256=observed,
        prompt_matches_config_version=observed == config.prompt_sha256,
        greet_first=config.greet_first,
        knowledge=knowledge,
    )


__all__ = [
    "ENGINE_NAME",
    "FUNCTION_CALL_TIMEOUT_SECS",
    "KNOWLEDGE_OUTCOME_NO_PACK",
    "KNOWLEDGE_TOOL_DESCRIPTION",
    "KNOWLEDGE_TOOL_NAME",
    "KNOWLEDGE_TOOL_QUESTION_PARAM",
    "SMART_TURN_STOP_SECS",
    "STT_MODEL",
    "TELEPHONY_SAMPLE_RATE_HZ",
    "TTS_MODEL",
    "AssembledCall",
    "NormalizedEventBoundary",
    "NormalizedEventSink",
    "SessionConfig",
    "VendorCredentials",
    "VendorLegs",
    "assemble_call",
    "build_knowledge_tool",
    "build_user_aggregator_params",
    "build_vendor_legs",
    "knowledge_tool_payload",
    "recompute_prompt_sha256",
]
