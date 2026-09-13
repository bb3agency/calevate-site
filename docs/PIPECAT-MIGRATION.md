# Pipecat migration — the construction manual for the engine we run

**Status:** BINDING for `apps/voice-worker/`, `apps/api/engine/pipecat.py` and every change
they require elsewhere. Extends `docs/BACKEND-PATTERNS.md`, which stays the general manual —
module anatomy, bootstrap order, the error ladder, the reliability triad, CAS concurrency and
testing structure all apply unchanged and are not restated here.

**Date:** 13 September 2026.

## 0. What this is built on

| Input | What it establishes | Class |
|---|---|---|
| `docs/evidence/orchestrator-livekit-vs-pipecat-2026-09-12.md` | Pipecat over LiveKit, on five source-read grounds | VERIFIED-OSS |
| `docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` | No monthly floor, `ap-south` exists; the carrier findings | REPORTED |
| `docs/evidence/pipecat-api-surface-2026-09-13.md` | The real API of `pipecat-ai==1.10.0`, at `file:line` | VERIFIED-OSS |
| `docs/evidence/voice-engine-contract-2026-09-13.md` | All 25 methods + 3 attributes, ~55 conformance clauses, the call-site map | VERIFIED-OSS |
| D-592 | `apps/voice-worker/` is a sanctioned home for vendor SDKs | DECISION |
| D-593 | `Clear` → Gnani staged behind an unanswered rate-limit question | DECISION |

**The dependency is pinned at `pipecat-ai==1.10.0`** and the clone read at `f67c18af` was
verified byte-identical to it across the whole tree. Read source from the installed package,
not from a checkout that may drift.

⚠ **The API most people will reach for is deprecated.** `PipelineTask`, `PipelineTaskParams`,
`PipelineRunner`, `AudioContextTTSService` and all four `*Word*TTSService` classes are
removal-in-2.0.0 shims. Use `PipelineWorker`, `WorkerParams`, `WorkerRunner`, and
`TTSService` / `WebsocketTTSService` / `InterruptibleTTSService`. The deprecation table is in
the API reference's first appendix.

## 1. THE THREE DECISIONS

The contract inventory §9.5 named these as decisions rather than consequences. Each is
settled here and each becomes a decision-log row when the code that emits it lands.

### 1.1 `AgentHosting` gains `owned_runtime`, and the read-back becomes an ATTESTATION

