# Pipecat API surface reference — for the Calevate adapter spec

**Evidence class: VERIFIED-VENDOR-SOURCE (read this session).**
Sole source: the local clone at `/home/user/pipecat-ai/pipecat`, stated by the founder to be
byte-identical to published `pipecat-ai==1.10.0`. Clone HEAD at time of reading:
`f67c18a Merge pull request #5711 from pipecat-ai/changelog-1.10.0`.
Read date: 13 Sep 2026.

**No network was used.** `docs.pipecat.ai` is egress-blocked from this container; every claim
below is cited to `file:line` inside the clone. Nothing here is inferred from the published
documentation site, from training data, or from any other Pipecat version.

All paths below are relative to `/home/user/pipecat-ai/pipecat/` unless stated otherwise.
Line numbers are from the files as they exist at the HEAD above.

Conventions used in this document:

- **AMBIGUOUS IN SOURCE** — the source admits more than one reading and the document says which.
- **NOT FOUND IN SOURCE** — a feature Calevate needs for which no implementation exists in the clone.
- Signatures are transcribed verbatim, including defaults. `*` marks the start of keyword-only
  parameters exactly as the source declares it.

Python floor: `requires-python = ">=3.11"` (`pyproject.toml:14`).

---

## 1. PIPELINE CONSTRUCTION

### 1.1 Naming — what 1.10.0 actually calls these

⚠ **`PipelineTask`, `PipelineTaskParams` and `PipelineRunner` are all DEPRECATED in 1.10.0 and
are scheduled for removal in 2.0.0.** Writing a new adapter against those names means writing
against something already marked for deletion. The live names are `PipelineWorker`,
`WorkerParams` and `WorkerRunner`.

| Deprecated name | Since | Removed in | Live replacement | Citation |
|---|---|---|---|---|
| `PipelineTask` | 1.3.0 | 2.0.0 | `pipecat.pipeline.worker.PipelineWorker` | `src/pipecat/pipeline/worker.py:1685-1698` |
| `PipelineTaskParams` | 1.3.0 | 2.0.0 | `pipecat.workers.base_worker.WorkerParams` | `src/pipecat/pipeline/worker.py:1701-1714` |
| `PipelineRunner` | 1.3.0 | 2.0.0 | `pipecat.workers.runner.WorkerRunner` | `src/pipecat/pipeline/runner.py:52-66` |
| module `pipecat.pipeline.task` | 1.3.0 | 2.0.0 | `pipecat.pipeline.worker` | `src/pipecat/pipeline/task.py:7-13` |
| module `pipecat.pipeline.runner` | — | — | `pipecat.workers.runner` (re-export shim) | `src/pipecat/pipeline/runner.py:36-44` |

`PipelineTask` is a bare `pass` subclass of `PipelineWorker` wrapped in `@deprecated`
(`src/pipecat/pipeline/worker.py:1690-1698`) — it adds nothing, so the constructor signature of
`PipelineWorker` below is also `PipelineTask`'s.

### 1.2 `Pipeline`

`src/pipecat/pipeline/pipeline.py:99-105`:

```python
class Pipeline(BasePipeline):
    def __init__(
        self,
        processors: Sequence[FrameProcessor],
        *,
        source: FrameProcessor | None = None,
        sink: FrameProcessor | None = None,
    )
```

Semantics:

- The pipeline always wraps the caller's list with an auto-created `PipelineSource` and
  `PipelineSink`: `self._processors = [self._source, *processors, self._sink]`
  (`pipeline.py:117-119`). Defaults are `PipelineSource(self.push_frame, name=f"{self}::Source")`
  and `PipelineSink(self.push_frame, name=f"{self}::Sink")`.
- Processors are linked in list order by `_link_processors()` (`pipeline.py:121`, `197-202`).
  **List order IS the frame order** — there is no graph, no explicit edges.
- `processors_with_metrics()` recurses into nested pipelines and returns every processor whose
  `can_generate_metrics()` is true (`pipeline.py:153-167`). This is what the metrics machinery
  enumerates.
- `setup()` / `cleanup()` fan out to every contained processor (`pipeline.py:169-181`).
- A `Pipeline` is itself a `FrameProcessor`, so pipelines nest (`pipeline.py:91`, `139-151`).

### 1.3 `PipelineParams`

`src/pipecat/pipeline/worker.py:172-204` — a **pydantic `BaseModel`**, not a dataclass,
with `model_config = ConfigDict(arbitrary_types_allowed=True)` (`worker.py:191`):

| Field | Type | Default | Citation |
|---|---|---|---|
| `audio_in_sample_rate` | `int` | `16000` | `worker.py:195` |
| `audio_out_sample_rate` | `int` | `24000` | `worker.py:196` |
| `enable_heartbeats` | `bool` | `False` | `worker.py:197` |
| `enable_metrics` | `bool` | `False` | `worker.py:198` |
| `enable_usage_metrics` | `bool` | `False` | `worker.py:199` |
| `heartbeats_period_secs` | `float` | `HEARTBEAT_SECS` = `1.0` | `worker.py:200`, `worker.py:97` |
| `heartbeats_monitor_secs` | `float` | `HEARTBEAT_MONITOR_SECS` = `10.0` | `worker.py:201`, `worker.py:98` |
| `report_only_initial_ttfb` | `bool` | `False` | `worker.py:202` |
| `send_initial_empty_metrics` | `bool` | `True` | `worker.py:203` |
| `start_metadata` | `dict[str, Any]` | `Field(default_factory=dict)` | `worker.py:204` |

**Note for Calevate:** `enable_metrics` and `enable_usage_metrics` are **`False` by default**.
Per-minute cost attribution (hard rule 7) requires both set to `True` explicitly. The docstring
states these params "are usually passed to all frame processors through StartFrame"
(`worker.py:176-178`).

Note also `audio_out_sample_rate` defaults to `24000`, which is *not* a telephony rate; on the
Plivo leg the serializer resamples to 8 kHz μ-law itself (§2.6).

### 1.4 `PipelineWorker` (a.k.a. deprecated `PipelineTask`)

`src/pipecat/pipeline/worker.py:282-319` — full signature, verbatim:

```python
class PipelineWorker(BaseWorker):
    def __init__(
        self,
        pipeline: BasePipeline,
        *,
        active: bool = True,
        additional_span_attributes: dict | None = None,
        app_resources: Any = None,
        bridged: tuple[str, ...] | None = None,
        cancel_on_idle_timeout: bool = True,
        cancel_runner_on_idle_timeout: bool = True,
        cancel_timeout_secs: float = CANCEL_TIMEOUT_SECS,       # 20.0
        check_dangling_tasks: bool = True,
        clock: BaseClock | None = None,
        conversation_id: str | None = None,
        enable_tracing: bool = False,
        enable_turn_tracking: bool = True,
        handle_flush_frame: bool | None = None,
        enable_rtvi: bool = True,
        exclude_frames: tuple[type[Frame], ...] | None = None,
        idle_timeout_frames: tuple[type[Frame], ...] = (
            BotSpeakingFrame,
            InterimTranscriptionFrame,
            TranscriptionFrame,
            UserSpeakingFrame,
            UserStartedSpeakingFrame,
        ),
        idle_timeout_secs: float | None = IDLE_TIMEOUT_SECS,    # 300
        name: str | None = None,
        observers: list[BaseObserver] | None = None,
        processor_unusable_policy: ProcessorUnusablePolicy = ProcessorUnusablePolicy.CONTINUE,
        params: PipelineParams | None = None,
        rtvi_processor: RTVIProcessor | None = None,
        rtvi_observer_params: RTVIObserverParams | None = None,
        setup_timeout_secs: float = SETUP_TIMEOUT_SECS,         # 20.0
        start_timeout_secs: float = START_TIMEOUT_SECS,         # 20.0
        task_manager: BaseTaskManager | None = None,
        tool_resources: Any = None,                             # deprecated 1.2.0 -> app_resources
    )
```

Module constants (`src/pipecat/pipeline/worker.py:97-109`):

```
HEARTBEAT_SECS            = 1.0    # :97
HEARTBEAT_MONITOR_SECS    = 10.0   # :98
FLUSH_PROGRESS_PERIOD_SECS= 1.0    # :101
IDLE_TIMEOUT_SECS         = 300    # :103
CANCEL_TIMEOUT_SECS       = 20.0   # :105
SETUP_TIMEOUT_SECS        = 20.0   # :107
START_TIMEOUT_SECS        = 20.0   # :109
```

Selected semantics that matter for a telephony deployment:

- `idle_timeout_secs=300` with `cancel_on_idle_timeout=True` **and**
  `cancel_runner_on_idle_timeout=True` (both default `True`) means a silent call is cancelled
  after 5 minutes *and* the whole `WorkerRunner` is cancelled with it — the worker "emits a
  `BusCancelMessage` so the runner broadcasts cancellation to every other root worker"
  (`worker.py:356-368`). Set `idle_timeout_secs=None` to disable idleness entirely
  (`worker.py:383-387`).
- Idleness is reset by any of the five `idle_timeout_frames` above, or a `StartFrame`
  (`IdleFrameObserver.on_push_frame`, `worker.py:134-147`).
- `processor_unusable_policy` — `ProcessorUnusablePolicy` is an `Enum` with `CONTINUE="continue"`,
  `END="end"`, `CANCEL="cancel"` (`worker.py:152-168`). A processor becomes unusable "through a
  permanent error category or through `FrameProcessor.push_error` with
  `force_treat_as_permanent=True`" (`worker.py:155-158`). Default is `CONTINUE`, i.e. a TTS whose
  API key was rejected keeps the pipeline alive and leaves the decision to an
  `on_pipeline_error` handler (`worker.py:388-394`).
- `enable_rtvi=True` by default: RTVI support is added to the pipeline automatically
  (`worker.py:373`).
- `setup_timeout_secs` / `start_timeout_secs` (both 20 s): "Processors connect while they are set
  up, so one that blocks connecting never lets the pipeline start, and the worker is torn down
  instead of waiting forever" (`worker.py:396-404`). A GnaniTTSService whose websocket connect
  hangs will therefore kill the call at 20 s, not hang forever.
- `app_resources` is passed by reference, exposed as `worker.app_resources`, and reaches tool
  handlers as `FunctionCallParams.app_resources`; the framework "never copies or clears this
  object" (`worker.py:328-338`). This is the supported way to hand a tenant id / DB handle to
  function-call handlers.

Public methods:

| Method | Signature | Citation |
|---|---|---|
| `has_finished` | `def has_finished(self) -> bool` | `worker.py:754-763` |
| `stop_when_done` | `async def stop_when_done(self)` — queues an `EndFrame` | `worker.py:765-772` |
| `end` | `async def end(self, *, reason: str \| None = None) -> None` — drains first | `worker.py:774-785` |
| `cancel` | `async def cancel(self, *, reason: str \| None = None)` | `worker.py:832-839` |
| `run` | `async def run(self, params: WorkerParams)` | `worker.py:841-884` |
| `queue_frame` | `async def queue_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM)` | `worker.py:886-901` |
| `queue_frames` | `async def queue_frames(self, frames: Iterable[Frame] \| AsyncIterable[Frame], direction: FrameDirection = FrameDirection.DOWNSTREAM)` | `worker.py:903-922` |
| `flush_pipeline` | `async def flush_pipeline(self, timeout: float = 5.0) -> bool` | `worker.py:924-970` |

`queue_frame` with `DOWNSTREAM` pushes at the head of the pipeline; with `UPSTREAM` it pushes from
the sink (`worker.py:897-901`).

`PipelineWorker` event handlers, registered with `@worker.event_handler("<name>")`
(`worker.py:215-279`; registration at `worker.py:599-607`):

| Event | Handler args | Meaning |
|---|---|---|
| `on_frame_reached_upstream` | `(worker, frame)` | upstream frame reached the source |
| `on_frame_reached_downstream` | `(worker, frame)` | downstream frame reached the sink |
| `on_heartbeat_timeout` | `(worker)` | fires **repeatedly** every `heartbeats_monitor_secs` while stalled |
| `on_idle_timeout` | `(worker)` | idle beyond threshold |
| `on_pipeline_started` | `(worker, frame)` | `StartFrame` |
| `on_pipeline_finished` | `(worker, frame)` | any terminal state: `StopFrame`, `EndFrame` or `CancelFrame` — inspect the frame |
| `on_pipeline_timeout` | `(worker, frame)` | a frame never reached the end: `StartFrame` (never started) or `CancelFrame` (did not drain). **There is no `EndFrame` case** |
| `on_pipeline_error` | `(worker, frame)` | `ErrorFrame`; read `frame.processor.is_usable` |
| `on_setup_timeout` | `(worker)` | listed in the example block at `worker.py:277-278`, registered at `worker.py:606` |

### 1.5 `WorkerRunner` (live) / `PipelineRunner` (deprecated alias)

`src/pipecat/workers/runner.py:109-120`:

```python
class WorkerRunner(BaseObject, BusSubscriber):
    def __init__(
        self,
        *,
        name: str | None = None,
        bus: WorkerBus | None = None,
        handle_sigint: bool = True,
        handle_sigterm: bool = False,
        force_gc: bool = False,
        check_dangling_tasks: bool = True,
        loop: asyncio.AbstractEventLoop | None = None,   # deprecated 1.5.0 -> task_manager
        task_manager: BaseTaskManager | None = None,
    )
```

- `handle_sigint` defaults `True`, `handle_sigterm` defaults **`False`** (`runner.py:114-115`).
  Under a container orchestrator that sends SIGTERM, pass `handle_sigterm=True` explicitly.
- Registration: `async def add_workers(self, *workers: BaseWorker) -> None` (`runner.py:199`).
  Every added worker is a peer; a duplicate name is logged as an error and skipped
  (`runner.py:219-223`).
- `async def run(self, worker: BaseWorker | None = None, *, auto_end: bool = True) -> None`
  (`runner.py:236-241`). Passing `worker` positionally is deprecated since 1.3.0
  (`runner.py:258-266`). With `auto_end=True` the runner ends once every root worker finishes;
  `auto_end=False` keeps it up until `end()`/`cancel()` — the documented choice for a long-lived
  FastAPI host that adds and removes workers per session (`runner.py:36-39`, `268-278`).
- Default bus is an in-process `AsyncQueueBus` (`runner.py:145`).
- Runner events: `on_ready`, `on_error` (`runner.py:172-173`; documented `runner.py:102-106`).

`WorkerParams` is a plain dataclass with a single field
`task_manager: BaseTaskManager` (`src/pipecat/workers/base_worker.py:72-80`).

### 1.6 Canonical processor ordering for a telephony agent

Taken verbatim from the shipped example `examples/voice/voice-cartesia.py:86-96`:

```python
pipeline = Pipeline(
    [
        transport.input(),      # Transport user input
        stt,
        user_aggregator,        # User responses
        llm,                    # LLM
        tts,                    # TTS
        transport.output(),     # Transport bot output
        assistant_aggregator,   # Assistant spoken responses
    ]
)
```

⚠ **The assistant context aggregator goes AFTER `transport.output()`, not before.** That is the
shipped ordering (`voice-cartesia.py:93-94`); placing it before the output would record assistant
text that was never spoken.

The aggregator pair is built from a single context
(`voice-cartesia.py:80-84`):

```python
context = LLMContext()
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
)
```

Imports for those names (`voice-cartesia.py:17-21`):
`pipecat.processors.aggregators.llm_context.LLMContext`,
`pipecat.processors.aggregators.llm_response_universal.{LLMContextAggregatorPair, LLMUserAggregatorParams}`.

⚠ **In 1.10.0 the VAD analyzer is supplied to the USER AGGREGATOR, not to `TransportParams`.**
`TransportParams` (`src/pipecat/transports/base_transport.py:66-93`) declares **no** `vad_analyzer`
and **no** `turn_analyzer` field. See §10.

Worker + runner wiring from the same example (`voice-cartesia.py:98-110`, `141`):

```python
worker = PipelineWorker(
    pipeline,
    params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    processor_unusable_policy=ProcessorUnusablePolicy.END,
)
runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
await runner.add_workers(worker)
...
await runner.run()
```

The conversation is kicked off from the transport's connect event by queueing an `LLMRunFrame()`
(`voice-cartesia.py:112-119`) — see §11.

---

## 2. PLIVO TELEPHONY

Files read in full for this section: `src/pipecat/serializers/plivo.py` (256 lines),
`src/pipecat/serializers/base_serializer.py` (108 lines),
`src/pipecat/transports/websocket/fastapi.py` (706),
`src/pipecat/transports/websocket/server.py` (718),
`src/pipecat/transports/websocket/client.py` (559),
`src/pipecat/transports/websocket/rtvi_client.py` (108).
`src/pipecat/transports/websocket/__init__.py` is empty (0 bytes).

### 2.1 Which websocket transport a Plivo call uses

There are three transports under `transports/websocket/` and **only one is for inbound telephony**:

| Class | Module | Role |
|---|---|---|
| `FastAPIWebsocketTransport` | `fastapi.py:610` | wraps an already-accepted FastAPI/Starlette `WebSocket`. **This is the telephony one.** |
| `SingleClientWebsocketServerTransport` | `server.py:520` | runs its own `websockets` server, `host="localhost"`, `port=8765`, **one client at a time**; new connections are rejected while one is connected (`server.py:528-531`). Documented as suited to "local development and single-session bots, but not for serving multiple concurrent clients". |
| `WebsocketClientTransport` | `client.py:479` | dials **out** to a websocket URI; defaults its serializer to `ProtobufFrameSerializer` (`client.py:511`). |

`RTVIClientTransport` (`rtvi_client.py:32`) subclasses `WebsocketClientTransport` for the eval
harness — not telephony.

Deprecated aliases in `server.py`, all since 1.4.0, removal in 2.0.0: `WebsocketServerParams`
(`server.py:649`), `WebsocketServerCallbacks` (`server.py:664`), `WebsocketServerInputTransport`
(`server.py:679`), and further aliases below them. Use the `SingleClient*` names if you use that
transport at all.

The runner's own telephony path constructs `FastAPIWebsocketTransport` for every telephony
provider, Plivo included: `_create_telephony_transport` (`src/pipecat/runner/utils.py:484-553`)
ends with `return FastAPIWebsocketTransport(websocket=websocket, params=params)`
(`runner/utils.py:553`).

### 2.2 `FastAPIWebsocketTransport` construction

`src/pipecat/transports/websocket/fastapi.py:629-635`:

