# Per-call latency accounting — what we hold, what the vendor documents, what gate 4 must capture

**Date**: 10 Sep 2026. **Subject**: `docs/PRODUCTION-READINESS.md` §B2 "Per-call latency
storage", sequenced after OPERATIONS §2 gate 4. **Repo state**: read-only research; this
file and one corrected row in `docs/PRODUCTION-READINESS.md` §B2 are the only things this
lane wrote. **No migration, no column, no schema was designed here** — choosing a shape
before a real payload is read is the guess hard rule 12 forbids, and the §B2 row is right.

**What this closes**: the research half. On the day gate 4 produces one real
`latency_data` payload and one stopwatch ledger, the shape decision is the checklist in §5
below, not a research project.

---

## 1. The question an operator actually asks

> *"This call took two minutes. Where did the two minutes go?"*

**Answerable today, per call:**

| Quantity | Where it lives | Evidence class |
|---|---|---|
| Total conversation length, whole seconds | `calls.duration_s` (`apps/api/crm/models.py:142`), from the vendor's `conversation_duration` / `telephony_data.duration` (`apps/api/engine/bolna.py:5531,5542`) | REPORTED (vendor-reported number, stored verbatim) |
| Per-turn transcriber / LLM-TTFT / synthesizer-TTFA milliseconds | `call_engine_latency.turns` — `[{turn, stt_ms, llm_ttft_ms, tts_ttfa_ms}]` (`apps/api/crm/models.py:386-470`), written by `apps/workers/pipeline.py:1005 _record_engine_latency` | REPORTED (engine's own measurement of its own pipeline) |
| Per-call time-to-first-audio and the region the execution ran in | `call_engine_latency.time_to_first_audio_ms`, `.region` | REPORTED |
| Fleet/tenant aggregates of the above, grouped by `region`, with a `basis` that withholds a p95 below 20 turns | `GET /v1/ops/engine-latency` (`apps/api/ops/engine_latency.py`, mounted `apps/api/ops/routes.py:1097`) | derived from the above |
| The engine's own document for that call, verbatim | object storage, keyed by `calls.engine_payload_ref` (`apps/workers/pipeline.py:929 _archive_engine_document`) — until the tenant's retention window clears it (`apps/workers/retention.py:1128-1132`, D-179) | VERIFIED (bytes as received) |
| Our post-call **processing** stages (recording copy, archive, latency write, transcript, extraction) | OpenTelemetry spans, `apps/workers/pipeline.py:1082-1190` | **only if tracing is on** — see below |

**NOT answerable today, and each for a structural reason:**

1. **Voice-to-voice latency — the caller's actual experience.** Both ends of the interval
   (caller stops speaking / caller hears audio) are on the PSTN leg, and our stack is not
   in the audio path at all (D-25/D-33). This is why `calls.latency` was dropped
   (`f1a7c39d5be2`) and why nothing here proposes bringing it back. It is a stopwatch or a
   dual-channel recording, typed in — `scripts/pilot/latency.py` is the ledger.
   **Evidence class: VERIFIED (our own architecture).**
2. **Ring / answer time.** There is no `answered_at` anywhere. `calls.started_at` is the
   vendor's `created_at` (execution *created*, i.e. queued) and `calls.ended_at` falls back
   to `updated_at` — the adapter says so in as many words: *"THE VENDOR HAS EXACTLY TWO
   TIMESTAMPS ON AN EXECUTION"* (`apps/api/engine/bolna.py:5512-5529`, D-361). So
   `ended_at - started_at` is **not** talk time and includes dial/queue/ring. The
   difference between it and `duration_s` is un-attributed today.
3. **Endpointing / silence wait per turn.** The vendor's model puts endpointing (50–300 ms)
   inside TTFA (`bolna-findings/mirror/pages/concepts/latency.md:17-31`) but reports no
   per-turn endpointing figure — `apps/api/ops/engine_latency.py:167-170` records the same
   reading. The three stored components therefore do **not** sum to TTFA, and the module
   deliberately refuses a partial sum (`TurnLatency.component_sum_ms`).
4. **Dead air, interruption, transfer wait, cold start attribution.** Nothing is captured.
5. **Our own trace across the process boundary.** `OTEL_EXPORTER_OTLP_ENDPOINT` defaults to
   `None` (`packages/shared/src/calevate_shared/config.py:1304`), so `tracing_enabled()` is
   False unless a deployment sets it, and OPERATIONS §2 **gate 15(b)** — confirm one trace
   spans voice-runtime → ARQ → worker → Postgres in a collector — is **blocked outside this
   repo on a collector endpoint and has never been run** (`docs/OPERATIONS.md:100`). The
   "one trace" statement is a design property of the code (`TRACE_KWARG`,
   `apps/api/core/observability.py:263-266`), **not** an observed one.
   **Evidence class: UNKNOWN (never executed).**
6. And these spans would answer *"where did our post-call pipeline go"*, never *"where did
   the call go"*. No span this repo opens is inside the audio path.

---

## 2. §B2's row was stale in one direction, and the correction narrows the work

§B2 read as though nothing per-call existed. In fact the **engine-reported half is built and
wired end to end**: `latency_data` → `parse_latency_data` (`apps/api/engine/bolna.py:2974`)
→ `ExecutionSnapshot.latency` (`packages/shared/src/calevate_shared/engine.py:4135`) →
`call_engine_latency` (migration `b7d3e91c4a05`, RLS FORCEd, `call_id` UNIQUE, upserted per
re-drive) → `GET /v1/ops/engine-latency`. `apps/api/engine/fake.py:159` carries a sample so
the conformance suite exercises it.

What is genuinely undecided is therefore **narrower than "per-call latency storage"**: it is
whether any of the engine's per-call numbers earns a place **on the call row** (a scalar an
operator or a client sees beside a call), and if so which one. `calls.latency` — the
`{stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_p50, turn_p95}` column — stays dropped either way;
`tests/call_latency_column_test.py` keeps it dropped.

