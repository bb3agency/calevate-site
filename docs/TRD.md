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
  Tremor. Typed API client generated from FastAPI OpenAPI. (Bolna DOES publish an
  OpenAPI spec — this line said otherwise for the repository's whole life, D-350. It is
  `references/openapi.yml` in `bolna-ai/skills`, their own GitHub org, pinned and
  checksummed in `docs/vendor/bolna/hosted-oas.md`; the adapter's models are now read
  from it rather than hand-maintained, §5.)
- **DB:** Postgres 16 for all system-of-record data. Vector/RAG: a managed RAG/memory
  service via API (D-28 — supersedes the earlier in-Postgres pgvector plan and the "no
  external vector DB" rule; D-08's RTT physics now governs provider REGION choice and
  keeps v1 in-call retrieval on the engine's built-in KB — TRD §6).
- **Queue:** Redis + ARQ. Promote only campaign orchestration to Temporal if/when retry
  semantics outgrow ARQ. Not before.
- **Auth: OURS, end to end. There is no identity vendor.** This bullet named Clerk for most
  of the repository's life; D-165 designed the replacement, D-170 mounted it and **D-177
  deleted the vendor from the tree** — settings, routes, dependency and code. `apps/api/authn/`
  is the only thing that mints a credential, and the credential is an opaque token in an
  `HttpOnly` `__Host-` cookie (`authn/cookies.COOKIE_NAMES`:
  `__Host-calevate_admin_session`, `__Host-calevate_client_session`). Full design and the
  26-endpoint surface: `docs/AUTH-MIGRATION.md` (§3 the realm boundary, §10.5 the routes,
  §11 what is still not built).
  - **Two realms, four independent separations**, because a `realm` column queries must
    remember to filter on is one forgotten `WHERE` from being nothing: the realm is inside
    the stored session hash (`sessions.token_fingerprint(token, realm)`, so a client token
    looked up as admin matches no row), the `realm` column is in the `WHERE` clause anyway,
    the two cookie NAMES differ, and `Origin` is enforced per realm because `admin.` and
    `app.` are same-site and `SameSite` therefore does not separate them.
  - **MFA mandatory on the admin realm, enforced by the API**: `core/auth.py::verify_token`
    refuses any admin principal whose session has a NULL `auth_sessions.mfa_verified_at`.
    The gate is in the verifier, not on the routes, so there is no admin identity that
    skipped it; the client realm is unaffected. `authn/service.MFA_REQUIRED_REALMS` is a
    frozen `{"admin"}` with no setting behind it — **there is nothing to switch on and
    nothing that can switch it off**, which is why OPERATIONS §8's old two-step operator
    task is retired rather than restated. One refusal code,
    `401 second_factor_required`; the Clerk-era pair (`mfa_required` /
    `mfa_claim_missing`) collapsed into it because a NULL column, unlike a droppable JWT
    claim, has no "we cannot tell" state.
  - **The second factor is a six-digit code emailed to the address on file** — no
    authenticator app, no shared secret, no recovery codes (D-170; the trade is in
    AUTH-MIGRATION §2.3 and §7). Passwords are Argon2id with a KEK-derived pepper.
  - **Session lifetimes are enforced on the ROW, per realm** (`authn/sessions.REALM_TIMEOUTS`):
    admin 30 min idle / 8 h absolute, client 12 h idle / 14 d absolute. The cookie carries
    no `max_age` — the row is the authority, so a revoke bites immediately.
- **Storage:** R2/Spaces, SSE encryption, presigned URLs (5 min for everything except a
  call recording, whose link is sized to the recording per D-153 and capped at
  `RECORDING_LINK_CEILING_S` — the widest credential window this platform opens, so it
  is named rather than averaged away), never public.
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
unversioned paths are deprecated, never call them; the adapter's typed models are read
from the vendor's OWN published OpenAPI 3.1 document — `references/openapi.yml` in
`bolna-ai/skills`, pinned and checksummed in `docs/vendor/bolna/hosted-oas.md` — and no
longer hand-maintained from prose, D-350). Adopted by D-31 (supersedes
D-02's ThinnestAI pick), gated on the pilot scorecard.
Models (per-agent config, BYOK):
- STT: **Sarvam Saaras V3** (22 Indian languages, streaming, code-mixed) — their docs
  supersede our original Saarika v2.5 pick [docs-verified Jul 2026]. Auto-available when
  Sarvam is the speech provider. Gate A-2: compare bundled/managed Sarvam tier.
- LLM: **Azure OpenAI in South India — `AZURE_LOCATION` (`southindia`), default
  `AZURE_OPENAI_DEFAULT_MODEL` (`gpt-4o-mini`) — on BOTH LLM surfaces (D-410,
  superseding D-400/D-404 on the in-call leg and D-127 on the dashboard leg).** One
  region, one allow-list, one price table, one builder. `gpt-4.1-mini` is a CONFIG SWITCH
  through `azure_openai_model`, not a second shipped default, because its availability in
  Indian regions is not confirmed while `gpt-4o-mini`'s in South India is.

  ⚠ **"SWITCH" IS TWO EDITS AND A REPUBLISH, NOT ONE TOGGLE, AND GETTING THAT WRONG IS
  SILENT.** Of the four Azure settings only `azure_openai_model` is `applies: live`, and it
  is live precisely because **nothing sends it to anybody** — it names which model the
  deployment was made from, and `billing/` reads it to price the leg.
  `azure_openai_resource` and `azure_openai_deployment` are **`needs_republish`**: they
  become `ModelConfig.llm_base_url` and `ModelConfig.llm_model` inside each PUBLISHED agent
  record, so a live agent keeps calling what it was published against no matter how often
  the console is edited. `azure_openai_api_key` is `needs_republish` too — the dashboard leg
  re-reads it per request, but the in-call copy sits in the engine's credential store until
  `VoiceEngine.set_llm_credential` re-installs it. **So flipping the model alone changes the
  INVOICE and not a single call**: every agent goes on running `gpt-4o-mini` while every
  usage event is priced at 2.67x. That is a wrong invoice rather than an outage, which is
  why it hides longest. Move `azure_openai_deployment` to a deployment that actually runs
  the new model, move `azure_openai_model` with it, and republish the agents.
  `apps/api/core/platform_config.py` carries each answer beside its reason and
  `scripts/check_config_applies.py` binds it to the reader that justifies it.
  Read the three surfaces separately, because one of them deliberately did not move:
  - **In-call** (inside the engine, BYOK). The engine calls our Azure deployment directly
    on `azure_openai_base_url(resource)` — `https://{resource}.openai.azure.com/openai/v1`
    — with **a static API key** in `Authorization: Bearer`. That is the **v1 surface**:
    OpenAI-compatible, and it needs no `api-version`. **The classic surface is rejected**
    (`…/deployments/<id>/chat/completions?api-version=YYYY-MM-DD` with an `api-key:`
    header): the dated `api-version` is a second thing to keep current and the header is
    not what an OpenAI-shaped client sends. **`azure_openai_deployment` is a separate
    setting from `azure_openai_model`** because on Azure a deployment id is NOT a model
    name — you deploy a model under an id you choose and call THAT id — so it is config
    and can never be derived. `engine/bolna.py::_llm_routing` maps our vocabulary to
    `provider: "azure"`, a **first-class Bolna provider**: it is on their published
    provider list, `azure` is in the live per-agent LLM dropdown, and their OSS
    `LLMProvider` carries both `azure` and `azure-openai`. So the `custom` route — whose
    credential path was never verified, and whose doubt is what moved this product
    (retired gate 16c) — is not used. **There is no rotation cron, no dead man, no org
    policy and no 12-hour ceiling**: all of that existed because a regional Vertex
    endpoint took no static key, and it is deleted with the endpoint.
    ⚠ ONE MARKED ASSUMPTION REMAINS: which credential FIELDS Bolna's Azure provider
    expects. Their docs are egress-blocked from this environment, so nothing here invents
    a field name. `Settings.bolna_llm_credential_name` (default `AZURE`, `applies: live`)
    names the credential-store entry, so a wrong guess is a console edit rather than a
    deploy — OPERATIONS §2 gate 16f.
  - **Dashboard AI** (user-triggered, over the REDACTED copy) — same resource, same
    region, same constants. Every rule D-127 wrote (G-1..G-7: redaction before the call,
    no raw PII, the disclosed Sarvam fallback) is unchanged and now binds Azure.
  - **First post-call extraction** — **`GEMINI_EXTRACTION_DEFAULT is False` (D-127 G-7):
    Sarvam runs it permanently**, because that pass reads the RAW transcript and G-2
    forbids raw PII reaching a general-purpose model vendor. D-410 does not move it.

  At $0.15 in / $0.60 out per 1M tokens for `gpt-4o-mini` and $0.40 / $1.60 for
  `gpt-4.1-mini` (Global Standard list) — cheaper than the outgoing `gemini-2.5-flash`
  ($0.30 / $2.50) on both legs and **half the input price**, which is where the saving
  lands because §6.1 resends the whole conversation every turn. `AZURE_LIST_PRICE_USD_PER_MTOK`
  states those once, in the vendor's unit, and the whole INR chain derives from it (§10.1).
  **THE RESIDENCY CLAIM IS NARROWER THAN VERTEX'S AND THIS DOCUMENT SAYS SO.** Vertex put
  `asia-south1` in the hostname AND the `locations/` path, so `scripts/check_model_residency.py`
  could prove residency from the AST. `<resource>.openai.azure.com` names no region: the
  region is a property of the RESOURCE. The guard changes job rather than being deleted
  and still proves four things — `AZURE_LOCATION` is the only spelling of the region in
  shipped code, no `Settings` field may carry a region, no Azure endpoint is constructible
  except through `azure_openai_base_url()`, and that builder cannot emit a non-India
  region. The rest is **attested by a human**: that the resource is in South India
  (OPERATIONS §2 gate 20) and that its deployment is **Regional Standard and NOT Global**
  (gate 20c). Global is Azure's DEFAULT deployment type and processes worldwide; a Global
  deployment inside a South India resource passes every automated check in this tree and
  breaks the DPA. Regional costs roughly 5–10% more (published examples to +12% and +20%),
  which is a payable cost of the posture rather than an accident. The REGIONAL hostname
  form `southindia.api.cognitive.microsoft.com` would restore the AST proof and is
  rejected FOR NOW because the v1 surface is documented only on the custom-subdomain form
  — gate 20d is what reopens it. **What is NOT claimed**: which model extracts or converses
  BETTER in Telugu code-mixed function-calling is still unmeasured and still blocked on a
  Sarvam key and egress (§7's golden-transcript fixtures); D-410 is a residency, delivery
  and billing decision and does not claim a quality one. **NO VENDOR RETIREMENT DATE IS
  RUNNING AGAINST THIS PRODUCT** — BRD R-04's 16 Oct 2026 died with the Gemini model, the
  date-carrying constant and the test that turned CI red thirty days out (D-410). Sarvam's
  **rate limits (60/200/1,000 rpm by plan) are a concurrency input**, not a price input,
  and Azure's TPM/RPM quota in `southindia` is a fourth such input — size both at pilot
  gates 13 and 20b. LLM id is a config string on the agent, so changing it is a config
  edit plus a regression run.
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
    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot   # the read half,
        # without which update_agent is a write into the dark (D-64). Carries the prompt
        # as TEXT plus `*_readable` verdicts, so "the field was absent" and "the value is
        # empty" stay different answers. An unknown ref RAISES — a snapshot for an agent
        # nobody created is a conclusion drawn from nothing that looks like a measurement
    async def delete_agent(self, ref: EngineAgentRef) -> None   # the compensation half,
        # without which an orphan is detectable and un-fixable (D-123). IDEMPOTENT BY
        # CONTRACT: the caller is a compensation path, i.e. the one most likely to be
        # retried, so a ref the engine does not hold is the postcondition already
        # satisfied — raising there DLQs a job whose work is done (RFC 9110 §9.2.2 says
        # the same of DELETE). Deliberately NOT symmetric with detach_kb, which raises
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
        # read; THIS, not the webhook, is what we persist. It must also carry the vendor's
        # OWN document as `raw_document: bytes` — the archive below has no other source,
        # and bytes rather than a dict because a dict would hand a worker the vendor's
        # field names, which is the leak an import contract cannot see (hard rule 2)
    async def list_executions(self, *, since: datetime) -> ExecutionListing  # backs the
        # reconciliation poller (D-31: guarantee of record, not a safety net). Returns the
        # snapshots AND whether they are all of them: a bare list cannot distinguish "a
        # quiet window" from "page one of nine", and the executions in that gap are exactly
        # the ones whose at-most-once webhook was lost. complete=False + a reason is what an
        # adapter says when it cannot rule out another page; the poller alerts on it
    def verify_webhook(self, headers, body: bytes, source_ip: str) -> WebhookVerdict
        # per-engine: HMAC where the engine signs, source-IP + dedupe where it does not (§5).
        # A verdict, not a bool, so an UNSIGNED accept is recorded as the hint it is
    def parse_webhook(self, payload: dict) -> CallEvent       # → OUR normalized event
```

Normalized models (ours, stored): CallEvent{call_id, tenant_id, agent_id, direction,
status, started_at, ended_at, from, to, recording_url, cost_raw, engine="bolna",
engine_payload_ref}; TranscriptTurn{call_id, idx, speaker, text, start_ms, end_ms, lang}.
Raw vendor payloads are archived to object storage for debugging but NEVER read by app code —
under `engine-payloads/{tenant}/{call}/…` so a DPDP erasure can enumerate one subject's copies
(D-126); the reference is committed before the object is written. The post-call pipeline is
the writer: one document per completed call, carried out of the adapter as opaque bytes so
"never read by app code" is a property of the TYPE and not a promise (D-157).
Adapter conformance test suite runs against the `bolna` and `fake` adapters in CI
(mocked) — the second adapter exists to keep the first one honest.

**ACCEPTED is not APPLIED, and a publish must score the second.** A 2xx from
`create_agent`/`update_agent` says the vendor took the bytes; whether the agent is
RUNNING them is a different claim, and it is the one a client's compliance disclosure
depends on. `publish_agent` therefore reads the agent back through `get_agent` and scores
it (`apps/api/agents/verification.py`), before any column records the publish:

- **proven mismatch ⇒ REFUSAL.** The transaction rolls back, so `status = 'live'`,
  `engine_agent_ref`, `live_prompt_id` and `live_tts_voice` never claim a script the
  engine was observed not to be holding.
- **unproven ⇒ RECORDED, never rounded up.** `agents.live_verify_state` (migration
  c1f6a94d2b07) carries `unverified` / `applied` / `unreadable` / `unreachable`, and the
  screen renders which. "We could not read the field" and "the engine does not have it"
  are different facts (the `AgentSnapshot.*_readable` tri-state) and only one is evidence.
- **drift the publish path cannot see** — an agent edited in the vendor's own dashboard,
  or a publish that failed on our side after the vendor committed — is answered by
  `GET /v1/agents/{agent_id}/engine-state` on demand, and by `sweep_engine_drift`, an ARQ
  cron at :07/:37 that walks the 25 STALEST live agents through the same read (D-123).
  Both are READS: they report and re-publish nothing, because overwriting a drift
  overwrites whatever the vendor's console was used to change, plausibly the correct
  emergency edit made while ours was down. The sweep's verdict lands on
  `engine_agent_routes.drift_state` (migration d4b8e1c73f05 — there rather than on
  `agents`, which is FORCE-RLS'd and so cannot serve a global staleness-ordered queue or a
  cross-tenant ops summary) and is published on `GET /v1/ops/platform` as `engine_drift`.
  A PROVEN mismatch alerts; `unreadable`/`unreachable` are counted separately and do not,
  because an alarm that fires when the vendor is briefly slow is one nobody reads.
- **an orphan is now COMPENSATED, not just logged.** A create whose recording fails leaves
  a vendor object we are billed for and cannot address; `agents/service.py::_reclaim_orphan`
  calls `delete_agent` inline before the publish raises — inline rather than through the
  outbox because the ref lives only in that frame and an outbox row would roll back with
  the transaction that is failing. It stays best-effort: a delete that fails logs the ref,
  which is where this path was before. A human's soft-delete deliberately does NOT reach
  `delete_agent` — Bolna's delete destroys the agent's executions, which are a retention
  obligation (SEC-COMP §4).

One property here genuinely needs a vendor account and is the last equality-asserted entry
in `tests/publish_known_gaps_test.py`: whether `POST /v2/agent` honours an idempotency key.
Without one, a create whose RESPONSE is lost makes a second vendor object whose id we never
saw — so there is nothing for the compensator above to name. It is not guessed. What a
REPEAT `delete_agent` answers is the smaller unknown that remains, and it is a MARKED
ASSUMPTION in both real adapters (assumed 404) measured by OPERATIONS §2 gate 2.

Bolna integration surface [deep-research-verified Aug 2026 against docs.bolna.ai + the
bolna-ai/bolna OSS repo; items marked (pilot) need live confirmation on the pilot
scorecard — D-31]:

- **Integration model**: the entire voice pipeline runs on their hosted platform; we
  are an API client (CRUD/provisioning), a webhook consumer, and a custom-function
  server (their agent calls our endpoints mid-call; no documented timeout — measure at
  pilot, design async regardless). Bearer auth, base api.bolna.ai; agent CRUD under
  /v2/agent (legacy unversioned paths deprecated); /call, /call/{id}/stop and
  /executions/{id} unversioned — and note that the EXECUTIONS LISTING is per agent,
  `GET /v2/agent/{agent_id}/executions`, not a global collection: there is no
  `/executions` collection at all, which is what D-353 fixed. A published OpenAPI 3.1
  spec exists and the typed models are read from it (`docs/vendor/bolna/hosted-oas.md`
  holds the pin, the checksum and the complete endpoint inventory). A captured payload
  is still a pilot artifact worth committing — a spec is what the vendor says the server
  does, not what it does.
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
  enforced IN-APP, and there only** (nginx does D-27 real_ip restoration and no `allow`;
  SECURITY-COMPLIANCE §5 carries why the edge layer is declined rather than pending),
  plus dedupe on execution_id; webhook payloads are
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
  names Hindi/Tamil — **Telugu KB quality is a pilot gate**. **THE BUILT-IN KB IS NOT
  DRIVABLE THROUGH OUR PORT AND THE ENGINE NOW DECLARES THE CAPABILITY ABSENT (D-354).**
  `POST /knowledgebase` is `multipart/form-data` taking a PDF (max 20 MB) OR a `url` —
  never raw text, which is all `KBSourceRef` carries — and the created object has NO
  agent field: an agent references a knowledge base by `vector_id` inside
  `llm_agent.llm_config.vector_store.provider_config.vector_ids`, not by the `rag_id`
  this port returned and deleted by. Both of gate 8's questions are therefore answered
  (the list carries no agent linkage, so `list_kb` reported every agent empty forever),
  and in-call retrieval stays OURS — the D-28 managed vector service behind the RAG tool
  endpoint, which is where every tier above T0 already lives. Custom functions follow
  the OpenAI function-calling schema (bearer/custom-header auth, pre_call_message
  filler line).
- **BYOK key custody — where the keys actually live.** First, a terminology fix: in this
  blueprint **"BYOK" means *we* bring *our* model keys to the *engine*.** Clients never
  hold or supply model keys — we are a managed service (D-10, flat tenancy). Three
  locations, and only three:
  1. **Canonical copy → the secrets manager.** `SARVAM_API_KEY`,
     `AZURE_OPENAI_API_KEY` (D-410 — the static key for BOTH LLM surfaces; it is a
     credential, so the name-fragment machinery seals it out of `platform_settings` and
     nothing may log it), `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` (D-23 — lead delivery
     only; the LLM legs no longer touch Google),
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
| **H1** | In-call working memory — the running dialogue the agent reasons over | the call only; **discarded at hangup** | the ENGINE's orchestrator (the LLM message array) | no line item — LLM input tokens, already inside the ₹0.10–0.24/min LLM leg (§10.1) | 0ms (nothing is retrieved) |
| **H2** | Call-level durable memory — transcript, AI summary, extraction fields, sentiment, resolved/needs-follow-up | retention policy (90-day recording floor) | OURS — Postgres, written by the post-call pipeline (§8) | Sarvam extraction ₹0.00/call — free per token, and this pass has never run on a paid vendor (`GEMINI_EXTRACTION_DEFAULT is False`) | n/a (post-call) |
| **H3** | Caller / tenant long memory — repeat-caller context, semantic search over calls and leads | forever | managed RAG/memory service (D-28) | provider unit cost | injected **pre-call** via the context webhook (~5s budget), never mid-call |

H1 is not a component we build, buy, or key: the engine holds the conversation for the
duration of the call and drops it at hangup. The hand-off from H1 to H2 is the post-call
pipeline (§8) — **from H2 onward this is entirely mechanisms we already have** (extraction
§7, leads, dashboards), and repeat-caller behaviour is H3 injected at the START of the next
call, not memory persisting across calls. Two consequences:

- **H1 is not free, it is unmetered.** The full conversation is resent to the LLM every
  turn, so input tokens grow through the call: minute 10 costs more than minute 1. The
  per-minute LLM figure in §10.1 is therefore a CURVE and not a rate — `billing/rates.py::llm_cost_inr_per_minute`
  takes a duration for exactly this reason. Provider-side prompt caching would mitigate it
  and a resent conversation is the ideal shape for it, but **whether Azure OpenAI applies
  it to our deployment, and on what terms, is NOT verified here and is not folded into any
  number** — the same discipline retired gate 14c applied to a Vertex surcharge.
  **UNVERIFIED (pilot gate 8):** whether Bolna truncates or summarises history at a
  window limit, and whether it enables any provider-side caching on BYOK keys.
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

**Cost is not the deciding variable** (₹0.02–0.05 against ₹1.70–2.34/min of BYOK model
cost is noise; D-410 moved that subtotal by pennies and did not move this conclusion). **Latency is** — which is exactly the D-28 gate below. So v1 keeps in-call
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

**MEASURED, 15 Aug 2026 — the server half of the 100ms budget, which had never been
measured despite CLAUDE.md saying to.** The budget names an in-call RAG tool endpoint that
does not exist (D-33 keeps T3 in the engine, and
`tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side` fails
the day one appears). What DOES sit on the audio path is the engine custom function
`POST /tools/v1/{engine}/opt-out`, which shares every layer a retrieval endpoint would
need before it retrieved anything — source verification, bounded read, JSON parse, ack
accounting, ARQ hand-off. Measured against the real handler, real Redis, nothing stubbed
(`tests/tool_endpoint_budget_test.py` holds the harness, the full table and the caveats):

| in flight | 1 | 8 | 24 | 96 | 250 |
|---|---|---|---|---|---|
| server-measured ack p50 (ms) | 0.9 | 6.3 | 15.1 | 48.5 | 143.0 |
| server-measured ack p95 (ms) | 0.9 | 6.8 | 17.1 | 51.1 | 187.7 |

At one call in flight the handler spends **p50 1.0ms, p95 1.4ms, max 3.8ms** over n=500,
reaching Postgres **zero** times — 1.4% of the budget. The cost is CONCURRENCY, not the
handler: the distribution is flat at every width (D-55's convoy signature — one event
loop, ~1,750 acks/s per process), so `latency ≈ in-flight ÷ 1,750` and **100ms is reached
at ~175 concurrent in-flight tool calls per process**. D-32 records Bolna at 100
concurrent on Pilots and 250+ in production, so at production width our own server time
exceeds the whole budget before any network is counted — a process-count question
(DEPLOYMENT §2a), on this endpoint as on the receiver.

**What that does and does not settle.** It settles the half we own: the server side is
affordable at one call in flight and is a sizing problem above ~175. It settles nothing
about the ROUND TRIP, which is the number this section's "+150–400ms" estimate is about
and which only a live call can produce — pilot gate 8's `custom_function_tool_call_budget`
(`scripts/pilot/knowledge.py`), still NOT RUN. The two are different quantities and are
deliberately kept in different places.

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
and there is NO silent failover between providers — Sarvam
(`calevate_shared.engine.SARVAM_DEFAULT_LLM`, today `sarvam-105b`; the literal
`sarvam-m` shipped here until D-105 and Sarvam has since RETIRED it, so the code was
aimed at a model that no longer answers while §10 priced the 105B) when a Sarvam key
is present, and an offline heuristic runner otherwise, which is what keeps the regression
harness's baseline stable.

**No general-purpose model vendor is in that ladder, and `GEMINI_EXTRACTION_DEFAULT is False`
is the greppable form of why** (D-127 G-2/G-7; the constant keeps its name because the rule
it records is about this PASS, not about a vendor). **D-400 moved the in-call LLM leg off
Sarvam and D-410 moved it again, to Azure OpenAI South India — neither moved THIS one**, and
that is the distinction both decisions turn on: the in-call leg and the dashboard assist see
the caller through the engine and through `text_redacted` respectively, and this pass is the
only one in the system that reads `turn.text`. This selector's caller is `workers/pipeline.py`, which hands
over the RAW transcript — `turn.text`, one line after `redacted.text` is computed, because
a CRM "callback number" field needs the actual digits. Until D-127 the ladder returned a
second-vendor client whenever that vendor's key was configured and a Sarvam key was not, so
one absent environment variable sent raw caller PII to a second processor. The other vendor
now serves only the USER-TRIGGERED work, through `workers/extraction.run_assist()`, over the
redacted copy, on Azure OpenAI in South India — and `run_assist` re-runs `redact()` on its
input and REFUSES text that still yields a match, so G-2 is structural rather than
documentary.

⚠ **This paragraph describes BEHAVIOUR and is the line that rots first.** Everything in it
is decided in one function; if you are changing that function, change this paragraph in the
same edit. `GEMINI_EXTRACTION_DEFAULT` exists so `scripts/check_docs_drift.py` §5 can catch
the half of that which is machine-decidable.

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

Per-minute variable (₹): platform 1.5–2.0 (A-1) · STT 0.50 · TTS 1.08–1.62 (Bulbul v3)
· **LLM 0.10–0.24 (`gpt-4o-mini` on Azure OpenAI South India — the band is the one- to
ten-minute curve, not a rate; supersedes D-400's 0.23–0.51 Gemini band and D-36's ₹0.00.
On the `gpt-4.1-mini` switch it is 0.27–0.65 — 2.67x, see §10.1)**
· telephony 0.40–0.90 inbound / 0.60–1.80 outbound. **Blended all-in ≈ 3.3–3.8 (launch)
→ 1.9–2.6 (phase 2)** — derived rather than adjusted, because adjusting is how the two
bands drifted apart in the first place. Launch is **D-36's ≈₹3.1–3.6 plus the shipped LLM
leg at the five-minute reference (₹0.16)** = 3.26–3.76. Phase 2 is that minus the ₹1.50
platform fee plus §10.1's ₹0.15–0.30 compute = 1.91–2.56. *(This line read "3.3–3.9 →
1.7–2.6" and `docs/README.md` read "3.3–3.8 → 1.9–2.5" — the same decision, subtracted
twice by two different routes, because D-400 rounded 3.46–3.96 UP to "3.5–4.1" and every
later re-derivation inherited the extra 0.14. Both now quote this derivation; neither is
re-rounded independently.)* These are blended mid-ladder estimates, not the min–max — that
is §10.1's **₹2.89–4.28**.

> ⚠ **THE LLM LEG IS NOT FREE AND IS NOT A FLAT PER-MINUTE RATE (D-400, repriced by D-410).**
> D-36 priced it at ₹0.00 because Sarvam 105B is free per token; it is now `gpt-4o-mini` on
> a paid Azure OpenAI deployment in South India. The computation is
> `billing/rates.py::llm_cost_inr_per_minute`, which takes a DURATION, because §6.1 resends
> the whole conversation to the model on every turn — so input tokens grow through the call
> and total input cost is quadratic in length. **The SHAPE of the calculation is unchanged
> by D-410; only the vendor price feeding it moved**, from $0.30/$2.50 per 1M tokens to
> `AZURE_LIST_PRICE_USD_PER_MTOK`'s **$0.15 in / $0.60 out** for `gpt-4o-mini` (and
> $0.40 / $1.60 for `gpt-4.1-mini`, the live switch). Cheaper on both legs and half the
> input price, which is where it lands because voice is input-dominated. On the reference
> conversation stated at `rates.REFERENCE_CALL`, on the DEFAULT model: **₹0.10/min on a
> one-minute call, ₹0.16/min at five minutes, ₹0.24/min at ten** — **less than half what
> the Gemini leg cost at every duration** (₹0.23 / ₹0.36 / ₹0.51). **The switch is not a
> free upgrade and the figures say so**: `gpt-4.1-mini` is **₹0.27 / ₹0.44 / ₹0.65**, which
> is **2.67x the default at every duration** (it is exactly 2⅔x on both the input and the
> output leg, so the ratio cannot vary with call length) and **19% to 27% MORE than the
> Gemini leg we just left**, widening with duration. `llm_cost_inr_per_minute` takes
> `model` as a REQUIRED keyword argument for that reason: a caller that priced the default
> while the deployment ran the other one would record 37 paise for every rupee actually
> spent, silently, in a ledger that is append-only. **This is still the one
> leg whose cost a longer call makes worse per minute rather than better**, which is why
> the figure is a function and not a literal.
>
> ⚠ It is also **not billed by the engine, and will never be**. A BYOK leg means the ENGINE
> pays nothing and reports nothing, and the truth arrives on an **Azure invoice, per
> subscription and not per tenant**. That is a metering gap this rate card models and no
> vendor field can close. **A Regional-Standard premium of roughly 5–10% over Global
> Standard is REPORTED (published examples to +12% and +20%) and deliberately not folded
> in** — it is the price of the residency posture, it is paid on purpose, and it is
> confirmed against a real invoice at OPERATIONS §2 gate 20c rather than guessed into a
> constant. This is the same discipline retired gate 14c applied to the Vertex question.

> ⚠ **The model legs above are §10.1's, not July's** — this paragraph is a summary and
> **§10.1 is the rate card.** Two July readings that survived here after §10.1 corrected
> them, both stale in the direction that understates what we have built: "the v2 ₹0.60
> band is likely gone; their docs list only V3 — confirm pricing on account" (D-35 read
> the card live on 11 Aug 2026: **v2 is live at half the v3 rate**, which is why
> `billing/rates.py` bills a two-rung ladder and why `plans.overage_rate_value` exists at
> all), and "LLM 0.04–0.10" — which is stale in the OTHER direction now. D-36 replaced it
> with ₹0.00 (Sarvam 105B, free per token), D-400 replaced that with a real,
> duration-dependent leg, and **D-410 has repriced that leg onto `gpt-4o-mini`** — same
> curve, a cheaper vendor price, and an output leg 4x its input leg rather than 8.3x.
> `scripts/check_docs_drift.py` §4b now
> diffs §10.1's card against `TTS_INR_PER_10K_CHARS`, so the RATES cannot drift again
> unwatched; the platform and telephony bands here remain UNVERIFIED estimates (pilot
> gate 12) and no check can say otherwise.

Actual per-call cost comes from Get Call's
cost.breakdown (platform_fee/stt/tts/llm/telephony, INR) recorded into usage_events.
Fixed monthly: **priced against a DigitalOcean stack that is no longer the plan** —
~$75–125 (web/api droplet, worker droplet, managed PG, Redis, storage) ≈ ₹7–10k; plus
platform/model minimums + numbers ≈ ₹3k. **D-25/D-26 moved hosting to a single
general-purpose VPS with self-hosted Postgres and Redis**, which is fewer billed
components, so ₹7–10k is a CEILING rather than an estimate and the real figure is likely
lower. It is left standing because no host is chosen and nothing is provisioned
(LEGAL-SURFACE F-1), so there is no invoice to replace it with — re-measure at deploy.
§10.2 carries the same caveat where the number is actually used.

**Normalized platform comparison (D-32 method: BYOK legs removed, since they are
identical on every platform).** The BYOK stack is a CONSTANT — STT ₹0.50 + TTS
₹1.10–1.60 + LLM ₹0.10–0.24 (`gpt-4o-mini`, one to ten minutes) = **₹1.70–2.34/min
everywhere** (→ ₹1.60–2.10 if Sarvam's LLM is genuinely free and the leg is switched back
to it; → ₹1.87–2.75 on the `gpt-4.1-mini` switch).
**The forced-migration adder that used to sit here is GONE**: it priced BRD R-04's
Gemini-3.x step, and D-410 removed the retirement date along with the model.
Telephony (~₹0.35–0.50) is likewise constant. Only the platform fee and latency differ:

| Platform | Platform fee (BYOK; excludes STT/TTS/LLM) | Latency posture |
|---|---|---|
| **Bolna** (primary, D-31) | **unpublished** — pilot gate 12; bundled ₹5.52→₹4.15; rumoured ~₹1.8 (unverified); target ≤₹1.5. **No monthly floor** (prepaid credits) | undefined "<300ms" marketing claim; compute region UNVERIFIED (recordings on S3 us-east-1) |
| LiveKit Cloud (phase-2 candidate) | marginal ₹1.23 (agent + third-party SIP, two meters) but **$50/mo Ship floor dominates**: ₹4.40/min @1k min, ₹0.88/min @5k min; concurrency capped 5/20/600 | ✅ ap-south (Mumbai) VERIFIED — best-evidenced |
| Pipecat Cloud (phase-2 candidate) | ~₹0.88 claimed — **entirely unverified** | regions unverified |
| Self-host (DO BLR / Vultr Mumbai) | ₹2.1/min @1k, ₹0.85–1.2/min @5k (₹2,112/node ≈ 8–9 concurrent) | best possible physics (co-located), unmeasured |
| ~~Cartesia **Line**~~ (D-88, re-examined Aug 2026) | ₹5.28/min ($0.06/min, Free→Startup) — **bundled, and now CONFIRMED bundled**: Line's LLM is fully BYOK via LiteLLM (`model=` + `api_key=`, 100+ providers) but **STT and TTS are not** — Ink 2 and Sonic 3.5 are the product and the SDK exposes no swap interface (first-party: the Line SDK README, `github.com/cartesia-ai/line`). So it is not comparable to a BYOK fee, and it **cannot host D-36's Sarvam stack**. Scale tier $0.014/min (₹1.23) is enterprise-negotiated with an unpublished commitment. Monthly plans to $299 (₹26,312); agent concurrency capped 1/3/5/10 by tier. Eliminated on **telephony**, not price: Cartesia numbers / imported Twilio / Voximplant, none of which is a DLT-registered Indian number | India story is REAL but enterprise-shaped: Blue Machines AI partnership (~Feb 2026) for India-**resident** processing, Bangalore office, Sonic 3 across the top 9 Indic languages incl. Telugu, on-prem/VPC/air-gapped, SOC 2 Type II + HIPAA + PCI L1. The earlier "English-first TTS" reading was **stale and is withdrawn**. Self-serve India region still unverified — `docs.cartesia.ai` and `www.cartesia.ai` are unreachable from our build environment |
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
| **Sarvam 105B / 30B (chat LLM)** | ⚠ **Free per token** — *and no longer our LLM leg (D-400, D-410). Kept on the card because it is the disclosed dashboard-assist fallback, because it prices the value rung of §10.3's ladder, and because a rate we walked away from is worth being able to walk back to. Walking back is not free: Sarvam has no member in Bolna's `LLMProvider`, so an in-call return means `provider: "custom"` — the credential path retired gate 16c put in doubt.* |
| Text-to-Speech **Bulbul v3** | ₹30 / 10,000 chars |
| Text-to-Speech **Bulbul v2** | ⚠ **₹15 / 10,000 chars — still live, not discontinued** |
| Speech-to-Text | ₹30 / hour |
| Speech-to-Text **and Translate** (Saaras) | ₹30 / hour |
| STT with diarization | ₹45 / hour |
Plans: pay-as-you-go with **no minimum**; ₹1,000 free credits; credits never expire and are
universal across APIs. **Rate limits are the real constraint, not price** — 60 rpm (Starter) /
200 rpm (Pro ₹10k) / 1,000 rpm (Business ₹50k).

> ⚠ **Corrects D-20**, which recorded Bulbul v2 as "appears discontinued." It is live at
> **half** the v3 rate. ⚠ **Corrected R-04's premise; D-400 overtook that and D-410 has closed it** — Sarvam's LLM is genuinely free per token, which made a paid LLM leg avoidable on COST grounds; the founder took one anyway, first on Vertex and now on Azure OpenAI South India, for the reasons in D-400 and D-410. **R-04 itself is now CLOSED on every leg**: the retirement date died with the Gemini model. The ₹0.00 line below is what we gave up rather than what we run.

**Cost per call-minute.** Assumption doing the most work: the agent speaks 40–60% of a call at
~900 characters/minute of speech → **360–540 TTS characters per call-minute**. That ratio is
unmeasured and is the single biggest lever on the TTS line (pilot gate 12).

| Leg | Rate | Per call-minute |
|---|---|---|
| STT — Saaras (STT+Translate) | ₹30/hr | **₹0.50** |
| TTS — Bulbul **v3** | ₹3.00 / 1,000 chars | **₹1.08–1.62** |
| TTS — Bulbul **v2** | ₹1.50 / 1,000 chars | **₹0.54–0.81** |
| LLM — **`gpt-4o-mini` on Azure OpenAI `southindia`** (D-410 default) | $0.15/$0.60 per 1M tok | **₹0.10 (1 min) / ₹0.16 (5 min) / ₹0.24 (10 min)** |
| LLM — `gpt-4.1-mini` on Azure OpenAI `southindia` *(the live switch, `azure_openai_model`; availability in Indian regions NOT confirmed — gate 20b)* | $0.40/$1.60 per 1M tok | **₹0.27 (1 min) / ₹0.44 (5 min) / ₹0.65 (10 min)** |
| LLM — Sarvam 105B *(what D-400 superseded; the disclosed dashboard fallback and §10.3's value rung)* | free per token | ₹0.00 |

**BYOK model subtotal, by combination** (identical on every platform — not a decision
variable, D-32):

Paid-LLM rows are quoted at the **five-minute** figure — **₹0.16/min on `gpt-4o-mini`, ₹0.44 on `gpt-4.1-mini`** — because a blended average has to pick a call length and five minutes is the one §10's other assumptions are written for. A ten-minute call adds **₹0.08/min** to every `gpt-4o-mini` row and **₹0.21/min** to every `gpt-4.1-mini` row. Neither figure is a rate: `llm_cost_inr_per_minute` takes a duration because §6.1 resends the whole conversation each turn, and it takes `model` as a required keyword because the two rows above differ by 2.67x.

| Combination | Per call-minute |
|---|---|
| **Bulbul v3 + `gpt-4o-mini`** (D-410 default) | **₹1.74–2.28** |
| Bulbul v3 + `gpt-4.1-mini` *(the switch — what it costs, stated where the choice is made)* | ₹2.02–2.56 |
| Bulbul v3 + Sarvam LLM *(what runs today)* | ₹1.58–2.12 |
| Bulbul v2 + `gpt-4o-mini` | ₹1.20–1.47 |
| **Bulbul v2 + Sarvam LLM** (cheapest verified) | **₹1.04–1.31** |

| Remaining legs | Per call-minute | Status |
|---|---|---|
| Telephony (Exotel/Vobiz class) | ₹0.35–0.50 *(estimate)* | **UNVERIFIED** |
| Engine platform fee (Bolna BYOK) | target ≤₹1.50 | **UNVERIFIED — pilot gate 12** |
| **All-in, rented engine** | **₹2.89–4.28** | v2+Sarvam-LLM floor → v3+`gpt-4o-mini` ceiling at five minutes; **₹4.36 at ten**. **The floor did not move at D-410** — its combination has a free LLM leg — but it was WRONG, by ₹1.00, from the first commit of this document until 20 Aug 2026: it read **₹1.89**. See the ⚠ below. The CEILING fell ₹0.20, from D-400's ₹4.48. On the `gpt-4.1-mini` switch the ceiling is **₹4.56 at five minutes and ₹4.77 at ten** — above where the Gemini leg left it |

> ⚠ **THE FLOOR SAID ₹1.89 AND THAT WAS ARITHMETIC, NOT A DIFFERENT ASSUMPTION.** Both ends
> of this row add the same three things: a BYOK model subtotal from the table above, a
> telephony estimate from the row above, and the engine platform fee. Written out:
>
> ```
> floor    = 1.04 (Bulbul v2 + Sarvam LLM, low end)  + 0.35 (telephony, low)  + 1.50 (fee) = 2.89
> ceiling  = 2.28 (Bulbul v3 + gpt-4o-mini, high, 5m) + 0.50 (telephony, high) + 1.50 (fee) = 4.28
> ceiling@10m = 2.36 + 0.50 + 1.50 = 4.36      gpt-4.1-mini: 2.56/2.77 + 0.50 + 1.50 = 4.56 / 4.77
> ```
>
> **₹1.89 implied a platform fee of ₹0.50 on the floor and ₹1.50 on the ceiling — one row
> of one table, two different fees — while the row directly above states one target,
> ≤₹1.50.** Nothing in the document ever asserted ₹0.50; it is the ceiling's arithmetic run
> once correctly and once with a dropped rupee. Three independent places already carried the
> right number and were never reconciled against this cell: `docs/README.md` ("floor
> **₹2.9** on Bulbul v2 + Sarvam LLM"), ROADMAP §6 D-36 ("verified floor ₹2.9 on v2+Sarvam"),
> and §10.2, which quoted "the ₹2.98–4.32 above" — a digit transposition of the same ₹2.89,
> propagated into every row of its effective-cost table and corrected there too.
> **The fee target is right and the floor was wrong**, and it is corrected here rather than
> left as two numbers that cannot both be true.
>
> What the floor is NOT: it is not a price we have been quoted. The platform fee is
> **UNVERIFIED** (pilot gate 12) and the dashboard reading of ~₹1.76/min in
> `docs/PRODUCTION-READINESS.md` §A1 is a screen, not a commercial term — at ₹1.76 this
> floor is ₹3.15 and the ceiling ₹4.54. The ladder is written against the TARGET because
> that is the number the pricing decisions were made on; gate 12 is what replaces it.

The quality/cost trade is now explicit and ours to choose per tier: **v2+Sarvam LLM is ~42% cheaper per minute than v3+`gpt-4o-mini`** (and ~49% cheaper than v3+`gpt-4.1-mini`) — and D-400 moved the DEFAULT to the expensive end of that ladder deliberately, so the ladder itself is the margin lever it was designed to be rather than a note about one. **D-410 narrowed the gap rather than closing it**: the spread was ~47% against the Gemini leg and is ~42% against `gpt-4o-mini`, because the premium rung got cheaper while the free rung did not move. **Flipping `azure_openai_model` widens it straight back to ~49%**, which is the honest way to read that switch — it is a quality bet costing 2.67x the default LLM leg, not a free upgrade. Bulbul v3 vs v2 Telugu quality is an **ear test at
the pilot**, not a spec decision — and it is exactly the lever that lets us build a
value/premium ladder (see §10.3).

**Self-orchestrated comparison (phase 2).** Same BYOK subtotal + telephony, no platform
fee, plus ~₹0.15–0.30/min compute (2 vCPU/4 GB node ≈ ₹2,112/mo, ~8–9 concurrent):
**≈ ₹2.20–3.14/min** (re-derived at D-410 from the ₹1.70–2.34 BYOK constant above; it read
₹2.23–3.12 against the Gemini leg, so this one barely moved — the LLM change lands almost
entirely inside the subtotal's own rounding). *(This is the **v3 premium rung across the
whole 1–10 minute LLM curve**, which is why it sits above §10's blended phase-2 band of
≈₹1.9–2.6: that one is mid-ladder, and the v2 rung takes ₹0.54–0.81 off the TTS line. Two
different questions, both stated, neither an adjustment of the other.)* The delta is therefore still **≈ ₹0.9–1.5/min**,
which is simply the platform fee: **both sides carry the identical BYOK leg, so a cheaper
model moves the two totals together and the delta by nothing** — consistent with the
~2k min/month break-even already stated above.

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
| LLM (Sarvam 105B) | ₹0.00 — free per token | **verified rate** *(theirs; ours moved to a paid leg at D-400 and to Azure OpenAI South India at D-410, so this row is a statement about a COMPETITOR's inputs and not about ours)* |
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

The ₹2.89–4.28 above is **variable cost only**. It is not what a minute actually costs us
until the fixed base is carried. Applying the D-32 floor rule to ourselves (we applied it to
LiveKit and to Outpero; it binds here too):

*(This section's variable band read **₹2.98–4.32** from this document's first commit until
20 Aug 2026 — the ₹2.89 floor with two digits transposed, and the pre-D-400 ₹4.32 ceiling.
The effective column was internally consistent with those two numbers, so correcting the
band moved every row by 5–10 paise; the conclusions below are unchanged and the break-even
still lands near 5,000 platform-minutes.)*

**Fixed monthly base ≈ ₹10–13k** — infra ₹7–10k + platform/model minimums and numbers ≈ ₹3k.
*(This range predates D-25/D-26, which moved us to a general-purpose VPS with self-hosted
Postgres; the true figure is likely lower — re-measure at deploy.)*

Crucially this base is **shared across all tenants**, so the divisor is **total platform
minutes**, not one client's usage:

| Total platform min/month | Fixed share | + variable | **Effective ₹/min** |
|---|---|---|---|
| 1,000 (client #1 only) | ₹10.0–13.0 | ₹2.89–4.28 | **₹12.9–17.3** |
| 2,500 | ₹4.0–5.2 | ₹2.89–4.28 | **₹6.9–9.5** |
| 5,000 | ₹2.0–2.6 | ₹2.89–4.28 | **₹4.9–6.9** |
| 10,000 | ₹1.0–1.3 | ₹2.89–4.28 | **₹3.9–5.6** |
| 20,000 | ₹0.5–0.65 | ₹2.89–4.28 | **₹3.4–4.9** |

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

### 10.4 Scenario model: Bolna BYOK vs Cartesia Line at four volumes (Aug 2026, D-88)

§10.1 prices the legs and §10.2 amortizes the base. This section is the same arithmetic
run against a **named alternative**, because R6 forbids comparing platforms on headline
rates and the only honest comparison is effective ₹/min at a stated volume, per path.

**Two inputs are new since §10.1 and both change the answer.** First, **Bolna's BYOK
platform fee is observed at 2¢/min ≈ ₹1.76** (from the Bolna dashboard, Aug 2026) — that
sits INSIDE §10's assumed ₹1.50–2.00 band but **ABOVE OPERATIONS gate 12's negotiation
target of ≤₹1.50**, so the gate is not satisfied by the observation and still needs the
number in writing. Second, **Cartesia Line's $0.06 is confirmed bundled** (D-88), so it
must be compared against Bolna's *platform + models*, never against the platform fee
alone. FX ₹88/USD throughout, matching §10's existing figures.

| Leg | Bolna (BYOK) | Cartesia Line (Startup) |
|---|---|---|
| Platform fee | ₹1.76 (2¢) | ₹5.28 ($0.06) — **includes STT + TTS** |
| STT | ₹0.50 (Saaras) | *in the fee (Ink 2)* |
| TTS | ₹0.54–0.81 (Bulbul v2) · ₹1.08–1.62 (v3) | *in the fee (Sonic 3.5)* |
| LLM | ₹0.00 → **+₹0.16 (D-410, five-minute)** | ₹0.00 → **+₹0.16** (BYOK; Cartesia's own LLM line is "free for a limited time" — do not model on it) |
| Telephony, blended in/out | ₹0.50–1.35 | ₹0.50–1.35 |
| **Variable total** | **₹3.30–4.42** (v2) · **₹3.84–5.23** (v3) | **₹5.78–6.63** |
| Midpoint used below | **₹3.87** (v2 stack) | **₹6.21** |

> ⚠ **THE TOTALS AND MIDPOINTS ABOVE HOLD THE LLM LEG AT ₹0.00 ON BOTH SIDES, AND THAT IS
> DELIBERATE RATHER THAN STALE (D-400, repriced by D-410).** The leg is no longer free —
> `gpt-4o-mini` on Azure OpenAI South India costs ₹0.10–0.24 per minute
> depending on call length (§10.1) — but it is BYOK on both platforms and therefore
> identical on both, which is exactly the class of input D-32's method removes from a
> platform comparison. Adding the same figure to each column moves both midpoints and moves
> the DELTA by nothing, so the break-even arithmetic below is unaffected. **What it does
> move is the absolute floor**, and §10.1 is where that lives: read the all-in number from
> there, never from this table.

Fixed monthly: infra ₹8,500 + ~₹300/client DID rental *(assumption — the Exotel/Vobiz
rate card is still an open gate, ROADMAP §1)*. The Bolna path additionally buys a
**Sarvam plan tier for RATE LIMITS, not price** (60 → 200 rpm ₹10k → 1,000 rpm ₹50k);
the Cartesia path does not, because it is not calling Sarvam for speech. The Cartesia
path instead carries **$299/mo ≈ ₹26,312** for the Startup plan.

| | S1 · 1 client<br>1,000 min | S2 · 3 clients<br>5,000 min | S3 · 10 clients<br>20,000 min | S4 · 25 clients<br>60,000 min |
|---|---|---|---|---|
| Bolna — variable | ₹3,870 | ₹19,350 | ₹77,400 | ₹232,200 |
| Bolna — fixed | ₹8,800 | ₹9,400 | ₹21,500¹ | ₹26,000¹ |
| **Bolna — effective ₹/min** | **₹12.67** | **₹5.75** | **₹4.95** | **₹4.30** |
| Cartesia — variable | ₹6,210 | ₹31,050 | ₹124,200 | *concurrency cap* |
| Cartesia — fixed | ₹35,112 | ₹35,712 | ₹37,812 | *enterprise* |
| **Cartesia — effective ₹/min** | **₹41.32** | **₹13.35** | **₹8.10** | **n/a self-serve** |

¹ Sarvam Pro (₹10k) assumed from S3 for the 200 rpm ceiling — the one line where not
using Sarvam speech genuinely helps Cartesia, and it is nowhere near enough to pay for
itself.

**The concurrency wall is the part a price table hides.** At 22 working days × 8 hours,
average concurrency is `min ÷ 10,560`; peak runs ~4× average. S3 needs ~8 slots against
Line's **10-slot self-serve ceiling**; S4 needs ~23 and has no self-serve tier at all.
Bolna has no concurrency tier and no monthly floor (prepaid credits).

**Break-even against retail**, solving `(variable × min + fixed) / min = retail` at
S2-scale fixed costs:

| Retail | Bolna break-even | Cartesia Startup break-even |
|---|---|---|
| ₹5/min | 8,319 min/mo | never (variable ₹6.21 > ₹5) |
| ₹6/min | 4,413 min/mo | never |
| ₹7/min | 3,003 min/mo | **45,205 min/mo** |

That last cell is the elimination in one number **for the Startup tier**: it needs ~45,000
min/month to break even at ₹7/min, which needs ~17 concurrent slots, which the tier caps
at 10. There is no volume at which the Startup tier works.

### 10.4a The Scale tier — CORRECTION to the paragraph this replaces

The first version of this section called Scale "enterprise-negotiated with an unpublished
commitment". **That was wrong and is withdrawn.** Scale is published and self-serve:
**$239/month on annual billing** ($2,868/year ≈ **₹252,384**) or $299/month monthly, and
it drops the Line rate from $0.06 to **$0.014/min (₹1.23)**, models still included, with
8M model credits and $299 of prepaid Line minutes in the plan. The commitment is a known
₹21,032/month, not an unknown. That changes the arithmetic materially and in Cartesia's
favour, so it is corrected here rather than left flattering to the incumbent.

| | S1 · 1,000 min | S2 · 5,000 min | S3 · 20,000 min | S4 · 60,000 min |
|---|---|---|---|---|
| Bolna effective ₹/min | ₹12.67 | ₹5.75 | ₹4.95 | ₹4.30 |
| Cartesia **Scale** effective ₹/min | ₹31.99 | ₹8.25 | **₹3.79** | ₹2.78 *(unreachable — see below)* |
| Monthly delta | +₹19,322 | +₹12,482 | **−₹23,168** | — |

**Crossover ≈ 12,300 min/month**, solving `1.71 × min = ₹21,032` (the ₹1.71/min variable
advantage against the plan fee). It arrives earlier still — ≈6,450 min/month — once the
Bolna path needs the Sarvam Pro tier for rate limits, since the Cartesia path buys no
Sarvam speech and therefore does not.

**And there is an upper bound, which is the part a price table hides.** Scale caps agent
concurrency at 10 slots. At 22 working days × 8 hours with peaks ~4× average, 10 slots is
~26,400 min/month. So the Scale window is roughly **12,300 → 26,400 min/month**; above it
the tier is Enterprise and genuinely unpublished again.

That window is real and it is narrow, and it is exactly the volume band where the four
blockers below bite hardest — Indian DLT telephony above all, since a saving you cannot
legally dial through is not a saving. §10.5 is what to do about that.

**Two things this table says about OUR path, independent of Cartesia:**

1. **Closing gate 12's ₹0.26 fee gap is worth ₹5,200/month at S3 and ₹15,600 at S4.**
   Real money, and a reason to run the negotiation properly — but not a crisis, and not
   something switching orchestrators fixes.
2. **The larger lever is Bulbul v2 vs v3** — ₹0.68 vs ₹1.35 at the midpoint, which is
   ₹13,400/month at S3 and ₹40,200 at S4, *bigger than the entire platform-fee gap*. It
   is decided by a Telugu ear test at the pilot (§10.1), not by a rate card.

**Caveat carried forward, and it is ours:** §10 and FLOWS §257 price telephony at
₹0.40–0.90 inbound / ₹0.60–1.80 outbound while §10.1 estimates ₹0.35–0.50. This table
uses the wider band. If outbound really lands at ₹1.80, every Bolna figure above rises
~₹0.45/min and the ₹5/min tier stops working below ~12,000 min/month.

### 10.5 The orchestrator exit plan — build for the switch, do not build the switch

D-31 rents an engine. §10.4a shows a real cost window in which Cartesia Line beats that
choice. The decision this section records is **not** "switch"; it is **"make switching a
configuration change, and pre-commit the trigger that makes it one worth making."**

**Why this is not speculative work.** The exit door already exists by construction: hard
rule 2 isolates every vendor shape inside `apps/api/engine/`, `VoiceEngine` in
`packages/shared` is the port, and `make conformance` runs both adapters against one
contract. What has never been tested is whether that contract is vendor-NEUTRAL or merely
Bolna-shaped — and those look identical while only one vendor exists. A second adapter
written on the day of the switch is the expensive way to find out.

**The one thing the founder's instinct got right, and the one it got wrong.** Right: our
**Sarvam LLM key works on Cartesia Line** — Line routes through LiteLLM, Sarvam is a
first-class LiteLLM provider (`sarvam/` prefix) with an OpenAI-compatible endpoint at
`https://api.sarvam.ai/v1`, so the free-per-token LLM leg of D-36 survives the move
intact. **D-400 replaced that leg and D-410 has replaced it again, with Azure OpenAI South
India — and the portability argument comes back STRONGER than either Vertex form left it**:
an OpenAI-compatible `base_url` is what both engines take, so the endpoint ports, and the
credential is now a STATIC API KEY, so it ports too. The Vertex leg's blocker — a
short-lived OAuth2 bearer that no static credential store can hold (D-402) — would have
been the identical blocker against Line, and it is gone. Wrong: **the speech legs do not.** Line's TTS configuration takes a Cartesia
`voice_id` and a Cartesia `model` (`sonic-3.5`/`sonic-2`) — there is no provider field,
and Ink 2/Sonic are the product rather than a default. So "BYOK Sarvam into Cartesia"
is true for one leg of three, and D-36's residency argument rests on the other two.

**What a switch actually costs, itemised.** These are capability DIFFERENCES, which is
why the engine port is where the work belongs:

| Capability | Bolna | Cartesia Line | Consequence for us |
|---|---|---|---|
| BYOK LLM | yes | **yes** (LiteLLM) | Sarvam 105B survives the move; D-410's Azure leg ports as a URL AND a static key, which the Vertex leg could not |
| BYOK STT | yes (Saaras) | **no** (Ink 2) | D-36 residency argument weakens; new ear test |
| BYOK TTS | yes (Bulbul) | **no** (Sonic) | agent voice picker becomes a lie unless capability-driven |
| Engine-side campaigns | yes (unverified, TRD §5) | no | we already dispatch in our layer — no loss |
| Built-in KB | yes, `rag_id` (D-33) | **yes** — CORRECTED, see below | no forced loss; the shapes differ, the capability does not |
| Webhook auth | unsigned → IP allowlist + execution-id dedupe | authenticated by an UNSOURCED scheme — see correction 2 | receiver must not hard-code one model |
| Indian DID / DLT 140/160 | yes | **no** | **the blocker** — see below |
| Concurrency | no tier cap | 1/3/5/10 by tier | a business constraint, not a code one |
| **Agent hosting** | agent object we POST a config into | **the agent IS a deployed git repository** — see correction 2 | `EngineCapabilities.agent_hosting`; publishing refuses by name and the floor rides the call (D-280…D-282) |

> ⚠ **CORRECTION (recorded the day it was found).** This table first said Cartesia Line
> has **no** built-in knowledge base, and concluded that T0 retrieval would need our own
> path. **That was wrong.** Reading the Line SDK at source (`github.com/cartesia-ai/line`
> @ `3062c978`) shows `line/knowledge_base.py` as a first-class client and
> `knowledge_base` as a shipped built-in tool. The KB capability survives a move; only its
> shape differs. The wrong version is left visible rather than silently edited, because it
> was reasoned from an absence of evidence — the failure mode `RESEARCH-DISCIPLINE.md`
> exists to catch.

> ⚠ **CORRECTION 2 (D-270) — and this one answers the question this section opened with.**
> §10.5 says: *"What has never been tested is whether that contract is vendor-NEUTRAL or
> merely Bolna-shaped — and those look identical while only one vendor exists."* Reading
> Cartesia's **generated** clients (`cartesia-ai/cartesia-python` and `cartesia-js`, both
> emitted from their OpenAPI spec) settles it. **The contract is Bolna-shaped**, and the
> evidence is in `docs/vendor/cartesia/`:
>
> * **There is no `POST /agents`.** Their `AgentsResource` has `retrieve`, `update`,
>   `list`, `delete`, `list_phone_numbers`, `list_templates` and no `create`. An agent is
>   created by deploying a git repository through the `cartesia` CLI.
> * **The agent object holds no prompt, no greeting and no model.** `AgentSummary` carries
>   `git_repository`/`git_deploy_branch` where a hosted platform would carry a script, and
>   `PATCH /agents/{id}` accepts exactly `{description, name, tts_language, tts_voice}`.
>   The prompt is per-CALL data (`CallRequest.agent.system_prompt`) or deployed code.
> * **The calls listing is per-agent and has no time filter.** `GET /agents/calls` requires
>   `agent_id`, pages on `limit`/`starting_after`, and needs `expand=transcript`.
> * **There is no per-call cost.** Usage is an account-level daily credit meter
>   (`GET /usage/credits`, grouped by capability/model/voice/api_key).
> * **The webhook scheme is not published anywhere we can reach.** The table row above used
>   to say "signed"; no Cartesia SDK carries a signing helper, and the only description of
>   one is a search snippet naming an `x-webhook-secret` SHARED SECRET header — which is
>   not an HMAC. `WEBHOOK_AUTH_BY_ENGINE["cartesia"]` stays `"hmac"` because it is the only
>   value in that Literal that fails CLOSED, and the comment there says so.
>
> **What this cost, and what closed it.** `VoiceEngine.create_agent` and the
> prompt/greeting/model half of `get_agent` describe a platform Cartesia does not run, so
> `apps/api/agents/verification.py` would have scored every publish `unreadable` and hard
> rule 5 could not have been enforced from this repository at all. The port needed a way to
> say *"this engine does not host an agent of ours"*, which `EngineCapabilities` could not
> express — so D-270 relabelled the adapter rather than rewriting it, and named the work.
>
> ⚠ **THAT WORK IS DONE (D-280…D-282), and `docs/evidence/engine-port-neutrality.md` is the
> account of it.** `EngineCapabilities.agent_hosting` is
> `control_plane | external_deployment`; Cartesia declares the second, its three
> agent-write methods and `publish_agent` refuse by name through the one capability
> refusal, and the admin console asks the same capability so the Publish button is not
> offered. **Hard rule 5 did not get weaker to accommodate it**: on the second shape the
> truthful-answer directive rides `CallContext.system_prompt`, every adapter's dial runs
> `require_call_compliance_floor`, and an adapter with no request field for a prompt —
> which is Cartesia's outbound shape today — **refuses every dial** rather than placing one
> with a weaker floor. `fake.EXTERNAL_DEPLOYMENT_CAPABILITIES` exercises the branch that
> DOES dial, in CI, with no account. `CARTESIA_CAPABILITIES.llm` moved `ours` → `engine`
> as a consequence: the vendor really does run Sarvam through LiteLLM (the row above is
> about the VENDOR and stays correct), but no endpoint this adapter holds can carry a
> `ModelConfig` value, which is `transfer`'s argument applied to a speech leg. What remains
> is OPERATIONS §2 **gate 19**, whose (a) and (b) turn two named refusals back into
> behaviour the hour an API key exists.

**The blocker is telephony, and it is the only one that is not ours to fix in code.** Our
entire compliance spine — PE/TM registration, DLT headers and templates, the
promotional-vs-service series classification in `campaigns/service.py`, DNC before every
dispatch tick — presumes an Indian carrier relationship. Cartesia's number paths are
Cartesia-provisioned, imported Twilio, or Voximplant, and none of those yields a
DLT-registered 140/160-series Indian number. **Whether Line accepts SIP from an arbitrary
carrier (BYOC) is the single question that decides whether this exit is available at all,
and it is UNVERIFIED — their docs are unreachable from our build environment.** If BYOC
works, an Indian carrier (Exotel/Vobiz class) can front Line and the exit is live. If it
does not, §10.4a's window is unreachable regardless of price. **Ask this before anything
else; it is cheap to ask and it gates everything downstream.**

**Pre-committed triggers, in the style of §10.2's phase gates.** Re-evaluate the
orchestrator when ALL of:

1. sustained volume **> 12,500 min/month** (§10.4a's crossover), AND
2. Line **BYOC SIP from an Indian DLT-registered carrier is confirmed in writing**, AND
3. **Sonic Telugu passes the same ear test Bulbul passed** for D-36 — a spec claim about
   9 Indic languages is not the test, and D-36 was decided by listening.

Below 12,500 min/month the plan fee dominates and the answer is Bolna. Above ~26,400
min/month the Scale tier's concurrency cap has been passed and the comparison is against
an unpublished Enterprise price, which resets the analysis rather than continuing it.

**What we build NOW, and what we deliberately do not.** We build the capability
descriptor on the engine port, we make the conformance suite prove a capability claim
rather than trust it, and we run the whole system in tests against capability-restricted
engines — one that dictates speech and answers the KB question differently, and one whose
agents are deployed to it from elsewhere — so the places that cannot survive those answers
are found now, cheaply, and not on a migration weekend.

⚠ This paragraph used to end *"We do not write a Cartesia adapter"*, on the sound argument
that an adapter written against an imagined API is worse than none because it looks
finished. **One exists** (`apps/api/engine/cartesia.py`), and the argument was right: it
looked finished, and D-270 found six wire-level facts invented and three methods
describing endpoints the vendor does not serve. What made the difference was not writing
less but marking evidence at the line, harvesting the vendor's own generated clients into
`docs/vendor/cartesia/`, and — D-280…D-282 — teaching the port to REFUSE what the adapter
cannot do instead of pretending. The day the trigger fires, the remaining vendor work is
gate 19, not a class.

### 10.6 Running two engines at once — the concrete Cartesia implementation plan

§10.5 says build FOR the switch. This is what that means in files, in order, with the one
architectural change that actually matters.

**The architectural change: engine selection is currently GLOBAL and must become
per-tenant.** `apps/api/engine/__init__.py::get_engine()` resolves one engine per
deployment from `ENGINE=`, whose permitted values are `calevate_shared.config.EngineName`
— today `fake|bolna|cartesia`, and never spelled out again anywhere else (D-103). That is
a fine shape for one vendor and the wrong
shape for a migration, because it makes the switch a single irreversible flip for every
client at once. Nobody sane migrates a phone system that way.

The good news is that half the work is already done and nobody planned it that way:
**`engine_agent_routes` already carries an `engine` column per agent.** Inbound resolution
— "which agent is this webhook about, and on which engine does it live" — therefore
already works across two engines. What is missing is the WRITE side: `get_engine()` has
no tenant argument, so agent creation, KB pushes and outbound dials all go to the one
globally-configured vendor.

| Layer | State today | What the plan changes |
|---|---|---|
| Inbound routing | `engine_agent_routes.engine` per agent — **already multi-engine** | nothing |
| Write path (`get_engine()`) | global `ENGINE` env | resolves per tenant, defaulting to the platform value |
| Capability differences | implicit, Bolna-shaped | explicit descriptor, conformance-proven (D-93) |
| Webhook auth | Bolna's unsigned + IP allowlist + execution-id dedupe | per-engine: Cartesia signs, so the receiver picks by engine, not by config |
| Cost breakdown | Bolna's `cost.breakdown` legs | per-engine mapping into our `usage_events` legs |
| Voice picker | free choice of TTS vendor | capability-driven — an engine that dictates speech offers its own catalogue |

**Build order, each step independently shippable:**

1. **Capability descriptor + conformance proves the claim** (D-93, in flight). This lands
   first because everything downstream reads it.
2. **`apps/api/engine/cartesia.py`** — the adapter, written to the Razorpay precedent:
   documented shapes, every unsourced field marked UNVERIFIED at the line with the source
   used, and the API version **pinned**. Passes the conformance suite. Its
   `provision_number` refuses by name — Cartesia has no DLT-registered 140/160 path, and
   an adapter that pretends otherwise is worse than one that refuses.
3. **voice-runtime intake per engine.** Cartesia signs its webhooks; Bolna does not, which
   is why our receiver uses an IP allowlist plus execution-id dedupe (TRD §5). The
   receiver must choose its verification by the engine the route resolves to, never by a
   global setting — a deployment running both engines has two authenticity models live at
   once, and getting that wrong means either rejecting good calls or accepting forged ones.
4. **`get_engine(tenant_id)`** — per-tenant resolution, with the platform value as the
   default. This is the canary lever: one client moves, the rest do not.
5. **Ops console engine panel** (D-95 phase 3) — which adapter is live per tenant, its
   capability descriptor rendered from the API rather than hard-coded, and its credential
   status. Switching a tenant's engine becomes a screen action with a step-up
   confirmation and an audit row.
6. **The cutover runbook.** This is the part a config flag cannot do, and pretending
   otherwise is how a migration weekend goes wrong: agents must be re-created on the new
   engine, knowledge bases re-uploaded and re-attached, numbers re-pointed at the new
   webhook URL, and the old engine's agents left in place until the new ones are verified.
   `engine_agent_routes` makes the two coexist; it does not make the objects appear.

**What stays ours regardless of engine, and therefore never migrates:** the compliance
gate, DNC, the consent ledger, DLT template and header state, number classification,
campaign dispatch, the post-call pipeline, extraction, billing. That list is why the
engine is a rented component rather than the product.

**Still UNVERIFIED and gating step 2's usefulness rather than its existence:** whether
Line accepts BYOC SIP from an Indian DLT-registered carrier (§10.5). The adapter can be
built and conformance-proven without that answer. It cannot legally dial an Indian
consumer without it.

## 11. Multi-Tenancy & Security (engineering-level; full detail in SECURITY-COMPLIANCE.md)

Flat tenancy (no reseller tree — decided): Organization → Users(role: owner|staff) →
Agents → Calls/Leads/KB. tenant_id on every row; **Postgres RLS on every tenant table**
(policy: tenant_id = current_setting('app.tenant_id')); the API sets the GUC per request
from the verified session; a missing GUC yields zero rows, never all rows.
Admin realm (admin.calevate.tech) and client realm (app.calevate.tech/c/<slug>/…) are
separate route trees, separate first-party session modules, separate `__Host-` cookies and
separate deploys — and the boundary is the four mechanisms in §2's Auth bullet, not the
two vendor applications this line named before D-177. The hostname half is enforced at the
edge (`location ^~ /admin { return 404; }` on `app.`, `^~ /c/` on `admin.`), which stopped
being "worth doing" and became load-bearing the moment a `__Host-` cookie set by the API
started being sent from either hostname (AUTH-MIGRATION §3). Slugs are auto-generated,
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