```python
class FastAPIWebsocketTransport(BaseTransport):
    def __init__(
        self,
        websocket: WebSocket,
        params: FastAPIWebsocketParams,
        input_name: str | None = None,
        output_name: str | None = None,
    )
```

- The `WebSocket` must already be accepted by the caller; the transport does not call `accept()`
  anywhere in this file.
- **Origin check happens in the constructor and raises**: if `params.allowed_origins` is non-empty
  and the connection's `Origin` header is missing or disallowed, `__init__` raises
  `ValueError(f"WebSocket connection rejected: origin '{origin}' not allowed")`
  (`fastapi.py:645-649`). "The caller is responsible for closing the WebSocket in that case"
  (`fastapi.py:631-633`).
  ⚠ `allowed_origins` defaults to `default_allowed_origins()`, which reads the
  `PIPECAT_ALLOWED_ORIGINS` env var (`fastapi.py:86`, docstring `fastapi.py:68-72`). **Whether
  Plivo's media websocket sends an `Origin` header is UNKNOWN — the clone says nothing about it
  and Plivo's docs are not readable from here.** If it sends none and that env var is set in a
  Calevate deployment, every Plivo call is rejected at construction. Treat leaving it unset as
  the safe configuration for the telephony route.
  Resolved (`src/pipecat/utils/security/allowed_origins.py:12-19`):
  `default_allowed_origins()` returns `[]` when `PIPECAT_ALLOWED_ORIGINS` is unset or empty, and
  `is_origin_allowed()` returns `True` unconditionally for an empty list
  (`allowed_origins.py:31-32`). So **unset env var = no origin check at all**; a
  non-empty list is matched case-insensitively and exactly (`allowed_origins.py:33`), and a
  missing Origin is rejected outright (`allowed_origins.py:26-29`).
- Input/output processors are created eagerly in `__init__` (`fastapi.py:663-668`) and returned by
  `input()` (`fastapi.py:680-687`) and `output()` (`fastapi.py:688-695`).

#### `FastAPIWebsocketParams`

`fastapi.py:59-88`, subclass of `TransportParams`:

| Field | Type | Default | Line |
|---|---|---|---|
| `add_wav_header` | `bool` | `False` | `fastapi.py:82` |
| `serializer` | `FrameSerializer \| None` | `None` | `fastapi.py:83` |
| `session_timeout` | `int \| None` | `None` | `fastapi.py:84` |
| `fixed_audio_packet_size` | `int \| None` | `None` | `fastapi.py:85` |
| `allowed_origins` | `list[str]` | `Field(default_factory=default_allowed_origins)` | `fastapi.py:86` |
| `ws_close_timeout` | `float` | `_WS_CLOSE_TIMEOUT_DEFAULT` = `0.5` | `fastapi.py:87`, `fastapi.py:57` |

`ws_close_timeout` exists precisely for telephony: it bounds the close handshake so "a dead or
half-closed peer (e.g. a telephony call already torn down on the provider's side)" cannot stall
pipeline shutdown (`fastapi.py:72-79`).

`fixed_audio_packet_size` only applies to **bytes** payloads (`fastapi.py:573-585`). The Plivo
serializer emits JSON **strings**, so it is inert on the Plivo leg.

Inherited `TransportParams` fields used on a telephony call
(`src/pipecat/transports/base_transport.py:66-93`) — full table, since these are the audio knobs:

| Field | Default | Line |
|---|---|---|
| `audio_out_enabled` | `False` | `:68` |
| `audio_out_sample_rate` | `None` | `:69` |
| `audio_out_channels` | `1` | `:70` |
| `audio_out_bitrate` | `96000` | `:71` |
| `audio_out_10ms_chunks` | `4` | `:72` |
| `audio_out_mixer` | `None` | `:73` |
| `audio_out_destinations` | `[]` | `:74` |
| `audio_out_end_silence_secs` | `2` | `:75` |
| `audio_out_auto_silence` | `True` | `:76` |
| `audio_out_write_timeout_secs` | `10.0` | `:77` |
| `audio_in_enabled` | `False` | `:78` |
| `audio_in_sample_rate` | `None` | `:79` |
| `audio_in_channels` | `1` | `:80` |
| `audio_in_filter` | `None` | `:81` |
| `audio_in_stream_on_start` | `True` | `:82` |
| `audio_in_passthrough` | `True` | `:83` |
| `video_in_enabled` | `False` | `:84` |
| `video_out_enabled` | `False` | `:85` |
| `video_out_is_live` | `False` | `:86` |
| `video_out_width` | `1024` | `:87` |
| `video_out_height` | `768` | `:88` |
| `video_out_bitrate` | `None` (deprecated 1.1.0) | `:89` |
| `video_out_framerate` | `30` | `:90` |
| `video_out_color_format` | `"RGB"` | `:91` |
| `video_out_codec` | `None` | `:92` |
| `video_out_destinations` | `[]` | `:93` |

⚠ `audio_in_enabled` and `audio_out_enabled` are **both `False` by default** and must be set
`True` explicitly (as every shipped example does, e.g. `examples/voice/voice-cartesia.py:45-48`).

⚠ **`TransportParams` in 1.10.0 has NO `vad_analyzer` and NO `turn_analyzer` field** — verified by
reading the whole model (`base_transport.py:66-93`). See §10 for where VAD now lives.

### 2.3 `PlivoFrameSerializer` — class and params

`src/pipecat/serializers/plivo.py:32`, `class PlivoFrameSerializer(FrameSerializer)`.

Params dataclass is a **nested pydantic model**, `PlivoFrameSerializer.InputParams`, subclassing
`FrameSerializer.InputParams` (`plivo.py:44`). Every field, own and inherited:

| Field | Type | Default | Declared at |
|---|---|---|---|
| `plivo_sample_rate` | `int` | `8000` | `plivo.py:54` |
| `sample_rate` | `int \| None` | `None` (override for the pipeline input rate) | `plivo.py:55` |
| `auto_hang_up` | `bool` | `True` | `plivo.py:56` |
| `ignore_rtvi_messages` (inherited) | `bool` | `True` | `base_serializer.py:43` |
| `resampler_clear_after_secs` (inherited) | `float \| None` | `0.2` | `base_serializer.py:44` |

`resampler_clear_after_secs` is "Seconds of inactivity after which the stream resampler clears its
internal history to avoid audio artefacts from stale state. Set to `None` to never clear —
recommended for telephony providers (e.g. Genesys) that have irregular gaps between audio chunks"
(`base_serializer.py:37-40`). The recommendation names Genesys, **not Plivo**; whether Plivo's
chunk cadence needs `None` is **NOT STATED IN SOURCE**.

Constructor (`plivo.py:58-65`):

```python
def __init__(
    self,
    stream_id: str,
    call_id: str | None = None,
    auth_id: str | None = None,
    auth_token: str | None = None,
    params: InputParams | None = None,
)
```

⚠ **`auto_hang_up` defaults to `True`, and with it on the constructor RAISES if any of
`call_id`, `auth_id`, `auth_token` is falsy** — `ValueError(f"auto_hang_up is enabled but missing
required parameters: {', '.join(missing_credentials)}")` (`plivo.py:80-92`). So the practical
minimum for Calevate is all four positional-ish arguments, or `auto_hang_up=False`.

`setup()` resolves the pipeline-side rate: `self._sample_rate = self._params.sample_rate or
setup.audio_in_sample_rate` (`plivo.py:110-116`). It is called by both the input transport
(`fastapi.py:302-306`) and the output transport (`fastapi.py:459-461`) — i.e. **twice** on the
same serializer instance; the method is idempotent.

### 2.4 How a call binds to a stream id / call id

The serializer is bound at construction — the ids are constructor arguments, stored as
`self._stream_id` / `self._call_id` (`plivo.py:94-97`) and stamped into every outbound message.
**There is no rebinding API and no setter**: one serializer instance per call, therefore one
transport, one pipeline and one `PipelineWorker` per call.

The ids come from Plivo's first websocket message. `parse_telephony_websocket`
(`src/pipecat/runner/utils.py:112-296`) reads the **first two** text messages off the socket
(`runner/utils.py:180-207`), auto-detects the provider, and extracts:

```python
elif transport_type == "plivo":
    start_data = call_data_raw.get("start", {})
    call_data = {
        "stream_id": start_data.get("streamId"),
        "call_id": start_data.get("callId"),
    }
```
(`runner/utils.py:257-263`)

Plivo detection predicate (`runner/utils.py:89-96`):

```python
if (
    "start" in message_data
    and "streamId" in message_data.get("start", {})
    and "callId" in message_data.get("start", {})
):
    return "plivo"
```

Note this predicate does **not** require `event == "start"` (Twilio's and Exotel's do —
`runner/utils.py:70-76`, `98-107`). Plivo's handshake shape as the source understands it is
therefore `{"start": {"streamId": ..., "callId": ...}}`, possibly not at the first message —
hence the two-message read and the "Only received one WebSocket message, expected two" warning
(`runner/utils.py:203-207`).

`parse_telephony_websocket` caches its result on the websocket object under
`_pipecat_parsed_telephony` and is therefore idempotent (`runner/utils.py:168-176`, `288-292`) —
important, because `websocket.iter_text()` is single-use.

Returned `call_data` is a `CallData` pydantic model with dict-compatible access
(`runner/utils.py:119-124`, `280-287`). Plivo gets the base `CallData` class, not a subclass
(`runner/utils.py:281-283`), so **Plivo carries no `from`/`to` numbers through this path**:
the Plivo branch populates only `stream_id` and `call_id`. Caller number for a Plivo call is
**NOT FOUND IN SOURCE** on the websocket leg — it must come from the Plivo HTTP webhook that
answered the call, outside Pipecat.

The reference wiring (`runner/utils.py:532-540`):

```python
elif transport_type == "plivo":
    from pipecat.serializers.plivo import PlivoFrameSerializer
    params.serializer = PlivoFrameSerializer(
        stream_id=call_data["stream_id"],
        call_id=call_data["call_id"],
        auth_id=os.getenv("PLIVO_AUTH_ID", ""),
        auth_token=os.getenv("PLIVO_AUTH_TOKEN", ""),
    )
```

and `params.add_wav_header = False` is forced for every telephony provider
(`runner/utils.py:503-504`).

The dev runner's answer XML for Plivo (`src/pipecat/runner/run.py:1437-1440`), which documents the
expected Plivo-side stream configuration:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">wss://{proxy}/ws</Stream>
</Response>
```

### 2.5 Inbound message shapes (Plivo → us)

`deserialize()` (`plivo.py:207-256`) parses JSON and handles exactly **two** events. Anything else
returns `None` (`plivo.py:255-256`); malformed JSON logs a warning and returns `None`
(`plivo.py:218-222`).

1. `{"event": "media", "media": {"payload": "<base64>"}}` → base64-decode, μ-law→PCM, emit
   `InputAudioRawFrame(audio=..., num_channels=1, sample_rate=self._sample_rate)`
   (`plivo.py:224-244`). An empty/absent payload returns `None` (`plivo.py:228-229`), as does a
   zero-length resample result (`plivo.py:237-239`).
2. `{"event": "dtmf", "dtmf": {"digit": "<d>"}}` → `InputDTMFFrame(KeypadEntry(digit))`
   (`plivo.py:245-254`). A digit outside the enum logs `"Invalid DTMF digit received"` and returns
   `None` (`plivo.py:251-254`).

⚠ **The `start` message itself is NOT handled by the serializer** — no branch matches it, so it
deserializes to `None`. The handshake must be consumed before the transport starts reading (that
is exactly what `parse_telephony_websocket` does). Likewise **no `stop`/`clear`/`checkpoint`
inbound event is handled**: NOT FOUND IN SOURCE.

### 2.6 Audio encoding

**Inbound** (`plivo.py:231-243`): base64 → bytes → `ulaw_to_pcm(payload, self._plivo_sample_rate,
self._sample_rate, self._input_resampler)`, i.e. 8000 Hz μ-law in, PCM at the pipeline's
`audio_in_sample_rate` out, mono.

**Outbound** (`plivo.py:141-163`): any `AudioRawFrame` → `pcm_to_ulaw(data, frame.sample_rate,
self._plivo_sample_rate, self._output_resampler)` → base64 →

```json
{
  "event": "playAudio",
  "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": "<base64>"},
  "streamId": "<stream_id>"
}
```

serialized with `json.dumps` and sent as a **text** frame (`fastapi.py:169-178`:
`send_bytes` for `bytes`, `send_text` otherwise).

**Outbound barge-in.** An `InterruptionFrame` serialises to
`{"event": "clearAudio", "streamId": self._stream_id}` (`plivo.py:138-140`) — this is how the
bot's queued audio is dropped on Plivo's side when the caller interrupts. Note the branch order in
`serialize()`: the `EndFrame`/`CancelFrame` hangup check comes **first** (`plivo.py:130-137`), then
`InterruptionFrame`, then `AudioRawFrame`, then transport messages (`plivo.py:164-167`, which
respect `should_ignore_frame()` and therefore drop RTVI messages while `ignore_rtvi_messages` is
`True`).

Resamplers are per-direction, created in `__init__` via `create_stream_resampler(
clear_after_secs=self._params.resampler_clear_after_secs)` (`plivo.py:102-107`).

Output pacing: `FastAPIWebsocketOutputTransport` deliberately throttles sends to emulate an audio
device. `self._send_interval = (self.audio_chunk_size / self.sample_rate) / 2`, computed in
`setup()` (`fastapi.py:456`), and `_write_audio_sleep()` sleeps to the next send time
(`fastapi.py:598-608`). On an interruption `self._next_send_time = 0` resets the clock
(`fastapi.py:499-514`).

### 2.7 Hanging up

Two mechanisms, and they are different things:

**(a) Serializer-driven REST hangup (the real hangup).** On the first `EndFrame` **or**
`CancelFrame`, if `auto_hang_up` is on and no hangup has been attempted, `serialize()` sets
`self._hangup_attempted = True`, calls `_hang_up_call()` and returns `None`
(`plivo.py:130-137`). `_hang_up_call()` (`plivo.py:172-205`):

- endpoint: `https://api.plivo.com/v1/Account/{auth_id}/Call/{call_id}/` (`plivo.py:184`)
- method: HTTP **DELETE** with `aiohttp.BasicAuth(auth_id, auth_token)` (`plivo.py:187-191`)
- a **new `aiohttp.ClientSession` is created per hangup** (`plivo.py:190`) — no shared session
- `204` = success, `404` = already terminated (both logged at debug), anything else logged at
  error with the body (`plivo.py:192-202`)
- every exception is caught and logged: `logger.error(f"Failed to hang up Plivo call: {e}")`
  (`plivo.py:204-205`). **A failed hangup never raises and never surfaces a frame.** For Calevate
  that means a leaked live call is invisible to the pipeline; if we need certainty that the call
  ended, we must verify out-of-band.

⚠ Note the guard is `self._hangup_attempted`, set *before* the call — so if the DELETE fails, no
retry is ever attempted, including on a subsequent `CancelFrame`.

**(b) Websocket close.** `FastAPIWebsocketOutputTransport.stop()` / `.cancel()` write the
End/Cancel frame and then `await self._client.disconnect()` (`fastapi.py:473-491`);
`cleanup()` disconnects too (`fastapi.py:493-497`). `disconnect()` is refcounted by
`_leave_counter` (incremented once per `setup()`, so twice: input + output) and only actually
closes when the counter reaches zero (`fastapi.py:186-212`). The close runs as a background task
bounded by `ws_close_timeout` (default 0.5 s); if the peer does not ack, shutdown proceeds anyway
(`fastapi.py:198-212`).

**To hang up from application code**: queue an `EndFrame` — `await worker.stop_when_done()`
(`worker.py:765-772`) — or `await worker.cancel()` for an immediate teardown
(`worker.py:832-839`). There is **no** `hangup()` method on the serializer or transport:
NOT FOUND IN SOURCE.

### 2.8 DTMF

**Inbound: supported.** `{"event":"dtmf","dtmf":{"digit":...}}` → `InputDTMFFrame`
(`plivo.py:245-254`). `KeypadEntry` is a `StrEnum` with `"0"`–`"9"`, `POUND="#"`, `STAR="*"`
(`src/pipecat/audio/dtmf/types.py:17-47`) — no `A`–`D`.

To consume digits as text there is `DTMFAggregator`
(`src/pipecat/processors/aggregators/dtmf_aggregator.py:88-97`), which accumulates
`InputDTMFFrame`s and flushes them.

**Outbound: NOT SUPPORTED ON THE PLIVO LEG.** `PlivoFrameSerializer.serialize()` has **no branch
for `OutputDTMFFrame` or `OutputDTMFUrgentFrame`** — read the whole method, `plivo.py:118-170`.
A grep across the tree confirms no serializer handles output DTMF; only `transports/base_output.py`
does.

What actually happens if you push an `OutputDTMFFrame` on a Plivo call:
`BaseOutputTransport.write_dtmf()` (`base_output.py:265-273`) checks `_supports_native_dtmf()`,
which is `False` by default (`base_output.py:287-293`) and is **not overridden by
`FastAPIWebsocketOutputTransport`** — so it falls through to `_write_dtmf_audio()`
(`base_output.py:304-317`), which synthesises the tone locally via `load_dtmf_audio(button,
sample_rate=self._sample_rate)` and writes it as ordinary `OutputAudioRawFrame` audio. In other
words **outbound DTMF on Plivo is in-band generated tones carried in the μ-law media stream, not a
Plivo DTMF API call.** Whether Plivo's media path reproduces those tones cleanly enough for an IVR
to detect is **NOT ADDRESSED IN SOURCE** and must be tested on a real call before relying on it.

`OutputDTMFFrame` takes either `button: KeypadEntry` or `buttons: list[KeypadEntry]`; `buttons`
wins if both are given, and an empty one raises in `__post_init__`
(`src/pipecat/frames/frames.py:890-912`). `OutputDTMFUrgentFrame` is the `SystemFrame` variant
(`frames.py:1630-1631`). A worked example of pushing them is
`src/pipecat/extensions/ivr/ivr_navigator.py:189`.

---

## 3. SARVAM STT

Source: `src/pipecat/services/sarvam/stt.py` (1555 lines), read in full for the parts documented
here. Supporting: `src/pipecat/services/sarvam/_sdk.py` (16 lines),
`src/pipecat/services/settings.py`, `src/pipecat/services/stt_latency.py`.

⚠ **There are TWO Sarvam STT services in this file and they are not interchangeable.**