---

## 3. What the vendor documents — VERIFIED-VENDOR-DOCS

All from the hash-pinned read-only mirror (`bolna-findings/mirror/`, `MANIFEST.json`), read
10 Sep 2026. Nothing under `bolna-findings/` was modified.

| Field | Vendor's own description | Cite | Do we read it? |
|---|---|---|---|
| `latency_data.time_to_first_audio` | float, ms, *"from end of caller's utterance to start of agent's audio response"*; *"the most important metric for perceived responsiveness"* | `concepts/call-latencies.md:37,41` | **yes** → `time_to_first_audio_ms` |
| `latency_data.region` | string, *"e.g., `in` for India, `us` for United States"* | `concepts/call-latencies.md:38` | **yes** → `region` (validated as a short code) |
| `latency_data.stream_id` | float, *"Time (ms) to establish the audio stream connection"* | `concepts/call-latencies.md:36` | **NO** |
| `transcriber.time_to_connect` | integer ms to connect to the transcriber | `concepts/call-latencies.md:77` | **NO** |
| `transcriber.turns[].turn_latency[].audio_to_text_latency` | float, *"from audio input to transcribed text"*; example value `20.12` | `:63,80` | yes → `stt_ms`, last sequence only |
| `transcriber.turns[].turn_latency[].text` | *"Transcribed text for this sequence"* — recognised CALLER SPEECH | `:64,81` | **never stored** (hard rules 5/6); `CallLatency` has no text field |
| `llm.time_to_connect` | integer\|null | `:114` | **NO** |
| `llm.turns[].time_to_first_token` / `time_to_last_token` | float ms | `:116-117` | TTFT yes → `llm_ttft_ms`; **TTLT no** |
| `synthesizer.time_to_connect` | integer ms | `:152` | **NO** |
| `synthesizer.turns[].time_to_first_token` / `time_to_last_token` | integer ms, first audio chunk / all audio | `:154-155` | TTFT yes → `tts_ttfa_ms`; **TTLT no** |
| Vendor's own bottleneck thresholds | transcriber >100 ms/sequence, LLM TTFT >1000 ms, synthesizer >500 ms | `:164-200` | LLM one only, as the alarm threshold (`_LLM_TTFT_ALARM_MS`) |
| TTFA composition | *"Endpointing (50–300ms) → Transcription (50–150ms) → LLM first token (100–400ms) → Synthesis first chunk (80–200ms)"*, TTFA is *"the total of these stages"*; vendor targets *"sub-600ms end-to-end"* | `concepts/latency.md:9,17-31` | not modelled |
| Webhook payload shape | *"the same structure as the Raw Call Data … It matches the Get Execution API response format"* | `guides/post-call/polling-call-status-webhooks.md:58` | see §4 |

