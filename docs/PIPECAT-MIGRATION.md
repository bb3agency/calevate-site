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

**`get_execution` AND `list_executions` LAND ON OPPOSITE SIDES OF THAT TABLE, AND D-607 IS
WHERE THE DIFFERENCE BECAME LOAD-BEARING.** The listing is the DISCOVERY question — "which
calls happened that you have not heard about" — and answering it from the table that holds
what we have heard about is the tautology above, so it stays empty until the carrier's CDR
gives it a real second authority. The single fetch is a CONTENT read for a call the worker's
own settlement transaction already attested, and content is ours by the row above: it reads
`calls` and `transcript_turns` back, finds the tenant by parsing the engine-space id the sink
minted, and is what lets a settled call reach the post-call pipeline at all. Nothing in it is
corroborating anything.

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

**A REFUSAL NOW HAS SOMEWHERE TO GO, AND THAT IS THE HALF THIS SECTION WAS MISSING**
(15 Sep 2026). Raising is correct and was not sufficient: a refusal whose only record is a
log line is a refusal in a container that will be gone by morning, and
`admin/health.py::calls_unmetered` could say a completed call had no money against it
without ever saying WHICH leg or WHAT to do. `call_metering_refusals` (migration
`a3f1c6e82d47`, append-only, FORCE-RLS'd) carries the four fields
`voice_worker/meter.py`'s `LegNotMeterableError` family already produces — `leg`, `code`,
`detail`, `remediation` — and `voice_worker/sink.py::settle` writes one instead of a row of
zeroes. **Settlement stays all-or-nothing**: `metered_rows` refuses whole, so a refused call
has a refusal row and NO `usage_events` rows at all, never four legs and a hole.

**THE TWO LLM UNIT TYPES LANDED WITH IT.** `meter.py` had spelled `llm_ktok_in` /
`llm_ktok_out` since it was written and `ck_usage_events_unit_type_enum` refused them, which
was the correct failure and is now answered rather than worked around. They are NOT
`llm_tok_in`/`llm_tok_out`, which carry the rented engine's leg charge at `qty = 1`; see
`docs/DATA-MODEL.md` §8 for the split and the NUMERIC(12,4) arithmetic that makes the `k`
a money decision.

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
  → STT            SarvamSTTService, saaras:v4, language auto-detected (§9.1, §9.5)
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
| 5 | Conformance suite green for `pipecat` | **GREEN, 14 Sep 2026 — and it was green before it meant anything.** `uv run pytest packages/shared/tests/engine_conformance`: 386 passed, 6 skipped, `pipecat` among the seven subjects, no adapter changed. The audit found the green was thinner on this adapter than on any other, for a structural reason rather than a missing test: `pipecat` places no dial (its carrier REST surface is unread, §7/BLOCKER-1), so `_place_call` returns None and every clause that reads a snapshot back from a call returned early on it. The whole normalization half of the contract — our status vocabulary, the agent ref, turn order, speaker tags, per-call turn attribution — was being asserted about nothing on the newest adapter in the tree. Closed by `test_a_listing_row_is_as_normalized_as_a_fetched_one`, which holds every row of the LISTING route to the same `_assert_snapshot_is_ours` the fetch route is held to; that route is the one `pipecat` has, and the one D-31 makes the guarantee of record for every adapter. Three more clauses landed with it — direction towards `inbound`, a tenant/engine name taken from the payload body, a status that is not a string — each proved real by a saboteur the suite ACCEPTED beforehand (`tests/engine_audit_test.py::SABOTEURS`, +6 entries). **STILL UNMEASURED ON THIS ADAPTER, AND GATED ON STEP 6, NOT ON A TEST:** `billable_ready` against a real call (§1.2 says it may never honestly be True until a CDR can be read), the `raw_document` archive clause (an `owned_runtime` engine's far side is our own database, so there is no vendor document to archive — this may be a clause that never applies here rather than one that is waiting), and `end_call`. Say the suite is green; do not say the adapter is exercised as hard as `bolna`. |
| 6 | Carrier wiring, first real call | **THE TRANSPORT LANDED 15 Sep 2026; THE CALL HAS NOT HAPPENED, AND THOSE ARE NOT THE SAME CLAIM.** What is built and tested with no account and no socket (`apps/voice-worker/voice_worker/carrier.py`, `tests/voice_worker_carrier_test.py`): the Plivo transport (`PlivoFrameSerializer` + `FastAPIWebsocketTransport`, 8 kHz both ways, no WAV header), the answer document, the stream URL, the handshake narrowing, and the whole INBOUND path — a route token off the stream URL → `(tenant, agent)` → an RLS-scoped read of the published config version → the knowledge pack → `assemble_call` → the agent speaking first from the transport's own connect event. **THE ROUTE IS THE URL, NOT THE DIALLED NUMBER**: Pipecat's Plivo parser leaves `from`/`to` `None` (`runner/utils.py:257-262`), so the stream URL carries the agent ref the control plane already mints (`calevate_shared.engine.owned_runtime_agent_ref`) and the number → agent decision stays on the screen that binds the number, where a tenant session exists. **Hard rule 5 now binds this leg**: `config.load_session_config` refuses an agent with no `ai_disclosure_line` and a prompt that has lost the truthful-answer floor — an inbound call reaches neither the column CHECK nor `check_dispatch`. **WHAT REMAINS IS AN ACCOUNT, PLUS TWO THINGS THAT NEED IT**: (a) a Plivo account in the **India data region** (BLOCKER-1) with its `auth_id`/`auth_token` in the ops console and a number pointed at our answer URL — an external blocker, not engineering; (b) the HTTP half — the route that serves `plivo_answer_document` and accepts the WebSocket — which is one mount in `apps/voice-runtime` and is deliberately NOT written against an unread vendor grammar; (c) **OUTBOUND DIAL IS UNBUILT AND REFUSES BY NAME** (`carrier.place_outbound_call`): Pipecat's whole tree holds one Plivo REST endpoint, the hangup (`serializers/plivo.py:184`), and the request that places a call is UNKNOWN here. Step 6 is DONE when a real call has happened, and it has not |
| 7 | Metering reconciled against the Plivo CDR | step 6 |
| 8 | `GnaniTTSService` | Gnani Q1 |
| 9 | `Clear` flips to Gnani; Sarvam TTS retires | step 8 + price attested |
| 10 | Bolna adapter deleted, one commit | a real Pipecat call has happened |
| 11 | Wire `voice_worker/knowledge.py` into `pipeline.py` — `SessionConfig` carries the pack digest, `assemble_call` awaits `load_session_knowledge`, `SessionKnowledge.search` registers as a tool | **DONE, 14 Sep 2026.** The ends landed first and the MIDDLE was open for three commits: nothing read `agents.knowledge_pack_sha256` into a `SessionConfig` and nothing awaited the load, so every call would have been assembled with `knowledge=None` and every caller told the client had published nothing. Closed by `voice_worker/config.py` (the version + pack-pointer read), `voice_worker/storage.py` (the `PackFetcher` over the bucket, bounded) and `voice_worker/session.py` (`start_session`: config, then pack, then `assemble_call`, with the one process-wide `PackCache`). **THE BOOTSTRAP LANDED 15 SEP 2026 AND ONE THIRD OF IT REMAINS OPEN.** This row used to end "what is still not called in production is the CONTAINER BOOTSTRAP — transport, sink and DB engine". The sink and the engine now exist: `voice_worker/db.py` (ONE engine and pool for the container, shared by the config read and the writer, which is what `config.load_session_config` asked for by name), `voice_worker/sink.py` (`calls`, `transcript_turns` and `usage_events`, in the same statements, on the same idempotency keys and through the same `apps/workers/redaction.py` as the post-call pipeline, so the two writers converge on one row) and `voice_worker/runtime.py` (the entrypoint: bootstrap order, the meter's observer, and `WorkerRunner(handle_sigterm=True)` — OFF by default, so without it an orchestrator's stop signal kills a call mid-settlement). What is still open is the TRANSPORT, which is BLOCKER-1 and nobody's to code around, and the container IMAGE: the root `Dockerfile` copies `apps/api`, `apps/voice-runtime` and `apps/workers` and not this package. ⚠ Every settlement in production TODAY is a recorded refusal rather than rupees, because §1.2 gives the billable minute to the carrier and there is no carrier — see §1.3 and `call_metering_refusals`. §8 |
| 12 | Give `kb/pack.py::publish_pack` a caller on the publish path, and an object-lifecycle rule for `knowledge-packs/` | **DONE — AND THIS ROW WAS STALE ON BOTH HALVES BEFORE D-611 TOUCHED ANYTHING.** The CALLER landed with the pack builder itself: `publish_pack` is called by `kb/pack.refresh_published_pack`, which is the one entry point for every writer of `agents.knowledge_pack_sha256` and is reached from `kb/service.publish_source`, `kb/service.withdraw_source` and the gloss sweep (`workers/kb_gloss.py`) — it was never dead code and deleting it would have been wrong. The RULE landed too: `infra/object-lifecycle/policy.json`'s `knowledge-packs-growth-ceiling-not-retention`, 2555 days, pinned by `tests/object_lifecycle_test.py`. **WHAT WAS ACTUALLY MISSING IS THE THING A BUCKET RULE CANNOT BE**, and three files in this tree said so in their own words: S3 expiry runs from an object's CREATION and a pack is rebuilt only when knowledge changes, so the oldest object under the prefix is the LIVE pack of the client whose price list has been correct longest — any expiry short enough to reclaim space deletes exactly the wrong objects. **D-611 adds the reference-aware collector** (`apps/workers/pack_gc.py`, 05:07 daily): delete a pack that no `agents.knowledge_pack_sha256` names, after a seven-day grace that covers `refresh_published_pack`'s deliberate store-the-object-before-the-pointer-commits order. It writes no row, takes no lock, and every uncertainty resolves to KEEP — an unparseable key, an object the store reports no age for, a tenant this tick could not enumerate, and any incomplete reference read all abort or skip rather than delete. ⚠ **STILL OPEN AND NAMED**: a CLOSED tenant's packs are not reclaimed, because deleting on absence from the organization directory would take the live pack of every tenant one bad read missed; that belongs in the closure path, which positively knows the tenant is gone, and the 2555-day ceiling is what bounds it meanwhile |
| 13 | Golden caller-language → English-hit set in CI | **FIRST ARM LANDED 14 Sep 2026**: `tests/in_call_retrieval_recall_test.py` scores the real pack and the real search, no wiring needed. What remains is a second language's corpus. §9.4 |
| 14 | Supermemory on box 2 behind `RetrievalProvider`; embedding pointed at Gemini and PROVEN non-local | **THE ADAPTER LANDED 14 Sep 2026; THE INSTALL DID NOT, AND THE TWO HALVES ARE NOT THE SAME CLAIM.** `apps/api/retrieval/supermemory.py` is a third value of `Settings.retrieval_provider` that swaps the T3 member of `KnowledgeRetriever`, with `PgVectorRetriever` underneath it as a per-request fallback — so an unreachable box 3 degrades dashboard search and nothing else (§8.5), and step 15 is untouched. ⚠ **IT IS NOT A VERIFIED INTEGRATION**: nothing here has read a page of Supermemory's API docs (`supermemory.ai` egress-blocked), so every path and key is an ASSUMPTION collected in `retrieval/supermemory_wire.ASSUMED_CONTRACT` and a shape we guessed wrong falls back rather than erroring. Tenancy is OURS per §8.4 — `per_tenant_namespace` is declared **False**, the scope is a required first parameter of every wire method, and records returned without the tenant tag are dropped and counted. What still gates this row is entirely outside the repo: the install itself, §8.3's `top` check, and an operator attesting the embedding price — until that figure is entered, `search_is_billable()` is False and the provider is not selectable at all (hard rule 7's pre-flight) |
| 15 | `kb_chunks` and our lexical search retire; `kb_documents` ledger stays | **THE WRITE HALF LANDED 15 Sep 2026; THE RETIREMENT DID NOT, AND STEP 14 LANDING IS NOT THE GATE — §8.6 IS.** `apps/api/retrieval/supermemory_index.py` gives box 3 an ingestion path (`kb/service.publish_source`), a withdrawal path (`withdraw_source`), a DPDP tenant purge (`workers/retention.execute_tenant_erasure`) and a difference-driven reconciliation sweep (`workers/kb_index_sync.py`, `:19`/`:49`), on a ledger of what the vendor last accepted (`kb_index_documents`, migration `b5e83f21c4d7`). **`kb_chunks` stays and must** until the install is real and §8.3's `top` check has been run: it is the authority the index is derived FROM, the fallback an unreachable box 3 degrades to, and the corpus the sweep measures the difference against — retiring it would leave nothing able to answer the question "what should box 3 hold?". The publish path cannot be failed by the vendor (`kb/pack.refresh_published_pack`'s posture) and the erasure deliberately CAN (§8.4 — a certificate over content we did not remove is the one thing it may not be). Hard rule 7 gates the whole write side on the same pre-flight as the read side: no attested embedding price, no writes at all. ⚠ Every path and key is still an ASSUMPTION in `retrieval/supermemory_wire.ASSUMED_CONTRACT` — the write half added five (`ingest_path`, `delete_path`, `content_key`, `document_id_key`, `delete_ids_key`) and nobody here has read a page of their documentation **§8.6 is the plan the retirement runs against**: six things that must be PROVEN (reachable, priced, ingested, measured against the incumbent, agreed on live traffic, rollback without a redeploy) and the three-release shape hard rule 8 demands — stop reading, then stop writing once a sweep proves nothing reads, then DROP in a LATER release with a `downgrade` that backfills from `kb_documents`. **The incumbent's own recall was never measured either**, so "better" still has no baseline; `retrieval/shadow.py` and `retrieval/compare.py` are the instrument that produces one, and `retrieval_shadow_arm` / `retrieval_shadow_tenant_ids` are LIVE and off — two settings, because a shadow search buys an embedding on a client's quota. Nothing was deleted | step 14 |
| 16 | Apply the new rate card (§12) — catalogue plus the wide fixture update | **DONE, 14 Sep 2026.** `PACK_CATALOGUE` carries Clear ₹4.00 flat and Studio 7.00 → 5.50; sixteen test files and three web surfaces moved with it |
| 17 | The post-call pipeline runs for an `owned_runtime` call — extraction, CRM columns, moments, knowledge gaps, the lead, the hot-lead alert, the CRM fan-out | **DONE, 15 Sep 2026 (D-607).** This row is here because the seam was MISSING and nothing in the table said so: steps 4 and 11 land a worker that writes `calls`, `transcript_turns` and `usage_events`, and then nothing happened. There is no webhook on this engine (§3 category D — nothing external calls us) and no poller (`PipecatEngine.list_executions` reports nothing, on an independence argument that is correct for a poller and says nothing about a call we already know about), so every call this engine handled lost extraction, the CRM columns, the lead and the hot-lead alert — silently, and totally. Closed with the transactional OUTBOX, not a poller and not a new deployable: `voice_worker/sink.py::settle` writes the call row, the ledger (or its refusal) and ONE `outbox_messages` row in ONE transaction, and `dispatch_outbox` — which already exists, already runs every ten seconds and already owns Redis — hands it to `apps/workers/pipeline.py::run_post_call_pipeline`, the SAME function the Bolna path reaches. Idempotent on the partial unique index over `dedupe_key` (`post-call:<calls.id>`), so a re-settlement promises nothing twice. The half that made it possible: `SqlControlPlane.execution()` now reads the call back out of our own rows, finding the tenant by PARSING the engine-space id the sink mints (`calevate_shared.engine.pipecat_call_ref`) — `calls` is FORCE-RLS'd and `get_execution` carries no tenant, and the alternatives were widening a policy or adding a routing table. ⚠ **`_upsert_lead` STILL FILES NO LEAD**, and that is BLOCKER-1 rather than this seam: §1.2 gives the party numbers to the carrier's CDR, the worker is handed none, so `calls.from_e164` is NULL and the lead has no key. Extraction, the moments, the knowledge gaps and the call row's summary/sentiment/outcome all land today; the lead, the hot-lead alert and the CRM fan-out land the day step 6 fills those two columns, with no further edit — `execution()` reads them from the row |

**Nothing before step 6 needs an account.** Pipecat is a library; the worker runs locally.

## 7. WHAT THIS SPEC DOES NOT DECIDE

- Whether Plivo media reaches the Mumbai worker or terminates at a US edge. ⚠ **THIS IS NO
  LONGER A RESEARCH QUESTION AND IS NOT A GATE** (founder, 13 Sep 2026): it changes no code,
  and the answer that counts is what a real call measures rather than what a documentation
  page claims. It moved to `pre-build-blockers` §3.6 beside M-1..M-5. Let the media land
  where it lands until a measured call says otherwise.
- What a Pipecat "active minute" bills (§3.5 P-1). It changes the cost model, not the shape.
- **Everything about the Plivo wire that Pipecat's own source does not show.**
  `www.plivo.com` and `api.plivo.com` are egress-blocked here (re-measured 13 Sep 2026, §10
  of `pre-build-blockers`), so the carrier module cites PIPECAT SOURCE and nothing else.
  Three named gaps, each labelled at its point of use in
  `apps/voice-worker/voice_worker/carrier.py`:
  1. **The dialled and calling numbers on an inbound stream.** Pipecat's parser populates
     `from`/`to` for Telnyx and Exotel and leaves both `None` for Plivo
     (`runner/utils.py:250-262`). Whether the carrier sends them at all is UNKNOWN. The
     routing design does not need the answer and must not be changed to depend on one
     until it is verified.
  2. **Whether Plivo's `<Stream>` accepts any attribute beyond the four Pipecat's shipped
     template sets** (`runner/run.py:1435-1438`). We emit exactly those four.
  3. **Every carrier REST call except the hangup** — placing a call, reading a CDR, binding
     a number to a URL. `carrier.place_outbound_call` and `engine/pipecat.py`'s carrier
     methods refuse by name rather than guess.
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
| 3 | **Supermemory** | no | Document store, chunking, index, dashboard retrieval (T3) |

⚠ **THE BOX-3 ROW SAID "…, caller memory" AND CALLER MEMORY IS NOT IN BOX 3 (15 Sep 2026).**
It is OURS and it shipped before this document was written: `caller_memories` in our own
Postgres under FORCEd RLS, subject-keyed by `compliance/caller_ref.py` (HMAC under a
`PLATFORM_KEK`-derived key, tenant inside the MAC input), written by
`workers/caller_memory_distil.py` and destroyed by `retrieval/caller_erasure.py` and the
`caller_memory` retention category. §8.4's four reasons for keeping the document LEDGER in
our Postgres bind this store harder than they bind that one — reason 1 (tenant isolation
we can prove) and reason 2 (a DPDP erasure we can show returned zero rows) are the whole
reason the feature is shippable, and a vendor whose local build is single-tenant with one
API key cannot supply either. What Supermemory actually swaps is the **T3 member** of the
retrieval composite and nothing else (`apps/api/retrieval/service.get_retriever`). Read
§10.4's correction with this one: the same sentence priced a design, not the build.

**Box 3 lives ON box 2 until the first client.** The founder's box is 1 vCPU / 4 GB / 50 GB
and will be upgraded (4 vCPU / 8 GB or larger) when there is a client to upgrade for. That is
a deliberate dev-phase choice, not a target architecture: §8.3 states the condition that must
hold for it to be safe, and §11 sizes the box for real volumes.

### 8.1 Why the in-call KB is not a network call

⚠ **THIS SECTION SAID "ZERO NETWORK PER TURN" FULL STOP AND THAT BECAME TRUE-OF-ALMOST-EVERY-
TURN ON 14 SEP 2026 (§8.1a).** The lexical arm below is unchanged and still answers the
overwhelming majority; a DENSE second arm now fires on the turns it answers `not_found` or
`ambiguous`, and that arm is one hosted request. Read both halves before quoting either.

Box 1 fetches the agent's `KnowledgePack` ONCE at session start and searches it in-process
for the rest of the call. **Measured: p50 0.31 ms / p95 0.34 ms per lookup, zero network per
turn** — `tests/in_call_lookup_latency_test.py`, 400-entry pack, n=500 after warm-up, on the
development container (Intel Xeon @ 2.10GHz, 4 vCPU, contended) on 14 Sep 2026. ⚠ **THIS
SECTION SAID `0.501 ms p50` AND NOTHING IN THE TREE COULD REPRODUCE IT** — an ad-hoc run with
no corpus, no sample count and no machine recorded. The committed harness puts it at the same
order of magnitude and states its conditions; quote that file, not a bare number. The
alternative — box 1 asking box 3 on every question — costs 30–50 ms of network, and makes
every question on every call depend on a second machine being up and fast. A phone call has
no retry affordance: a caller hears the hesitation.

This is why "use Supermemory for the KB" and "the in-call KB is a pack in memory" are not in
conflict. Box 3 is where documents LIVE and where the pack is BUILT (at publish, once). Box 1
is where a question is ANSWERED. Nothing about adopting Supermemory changes that split.

### 8.1a The dense second arm (pack format v2, 14 Sep 2026)

**WHAT MOVED IS A MEASUREMENT.** The founder ran `scripts/gemini_embedding_harness.py`
against the live Gemini API with their own key — `models/gemini-embedding-001`, 3072
dimensions, n=24, English-only index. [VENDOR-PUBLISHED, founder-relayed live run, 14 Sep
2026. `ai.google.dev` is egress-blocked from the build container and nobody here has read a
vendor page for this model.]

| Query form | Gemini recall@1 | recall@3 | MRR | This index (§9.4) |
|---|---|---|---|---|
| English | 0.9583 | 1.000 | 0.9722 | 0.833 |
| Tenglish | **1.0000** | 1.000 | 1.0000 | 0.583 |
| **Telugu script** | **0.9583** | 1.000 | 0.9792 | **0.083 — 22 of 24 `not_found`** |

The Telugu-script row is the finding: two hits in twenty-four becomes twenty-three. That is
not a better ranking of the same answers, it is the removal of the English-paraphrase
dependency §9.4 calls load-bearing.

**THE CORPUS SIDE COSTS A CALL NOTHING.** Passage vectors are computed at PUBLISH
(`apps/api/kb/pack_vectors.py`) and travel inside the pack as base64 float32. **That was
arithmetic in prose until 14 Sep 2026 and is now weighed** (`tests/in_call_lookup_latency_
test.py`, against the exact bytes `kb/pack.publish_pack` uploads): a 300-entry pack at 3072
dimensions serialises to **5,003,292 B — 16,678 B per entry, of which 16,382 B is the base64
vector** — against **63,775 B** for one vector rendered as JSON decimals, so the encoding is
worth 3.9x. The ~16 KB / ~60 KB / ~5 MB figures were right. ⚠ **WHAT THAT DOES NOT SHOW is
that 5 MB fits inside `storage.PACK_FETCH_BUDGET_S`**: that budget is an assumption, no fetch
from a Pipecat Cloud `ap-south` container to the bucket has ever been timed, and a pack size
is not a transfer time. **UNMEASURED**, and §3.6 is where it closes. What is left on the call
path is ONE query vector.

**IT FIRES ONLY ON `not_found` AND `ambiguous`** — turns where the agent was about to tell
the caller it has nothing. The sub-millisecond `found` path is unchanged, which is the §4(b) finding
(unconditional fusion makes cells WORSE) respected rather than re-learned.

**IT CAN ONLY ADD.** A dense pass below `knowledge.DENSE_MIN_COSINE` leaves the lexical
answer standing, so a badly-set threshold costs at worst today's behaviour. The one case
where it makes a turn worse is deliberate: a FAILED query embedding answers
`temporarily_unavailable` rather than `not_found`, because once the code has consulted a
second arm it has said the first is not authoritative, and "this business publishes nothing
about that" would then be a claim about a client's business made out of our own outage.

**IT IS OFF UNTIL AN OPERATOR ATTESTS A PRICE.** ⚠ The Gemini embedding price is UNVERIFIED
(§10.4) and hard rule 7's pre-flight is asked BEFORE the provider is called, so
`pack_embedding_is_billable()` is False today, packs are built with no vectors, and the arm
is structurally unreachable. What closes it is one figure from a vendor invoice in the ops
console — an input outside this repository, not an engineering task.

**Budget:** `embedding.EMBED_BUDGET_S` = 1.2 s, strictly below `FUNCTION_CALL_TIMEOUT_SECS`
(2.0 s) so a hung encoder still returns the honest word INSIDE the tool call. ⚠ That number
is an ASSUMPTION with a measurement beside it: five POSTs to the live route from the build
container on 14 Sep 2026 took 0.24–0.51 s including TLS (~0.16 s warm), against an INVALID
key so no inference ran and over the wrong network. The real figure is larger and is UNKNOWN
until the first live call from Pipecat Cloud `ap-south` measures it (§3.6).

### 8.2 What the pack contains, and how big it is

Everything the client has published **for one agent** — every active chunk, as text plus its
English gloss. Not the platform's KB, not other clients, not other agents. Chunk text is
capped at 4,000 characters (`calevate_shared/knowledge_pack.py`), so a 50-page client KB is a
few hundred chunks.

⚠ **THIS SECTION SAID "a few hundred KB of text, ~1 MB with the search index" AND IT WAS
WRITTEN BEFORE v2 CARRIED VECTORS.** Measured, 14 Sep 2026
(`tests/in_call_lookup_latency_test.py`, over the exact bytes `kb/pack.publish_pack` uploads),
300 entries of short shop facts:

| pack | serialised | per entry |
|---|---|---|
| v1 / v2 with no vectors | 88,667 B | 296 B + the chunk's own text |
| v2 at 3072 dimensions | **5,003,292 B (5.00 MB)** | 16,678 B |

**The vector is a FIXED 16,382 B per entry whatever the text weighs**, so the lexical-only
figure scales with the corpus and the dense one barely does: at 4,000-character chunks the
text still loses to the vector. A vector-carrying pack is therefore MEGABYTES, not ~1 MB, and
the "rounding error" framing only ever applied to the lexical one. It remains small against
the ONNX turn-detection model and the Pipecat runtime the container already holds (hundreds
of MB) — but ⚠ **what 5 MB costs to FETCH is UNMEASURED**: `storage.PACK_FETCH_BUDGET_S` is an
assumption, a size is not a transfer time, and no fetch from Pipecat Cloud `ap-south` to the
bucket has been timed (§3.6).

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
   **WHAT THAT MEANS NOW THAT DOCUMENTS ACTUALLY REACH BOX 3 (15 Sep 2026, step 15's write
   half):** the copy exists, so the obligation follows it. `kb_index_documents` records what
   was sent, `retrieval/supermemory_index.purge_tenant_index` sends a scope-wide delete and
   empties those rows inside `execute_tenant_erasure`, and `scripts/check_erasure_coverage.py`
   walks that module so the table is reached from an erasure entrypoint rather than believed
   to be. Two things are deliberately NOT claimed: the vendor publishes no way to verify a
   deletion, so `deletion_proof` stays **False** and the certificate says "an accepted request
   rather than a confirmed removal" in those words; and if the credential is gone while rows
   remain, the erasure **raises** and issues no certificate at all rather than certifying a
   copy nothing can address.
3. **Provenance.** The pack carries `document_id` + `document_version`, so an answer on a call
   traces to "brochure v3, chunk 12" — which is what a client sees when they ask why the agent
   said something. The id has to be minted by us.
4. **Rebuildability.** If box 3 is ever rebuilt (bug, version upgrade, migration), the ledger
   says what should be in it.

### 8.5 Supermemory's status: adopt behind the adapter, pin on a version

`calevate_shared.retrieval.RetrievalProvider` and `apps/api/retrieval/service.get_retriever`
already exist for exactly this (D-502). Supermemory becomes a provider behind that seam:
dashboard copilot and CRM search read from it; if it is down, calls do not notice and
uploads do not notice — only dashboard search degrades to the Postgres fallback.

⚠ **"and caller memory" WAS IN THAT LIST AND IS STRUCK (15 Sep 2026)** — see the §8 box-3
correction. Caller memory does not read through `RetrievalProvider` at all: its reader is
`compliance/caller_memory.recall`, recency-ordered over our own table, and the seam a caller
on the voice leg reaches it through is `GET /v1/engine/caller-data/{engine}`. Moving it
behind this provider would put a data principal's durable profile in a store whose local
build is single-tenant with one API key, which §8.4 reason 1 refuses for strictly less
sensitive data.

Three open issues bear on WHICH RELEASE we pin, and all three are **UNVERIFIED as to current
state** (nobody has read the live issue pages; `supermemory.ai` is egress-blocked from this
container):

- **#1336** — custom embedding env vars ignored (see §8.3; the `top` check substitutes).
- **#1315** — searches return empty on Linux in 0.0.6.
- **#1320** — segfault under concurrent embedding.

These are a version gate, not a verdict. The founder's position — "bugs are not blockers, they
will be fixed" — is accepted: what is refused is pinning a release whose search returns
nothing, which the empirical check above catches in one upload.

### 8.6 HOW `kb_chunks` IS RETIRED — THE PLAN STEP 15 RUNS AGAINST (D-604)

**STEP 15 MAY NOT RUN YET, AND THE GATE THAT SAYS SO IS NOT "STEP 14 LANDED".** Step 14's
row says the ADAPTER landed. Four things it does not say, each checked in this tree on
15 Sep 2026 rather than recalled:

1. **Nothing has ever written to box 3.** `grep -rl supermemory apps packages scripts`
   returns six files — `retrieval/{service,supermemory,supermemory_wire,tiered}.py`,
   `core/platform_config.py`, `calevate_shared/config.py` — and NONE of them is under
   `apps/workers` or `apps/api/kb`. There is no ingestion path, so the store a retirement
   would cut over to is empty. Retiring `kb_chunks` today deletes the only populated store.
2. **Nobody has read the vendor's API.** `supermemory.ai` is egress-blocked from this
   container; every path and key is an ASSUMPTION in `retrieval/supermemory_wire.
   ASSUMED_CONTRACT`, and the adapter is written to FALL BACK on a shape we guessed wrong —
   which is correct behaviour and is also why a green test suite proves nothing about the
   wire.
3. **The incumbent's recall was never measured either.** The only recall figures in this
   tree (`tests/in_call_retrieval_recall_test.py`) score the IN-CALL pack, which §8.1 does
   not retire. So "Supermemory is better" had no baseline to be better than.
4. **A search costs money that hard rule 7 does not yet permit.** No embedding price has
   been attested, so `supermemory.search_is_billable()` is False and the provider is not
   even selectable.

⚠ **UNKNOWN, IN THOSE WORDS**: whether a Supermemory install answers our assumed contract,
what it costs per search, what its recall is on any corpus, and the current state of
upstream issues #1336 / #1315 / #1320. None of these can be settled from this container.

**WHAT MUST BE TRUE BEFORE THE PGVECTOR PATH MAY BE RETIRED.** Each is a fact somebody
produces, not a judgement somebody makes:

| # | Must be proven | How it is proven, and where the evidence lands |
|---|---|---|
| a | **Reachable.** A box 3 exists, answers on `supermemory_base_url`, and its responses match `ASSUMED_CONTRACT` — or the contract is corrected to what it really sends. | `GET`/`POST` from the host, plus §8.3's `top` check that embedding is NOT running on the local CPU. Corrections land in `ASSUMED_CONTRACT` with the page and date; OPERATIONS §2 gets the gate. |
| b | **Priced.** An operator has attested the embedding price from their own invoice, so `search_is_billable()` is True. | Ops console. Until then the provider cannot be selected at all, so (c)–(e) are unreachable. |
| c | **Ingested.** An ingestion path EXISTS, HAS RUN over a real tenant's published sources, and every record carries the tenant tag and our `source_id`/`document_version` metadata. | The sweep's own logs plus a scoped search returning records `supermemory_wire.parse_search` keeps rather than rejects. `supermemory_records_out_of_scope` at zero is part of the proof, not a detail. |
| d | **Measured.** `retrieval/compare.py` scores BOTH arms over the same corpus and the same `k`, and the challenger does not lose recall. | `compare_arms` against the real `PgVectorRetriever` and the real `SupermemoryRetriever`. The number goes in `docs/evidence/`, with the corpus named. A table measured over two different question sets is an artefact, which is why it is one function and not two. |
| e | **Agreed in production.** The shadow read (below) has run on live dashboard traffic for enrolled tenants and the disagreement rate is understood — not necessarily zero, but every class of difference explained. | `retrieval_shadow_compared` log lines. |
| f | **Rollback without a redeploy.** Setting `retrieval_provider` back serves the next question from Postgres. | `Settings.retrieval_provider` is `applies: live` and `get_retriever` is called per request and holds no state (`tests/retrieval_shadow_test.py::test_the_switch_turns_the_comparison_on_and_off_between_two_requests`). **This one is already true**, and it stays true only while `kb_chunks` is still populated — which is exactly why the drop is last. |

**THE TWO-STEP SHAPE HARD RULE 8 DEMANDS.** `kb_chunks` is a tenant table with FORCEd RLS
and a live writer inside the publish transaction (`kb/service.project_chunks`), so its
retirement is three releases and not one:

* **Release 1 — STOP READING.** `retrieval_provider = supermemory` platform-wide. Nothing
  is dropped, nothing stops being written, and the rollback in (f) is one setting. The
  projection keeps running, which is what makes the rollback free.
* **Release 2 — STOP WRITING.** `project_chunks` and `workers/kb_embeddings.py` stop
  writing, after a sweep proves NOTHING READS: no `PgVectorRetriever` construction outside
  the shadow arm, no `kb_chunks` in any query path, `retrieval_shadow_arm` off. The table
  stays, populated and readable, and a reversal is a re-enabled writer plus a backfill.
* **Release 3 — DROP,** in a LATER release than 2, never the same one. A reversible
  migration that drops `kb_chunks`, its indexes and its RLS policy, with a `downgrade` that
  recreates them — and the backfill from `kb_documents` that makes the downgrade mean
  something, because every byte in `kb_chunks` is derived (D-502).

`kb_documents` stays in all three. §8.4's four reasons are unchanged and the fourth is the
one that makes release 3 safe at all: the ledger says what should be in box 3.

**WHAT LANDED INSTEAD, 15 SEP 2026, AND WHY IT IS THE USEFUL HALF.**

* **`apps/api/retrieval/shadow.py` — the shadow read.** The industry's way to retire a
  retrieval path: ask the challenger the same live question, record how far apart the two
  arms were, and serve the incumbent's answer regardless. `ShadowReadRetriever.retrieve`
  returns the primary arm's own `RetrievalResult` OBJECT — not a copy, not a merge — and the
  challenger's answer reaches one log line and nothing else. It wraps the T3 member, so a t0
  question never pays for a comparison that is true by construction; it is sequential rather
  than concurrent because both arms may hold the caller's one `AsyncSession`.
* **`apps/api/retrieval/compare.py` — the harness.** recall@1, recall@k, MRR and agreement,
  keyed on the DOCUMENT (`Provenance.source_id`, which both adapters carry because we minted
  it) rather than on chunk text, which would score the two chunkers instead of the two
  stores. Provider-agnostic, so the same scoring runs offline in CI over
  `tests/fixtures/telugu_gloss_corpus.json` and against a live box 3 unchanged.
* **Two LIVE settings, both off.** `retrieval_shadow_arm` names the store to ask in the
  dark; `retrieval_shadow_tenant_ids` names whose questions may be asked, **and empty means
  nobody**. Two rather than one because a shadow search buys an embedding and meters it
  against the tenant whose question it was — a platform-wide switch would spend every
  client's AI quota on an experiment they did not ask for.

---

## 9. THE LANGUAGE PATH, END TO END

The design question: a caller speaks an Indian language — often mixing it with English —
and must be answered in the same language, with KB retrieval working throughout.

⚠ **THIS SECTION READ AS A TELUGU DESIGN UNTIL 14 SEP 2026, AND THAT WAS A SCOPE ERROR, NOT
A SIMPLIFICATION.** Nothing in the mechanism is Telugu-specific. The model paraphrases the
caller's question **into English** before the index is touched (§9.1 step 2), and a
paraphrase is written from whatever the model has just read — Telugu, Marathi, Bengali or a
sentence that switches script mid-clause. Telugu is the language the MEASUREMENTS were taken
in, because that is the corpus this repository has; it is not the design's reach. **The
reach is set by the two vendor legs, not by us: Sarvam STT understands 17 language codes and
Sarvam TTS speaks 11, and an agent converses only in the intersection** — §9.5, which also
records the product constraint that follows from those two lists not matching. (D-600.)

### 9.1 The turn, in order

1. Caller speaks. **Sarvam STT** transcribes. Saaras v3/v4 default to `"unknown"` =
   auto-detect [VERIFIED-VENDOR-SDK: `pipecat/services/sarvam/stt.py:118,207-208`, installed
   `pipecat-ai==1.10.0`, re-read 14 Sep 2026], so nobody has to declare the language up
   front, and what may come back is §9.5's list rather than a language we configured.
2. **The LLM reads the transcript.** If it needs a fact it calls the search tool and **writes
   the query itself, in English**. No translation hop, no extra vendor: writing an English
   query is part of the model's own reading, the same way it would answer in English if asked.
   [VERIFIED: `llm_service.py:917,1024` `register_function`/`register_direct_function`;
   `google/llm.py:213,367` passes `tools`.] **THIS IS THE STEP THAT MAKES THE PATH
   LANGUAGE-GENERAL**, and it is also the step §9.4 shows is load-bearing: the index never
   sees the source language, so adding a source language costs the index nothing.
3. **Search runs in the worker's memory** over the English index. Sub-millisecond — p50
   0.31 ms on a 400-entry pack, `tests/in_call_lookup_latency_test.py` (§8.1 for conditions).
4. **The LLM composes the reply in the caller's language.**
5. **Sarvam TTS speaks it.** `target_language_code` is sent per request on the HTTP leg and
   in the opening config on the websocket leg (`sarvam/tts.py:564,1060`); the 11 locales it
   may be set to are §9.5's.

**STT is ears, the LLM is the brain and does all translating in both directions, TTS is the
mouth.** TTS does not translate; this was a live misunderstanding on 14 Sep 2026 and is
recorded so it is not repeated. It is also why the language count is a vendor fact rather
than a feature we build per language: adding Kannada is not a code path, it is a voice and a
language code.

### 9.2 English-only indexing

⚠ **THIS IS THE LEXICAL INDEX, AND SINCE 14 SEP 2026 IT IS NOT THE ONLY ONE (§8.1a).** The
dense arm embeds the client's OWN WORDS together with the gloss and reads the source language
directly, which is why its Telugu-script row is 0.9583 against this one's 0.083. Everything
below remains exactly right about the arm it describes; "the index is English-only" is no
longer a statement about in-call retrieval as a whole.

**Store BOTH, index ONE.** Every chunk keeps the client's original text (for display,
provenance and the client-facing record) and an English gloss. **Only the English is
indexed and searched.** Justification is measured, not assumed
(`docs/evidence/telugu-embedding-quality.md`, n=24): matching query words against
Telugu-script text scored **0.042**; against English, **0.625**. Since step 2 above guarantees
every query arrives in English, the source-language text in the index is pure noise.

**What that pair of numbers is evidence FOR is the mechanism, not the language.** A lexical
index shares no tokens with text written in a script the index does not contain, and that is
a property of tokens rather than of Telugu — so the same design applies to every language in
§9.5. ⚠ **MEASURED-HERE IN TELUGU ONLY** (`docs/evidence/telugu-embedding-quality.md`, 31 Aug
2026; re-measured end-to-end 14 Sep 2026, §9.4). Devanagari, Bengali, Tamil, Kannada,
Malayalam, Gujarati, Gurmukhi and Odia are **UNMEASURED**: the design expects them to behave
the same way and nobody has run the corpus. Reasoning from one script to the rest is how the
numbers would stop meaning anything, so they are labelled rather than assumed.

Do NOT store romanised source text as a searchable form — Tenglish, Hinglish or any of the
rest. There is no standard spelling for any of them, so it multiplies index entries without
adding recall, and §9.4 has the number for what romanisation is worth against this index.

### 9.3 The one OPEN question on this path

⚠ **Whether Bulbul v3 pronounces text correctly when the script does not match
`target_language_code`, and whether there is any auto/mixed setting, is UNKNOWN.**
`docs.sarvam.ai` is egress-blocked from this container. Pipecat CAN change the setting
mid-session (`TTSUpdateSettingsFrame`, `pipecat/frames/frames.py:2375`), so if a per-turn flip
turns out to be necessary the mechanism exists; what is unknown is whether it is necessary.
It is one question for all 11 languages, not one per language.

A Comet brief covering this sits in `docs/evidence/` (Part 2 of the 14 Sep 2026 vendor brief).
Until it is answered, no code assumes either behaviour.

### 9.4 Reliability, and how it is guarded

The failure mode is not translation — it is a bad English paraphrase ("doctor timings" vs
"when is the doctor available"). Three things absorb it: the English gloss, top-3 results, and
the `ambiguous` state. What closes it properly is a **golden set of questions in the caller's
language → expected English hit, run in CI**, so a regression is a red test rather than a bad
call. That is step 13 in §6, and **its first arm landed on 14 Sep 2026**:
`tests/in_call_retrieval_recall_test.py` scores the real pack, the real index and the real
`SessionKnowledge.search` over the 24-fact Telugu corpus asked three ways, plus a
hand-written code-mixed set.

**MEASURED-HERE, 14 Sep 2026** (`tests/in_call_retrieval_recall_test.py`, n=24, English-only
index, `DEFAULT_TOP_K`=3; recall counted over the passages the caller's turn would actually
have received, so an `ambiguous` answer contributes its two and a `not_found` contributes
none):

| Query form reaching the index | recall@1 | Outcome |
|---|---|---|
| English — **the form step 2 actually emits** | **0.833** | the control, and it wins |
| Romanised (Tenglish), unparaphrased | **0.583** | degrades gradually |
| Telugu script, unparaphrased | **0.083** | **22 of 24 answered `not_found`** |

**SO THE ENGLISH PARAPHRASE IS LOAD-BEARING, NOT A CONVENIENCE.** If it ever stops — a prompt
edit, a model swap, a tool description that stops asking for it — in-call retrieval does not
degrade, **it stops**, and 0.083 is the number it stops at. ⚠ **AND THAT IS WHY §8.1a EXISTS:
the dense arm is the floor under this failure**, measured at 0.9583 on the same Telugu-script
row — but only once a price is attested, so until then the sentence stands unqualified. That conclusion is what
generalises: the index has no tokens in common with any non-Latin Indic script, so every
language in §9.5 depends on step 2 exactly as Telugu does, and a change to the search tool's
description is a change to all of them at once.

A fourth set, ten code-mixed questions (Telugu or Hindi words inside an English sentence),
scored **1.000**. ⚠ **It is not comparable with the three rows above and must not be quoted
beside them.** The test's own docstring says why: ten topically disjoint facts against
twenty-four related ones, and the English nouns a code-mixed speaker keeps — "delivery",
"UPI", "parking" — are themselves the match. It is evidence that the register works, not
that the harder corpus is fine.

### 9.5 WHAT AN AGENT CAN HEAR IS NOT WHAT IT CAN SPEAK

[VERIFIED-VENDOR-SDK: `pipecat-ai==1.10.0` as installed in `.venv`, read 14 Sep 2026.]

**Sarvam STT — 17 codes** (`pipecat/services/sarvam/stt.py:738-755`, the inbound map
`_map_language_code_to_enum`): `as-IN`, `bn-IN`, `en-IN`, `en-US`, `gu-IN`, `hi-IN`, `kn-IN`,
`kok-IN`, `mai-IN`, `ml-IN`, `mr-IN`, `od-IN`, `pa-IN`, `sd-IN`, `ta-IN`, `te-IN`, `ur-IN`.

**Sarvam TTS — 11 India locales** (`pipecat/services/sarvam/tts.py:219-243`): `bn-IN`,
`en-IN`, `gu-IN`, `hi-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `od-IN`, `pa-IN`, `ta-IN`, `te-IN`.

**An agent converses in the INTERSECTION, and the intersection is the smaller list.**
Assamese, Konkani, Maithili, Sindhi and Urdu can be **heard and not answered**: STT will
return a clean transcript, the LLM will read it, and there is no voice to say the reply in.

⚠ **THAT IS A PRODUCT CONSTRAINT, NOT A FOOTNOTE, AND IT IS DISCOVERED ON A LIVE CALL IF IT
IS NOT ENFORCED BEFORE ONE.** An agent whose configured language has no TTS leg is an agent
that listens politely and cannot reply — the worst shape a failure can take on a phone call,
because it looks like the product working right up until the moment it has to speak. The
enforceable form is the same one hard rule 5 uses for the disclosure lines: an agent may only
be configured in, and may only be published in, a language present in BOTH lists. The
conversational set is therefore **11 languages**, and it is the number to quote to a client.

⚠ **THE ODIA TRAP IS REAL, AND IT IS INSIDE ONE FILE.** Odia is spelled **two different ways
by the same installed package**, both for the same `Language.OR_IN`:

| Where | Emits | Line |
|---|---|---|
| STT, batch/saaras path (`language_to_sarvam_language`) | `od-IN` | `stt.py:86` |
| STT, inbound code → enum map | `od-IN` | `stt.py:748` |
| STT, **realtime** path (`language_to_sarvam_realtime_language`) | **`or-IN`** | `stt.py:877` |
| STT, realtime `SUPPORTED_LANGUAGES` set | **`or-IN`** | `stt.py:809` |
| TTS (`language_to_sarvam_language`) | `od-IN` | `tts.py:235` |

So the wire value depends on which Sarvam leg is being spoken to, and the two legs disagree
inside one vendor SDK. Never hard-code either spelling, never carry Odia as a string in our
own config, and never assume a code that round-trips on one leg round-trips on the other:
pass `Language.OR_IN` and let each service's own mapper emit its own spelling. ⚠ **WHICH
SPELLING SARVAM'S API ACTUALLY ACCEPTS ON EACH LEG IS UNKNOWN** — `docs.sarvam.ai` is
egress-blocked from this container, so what is verified is what the SDK sends, not what the
vendor takes. Odia is the one language in the 11 that must be proven on a real call before it
is offered to a client.

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

⚠ **"ZERO EMBEDDINGS ON THE CALL PATH" WAS TRUE UNTIL 14 SEP 2026 AND §8.1a IS THE CHANGE.**
The dense fallback buys ONE query embedding on each turn the lexical arm answers `not_found`
or `ambiguous` — a short question, on a minority of turns, against the per-call figures
below, so it does not move the per-minute model. It is also OFF until the price this section
says is unverified has been attested, which is the same fact stated twice: hard rule 7 will
not let an unpriced embedding reach `unit_cost_paid`, so it will not let one be bought.

**Zero embeddings on the call path** — the pack is lexical.

⚠ **THIS PARAGRAPH SAID EMBEDDINGS OCCUR TWICE PER CALL — "caller-memory read at start,
write at end, ~165 tokens total" — AND CALLER MEMORY BUYS NEITHER (15 Sep 2026).** It
priced the Supermemory design the box-3 row also described; the SHIPPED store is ours and
neither half of it embeds anything. The **read** is one HTTP GET to
`/v1/engine/caller-data/{engine}`, answered from two indexed Postgres reads and an HMAC —
recency-ordered, with no relevance channel at all, and `compliance/caller_memory.recall`
argues why there is none (at the moment the prompt is built there is no question yet, so
there is nothing to be relevant TO). The **write** is `workers/caller_memory_distil.py`, an
hourly cron that buys a CHAT completion — larger than an embedding, not smaller — and it is
already metered through `record_ai_assist_usage`, so it reaches the client's bill and their
spend cap can stop it. Nothing about either is on the call path: the read is spent on the
ring concurrently with the pack fetch (`voice_worker/session.open_session`), and the write
happens after the call, on another box, on another clock. **The per-minute model does not
move either way**, which is the only claim this paragraph was load-bearing for.

Embeddings therefore occur once per DOCUMENT at
publish (a 50-page KB ≈ 25,000 tokens). For scale: a 3-minute call already sends **25,380**
input tokens to the LLM and a 10-minute call **160,200** (derived from `REFERENCE_CALL`). So
embedding traffic is 150×–1,000× smaller than the LLM traffic already on the same call.

⚠ **"AT 10,000 CALLS/MONTH THE EMBEDDING VOLUME IS 1.65 M TOKENS" WAS 10,000 × THE 165
TOKENS PER CALL THE CORRECTION ABOVE DELETES, so the whole figure and the ≈ ₹145 × P per
month it produced went with it.** Nothing replaces it as a per-CALL number, because calls
now buy no embeddings at all (the §8.1a dense arm is the one exception, it is structurally
OFF until a price is attested, and it is per-TURN-that-failed rather than per call). The
volume that remains is per-DOCUMENT at publish, which scales with what clients upload and
not with how much they are rung — and nobody has a client upload figure to multiply, so
stating one would be a guess dressed as a finding.

⚠ **THE GEMINI EMBEDDING PRICE IS STILL UNVERIFIED IN THIS REPOSITORY, AND THE ENCODER
MOVED (D-608, 15 Sep 2026).** `ai.google.dev` is egress-blocked from this container
(re-measured 14 Sep 2026, CONNECT rejected) and nothing since has re-fetched it. What
changed is which model the leg names and where a price can come from:

* `kb/pack_vectors.EMBEDDING_MODEL` is now **`models/gemini-embedding-2`**, because
  `gemini-embedding-001` carries **no price on the vendor's page at all** — a model nobody
  publishes a price for can never be attested against an invoice line, so that leg was
  unreachable by construction. The recall measurement is a WASH between the two (n=24;
  1.000/1.000/0.958 against 0.958/0.958/1.000) and must not be read as an upgrade.
* The vendor lists the new model at **$0.20 per 1M INPUT tokens** standard, $0.10 batch,
  with **no output charge** — Google pricing page dated 2026-09-11. **EVIDENCE CLASS:
  VENDOR-PUBLISHED, FOUNDER-RELAYED.** It is a pre-fill on the ops console's form and
  nothing else; hard rule 7 gives it no path to `unit_cost_paid`.
* The only door is now open: an operator attests the figure at
  `POST /v1/ops/embedding-prices/{model}`, **input-only**, and until they do BOTH encoder
  legs are no-ops, every pack is built lexical-only and nothing is charged.

**WHAT AN ATTESTED PRICE WOULD ACTUALLY BUY IS STILL NOT A NUMBER ANYBODY HERE HAS**, for
the reason the paragraph above gives: the volume is per-DOCUMENT and scales with client
uploads. The formula is unchanged — tokens published × the attested input rate — and the
multiplicand is UNKNOWN until there are clients uploading. What IS now true is that when
those rupees are spent they are visible per client and on their own, separately from
dashboard AI, on both the admin spend board (`AbsorbedAiSpendOut.kb_used_inr`) and the
client's own screen (`AiQuotaOut.kb_used_inr`).

⚠ **The cost to watch is not embedding — it is Supermemory's per-chunk LLM call at ingestion.**
A 50-page document is ~200 chunks, each drawing a Gemini *chat* call far larger than an
embedding call. This is also why ingestion must be QUEUED, never inline: one client uploading a
300-page manual must not sit in front of another client's memory write on a 1 vCPU box.

---

## 11. SIZING BOX 3

**Box 3's load scales with calls per HOUR, not concurrent calls.** Calls run on box 1 with the
pack; box 3 sees dashboard traffic. The heavy work — ingestion — happens at upload, not at
call time.

⚠ **THIS SAID "box 3 sees exactly two requests per call (memory read, memory write)" AND
BOX 3 SEES NEITHER (15 Sep 2026)** — caller memory is ours and lives in box 2's Postgres
(the box-3 row in §8 carries the correction). The two requests per call are real, they are
just aimed at **box 2**: `GET /v1/engine/caller-data/{engine}` on the ring, and the hourly
distiller's read afterwards. The `Box-3 requests/hour` column is therefore an overcount of
box 3 and an equal undercount of box 2, and every row's Box and Real bottleneck are ESTIMATE
(they always said so) rather than measurements that moved. Two indexed reads and an HMAC per
call do not change which tier anybody sits in; what the column is still right about is the
SHAPE — per hour, not per concurrent call.

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

✅ **APPLIED, 14 Sep 2026.** Founder decision of the same day: **Clear ₹4.00 flat; Studio
₹7.00 at the ₹2,000 pack down to ₹5.50 at the ₹50,000 pack**, middle Studio rungs at even
₹0.30 steps. `billing/credit_packs.PACK_CATALOGUE` carries it; the card it replaced was
Clear 5.00→4.50, Studio 8.00→6.00.

The change was one edit to the catalogue and a WIDE test update: the old rates were pinned
as literals, and as arithmetic derived from them, across sixteen test files. It had been
attempted and reverted once rather than rushed, because a half-checked substitution across
fixtures that do arithmetic on the old numbers is how a wrong rate reaches an invoice.

**WHAT THE SECOND ATTEMPT DID DIFFERENTLY, AND THE FOUR SITES THAT NEEDED MORE THAN A
SUBSTITUTION.** Every rate that was an assertion ABOUT THE CARD IN FORCE is now derived
from `PACK_CATALOGUE` rather than retyped, so the next move of the card is a one-line
change. Four tests were not substitutions at all — a flat Clear column deletes the
difference they were built on, and a blind replace would have left each one passing while
proving nothing:

* `credit_lot_reprice::test_the_next_call_is_charged_at_the_replacements_rate` re-priced a
  `growth` lot to `max` and charged a CLEAR minute. Both rungs now sell Clear at ₹4.00, so
  it would have passed whether or not the re-price did anything. Moved to Studio.
* `credit_refund_lots::test_a_refunded_purchase_does_not_price_the_clients_next_top_up` had
  the identical problem: a phantom `max` lot and a real `starter` lot price Clear the same,
  so the money defect it guards became invisible. Moved to Studio.
* `credit_lot_reprice::test_a_reprice_that_raises_both_tiers_names_both_of_them` can no
  longer be reached from ANY pair of catalogue packs — no pack raises Clear against another
  — so the plural branch of the refusal message is now driven from a lot opened at rates
  below every rung, which is what a bespoke `override` lot holds.
* `cost_floor::test_the_approved_card_clears_both_floors_and_every_rung_clears_target`
  asserted the opposite of the truth and is renamed: it now asserts the POSTURE (below cost
  is refused, under target is warned) and reads the twelve margins back rather than
  encoding the rule in them.

`tests/credit_lots_helpers.GROWTH` / `PLUS` deliberately KEEP the 7 Sep figures. A lot's
rates are frozen for the life of its credit, so a wallet really does hold rows priced at
cards no longer sold — and with Clear flat, fixtures rebuilt from today's catalogue could
not show a call splitting across two lots at two Clear rates at all.

**THREE FRONTEND SURFACES CARRIED A SENTENCE, NOT A RATE, AND ALL THREE WERE FALSE.** No
page holds a price — every figure renders from the API — but `billing/WhatCallsCost.tsx`
rendered "₹4.00 a minute, down to ₹4.00 on the largest pack", `pricing/page.tsx`'s section
heading promised "the rate comes down as the pack gets bigger" above a table with a voice
switch, and `marketing/roiCalculator.tsx` said "Down to ₹X/min on the deepest pack" in both
voice captions. Each now derives the claim from the card, per column.

| Pack | Clear | Clear margin | Studio | Studio margin |
|---|---|---|---|---|
| starter ₹2,000 | ₹4.00 | 17.2% | ₹7.00 | 32.7% |
| growth ₹5,000 | ₹4.00 | 17.2% | ₹6.70 | 29.7% |
| scale ₹10,000 | ₹4.00 | 17.2% | ₹6.40 | 26.4% |
| plus ₹15,000 | ₹4.00 | 17.2% | ₹6.10 | 22.8% |
| pro ₹25,000 | ₹4.00 | 17.2% | ₹5.80 | 18.8% |
| max ₹50,000 | ₹4.00 | 17.2% | ₹5.50 | 14.4% |

**8 of 12 cells sit under the 20% gross-margin target.** None is under COST, so the ops console
warns rather than refuses — eight WARNING lines in its card preview, which
`tests/ops_rate_card_write_test.py` now pins by count and by set. This is a deliberate price cut
to win the first clients, recorded as a decision rather than absorbed silently. To hold 20%
instead: Clear ₹4.15, Studio floor ₹5.90. **Do not "fix" a thin cell by nudging a rate** — it is
the founder's number, and the guard's job is to make it visible.

Two consequences of the cut that are worth having written down:

* **The Studio break-even volumes all moved out.** A rung stops losing money at a higher
  monthly volume when its rate is lower: 82 / 87 / 93 / 99 / 106 / 114 platform call-minutes
  a month (were 69 / 82 / 86 / 91 / 96 / 101). At the ops console's bottom ladder rung —
  100 call-minutes, ₹6.0211 a minute — `pro` and `max` are under water, where only `max` was.
* **The ROI calculator's case got STRONGER, by lowering our own side.** The published
  comparison's gap widened from ₹12,000 to ₹22,400 a month at its default inputs.

`credit_packs.py::PACK_CATALOGUE` is the single source, and the margin figures above are
recomputed from it against `rates.cost_floor_inr_per_min` rather than copied.