| Class | Line | Base | Transport | Model |
|---|---|---|---|---|
| `SarvamSTTService` | `stt.py:173` | `STTService` | Sarvam **SDK** websocket (`sarvamai.AsyncSarvamAI`) | `saaras:v3`, `saaras:v4` |
| `SarvamRealtimeSTTService` | `stt.py:915` | `WebsocketSTTService` | raw websocket to a URL we control | `saaras:v3-realtime` |

Both require the extra: `uv add "pipecat-ai[sarvam]"` — the module raises `ImportError` at import
time if `sarvamai` is absent (`stt.py:55-63`).

### 3.1 `SarvamSTTService`

Constructor (`stt.py:220-232`) — **all keyword-only**:

```python
def __init__(
    self,
    *,
    api_key: str,
    model: str | None = None,                       # DEPRECATED 0.0.105 -> settings.model
    mode: SarvamMode | None = None,
    sample_rate: int | None = None,
    input_audio_codec: str = "wav",
    params: InputParams | None = None,              # DEPRECATED 0.0.105 -> settings
    settings: Settings | None = None,
    ttfs_p99_latency: float | None = SARVAM_TTFS_P99,   # 1.17
    keepalive_timeout: float | None = None,
    keepalive_interval: float = 5.0,
    **kwargs,
)
```

- `SARVAM_TTFS_P99 = 1.17` seconds (`src/pipecat/services/stt_latency.py:60`). Docstring: "P99
  latency from speech end to final transcript in seconds. Override for your deployment. See
  https://github.com/pipecat-ai/stt-benchmark" (`stt.py:414-415`). **This is a REPORTED figure
  from Pipecat's own benchmark, not something Calevate has measured** — do not put it in a latency
  budget without measuring on our own leg.
- **Hardcoded default model is `"saaras:v4"`** (`stt.py:284`), applied before any override.
- `keepalive_timeout=None` means keepalive is **disabled by default**; when enabled, silence is
  sent via `transcribe()` at `keepalive_interval` (default 5.0 s) (`stt.py:774-796`).
- `input_audio_codec="wav"` is turned into an `encoding` of `"audio/wav"` unless it already starts
  with `audio/` (`stt.py:506-511`).
- `SarvamSTTService.InputParams` (`stt.py:198-217`) is deprecated since 0.0.105, removal in 2.0.0.
  Use `settings=`.

**Accepted model ids** are exactly the keys of `MODEL_CONFIGS` (`stt.py:113-128`):

```python
MODEL_CONFIGS: dict[str, ModelConfig] = {
    "saaras:v3": ModelConfig(supports_mode=True, supports_language=True,
                             default_language="unknown", default_mode="transcribe"),
    "saaras:v4": ModelConfig(supports_mode=True, supports_language=True,
                             default_language="unknown", default_mode="transcribe"),
}
```

Anything else raises at construction:
`ValueError(f"Unsupported model '{resolved_model}'. Allowed values: {allowed}.")`
(`stt.py:303-306`). So **`saaras:v3` and `saaras:v4` only** for this class.

`ModelConfig` is a frozen dataclass with `supports_mode`, `supports_language`,
`default_language`, `default_mode` (`stt.py:97-111`).

`SarvamMode = Literal["transcribe", "translate", "verbatim", "translit", "codemix"]`
(`stt.py:94`). `mode` is an **init-only** connection parameter stored as `self._mode`
(`stt.py:332-334`), defaulted from the model config when `None` (`stt.py:318-319`).

**API key handling** (`stt.py:329`, `stt.py:339-343`): the key is passed to the SDK client as
`AsyncSarvamAI(api_subscription_key=api_key, headers=self._sdk_headers)`. There is **no env-var
fallback in this class** — `api_key` is a required keyword argument. `sdk_headers()` is only
`{"User-Agent": f"Pipecat/{version} Python/{python_version}"}` (`_sdk.py:12-16`); it is logged at
info level on init (`stt.py:357`) and carries no secret.

**Language configuration and the Telugu code.**
`language_to_sarvam_language()` (`stt.py:65-91`) maps the `Language` enum to Sarvam codes:

| `Language` | Sarvam code |
|---|---|
| `BN_IN` | `bn-IN` |
| `GU_IN` | `gu-IN` |
| `HI_IN` | `hi-IN` |
| `KN_IN` | `kn-IN` |
| `ML_IN` | `ml-IN` |
| `MR_IN` | `mr-IN` |
| `TA_IN` | `ta-IN` |
| **`TE_IN`** | **`te-IN`** ← Telugu (`stt.py:83`) |
| `PA_IN` | `pa-IN` |
| `OR_IN` | **`od-IN`** (note: `od-`, not `or-`, on this class) |
| `EN_IN` | `en-IN` |
| `AS_IN` | `as-IN` |

**Telugu for Calevate is `Language.TE_IN` → wire value `te-IN`** (`stt.py:83`).

Set it as `settings=SarvamSTTService.Settings(language=Language.TE_IN)`; `language` is a field of
the base `STTSettings` (`src/pipecat/services/settings.py:397`). When `language` is unset the
model config's `default_language` — `"unknown"`, i.e. Sarvam auto-detect — is sent
(`stt.py:118`, `stt.py:369-377`). The resolved code goes on the wire as the `language_code`
connect parameter (`stt.py:565-568`).

⚠ **The inbound mapping table is LARGER than the outbound one** (`stt.py:729-767`): it also
recognises `en-US`, `ur-IN`, `mai-IN`, `sd-IN`, `kok-IN`. An unrecognised code — or Sarvam's
`"unknown"` — leaves `TranscriptionFrame.language` as `None` rather than guessing, and warns once
per code (`stt.py:756-767`).

**Sample rates.** `sample_rate: int | None = None`, "Defaults to 16000 if not specified"
(`stt.py:400`). ⚠ **`SarvamSTTService` imposes NO sample-rate validation** — the check against
`SUPPORTED_SAMPLE_RATES = {8000, 16000}` (`stt.py:828`) belongs to the *realtime* class only
(`stt.py:987-989`). The rate is sent as a string on connect (`stt.py:530`) and per-chunk
(`stt.py:517`).

**Interim / partial results: NOT EMITTED by `SarvamSTTService`.** Read the whole message handler
(`stt.py:653-717`): a `message.type == "data"` event pushes a `TranscriptionFrame` and nothing
else; `InterimTranscriptionFrame` is imported in this module but is used **only** by the realtime
class (`stt.py:1355-1368`). If Calevate needs partials for barge-in UX, it needs
`SarvamRealtimeSTTService` — or must live without them.

**What it does emit** (`stt.py:653-717`):

- `message.type == "events"`, `signal_type == "START_SPEECH"` → event handler `on_speech_started`
  + `broadcast_frame(ProposedUserStartedSpeakingFrame)` (`stt.py:661-670`)
- `signal_type == "END_SPEECH"` → `on_speech_stopped` +
  `broadcast_frame(ProposedUserStoppedSpeakingFrame)` (`stt.py:672-677`)
- `message.type == "data"` → `on_utterance_end` event, then, only if the transcript is non-blank:
  `emit_stt_usage_metrics()` **before** `push_frame(TranscriptionFrame(...))`, with the raw
  message attached as `result=` (`stt.py:679-714`). The ordering is deliberate — "Report usage
  before the transcription frame so tracing can attach it to the STT span the frame closes"
  (`stt.py:703-704`).

⚠ The three speech event handlers are **only registered when `vad_signals` is truthy**
(`stt.py:352-355`). Registering a handler for `on_speech_started` without `vad_signals` set will
not work.

Service-level event handlers documented at `stt.py:180-186`: `on_connected`, `on_disconnected`,
`on_connection_error(service, error)`.

**Turn ownership.** `service_metadata_frame()` (`stt.py:387-399`) returns
`user_turn_strategies = ExternalUserTurnStrategies()` **when `vad_signals` is enabled**, which
tells the user aggregator to stop running local VAD/smart-turn and use Sarvam's server-side
boundaries instead. With `vad_signals` off, `process_frame` flushes the socket on
`VADUserStoppedSpeakingFrame` (`stt.py:401-413`) and the connect call adds
`flush_signal="true"` (`stt.py:535-539`). **These are two mutually exclusive turn architectures;
pick one deliberately.**

`SarvamSTTSettings` (`stt.py:130-170`) — every field, all defaulting to `NOT_GIVEN`:
`vad_signals` (bool), `high_vad_sensitivity` (bool), `positive_speech_threshold` (float),
`negative_speech_threshold` (float), `min_speech_frames` (int), `first_turn_min_speech_frames`
(int), `negative_frames_count` (int), `negative_frames_window` (int),
`start_speech_volume_threshold` (float, dB), `interrupt_min_speech_frames` (int),
`pre_speech_pad_frames` (int), `num_initial_ignored_frames` (int) — plus inherited `model` and
`language` from `STTSettings` (`services/settings.py:378-397`).
All are **connect-time** parameters: changing any of them at runtime triggers a full
disconnect/reconnect (`stt.py:415-460`; the `reconnect_fields` set is at `stt.py:438-450`).
Hardcoded init defaults set all twelve to `None` (`stt.py:283-298`), and a `None` is simply not
sent, "avoid overriding server defaults" (`stt.py:541-561`).

`setup()` connects immediately (`stt.py:461-468`); `stop()`/`cancel()` disconnect
(`stt.py:470-486`). `can_generate_metrics()` returns `True` (`stt.py:379-385`).

### 3.2 `SarvamRealtimeSTTService` — the one with partials

Constructor (`stt.py:941-955`):

```python
def __init__(
    self,
    *,
    api_key: str,
    base_url: str = "wss://api.sarvam.ai/speech-to-text-realtime/ws",
    endpointing: Literal["vad", "manual"] = "vad",
    sample_rate: int | None = None,
    return_timestamps: bool = False,
    prefix_padding_ms: int | None = None,
    settings: Settings | None = None,
    should_interrupt: bool = True,
    ttfs_p99_latency: float | None = SARVAM_REALTIME_TTFS_P99,   # 1.00
    **kwargs,
)
```

- Model is fixed: `_REALTIME_MODEL = "saaras:v3-realtime"` (`stt.py:798`), set as the settings
  default (`stt.py:991`). No other id is accepted through the settings default.
- **`sample_rate` is validated: `SUPPORTED_SAMPLE_RATES = {8000, 16000}`** (`stt.py:828`), and an
  unsupported explicit value raises `ValueError` at construction (`stt.py:987-989`). Once the
  pipeline's rate is resolved at `setup()`, an unsupported resolved rate is pushed as a
  **permanent** error with `ErrorCategory.INVALID_REQUEST`, costing the service its usability
  (`stt.py:1067-1082`). **8000 Hz is supported — which matters, because that is the Plivo rate.**
- Auth: header `{"API-SUBSCRIPTION-KEY": self._api_key}` on the websocket handshake
  (`stt.py:1168`), plus `user_agent_header=sdk_headers()["User-Agent"]` (`stt.py:1173`).
  No env-var fallback.
- `reconnect_on_error` is **rejected** as a kwarg: "reconnection is always disabled"
  (`stt.py:981-985`, and `reconnect_on_error=False` is forced at `stt.py:1016`). When the receive
  loop exits the service marks itself unusable (`stt.py:1200-1214`).
- Passing any `Settings` field name as a bare kwarg raises `TypeError` (`stt.py:974-980`).

`SarvamRealtimeSTTSettings` (`stt.py:886-912`) and its init defaults (`stt.py:990-1000`):

| Field | Type | Init default |
|---|---|---|
| `model` | inherited | `"saaras:v3-realtime"` |
| `language` | inherited | `None` |
| `language_code` | `str` | `"en-IN"` |
| `stream_type` | `Literal["fast","balanced","simulated"]` | `"balanced"` |
| `mode` | `SarvamMode` | `"transcribe"` |
| `prompt` | `str \| None` | `None` |
| `threshold` | `float \| None` | `None` |
| `silence_duration_ms` | `int \| None` | `None` |
| `min_speech_duration_ms` | `int \| None` | `None` |

⚠ **The realtime default `language_code` is `"en-IN"`, not auto-detect.** For Telugu you must set
it. Either pass `settings=Settings(language_code="te-IN")` directly, or pass
`language=Language.TE_IN` and let the constructor derive it — an explicit `language_code` wins
(`stt.py:1002-1009`).

Realtime language map `language_to_sarvam_realtime_language()` (`stt.py:862-882`) — 15 entries;
**Telugu is `Language.TE_IN` → `"te-IN"` (`stt.py:879`)**. ⚠ Note Odia here is `"or-IN"`, whereas
the non-realtime class maps it to `"od-IN"` (`stt.py:86` vs `stt.py:877`). **AMBIGUOUS IN
SOURCE** — the clone gives two different wire codes for the same language on two Sarvam endpoints
with no comment explaining it. Either Sarvam's two endpoints really differ, or one of them is a
bug; the clone cannot tell us which. Irrelevant to Telugu, but do not assume the two tables are
interchangeable.

`SUPPORTED_LANGUAGES` for realtime is a 24-entry set including `"auto"` and `"te-IN"`
(`stt.py:801-825`).

Connect query string (`stt.py:1444-1456`): `language_code`, `stream_type`, `endpointing`,
`encoding="linear16"` (hardcoded), `sample_rate`, `model`, `mode`,
`return_timestamps` (lowercased string), plus optional `prompt`, appended to `base_url`
(`stt.py:1134-1137`).

**Interim results: YES.** `transcript.partial` → `InterimTranscriptionFrame(text, user_id,
time_now_iso8601(), language, result=...)`, blank text skipped (`stt.py:1245-1246`,
`1355-1368`). `transcript.final` → `emit_stt_usage_metrics()` then
`TranscriptionFrame(..., finalized=True)` with `speech_end_audio_position_s` added to `result`
(`stt.py:1370-1388`).

Server events handled (`stt.py:1232-1258`): `session.begin`, `vad.speech_start` /
`vad.speech_end` (only under `endpointing="vad"`), `transcript.partial`, `transcript.final`,
`session.end`, `config.updated`, `error`, `pong`. Anything else is logged at trace.

Client events sent: `audio_input` (base64) (`stt.py:1400-1404`), `speech_start` /
`speech_end` under `endpointing="manual"` (`stt.py:1096-1108`), `end` on disconnect
(`stt.py:1152`), and `config.update` via the public
`async def update_config(self, **fields: Any)` (`stt.py:1259-1268`) — rejects connection-only
fields. Runtime-updatable set `_RUNTIME_CONFIG_FIELDS` (`stt.py:837-848`): `language_code`,
`stream_type`, `mode`, `prompt`, `threshold`, `silence_duration_ms`, `min_speech_duration_ms`;
the first four are "boundary-gated: the server defers them to the next utterance boundary"
(`stt.py:835-836`).

Audio is buffered and sent on a fixed cadence: `_CLIENT_CHUNK_MS = 50` — "Sarvam's `stream_type`
selects the *server* flush profile; it says nothing about how often the client should send"
(`stt.py:830-833`, `stt.py:1110-1132`).

⚠ **A VAD analyzer is required in BOTH endpointing modes** (`stt.py:925-935`). Under `"vad"` it is
used to *time* TTFB from `VADUserStoppedSpeakingFrame`, because Sarvam's own `vad.speech_end`
arrives only after the server's silence window and "would time a shorter interval than every other
STT service reports". Under `"manual"` the same frames also mark the turn for Sarvam, and without
a strategy emitting them "Sarvam never receives a boundary and never emits a final transcript"
(`stt.py:920-924`).

`SARVAM_REALTIME_TTFS_P99 = 1.00` s (`services/stt_latency.py:62`) — again REPORTED, not measured
by us.

---

## 4. TTS SERVICE BASE CLASSES — the contract for `GnaniTTSService`

Source: `src/pipecat/services/tts_service.py` (2146 lines) and
`src/pipecat/services/websocket_service.py` (424 lines).

### 4.0 Which base class to inherit — read this first

⚠ **Four of the seven TTS base classes named in the brief are DEPRECATED in 1.10.0.**

| Class | Line | Status |
|---|---|---|
| `TTSService` | `tts_service.py:110` | **LIVE** — the base. Abstract `run_tts`. |
| `WebsocketTTSService` | `tts_service.py:1909` | **LIVE** — `TTSService` + `WebsocketService`. |
| `InterruptibleTTSService` | `tts_service.py:1979` | **LIVE** — `WebsocketTTSService` + reconnect-on-barge-in. |
| `WordTTSService` | `tts_service.py:1892` | DEPRECATED 0.0.105, removed 2.0.0 → use `TTSService` |
| `WebsocketWordTTSService` | `tts_service.py:2050` | DEPRECATED 0.0.105 → use `WebsocketTTSService` |
| `InterruptibleWordTTSService` | `tts_service.py:2072` | DEPRECATED 0.0.105 → use `InterruptibleTTSService` |
| `AudioContextTTSService` | `tts_service.py:2093` | DEPRECATED 0.0.105 → use `WebsocketTTSService` |
| `AudioContextWordTTSService` | `tts_service.py:2131` | DEPRECATED 0.0.105 → use `WebsocketTTSService` |

All four deprecated `*Word*` classes are empty `pass`-through subclasses. The deprecation reason
is stated plainly: **"Word timestamp functionality is now always active in TTSService"**
(`tts_service.py:1896-1897`), and **audio-context management "is now built into `TTSService`"**
(`tts_service.py:2098-2099`). There is no separate "Word variant" contract to implement in 1.10.0
— the word-timestamp API is on `TTSService` itself (§4.6).

**Recommendation for `GnaniTTSService`, from the source:** inherit
**`InterruptibleTTSService`** if Gnani has no server-side cancel/clear message (it forces a
websocket reconnect on barge-in, which is the only reliable way to stop a stream that keeps
sending), or **`WebsocketTTSService`** if Gnani supports an explicit cancel that
`on_audio_context_interrupted()` can send. The five first-party services that subclass
`InterruptibleTTSService` are deepgram, fish, neuphonic, rime, sarvam and smallest
(`services/*/tts.py`).

### 4.1 `TTSService.__init__` — full signature

`tts_service.py:146-190`, all keyword-only:

```python
def __init__(
    self,
    *,
    text_aggregation_mode: TextAggregationMode | None = None,   # -> SENTENCE if None
    aggregate_sentences: bool | None = None,                    # DEPRECATED 0.0.104
    push_text_frames: bool = True,
    push_stop_frames: bool = False,
    push_start_frame: bool = False,
    stop_frame_timeout_s: float = 3.0,
    push_silence_after_stop: bool = False,
    silence_time_s: float = 2.0,
    pause_frame_processing: bool = False,
    pause_watchdog_timeout_s: float | None = None,              # DEPRECATED 1.8.0, unused
    max_consecutive_zero_audio_contexts: int = 3,
    append_trailing_space: bool = False,
    sample_rate: int | None = None,
    skip_aggregator_types: list[str] | None = None,
    text_transforms: list[tuple[AggregationType | str,
                                Callable[[str, str | AggregationType], Awaitable[str]]]] | None = None,
    text_filters: Sequence[BaseTextFilter] | None = None,
    transport_destination: str | None = None,
    settings: TTSSettings | None = None,
    reuse_context_id_within_turn: bool = True,
    **kwargs,
)
```

Each flag, and what it obliges the subclass to do (`tts_service.py:148-175` inline comments,
`tts_service.py:191-250` docstring):

- `push_text_frames=True` — the base pushes `TTSTextFrame`s and `LLMFullResponseEndFrame`s.
  **Set it `False` only if the subclass emits per-word text frames itself.** With it `True`, the
  base pushes the whole (untransformed) text after synthesis completes, so "if we are interrupted,
  the text is not added to the assistant context" (`tts_service.py:1318-1330`).
- `push_stop_frames=False` — set `True` and the base pushes `TTSStoppedFrame` after
  `stop_frame_timeout_s` (default **3.0 s**) of queue idleness (`tts_service.py:1770-1782`).
- `push_start_frame=False` — set `True` and the base does `create_audio_context()`,
  `start_ttfb_metrics()` and appends `TTSStartedFrame(context_id=...)` for you, "so `run_tts`
  implementations do not need to" (`tts_service.py:1278-1285`, docstring `tts_service.py:205-208`).
- `pause_frame_processing=False` — set `True` and incoming frames are held until the turn's audio
  has played, "to avoid audio overlapping" (`tts_service.py:815-818`, `tts_service.py:1071-1089`).
- `max_consecutive_zero_audio_contexts=3` — **important for Calevate.** A provider that accepts
  requests and returns no audio (bad voice id) surfaces no error otherwise. Every silent context
  pushes a recoverable error; on the 3rd consecutive one the service pushes a
  `force_treat_as_permanent=True` error, stops being given work, and the worker's
  `ProcessorUnusablePolicy` applies (`tts_service.py:1786-1845`, docstring
  `tts_service.py:224-233`). `0` disables the write-off but still reports each silent context.
- `append_trailing_space=False` — "helps prevent some TTS services from vocalizing trailing
  punctuation (e.g., 'dot')"; applied only in SENTENCE mode (`tts_service.py:572-586`).
- `reuse_context_id_within_turn=True` — one context id per LLM turn (`tts_service.py:528-538`).

`TextAggregationMode` (`tts_service.py:83-98`) is a `StrEnum`: `SENTENCE = "sentence"` (default;
"~200-300ms per sentence" of added latency per its own docstring, `tts_service.py:88-89`) and
`TOKEN = "token"`. ⚠ That latency figure is **Pipecat's own REPORTED estimate in a docstring**, not
a measurement.

`TTSContext` (`tts_service.py:66-81`) is a small dataclass: `append_to_context: bool = True`,
`push_assistant_aggregation: bool | None = False`.

Language conversion at init: a `str` language is coerced to `Language`, then through
`language_to_service_language()`; an unrecognised string is passed through as-is with a debug log
(`tts_service.py:256-276`).

### 4.2 `run_tts` — the exact contract

`tts_service.py:540-556`:

```python
@abstractmethod
async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
    ...
```

Semantics, from `tts_process_generator` (`tts_service.py:1350-1381`), which is what consumes it:

- **Every non-`None` frame yielded is appended to the audio context named by `context_id`** —
  the generator does NOT push frames downstream itself.
- **The audio context must exist before the first frame is yielded.** Either `push_start_frame=True`
  (base class creates it — `tts_service.py:1278-1285`) or `run_tts` calls
  `await self.create_audio_context(context_id)` itself.
- **Yielding `None` is the websocket signal**: "WebSocket services yield `None` to signal that
  audio will arrive via a separate receive loop; those services manage context lifetime themselves
  (via `remove_audio_context` in the receive loop on 'done'). HTTP services never yield `None` and
  do NOT call `remove_audio_context` in `run_tts`" (`tts_service.py:1358-1364`).
- `self._is_yielding_frames_synchronously` is set from whether any `TTSAudioRawFrame` was yielded
  inline (`tts_service.py:1375-1381`).
- The base class **already logs the text** before calling `run_tts`
  (`tts_service.py:1302-1308`) — "implementations should not log it again"
  (`tts_service.py:545-546`).
- `run_tts` is **not** called at all when `self.is_usable` is `False`; the turn completes with a
  warning naming the unspoken text (`tts_service.py:1311-1321`).

**Frames and their order.** For a streaming websocket service with `push_start_frame=True` and
`push_stop_frames=True` (the Neuphonic/Calevate shape), the ordering that reaches the pipeline is
produced by `_handle_audio_context` (`tts_service.py:1713-1782`) draining the context queue:

1. `TTSStartedFrame(context_id=...)` — appended by the base before `run_tts`
   (`tts_service.py:1278-1285`); `append_to_context` is stamped on it as it passes through
   (`tts_service.py:1749-1756`).
2. `TTSAudioRawFrame(audio, sample_rate, num_channels, context_id=...)` — one per chunk, appended
   from the receive loop. On the **first** one the base calls `stop_ttfb_metrics()` and
   `start_word_timestamps()` exactly once, then `process_ttfa_metrics(frame)` on every chunk
   (`tts_service.py:1737-1747`).
3. `TTSTextFrame` — appended by the base after `run_tts` returns when `push_text_frames=True`
   (`tts_service.py:1325-1340`), or emitted per word by a word-timestamp service.
4. `TTSStoppedFrame(context_id=...)` — either yielded/appended by the subclass, or pushed by the
   base on the `stop_frame_timeout_s` timeout / at end of context when `push_stop_frames=True`
   (`tts_service.py:1770-1782`). Its `pts` is back-filled from the last word timestamp
   (`tts_service.py:1757-1763`).

An `ErrorFrame` in the queue is routed through `push_error_frame()` rather than `push_frame()`
(`tts_service.py:1765-1768`).

**Minimal websocket `run_tts` body** — the shape to mirror (Neuphonic, `neuphonic/tts.py:355-390`):
connect if the socket is closed, send the text, `await self.start_tts_usage_metrics(text)`, then
`yield None`. On a send failure: `yield ErrorFrame(...)`, `yield TTSStoppedFrame(context_id=...)`,
disconnect, reconnect, return.

Decorate it with `@traced_tts` (`pipecat.utils.tracing.service_decorators.traced_tts`) — every
first-party implementation does (`neuphonic/tts.py:355`).

### 4.3 Audio contexts — the queue every frame travels through

Public API on `TTSService`:

| Method | Signature | Line |
|---|---|---|
| `create_context_id` | `def create_context_id(self) -> str` | `:528` |
| `create_audio_context` | `async def create_audio_context(self, context_id: str)` | `:1499` |
| `append_to_audio_context` | `async def append_to_audio_context(self, context_id: str \| None, frame: Frame \| _WordTimestampEntry \| None)` | `:1509` |
| `remove_audio_context` | `async def remove_audio_context(self, context_id: str \| None)` | `:1542` |
| `has_active_audio_context` | `def has_active_audio_context(self) -> bool` | `:1562` |
| `get_audio_contexts` | `def get_audio_contexts(self) -> list[str]` | `:1572` |
| `get_active_audio_context_id` | `def get_active_audio_context_id(self) -> str \| None` | `:1576` |
| `remove_active_audio_context` | `async def remove_active_audio_context(self)` | `:1591` |
| `reset_active_audio_context` | `def reset_active_audio_context(self)` | `:1597` |
| `audio_context_available` | `def audio_context_available(self, context_id: str) -> bool` | `:1601` |
| `flush_audio` | `async def flush_audio(self, context_id: str \| None = None)` — base is a no-op | `:588` |

Behaviour that matters when writing a subclass:

- A context is an `asyncio.Queue` (`tts_service.py:1506`). `remove_audio_context` does **not**
  delete it — it appends the `None` sentinel and deletion happens when the drain loop reaches it
  (`tts_service.py:1554-1558`, `tts_service.py:1729-1730`).
- `append_to_audio_context(None, frame)` is a **logged no-op**, not an error
  (`tts_service.py:1526-1528`) — so `append_to_audio_context(self.get_active_audio_context_id(),
  frame)` is safe without a guard.
- If the context is gone but the id matches the current turn, it is **transparently recreated**
  (`tts_service.py:1531-1537`) — added because "the HTTP service can take more than 3 seconds
  without sending any audio".
- `get_active_audio_context_id()` returns the playback cursor, falling back to the turn's synthesis
  id. Its docstring names exactly our case: the fallback is "important for services whose wire
  protocol does not echo `context_id` back on incoming audio" (`tts_service.py:1576-1589`).
  **If Gnani's protocol does not echo a context id, this is the call to use in the receive loop.**
- `_CONTEXT_KEEPALIVE` (a sentinel object, `tts_service.py:144`) resets the idle timeout without
  being a frame (`tts_service.py:1612-1615`, `1723-1725`).

Two override hooks for provider-specific cleanup, both no-ops in the base:

```python
async def on_audio_context_interrupted(self, context_id: str)   # tts_service.py:1858
async def on_audio_context_completed(self, context_id: str)     # tts_service.py:1873
```

`on_audio_context_interrupted` is where a cancel/close message goes on barge-in; the audio-context
task is already stopped and the active context not yet reset when it runs
(`tts_service.py:1858-1871`).

### 4.4 Interruption

`TTSService._handle_interruption(frame: InterruptionFrame, direction)` (`tts_service.py:1033-1069`)
does, in order: clear `_processing_text`; clear `_bot_speaking`; `handle_interruption()` on the
text aggregator and every text filter; reset word timestamps; **stop the audio-context task**;
reset the serialization queue (dropping everything except `UninterruptibleFrame`s such as
`FunctionCallResultFrame`); call `on_audio_context_interrupted()` for **every** live context;
reset the active context and `_turn_context_id`; recreate the audio-context task; resume frame
processing if it was paused.

`InterruptibleTTSService` adds the reconnect (`tts_service.py:2002-2012`):

```python
should_reconnect = self._bot_speaking or self._tts_started
self._tts_started = False
await super()._handle_interruption(frame, direction)
if should_reconnect:
    await self._disconnect()
    await self._connect()
```

`_tts_started` is set when a `TTSStartedFrame` is pushed (`tts_service.py:2014-2026`) and cleared
on `BotStoppedSpeakingFrame` or `LLMFullResponseStartFrame` (`tts_service.py:2028-2047`). Its
purpose: close "the narrow window where `_bot_speaking` ... can't yet tell a reconnect is needed"
(`tts_service.py:1993-2000`). **The cost of this base class is a fresh websocket handshake on every
barge-in** — on an Indian telephony leg that is the latency to measure before choosing it over an
explicit cancel message.

### 4.5 Metrics reported by the TTS layer

- `supports_processing_metrics` — `True` on `TTSService` (`tts_service.py:424-435`), **`False` on
  `WebsocketTTSService`** (`tts_service.py:1935-1944`), because "`run_tts` sends the text and
  returns, and audio arrives later on the receive task, so there is no synthesis inside the
  measured window. A subclass that instead waits for the server to signal the end of synthesis
  before returning can override this back to True."
- TTFB: `start_ttfb_metrics()` is called by the base when it creates the context under
  `push_start_frame=True` (`tts_service.py:1280`); `stop_ttfb_metrics()` fires on the **first**
  `TTSAudioRawFrame` reaching the context queue (`tts_service.py:1740`). Concrete services also
  call `stop_ttfb_metrics()` in the receive loop (`neuphonic/tts.py:328`) — both paths exist.
- TTFA: `process_ttfa_metrics(frame)` on every audio frame (`tts_service.py:1747`).
- Usage: `start_tts_usage_metrics(text)` — overridden to **skip per-token calls in TOKEN mode**,
  where usage is aggregated and reported once at flush (`tts_service.py:437-448`, and the flush at
  `tts_service.py:822-826`). Call it from `run_tts` after a successful send
  (`neuphonic/tts.py:370`).
- Text aggregation: `start_text_aggregation_metrics()` / `stop_text_aggregation_metrics()`
  (`tts_service.py:450-464`), once per LLM response.

`can_generate_metrics()` must return `True` on the subclass for any of it to be collected
(`neuphonic/tts.py:200-206`), **and** `PipelineParams(enable_metrics=True)` must be set (§1.3).

### 4.6 Word timestamps — always present, no separate class

`TTSService` methods (`tts_service.py:1383-1497`):

```python
async def start_word_timestamps(self)                      # :1383
async def reset_word_timestamps(self)                      # :1402
async def add_word_timestamps(self, ...)                   # :1409
```

`_WordTimestampEntry` is an internal dataclass — `word`, `timestamp`, `context_id`,
`includes_inter_frame_spaces: bool = False` (`tts_service.py:101-108`) — routed through the same
context queue as audio so words are emitted in playback order (`tts_service.py:1731-1736`).
The clock baseline is taken once, on the first audio chunk of a context
(`tts_service.py:1383-1400`).

**For `GnaniTTSService` (no word timestamps): do nothing here.** Leave `push_text_frames=True`
and the base pushes the whole text after synthesis. That is exactly what Neuphonic does.

### 4.7 Connection lifecycle hooks

`TTSService` (`tts_service.py:597-643`): `setup(setup)`, `cleanup()`, `start(StartFrame)`,
`stop(EndFrame)`, `cancel(CancelFrame)`.

`WebsocketTTSService` (`tts_service.py:1909-1977`):

```python
def __init__(self, *, reconnect_on_error: bool = True, **kwargs):
    TTSService.__init__(self, **kwargs)
    WebsocketService.__init__(self, reconnect_on_error=reconnect_on_error, **kwargs)
```

- `stop(EndFrame)` → `super().stop()` then `await self._disconnect()` (`tts_service.py:1946-1953`)
- `cancel(CancelFrame)` → `super().cancel()` then `await self._disconnect()`
  (`tts_service.py:1955-1967`). The docstring explains why cancel must disconnect: "the websocket
  receive loop runs independently of the audio-context task, so it keeps reading from the provider
  until the socket is closed."
- `cleanup()` → `await self._disconnect()` (`tts_service.py:1969-1972`)
- `_report_error()` fires the `on_connection_error` event handler and then
  `push_error_frame(..., force_treat_as_permanent=...)` (`tts_service.py:1974-1976`).

`WebsocketService` (`websocket_service.py:84`) — the mixin, with **three abstract methods a
subclass must implement**: `_connect_websocket()` (`:400`), `_disconnect_websocket()` (`:409`),
`_receive_messages()` (`:418`). Its constructor (`websocket_service.py:100-107`):

```python
def __init__(
    self,
    *,
    reconnect_backoff_min_wait: float = 4.0,
    reconnect_backoff_max_wait: float = 10.0,
    reconnect_on_error: bool = True,
    ws_close_timeout: float = WS_CLOSE_TIMEOUT,   # 2.0, websocket_service.py:50
    **kwargs,
)
```

- `_websocket_connect(uri, **kwargs)` (`:149-166`) wraps `websockets.asyncio.client.connect`,
  defaulting `close_timeout` to `ws_close_timeout` and `create_connection` to
  `_BoundedCloseConnection`. **Use it, not `websockets.connect` directly.**
- `_receive_task_handler(report_error)` (`:338-376`) is the retry loop: it calls
  `_receive_messages()`, and on graceful close, `ConnectionClosedError`, or any exception it goes
  through `_maybe_try_reconnect`. `ConnectionClosedOK` breaks without retrying.
- `_try_reconnect(max_retries=3, report_error=None)` (`:199-254`) — **3 attempts**, exponential
  backoff between `reconnect_backoff_min_wait` and `reconnect_backoff_max_wait` (4–10 s). On
  exhaustion it reports the error with `force_treat_as_permanent=True` (`:246-250`), i.e. the
  service becomes unusable.
- `send_with_retry(message, report_error)` (`:256-274`) — send, and on failure reconnect once and
  resend.
- `_connect()` / `_disconnect()` (`:378-398`) only manage `_disconnecting` and the quick-failure
  tracker; **subclasses must call `super()` first** and then do their own work.
- A `QuickFailureTracker` catches the case where "a server accepts the WebSocket handshake but
  immediately closes the connection (e.g. invalid API key, policy rejection)", which backoff alone
  cannot fix (`websocket_service.py:129-136`).

`TTSService` event handlers (`tts_service.py:117-140`): `on_connected`, `on_disconnected`,
`on_connection_error(tts, error)`, `on_tts_request(tts, context_id, text)`.
`on_tts_request` fires just before synthesis with the **prepared** text
(`tts_service.py:1276`) — this is the hook Calevate should use for per-utterance character
accounting, since it sees exactly what was sent.

### 4.8 WORKED TEMPLATE — `NeuphonicTTSService`

Chosen because it is the closest analogue in the tree to the service Calevate is writing: a
websocket service that receives **base64-encoded PCM chunks** with **no word timestamps**.
Source: `src/pipecat/services/neuphonic/tts.py:82-390`. (Other `InterruptibleTTSService`
implementations: `deepgram/`, `fish/`, `rime/`, `sarvam/`, `smallest/tts.py`.)

Structure, in the order `GnaniTTSService` should mirror it:

**1. Language map + converter function** (`neuphonic/tts.py:39-64`) — a module-level
`language_to_<vendor>_lang_code(language: Language) -> str` wrapping
`resolve_language(language, LANGUAGE_MAP, use_base_code=True)`.

**2. Settings dataclass** (`neuphonic/tts.py:67-78`):

```python
@dataclass
class NeuphonicTTSSettings(TTSSettings):
    speed: float | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    temperature: float | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
```

Vendor-specific fields only; `model`, `voice`, `language` come from `TTSSettings`. Every field
defaults to `NOT_GIVEN` so a delta can be distinguished from an explicit `None`.

**3. Class declaration** (`neuphonic/tts.py:82-90`):

```python
class NeuphonicTTSService(InterruptibleTTSService):
    Settings = NeuphonicTTSSettings
    _settings: Settings
```