**The single most important vendor finding, and it is a warning, not a reassurance:** their
own *completed execution* example prints

```json
"latency_data": { "time_to_first_audio": 189.69 }
```

with **no `region`, no `stream_id` and none of the three component blocks**
(`api-reference/executions/get_execution.md:66-68`). The rich shape is documented on the
concepts page; the API reference's worked example carries one scalar. **Which of the two a
live account actually returns is UNKNOWN and is exactly what gate 4 settles.** Our parser
already survives both — an absent block becomes a `parse_warnings` entry, not an exception
(`bolna.py:2974` docstring) — but if the API-reference shape is what arrives, then the only
durable per-call latency this product will ever have is `time_to_first_audio`, and the shape
decision collapses to one nullable numeric.

---

## 4. Is anything being discarded? — NO. No code was written, and here is why

The brief permitted code only if timing the engine already sends us is dropped on the floor.
It is not:

- **Every completed call's raw vendor document is archived to object storage, verbatim**,
  before the latency read: `_archive_engine_document` (`pipeline.py:929`) commits
  `calls.engine_payload_ref` first and PUTs the sealed bytes second, and it runs on **every**
  post-call pass (`pipeline.py:1088-1093`), re-written on every re-drive. So `stream_id`,
  the three `time_to_connect` values and both `time_to_last_token` series — the documented
  fields `parse_latency_data` does not read — **are preserved in the archive**, and gate 4's
  fixture can be produced from a real one. They are not lost; they are unparsed, which is
  the correct posture until a real payload proves them populated.
- **The webhook body is deliberately not archived**, and that is hard rule 3 rather than a
  gap: the receiver takes status hints only and writes one minimal row
  (`apps/voice-runtime/webhook_routes.py:900-912`), and the pipeline then fetches
  `get_execution` itself (`pipeline.py:1081`) — the same document the webhook would have
  carried (`polling-call-status-webhooks.md:58`), from the source TRD §5 calls the truth.
  Nothing timing-shaped is lost by not persisting the ack-path body.
- **A listing-row snapshot cannot clobber a real measurement**: `latency is None` returns
  `"none_reported"` and writes no row (`pipeline.py:1034-1038`).

The **one bounded, non-structural gap** is the retention window: the archive is cleared on
the tenant's own retention clock (`retention.py:1128-1132`), so a payload fixture must be
taken from a **recent** call. That is a note for whoever runs gate 4, not a defect.

---

## 5. What gate 4 must record for the shape to be decidable

Gate 4 (`docs/OPERATIONS.md:85`) already specifies the stopwatch run; this is the list the
*storage* decision needs out of it, and nothing on it can be answered from this repo.

**From ONE real `latency_data`, captured verbatim then redacted** (`redact_latency_data` +
`unredacted_text_paths` refuse a fixture that still carries caller text — never commit an
unredacted one):

1. **Which of the six documented top-level/blocks are actually present on a completed
   execution** — the concepts shape or the API-reference one-scalar shape (§3).
