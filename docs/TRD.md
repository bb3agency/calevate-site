# Calevate — Technical Requirements Document (TRD)

Version 1.0 · July 2026 · Audience: engineering (Sri + collaborators)
All choices are final unless a decision-log entry (ROADMAP.md §6) supersedes them.

---

## 1. Architecture Overview

Style: **modular monolith API + isolated latency-critical runtime**, NOT microservices.
Fault isolation and swappability come from bulkheads (queues, timeouts, circuit breakers)
and code-level interfaces (Protocols + DI), not from network boundaries. Four deployables:

| Service | Runtime | Responsibility | Scaling driver |
|---|---|---|---|
| `web` | Next.js 15 (App Router), TypeScript | Admin console (admin.calevate.tech) + client app (app.calevate.tech) | Traffic; CDN-cached |
| `api` | FastAPI (Python 3.12) modular monolith | Auth/tenancy, agent config, CRM, analytics, billing, KB mgmt | Requests; deploy freely |
| `voice-runtime` | FastAPI, separate deploy | Engine webhooks, in-call tool endpoints (RAG search, booking), engine adapters | **Concurrent calls; never redeployed casually; a dashboard deploy must not touch live calls** |
| `workers` | ARQ on Redis | Post-call pipeline, embeddings, campaign dispatch, notifications, redaction, retention jobs | Queue depth; crashes delay work, never drop calls |

Shared infra: PostgreSQL 16 (+pgvector) on the host, Redis (Compose), Cloudflare R2
object storage. Hosting (D-25 narrows D-13): the site stack is NOT in the live-call
path (the rented engine — Bolna, D-31 — hosts the entire call in v1), so it deploys on a general-purpose VPS
— see DEPLOYMENT.md. D-13's India-co-location reasoning still binds every future
IN-CALL-PATH service (the M3 RAG tool endpoint deploys to an India region host;
co-location saves 50–100ms/turn and the 100ms retrieval budget is unmeetable from EU).

Module boundaries inside `api` (each owns its tables; no cross-module SQL; communicate via
service interfaces): tenancy, agents, engine, campaigns, ingest(webhooks-in), postcall,
crm, analytics, billing, kb, integrations, compliance, audit.

## 2. Stack (locked)

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic, `uv`,
  Ruff + mypy(strict) in CI. One backend language (voice/AI ecosystem is Python-first;
  phase-2 Pipecat runtime reuses everything).
- **Frontend:** Next.js 15 + TypeScript, Tailwind + shadcn/ui, TanStack Query, Recharts/
  Tremor. Typed API client generated from FastAPI OpenAPI. (Bolna publishes no OpenAPI
  spec — adapter models are hand-maintained from docs + pilot-captured payloads, §5.)