**4. Constructor** (`neuphonic/tts.py:109-198`) — the four-step settings resolution is the house
pattern, and the comments in the source number them:

```
# 1. Initialize default_settings with hardcoded defaults
# 2. Apply direct init arg overrides (deprecated)
# 3. Apply params overrides — only if settings not provided
# 4. Apply settings delta (canonical API, always wins):  default_settings.apply_update(settings)
```

then:

```python
super().__init__(
    aggregate_sentences=aggregate_sentences,
    text_aggregation_mode=text_aggregation_mode,
    push_stop_frames=True,
    push_start_frame=True,
    pause_frame_processing=True,
    sample_rate=sample_rate,
    settings=default_settings,
    **kwargs,
)
```

⚠ **Those three flags — `push_stop_frames=True`, `push_start_frame=True`,
`pause_frame_processing=True` — are the configuration a streaming websocket TTS wants**
(`neuphonic/tts.py:180-187`). A new service should start there. Note `push_text_frames` is left at
its `True` default, which is correct for a service with no word timestamps.
Neuphonic's own defaults: `url="wss://api.neuphonic.com"`, `sample_rate=22050`,
`encoding="pcm_linear"` (`neuphonic/tts.py:112-119`).

**5. `can_generate_metrics()` → `True`** (`neuphonic/tts.py:200-206`) and
`language_to_service_language()` delegating to the module function (`:208-217`).

**6. `_update_settings(delta)`** (`:219-226`): call `super()`, and if anything changed,
disconnect + reconnect, because the config lives in the connect-time query string.

**7. `setup()`** (`:228-235`): `await super().setup(setup)` then `await self._connect()` —
connect eagerly at pipeline setup, not on first utterance.

**8. `flush_audio(context_id=None)`** (`:237-241`): send the vendor's flush token
(`{"text": "<STOP>"}`).

**9. `_connect()` / `_disconnect()`** (`:243-266`): call `super()` first, then create/cancel the
receive task (`self._receive_task_handler(self._report_error)`) and a keepalive task, then
`_connect_websocket()` / `_disconnect_websocket()`.

**10. `_connect_websocket()`** (`:268-300`): early-return if `self._websocket.state is State.OPEN`;
build the config into a query string dropping `None` values; `headers = {"x-api-key": api_key}`;
`self._websocket = await self._websocket_connect(url, additional_headers=headers)`; fire
`on_connected`. On exception: `push_error(...)`, null the socket, fire `on_connection_error`.

**11. `_disconnect_websocket()`** (`:302-315`): `await self.stop_all_metrics()`, close the socket,
and in a `finally` null it and fire `on_disconnected`.

**12. `_receive_messages()`** — the heart of it, verbatim (`neuphonic/tts.py:317-337`):

```python
async def _receive_messages(self):
    websocket = self._websocket
    if websocket is None:
        return
    async for message in websocket:
        if isinstance(message, str):
            msg = json.loads(message)
            if msg.get("data") and msg["data"].get("audio"):
                await self.stop_ttfb_metrics()
                audio = base64.b64decode(msg["data"]["audio"])
                context_id = self.get_active_audio_context_id()
                frame = TTSAudioRawFrame(audio, self.sample_rate, 1, context_id=context_id)
                await self.append_to_audio_context(context_id, frame)
```

Note the three load-bearing details: `stop_ttfb_metrics()` on audio arrival;
`get_active_audio_context_id()` because the protocol does not echo a context id; and
`append_to_audio_context()` rather than `push_frame()`.

**13. Keepalive** (`:339-351`): a task sleeping `KEEPALIVE_SLEEP = 10` seconds and sending
`{"text": ""}`.

**14. `run_tts`** (`:353-390`), verbatim:

```python
@traced_tts
async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
    try:
        if not self._websocket or self._websocket.state is State.CLOSED:
            await self._connect()
        try:
            await self._send_text(text)
            await self.start_tts_usage_metrics(text)
        except Exception as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
            yield TTSStoppedFrame(context_id=context_id)
            await self._disconnect()
            await self._connect()
            return
        yield None
    except Exception as e:
        yield ErrorFrame(error=f"Unknown error occurred: {e}")
```

⚠ Neuphonic never calls `remove_audio_context()` — it relies on the base class's
`stop_frame_timeout_s` (3 s) idle timeout to close the context and push `TTSStoppedFrame`. **If
Gnani sends an explicit end-of-synthesis message, call `remove_audio_context(context_id)` from the
receive loop instead and save 3 seconds per turn.** That is the single biggest latency difference
between this template and a well-written adapter.

---

## 5. CARTESIA TTS

Source: `src/pipecat/services/cartesia/tts.py` (1018 lines).

Two classes:

| Class | Line | Base |
|---|---|---|
| `CartesiaTTSService` | `cartesia/tts.py:221` | `WebsocketTTSService` |
| `CartesiaHttpTTSService` | `cartesia/tts.py:768` | `TTSService` |

### 5.1 Model identifiers that appear in source

⚠ **Exactly ONE model id is written anywhere in this file: `"sonic-3.6"`.** It appears twice, as
the hardcoded settings default of each service — `cartesia/tts.py:331` (websocket) and
`cartesia/tts.py:852` (HTTP). Grep for `sonic` across the whole clone returns only those two lines
plus a prose mention of "sonic-3 series models" in the `GenerationConfig` docstring
(`cartesia/tts.py:62`).

**There is NO enumeration, `Literal`, or validation of Cartesia model ids in the clone** —
`model` is a free-form `str` on `TTSSettings`, put straight into the request as `"model_id"`
(`cartesia/tts.py:524` websocket, `cartesia/tts.py:969` HTTP). Any string is accepted by Pipecat
and rejected, or not, by Cartesia.

⚠ **`"sonic-3.5"` — the id Calevate's `voices.TtsModel` literal carries — DOES NOT APPEAR IN THIS
SOURCE.** That is not evidence it is wrong: Pipecat validates nothing here, so any id we pass is
sent verbatim. But it means **this clone cannot confirm `sonic-3.5` exists or is current**, and
Cartesia's own docs are the only thing that can. Treat the id in `apps/api/agents/voices.py` as
REPORTED until someone reads Cartesia's model list. What the clone *does* tell us is that
Pipecat's own default has moved on to `sonic-3.6`.

API version is **pinned, not configurable**: `_CARTESIA_API_VERSION = "2026-03-01"`
(`cartesia/tts.py:41`), sent as the `Cartesia-Version` header (`cartesia/tts.py:586`). The
`cartesia_version` constructor argument is deprecated since 1.8.0 with **no replacement** —
"the service sends the API version it is written against, so overriding it can break request and
response handling" (`cartesia/tts.py:43-55`).

### 5.2 `CartesiaTTSService.__init__`

`cartesia/tts.py:246-264`:

```python
def __init__(
    self,
    *,
    api_key: str,
    voice_id: str | None = None,            # DEPRECATED 0.0.105 -> settings.voice
    cartesia_version: str | None = None,    # DEPRECATED 1.8.0, no replacement
    url: str = "wss://api.cartesia.ai/tts/websocket",
    model: str | None = None,               # DEPRECATED 0.0.105 -> settings.model
    sample_rate: int | None = None,
    encoding: str = "pcm_s16le",
    container: str = "raw",
    max_buffer_delay_ms: int | None = None,
    params: InputParams | None = None,      # DEPRECATED 0.0.105 -> settings
    extra_headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    text_aggregation_mode: TextAggregationMode | None = None,
    aggregate_sentences: bool | None = None,   # DEPRECATED 0.0.104
    **kwargs,
)
```

Hardcoded settings defaults (`cartesia/tts.py:329-336`): `model="sonic-3.6"`, `voice=None`,
`language=Language.EN`, `generation_config=None`, `pronunciation_dict_id=None`.

Base-class flags it passes (`cartesia/tts.py:361-370`) — **and how they differ from the
Neuphonic/Gnani shape in §4.8**:

```python
super().__init__(
    text_aggregation_mode=text_aggregation_mode,
    aggregate_sentences=aggregate_sentences,
    push_text_frames=False,      # Cartesia emits its own per-word TTSTextFrames
    pause_frame_processing=False,
    sample_rate=sample_rate,
    push_start_frame=True,
    settings=default_settings,
    **kwargs,
)
```

`push_text_frames=False` because "Cartesia gives us word-by-word timestamps. We can use those to
generate text frames ourselves aligned with the playout timing of the audio"
(`cartesia/tts.py:324-328`). Note also `push_stop_frames` is **not** set (so it stays `False`) —
Cartesia appends its own `TTSStoppedFrame` on the `done` message (`cartesia/tts.py:690`).

`max_buffer_delay_ms` — "Server-side buffering window before generation starts. `0` disables
server buffering (custom buffering); any value in (0, 5000] enables managed buffering. If `None`,
derived from `text_aggregation_mode`: `0` for `SENTENCE` (avoids stacking client and server
buffering), unset for `TOKEN` (uses Cartesia's 3000ms default)" (`cartesia/tts.py:289-295`,
implemented `cartesia/tts.py:391-396`). ⚠ The "3000ms default" is a **claim about Cartesia's
server**, sourced only from this comment — REPORTED, not verified.

A `SkipTagsAggregator` for `<spell>…</spell>` is installed unconditionally
(`cartesia/tts.py:372-380`).

`CartesiaTTSSettings` (`cartesia/tts.py:206-219`), on top of `TTSSettings`
(`model`/`voice`/`language`):

| Field | Type | Default |
|---|---|---|
| `generation_config` | `GenerationConfig \| None \| NotGiven` | `NOT_GIVEN` |
| `pronunciation_dict_id` | `str \| None \| NotGiven` | `NOT_GIVEN` |

`GenerationConfig` (`cartesia/tts.py:58-76`) is a pydantic model: `volume: float | None = None`
(documented valid range [0.5, 2.0], default 1.0), `speed: float | None = None` (range [0.6, 1.5],
default 1.0), `emotion: str | None = None`. Those ranges are docstring claims about Cartesia's
API — REPORTED, and not enforced in code.

`CartesiaEmotion` is a `StrEnum` of **60 values** (`cartesia/tts.py:140-204`), from `NEUTRAL`
through `DETERMINED`, including `JOKING_COMEDIC = "joking/comedic"`.

### 5.3 Languages

`language_to_cartesia_language()` (`cartesia/tts.py:78-136`) maps 44 base-language codes.
**Telugu is present: `Language.TE → "te"` (`cartesia/tts.py:126`)**, alongside `hi`, `bn`, `gu`,
`kn`, `ml`, `mr`, `or`, `pa`, `ta`, `ur`.

⚠ These are **base codes, not `xx-IN` regional codes** — this map keys off `Language.TE`, not
`Language.TE_IN`, and `resolve_language(..., use_base_code=True)` means an unmapped regional code
falls back to its base and logs a warning (`cartesia/tts.py:135`). So `Language.TE_IN` resolves to
`"te"` via the fallback path, with a warning. **AMBIGUOUS IN SOURCE** whether that warning is
expected operation or a signal to pass `Language.TE` directly; the clone does not say. Passing
`Language.TE` avoids the warning.

### 5.4 Wire protocol

Request payload, `_build_msg()` (`cartesia/tts.py:506-547`):

```python
{
  "transcript": text,
  "continue": continue_transcript,          # True for a normal utterance
  "context_id": context_id,
  "model_id": self._settings.model,
  "voice": {"mode": "id", "id": self._settings.voice},
  "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": <resolved>},
  "add_timestamps": True,
  "use_normalized_timestamps": False,
  # optional:
  "max_buffer_delay_ms": ..., "language": ...,
  "generation_config": {...}, "pronunciation_dict_id": ...,
}
```

`_output_sample_rate` is set from `self.sample_rate` in `setup()` (`cartesia/tts.py:549-556`).

Connect (`cartesia/tts.py:577-593`): `self._websocket_connect(self._url, additional_headers={
"X-API-Key": api_key, "Cartesia-Version": self._cartesia_version, **extra_headers})`, then fire
`on_connected`. On failure: `push_error`, null the socket, fire `on_connection_error`.
`_disconnect_websocket()` calls `stop_all_metrics()`, closes, and in `finally` calls
`remove_active_audio_context()` before firing `on_disconnected` (`cartesia/tts.py:595-608`).

Server messages, `_process_messages()` (`cartesia/tts.py:683-724`) — a message whose
`context_id` is not an available audio context is **dropped** (`cartesia/tts.py:685-687`):

| `type` | Handling |
|---|---|
| `chunk` | `TTSAudioRawFrame(base64.b64decode(msg["data"]), self.sample_rate, 1, context_id=ctx_id)` appended to the context (`:707-714`) |
| `timestamps` | `_normalize_word_timestamps(msg["word_timestamps"]["words"], [...]["start"])` → `add_word_timestamps(...)` (`:694-706`) |
| `done` | `stop_ttfb_metrics()`, append `TTSStoppedFrame(context_id=...)`, `remove_audio_context(ctx_id)` (`:689-692`) |
| `error` | push `TTSStoppedFrame`, `stop_all_metrics()`, `push_error`, `reset_active_audio_context()` (`:715-719`) |
| `flush_done` | acknowledged silently — "each turn already has its own context_id" (`:720-726`) |
| anything else | `push_error("Error, unknown message type: ...")` (`:727-728`) |

⚠ `_receive_messages()` is an **infinite loop that reconnects on exit**: "Cartesia times out after
5 minutes of inactivity (no keepalive mechanism is available). So, we try to reconnect."
(`cartesia/tts.py:730-736`). That 5-minute figure is a REPORTED claim about Cartesia in a code
comment.

`run_tts` (`cartesia/tts.py:738-766`) is the same shape as Neuphonic's: reconnect if closed, send
`_build_msg(text=text, context_id=context_id)`, `start_tts_usage_metrics(text)`, `yield None`; on
send failure yield `ErrorFrame` + `TTSStoppedFrame`, disconnect, reconnect, return.

**Interruption**: `on_audio_context_interrupted()` (`cartesia/tts.py:614-620`) calls
`stop_all_metrics()` and sends `{"context_id": ctx, "cancel": True}` — this is why Cartesia
subclasses `WebsocketTTSService` and **not** `InterruptibleTTSService`: it has a real cancel
message and does not need the reconnect. `on_audio_context_completed()` is a documented no-op:
"the server already considers the context done once it has sent its `done` message"
(`cartesia/tts.py:622-629`).

**Flush**: `flush_audio(context_id=None)` (`cartesia/tts.py:631-643`) sends
`_build_msg(text="", continue_transcript=False, context_id=flush_id)`.

**Runtime settings changes** (`cartesia/tts.py:645-681`): "Voice, model, and language are locked
per Cartesia context." Changing any of the three finalises the pending sentence, flushes the
context, and assigns a **new** turn context id so the next sentence opens a fresh Cartesia context.

**Text-tag helpers** — static methods on the service (`cartesia/tts.py:421-444`):
`SPELL(text)` → `<spell>…</spell>`; `EMOTION_TAG(CartesiaEmotion)` → `<emotion value="…" />`;
`PAUSE_TAG(seconds)` → `<break time="Ns" />`; `VOLUME_TAG(ratio)`; `SPEED_TAG(ratio)`.
Tags are stripped out of word-timestamp tokens before they become text frames
(`cartesia/tts.py:459-478`).

### 5.5 `CartesiaHttpTTSService`

`cartesia/tts.py:793-808`:

```python
def __init__(
    self,
    *,
    api_key: str,
    voice_id: str | None = None,       # DEPRECATED
    model: str | None = None,          # DEPRECATED
    base_url: str = "https://api.cartesia.ai",
    cartesia_version: str | None = None,   # DEPRECATED 1.8.0
    aiohttp_session: aiohttp.ClientSession | None = None,
    sample_rate: int | None = None,
    encoding: str = "pcm_s16le",
    container: str = "raw",
    params: InputParams | None = None,     # DEPRECATED
    extra_headers: dict[str, str] | None = None,
    settings: Settings | None = None,
    **kwargs,
)
```

Same `model="sonic-3.6"` default (`cartesia/tts.py:852`). Same `Settings` class. No word
timestamps and no context cancel — it is the non-streaming fallback, not the telephony path.

---

## 6. BYOK LLM — custom `base_url` + `api_key`, Azure, Gemini

### 6.1 OpenAI-compatible with a custom base URL

`BaseOpenAILLMService.__init__` (`src/pipecat/services/openai/base_llm.py:150-165`):

```python
def __init__(
    self,
    *,
    model: str | None = None,          # DEPRECATED 0.0.105 -> settings.model
    api_key=None,
    base_url=None,
    organization=None,
    project=None,
    default_headers: Mapping[str, str] | None = None,
    service_tier: str | None = None,
    params: InputParams | None = None,  # DEPRECATED 0.0.105
    settings: Settings | None = None,
    retry_timeout_secs: float | None = 5.0,
    retry_on_timeout: bool | None = False,
    **kwargs,
)
```

`base_url` and `api_key` are passed straight to `create_client()`
(`openai/base_llm.py:243-251`), which constructs the SDK client
(`openai/base_llm.py:254-291`):

```python
return AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
    organization=organization,
    project=project,
    http_client=DefaultAsyncHttpxClient(
        limits=connection_limits(max_keepalive_connections=100, max_connections=1000,
                                 keepalive_expiry=None)
    ),
    default_headers=default_headers,
)
```

⚠ `api_key=None` means the OpenAI SDK reads `OPENAI_API_KEY` from the environment
(docstring `openai/base_llm.py:175`). For BYOK, **always pass `api_key` explicitly** so no
ambient key can be picked up — this matters for `tests/conftest._no_ambient_credentials` in the
Calevate repo.

`OpenAILLMService` (`src/pipecat/services/openai/llm.py:15-98`) adds only context aggregation and
a `service_tier` passthrough. Hardcoded default model: **`"gpt-4.1"`** (`openai/llm.py:56`, and
the same in the base at `openai/base_llm.py:233`).

`OpenAILLMSettings` (`openai/base_llm.py:49-72`) overrides the inherited numeric fields to also
accept the OpenAI SDK's own `NotGiven` sentinel, so they pass through to the client unchanged:
`frequency_penalty`, `presence_penalty`, `seed`, `temperature`, `top_p`, `max_tokens`,
`max_completion_tokens` — all defaulting to `NOT_GIVEN`. Base `LLMSettings`
(`src/pipecat/services/settings.py:294-340`) supplies `model`, `system_instruction`,
`temperature`, `max_tokens`, `top_p`, `top_k`, `frequency_penalty`, `presence_penalty`, `seed`,
plus two fields deprecated in 1.7.0 (`filter_incomplete_user_turns`,
`user_turn_completion_config`).

