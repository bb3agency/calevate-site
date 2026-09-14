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
| 11 | Wire `voice_worker/knowledge.py` into `pipeline.py` — `SessionConfig` carries the pack digest, `assemble_call` awaits `load_session_knowledge`, `SessionKnowledge.search` registers as a tool | steps 3-4. **The pack builder and the search are BUILT AND TESTED; nothing calls them.** §8 |
| 12 | Give `kb/pack.py::publish_pack` a caller on the publish path, and an object-lifecycle rule for `knowledge-packs/` | step 11 |
| 13 | Golden Telugu/Hindi → English-hit set in CI | step 11. §9.4 |
| 14 | Supermemory on box 2 behind `RetrievalProvider`; embedding pointed at Gemini and PROVEN non-local | §8.3's `top` check |
| 15 | `kb_chunks` and our lexical search retire; `kb_documents` ledger stays | step 14 |
| 16 | Apply the new rate card (§12) — catalogue plus the wide fixture update | nothing; it is the next piece of work |

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
- **Whether Bulbul v3 speaks text whose script does not match `target_language_code`**, and
  whether TTS has any auto/mixed setting. `docs.sarvam.ai` is egress-blocked here. §9.3.
- **Gnani's Clear-tier price**, and whether its 60 req/min cap counts a session or an
  utterance. The only figure in this tree is REPORTED (₹27/10,000 chars, a dashboard reading
  relayed in a brief, never re-verified), and hard rule 7 keeps it out of the rate card. §5.
- **Whether Gnani supports cloned voices at all.** D-593's whole ground for replacing Sarvam
  on Clear is that `SarvamTTSSpeakerV3` is a closed enum with nowhere to put a client's own
  cloned voice. If Gnani cannot clone either, the swap buys only the price.
- **The current state of Supermemory issues #1336, #1315 and #1320.** `supermemory.ai` is
  egress-blocked here; §8.3's `top` check settles the one that matters empirically.
- **Google's embedding price per million tokens.** `ai.google.dev` is egress-blocked
  (re-measured 14 Sep 2026). §10.4 states the bill as a formula rather than a number.
- **Telugu retrieval quality on Gemini embeddings.** The harness exists; it needs the
  founder's Google API key to run.

Each is UNKNOWN and labelled. None is filled with a guess.

## 8. THE THREE BOXES, AND WHAT RUNS WHERE

Settled with the founder, 14 Sep 2026. Three deployables, and the only one on the call path
is the first.

| Box | What it is | On the call path? | What it runs |
|-----|------------|-------------------|--------------|
| 1 | **Pipecat Cloud `ap-south`** | YES — it IS the call | `apps/voice-worker/`: STT, LLM, TTS, turn detection, and the in-call KB **in its own memory** |
| 2 | **Calevate VPS (Hostinger, Mumbai)** | no | `apps/web`, `apps/api`, `apps/workers`, Postgres 16 + pgvector, Redis, nginx |
| 3 | **Supermemory** | no | Document store, chunking, index, dashboard retrieval, caller memory |

**Box 3 lives ON box 2 until the first client.** The founder's box is 1 vCPU / 4 GB / 50 GB
and will be upgraded (4 vCPU / 8 GB or larger) when there is a client to upgrade for. That is
a deliberate dev-phase choice, not a target architecture: §8.3 states the condition that must
hold for it to be safe, and §11 sizes the box for real volumes.

### 8.1 Why the in-call KB is not a network call

Box 1 fetches the agent's `KnowledgePack` ONCE at session start and searches it in-process
for the rest of the call. **Measured: 0.501 ms p50 per lookup, zero network per turn.** The
alternative — box 1 asking box 3 on every question — costs 30–50 ms of network, and makes
every question on every call depend on a second machine being up and fast. A phone call has
no retry affordance: a caller hears the hesitation.

This is why "use Supermemory for the KB" and "the in-call KB is a pack in memory" are not in
conflict. Box 3 is where documents LIVE and where the pack is BUILT (at publish, once). Box 1
is where a question is ANSWERED. Nothing about adopting Supermemory changes that split.

### 8.2 What the pack contains, and how big it is

Everything the client has published **for one agent** — every active chunk, as text plus its
English gloss. Not the platform's KB, not other clients, not other agents. Chunk text is
capped at 4,000 characters (`calevate_shared/knowledge_pack.py`), so a 50-page client KB is a
few hundred chunks: on the order of a few hundred KB of text, ~1 MB with the search index.
The container already holds an ONNX turn-detection model and the Pipecat runtime, which are
hundreds of MB. The pack is a rounding error beside them.

The pack is **content-addressed** (`content_sha256`, `built_at` deliberately outside the
hash), so republishing identical content produces the identical key and nothing is
re-uploaded. `PackCache` in the worker holds up to `MAX_CACHED_PACKS` (8) keyed on the
digest, so a busy agent's second call downloads nothing.