**The problem.** `AgentHosting = Literal["control_plane", "external_deployment"]` has no
member for a framework we run, and both existing values are wrong in ways that matter.
`control_plane` makes `get_agent` a read-back of our own configuration — the exact defect its
docstring forbids (*"agrees with the caller by construction"*), which turns gate 2's
APPLIED-not-merely-ACCEPTED property from false into unfalsifiable. `external_deployment`
makes `publish_agent` refuse, so nothing is ever `live`, on a ground (*"there is no agent
record to write and no read-back to prove"*) that is untrue of us.

**The member:** `owned_runtime` — we hold the agent record AND run the program. Not
`self_hosted`, which would be false: the container runs on Pipecat Cloud. What is ours is the
runtime, not the metal.

**What replaces the read-back, and this is the load-bearing half.** Under a rented engine the
vendor is an independent witness: we ask it what it is running and it may disagree with us.
Delete the vendor and you delete the witness — unless something else can disagree.

Something can: **the running worker, about what it actually loaded.**

```
agent_config_versions          immutable, content-addressed
  id                           uuid_v7
  agent_id                     FK
  prompt_sha256                sha256 of the composed prompt, ours
  model_config_sha256          sha256 of the resolved ModelConfig
  created_at

worker attestation             written by the worker at session start
  agent_config_version_id      what the process ACTUALLY loaded
  prompt_sha256                recomputed BY THE WORKER from what is in memory
  observed_at
```

`get_agent` returns **what the worker last attested**, never what the control plane intends.
The two can disagree — a worker on a stale deploy, a config version published after the
session started, a truncated prompt — and that disagreement is exactly what gate 2, the drift
sweep and `agents/verification.py` exist to detect. The property survives; only the witness
changes, from a vendor to our own process reporting on its own memory.

**Rejected — declaring `control_plane` and letting `get_agent` echo the DB.** It passes every
test and measures nothing, which the port's own author already identified as the failure mode.

**Rejected — declaring `external_deployment` and marking `agent_hosting` a known lie.** A
capability that is false in a comment is a capability nobody can gate on.

**Rejected — dropping the read-back and re-aiming gate 2 at "did the deploy succeed".** A
deploy succeeding says nothing about which prompt a given session loaded, and sessions
outlive deploys.

### 1.2 The guarantee of record splits: the CARRIER owns the facts, WE own the content

**The problem.** D-31 settled "payloads as hints, poller as truth" because Bolna's API was an
authority independent of the webhook. Under a framework we run, `list_executions` would read
our own store and call it truth.

**The settlement.** A call has two kinds of record and they have different authorities:

| | Authority | Why |
|---|---|---|
| **Facts** — connected, answered, duration, disposition, the number that rang | **The carrier's CDR** (Plivo) | It is the party that billed the minute. It cannot be argued with and it is independent of us. |
| **Content** — transcript, turns, tool calls, outcome, extraction | **Our worker** | Nobody else ever had it. Pipecat Cloud does not retain our transcripts. |

`list_executions` reads our store and **reconciles against the carrier's CDR**, and the
reconciliation is the guarantee: a session we have no CDR for, or a CDR we have no session
for, is a named discrepancy rather than a silent gap. `ListingIncompleteReason` keeps its job
and gains a member for "carrier CDR not yet retrievable".

**This is stronger than what Bolna gave us, not weaker** — the billable quantity is now
witnessed by the party that charges for it, which is what hard rule 7 wants and what a vendor
total never provided.

### 1.3 `unit_cost_paid` becomes a SUM of independently metered legs

**The problem.** There is no vendor total to convert. Hard rule 7 requires a real cost per
`usage_event`, against an append-only ledger.

**The settlement.** Each leg is metered from a source that can be audited on its own:

| Leg | Quantity | Source | Evidence |
|---|---|---|---|
| Carrier | connected minutes | Plivo CDR | independent, billable |
| Runtime | Pipecat active minutes | Pipecat Cloud usage | ⚠ what an "active minute" covers is UNKNOWN — §7a Q1 of `pre-build-blockers` |
| STT | audio seconds | our worker's own meter | ours |
| TTS | characters synthesised | our worker's own meter | ours, priced at the attested rate |
| LLM | `total_tokens` | `LLMTokenUsage` | see the trap below |

⚠ **`LLMTokenUsage` reports prompt tokens NET on Anthropic and Bedrock but GROSS on
OpenAI-compatible legs.** `total_tokens` is the only cross-provider comparable figure, and
adding cache counts to `prompt_tokens` would double-count on our Azure and OpenAI legs. Meter
`total_tokens`. Never reconstruct it.

**The costing rule is unchanged in shape:** each figure still passes through
`billing/rates.py`, still refuses an unattested price, and still never takes a catalogue
number as `unit_cost_paid`. What changes is that five refusals are now possible where one was.
That is the honest consequence of owning the pipeline and it must not be softened by
defaulting any leg to zero — a leg we cannot price raises, exactly as
`llm_inr_per_ktok` already does.

## 2. THE THREE MOVING PARTS

```
apps/api  (control plane)            apps/voice-worker  (the engine)
├── engine/pipecat.py  ─ adapter     ├── pipeline.py    ─ Pipecat assembly
│     speaks VoiceEngine             ├── config.py      ─ loads a config VERSION
│     owns no vendor shape           ├── attest.py      ─ reports what it loaded  (§1.1)
│     outward                        ├── meter.py       ─ emits our normalized usage (§1.3)
├── agents/  crm/  billing/          └── services/gnani_tts.py  ─ staged, D-593
└── compliance/                              │
        │                                    │ OUR normalized events only
        └────────────  Postgres  ────────────┘
```

**The worker emits `CallEvent` and `TranscriptTurn`, never a Pipecat frame.** That single
sentence is what keeps hard rule 2 true after D-592 moved its boundary, and it is the first
thing to check in any review of this code.

**The adapter imports no Pipecat.** It speaks to the worker through the database and, where a
call must be started or ended now, through the carrier's API. `apps.api.engine.pipecat` joins
`forbidden_modules` in `pyproject.toml` beside `bolna`, `cartesia` and `fake`.

## 3. THE ADAPTER, BY CATEGORY

The contract inventory's §9 divides the 25 methods four ways. Build in this order.

**A. Real work against the carrier** — `start_outbound_call`, `end_call`,
`list_engine_numbers`, `bind_inbound_number`, `unbind_inbound_number`. These become Plivo API
calls. `transfer` has **no caller anywhere in the tree** — implement it as a named refusal
until something needs it, and say so in the capability.

⚠ **THIS LIST SHRANK ON 13 SEP 2026 AND USED TO NAME THREE MORE.** `search_numbers`,
`provision_number` and `release_number` are **named refusals**, not carrier calls, and
`number_series` is empty. We do not buy numbers through an API: where a number is ours to
supply it is a **140 or 1600 series** number obtained by application through the carrier and
the regulatory process, and it is never retired (founder, 13 Sep 2026 —
`docs/evidence/pre-build-blockers-2026-09-13.md` §9, D-596). The earlier listing was carried
over from an engine that RESELLS telephony, which is not our shape. This also settles a
contradiction that was open between two documents: the contract inventory's §9.1 reasoned
these three become refusals while this section listed them as carrier calls — §9.1 was
right, and the reason it was right is a product fact rather than an architectural one.

**B. Our own control plane** — `create_agent`, `update_agent`, `delete_agent`,
`attach_kb`, `detach_kb`, `list_kb`, `list_account_kb`, `set_llm_credential`, `list_voices`.
These write our tables. They are not no-ops and must not be stubbed: `create_agent` mints an
immutable `agent_config_version` (§1.1), which is what the worker later loads and attests.

**C. Reconciled reads** — `get_agent` (returns the worker's attestation), `get_execution` and
`list_executions` (our store ∪ carrier CDR, per §1.2).

**D. Webhook intake** — `verify_webhook` and `parse_webhook` have **no counterpart**: nothing
external calls us. `WEBHOOK_AUTH_BY_ENGINE` gains `pipecat: "none"` with the ground recorded,
and voice-runtime's intake path is not extended. The worker writes directly; it is inside our
trust boundary and authenticates as itself.

## 4. THE WORKER PIPELINE

From the API reference, corrected for 1.10.0:

```
transport.input()
  → STT            SarvamSTTService, saaras:v4, Language.TE_IN
  → user aggregator    LLMUserAggregatorParams  ← VAD LIVES HERE, not on TransportParams
  → LLM            BYOK: Azure / OpenAI / Gemini, our keys
  → TTS            Sarvam bulbul:v3 today; Gnani staged (D-593); Cartesia on Studio
  → transport.output()
  → assistant aggregator   ← AFTER output, per the shipped ordering
```

**Turn detection is the whole point and its default is wrong for us.** Smart turn v3 is ON by
default, its 8.7 MB ONNX model ships inside the wheel, and `onnxruntime`/`soxr` are base
dependencies — so no extra install. But **`stop_secs` defaults to 3 seconds**, against the
650 ms of inherited fixed-timeout endpointing this migration exists to beat. Tune it, measure
it on real Telugu PSTN audio (`pre-build-blockers` §3.6 M-1..M-5), and record the measurement
rather than the intention. The 0.5 decision threshold beside it is hardcoded and not
configurable.

**Two Plivo facts that are capability declarations, not footnotes:**
- `auto_hang_up=True` by default, and hangup is a `DELETE` to `api.plivo.com` that **swallows
  every error and never retries**. If a hangup matters — and on a billed call it does — we
  verify it, not assume it.
- **Outbound DTMF is not supported on the Plivo leg**; it falls through to locally synthesised
  in-band tones. `EngineCapabilities` must say so.

**Set `function_call_timeout_secs`.** It defaults to `None` — no tool timeout at all — against
an in-call tool endpoint with a 100 ms budget.

## 5. `GnaniTTSService` — staged, not built

Gated on §7a Q1 of `pre-build-blockers`: whether Gnani's 60 req/min TTS cap counts a WebSocket
session or each utterance. Ten lines at 40–50 synthesis requests a minute cannot survive the
second reading, and building before the answer is building for nothing.

When it is built: subclass `InterruptibleTTSService` — websocket TTS, no word timestamps,
barge-in by reconnect, which is exactly Gnani's shape. `NeuphonicTTSService` is the closest
template and the API reference documents it step by step. **One thing to do better than the
template:** Neuphonic relies on a 3-second idle timeout to close each context; if Gnani sends
an end-of-synthesis message, call `remove_audio_context()` from the receive loop and save
three seconds per turn.

## 6. SEQUENCING, AND WHAT GATES EACH STEP

| # | Step | Gated on |
|---|---|---|
| 1 | `apps/voice-worker/` workspace member, `pipecat-ai==1.10.0` pinned, lint-imports entry | nothing |
| 2 | `owned_runtime` on `AgentHosting`, `agent_config_versions`, the attestation table | nothing |
| 3 | `apps/api/engine/pipecat.py` — categories B then A then C | step 2 |
| 4 | The worker pipeline, Sarvam TTS, local run against a fake transport | step 1 |
| 5 | Conformance suite green for `pipecat` | steps 3–4 |
| 6 | Carrier wiring, first real call | Plivo account in the **India data region** (BLOCKER-1) |
| 7 | Metering reconciled against the Plivo CDR | step 6 |
| 8 | `GnaniTTSService` | Gnani Q1 |
| 9 | `Clear` flips to Gnani; Sarvam TTS retires | step 8 + price attested |
| 10 | Bolna adapter deleted, one commit | a real Pipecat call has happened |

**Nothing before step 6 needs an account.** Pipecat is a library; the worker runs locally.

## 7. WHAT THIS SPEC DOES NOT DECIDE

- Whether Plivo media reaches the Mumbai worker or terminates at a US edge. ⚠ **THIS IS NO
  LONGER A RESEARCH QUESTION AND IS NOT A GATE** (founder, 13 Sep 2026): it changes no code,
  and the answer that counts is what a real call measures rather than what a documentation
  page claims. It moved to `pre-build-blockers` §3.6 beside M-1..M-5. Let the media land
  where it lands until a measured call says otherwise.
- What a Pipecat "active minute" bills (§3.5 P-1). It changes the cost model, not the shape.
- Whether `sonic-3.5` is a real Cartesia identifier — **it appears nowhere in Pipecat's
  source**, whose own default is `sonic-3.6`, and Pipecat validates no Cartesia id at all. Our
  value stays REPORTED. Do not silently "fix" it to match a library that would accept anything.
- Gate 16f (`AZURE_OPENAI_API_VERSION` on the v1 surface). Pipecat's `AzureLLMService`
  corroborates our declared leg but is not a primary source for Azure.

Each is UNKNOWN and labelled. None is filled with a guess.