⚠ **`settings.extra: dict` is the escape hatch** for provider-specific request fields
(`openai/llm.py:68`, `openai/base_llm.py:245`) — that is where a GPT-5-style trap parameter would
go if the standard fields cannot express it.

`retry_on_timeout=False` by default; when `True`, a request producing no output within
`retry_timeout_secs` (5.0) is abandoned and re-issued, and "the retry is unbounded"
(`openai/base_llm.py:183-189`).

**Dozens of the `services/*` directories are OpenAI-compatible subclasses** created exactly this
way (cerebras, deepseek, fireworks, groq, grok, mistral, nebius, novita, openrouter, perplexity,
qwen, sambanova, together, ollama, …). Subclassing `OpenAILLMService` and overriding
`create_client()` is therefore the established pattern for any OpenAI-compatible endpoint.

### 6.2 A dedicated Azure service EXISTS

**Yes** — `AzureLLMService` at `src/pipecat/services/azure/llm.py:44`, subclassing
`OpenAILLMService`.

```python
def __init__(
    self,
    *,
    endpoint: str,
    api_key: str | None = None,
    token_provider: AzureTokenProvider | None = None,
    model: str | None = None,            # DEPRECATED 0.0.105 -> settings.model
    api_version: str | None = None,      # DEPRECATED 1.8.0
    settings: Settings | None = None,
    **kwargs,
)
```
(`azure/llm.py:66-76`)

**This maps exactly onto Calevate's declared in-call leg.** Facts from the source:

- **The endpoint shape selects the API surface.** `V1_ENDPOINT_PATH = "/openai/v1"`
  (`azure/llm.py:26`); `self._use_v1_api = endpoint.rstrip("/").endswith(V1_ENDPOINT_PATH)`
  (`azure/llm.py:140`). The docstring example is literally
  `endpoint="https://my-resource.openai.azure.com/openai/v1"` (`azure/llm.py:59`) — the same URL
  `apps/api/.../azure_openai_base_url(resource)` emits.
- **On the v1 surface the plain `AsyncOpenAI` client is used, not `AsyncAzureOpenAI`**, with
  `base_url = endpoint.rstrip("/") + "/"` (`azure/llm.py:154-161`). The comment says why:
  "`AsyncAzureOpenAI` appends its own `/openai` path segment, which the endpoint already carries."
- **`api_version` does not apply on the v1 surface** and is deprecated since 1.8.0 with no
  replacement: "Azure issued no dated version after 2025-04-01-preview, and new features reach only
  the v1 API surface" (`azure/llm.py:111-119`). The non-v1 path still sends
  `DATED_API_VERSION = "2025-04-01-preview"` (`azure/llm.py:29`).
  ⚠ This is Pipecat's reading of Azure's behaviour, recorded in a docstring — **REPORTED, not
  verified against Microsoft**. It does however **corroborate** the Calevate position that the v1
  surface takes no `api_version`; it does not close OPERATIONS §2 gate 16f, because Pipecat is not
  a primary source for Azure.
- **Auth**: either a static `api_key` **or** a `token_provider` — `AzureTokenProvider =
  Callable[[], Awaitable[str]]`, "Matches `azure.identity.aio.get_bearer_token_provider` used with
  the `https://ai.azure.com/.default` scope" (`azure/llm.py:19-24`). Exactly one is required;
  neither raises `ValueError("Either `api_key` or `token_provider` is required.")`
  (`azure/llm.py:108-109`).
  ⚠ Note on the v1 path the token provider is passed **as the `api_key` argument**:
  `AsyncOpenAI(api_key=self._token_provider or api_key, ...)` (`azure/llm.py:158-161`).
- **`settings.model` is the DEPLOYMENT name on Azure.** The docstring example says so:
  `settings=AzureLLMService.Settings(model="my-deployment")` (`azure/llm.py:60`). This confirms
  Calevate's `azure_openai_deployment` ≠ `azure_openai_model` distinction at the adapter boundary.
- Hardcoded default model: `"gpt-4.1"` (`azure/llm.py:122`).
- `AzureLLMSettings` is `BaseOpenAILLMService.Settings` with no additions (`azure/llm.py:37-41`).

**NOT FOUND IN SOURCE:** any region field, any residency assertion, or anything that infers a
region from the endpoint. `AzureLLMService` treats the endpoint as an opaque URL — consistent with
Calevate's own finding that `<resource>.openai.azure.com` names no region.

### 6.3 Google Gemini

`GoogleLLMService` at `src/pipecat/services/google/llm.py:157`, `LLMService[GeminiLLMAdapter]`:

```python
def __init__(
    self,
    *,
    api_key: str,                        # REQUIRED, no env fallback
    model: str | None = None,            # DEPRECATED 0.0.105
    params: InputParams | None = None,   # DEPRECATED 0.0.105
    settings: Settings | None = None,
    system_instruction: str | None = None,   # DEPRECATED 0.0.105
    tools: list[dict[str, Any]] | None = None,
    tool_config: dict[str, Any] | None = None,
    http_options: HttpOptions | None = None,
    stream_idle_timeout_secs: float | None = 20.0,
    retry_timeout_secs: float | None = 5.0,
    retry_on_timeout: bool | None = False,
    **kwargs,
)
```
(`google/llm.py:205-220`)

- Client: `genai.Client(api_key=self._api_key, http_options=self._http_options)`
  (`google/llm.py:333-335`) — the **Developer API**, keyed, no region argument. This corroborates
  Calevate's finding that Google's Developer API has no region to request.
- Hardcoded default model: **`"gemini-3.6-flash"`** (`google/llm.py:270`).
- `stream_idle_timeout_secs=20.0` — "How long to wait for the next chunk of a streamed response
  before giving up on it. Bounds the wait when the API accepts a request and then stops producing
  without closing the stream" (`google/llm.py:249-256`). **This is Pipecat's guard against exactly
  the failure mode Calevate's Gemini-trap note describes.** It is a gap between chunks, not a
  total-response limit; `None` waits indefinitely.

**The thinking controls, which bear directly on the `gemini-3.*` decision in `CLAUDE.md`.**

`GoogleThinkingConfig` (`google/llm.py:84-115`): `thinking_budget: int | None`,
`thinking_level: Literal["low","high","medium","minimal"] | str | None`,
`include_thoughts: bool | None`. Set **either** level or budget, never both
(`google/llm.py:87-88`).

Pipecat applies **model-aware low-latency defaults** in `_maybe_unset_thinking_budget()`
(`google/llm.py:485-510`), unless the caller already set `thinking_config`:

```python
if model.startswith("gemini-2.5-flash"):
    generation_params["thinking_config"] = {"thinking_budget": 0}
elif model.startswith("gemini-3") and "flash" in model:
    level = <lowest level this model accepts, default "minimal">
    generation_params["thinking_config"] = {"thinking_level": level}
```

with `_LOWEST_MODEL_THINKING_LEVELS = {"gemini-3.7-flash": "low"}` (`google/llm.py:74-76`) and
`_MODELS_SUPPORTING_THINKING_LEVEL = ("gemini-3",)` (`google/llm.py:81`).

**What this means for Calevate, stated carefully:**

- The clone **corroborates** that `thinking_budget: 0` is the 2.5-flash mechanism and that
  Gemini 3 uses `thinking_level` instead (`google/llm.py:78-81`, `497-508`).
- It **also shows Pipecat does not leave Gemini 3 thinking on**: it sends the lowest level the
  model accepts, `"minimal"` by default. Per the `GoogleThinkingConfig` docstring, Gemini 3 Flash
  accepts `"minimal"`, but **Gemini 3.7 Flash accepts only `"low"`, `"medium"`, `"high"`**
  (`google/llm.py:91-96`) — hence the special case. So the shape of the problem Calevate recorded
  ("3.x do not support full thinking-off") is consistent with what this code does; **but this is a
  Pipecat docstring, not Google's documentation, and it is REPORTED evidence, not primary.**
  It does not by itself justify changing `selectable=False` on `gemini-3.*`.
- The failure mode Calevate fears — a candidate with no content — is guarded here only by
  `stream_idle_timeout_secs`, which bounds the wait but does not produce audio. **NOT FOUND IN
  SOURCE:** any handling that turns an empty Gemini candidate into a recoverable error.

`_warn_if_thinking_budget_ignored()` (`google/llm.py:464-483`) logs a warning when a
`thinking_budget` is set on a `gemini-3*` model, because "whether a budget set alongside one is
honored, quietly ignored, or rejected varies by model and by backend, and the rejection names no
field, so this warning is the only signal the caller gets".

**Vertex**: `GoogleVertexLLMService` exists at `src/pipecat/services/google/vertex/llm.py:48`,
subclassing `GoogleLLMService`, taking `credentials` / `credentials_path` (service-account JSON)
and `location: str = "global"` (`vertex/llm.py:63-69`). It **rejects `api_key`** with
`"Invalid parameter 'api_key'. Use 'credentials' or 'credentials_path' for Vertex AI
authentication."` (`vertex/llm.py:115-127`). Its docstring says `"global"` is "the only location
that serves the Gemini 3 series" (`vertex/llm.py:90-91`) — again Pipecat's REPORTED claim about
Google. **Calevate has ruled Vertex out of the product (D-410), so this is noted only so the
next reader does not mistake it for an option the adapter should carry.**

### 6.4 What Calevate would actually construct

Three services, all first-party, all taking our own keys:

| Calevate leg | Pipecat class | Key argument |
|---|---|---|
| `azure_openai` | `AzureLLMService(endpoint=".../openai/v1", api_key=..., settings=Settings(model=<deployment>))` | static `api_key` |
| `openai` | `OpenAILLMService(api_key=..., settings=Settings(model="gpt-5.4-mini"))` | `api_key` |
| `google` | `GoogleLLMService(api_key=..., settings=Settings(model="gemini-2.5-flash-lite"))` | `api_key` |

⚠ **NOT FOUND IN SOURCE: any trap registry.** Pipecat has no equivalent of
`LlmModelSpec.traps` / `ModelConfig.llm_traps`. A GPT-5 model that rejects `temperature` will
reject it here too unless `temperature` is left at `NOT_GIVEN` (its default) or the trap is
expressed through `settings.extra`. The Calevate trap layer stays ours.

---

## 7. TURN DETECTION (smart turn)

Source: `src/pipecat/audio/turn/smart_turn/` in full —
`base_smart_turn.py` (282), `local_smart_turn_v3.py` (183), `local_smart_turn_v2.py` (207),
`local_coreml_smart_turn.py` (95), `http_smart_turn.py` (123), `_whisper_features.py` (175),
`__init__.py` (0 bytes), plus `data/smart-turn-v3.2-cpu.onnx`. Also
`src/pipecat/audio/turn/base_turn_analyzer.py` and `src/pipecat/turns/user_turn_strategies.py`.

### 7.1 The four variants

| Class | Module | Status | Backend |
|---|---|---|---|
| `LocalSmartTurnAnalyzerV3` | `local_smart_turn_v3.py:28` | **LIVE — the default** | ONNX Runtime, bundled model |
| `HttpSmartTurnAnalyzer` | `http_smart_turn.py:24` | LIVE | remote HTTP inference |
| `LocalSmartTurnAnalyzerV2` | `local_smart_turn_v2.py:42` | DEPRECATED 0.0.106, removed 2.0.0 → V3 | PyTorch + transformers (Wav2Vec2) |
| `LocalCoreMLSmartTurnAnalyzer` | `local_coreml_smart_turn.py:36` | DEPRECATED 0.0.106, removed 2.0.0 → V3 | CoreML (Apple silicon) |

⚠ **`LocalSmartTurnAnalyzerV3` is the DEFAULT user-turn-stop strategy in 1.10.0** — you get it
without asking. `default_user_turn_stop_strategies()`
(`src/pipecat/turns/user_turn_strategies.py:45-53`) returns
`[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]`, and
`UserTurnStrategies.__post_init__` installs it whenever no stop strategy is given
(`user_turn_strategies.py:76-80`). This is why the shipped example
`examples/turn-management/turn-management-smart-turn-local.py` never mentions a smart-turn class:
constructing `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())` is enough.

**For Calevate that means smart turn is ON by default on every Pipecat pipeline** — an 8.7 MB
ONNX model loaded and an inference thread per analyzer, on every call. It has to be an explicit
decision, not a default we inherit unexamined.

### 7.2 Installation — confirmed, no extra needed for the ONNX path

`onnxruntime~=1.24.3` and `soxr~=1.0.0` are **base dependencies**, not extras
(`pyproject.toml:51` and `:40`, inside the top-level `dependencies` list that runs from
`pyproject.toml:21` to `:52`). The `onnxruntime` entry carries the comment:

```
# Required by LocalSmartTurnAnalyzerV3
# Inlined here instead of using a self-referential extra for Poetry compatibility.
```
(`pyproject.toml:49-51`)

**The ONNX model file ships inside the wheel**: `src/pipecat/audio/turn/smart_turn/data/
smart-turn-v3.2-cpu.onnx`, **8,679,182 bytes** (measured on disk, this clone). It is loaded
through `importlib_resources` from package `pipecat.audio.turn.smart_turn.data`
(`local_smart_turn_v3.py:48-66`). **No download, no HuggingFace call, no network at any point.**

The two deprecated local analyzers DO need an extra:
`local-smart-turn = ["coremltools>=8.0", "transformers>=4.48.0,<6", "torch>=2.5.0,<3",
"torchaudio>=2.5.0,<3"]` (`pyproject.toml:108`), and both raise `ImportError` at import time
without it (`local_smart_turn_v2.py:21-35`, `local_coreml_smart_turn.py:21-30`).
V2 additionally falls back to the HuggingFace model id `"pipecat-ai/smart-turn-v2"` when no path
is given (`local_smart_turn_v2.py:63-66`) — i.e. **a network fetch**. V3 does not.

### 7.3 Construction

```python
class LocalSmartTurnAnalyzerV3(BaseSmartTurn):
    def __init__(self, *, smart_turn_model_path: str | None = None, cpu_count: int = 1, **kwargs)
```
(`local_smart_turn_v3.py:35`)

- `smart_turn_model_path=None` → the bundled `smart-turn-v3.2-cpu.onnx`
  (`local_smart_turn_v3.py:48-66`).
- `cpu_count=1` → `SessionOptions.intra_op_num_threads`. The full ONNX session config
  (`local_smart_turn_v3.py:70-76`):

```python
so = ort.SessionOptions()
so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
so.inter_op_num_threads = 1
so.intra_op_num_threads = cpu_count
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
self._session = ort.InferenceSession(smart_turn_model_path, sess_options=so)
```

- `PIPECAT_SMART_TURN_LOG_DATA` (env, falsy by default) writes every analysed segment to
  `./smart_turn_audio_log/<timestamp>_{complete,incomplete}.wav` from a background thread
  (`local_smart_turn_v3.py:46`, `80-121`).
  ⚠ **That directory would contain raw caller audio.** Under Calevate hard rule 6 and
  SECURITY-COMPLIANCE, this env var must never be set in any environment that handles real calls.

```python
class HttpSmartTurnAnalyzer(BaseSmartTurn):
    def __init__(self, *, url: str, aiohttp_session: aiohttp.ClientSession,
                 headers: dict[str, str] | None = None, **kwargs)
```
(`http_smart_turn.py:31-38`)

```python
class LocalSmartTurnAnalyzerV2(BaseSmartTurn):        # deprecated
    def __init__(self, *, smart_turn_model_path: str, **kwargs)        # v2:54
class LocalCoreMLSmartTurnAnalyzer(BaseSmartTurn):    # deprecated
    def __init__(self, *, smart_turn_model_path: str, **kwargs)        # coreml:48
```

`BaseSmartTurn.__init__` (`base_smart_turn.py:60`):

```python
def __init__(self, *, sample_rate: int | None = None, params: SmartTurnParams | None = None)
```

### 7.4 Every sensitivity / timeout parameter

`SmartTurnParams` (`base_smart_turn.py:32-43`), a pydantic model extending the empty
`BaseTurnParams` (`base_turn_analyzer.py:33-36`):

| Field | Type | Default | Constant | Line |
|---|---|---|---|---|
| `stop_secs` | `float` | `3` | `STOP_SECS = 3` | `base_smart_turn.py:41`, `:27` |
| `pre_speech_ms` | `float` | `500` | `PRE_SPEECH_MS = 500` | `:42`, `:28` |
| `max_duration_secs` | `float` | `8` | `MAX_DURATION_SECONDS = 8` | `:43`, `:29` |

What each actually does:

- **`stop_secs` (3 s)** — the hard silence fallback. `append_audio()` accumulates
  `chunk_duration_ms` of non-speech into `_silence_ms`, and at `_silence_ms >= stop_secs*1000`
  returns `EndOfTurnState.COMPLETE` **without running the model at all**, logging "End of Turn
  complete due to stop_secs" (`base_smart_turn.py:129-138`). ⚠ **3 seconds is far too long for an
  Indian telephony agent** and is the first parameter Calevate must tune.
  `stop_secs` is ALSO the HTTP request timeout for `HttpSmartTurnAnalyzer`:
  `aiohttp.ClientTimeout(total=self._params.stop_secs)` (`http_smart_turn.py:67`), and a timeout
  there raises `SmartTurnTimeoutException` which `_process_speech_segment` catches and converts to
  `COMPLETE` (`http_smart_turn.py:100-102`, `base_smart_turn.py:267-271`).
- **`pre_speech_ms` (500 ms)** — audio prepended before speech onset. The effective value is
  `pre_speech_ms + (vad_start_secs * 1000)` (`base_smart_turn.py:215`), where `vad_start_secs`
  comes from the VAD via `update_vad_start_secs()` (`base_smart_turn.py:170-172`).
- **`max_duration_secs` (8 s)** — the segment is truncated to the **last** `max_duration_secs *
  sample_rate` samples (`base_smart_turn.py:232-236`). V3 then independently truncates-or-pads to
  exactly 8 seconds at 16 kHz (`local_smart_turn_v3.py:141-161`), so changing
  `max_duration_secs` away from 8 does not change what the V3 model sees at its input.
- Pre-speech buffer trimming keeps at most
  `pre_speech_ms/1000 + stop_secs + max_duration_secs` seconds of audio
  (`base_smart_turn.py:140-150`).