### 8.3 THE HARD CONDITION ON A SMALL BOX: EMBEDDING MUST NOT BE LOCAL

Self-hosted Supermemory's DEFAULT embedding model is `Xenova/bge-base-en-v1.5` (768d), run
**on the host's CPU** [VERIFIED-VENDOR-DOCS: supermemory.ai/docs/self-hosting/overview, read
by the founder 14 Sep 2026]. Measured on this container (Intel Xeon 2.10 GHz, AVX-512,
seq_len 32, GEMM-only floor): **bge-base 78.7 ms at 1 thread**, MiniLM-L6 9.3 ms. A 200-chunk
document is therefore ~16 seconds of a single core pinned at 100%, contending with Postgres,
the API, the workers and `next build` on the same core.

So on box 2's current shape, embedding MUST go to the Gemini API. The documented settings are
`SUPERMEMORY_EMBEDDING_PROVIDER` (`local` | `openai` | `gemini` | OpenAI-compatible),
`SUPERMEMORY_EMBEDDING_MODEL`, `SUPERMEMORY_EMBEDDING_DIMENSIONS`,
`SUPERMEMORY_EMBEDDING_BASE_URL` [same source, /docs/self-hosting/configuration].

⚠ **DO NOT TRUST THE SETTING — PROVE IT.** GitHub issue #1336 reports that these variables are
ignored and the local model runs regardless. Its CURRENT state is **UNVERIFIED** — nobody has
read the live issue page — so it is neither a blocker nor a closed question. The five-minute
empirical check after install: upload one document, watch `top`. If an encoder process eats a
core for ten seconds, the variables are being ignored and the install is on the local model.
That measurement settles it without needing the issue at all.

Also required before install: **swap**. A 4 GB box running two Postgres-touching services with
no swap is how the OOM killer takes out the API container. Supermemory's own documented
post-boot baseline is ~1.6 GB and it publishes **no minimum hardware requirements at all**
[NOT FOUND, same source].

### 8.4 What stays in OUR Postgres, and why

`kb_chunks` and our lexical search retire in favour of Supermemory. **The document LEDGER does
not.** `kb_documents` keeps: which tenant uploaded what, which version is published, when it
was erased. Four reasons, none of them pride:

1. **Tenant isolation we can prove.** Ours is FORCEd RLS enforced by Postgres (hard rule 1).
   Supermemory's local build is **single-tenant with one auto-generated API key**; scoped
   per-tenant keys are an Enterprise feature [VERIFIED-VENDOR-DOCS: /docs/self-hosting/
   local-vs-enterprise]. Container tags are therefore a filter WE remember to send, not a wall
   the server enforces — so the wall stays on our side.
2. **DPDP erasure.** "Delete everything for this tenant" must be one statement we can prove
   returned zero rows. Against a vendor we would be trusting their delete with no way to check.
3. **Provenance.** The pack carries `document_id` + `document_version`, so an answer on a call
   traces to "brochure v3, chunk 12" — which is what a client sees when they ask why the agent
   said something. The id has to be minted by us.
4. **Rebuildability.** If box 3 is ever rebuilt (bug, version upgrade, migration), the ledger
   says what should be in it.

### 8.5 Supermemory's status: adopt behind the adapter, pin on a version

`calevate_shared.retrieval.RetrievalProvider` and `apps/api/retrieval/service.get_retriever`
already exist for exactly this (D-502). Supermemory becomes a provider behind that seam:
dashboard copilot, CRM search and caller memory read from it; if it is down, calls do not
notice and uploads do not notice — only dashboard search degrades to the Postgres fallback.

Three open issues bear on WHICH RELEASE we pin, and all three are **UNVERIFIED as to current
state** (nobody has read the live issue pages; `supermemory.ai` is egress-blocked from this
container):

- **#1336** — custom embedding env vars ignored (see §8.3; the `top` check substitutes).
- **#1315** — searches return empty on Linux in 0.0.6.
- **#1320** — segfault under concurrent embedding.

These are a version gate, not a verdict. The founder's position — "bugs are not blockers, they
will be fixed" — is accepted: what is refused is pinning a release whose search returns
nothing, which the empirical check above catches in one upload.

---

## 9. THE LANGUAGE PATH, END TO END

The design question: a caller speaks Telugu, Hindi or English — often mixing them — and must
be answered in the same language, with KB retrieval working throughout.

### 9.1 The turn, in order

1. Caller speaks. **Sarvam STT** transcribes. Saaras v3/v4 default to `"unknown"` =
   auto-detect [VERIFIED: `pipecat/services/sarvam/stt.py:118,207-208`, installed 1.10.0], and
   the language map carries `te-IN`, `hi-IN`, `en-IN` (`stt.py:79-87`).