- **DB:** Postgres 16 for all system-of-record data. Vector/RAG: a managed RAG/memory
  service via API (D-28 — supersedes the earlier in-Postgres pgvector plan and the "no
  external vector DB" rule; D-08's RTT physics now governs provider REGION choice and
  keeps v1 in-call retrieval on the engine's built-in KB — TRD §6).
- **Queue:** Redis + ARQ. Promote only campaign orchestration to Temporal if/when retry
  semantics outgrow ARQ. Not before.
- **Auth:** Clerk (Organizations) — admin realm and client realm are separate applications
  with separate session cookies. MFA mandatory on admin realm.
- **Storage:** R2/Spaces, SSE encryption, presigned URLs (5-min TTL), never public.
- **Observability:** OpenTelemetry traces; Sentry (errors); operator alerts by email.
  LLM tracing (prompt versions, per-call token cost, latency breakdown) is a NAMED GAP,
  not a component — see the correction below.
  Shipped in `apps/api/core/observability.py`, all of it config-gated (no keys ⇒ no-op):
  the trace crosses the queue boundary — the W3C traceparent rides in the ARQ job payload
  (`TRACE_KWARG = "_calevate_traceparent"`) so voice-runtime → ARQ → worker → adapter is
  ONE trace and "where did the two minutes go?" is answerable. Span attributes are an
  ALLOWLIST (`ALLOWED_SPAN_ATTRIBUTES`), not a denylist, and every value must be id-shaped
  by the logger's own `redact_text` — a denylist on a tracing API fails open (hard rule 6).
  **Read "shipped" precisely.** OTel and Sentry are wired end to end. **Langfuse and
  PostHog configuration was REMOVED rather than wired** (D-49): `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY` and `POSTHOG_KEY` were settings with no client — no-ops even WITH
  credentials, which is worse than absent, because the next reader assumes traces are
  being recorded. **Per-call token cost and the latency breakdown named above are NOT
  being recorded and are not one config value away**: restoring Langfuse needs a project nobody holds plus a decision-log entry
  choosing a second tracing pipeline beside the OTel one already shipped, and PostHog
  restores as `NEXT_PUBLIC_POSTHOG_KEY` in `apps/web`, where browser analytics belongs.
  The restore steps sit in `calevate_shared/config.py` beside `SENTRY_DSN`, and a test
  pins that the keys stay gone.
- **Alerting:** `apps/api/core/alerting.py` (D-49). Every `alert()` writes its structured
  ERROR log first and unconditionally, then DELIVERS by email through the same transport
  as hot-lead notifications, off the request path on a daemon thread, with per-fingerprint
  repeat suppression (15 min, keyed `stage:code`) and a global hourly token bucket whose
  drops are counted and reported in the next body. It deliberately touches neither the
  outbox nor Redis — the alarms that matter most are the ones saying those are broken.
  Recipient is `ALERTS_EMAIL`; a non-local deployment without it warns at boot rather than
  at 3am. Detail and thresholds: OPERATIONS §4.
- **IaC/CI:** Terraform; GitHub Actions (lint, typecheck, tests, migrations, deploy);
  Dependabot + secret scanning + SAST.

## 3. Voice Stack (locked, with verification gates)

Primary engine: **Bolna** (api.bolna.ai, Bearer auth; agent CRUD under /v2 — legacy
unversioned paths are deprecated, never call them; no published OpenAPI spec, so the
adapter's typed models are hand-maintained from docs.bolna.ai + payloads captured
during the pilot; doc index at bolna.ai/docs/llms.txt). Adopted by D-31 (supersedes
D-02's ThinnestAI pick), gated on the pilot scorecard.
Models (per-agent config, BYOK):
- STT: **Sarvam Saaras V3** (22 Indian languages, streaming, code-mixed) — their docs
  supersede our original Saarika v2.5 pick [docs-verified Jul 2026]. Auto-available when
  Sarvam is the speech provider. Gate A-2: compare bundled/managed Sarvam tier.
- LLM: **Sarvam 105B — DEFAULT (D-36)**. Free per token (verified 11 Aug 2026), sovereign
  (all-India residency, no transcript text leaves India), and one vendor for STT+LLM+TTS.
  **Gemini 2.5 Flash-Lite is retained as a configurable fallback** ($0.10/$0.40 per M) and
  remains the reference for the post-call extraction path until Sarvam is measured against
  the golden-transcript fixtures (§7). Availability of either on Bolna is UNVERIFIED (pilot;
  fallback = their listed LLMs or an OpenAI-compatible endpoint if offered). Sarvam's
  **rate limits (60/200/1,000 rpm by plan) are a concurrency input**, not a price input —
  size the plan at pilot gate 13.
  R-04: 2.5 family retires 16 Oct 2026 → migration target 3.x Flash-Lite; LLM id is a
  config string on the agent, changing it is a config edit + regression run. COST NOTE
  [verified Aug 2026]: 3.1 Flash-Lite is $0.25/$1.50 and 3.5 is $0.30/$2.50 — the
  forced migration moves the LLM leg from ~₹0.15–0.20 to ~₹0.55–0.65/min (§10).
- TTS: **Sarvam Bulbul V3** (11 Indian languages) — their docs list only V3; Bulbul v2
  may no longer be offered, which moves the TTS cost line to the v3 band (₹30/10K,
  ~₹1.20–1.35/min) [docs-verified; cost model §10 updated]. Ear-test at verification
  (item 3) is now V3 vs their bundled voices, not a v2/v3 bake-off.
- Telephony: Bolna guides verified for **Exotel (inbound+outbound+connect-your-account),
  Plivo (in+out), Twilio (in+out), Vobiz (connect + outbound only — no inbound guide;
  the inbound-DID plan must confirm Vobiz inbound at pilot or shift inbound DIDs to
  Exotel)** [docs-verified Aug 2026]. DLT-aware (their regulated-numbers runbook: 140
  via Vobiz, 160 via Plivo).
- Embeddings: provider-managed if the D-28 RAG service bundles them; otherwise
  **Cohere Embed v4** (strongest hosted cross-lingual ~0.955), BGE-M3 as fallback.
  Whoever embeds: model name+version recorded per source version (embedding model
  change = full re-index; background job, never a crisis).

No fallback engine is currently designated (ThinnestAI was retired by D-31 before any
adapter existed). Engine risk is carried by the VoiceEngine adapter contract itself:
normalized schemas and the conformance suite (`bolna` + `fake` adapters) keep a future
second adapter cheap to add. D-02's phase-2 self-orchestration trajectory stands
unchanged, on its own triggers (ROADMAP §5).

## 4. Latency Budget (the governing constraint)

Voice-to-voice target: **p50 ≤ 1.1s, p95 ≤ 1.8s** (honest target for a cascade pipeline;
<800ms is aspirational, achieved by masking not magic). Sub-budgets: STT finalization
≤300ms; LLM TTFT ≤350ms (short system prompt — hot facts only, catalog goes to RAG; a
bloated prompt raises TTFT and hallucination together; the ~2.5k budget in
PROMPT-GUIDE §2 stands regardless of engine); TTS TTFA ≤300ms streaming; retrieval ≤100ms (see §6).
Techniques (required): streaming end-to-end; filler utterances fired the moment a tool
call starts ("ఒక్క నిమిషం, చూస్తాను"); brief agent replies enforced in prompt; India-only
network path. **The rule stands and the mechanism does not exist yet**: stage timings per
call (stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_ms) are what any latency work must be argued
from, and nothing records them today. `calls.latency` was DROPPED (migration
`f1a7c39d5be2`): a column that always reads NULL is worse than none, because the next
reader builds a dashboard on it. Every span this repo opens is on OUR side of the call —
the post-call pipeline serving the 2-minute lead SLO — so filling it from those would have
named the engine's 2-3 minute wait for `completed` as a caller-perceived latency.

**Bolna does document per-component latency** (`latency_data` on Get Execution:
`time_to_first_audio` plus transcriber/llm/synthesizer blocks), which supersedes the older
"no per-turn timings" reading — but it is UNVERIFIED against a live account, it is a
DIFFERENT set of numbers from the four above (voice-to-voice turn latency would be our own
arithmetic aligning three components), and its documented `transcriber.turns` entries carry
recognised TEXT, which a naive mapper would land in a column with no redacted counterpart
(hard rules 5/6). So it is captured as a fixture at OPERATIONS §2 gate 4, beside the
stopwatch that can falsify it, and the storage shape is chosen from the payload we actually
receive — no latency work without measurement, and no measurement invented to fill the gap.

### 4a. Where the measured numbers replace the targets (gate 4's landing zone)

**Every number in §4 above is a TARGET and we hold zero measurements.** This block is the
only place a measured number may be written in, and it names the slots so a later reader
can tell at a glance which figures above have been earned. Nothing here is filled in yet.

| §4 figure | status | replaced by | source |
|---|---|---|---|
| voice-to-voice p50 ≤ 1.1s | TARGET — unmeasured | median + its 97.9% order-statistic interval | gate 4 stopwatch/recording, via `scripts/pilot/latency.py` |
| voice-to-voice p95 ≤ 1.8s | TARGET — unmeasured, and **not confirmable at n=10** (see below) | exceedance count + exact binomial bound | same |
| first-greeting delay after pickup | TARGET absent (no figure has ever been set) | its own distribution, kept separate from turn latency | same |
| STT ≤300ms · LLM TTFT ≤350ms · TTS TTFA ≤300ms | TARGETS — unmeasured | `latency_data` transcriber/llm/synthesizer per turn | Get Execution capture, gate 4 |
| retrieval ≤100ms (§6) | TARGET — unmeasured | out of gate 4's scope | TRD §6 bake-off |

Three findings from building the harness, recorded here because they change how the
figures above should be read:

1. **Voice-to-voice latency is not measurable from our side.** Both ends of the interval
   sit on the caller's PSTN leg and our stack is not in the audio path (D-25). It is a
   human with a stopwatch or an offset read off a recording; only `latency_data` is an
   automatic capture, and it is a different quantity. The harness is a ledger and a
   comparator, not a measuring instrument.
2. **Ten calls cannot confirm the p95 leg of gate 4.** "p95 ≤ 1.8s" is "P(turn > 1.8s)
   ≤ 5%"; ten clean samples bound that at 25.9% (exact binomial, 95% one-sided), and
   confirming it needs **n ≥ 59** clean samples. Ten calls CAN refute it (three
   exceedances put the lower bound at 8.7%) and CAN answer the p50 leg. So gate 4 at ten
   calls has three honest outcomes — PASS, FAIL, INCONCLUSIVE — and INCONCLUSIVE is the
   expected one. Raising the gate's sample size is a decision for whoever owns it.
3. **`latency_data` justifies no column until the agreement finding lands.** The storage
   shape it would justify — and the reason a JSONB blob on `calls` is not it — is written
   out in `STORAGE_SHAPE_FINDING` in `scripts/pilot/latency.py`. It stays a finding, not a
   migration, exactly as the paragraph above requires.

## 5. VoiceEngine Adapter (the portability contract)

Nothing outside `engine/` may import a vendor SDK or see a vendor payload shape.

```python
class VoiceEngine(Protocol):
    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef
    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None
    async def start_outbound_call(self, ref, to: E164, ctx: CallContext) -> CallHandle
    async def end_call(self, call_id: str) -> None
    async def transfer(self, call_id: str, to: E164, warm: bool) -> None
    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber
    async def attach_kb(self, ref, source: KBSourceRef) -> EngineKBRef   # the ENGINE's own
        # handle for its copy (Bolna: rag_id). Returning it is the whole reason a
        # superseded version can ever be removed — our kb_sources.id addresses nothing on
        # their side, so an adapter with nothing to return has a KB that can only grow (D-41)
    async def detach_kb(self, ref, kb: EngineKBRef) -> None   # must be REAL: a no-op turns
        # publish into a silent lie. Detaching a handle the engine never issued RAISES
    async def list_kb(self, ref) -> list[EngineKBRef]         # what the agent actually holds —
        # the only adapter-independent way to prove a detach did anything
    async def get_execution(self, call_id: str) -> ExecutionSnapshot   # the authenticated
        # read; THIS, not the webhook, is what we persist
    async def list_executions(self, *, since: datetime) -> list[ExecutionSnapshot]  # backs the
        # reconciliation poller (D-31: guarantee of record, not a safety net)
    def verify_webhook(self, headers, body: bytes, source_ip: str) -> WebhookVerdict
        # per-engine: HMAC where the engine signs, source-IP + dedupe where it does not (§5).
        # A verdict, not a bool, so an UNSIGNED accept is recorded as the hint it is
    def parse_webhook(self, payload: dict) -> CallEvent       # → OUR normalized event
```

Normalized models (ours, stored): CallEvent{call_id, tenant_id, agent_id, direction,
status, started_at, ended_at, from, to, recording_url, cost_raw, engine="bolna",
engine_payload_ref}; TranscriptTurn{call_id, idx, speaker, text, start_ms, end_ms, lang}.
Raw vendor payloads are archived to object storage for debugging but NEVER read by app code.
Adapter conformance test suite runs against the `bolna` and `fake` adapters in CI
(mocked) — the second adapter exists to keep the first one honest.

Bolna integration surface [deep-research-verified Aug 2026 against docs.bolna.ai + the
bolna-ai/bolna OSS repo; items marked (pilot) need live confirmation on the pilot
scorecard — D-31]:

- **Integration model**: the entire voice pipeline runs on their hosted platform; we
  are an API client (CRUD/provisioning), a webhook consumer, and a custom-function
  server (their agent calls our endpoints mid-call; no documented timeout — measure at
  pilot, design async regardless). Bearer auth, base api.bolna.ai; agent CRUD under
  /v2/agent (legacy unversioned paths deprecated); /call and /executions/{id}
  unversioned. No published OpenAPI spec — typed models hand-maintained from docs +
  captured payloads (pilot artifact, committed as evidence).
- **Outbound**: POST /call {agent_id, recipient_phone_number E.164} → execution_id;
  per-call context via `user_data` dynamic variables rendered into the agent prompt —
  OUR CallContext mechanism for lead callbacks; scheduled_at ISO-8601+tz built in.
  Dispatch pacing / API rate limits unpublished (pilot).
- **Execution payload** (polling and webhooks share one shape — GET /executions/{id}):
  15-value status enum; terminal = {completed, no-answer, busy, failed, canceled,
  stopped, error, balance-low}. **total_cost / recording_url / extracted_data populate
  only at `completed` (~2–3 min after disconnect)** — the post-call pipeline triggers
  on `completed`, never on `call-disconnected`. Costs arrive in **USD cents** with
  breakdown {platform, network, llm, synthesizer, transcriber} — the adapter converts
  to INR at capture and stamps the fx rate into usage_events.meta (hard rule 7).
  Transcript is prefix-tagged plain text (`assistant:`/`user:`) — the adapter parses
  it into TranscriptTurn, so `TranscriptTurn.start_ms`/`end_ms` are NULL for every Bolna
  turn and no turn latency is derivable from what we ingest. Their docs DO describe a
  `latency_data` object on Get Execution — unverified against a live account, and a
  pilot gate 4 capture rather than an adapter field (see §4).
- **Webhooks — UNSIGNED, at-most-once** [verified in docs AND the OSS delivery code:
  a single aiohttp POST, no retry, no timeout, errors swallowed]: per-agent
  webhook_url in agent_config; fires on status transitions (scheduled → queued →
  in-progress → completed); pre-call webhooks from tools share the shape. No delivery
  history, no replay tooling. Authenticity = **source-IP allowlist (13.203.39.153)
  enforced at nginx AND in-app**, plus dedupe on execution_id; webhook payloads are
  treated as hints — the authenticated Get Execution fetch is the truth. Consequently
  the **10-min List-Executions reconciliation poller (FLOWS §3) is the guarantee of
  record**, not a safety net. Empirical delivery behavior re-tested at pilot.
- **Recordings**: direct S3 URL (us-east-1), no documented expiry — the recording-copy
  step stays FIRST in the pipeline regardless (our storage is system of record).
  Vendor-side retention + deletion API undocumented (pilot; DPDP erasure — SEC-COMP §4
  — depends on it). Enterprise **India data-residency** option exists (audio,
  transcripts, logs + in-India inference) — required before any BFSI-adjacent client.
- **Multi-tenancy**: Enterprise **sub-accounts** — CRUD + per-sub-account usage APIs,
  auto-provisioned `sa-` API keys (org-admin controlled); isolates agents + call logs;
  phone numbers, providers and billing stay org-level (consolidated). Tenant ↔
  sub-account mapping lives in OUR db (D-16's reasoning unchanged); per-tenant
  metering derives from our usage_events, never their billing.
- **Campaign built-ins** (configure, don't rebuild): batch APIs with per-contact retry
  on outcome (no-answer/busy/failed/error/voicemail, ≤3 attempts, spaced delays) —
  exact API mechanics, pacing and limits unpublished (pilot). Built-in KB: rag_id CRUD
  API (POST /knowledgebase, GET /knowledgebase/all, GET|DELETE /knowledgebase/{rag_id}),
  multiple KBs per agent; multilingual mode
  names Hindi/Tamil — **Telugu KB quality is a pilot gate**. The ROUTES and the fact that
  a KB is addressed by the vendor's `rag_id` are verified from published docs; every
  BODY on this path is a hand-maintained claim (no OpenAPI spec), including the `rag_id`
  field name and the list row shape — the two that decide whether D-41's detach works are
  pilot gate 8 questions: does the list response carry the agent linkage `list_kb`
  filters on, and does deleting a KB clear the agent's reference to it? Custom functions follow
  the OpenAI function-calling schema (bearer/custom-header auth, pre_call_message
  filler line).
- **BYOK key custody — where the keys actually live.** First, a terminology fix: in this
  blueprint **"BYOK" means *we* bring *our* model keys to the *engine*.** Clients never
  hold or supply model keys — we are a managed service (D-10, flat tenancy). Three
  locations, and only three:
  1. **Canonical copy → the secrets manager.** `SARVAM_API_KEY`, `GEMINI_API_KEY`,
     `BOLNA_API_KEY` exist in `.env` for local dev only; prod values are injected at
     runtime from the secrets manager (DEV-SETUP §3). **Never in Postgres plaintext, never
     committed** (hard rule: secrets).
  2. **Operational copy → Bolna's provider configuration.** Unavoidable in a rented-engine
     model: Bolna's pipeline calls Sarvam and the LLM *during* the call, so it must hold a
     usable copy of our keys. **We are therefore trusting Bolna with our model keys** —
     state it plainly rather than discover it later (tracked under R-02 engine vendor risk).
  3. **Our database → a reference only.** Tables store `secret_ref` (the pattern already in
     DATA-MODEL §6 for `inbound_webhooks`), never key material.

  Required controls, because (2) is a real exposure:
  - **Dedicated keys per consumer.** The key handed to Bolna is never the key our workers
    use. One compromised engine ⇒ rotate one key, not the estate.
  - **Caps at the provider, not at the vendor.** Set spend limits and rate limits inside
    the Sarvam and Google consoles — do not rely on Bolna to bound our spend.
  - **Rotation is scheduled, not reactive** (OPERATIONS §6 quarterly secret rotation), and
    the runbook must cover "rotate the key Bolna holds" as its own step.
  - **Blast radius is bounded by design**: these keys buy model inference, nothing more.
    They grant no access to our DB, recordings, or tenant data.
  - Per-tenant model keys are **not** v1. If an enterprise client ever demands its own
    Sarvam account, the encrypted-per-tenant pattern (AES-256-GCM, versioned key) is
    already specified in BACKEND-PATTERNS §9 — build it then, not now.

  Phase-2 note: self-orchestration (D-02) removes location (2) entirely — the keys never
  leave our infrastructure. That is a **security** argument for owning the pipeline that
  sits alongside the ₹0.9–1.5/min cost argument in §10.3, and it should be weighed at the
  phase-2 gate.
- **Not yet verified on Bolna** (all (pilot)): agent draft/publish versioning,
  recording-consent + DNC built-ins, voicemail detection / transfer / DTMF specifics,
  concurrency by plan, KB size limits. Whatever is missing lands in OUR layer
  (workers + compliance gate), never as a reason to bypass hard rule 5.
- **Commercials**: full BYOK leaves a flat per-minute platform fee — **unpublished**;
  negotiation target ₹0.9–1.5/min to hold the §10 all-in budget. Bundled tiers
  6¢ → 4.51¢/min otherwise; Pilots plan = 10k min @ 6¢ + 20% bonus, $5 free signup
  credits, "up to 100 concurrent". INR/GST invoicing undocumented (ask in writing).
  Structurally important (D-32): billing is prepaid credits with **no monthly floor** —
  at launch volume that beats a lower headline rate carrying a fixed floor.
- **Production evidence** [first-party, Aug 2026]: 8 named customers — GoKwik
  (400k+ engagements, **250+ peak concurrent**), Futwork (10k+ calls/day, **250+
  concurrent**), Hypothesis (₹2.5 Cr+ recovered), Hyreo, Awign, plus Varun Beverages/
  Spinny/Snabbit via TechCrunch (~200k calls/day). The independent 250+ concurrent
  datapoints are the strongest evidence that platform concurrency is real.
- **Latency claims are NOT plannable**: their site says "<300ms" with no definition or
  methodology (a third-party comparison inflated this to "sub-600ms end-to-end" —
  unsupported). Our p50 ≤1.1s is established by OUR measurement on real PSTN calls
  (OPERATIONS §2 gate 4), never by a vendor number. Compute region is also unverified
  (recordings observed on S3 us-east-1) — pilot gate 9.

The ThinnestAI integration surface documented in v1.0 of this section was retired by
D-31 (vendor due diligence failed: no verifiable customers, no SLA, unresponsive);
it remains in git history. Its adapter was never built.

## 6. RAG Subsystem (per-client knowledge) — REVISED per D-28

Strategy (D-28 supersedes D-08's self-hosted pgvector plan): per-client knowledge and
call memory live in a **managed RAG/memory service consumed via API** — one shared
layer serving BOTH the engine voice pipeline AND the client CRM (semantic search
over calls/leads, caller memory, and future CRM features). We do not operate vector
infrastructure; provider is selected by the D-28 bake-off gate (below).

### 6.1 Memory horizons (three; do not conflate them with RAG)

Only H3 touches the retrieval layer. H1 is orchestration, H2 is our existing pipeline.

| # | Horizon | Lifetime | Owner / store | Cost | In-call latency |
|---|---|---|---|---|---|
| **H1** | In-call working memory — the running dialogue the agent reasons over | the call only; **discarded at hangup** | the ENGINE's orchestrator (the LLM message array) | no line item — LLM input tokens, already inside the ₹0.15–0.20/min LLM leg | 0ms (nothing is retrieved) |
| **H2** | Call-level durable memory — transcript, AI summary, extraction fields, sentiment, resolved/needs-follow-up | retention policy (90-day recording floor) | OURS — Postgres, written by the post-call pipeline (§8) | Gemini extraction ₹0.02–0.05/call | n/a (post-call) |
| **H3** | Caller / tenant long memory — repeat-caller context, semantic search over calls and leads | forever | managed RAG/memory service (D-28) | provider unit cost | injected **pre-call** via the context webhook (~5s budget), never mid-call |

H1 is not a component we build, buy, or key: the engine holds the conversation for the
duration of the call and drops it at hangup. The hand-off from H1 to H2 is the post-call
pipeline (§8) — **from H2 onward this is entirely mechanisms we already have** (extraction
§7, leads, dashboards), and repeat-caller behaviour is H3 injected at the START of the next
call, not memory persisting across calls. Two consequences:

- **H1 is not free, it is unmetered.** The full conversation is resent to the LLM every
  turn, so input tokens grow through the call: minute 10 costs more than minute 1. The
  ₹0.15–0.20/min LLM figure is a blended average that already assumes this; long calls
  skew above it. Provider-side context caching (Gemini implicit caching) mitigates.
  **UNVERIFIED (pilot gate 8):** whether Bolna truncates or summarises history at a
  window limit, and whether it enables the provider's context caching on BYOK keys.
- **Swapping the KB does not change H1.** H1 is orchestration; the KB choice below is
  retrieval. They are independent decisions.

### 6.2 KB integration choice — built-in vs external (Bolna)

BYOK covers STT/TTS/LLM. **The KB is not a BYOK slot** — there is no way to plug our own
vector store into the engine's retrieval pipeline. The two options are different
architectures, not different keys:

| | Built-in KB (`rag_id`) | External KB (custom function) |
|---|---|---|
| BYOK required | **No** | n/a — it is entirely ours |
| Billing | no KB line on the pricing page → **inferred included in the platform fee; confirm in writing** (gates 8 + 12) | provider unit cost ≈ ₹0.02–0.05/min at our volumes |
| In-call latency | inside their pipeline, zero network hops from the orchestrator | two extra hops (engine → our endpoint → provider, and back): realistically **+150–400ms**, against a 100ms budget and an **undocumented tool-call timeout** |
| Telugu | multilingual mode names Hindi/Tamil, **not Telugu**; mode is immutable at KB creation | ours — no constraint |
| Portability | engine-locked | portable |

**Cost is not the deciding variable** (₹0.02–0.05 against ₹1.75–2.30/min of BYOK model
cost is noise). **Latency is** — which is exactly the D-28 gate below. So v1 keeps in-call
retrieval on the built-in KB, with the T3 filler utterance as the only mask we rely on.
If pilot gate 8 shows Telugu retrieval quality is poor in multilingual mode, the external
custom-function route becomes the fallback and we accept the masked round trip.

Latency doctrine (D-08's physics still binds — it now selects the provider REGION
instead of forbidding external services):
- **In-call retrieval (100ms budget)**: v1 stays on **the engine's built-in knowledge
  base** (zero network hops from their pipeline; Bolna's rag_id KB API is the
  ingestion target — Telugu multilingual-mode quality is a pilot gate, D-31). The
  managed service takes over in-call retrieval ONLY once its measured p95 from the
  engine's region (Bolna hosting region: pilot-measured; Enterprise India-residency
  exists) fits the budget — wired either as an engine custom function calling the
  provider directly, or through a thin endpoint of ours; whichever the bake-off shows
  is faster. Region-matching is the deciding
  factor: nearest serverless regions today are Singapore-class (~35–70ms RTT from
  Mumbai) — tight but plausible; measure, don't assume.
- **CRM/context paths (latency-tolerant)**: the managed service serves these from day
  one — repeat-caller context injection (their webhook's ~5s budget), post-call
  memory writes, CRM semantic features, knowledge-gap analysis.

Tier model (unchanged in intent; T1–T3 now provider-backed):
- **T0 Compiled context (0ms):** hot facts compiled into the system prompt at
  agent-publish time; regenerated on KB change. Answers ~80% with zero retrieval.
- **T1/T2 (cache + speculative):** provider-side or thin-cache tiers, only relevant
  once in-call retrieval moves to the provider.
- **T3 Cold lookup:** hybrid search top_k=3, chunks 200–400 tokens, no in-call
  cross-encoder rerank; filler utterance masks the gap.
- **T4 Refuse-and-escalate:** below threshold → agent says it doesn't know, offers
  callback, call tagged needs_follow_up. Never invents prices/medical/legal facts.

Ingestion (workers, offline — OURS regardless of provider): parse (LlamaParse for
messy PDFs) → chunk preview → **client/admin approve** → push to BOTH targets
(engine KB API for in-call; managed service for CRM/memory) → version
bump → T0 recompilation. The preview-and-approve gate stays ours — a bad upload must
not poison live calls, whichever store serves it. Resolved-call transcripts are
indexed into the managed service as the per-client corpus (compounding, uncopyable).

D-28 bake-off gate (blocks provider commitment; run with M2, before any CRM feature
depends on the provider): candidates in two classes — vector-cloud (Qdrant Cloud,
Pinecone serverless [Singapore], Turbopuffer, Weaviate Cloud) and memory-API (Mem0,
Supermemory, Zep). Score: (a) measured retrieval p50/p95 from Mumbai; (b) hard
per-tenant namespace isolation; (c) hybrid (dense+sparse) search; (d) ingestion API
fit (files/text/URL + versioning); (e) memory semantics (per-caller session/user
memory) if a memory-API class provider; (f) DPDP posture (data residency, deletion
with proof via API); (g) unit cost at our volumes. Record the winner as a decision-log
entry with the scorecard committed to the repo.

## 7. Schema-Driven Extraction (the product core)

Per-agent `extraction_schema`: ordered list of {key, label, type(text|number|bool|enum|
date), enum_values?, description("what to listen for"), required}. Admin UI edits it;
vertical templates (clinic, real_estate, insurance, education) pre-fill it.
One schema drives, with zero code: (a) the post-call extraction prompt (generated),
(b) Pydantic validation of the LLM's structured output (retry on schema failure),
(c) Leads table columns, (d) filters, (e) CSV export, (f) hot-lead rules.
Extraction runs POST-CALL in workers (never in-call): input = full transcript; cost
≈ ₹0.02–0.05/call. Same pass also emits: sentiment, summary, resolved|needs_follow_up tag,
out_of_scope flags, callback intent. Every extraction stores prompt_version + model for
auditability. **Model, as shipped**: `workers/extraction.get_extractor()` picks by config
and there is NO silent failover between providers — Sarvam (`sarvam-m`) when a Sarvam key
is present, Gemini (`gemini-2.5-flash-lite`) when only a Gemini key is, and an offline
heuristic runner otherwise, which is what keeps the regression harness's baseline stable.
D-36 makes Sarvam the default; the §5 note that Gemini "remains the reference for the
post-call extraction path" is about which baseline is measured, not about which model the
pipeline reaches for.

The generated prompt (`packages/shared/.../extraction.build_extraction_prompt`, shared with
the regression harness so the scored prompt IS the shipped one) carries **five named rule
blocks**, each closing an observed extraction failure: **WHO SPOKE DECIDES WHAT IS A
FACT** — the transcript is one labelled turn per line, every field is a fact about the
CALLER, so only `caller:` lines are evidence and an `agent:` question, menu or read-back is
never an answer; **A DENIAL IS NOT A CONFIRMATION** — "ledu"/"vaddu"/"kaadu"/"nahi"/"no"
means refused, which is `false` for a bool field and `null` for every other; **ABSENT MEANS
NULL** — never guess, and never write "N/A"/"unknown"/"none"; **WHOSE IS IT** — a detail
belonging to a relative or colleague is not the caller's own; **VALUES, EXACTLY** — quote
the caller, keep the script and the caller's own relative time, digits in the order spoken
and `null` if one digit is unclear, enum values verbatim and only when meant.

## 8. Post-Call Pipeline (workers; idempotent; keyed by call_id)

webhook(execution status) → **authenticate per §5** (Bolna is unsigned: source-IP
allowlist + execution-id dedupe, payload treated as a HINT; HMAC only where an engine
signs) → authenticated Get Execution is the TRUTH → persist CallEvent + turns → enqueue:
1. fetch/persist recording to our storage (presigned; engine copy is not our system of record)
2. PII redaction pass on transcript (Aadhaar/PAN/card/OTP patterns + LLM assist) →
   redacted transcript is the default view; raw restricted by role
3. extraction (per §7) → upsert Lead
4. usage metering → usage_events rows (see §9)
5. notifications: hot-lead rules → client email/WhatsApp
6. campaign-contact resolution (close or re-queue on the FLOWS §5 retry ladder)
7. outbound CRM sync (`call.completed` through the outbox, D-23) — summary, never transcript
*Planned, NOT in the shipped pipeline:* embeddings for resolved calls (KB corpus) — M3
per ROADMAP; `apps/workers/pipeline.py` ends at step 7.
Retry budget is **3 attempts** — `WORKER_MAX_TRIES` in `apps/api/core/queue.py`,
the one number the ARQ worker and the delivery worker's exhaustion check both read.
Outbound deliveries back off **30s then 120s**; a failed recording copy waits 30s.
Only transport failures, 5xx, 408, 425 and 429 are retried; any other 4xx stops on the
first attempt as `rejected {code}`. A worker earns a retry only by raising `arq.Retry`
— a plain `raise` is terminal on the first attempt under arq 0.28.
DLQ on repeated failure; pipeline lag is a monitored SLO
(target: lead visible < 2 min after hangup). ⚠ Under arq 0.28 a plain `raise` is
terminal on the first attempt, so a worker earns the ladder above only by raising
`arq.Retry`. Full note and the incident it caused:
FLOWS §6.

## 9. Metering & Billing

Append-only `usage_events` (tenant_id, call_id, unit_type[telephony_s|stt_s|tts_chars|
llm_tok_in|llm_tok_out|platform_min], qty, unit_cost_paid, occurred_at) — records OUR cost
next to billable qty; per-client margin is a query, and phase-2/3 build-vs-rent decisions
use months of real data. Plans are config rows {setup_fee, monthly_fee, included_min,
overage_rate, hard_cap_min, hard_cap_spend}; invoices derive from ledger + plan. Prepaid
credit balance; **caps enforced pre-dispatch in the compliance gate**
(`apps/api/compliance/service.py::check_dispatch` — the one function every outbound path
calls: campaign dispatch, "call this lead", instant lead callback). A capped tenant's
outbound is refused (`spend_state.capped`); a self-serve/trial tenant with an empty
wallet is refused too (D-34 credits). **Inbound is unaffected and never reaches this
gate** — the caller initiated it, which is D-38's consent-clean property — so there is no
inbound fallback line, and voice-runtime carries no cap logic (hard rule 3 keeps it thin).
Razorpay for collection (phase 1 can invoice manually; ledger from day 1 is non-negotiable).

## 10. Cost Model (verified July 2026; re-verify quarterly)

Per-minute variable (₹): platform 1.5–2.0 (A-1) · STT 0.50 · LLM 0.04–0.10 · TTS
1.20–1.35 (Bulbul V3 — the v2 ₹0.60 band is likely gone; their docs list only V3
[Jul 2026]; confirm pricing on account) · telephony 0.40–0.90 inbound / 0.60–1.80
outbound. **Blended all-in ≈ 3.3–3.6 (launch) → 1.7–2.3 (phase 2)** — the low end of
the old 3.0 blend assumed v2 TTS. Actual per-call cost comes from Get Call's
cost.breakdown (platform_fee/stt/tts/llm/telephony, INR) recorded into usage_events.
Fixed monthly: DO stack ~$75–125 (web/api droplet, worker droplet, managed PG, Redis,
storage) ≈ ₹7–10k; platform/model minimums + numbers ≈ ₹3k.

**Normalized platform comparison (D-32 method: BYOK legs removed, since they are
identical on every platform).** The BYOK stack is a CONSTANT — STT ₹0.50 + TTS
₹1.10–1.60 + LLM ₹0.15–0.20 = **₹1.75–2.30/min everywhere** (→ ₹2.15–2.75 after the
forced Gemini-3.x migration, R-04; → ₹1.60–2.10 if Sarvam's LLM is genuinely free).
Telephony (~₹0.35–0.50) is likewise constant. Only the platform fee and latency differ:

| Platform | Platform fee (BYOK; excludes STT/TTS/LLM) | Latency posture |
|---|---|---|
| **Bolna** (primary, D-31) | **unpublished** — pilot gate 12; bundled ₹5.52→₹4.15; rumoured ~₹1.8 (unverified); target ≤₹1.5. **No monthly floor** (prepaid credits) | undefined "<300ms" marketing claim; compute region UNVERIFIED (recordings on S3 us-east-1) |
| LiveKit Cloud (phase-2 candidate) | marginal ₹1.23 (agent + third-party SIP, two meters) but **$50/mo Ship floor dominates**: ₹4.40/min @1k min, ₹0.88/min @5k min; concurrency capped 5/20/600 | ✅ ap-south (Mumbai) VERIFIED — best-evidenced |
| Pipecat Cloud (phase-2 candidate) | ~₹0.88 claimed — **entirely unverified** | regions unverified |
| Self-host (DO BLR / Vultr Mumbai) | ₹2.1/min @1k, ₹0.85–1.2/min @5k (₹2,112/node ≈ 8–9 concurrent) | best possible physics (co-located), unmeasured |
| ~~Cartesia **Line**~~ | ₹5.28/min ($0.06/min agent, verified) — but this is a **bundled** rate that appears to include their own models, so it is **not** comparable to Vapi's orchestration-only tax below. It sits level with Bolna's *bundled* 6.00¢. Eliminated because **BYOK support is unverified** (Line docs auth-gated) and Telugu depends on bringing Sarvam; plus monthly tiers to $299, agent concurrency 1/3/5/10 slots, and no India telephony/DLT story | India region **unverified** (docs auth-gated) |
| ~~Vapi~~ | ~~₹4.40/min~~ — survives full BYOK; exceeds the entire all-in target alone | ❌ US/EU only: +230–260ms hairpin |

Two rules this table encodes (D-32): at launch volume **monthly floors dominate
per-minute rates**, and **no latency figure here is measured** — all of it ranks by
region physics until the pilot produces real PSTN numbers (gate 4).

**A third rule, learned the hard way while building this table — compare like with like.**
Vendors price at two different layers and the same-looking number means different things:

| Layer | What you buy | Representative price |
|---|---|---|
| **Model** (STT/TTS/LLM) | one leg of the pipeline | Cartesia Sonic TTS ≈ ₹2.7–3.0 / 1k chars ≈ **₹1.0–1.6 per call-min**; Sarvam Bulbul v3 ₹3.00 / 1k chars |
| **Orchestration, bundled** | the whole call, vendor's models included | Cartesia Line $0.06/min · Bolna bundled 6.00¢/min |
| **Orchestration, BYOK** | the whole call, *our* models | Bolna BYOK (target ≤₹1.50) · Vapi $0.05/min **on top of** your model spend |
| **Self-orchestrated** | nothing — you built it | ₹0 fee + ~₹0.20/min compute |

Reading a model price against a platform price (or a bundled fee against a BYOK fee)
produces a ~4× error. **Outpero is the worked example:** they buy Cartesia at the *model*
layer (~₹1.0–1.6/call-min for TTS) and pay **nothing** at the orchestration layer because
they built it. That is why they can retail at ₹3/₹5/₹7 — not because they found a cheap
platform, but because they skipped the platform entirely. Anyone assuming they pay Line's
₹5.28/min has stacked two layers that never both apply.

### 10.1 Stack cost, computed from published rates (Aug 2026)

Every figure below is derived from a first-party rate card; the derivation is shown so it
can be re-checked when a rate moves. **Assumption used throughout:** the agent speaks
40–60% of a call, at ~900 characters/minute of actual speech → **360–540 TTS characters per
call-minute**. That ratio is itself unmeasured — it is the single biggest lever on the TTS
line and is a pilot measurement (gate 12).

**Sarvam rate card, read live from `sarvam.ai/api-pricing` on 11 Aug 2026** (this supersedes
the July figures and corrects two of our own doc errors — see the two ⚠ notes below):

| Sarvam API | Published rate |
|---|---|
| **Sarvam 105B / 30B (chat LLM)** | ⚠ **Free per token** |
| Text-to-Speech **Bulbul v3** | ₹30 / 10,000 chars |
| Text-to-Speech **Bulbul v2** | ⚠ **₹15 / 10,000 chars — still live, not discontinued** |
| Speech-to-Text | ₹30 / hour |
| Speech-to-Text **and Translate** (Saaras) | ₹30 / hour |
| STT with diarization | ₹45 / hour |
Plans: pay-as-you-go with **no minimum**; ₹1,000 free credits; credits never expire and are
universal across APIs. **Rate limits are the real constraint, not price** — 60 rpm (Starter) /
200 rpm (Pro ₹10k) / 1,000 rpm (Business ₹50k).

> ⚠ **Corrects D-20**, which recorded Bulbul v2 as "appears discontinued." It is live at
> **half** the v3 rate. ⚠ **Corrects R-04's premise** — Sarvam's LLM is genuinely free per
> token, so the forced Gemini-3.x migration is now *avoidable*, not an inevitable cost step.

**Cost per call-minute.** Assumption doing the most work: the agent speaks 40–60% of a call at
~900 characters/minute of speech → **360–540 TTS characters per call-minute**. That ratio is
unmeasured and is the single biggest lever on the TTS line (pilot gate 12).

| Leg | Rate | Per call-minute |
|---|---|---|
| STT — Saaras (STT+Translate) | ₹30/hr | **₹0.50** |
| TTS — Bulbul **v3** | ₹3.00 / 1,000 chars | **₹1.08–1.62** |
| TTS — Bulbul **v2** | ₹1.50 / 1,000 chars | **₹0.54–0.81** |
| LLM — **Sarvam 105B** | free per token | **₹0.00** |
| LLM — Gemini 2.5 Flash-Lite | $0.10/$0.40 per 1M tok | ₹0.15–0.20 |

**BYOK model subtotal, by combination** (identical on every platform — not a decision
variable, D-32):

| Combination | Per call-minute |
|---|---|
| Bulbul v3 + Gemini | ₹1.73–2.32 |
| Bulbul v3 + Sarvam LLM | ₹1.58–2.12 |
| Bulbul v2 + Gemini | ₹1.19–1.51 |
| **Bulbul v2 + Sarvam LLM** (cheapest verified) | **₹1.04–1.31** |

| Remaining legs | Per call-minute | Status |
|---|---|---|
| Telephony (Exotel/Vobiz class) | ₹0.35–0.50 *(estimate)* | **UNVERIFIED** |
| Engine platform fee (Bolna BYOK) | target ≤₹1.50 | **UNVERIFIED — pilot gate 12** |
| **All-in, rented engine** | **₹1.89–4.32** | v2+Sarvam-LLM floor → v3+Gemini ceiling |

The quality/cost trade is now explicit and ours to choose per tier: **v2+Sarvam LLM is
~45% cheaper per minute than v3+Gemini.** Bulbul v3 vs v2 Telugu quality is an **ear test at
the pilot**, not a spec decision — and it is exactly the lever that lets us build a
value/premium ladder (see §10.3).

**Self-orchestrated comparison (phase 2).** Same BYOK subtotal + telephony, no platform
fee, plus ~₹0.15–0.30/min compute (2 vCPU/4 GB node ≈ ₹2,112/mo, ~8–9 concurrent):
**≈ ₹2.23–3.12/min**. The delta is therefore **≈ ₹0.9–1.5/min**, which is simply the
platform fee — consistent with the ~2k min/month break-even already stated above.

### 10.3 Reconstructing Outpero's economics (why their ₹3/₹5/₹7 tiers work)

With the verified Sarvam rate card, their pricing reconciles cleanly — and the reconstruction
is instructive because **they buy the same inputs we do.** Confidence is marked per line.

**★ Their voice tiers are TTS-VENDOR tiers — read directly out of their shipped JS bundle
(`app.outpero.com/assets/*`, 11 Aug 2026), not inferred:**

```
value:    rates.sarvam_per_min      →  ₹3/min
standard: rates.smallest_per_min    →  ₹5/min
premium:  rates.cartesia_per_min    →  ₹7/min
```
The same `rates` object also carries `ai_per_use` (their AI-generation charge), and voices
carry a `provider` field plus `voice_id`. **This is verified evidence, and it corrects an
earlier assumption in this document:** the ₹7 "exclusive Outpero native Telugu speakers"
tier is **Cartesia**, not a premium Sarvam voice — and **Sarvam is their cheapest tier.**
A third vendor appears that we had not tracked: **Smallest.ai** (Indian TTS) at the ₹5 tier.
*(Smallest's public rate reads ~$0.09/min of generated audio, which is too vague and too high
to reconcile — do not build on it without direct verification.)*

| Input | Value | Confidence |
|---|---|---|
| STT (Sarvam) | ₹0.50/min | **verified rate** |
| LLM (Sarvam 105B) | ₹0.00 — free per token | **verified rate** |
| TTS by tier | Sarvam → Smallest → Cartesia | **verified from their code** |
| Telephony (India mobile) | ₹0.35–0.50/min | estimate |
| Orchestration | **unknown** | ⚠ **NOT ESTABLISHED — see below** |

> ⚠ **Correction — do not repeat the earlier claim that Outpero self-orchestrates.** That was
> an inference from their security page ("the voice engine", private-network agent API) and
> their mid-call cross-provider failover, and it was stated far more confidently than the
> evidence supports. **Evidence now points the other way, or at least muddies it:
> Sarvam, Smallest and Cartesia are all three on Bolna's published supported-TTS list**
> (TRD §5: ElevenLabs, Polly, Azure, Cartesia, Deepgram, Maya, Rime, Sarvam, Smallest).
> A vendor trio that exactly matches a rented orchestrator's provider menu is at least as
> consistent with *being a customer of one* as with building their own. Their footer
> ("BACKED BY Sarvam · Cartesia **| Startups**") likewise indicates vendor programmes, which
> cuts against the "they pay nothing upstream" reading.
>
> **The client bundle cannot settle this** — calls run over PSTN, never through the browser,
> so no orchestration vendor would appear there (and indeed no LiveKit/Twilio/Daily/Agora/
> WebRTC strings do; the only media code is `getUserMedia`/`MediaRecorder` for the in-browser
> "Talk" and voice-input features). **Treat their orchestration layer as UNKNOWN** until we
> have direct evidence, and do not build any cost or strategy conclusion on top of it.

**What survives as verified and useful:**

1. **The tier ladder is a vendor ladder, and we can build the same one.** Pricing a
   value/standard/premium tier off *which TTS vendor serves the call* is a clean, provable
   model — and every vendor they use is available to us at published rates (and all three are
   selectable on Bolna). Our own ladder can run **Bulbul v2 → Bulbul v3 → Cartesia**, chosen
   by measured Telugu quality rather than by their ordering.
2. **Sarvam is their *cheap* tier, which is a positioning fact worth knowing.** They sell
   Cartesia as the premium "native Telugu" experience. Whether Cartesia actually beats
   Bulbul v3 on Telugu is an **ear test we should run** — if it does not, their premium tier
   is a pricing story rather than a quality one, and that is directly usable in a sales
   conversation. If it does, we should adopt Cartesia for our own premium tier.
3. **What their economics prove is nothing about orchestration** — only that a competitor
   retails Sarvam-served calls at ₹3/min. Since our Sarvam-served cost is ₹1.04–1.31/min in
   models plus telephony, **₹3/min retail is reachable for us too whenever the platform fee
   allows it.** That is the number to hold them to, and the one the Bolna BYOK fee decides.

### 10.2 Effective cost per minute WITH fixed monthly costs amortized

The ₹2.98–4.32 above is **variable cost only**. It is not what a minute actually costs us
until the fixed base is carried. Applying the D-32 floor rule to ourselves (we applied it to
LiveKit and to Outpero; it binds here too):

**Fixed monthly base ≈ ₹10–13k** — infra ₹7–10k + platform/model minimums and numbers ≈ ₹3k.
*(This range predates D-25/D-26, which moved us to a general-purpose VPS with self-hosted
Postgres; the true figure is likely lower — re-measure at deploy.)*

Crucially this base is **shared across all tenants**, so the divisor is **total platform
minutes**, not one client's usage:

| Total platform min/month | Fixed share | + variable | **Effective ₹/min** |
|---|---|---|---|
| 1,000 (client #1 only) | ₹10.0–13.0 | ₹2.98–4.32 | **₹13.0–17.3** |
| 2,500 | ₹4.0–5.2 | ₹2.98–4.32 | **₹7.0–9.5** |
| 5,000 | ₹2.0–2.6 | ₹2.98–4.32 | **₹5.0–6.9** |
| 10,000 | ₹1.0–1.3 | ₹2.98–4.32 | **₹4.0–5.6** |
| 20,000 | ₹0.5–0.65 | ₹2.98–4.32 | **₹3.5–5.0** |

**Three consequences, and the first one is uncomfortable:**

1. **D-11 prices overage at ₹6–8/min, which is below our true cost until roughly 5,000 total
   platform minutes/month.** At client #1 alone we are underwater on any minute sold at the
   overage rate. This is not an argument to raise the overage price — it is the reason D-11 is
   deliberately **not** pure per-minute: the **setup fee funds the build and the retainer
   carries the fixed base** while volume is too low to amortize it. D-11's structure is
   *validated* by this table, not threatened by it. What the table does forbid is ever
   discounting to a pure per-minute deal before ~5k min/month.
2. **Our unit economics are a volume story, not a rate story.** Nothing about the model works
   at one client and everything works at five. That makes client #2–5 an economic
   requirement, not just growth.
3. **This is precisely the structure Outpero already uses, at a different price point.** Their
   **₹1,899/employee/month recovers fixed cost per seat**, which lets their per-minute rate sit
   close to variable cost (₹3/₹5/₹7). Their effective rate therefore behaves exactly like ours:
   **₹19/min at 100 min/month, ₹7.8 at 500, ₹6.4 at 1,000, ₹5.3 at 5,000** — i.e. their "from
   ₹3.5/min" headline is a high-volume asymptote, and at realistic SMB volume they are in the
   same ₹5–8/min band our D-11 overage occupies. The difference is packaging, not physics: they
   recover the base per-seat and advertise the variable; we recover it in a retainer and
   advertise the bundle. **Any competitive comparison must be made on effective ₹/min at a
   stated monthly volume, never on headline rates.**

**What the Aug-2026 Outpero teardown adds to this model** (evidence:
`docs/evidence/outpero-teardown-aug2026.md`): a direct competitor in our exact segment
retails at **₹3/₹5/₹7 per minute by voice tier**, which is at or below our *cost* on a
rented engine. They achieve it by **self-orchestrating** (their own voice engine — proven
by their mid-call cross-provider failover, which is impossible without owning the pipeline)
and by running on **Sarvam + Cartesia startup-programme credits** — a subsidy, not a durable
cost structure. Two corrections this forces on how we read their price: their per-minute
figures **exclude their own ₹1,899/employee/month fee** (effective cost is ₹19/min at 100
min/month, ₹6.4 at 1,000, ₹5.3 at 5,000 — the D-32 floor rule again), and their **"native
Telugu" voices are the ₹7 Premium tier**, so the ₹3.5 headline and the Telugu claim are
mutually exclusive.

**Conclusion for M1 (no change to D-31):** rent Bolna. The platform fee buys 4–8 engineering
weeks we do not have before client #1, and time-to-revenue dominates a ₹0.9–1.5/min saving
at launch volume. **What changes is phase-2 urgency**: the competitive floor is now set by a
self-orchestrating incumbent, so the phase-2 trigger should be reviewed against real client
volume rather than treated as distant.

**Single-vendor concentration risk (new, act on this).** We currently take *both* STT and
TTS from Sarvam. Outpero deliberately runs two model vendors and fails over between them
mid-call. Add **Cartesia Sonic as a second TTS candidate** to the pilot: Telugu (`te`) is
supported (verified in their TTS API docs, 42 languages), and at the Scale tier
($299/mo ≈ 10,667 TTS-minutes → ~$0.028/TTS-min → **≈ ₹1.0–1.5 per call-minute** at our
40–60% ratio) it is broadly cost-comparable to Bulbul V3 while removing a single point of
failure and hedging Bulbul V3's unpinned beta price. Caveats to verify: Cartesia plans are
**credit pools** (the per-product minute figures assume the whole pool goes to that product,
so TTS and STT allowances are not simultaneously available), concurrency is tier-capped
(TTS 2–15), and **Telugu voice quality is an ear test, not a docs claim**.
Phase triggers (numeric, pre-committed):
- **Phase 2 (own orchestration, Pipecat on CPU droplet — models stay APIs):** when
  sustained volume > ~10–15k min/month OR a feature needs pipeline control (T1/T2 RAG
  tiers, custom turn-taking). Break-even vs ₹1.5–2/min fee is ~2k min/month; the real cost
  is engineering the barge-in/turn-taking 20%, hence the volume gate.
- **Phase 3 (self-host models on GPU):** sustained > ~50k min/month AND Telugu-quality
  open TTS exists. Below that, a 24/7 GPU at ~$0.72–0.79/hr loses to APIs on utilization.

## 11. Multi-Tenancy & Security (engineering-level; full detail in SECURITY-COMPLIANCE.md)

Flat tenancy (no reseller tree — decided): Organization → Users(role: owner|staff) →
Agents → Calls/Leads/KB. tenant_id on every row; **Postgres RLS on every tenant table**
(policy: tenant_id = current_setting('app.tenant_id')); the API sets the GUC per request
from the verified session; a missing GUC yields zero rows, never all rows.
Admin realm (admin.calevate.tech) and client realm (app.calevate.tech/c/<slug>/…) are
separate Clerk applications, separate cookies, separate deploys. Slugs are auto-generated,
immutable, reserved-word-filtered. Client credentials/engine keys in a secrets manager,
never in DB plaintext; recordings envelope-encrypted per tenant; append-only audit_log
(who viewed which recording/lead, when); staging vs live agent config with promote action
(engine versioning idiom where available — Bolna equivalent unverified (pilot);
otherwise implemented in our layer via engine_staging_ref).

## 12. Non-Functional Requirements

Availability: 99.5% for voice-runtime webhooks (v1). Recovery: PG PITR + nightly
snapshots; storage versioning; RTO 4h / RPO 15min. Load: 20 concurrent calls v1 headroom
(engine handles media; our webhook path must be O(ms)). All external calls have timeouts +
circuit breakers; webhook handlers ack fast and defer to workers. Everything (including
DLT template text and system prompts) lives in git.