**The decision threshold is hardcoded at 0.5 and is NOT a parameter.**
`prediction = 1 if probability > 0.5 else 0` (`local_smart_turn_v3.py:174`, and identically in the
CoreML variant at `local_coreml_smart_turn.py:89`). **NOT FOUND IN SOURCE:** any way to configure
the probability threshold — tuning sensitivity requires subclassing `_predict_endpoint`.

### 7.5 Inference path and what the source says about latency

Audio is buffered as int16 PCM views; the float32 conversion is deferred to
`_process_speech_segment` so it "runs once per turn instead of once per ~20 ms audio frame"
(`base_smart_turn.py:110-117`, `225-230`).

The model runs **off the event loop**, on a `ThreadPoolExecutor(max_workers=1)` built lazily —
"One thread per analyzer is enough, since one analyzer handles one audio stream"
(`base_smart_turn.py:76-79`, `178-183`). `analyze_end_of_turn()` awaits it via
`loop.run_in_executor` (`base_smart_turn.py:154-168`).

V3 `_predict_endpoint` (`local_smart_turn_v3.py:138-183`):

1. resample to 16 kHz with `soxr.resample(..., quality="HQ")` if the pipeline rate differs
   (`:123-136`, `_MODEL_SAMPLE_RATE = 16000` at `:25`) — **relevant to Plivo, whose leg is 8 kHz**;
2. truncate-or-zero-pad to exactly 8 s at 16 kHz (`:141-161`);
3. `compute_whisper_log_mel_features(audio_array, do_normalize=True)` — a vendored numpy
   implementation, `_whisper_features.py` (`:164`);
4. `self._session.run(None, {"input_features": input_features})` — input tensor name is
   **`"input_features"`** (`:168`);
5. `probability = outputs[0][0].item()` — "the ONNX model returns sigmoid probabilities" (`:170-171`).

**On latency, the source measures but never asserts a number.** Every inference produces
`TurnMetricsData(processor="BaseSmartTurn", is_complete=..., probability=...,
e2e_processing_time_ms=...)` timed with `time.perf_counter()` around `_predict_endpoint`
(`base_smart_turn.py:241-260`), logged at TRACE level (`:262-266`).
**NOT FOUND IN SOURCE: any stated latency figure, budget, or benchmark for smart turn.**
Anyone who needs one must measure `TurnMetricsData.e2e_processing_time_ms` on our own hardware —
which §8's metrics path makes available.

`cleanup()` shuts the executor down without waiting and nulls it; the analyzer stays usable and
restarts the thread on the next turn, because "a turn strategy is cleaned up and re-applied
whenever the strategies are updated" (`base_smart_turn.py:185-197`).

`EndOfTurnState` is `COMPLETE = 1` / `INCOMPLETE = 2` (`base_turn_analyzer.py:21-30`).

⚠ `HttpSmartTurnAnalyzer._predict_endpoint` **swallows every failure and returns
`{"prediction": 0, "probability": 0.0, ...}`** — i.e. INCOMPLETE — on any error
(`http_smart_turn.py:116-123`). A dead remote endpoint therefore degrades silently to
"user still speaking", and the turn only ends on the `stop_secs` fallback. Another reason the
local V3 path is the right one for a telephony product.

### 7.6 Wiring it

```python
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
```

`TurnAnalyzerUserTurnStopStrategy`
(`src/pipecat/turns/user_stop/turn_analyzer_user_turn_stop_strategy.py:34`):

```python
def __init__(self, *, turn_analyzer: BaseTurnAnalyzer, wait_for_transcript: bool = True, **kwargs)
```

- `wait_for_transcript=True` (default): turn-end fires only after the analyzer says COMPLETE
  **and** either a finalized transcript arrives or "the STT safety-net timeout elapses with text in
  hand" (`turn_analyzer_user_turn_stop_strategy.py:61-72`). That timeout is
  `ttfs_p99_latency` from the STT service's `STTMetadataFrame` — i.e. the `SARVAM_TTFS_P99 = 1.17`
  of §3 (`turn_analyzer_user_turn_stop_strategy.py:43-47`, `:78`). **Sarvam's declared P99 feeds
  directly into Calevate's end-of-turn latency; overriding `ttfs_p99_latency` on the STT service
  with a measured value changes turn timing.**
- `wait_for_transcript=False`: fires as soon as the analyzer says COMPLETE, "independent of
  transcripts ... so transcripts are off the latency critical path"
  (`turn_analyzer_user_turn_stop_strategy.py:65-72`).

Pass the whole thing through the user aggregator:

```python
LLMUserAggregatorParams(
    vad_analyzer=SileroVADAnalyzer(),
    user_turn_strategies=UserTurnStrategies(
        stop=[TurnAnalyzerUserTurnStopStrategy(
            turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=...)),
        )],
    ),
)
```

---

## 8. METRICS

Source: `src/pipecat/metrics/metrics.py` (245 lines, read in full),
`src/pipecat/observers/service_metrics_observer.py`,
`src/pipecat/observers/loggers/metrics_log_observer.py`,
`src/pipecat/utils/tracing/setup.py`.

### 8.1 Every metrics data class

All are pydantic models inheriting `MetricsData(processor: str, model: str | None = None)`
(`metrics.py:19-28`). They travel inside `MetricsFrame(data: list[MetricsData])`, a `SystemFrame`
(`src/pipecat/frames/frames.py:1382-1391`).

| Class | Line | Fields | What it measures |
|---|---|---|---|
| `TTFBMetricsData` | `:31` | `value: float` | Time to first byte, **seconds** |
| `TTFAMetricsData` | `:41` | `ttfa`, `ttfb`, `leading_silence` (all `float`, seconds) | Time from a TTS request to the first **audible** sample. `ttfa = ttfb + leading_silence`. ⚠ "it is not a separate measurement, so don't aggregate both" TTFB and TTFA |
| `TTFATMetricsData` | `:64` | `ttfat`, `ttfb`, `thinking_time` (seconds) | Time from an LLM request to the first **answer** token. `ttfat = ttfb + thinking_time`. A turn that answers with a tool call reports **twice** — once for the call, once for the answer built from the result; "consumers wanting one per user turn keep the first". Text-answering LLMs only; speech-to-speech services never emit it |
| `ProcessingMetricsData` | `:99` | `value: float` | General processing time, seconds |
| `LLMUsageMetricsData` | `:151` | `value: LLMTokenUsage` | LLM token usage |
| `STTUsageMetricsData` | `:181` | `value: STTUsage` | STT audio seconds |
| `TTSUsageMetricsData` | `:191` | `value: int` | **Characters** synthesised |
| `TextAggregationMetricsData` | `:201` | `value: float` | "time from the first LLM token to the first complete sentence — the latency cost of sentence aggregation in the TTS pipeline", seconds |
| `TurnMetricsData` | `:214` | `is_complete: bool`, `probability: float`, `e2e_processing_time_ms: float` | Turn-detection prediction; time measured "from VAD speech-to-silence transition to turn completion", **milliseconds** |
| `SmartTurnMetricsData` | `:233` | adds `inference_time_ms`, `server_total_time_ms` | DEPRECATED 0.0.104 → `TurnMetricsData` |

`LLMTokenUsage` (`metrics.py:109-148`): `prompt_tokens: int`, `completion_tokens: int`,
`total_tokens: int`, and optional `cache_read_input_tokens`, `cache_creation_input_tokens`,
`reasoning_tokens`, `input_audio_tokens`, `output_audio_tokens`,
`cache_read_input_audio_tokens`.

⚠⚠ **THIS PARAGRAPH IS LOAD-BEARING FOR CALEVATE'S COST LEDGER** (hard rule 7,
`unit_cost_paid` per `usage_event`). Verbatim from `metrics.py:112-122`:

> Services differ in whether their input count is reported net or gross of the prompt cache.
> Anthropic and Bedrock report `prompt_tokens` **net**, with the cache counts alongside it;
> OpenAI-compatible services report it **gross**, with the cache counts already inside it.
> `total_tokens` is the gross figure either way, so it stays comparable across services, and it is
> therefore **not always `prompt_tokens + completion_tokens`**. Read the cache fields for the
> breakdown rather than subtracting.
>
> Per-bucket cost accounting has to account for that difference: adding the cache counts to
> `prompt_tokens` double-counts them on a service that reports gross.

Since Calevate's three declared legs (`azure_openai`, `openai`, `google`) would all be billed from
these counters, **`total_tokens` is the only field comparable across providers**, and per-bucket
pricing must not add cache counts to `prompt_tokens` on the OpenAI-compatible legs.

`STTUsage` (`metrics.py:161-178`): `audio_seconds: float`. ⚠ "Values are **incremental deltas**
since the previous usage report; consumers sum them across a session." And the sum means different
things per service class: continuous STT streams all audio including silence (≈ stream duration,
"which is what most streaming providers bill"), segmented STT submits only detected speech.
**Which class Sarvam falls into is not stated in this file** — AMBIGUOUS IN SOURCE, and it decides
whether our STT minutes match the vendor's invoice.

### 8.2 How to subscribe

**Prerequisite:** `PipelineParams(enable_metrics=True, enable_usage_metrics=True)` — both default
`False` (§1.3) — and the service's own `can_generate_metrics()` must return `True`.

Three mechanisms, all via `observers=[...]` on `PipelineWorker` (or `worker.add_observer(...)`,
`src/pipecat/pipeline/worker.py:706`):

**1. `ServiceMetricsObserver`** (`observers/service_metrics_observer.py:121`) — the structured one,
and the right base for Calevate's `usage_events` writer.

```python
def __init__(self, *, time_source: Callable[[], float] = time.time, **kwargs)
```
(`service_metrics_observer.py:152-161`)

Two events (`service_metrics_observer.py:138-143`, registered `:168-169`):

- `on_service_latency(observer, record: ServiceLatencyRecord)`
- `on_service_usage(observer, record: ServiceUsageRecord)`

`ServiceLatencyRecord` (`:50-74`): `kind: ServiceLatencyKind` (`TTFB`/`TTFA`/`TTFAT`,
`:34-39`), `processor`, `model`, `timestamp`, `seconds`, plus optional `ttfb_secs`,
`leading_silence_secs`, `thinking_time_secs`.

`ServiceUsageRecord` (`:77-119`): `kind: ServiceUsageKind` (`STT`/`LLM`/`TTS`, `:42-47`),
`processor`, `model`, `timestamp`, then per-kind optional fields: `audio_seconds` (STT),
`characters` (TTS), and the nine token fields (LLM).

⚠ Design notes that matter (`service_metrics_observer.py:122-136`):
- **Nothing is summed.** "A record arrives per piece of work rather than per turn or per session."
  This is exactly the grain Calevate's append-only `usage_events` wants (hard rule 4).
- **Processing time, text aggregation and turn metrics are deliberately ABSENT** from this
  observer — it reports "what a service made someone wait for", not "what it did with its own
  time". For `TurnMetricsData` use `MetricsLogObserver` or your own `BaseObserver`.
- Deduplication is by frame id: `self._reported: set[int]` (`:163-166`, `:180-183`).

**2. `MetricsLogObserver`** (`observers/loggers/metrics_log_observer.py:32`) — console logging.

```python
def __init__(self, include_metrics: set[type[MetricsData]] | None = None, **kwargs)
```
(`metrics_log_observer.py:65-69`). `None` logs everything; a set filters
(`metrics_log_observer.py:56-62`). It covers `TurnMetricsData`, which `ServiceMetricsObserver`
does not.

**3. Your own `BaseObserver`** (`observers/base_observer.py:108`) — override
`async def on_push_frame(self, data: FramePushed)` (`:129`) or
`async def on_process_frame(self, data: FrameProcessed)` (`:117`) and filter on `MetricsFrame`.
This is the only way to get `ProcessingMetricsData`, `TextAggregationMetricsData` and
`TurnMetricsData` as structured records.

Related observers that ship in the tree:
`observers/user_bot_latency_observer.py` (`LatencyBreakdown`, referenced at
`service_metrics_observer.py:132-134`), `observers/turn_tracking_observer.py`,
`observers/error_observer.py`, `observers/startup_timing_observer.py`,
`observers/speaking_observer.py`, `observers/function_call_observer.py`.

### 8.3 OpenTelemetry

**Supported, behind an optional extra.**
`tracing = ["opentelemetry-sdk>=1.33.0,<2", "opentelemetry-api>=1.33.0,<2",
"opentelemetry-instrumentation>=0.54b0,<1"]` (`pyproject.toml:147`) — i.e.
`uv add "pipecat-ai[tracing]"`. Without it, `OPENTELEMETRY_AVAILABLE = False` and everything
degrades silently (`utils/tracing/setup.py:18-25`).

```python
def setup_tracing(
    service_name: str = "pipecat",
    exporter=None,              # a pre-configured OTel span exporter
    console_export: bool = False,
) -> bool
```
(`utils/tracing/setup.py:37-41`) — returns `False` if OTel is unavailable
(`setup.py:61-62`) or setup raised (`setup.py:87-89`). It creates a `Resource` carrying
`service.name`, `service.instance.id` (from `$HOSTNAME`, default `"unknown"`) and
`deployment.environment` (from `$ENVIRONMENT`, default `"development"`)
(`setup.py:65-72`), sets a global `TracerProvider`, and attaches a `BatchSpanProcessor` per
exporter (`setup.py:78-85`). `is_tracing_available()` at `setup.py:~28-33`.

Pipeline-side switches on `PipelineWorker` (§1.4): `enable_tracing: bool = False`,
`additional_span_attributes: dict | None = None`, `conversation_id: str | None = None`, plus
`turn_trace_observer` (`worker.py:669`). Service methods are instrumented with decorators from
`src/pipecat/utils/tracing/service_decorators.py` — `@traced_tts`, `@traced_stt`, `@traced_llm` —
which is why §4 tells you to decorate `run_tts` with `@traced_tts`.
Span attribute builders live in `utils/tracing/service_attributes.py`; cross-process context in
`utils/tracing/tracing_context.py`; turn spans in `utils/tracing/turn_trace_observer.py`.

⚠ Calevate hard rule 6: **spans and metric records carry `processor` and `model` names, but a
custom observer is the point where transcript text or phone numbers could leak into telemetry.**
`ServiceUsageRecord` and `ServiceLatencyRecord` as shipped carry **no** text and no PII — verified
by reading both models in full (`service_metrics_observer.py:50-119`).

---

## 9. TOOLS / FUNCTION CALLING

Source: `src/pipecat/services/llm_service.py`,
`src/pipecat/adapters/schemas/direct_function.py`.

### 9.1 Handler signature

A handler takes `FunctionCallParams` as its first positional argument, then the tool's own
arguments as **typed keyword parameters**, and returns its result by awaiting
`params.result_callback(...)`. From the shipped example
(`examples/getting-started/07-function-calling.py:36-43`):

```python
async def get_current_weather(params: FunctionCallParams, location: str, format: str):
    """Get the current weather.

    Args:
        location: The city and state, e.g. "San Francisco, CA".
        format: The temperature unit to use. Must be either "celsius" or "fahrenheit". ...
    """
    await params.result_callback({"conditions": "nice", "temperature": "75"})
```

**The docstring IS the schema.** For a "direct function", metadata is "automatically extracted
from their signature and docstring, eliminating the need for accompanying configurations (as
FunctionSchemas or in provider-specific formats)" (`llm_service.py:1041-1043`).

`FunctionCallParams` (`llm_service.py:116-157`), a dataclass:

| Field | Type | Notes |
|---|---|---|
| `function_name` | `str` | |
| `tool_call_id` | `str` | |
| `arguments` | `Mapping[str, Any]` | |
| `llm` | `LLMService[Any]` | |
| `pipeline_worker` | `PipelineWorker` | carries worker-scoped state |
| `context` | `LLMContext` | |
| `result_callback` | `FunctionCallResultCallback` | call with `properties=FunctionCallResultProperties(is_final=False)` for intermediate updates on an async call |
| `app_resources` | `Any = None` | **the same object** passed to `PipelineWorker(app_resources=...)`, by reference — the supported way to give handlers a DB handle or tenant id |
| `worker_runner` | `WorkerRunner \| None = None` | `None` only when the params were built by hand |
| `tool_resources` | property | DEPRECATED 1.2.0 → `app_resources` (`llm_service.py:158-171`) |

### 9.2 Registration

**Preferred (1.10.0): list the functions in the context** — they are registered automatically.
`LLMContext(tools=[get_current_weather, get_restaurant_recommendation])`
(`07-function-calling.py:99`). Mid-session changes go through an `LLMSetToolsFrame`
(`llm_service.py:1035-1038`).

`register_direct_function()` is **DEPRECATED since 1.4.0, removal in 2.0.0**, precisely because
"Direct functions are now registered automatically" (`llm_service.py:1031-1038`).

Explicit registration is still live:

```python
def register_function(
    self,
    function_name: str | None,      # None = catch-all handler for every call
    handler: Any,
    *,
    cancel_on_interruption: bool | None = None,
    timeout_secs: float | None = None,
    cancellable_by_llm: bool | None = None,
)
```
(`llm_service.py:917-925`)

Option precedence is stated twice: **explicit argument > `@tool_options` decorator > default**
(`llm_service.py:928-931`). Registering a reserved `cancel_<name>` built-in raises `ValueError`
(`llm_service.py:963-967`).

`@tool_options` (`adapters/schemas/direct_function.py:290-296`) attaches options without
registering, so handlers stay at module level:

```python
def tool_options(fn=None, *, cancel_on_interruption: bool = True,
                 timeout_secs: float | None = None, cancellable_by_llm: bool = False)
```

A handler may also carry `_pipecat_cleanup`, a zero-arg async callable awaited at service cleanup
— used e.g. for an MCP connection; recorded once per callable and kept for the service's lifetime
(`llm_service.py:993-1022`).

### 9.3 Timeouts — yes, at two levels

**Global**, on `LLMService.__init__` (`llm_service.py:305-312`):

```python
def __init__(
    self,
    run_in_parallel: bool = True,
    group_parallel_tools: bool = True,
    function_call_timeout_secs: float | None = None,      # <-- global tool timeout
    enable_async_tool_cancellation: bool = False,          # DEPRECATED 1.8.0
    settings: LLMSettings | None = None,
    **kwargs,
)
```

**Per tool**, `timeout_secs` on `register_function` / `@tool_options`, overriding the global one.

What a timeout does, verbatim (`llm_service.py:947-953`): "A call that runs past it is cancelled:
the handler is thrown an `asyncio.CancelledError`, the call is settled as cancelled, **and
inference runs so the LLM can report that it didn't complete**."