2. **The LLM reads the transcript.** If it needs a fact it calls the search tool and **writes
   the query itself, in English**. No translation hop, no extra vendor: writing an English
   query is part of the model's own reading, the same way it would answer in English if asked.
   [VERIFIED: `llm_service.py:917,1024` `register_function`/`register_direct_function`;
   `google/llm.py:213,367` passes `tools`.]
3. **Search runs in the worker's memory** over the English index. 0.5 ms.
4. **The LLM composes the reply in the caller's language.**
5. **Sarvam TTS speaks it.** `target_language_code` per request (`sarvam/tts.py:564,1060`);
   `te-IN` / `hi-IN` / `en-IN` all present (`tts.py:223,227,241`).

**STT is ears, the LLM is the brain and does all translating in both directions, TTS is the
mouth.** TTS does not translate; this was a live misunderstanding on 14 Sep 2026 and is
recorded so it is not repeated.

### 9.2 English-only indexing

**Store BOTH, index ONE.** Every chunk keeps the client's original text (for display,
provenance and the client-facing record) and an English gloss. **Only the English is
indexed and searched.** Justification is measured, not assumed
(`docs/evidence/telugu-embedding-quality.md`, n=24): matching query words against
Telugu-script text scored **0.042**; against English, **0.625**. Since step 2 above guarantees
every query arrives in English, the Telugu text in the index is pure noise.

Do NOT store romanised Telugu as a searchable form: there is no standard spelling, so it
multiplies index entries without adding recall.

### 9.3 The one OPEN question on this path

⚠ **Whether Bulbul v3 pronounces text correctly when the script does not match
`target_language_code`, and whether there is any auto/mixed setting, is UNKNOWN.**
`docs.sarvam.ai` is egress-blocked from this container. Pipecat CAN change the setting
mid-session (`TTSUpdateSettingsFrame`, `pipecat/frames/frames.py:2375`), so if a per-turn flip
turns out to be necessary the mechanism exists; what is unknown is whether it is necessary.

A Comet brief covering this sits in `docs/evidence/` (Part 2 of the 14 Sep 2026 vendor brief).
Until it is answered, no code assumes either behaviour.

### 9.4 Reliability, and how it is guarded

The failure mode is not translation — it is a bad English paraphrase ("doctor timings" vs
"when is the doctor available"). Three things absorb it: the English gloss, top-3 results, and
the `ambiguous` state. What closes it properly is a **golden set of Telugu/Hindi questions →
expected English hit, run in CI**, so a regression is a red test rather than a bad call.
That harness does not exist yet and is step 11 in §6.

---

## 10. THE COST MODEL AFTER THE ENGINE CHANGE (D-592)

### 10.1 The engine leg

| | Bolna (was) | Pipecat (now) |
|---|---|---|
| Per ACTIVE call-minute | $0.02 BYOK platform fee | **$0.01** |
| Warm/reserved instance | n/a | **$0.0005/min**, one session per instance |