2. **Is `time_to_first_audio` populated on every completed call?** This is the one candidate
   for a per-call scalar: the vendor defines it as end-of-utterance → start-of-agent-audio,
   which is the closest thing to the caller's experience that exists anywhere, minus the
   PSTN transport legs at both ends.
3. **The unit of `audio_to_text_latency`.** Documented example `20.12` does not read as a
   millisecond transcription latency; every other field reads as ms. Until this is settled
   no sum of the three components may be believed (`engine_latency.py:214-217`,
   `pilot/latency.py::units_note`).
4. **Is `region` populated, and does it carry `us` after D-449?** This is the field that
   turns the D-449 geography trade from an argument into a `GROUP BY`.
5. **Are `stream_id` and the three `time_to_connect` values populated?** They are the only
   documented handle on **cold start** — gate 4 already requires first-greeting delay to be
   ledgered separately for that reason.
6. **Turn count on the longest call placed**, to bound the `turns` array.
7. **Does the component sum agree with the stopwatch, within the method's tolerance**
   (250 ms for a human stopwatch — the instrument's own floor)? `evaluate_gate4` produces
   `agrees` / `disagrees` / `not_comparable`.

**From the stopwatch ledger** (`docs/evidence/gate4-observations.json`, read by
`scripts/pilot/latency.py`): voice-to-voice per turn and first-greeting delay per call, each
with its `method`. Ten calls answer the p50 leg and cannot confirm the p95 leg
(`SMALL_N_FINDING`).

**The decision rule that follows, stated in advance so it is not re-argued:**

- **`agrees`** → `time_to_first_audio_ms` is a defensible per-call number. Whether it earns
  a column *on `calls`* or stays where it is (it is already stored per call in
  `call_engine_latency`) is then a UX/query question, not an evidence question — and the
  default answer is **stays where it is**, because `CallEngineLatency`'s docstring gives the
  reason a call-row column would mislead: the name of the thing is *"what the engine
  reported"*, not *"the call's latency"*.
- **`disagrees`** → no vendor number may be surfaced to a client as latency at all, and the
  per-call storage question is **closed rather than deferred**: the honest answer is that
  this product cannot measure the caller's experience and should not print a number that
  claims to.
- **`not_comparable` / the one-scalar payload shape** → gate 4 re-runs; nothing is built.
- In no branch does `calls.latency` return in its dropped `{stt_ms, llm_ttft_ms, tts_ttfa_ms,
  turn_p50, turn_p95}` form. `turn_p50`/`turn_p95` are voice-to-voice by definition and
  nothing can write them honestly.

---

## 6. Explicit UNKNOWNs

- **UNKNOWN** — whether a live Bolna account returns the rich `latency_data` or the
  single-scalar one. Both are in the vendor's own docs (§3).
- **UNKNOWN** — the unit of `audio_to_text_latency`.
- **UNKNOWN** — whether `region` is emitted for a US-hosted execution.
- **UNKNOWN** — every voice-to-voice and first-greeting figure. Zero measurements exist;
  TRD §4a says so and this lane found nothing that contradicts it.
- **UNKNOWN** — whether our own trace actually crosses the Redis boundary in a deployment.
  Gate 15(b) has never run; blocked outside this repo on a collector endpoint.
- **UNKNOWN** — the size of the us-east-1 ↔ India hop D-449 recovered. `~180–230 ms` in
  `apps/api/ops/engine_latency.py:29-32` is an ESTIMATE quoted from the internet and is
  labelled as one there; it must not be restated as a measurement.
- **REPORTED, not verified here** — everything `calls.duration_s`, `started_at` and
  `ended_at` hold. They are the vendor's numbers, stored verbatim.
- **Egress**: `www.bolna.ai` is egress-blocked from this container; every vendor fact above
  comes from the hash-pinned mirror, not from a fetch made this session.