⚠ **`function_call_timeout_secs` defaults to `None` — NO TIMEOUT.** A Calevate tool handler that
hangs (a slow CRM write, a DLT lookup) will hold the turn indefinitely unless a timeout is set.
Set it.

Other option semantics:

- `cancel_on_interruption` (default `True`) — when `False` the call is **asynchronous**: "the LLM
  continues the conversation immediately without waiting for the result, and the result is injected
  later via a developer message" (`llm_service.py:938-942`). ⚠ "realtime LLM services deliver only
  the final result to the provider; intermediate streamed results ... are dropped and an error is
  raised" (`llm_service.py:943-947`).
- `cancellable_by_llm` (default `False`) — advertises a `cancel_<name>` tool alongside the real
  one. Only meaningful with `cancel_on_interruption=False` (`llm_service.py:956-961`,
  `direct_function.py:325-333`). Every tool that opts in "also adds a tool for the LLM to weigh".
- `run_in_parallel=True` / `group_parallel_tools=True` — parallel calls, with the LLM triggered
  exactly once after the whole batch completes (`llm_service.py:317-322`).

`LLMService` event handlers (registered `llm_service.py:411-413`): `on_function_calls_started`,
`on_function_calls_cancelled`, `on_completion_timeout`. The example uses the first to speak a
filler line while a tool runs (`07-function-calling.py:95-97`):

```python
@llm.event_handler("on_function_calls_started")
async def on_function_calls_started(service, function_calls):
    await tts.queue_frame(TTSSpeakFrame("Let me check on that."))
```

`FUNCTION_CALL_ERROR_MESSAGE_TEMPLATE = "The function `{function_name}` failed and returned no
result."` (`llm_service.py:301-303`) is what the LLM is told when a handler produces nothing.

---

## 10. INTERRUPTION AND VAD

### 10.1 Where VAD is configured in 1.10.0

⚠ **NOT on `TransportParams`.** Verified by reading the whole model
(`src/pipecat/transports/base_transport.py:66-93`): there is no `vad_analyzer` and no
`turn_analyzer` field. VAD is configured on the **user context aggregator**:

```python
LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
```
(`examples/voice/voice-cartesia.py:80-84`)

### 10.2 `VADParams`

`src/pipecat/audio/vad/vad_analyzer.py:47-60`, a pydantic model:

| Field | Type | Default | Constant line |
|---|---|---|---|
| `confidence` | `float` | `0.7` (`VAD_CONFIDENCE`) | `vad_analyzer.py:25` |
| `start_secs` | `float` | `0.2` (`VAD_START_SECS`) | `:26` |
| `stop_secs` | `float` | `0.2` (`VAD_STOP_SECS`) | `:27` |
| `min_volume` | `float` | `0.6` (`VAD_MIN_VOLUME`) | `:28` |

`VADAnalyzer.__init__(self, *, sample_rate: int | None = None, params: VADParams | None = None)`
(`vad_analyzer.py:71`). It runs the model on its own `ThreadPoolExecutor(max_workers=1)`
(`vad_analyzer.py:90-92`) and applies exponential volume smoothing with a fixed
`_smoothing_factor = 0.2` (`vad_analyzer.py:86-88`).

`SileroVADAnalyzer(*, sample_rate: int | None = None, params: VADParams | None = None)`
(`silero.py:138`). It loads a **bundled** ONNX model, `silero_vad.onnx`, 2,327,524 bytes, from
package `pipecat.audio.vad.data` (`silero.py:149-165`) with `force_onnx_cpu=True`. **Supports
8 kHz and 16 kHz** (`silero.py:134-135`) — so the Plivo 8 kHz leg is covered without resampling.
No network fetch.

Other analyzers in the tree: `audio/vad/aic_quail_vad.py`, `audio/vad/krisp_viva_vad.py`,
plus `audio/vad/vad_controller.py`.

⚠ Note **two different `stop_secs`**: `VADParams.stop_secs` (0.2 s, when VAD declares silence) and
`SmartTurnParams.stop_secs` (3 s, the smart-turn fallback, §7.4). They are unrelated numbers with
the same name and are tuned separately.

### 10.3 Interruption configuration

Interruption is a property of the **user-turn START strategy**, not a transport or pipeline flag.
`BaseUserTurnStartStrategy.__init__` takes `enable_interruptions: bool = True`
(`src/pipecat/turns/user_start/base_user_turn_start_strategy.py:56`, stored `:78`): "If True, the
user aggregator will emit an interruption frame when the user turn starts" (`:63-64`).

Default start strategies (`turns/user_turn_strategies.py:29-42`):
`[VADUserTurnStartStrategy(), TranscriptionUserTurnStartStrategy()]`.

All start strategies shipped (`src/pipecat/turns/user_start/`):

| Strategy | Module | Constructor |
|---|---|---|
| `VADUserTurnStartStrategy` | `vad_user_turn_start_strategy.py` | inherits base |
| `TranscriptionUserTurnStartStrategy` | `transcription_user_turn_start_strategy.py` | inherits base |
| `MinWordsUserTurnStartStrategy` | `min_words_user_turn_start_strategy.py:31` | `(*, min_words: int, use_interim: bool = True, **kwargs)` |
| `WakePhraseUserTurnStartStrategy` | `wake_phrase_user_turn_start_strategy.py:84` | `(*, phrases: list[str], timeout: float = 10.0, single_activation: bool = False, **kwargs)` |
| `ExternalUserTurnStartStrategy` | `external_user_turn_start_strategy.py:45` | `(*, enable_interruptions: bool = True, **kwargs)` |
| `KrispVivaIPUserTurnStartStrategy` | `krisp_viva_ip_user_turn_start_strategy.py` | uses Krisp's IP model "to distinguish genuine user interruptions" so the bot isn't "interrupted by brief acknowledgements or filler words" (`:9-16`) |

⚠ **`MinWordsUserTurnStartStrategy(min_words=N)` is the barge-in filter Calevate most likely
wants on a noisy Indian PSTN leg** — it requires N spoken words before a turn (and therefore an
interruption) starts, with `use_interim=True` counting interim transcripts for earlier detection.

Stop strategies shipped (`src/pipecat/turns/user_stop/`): `TurnAnalyzerUserTurnStopStrategy`
(§7.6), `EagerUserTurnStopStrategy` + `EagerMatchPolicy`, `SpeechTimeoutUserTurnStopStrategy`,
`LLMTurnCompletionUserTurnStopStrategy`, `ExternalUserTurnStopStrategy`,
`ExternalUserTurnCompletionStopStrategy`, `DeferredUserTurnStopStrategy` (via the `deferred()`
wrapper).

`LLMUserAggregatorParams` (`processors/aggregators/llm_response_universal.py:123-180`), full
field list with defaults:

| Field | Type | Default | Line |
|---|---|---|---|
| `add_tool_change_messages` | `bool` | `False` | `:172` |
| `audio_idle_timeout` | `float` | `1.0` — forces speech stop when no audio frames arrive while SPEAKING (e.g. mic muted mid-speech); `0` disables | `:173` |
| `user_turn_strategies` | `UserTurnStrategies \| None` | `None` (→ defaults) | `:174` |
| `user_mute_strategies` | `list[BaseUserMuteStrategy]` | `[]` | `:175` |
| `user_turn_stop_timeout` | `float` | `5.0` | `:176` |
| `user_idle_timeout` | `float` | `0` (disabled) — emits `on_user_turn_idle` | `:177` |
| `vad_analyzer` | `VADAnalyzer \| None` | `None` | `:178` |
| `filter_incomplete_user_turns` | `bool` | `False` — DEPRECATED 1.2.0 | `:179` |
| `user_turn_completion_config` | `UserTurnCompletionConfig \| None` | `None` — DEPRECATED 1.2.0 | `:180` |

`ExternalUserTurnStrategies(enable_interruptions: bool = True)`
(`turns/user_turn_strategies.py:84-110`) is what an STT service asks for when it does its own
endpointing — the `SarvamSTTService(vad_signals=True)` and
`SarvamRealtimeSTTService(endpointing="vad")` paths of §3 both return it from
`service_metadata_frame()`. Its docstring records the distinction that matters:
`ProposedUserStarted/StoppedSpeakingFrame` "leaves the decision here, so the aggregator pushes the
turn frames and broadcasts interruptions"; `UserStarted/StoppedSpeakingFrame` means the emitter
already announced the turn and the aggregator emits nothing
(`turns/user_turn_strategies.py:95-101`).

---

## 11. LIFECYCLE EVENTS

### 11.1 Call start / client connect

On a `FastAPIWebsocketTransport` (the Plivo path), the **input transport's `start()`** does, in
order (`src/pipecat/transports/websocket/fastapi.py:314-333`):

1. start the session-timeout monitor task, if `params.session_timeout` is set;
2. `await self._client.trigger_client_connected()` → fires the `on_client_connected` event;
3. `await self.push_frame(ClientConnectedFrame())` downstream;
4. start the receive-messages task;
5. `await self.set_transport_ready(frame)`.

Hook it:

```python
@transport.event_handler("on_client_connected")
async def on_client_connected(transport, websocket):
    context.add_message({"role": "developer", "content": "Please introduce yourself to the user."})
    await worker.queue_frames([LLMRunFrame()])
```
(`examples/voice/voice-cartesia.py:112-119`)

**That is the canonical way to make the agent speak first** — add a developer message to the
context and queue an `LLMRunFrame()`.

`ClientConnectedFrame` is a `SystemFrame` with no fields, "pushed downstream by the input transport
when a client (participant) connects" (`frames/frames.py:2049-2056`), and is pushed by every
transport that has a connect notion: websocket/fastapi (`fastapi.py:328`),
websocket/server (`server.py:616`), smallwebrtc (`transport.py:1057`), daily
(`transport.py:2987`), livekit (`transport.py:1291`), tavus (`transport.py:1027`).

⚠ **`ClientDisconnectedFrame` DOES NOT EXIST** — grep across the whole clone returns nothing.
Disconnection is an **event only**, not a frame.

### 11.2 Participant join

**NOT APPLICABLE ON A TELEPHONY WEBSOCKET.** `FastAPIWebsocketTransport` registers exactly three
event handlers (`fastapi.py:674-678`):

- `on_client_connected(transport, websocket)`
- `on_client_disconnected(transport, websocket)`
- `on_session_timeout(transport, websocket)`

There is **no participant model** here — one websocket is one call. Multi-participant events
(`on_participant_joined` and friends) belong to the Daily/LiveKit transports, which Calevate does
not use. For the Plivo leg, "participant join" **NOT FOUND IN SOURCE** and "client connected" is
the equivalent.

`SingleClientWebsocketServerTransport` adds a fourth, `on_websocket_ready(transport)`
(`server.py:536-538`, registered `:584`). `WebsocketClientTransport` has only `on_connected` /
`on_disconnected` (`client.py:486-487`, registered `:525-526`).

### 11.3 Call end

Three distinct endings, and they are not interchangeable:

**(a) The caller hangs up (Plivo closes the socket).** `_receive_messages()` falls out of its
`async for`, and if we were not the ones closing, `trigger_client_disconnected()` fires
`on_client_disconnected` (`fastapi.py:392-397`). The shipped pattern is to end the run there:

```python
@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    await runner.cancel()
```
(`examples/voice/voice-cartesia.py:121-124`)

**(b) We hang up.** `await worker.stop_when_done()` queues an `EndFrame`
(`pipeline/worker.py:765-772`), which drains the pipeline, reaches the serializer, and triggers
the Plivo REST hangup (§2.7). `await worker.cancel()` is the immediate version
(`worker.py:832-839`). `await worker.end(reason=...)` drains then ends (`worker.py:774-785`).

**(c) Session timeout.** `params.session_timeout` (seconds) starts a task that sleeps and then
fires `on_session_timeout` (`fastapi.py:398-401`, `314-321`). Default `None` = no timeout.

Pipeline-level terminal hooks (§1.4): `on_pipeline_finished(worker, frame)` fires for
`StopFrame` / `EndFrame` / `CancelFrame` alike — inspect the frame to tell which
(`worker.py:223-232`). `on_pipeline_timeout(worker, frame)` fires when a `StartFrame` never
started or a `CancelFrame` never drained; **there is no `EndFrame` case**
(`worker.py:233-242`).

Idle end: `idle_timeout_secs=300` with `cancel_on_idle_timeout=True` and
`cancel_runner_on_idle_timeout=True` cancels the worker **and the whole runner** (§1.4).

### 11.4 Turn-level events (the ones a CRM/analytics layer wants)

On the **user** aggregator (`processors/aggregators/llm_response_universal.py:655-662`):
`on_user_turn_started`, `on_user_turn_stopped`, `on_user_turn_stop_timeout`,
`on_user_turn_idle`, `on_user_turn_inference_triggered`, `on_user_turn_message_added`,
`on_user_mute_started`, `on_user_mute_stopped`.

On the **assistant** aggregator (`llm_response_universal.py:1596-1599`):
`on_assistant_turn_started`, `on_assistant_turn_stopped`, `on_assistant_thought`,
`on_summary_applied`.

On the **TTS service** (§4.7): `on_connected`, `on_disconnected`, `on_connection_error`,
`on_tts_request(tts, context_id, text)`.

On the **LLM service** (§9.3): `on_function_calls_started`, `on_function_calls_cancelled`,
`on_completion_timeout`.

On the **STT service** (§3.1): `on_connected`, `on_disconnected`, `on_connection_error`, and —
only when `vad_signals` is enabled — `on_speech_started`, `on_speech_stopped`,
`on_utterance_end`.

On the **runner** (§1.5): `on_ready`, `on_error`.

Also available as observers rather than events:
`observers/turn_tracking_observer.py`, `observers/speaking_observer.py`,
`observers/startup_timing_observer.py`, `observers/error_observer.py`,
`observers/function_call_observer.py`, `observers/user_bot_latency_observer.py`.

---

## Appendix: the deprecation list, collected

Every deprecated name this document touched, so the adapter spec can avoid all of them at once.
All are scheduled for removal in **2.0.0**.

| Name | Deprecated since | Replacement |
|---|---|---|
| `PipelineTask` | 1.3.0 | `PipelineWorker` |
| `PipelineTaskParams` | 1.3.0 | `WorkerParams` |
| `PipelineRunner` | 1.3.0 | `WorkerRunner` |
| module `pipecat.pipeline.task` | 1.3.0 | `pipecat.pipeline.worker` |
| `WorkerRunner.run(worker)` positional | 1.3.0 | `add_workers()` then `run()` |
| `WorkerRunner(loop=...)` | 1.5.0 | `task_manager=` |
| `PipelineWorker(tool_resources=...)` | 1.2.0 | `app_resources=` |
| `WebsocketServerParams` / `WebsocketServerCallbacks` / `WebsocketServerInputTransport` | 1.4.0 | `SingleClient*` equivalents |
| `WordTTSService`, `WebsocketWordTTSService`, `InterruptibleWordTTSService`, `AudioContextTTSService`, `AudioContextWordTTSService` | 0.0.105 | `TTSService` / `WebsocketTTSService` / `InterruptibleTTSService` |
| `TTSService.set_model()` / `set_voice()` | 0.0.104 | `TTSUpdateSettingsFrame(...)` |
| `aggregate_sentences=` (all TTS services) | 0.0.104 | `text_aggregation_mode=` |
| `pause_watchdog_timeout_s=` | 1.8.0 | none (unused) |
| every `InputParams` class and bare `model=` / `voice_id=` init arg | 0.0.105 | `settings=Service.Settings(...)` |
| `cartesia_version=` | 1.8.0 | none (version is pinned) |
| `AzureLLMService(api_version=...)` | 1.8.0 | endpoint ending `/openai/v1` |
| `LocalSmartTurnAnalyzerV2`, `LocalCoreMLSmartTurnAnalyzer` | 0.0.106 | `LocalSmartTurnAnalyzerV3` |
| `SmartTurnMetricsData` | 0.0.104 | `TurnMetricsData` |
| `LLMService(enable_async_tool_cancellation=...)` | 1.8.0 | per-tool `cancellable_by_llm=True` |
| `register_direct_function()` | 1.4.0 | list in `LLMContext(tools=[...])` |
| `FunctionCallParams.tool_resources` | 1.2.0 | `.app_resources` |
| `LLMUserAggregatorParams.filter_incomplete_user_turns` / `user_turn_completion_config` | 1.2.0 | `FilterIncompleteUserTurnStrategies()` |
| `LLMSettings.filter_incomplete_user_turns` / `user_turn_completion_config` | 1.7.0 | as above |
| `SarvamSTTService.InputParams`, `model=`, `params=` | 0.0.105 | `settings=` |
| `TransportParams.video_out_bitrate` | 1.1.0 | provider-specific settings |

---

## Appendix: what this document could NOT establish

Recorded so nobody mistakes silence for absence of risk.

1. **`sonic-3.5` does not appear anywhere in the clone** (§5.1). Pipecat validates no Cartesia
   model id, so it would be sent verbatim; whether it exists at Cartesia is UNKNOWN from here and
   needs a reading of Cartesia's own model list.
2. **Whether Plivo's media websocket sends an `Origin` header** (§2.2) — UNKNOWN; decides whether
   `PIPECAT_ALLOWED_ORIGINS` can ever be set on the telephony route.
3. **Whether Sarvam bills as a continuous or segmented STT service** (§8.1) — the two give
   different `audio_seconds` sums, and the clone does not classify Sarvam.
4. **Odia's wire code differs between the two Sarvam classes** (`od-IN` vs `or-IN`, §3.2) —
   AMBIGUOUS IN SOURCE. Irrelevant to Telugu; a warning against assuming the tables are
   interchangeable.
5. **No latency figure for smart turn** (§7.5), and the two STT P99 figures (1.17 s / 1.00 s) are
   Pipecat's REPORTED benchmark numbers, not ours (§3.1, §3.2).
6. **Pipecat's claims about Azure, Cartesia and Google** — the v1 surface taking no `api_version`,
   Cartesia's 3000 ms server buffer and 5-minute idle timeout, Gemini 3.7 Flash's thinking levels,
   Vertex `global` being the only Gemini 3 location — are all **docstring/comment claims by a
   third party**. They corroborate several Calevate positions; none of them is a primary source,
   and none closes an OPERATIONS §2 gate.
7. **No trap registry, no price catalogue, no residency assertion anywhere in Pipecat** (§6.4,
   §6.2). Those layers remain entirely Calevate's.