[VERIFIED-VENDOR-DOCS: `docs.pipecat.ai/pipecat-cloud/pricing`, cited at
`docs/evidence/engine-replacement-comet-2026-09-06.md:93,103,122`. The evidence file records
that the vendor's page shows no date.]

At `COST_MODEL_USD_INR = 95` the active minute is **₹0.95**.

### 10.2 Reserved capacity is NOT in any floor, and that is structural

One warm slot = one concurrent call = 43,200 min/month × $0.0005 = **$21.60 = ₹2,052**. Per
CALL-minute it is entirely a function of utilisation:

| Busy minutes/month on one slot | Effective ₹/min |
|---|---|
| 1,000 | ₹3.00 |
| 5,000 | ₹1.36 |
| 10,000 | ₹1.16 |
| 43,200 | ₹1.00 |

There is no single rupee figure to put in a per-minute floor, and inventing one by assuming a
utilisation is how a floor stops meaning anything. It is infrastructure, like the VPS.
`ENGINE_RESERVED_INSTANCE_USD_PER_MIN` carries it; a test fails if anyone folds it in.

**Below roughly 4,000 call-minutes a month, a warm slot costs more than Bolna's fee did.**
During dev with no inbound traffic, scale-to-zero costs ₹0 reserved and the ~10 s cold start
does not matter.

### 10.3 The floors

| Tier | Was | Now |
|---|---|---|
| Clear | ₹4.1211 | **₹3.3111** (0.95 + 0.50 STT + 0.2411 LLM + 1.62 TTS) |
| Studio | ₹5.5899 | **₹4.7099** |

Which legs move with the dollar: the **engine** (USD) does. **STT** and **Sarvam TTS** are
published by Sarvam in rupees and do not. The **LLM** leg is struck at `LIST_PRICE_USD_INR`
(₹95.66), a different card that must not be re-struck — doing so reprices every account and
TRD §10's fifteen cost points.

### 10.4 Embedding cost is not a per-minute cost

**Zero embeddings on the call path** — the pack is lexical. Embeddings occur twice per CALL
(caller-memory read at start, write at end, ~165 tokens total) and once per DOCUMENT at
publish (a 50-page KB ≈ 25,000 tokens). For scale: a 3-minute call already sends **25,380**
input tokens to the LLM and a 10-minute call **160,200** (derived from `REFERENCE_CALL`). So
embedding traffic is 150×–1,000× smaller than the LLM traffic already on the same call.

At 10,000 calls/month the embedding volume is **1.65 M tokens**. ⚠ The Gemini embedding PRICE
is **UNVERIFIED** — `ai.google.dev` is egress-blocked (re-measured 14 Sep 2026, CONNECT
rejected) — so the bill is stated as a formula, not a number: at $P per million tokens it is
**≈ ₹145 × P per month**.

⚠ **The cost to watch is not embedding — it is Supermemory's per-chunk LLM call at ingestion.**
A 50-page document is ~200 chunks, each drawing a Gemini *chat* call far larger than an
embedding call. This is also why ingestion must be QUEUED, never inline: one client uploading a
300-page manual must not sit in front of another client's memory write on a 1 vCPU box.

---

## 11. SIZING BOX 3

**Box 3's load scales with calls per HOUR, not concurrent calls.** Calls run on box 1 with the
pack; box 3 sees exactly two requests per call (memory read, memory write) plus dashboard
traffic. The heavy work — ingestion — happens at upload, not at call time.

| Calls/hour | Box-3 requests/hour | Sustained CPU | Box | Real bottleneck |
|---|---|---|---|---|
| ≤ 100 | ~200 | ≪ 1 core | 2 vCPU / 4 GB | none |
| 100–1,000 | ~2,000 | ~1 core | **4 vCPU / 8 GB** | Postgres connections; LLM API rate limits |
| 1,000–5,000 | ~10,000 | 2–3 cores | 8 vCPU / 16 GB NVMe | ingestion bursts — queue them |
| 5,000+ | 10,000+ | 4+ cores | split Postgres to its own box | pgvector write contention |

RAM is set by wanting the vector index resident: ~1.5 KB per chunk at 768d → 1 M chunks ≈
1.5 GB. A hundred clients with 50-page KBs is ~20k chunks. Caller memories accumulate at ~1 row
per call, which is where the 16 GB tier starts to matter.

These rows are ESTIMATE (derived from the measured embedding figures and ordinary pgvector
behaviour), not vendor-published. Supermemory publishes no sizing guidance at all.

---

## 12. WHAT CHANGED IN THE RATE CARD

⚠ **DECIDED, NOT YET APPLIED.** Founder decision, 14 Sep 2026: **Clear ₹4.00 flat; Studio
₹7.00 at the ₹2,000 pack down to ₹5.50 at the ₹50,000 pack.** Middle Studio rungs
interpolated at even ₹0.30 steps. `PACK_CATALOGUE` still carries the OLD card
(Clear 5.00→4.50, Studio 8.00→6.00) as of this writing; §6 step 16 applies it.

The change is one edit to the catalogue and a WIDE test update: the old rates are pinned as
literals, and as arithmetic derived from them, across `credit_lots_wiring`,
`credit_refund_lots`, `credit_lot_reprice`, `public_rate_card`, `list_rate_card`,
`cartesia_volume`, `ops_rate_card_write`, `cost_floor`, `credit_packs` and
`credit_lots_helpers` — roughly twenty assertions plus prose. It was attempted and reverted
rather than rushed: a card is money, and a half-checked substitution across fixtures that do
arithmetic on the old numbers is how a wrong rate reaches an invoice.

| Pack | Clear | Clear margin | Studio | Studio margin |
|---|---|---|---|---|
| starter ₹2,000 | ₹4.00 | 17.2% | ₹7.00 | 32.7% |
| growth ₹5,000 | ₹4.00 | 17.2% | ₹6.70 | 29.7% |
| scale ₹10,000 | ₹4.00 | 17.2% | ₹6.40 | 26.4% |
| plus ₹15,000 | ₹4.00 | 17.2% | ₹6.10 | 22.8% |
| pro ₹25,000 | ₹4.00 | 17.2% | ₹5.80 | 18.8% |
| max ₹50,000 | ₹4.00 | 17.2% | ₹5.50 | 14.4% |

**8 of 12 cells sit under the 20% gross-margin target.** None is under COST, so the ops console
warns rather than refuses. This is a deliberate price cut to win the first clients, recorded as
a decision rather than absorbed silently. To hold 20% instead: Clear ₹4.15, Studio floor ₹5.90.

`credit_packs.py::PACK_CATALOGUE` is the single source; every pricing surface renders from the
API, so no frontend file carries a price.
