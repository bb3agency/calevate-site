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
| `voice-runtime` | FastAPI, separate deploy | The engine's signed webhooks (`/engine/{engine}`; ThinnestAI's are verified by `signed_intake.py`). No carrier routes and no in-call tool routes | **Concurrent calls; never redeployed casually; a dashboard deploy must not touch live calls** |
| `workers` | ARQ on Redis | Post-call pipeline, execution reconciliation and the engine charges sweep, recording copies, embeddings, campaign dispatch, number rental, notifications, redaction, retention jobs | Queue depth; crashes delay work, never drop calls |

Shared infra: PostgreSQL 16 (+pgvector) on the host, Redis (Compose), Cloudflare R2
object storage. Hosting (D-25 narrows D-13; D-180 chose a Hostinger India VPS): the site
stack is NOT in the live-call path — ThinnestAI hosts the whole call (numbers, telephony,
STT, LLM, TTS and recording; D-678..D-682, `docs/THINNEST-INTEGRATION.md`) — so it deploys
on a general-purpose VPS; see DEPLOYMENT.md. What a caller waits on from the VPS is the
caller lookup at call start and the in-call custom actions ThinnestAI sends to our API
(`/v1/worker/**`, `worker/engine_actions.py` and `engine_lookups.py`), which is why D-13's
co-location reasoning still binds any in-call-path service.

Module boundaries inside `api` (each owns its tables; no cross-module SQL; communicate via
service interfaces): tenancy, agents, engine, campaigns, ingest(webhooks-in), postcall,
crm, analytics, billing, kb, integrations, compliance, audit.

## 2. Stack (locked)

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic, `uv`,
  Ruff + mypy(strict) in CI. One backend language (the voice/AI ecosystem is Python-first).
- **Frontend:** Next.js 15 + TypeScript, Tailwind + shadcn/ui, TanStack Query, Recharts/
  Tremor. Typed API client generated from FastAPI OpenAPI.
- **DB:** Postgres 16 for all system-of-record data. Vector/RAG: `pgvector` inside that
  same Postgres (`kb_chunks`, D-502, which reversed D-28's managed service), serving the
  dashboard copilot and the CRM paths. In-call retrieval is ThinnestAI's own knowledge base,
  which every published source is attached to (D-689), never a network call to this store —
  TRD §6.
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
    admin 30 min idle / 8 h absolute, client 12 h idle / 14 d absolute; an operator who
    switches "Stay signed in" on for their own account gets the client bounds and a
    persistent cookie (D-766, `sessions.session_policy`). **The row is the
    authority either way, so a revoke bites immediately** — `verify_session` re-reads it on
    every request. The COOKIE is a browser-session cookie on the admin realm (unless "Stay
    signed in" is on, D-766) and, since
    D-539, carries a `max_age` on the client realm derived from that row's own
    `absolute_expires_at` (`cookies.session_cookie_max_age`) so a fourteen-day session is
    no longer ended by closing a tab. It can never ask for more time than the row has left,
    and it does not slide with the idle window.
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
> **The engine is ThinnestAI (D-678..D-682; production since 7 Oct 2026).** `ENGINE` accepts
> `thinnest` and `fake` (tests). ThinnestAI hosts the whole call — its own numbers, telephony,
> STT, LLM, TTS and recording — and `docs/THINNEST-INTEGRATION.md` is the engine's plan and
> build state. Bolna was deleted by D-639 and our own call engine by D-763; there is no
> second engine, and rollback is redeploying the previous image. Everything below that
> describes Bolna — its API, webhooks, source-IP allowlist, KB, pricing and pilot gates — is
> the record of the engine this section was written for, not an instruction: do not
> configure, call or buy from Bolna on its strength. What still binds from it is the dashboard
> AI and first post-call extraction legs of the LLM bullet, which do not run in the engine.
> do not configure, call or buy from Bolna on its strength.

Primary engine: **Bolna** (api.bolna.ai, Bearer auth; agent CRUD under /v2 — legacy
unversioned paths are deprecated, never call them; the adapter's typed models are read
from the vendor's OWN published OpenAPI 3.1 document — `references/openapi.yml` in
`bolna-ai/skills`, pinned and checksummed in `docs/vendor/bolna/hosted-oas.md` — and no
longer hand-maintained from prose, D-350). Adopted by D-31 (supersedes
D-02's ThinnestAI pick), gated on the pilot scorecard.
Models (per-agent config, BYOK):
- STT: **Sarvam Saaras V3** (22 Indian languages, streaming, code-mixed) — their docs
  supersede our original Saarika v2.5 pick [docs-verified Jul 2026]. Auto-available when
  Sarvam is the speech provider. ⚠ **An Indian vendor is not an India-processing claim**:
  Sarvam's privacy policy permits transfer to and processing in countries outside India (US
  cloud infrastructure; EU model and security vendors), and its ToS s.17.5 permits training
  on Inputs/Outputs/usage data absent a signed order form under s.6.2 — we hold none. VENDOR-PUBLISHED (Sarvam Privacy Policy "Cross-Border Data Transfers"; ToS v2.0 eff. 29 Jul 2026 ss.6.2/17.5 — read by the founder 27 Aug 2026 and relayed; `sarvam.ai` remains egress-blocked from this container). Gate A-2: compare bundled/managed Sarvam tier.
- LLM: **Azure OpenAI in East US 2 — `AZURE_LOCATION` (`eastus2`), default
  `AZURE_OPENAI_DEFAULT_MODEL` (`gpt-4o-mini`) — on BOTH LLM surfaces (D-410,
  superseding D-400/D-404 on the in-call leg and D-127 on the dashboard leg; **the region
  moved off `southindia` at D-449, 22 Aug 2026**).** One region, one allow-list, one price
  table, one builder. `gpt-4.1-mini` is a CONFIG SWITCH through `azure_openai_model`, not a
  second shipped default.

  > **THE PLATFORM'S OWN DEFAULT MOVED OFF THIS LEG ON 4 SEP 2026, AND THIS PARAGRAPH IS
  > ABOUT THE LEG RATHER THAN ABOUT THE DEFAULT.** Everything D-410 settled about the Azure
  > leg still holds. What changed is which model an account runs when neither it nor its
  > agent chose: the founder's answer is **`gemini-2.5-flash-lite`**, and it is now its own
  > setting - `Settings.platform_llm_model`, typed over all three declared legs - because the
  > platform rung used to read `azure_openai_model`, a field whose type could not hold it.
  > `AZURE_OPENAI_DEFAULT_MODEL` (`gpt-4o-mini`) keeps its two other jobs unchanged: the
  > default of `azure_openai_model` (which model the Azure DEPLOYMENT was made from) and
  > `billing/rates.BASE_RATE_LLM_MODEL`, the frozen model the plan rate is struck against - so
  > no client's bill moves and no account is re-classified. **A DEPLOYMENT CANNOT ACTUALLY
  > RUN THE NEW DEFAULT UNTIL ITS GOOGLE KEY IS INSTALLED AND ITS PRICE ATTESTED** (the Gemini
  > catalogue figures are `verified=False` - vendor-published and founder-relayed rather than
  > fetchable here - so hard rule 7 keeps them out of `unit_cost_paid`); until then an account
  > that has chosen nothing runs the ENGINE's own default and the picker marks the row
  > unavailable with its ground.

  **WHY THE REGION MOVED, AND WHAT IT COST [D-449].** Two grounds. **(a)** Bolna's
  orchestrator is US-hosted (VERIFIED-VENDOR-DOCS,
  `bolna-findings/mirror/pages/concepts/security.md:29`, AWS us-east-1), so every
  conversational turn was a us-east-1 → `southindia` → us-east-1 round trip inside the
  350 ms TTFT budget of §4 — a budget with zero measurements behind it (§4a, OPERATIONS §2
  gate 4). **(b)** Microsoft's Standard (regional) matrix does not offer `gpt-4o-mini` in
  `southindia` at all, so the residency posture and the shipped default model were in
  direct conflict (gate 20b). The recovered ocean hop is an ESTIMATE — this repo's own
  figure was ~180–230 ms, an internet estimate never measured — set against a budget
  nobody has measured, so the upside is unproved in both terms. **The cost is not**: the
  client-facing India warranty is WITHDRAWN (SECURITY-COMPLIANCE §4), the caller's words
  now leave India as they are spoken rather than only in an archived recording, and
  nothing about vendor erasure reach improves (gate 36).

  ⚠ **"SWITCH" IS TWO EDITS AND A REPUBLISH, NOT ONE TOGGLE, AND GETTING THAT WRONG IS
  SILENT.** Of the four Azure settings only `azure_openai_model` is `applies: live`, and it
  is live precisely because **nothing sends it to anybody** — it names which model the
  deployment was made from, and `billing/` reads it to price the leg.
  `azure_openai_resource` and `azure_openai_deployment` are **`live_agents`** (D-720): they
  become `ModelConfig.llm_base_url` and `ModelConfig.llm_model` inside each PUBLISHED agent
  record, so saving either republishes every live agent at once. `azure_openai_api_key` is
  `operator_step` — the dashboard leg
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
    **`provider: "azure-openai"`** — **and this said `"azure"` until the vendor's own
    documentation was read (D-417).** D-410 picked `azure` from two human-readable
    LABELS (a provider matrix reading "Azure OpenAI" and the dashboard dropdown), which
    is the wrong class of evidence for a wire value; the docs give a machine-readable one
    twice, in a copy-pasteable `llm_config` body and in the Key-settings table —
    *"`"llm_config": { "provider": "azure-openai",`"*
    (`bolna-findings/mirror/pages/providers/llm-model/azure-openai.md:20`) and
    *"| `provider` | string | `"azure-openai"` | Provider name |"* (`:59`) — and the same
    form is corroborated on every sibling page (`openai`, `anthropic`, `google`,
    `deepseek`, `openrouter`). It is still a FIRST-CLASS provider, so the `custom` route
    — whose credential path was never verified, and whose doubt is what moved this
    product (retired gate 16c) — is not used, and the docs make `custom` WORSE rather
    than better: its whole documented surface is two values, `custom_model_name` and
    `custom_model_url` (`api-reference/user/add_model.md:39-45`), with **no credential
    field anywhere** (`providers.md:111-112`), while our Azure endpoint needs
    `Authorization: Bearer` on every request. **There is no rotation cron, no dead man,
    no org policy and no 12-hour ceiling**: all of that existed because a regional Vertex
    endpoint took no static key, and it is deleted with the endpoint.
    **THE CREDENTIAL-FIELD ASSUMPTION IS CLOSED AND THE GUESS WAS WRONG (D-417).** Their doc
    HOST is still egress-blocked from this environment (403 on CONNECT, re-measured 20 Aug
    2026); what changed is that the pages were fetched elsewhere and delivered as a
    hash-manifested read-only mirror at `bolna-findings/mirror/`. Their Azure provider takes **four** flat credential entries, none of them `AZURE`:
    `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`,
    `AZURE_OPENAI_API_VERSION`, under *"All these keys **must** be added for the
    respective provider"* (`providers.md:40,96-102`). The store is flat —
    `ProviderRequest` is `{provider_name, provider_value}`
    (`api-reference/providers/add.md:55-68`) — so four keys means four `POST /providers`
    calls, not one. `Settings.bolna_llm_credential_name` now defaults to
    `AZURE_OPENAI_API_KEY` (`applies: live`), because a documented name and a live
    account's actual name are still different claims. ⚠ ONE HALF STAYS OPEN AND IT GOT
    SHARPER: `AZURE_OPENAI_API_VERSION` contradicts the v1-surface premise above, and the
    vendor contradicts itself about it — `providers.md:40` says all four are mandatory,
    while `providers/llm-model/azure-openai.md:32` describes the same connection as three
    things (*"your Azure endpoint URL, API key, and deployment name"*). Vestigial /
    classic-surface / required-but-unvalidated all survive the pages; **no value is
    invented here and none is in the code** — OPERATIONS §2 gate 16f.
  - **Dashboard AI** (user-triggered, over the REDACTED copy) — **Gemini is the main
    model** (founder, 27 Oct 2026, D-899): Pip and the dashboard assists run the platform's
    Gemini leg (`copilot_fast_model` / `copilot_planning_model`, `agents/assist_leg.py`) for
    every account whose own leg cannot serve, behind the Google dashboard data-use
    attestation; this Azure resource is an optional rung used only when configured and
    Gemini cannot serve; Sarvam is the disclosed last resort. An unpriced Pip Gemini model is
    never called and the other, priced one answers instead; only when no Pip Gemini model
    can serve is `assistant_gemini_unavailable` raised. Every rule D-127 wrote (G-1..G-7: redaction before the call,
    no raw PII, the disclosed Sarvam fallback) is unchanged and now binds Azure, except
    for Pip after the account owner turns it on (D-788): its primary model then receives
    what is typed, attached and read by its tools unmasked; the standby stays masked.
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
  except through `azure_openai_base_url()`, and that builder cannot emit a region other
  than the declared posture's. The rest is **attested by a human**: that the resource is in
  East US 2 (OPERATIONS §2 gate 20) and that its deployment is **Regional Standard and NOT
  Global** (gate 20c). Global is Azure's DEFAULT deployment type and processes worldwide; a
  Global deployment passes every automated check in this tree and makes the region named in
  the DPA unenforceable. Regional costs roughly 5–10% more (published examples to +12% and
  +20%), which is a payable cost of the posture rather than an accident — **since D-449 that
  premium buys an accurate sub-processor disclosure and the only enforceable property the
  posture still has, not an India warranty**. All four gates SURVIVE the region move
  re-aimed; none of them retires, because the posture still pins one region and is still
  Regional Standard. The REGIONAL hostname form `eastus2.api.cognitive.microsoft.com` would
  restore the AST proof and is rejected FOR NOW because the v1 surface is documented only on
  the custom-subdomain form — gate 20d is what reopens it, and it matters more than it did,
  the pinned region now being the only residency-shaped statement left. **What is NOT claimed**: which model extracts or converses
  BETTER in Telugu code-mixed function-calling is still unmeasured and still blocked on a
  Sarvam key and egress (§7's golden-transcript fixtures); D-410 is a residency, delivery
  and billing decision and does not claim a quality one. **NO VENDOR RETIREMENT DATE IS
  RUNNING AGAINST THIS PRODUCT** — BRD R-04's 16 Oct 2026 died with the Gemini model, the
  date-carrying constant and the test that turned CI red thirty days out (D-410). Sarvam's
  **rate limits (60/200/1,000 rpm by plan) are a concurrency input**, not a price input,
  and Azure's TPM/RPM quota in `eastus2` is a fourth such input — size both at pilot
  gates 13 and 20b. LLM id is a config string on the agent, so changing it is a config
  edit plus a regression run.
- Voices on ThinnestAI (D-687, D-688): **Clear** is ThinnestAI's own stack end to end, in
  the band the console setting `thinnest_clear_voice_band` names (Studio by default, D-792, or Premium);
  **Studio** is Cartesia on our key through ThinnestAI's voice-only BYOK (`scope: "voice"`),
  with ThinnestAI's STT, LLM and telephony. Every agent names its `byok` scope outright
  (`off` for Clear, `voice` for Studio; `llm` and `llm_voice` once our own model is switched
  on, D-764/D-834), never the `workspace` default (`engine/thinnest._byok_value`). Detail:
  THINNEST-INTEGRATION §4a-§4b; prices: §10.0 and BRD §6.
- Telephony on ThinnestAI: its own numbers and carrier carry every call. A client buys
  numbers in its own business name, in its own ThinnestAI customer workspace, once its KYC is
  verified and its business details are approved (D-693). Outbound needs a verified KYC
  record and an accepted no-cold-calls pledge, not DLT (D-692); inbound is never gated.
  Dispatch is held to the console-managed `thinnest_max_concurrent_calls`
  (`engine/dial_lines.py`). The recording is ThinnestAI's `recording.url`, copied into our
  object store (`engine/recording_source.py`).
- Embeddings: `text-embedding-3-small` on the existing Azure OpenAI resource (D-502, §6),
  for the dashboard and CRM stores only. The model and width are recorded per chunk
  (`kb_chunks.embed_model` / `embed_dim`), so a model change is a re-embed sweep, never a
  crisis.

No fallback engine is designated. Engine risk is carried by the VoiceEngine adapter contract
itself: normalized schemas and the conformance suite (`thinnest` + `fake` adapters) keep a
future second adapter cheap to add (BRD R-02).

## 4. Latency Budget (the governing constraint)

> **WHAT IS MEASURED NOW (D-770, 14 Oct 2026; D-902, 27 Oct 2026).** ThinnestAI hosts the
> whole call. The stage budget below is not checked against anything and its code is gone: `LatencyBudget`, the per-stage constants and `GET /v1/ops/engine-latency`
> were removed with the Pipecat loop that fed them (D-763), and `call_engine_latency` has no
> writer (it stays until its drop migration, hard rule 8). What the platform DOES report,
> once per call, is `quality` on `call.completed`, `call.analysed` and Get Call:
> `responseMs` (caller falls silent → the agent's first audio) and `firstTokenMs` (the turn
> reaching the platform → the first speakable word, not from speech end; §25.0 of
> `docs/vendor/thinnest-replies-2026-10-12.md`), each as median/p90/max, plus long silences, interruptions, model errors
> and rescues; and a live `call.problem` of kind `slow_reply` when a reply takes more than
> 5 s to start (VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-13/pages/
> api-reference/calls/get-call.md:300-307,327-335,984-1080`). We store it on
> `calls.engine_quality` (D-736) and `call_engine_signals`. Since 27 Oct 2026 `quality` also
> carries `answerMs` (caller falls silent → the first word of the actual answer; a filler or
> acknowledgement does not end it), which is THE reply time everywhere (D-902), and
> `responseMs` is shown as the first sound. Per-turn stage timings now exist too: Get Call
> Timeline (`VoiceEngine.get_call_timeline`, kept on `calls.engine_timeline` by
> `workers/call_timeline`) splits each turn into the wait before the decision, the
> recogniser, Ear's check, the model's first sentence and the voice (D-902, D-911); a call's
> timeline is final once Get Call's `quality.turns` is set (D-924). THINNEST-INTEGRATION
> Status (D-901, D-902, D-903, D-924) holds the vendor's reading of each stage.
>
> **The targets are `reply_time_typical_target_ms` and `reply_time_slow_target_ms`**
> (console settings, defaults **1,600 ms** and **2,200 ms**, the founder's targets of 27 Oct
> 2026, D-896, replacing the 500 ms goal of 27 Aug 2026 that the model's ~1 s first word alone
> cannot meet). The typical figure is judged against the first; a call is over target when its
> own p90 `answerMs` exceeds the second (more than one reply in ten waited longer); a call
> with no `answerMs` is not measured, never zero. Every
> figure is also split by the voice settings each call ran on (`calls.voice_settings`). The
> admin **Voice response time** screen (`/admin/ops/reply-times`, `GET /v1/ops/reply-times`,
> `apps/api/ops/reply_times.py`) reports it across every client: per window (1/7/30/90
> days) the calls measured, the median of the calls' own median reply, the 90th percentile
> of the calls' own p90 (withheld below ten calls), the model's first word, calls over target,
> slow-reply problems, model errors, rescues, interruptions and long silences, broken down
> by client, agent, Clear/Studio rung and IST day, with the slowest calls listed. The
> healer counts a call as slow when its p90 reply passes 2.5 s or it raised `slow_reply`.
> `answerMs` is measured inside the platform, not in the caller's ear, so it is still not
> the stopwatch figure gate 4 asks for.
>
> Everything from here to §5 is the **Bolna/Pipecat-era stage budget**, kept as the record
> of the reasoning behind the 500 ms goal; it describes no code that still exists.

**Voice-to-voice target: p50 ≤ 500ms** — from the caller finishing their sentence to
hearing the reply begin. Set by the founder on 27 Aug 2026; it replaces "p50 ≤ 1.1s, p95 ≤
1.8s", which this section called *"an honest target for a cascade pipeline"* while calling
sub-800ms *"aspirational, achieved by masking not magic"*. **That sentence is withdrawn as
a description of what we now promise, and it is not replaced by a claim that 500ms is
reachable.** What is true after this change is narrower and is the whole of §4:

> **THE DECLARED BUDGET DOES NOT FIT INSIDE THE TARGET, AND NOTHING IN THIS SECTION
> PRETENDS OTHERWISE.** Allocating every stage at the FASTEST figure its own vendor
> publishes, the pipeline floors at **600ms** against a 500ms target — a **100ms shortfall
> before any stage misses its own best case**. `calevate_shared.engine.
> latency_budget_composes()` returned **False** and `voice_to_voice_gap_ms()` **+100**, and
> the former `GET /v1/ops/engine-latency` shipped the shortfall on every report (both
> removed by D-770). §4b lists what would have to change; the target
> was NOT relaxed to make the arithmetic work, which is the one response the founder ruled
> out.

**p95 ≤ 800ms — PROVISIONAL, set by this session and not by the founder.** One number was
set (500ms, the typical reply); a p95 at or below a p50 is incoherent and the budget object
has the field, so a figure had to be written. It rests on nothing measured and nothing
published: do not build an argument on it, and replace it the moment a tail is set.

### The stages, and the evidence each figure came from

Every allocation below is a FLOOR: the fastest number the responsible vendor prints for
that stage, read this session at the cited page and line. That is deliberate — a budget cut
to fit 500ms would prove nothing, while a budget at the vendors' own floors makes the
shortfall an argument about physics and configuration rather than about our ambition.

| Stage | Budget | Evidence for the floor | Class |
|---|---|---|---|
| **Endpointing** (deciding the caller stopped) | 100ms | *"Decrease toward 100ms for fast-paced sales scripts"* — `bolna-findings/mirror/pages/concepts/latency.md:48`; the stage itself is `:17-29` (*"Endpointing (50–300ms)"*) | VERIFIED-VENDOR-DOCS (27 Aug 2026) |
| **STT finalization** | 70ms | Sarvam's own *"~70ms matches Sarvam STT processing latency"* — `sarvamai/skills`, `voice-agents/SKILL.md:57` (raw.githubusercontent, 27 Aug 2026); inside the engine's *"Transcription (50–150ms)"* (`latency.md:24`, `:54`) | VENDOR-PUBLISHED |
| **LLM TTFT** | 150ms | *"OpenAI gpt-4.1-mini \| ~150ms"* — `latency.md:66`; stage range *"LLM first token (100–400ms)"* (`:24`) | VERIFIED-VENDOR-DOCS, **but see the Azure caveat below** |
| **TTS TTFA** (streaming) | 80ms | Floor of *"Synthesis first chunk (80–200ms)"* — `latency.md:24` | VERIFIED-VENDOR-DOCS for the STAGE; **UNVERIFIED for Sarvam** |
| **Retrieval** (§6) | 100ms | Ours. No vendor bounds it; the in-call RAG endpoint is ours and uninstrumented | TARGET — unmeasured |
| **India → US → India transit** | 100ms | *"A caller in India connecting to a US-hosted telephony provider adds ~100–200ms round-trip"* — `latency.md:95` | VERIFIED-VENDOR-DOCS |
| **= floor for one reply** | **600ms** | 100 + (70 + 150 + 80) + 100 + 100, derived in code, never re-typed | |

The prompt discipline that protects the LLM leg is unchanged and matters more at 150ms than
it did at 350ms: a short system prompt (hot facts only, catalog to RAG; the ~2.5k budget in
PROMPT-GUIDE §2 stands regardless of engine), because *"Larger prompts increase TTFT"*
(Microsoft, `azure-ai-docs` `articles/foundry/openai/includes/how-to-latency-content.md:110`)
and a bloated prompt raises TTFT and hallucination together.

### Three findings that change how every number above should be read

**1. THE BUDGET WAS MISSING A STAGE, AND THAT IS THE MOST IMPORTANT THING IN THIS SECTION.**
§4 measured from "the caller finishing their sentence" and then budgeted four stages, none
of which is the wait that DETECTS the finishing. The engine's own stage diagram opens with
it and says time-to-first-audio is *"the total of these stages"*
(`concepts/latency.md:17-31`). A budget that omits a stage is not a budget: it was silently
charging endpointing to the 50ms of headroom the old target left. **And the omitted stage is
the largest single term in the overrun**: we send neither knob, so every published agent
inherits `transcriber.endpointing` = **250ms** and `incremental_delay` = **400ms** (the
*"linear delay to add before speaking everytime we get a partial transcript from ASR"*) —
`api-reference/agent/v2/create.md:1055-1058` and `:418-427`, matching the console's own
recommendation of *"Endpointing around 200-300ms and Linear Delay around 400-500ms"*
(`agent-setup/engine-tab.md:56,64`). **650ms of waiting, against a 100ms budget, before the
pipeline starts.** ⚠ Whether `incremental_delay` adds on every turn or only on partial
transcripts is UNVERIFIED — two vendor pages disagree by omission — and gate 4 settles it
with a stopwatch, not from a document.

**2. BYOK PINS US TO US SERVERS, SO THE OCEAN CROSSING IS NOT OPTIONAL.** Indian-server
routing has five requirements and the fifth is *"Use Bolna's default provider integrations.
Do not connect your own API keys"*, with the consequence stated: *"If you connect your own
API keys for any provider (transcriber, synthesizer, or LLM), calls will automatically route
through US servers regardless of other configuration settings"*
(`enterprise/indian-server-configuration.md:63-69`). This product is BYOK by construction,
so every call is processed in `us-east-1` (`concepts/security.md:29`) and the caller's audio
crosses the ocean on every turn. It was previously hidden inside "headroom"; it is now
declared (`INDIA_US_TRANSIT_FLOOR_MS`) because a cost that is on every turn and cannot be
opted out of is part of the budget, not part of the slack.

**3. THE LLM FIGURE IS THE ENGINE'S, FOR A LEG WE DO NOT RUN.** ~150ms is Bolna's published
typical TTFT for **OpenAI direct**. We run **Azure OpenAI in `eastus2`**, and **Microsoft
publishes no per-model TTFT at all**: their latency article gives the formula `TTLT = TTFT +
(TBT × Tokens Generated)` and a metrics catalogue, and its only model-choice guidance is
*"If your use case requires the lowest latency models ... we recommend the latest GPT-4o mini
model"* — with no number anywhere on the page (`MicrosoftDocs/azure-ai-docs@d002f330`,
`articles/foundry/openai/includes/how-to-latency-content.md:88,151`, `ms.date` 05/14/2026,
read 27 Aug 2026). The same page names a cost we have not quantified: *"The addition of
content filtering comes with an increase in safety, but also latency"* (`:191`). So the LLM
leg's floor is **UNVERIFIED on the leg we actually run**, and the direction of the error is
unknown.

### Techniques: what is required, and what is actually implemented

Checked in the code this session rather than recalled:

* **Streaming end-to-end — IMPLEMENTED.** The agent payload sends `synthesizer.stream: true`
  and `transcriber.stream: true` (`apps/api/engine/bolna.py`), and the engine starts
  synthesising *"as soon as the LLM emits the first sentence"* (`latency.md:77`). There is
  no further latency to buy here: it is already on.
* **Filler utterances at tool-call start — IMPLEMENTED.** `actions.pre_call_message` is
  stored per tool and sent as the vendor's `pre_call_message` on each custom function
  (`apps/api/engine/bolna.py:791-792`). It masks the external round trip; it does NOT mask
  the per-turn pipeline, which is what the 500ms target is about.
* **Brief agent replies enforced in prompt — unchanged**, and `max_tokens` is set explicitly
  per model rather than inherited (`_llm_trap_settings`), which Microsoft names as a latency
  lever (*"Set the `max_tokens` parameter on each call as low as possible"*, `:169` region of
  the same article).
* **The shortest network path the declared posture allows — done, and spent.** D-449 moved
  the language leg to `eastus2` beside the orchestrator precisely to delete a
  us-east-1 → `southindia` → us-east-1 round trip inside the TTFT budget; the India residency
  claim was WITHDRAWN to buy it, not narrowed. What that did NOT buy back is finding 2's
  crossing, which is the CALLER's, not the model's.
* **`synthesizer.buffer_size` — NOT set, and inherited at double the vendor's own advice**:
  `default: 250` (`create.md:654-657`) against *"A buffer of 100–150 characters is typical"*
  and *"Smaller buffers start audio sooner"* (`latency.md:89`).

**The measurement mechanism existed for three of the stages until D-770.** `stt_ms`,
`llm_ttft_ms` and `tts_ttfa_ms` were captured per TURN in `call_engine_latency.turns` and
reported by the former `GET /v1/ops/engine-latency`; nothing has written that table since
Pipecat left (D-763), and the per-call reply time above replaced the report. **No mechanism exists
for endpointing or retrieval**: the engine reports no endpointing figure (the wait is inside
`time_to_first_audio` and outside `audio_to_text_latency`, which starts at audio in), and the
in-call RAG endpoint is ours and uninstrumented. `calls.latency` was DROPPED (migration
`f1a7c39d5be2`): a column that always reads NULL is worse than none, because the next reader
builds a dashboard on it.

**Bolna documents per-component latency** (`latency_data` on Get Execution:
`time_to_first_audio` plus transcriber/llm/synthesizer blocks) — but it is UNVERIFIED against
a live account, it is a DIFFERENT set of numbers from voice-to-voice (which would be our own
arithmetic aligning three components), and its documented `transcriber.turns` entries carry
recognised TEXT, which a naive mapper would land in a column with no redacted counterpart
(hard rules 5/6). So it is captured as a fixture at OPERATIONS §2 gate 4, beside the
stopwatch that can falsify it — no latency work without measurement, and no measurement
invented to fill the gap.

### 4a. Where the measured numbers replace the targets (gate 4's landing zone)

**Every number in §4 above is a TARGET and we hold zero measurements.** This block is the
only place a measured number may be written in, and it names the slots so a later reader can
tell at a glance which figures above have been earned. Nothing here is filled in yet.

| §4 figure | status | replaced by | source |
|---|---|---|---|
| voice-to-voice p50 ≤ 500ms | TARGET — unmeasured, and **not reachable by the declared budget** (see the gap above) | median + its 97.9% order-statistic interval | gate 4 stopwatch/recording, via `scripts/pilot/latency.py` |
| voice-to-voice p95 ≤ 800ms | **PROVISIONAL — set by this session, not by the founder**, and not confirmable at n=10 (see below) | a founder decision first; then exceedance count + exact binomial bound | same |
| first-greeting delay after pickup | TARGET absent (no figure has ever been set) | its own distribution, kept separate from turn latency | same |
| endpointing ≤100ms | TARGET — unmeasured, **and no mechanism measures it**; the shipped config waits 650ms | a stopwatch against two agents, one per `endpointing`/`incremental_delay` setting | gate 4 |
| STT ≤70ms · LLM TTFT ≤150ms · TTS TTFA ≤80ms | TARGETS — unmeasured | `latency_data` transcriber/llm/synthesizer per turn | Get Execution capture, gate 4 |
| retrieval ≤100ms (§6) | TARGET — unmeasured | out of gate 4's scope | TRD §6 bake-off |
| India→US transit ≥100ms | VENDOR-PUBLISHED range (100–200ms), floor taken | the difference between a `region: in` run and a `region: us` run | gate 4, grouped by `region` |
| TTS TTFA floor for **Sarvam** | **UNVERIFIED** — `docs.sarvam.ai` and `www.sarvam.ai` are egress-blocked here (403 on CONNECT, 27 Aug 2026) | Sarvam's own published streaming TTFB, or our own measurement | whoever can reach the host, or gate 4 |
| LLM TTFT floor on **Azure** | **UNVERIFIED** — Microsoft publishes no per-model TTFT, and content filtering adds an unquantified increment | `AzureOpenAITimeToResponse` in Azure Monitor on our own deployment | ops, once the deployment exists |

Findings from building the harness and from the 27 Aug 2026 re-budget, recorded here because
they change how the figures above should be read:

1. **Voice-to-voice latency is not measurable from our side.** Both ends of the interval sit
   on the caller's PSTN leg and our stack is not in the audio path (D-25). It is a human with
   a stopwatch or an offset read off a recording; only `latency_data` is an automatic
   capture, and it is a different quantity. The harness is a ledger and a comparator, not a
   measuring instrument.
2. **Ten calls cannot confirm the tail leg of gate 4.** "p95 ≤ T" is "P(turn > T) ≤ 5%"; ten
   clean samples bound that at 25.9% (exact binomial, 95% one-sided), and confirming it needs
   **n ≥ 59** clean samples. Ten calls CAN refute it and CAN answer the p50 leg. So gate 4 at
   ten calls has three honest outcomes — PASS, FAIL, INCONCLUSIVE — and INCONCLUSIVE is the
   expected one.
3. **`latency_data` justifies no column until the agreement finding lands.** The storage
   shape it would justify — and the reason a JSONB blob on `calls` is not it — is written out
   in `STORAGE_SHAPE_FINDING` in `scripts/pilot/latency.py`.
4. **A budget that omits a stage is not a budget** (§4 finding 1). The four sub-budgets never
   contained endpointing, so every reading of "we are within budget" for the last several
   months would have been a reading against a pipeline missing its longest configurable wait.
   Endpointing is now a declared leaf and part of `PIPELINE_BUDGET_MS`.
5. **The vendor's own example is not self-consistent, so `time_to_first_audio` cannot yet be
   used to check this budget.** `call-latencies.md:22-31` shows `time_to_first_audio: 130.84`
   on an execution whose own LLM block reports `time_to_first_token: 1633.04` (`:99`) — a
   total smaller than one of its parts. Until gate 4 captures a real payload, treat the
   field's DEFINITION (`:37`) as documented and its worked VALUES as illustrative.

### 4b. What would have to change to reach 500ms (evaluated from evidence, ranked by what it buys)

Nothing below is scheduled; each entry says what it buys and on what evidence, or says that
the figure is unknown. Two of them are configuration and could be done in an hour; the rest
are decisions with prices attached.

1. **Set `transcriber.endpointing` and `incremental_delay` explicitly — buys up to ~550ms,
   and it is two integers.** Today: 250 + 400 inherited (`create.md:1055-1058`, `:418-427`).
   The vendor's own floor for endpointing is 100ms (`latency.md:48`) and their console's
   fast preset is 200–300 (`engine-tab.md:64`). ⚠ **The price is barge-in behaviour on
   Telugu telephone speech, and the same page warns our exact population the other way**
   (*"Increase to 400–500ms for callers who pause mid-sentence (non-native speakers,
   elderly)"*). This is the largest single term in the gap and the only one that is ours to
   set — and it moves what every caller HEARS, so it moves on gate 4's stopwatch, never on a
   document audit.
2. **Lower `synthesizer.buffer_size` from the inherited 250 toward 100–150 — buys an
   unquantified part of the TTS leg.** *"Smaller buffers start audio sooner"*, *"A buffer of
   100–150 characters is typical"* (`latency.md:89`); the schema default is 250
   (`create.md:654-657`), roughly double the vendor's own advice. **The figure it buys is
   UNKNOWN** — no page quantifies it — and the price is choppy speech if the synthesiser is
   slow to respond.
3. **Give up BYOK on the speech/LLM providers and take the vendor's own integrations — buys
   up to the 100–200ms crossing** (`latency.md:95`) by making Indian-server routing
   available (`indian-server-configuration.md:63-69`). **The price is the entire BYOK
   posture**: our vendor accounts, our rate card, D-410/D-449's model control and the
   deployment-level retirement control `scripts/check_model_lifecycle.py` consumes. It also
   requires one named telephony provider and one of their supported provider sets. Evaluated and NOT
   recommended here; recorded because it is the only documented way to delete the crossing
   while staying on this engine.
4. **A faster language model — buys an UNKNOWN amount, and possibly nothing.** The engine's
   own table puts `gpt-4.1-mini` and `gemini-2.5-flash` at ~150ms and `gpt-4.1` at ~200ms
   (`latency.md:64-69`), i.e. the spread across the models we offer is ~50ms, and none of
   those figures is for Azure. Microsoft's only advice is to prefer GPT-4o mini, unnumbered
   (`how-to-latency-content.md:151`). **This is the lever most people reach for first and the
   evidence says it is worth less than the endpointing knob by an order of magnitude.**
5. **A different speech vendor — buys an UNKNOWN amount and costs the product.** The vendor
   names *"ElevenLabs Turbo and Cartesia"* as lowest-latency TTS and *"Deepgram Nova-3"* as
   fastest STT (`latency.md:56,89`), but their Indian-language coverage is why we are on
   Sarvam at all (`concepts/choosing-providers.md:21-22` puts Sarvam against Indian
   languages), and Telugu is the product. No figure for Sarvam is readable from here, so the
   size of the trade is unknown in BOTH directions.
6. **Speculative start on partial transcripts — UNSUPPORTED BY THIS ENGINE, as far as the
   docs go.** The engine exposes `incremental_delay` (wait longer on partials) and no
   documented way to start the LLM on a partial and cancel it. **UNVERIFIED**: absence from
   335 mirrored pages is not proof of absence in the API. It is also the technique whose
   failure mode is the agent answering a question the caller had not finished asking.
7. **Leave the rented engine (self-orchestration, TRD §10.5) — buys the architecture, not a
   number.** It is the only route that puts endpointing, model choice, co-location and
   speculative execution under our control at once. Its numeric triggers are already written
   in TRD §10 and none of them is latency; nothing here changes that, and nothing here
   justifies it either.

**What NONE of these buys is a guarantee.** Even taking the two configuration wins in full,
the floor-allocated pipeline (600ms) exceeds the target (500ms), and every leg in it is
already the fastest figure its vendor publishes. **The honest statement to a client is that
500ms voice-to-voice is not achievable on this pipeline as specified**; what gate 4 can
establish is what IS achievable, measured, and that number does not exist yet.

## 5. VoiceEngine Adapter (the portability contract)

> **The engine is ThinnestAI (D-678; `apps/api/engine/thinnest.py`).** `ENGINE` accepts
> `thinnest` and `fake`; `docs/THINNEST-INTEGRATION.md` §2 maps this protocol onto
> ThinnestAI's API method by method. Bolna was deleted by D-639 and our own call engine,
> with its carrier seam, by D-763. Everything below that describes Bolna — its API,
> webhooks, source-IP allowlist, KB, pricing and pilot gates — is the record of the engine
> this section was written for, not an instruction: do not configure, call or buy from Bolna
> on its strength.

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
    async def get_call_timeline(self, call_id: str) -> CallTimeline | None   # per-turn
        # timings (D-902): None when the engine holds none for the call; the caller decides
        # when None is final (on ThinnestAI, once Get Call's quality.turns is set, D-924)
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

One property here genuinely needs a vendor account and is still open:
whether `POST /v2/agent` honours an idempotency key.
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
  **API rate limits ARE published and this line used to say they were not**: 500
  requests/minute each on `/call`, `/v2/agent/{id}` and `/v2/agent/{id}/executions`,
  1000/min default elsewhere, counted **per ORGANIZATION** (shared across every user in
  it) with a 429 on breach — `bolna-findings/mirror/pages/api-reference/rate-limiting.md:18-27`.
  Dispatch PACING is a different quantity and is still unpublished (pilot): the rate
  limit bounds our request rate, not how fast the platform will actually dial.
- **Execution payload** (polling and webhooks share one shape — GET /executions/{id}):
  **SIXTEEN-value status enum — this said fifteen, and the missing one had a real call
  attached.** `api-reference/errors.md:41-56` enumerates them, including
  `prepared` — *"Execution record created and validated (recipient number, from/to number
  assigned) but not yet handed off to the dial queue"* (`:42`) — which our adapter's
  unmapped default scored as `failed`, i.e. terminal, on a call the vendor had accepted
  and was about to dial. Terminal = {completed, no-answer, busy, failed, canceled,
  stopped, error, balance-low}; `call-disconnected` is **soft** terminal and the vendor
  says so in a warning of its own (`errors.md:57-59`). **total_cost / recording_url / extracted_data populate
  only at `completed` (~2–3 min after disconnect)** — the post-call pipeline triggers
  on `completed`, never on `call-disconnected`. Costs arrive in **USD cents** with
  breakdown {platform, network, llm, synthesizer, transcriber} — the adapter converts
  to INR at capture and stamps the fx rate into usage_events.meta (hard rule 7).
  Transcript is prefix-tagged plain text (`assistant:`/`user:`) — the adapter parses
  it into TranscriptTurn, so `TranscriptTurn.start_ms`/`end_ms` are NULL for every Bolna
  turn and no turn latency is derivable from what we ingest. Their docs DO describe a
  `latency_data` object on Get Execution — unverified against a live account, and a
  pilot gate 4 capture rather than an adapter field (see §4).
- **Webhooks — UNSIGNED; delivery guarantee UNSETTLED** [this line said "at-most-once"
  and cited the OSS delivery code — a single aiohttp POST, no retry, errors swallowed —
  which is a *different program* from the hosted deliverer (D-352). The skills repo says
  the hosted platform "retries on non-2xx"; the vendor's own hosted webhook page
  (`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`) says
  **nothing at all** about retries, signing or guarantees. So the retry claim rests on one
  first-party source and is not corroborated — treat delivery as lossy in both
  directions]: per-agent webhook_url in agent_config; fires on status transitions
  (scheduled → queued → in-progress → completed); pre-call webhooks from tools share the
  shape — and a tool that sets `pre_call_webhook_param` with no `pre_call_webhook_url`
  of its own delivers its **in-progress** pre-call webhook to THIS url
  (`bolna-findings/mirror/pages/tool-calling/custom-function-calls.md:268,749`), which is why the dedupe key
  below is the pair and not the id. Since 7 Jul 2026 the set of transitions is
  FILTERABLE — *"choose which call statuses trigger your webhook… By default, **all
  statuses** are sent"* (`changelog/july-2026.md:119-125`) — an unused lever, recorded
  because we receive every transition and drop most.
  No delivery history, no replay tooling. Authenticity = **source-IP allowlist
  (13.203.39.153, 13.126.9.249, 13.202.133.53 — THREE addresses; this said one until
  D-414, and the allowlist fails safe, so two of three senders were being rejected)
  enforced IN-APP, and there only** (nginx does D-27 real_ip restoration and no `allow`;
  SECURITY-COMPLIANCE §5 carries why the edge layer is declined rather than pending),
  plus dedupe on the **(execution_id, status) PAIR** — never on execution_id alone, or the
  `completed` transition is discarded as a duplicate of `queued` (D-352); webhook payloads
  are treated as hints — the authenticated Get Execution fetch is the truth. Consequently
  the **10-min List-Executions reconciliation poller (FLOWS §3) is the guarantee of
  record**, not a safety net. Empirical delivery behavior re-tested at pilot.
- **Recordings — BOTH HALVES OF THIS LINE EXPIRED ON 1 JUNE 2026 AND IT USED TO SAY
  "direct S3 URL (us-east-1), no documented expiry".** The vendor retired the raw S3
  shape in a dated breaking change: *"Direct Amazon S3 recording URLs will stop working
  after **June 1, 2026**"* (`bolna-findings/mirror/pages/changelog/may-2026.md:91`),
  replaced by `https://api.bolna.ai/recordings/call/{execution-id}` (`:99`, plus a
  `…/recordings/transfer/…` variant for a transfer leg), and *"The **resolved pre-signed
  link it returns expires after 24 hours** — do not store or cache it"* (`:118`). **The
  change passed without touching us, and copy-first is why**: nothing in this tree parses,
  stores or re-uses a vendor URL — `storage._fetch_recording` walks the redirect itself
  and `calls.recording_url` holds OUR object key — so the vendor's 24-hour window only has
  to outlive one fetch. The recording copy starts FIRST in the pipeline and runs beside the
  lead stages (our storage is system of record; every stage after the lead waits for it),
  and the 24h ceiling is now a real bound on
  `recording_copy_failed`'s recovery window. Vendor-side retention + deletion API still
  undocumented — *"contact support for retention policy"* (`concepts/security.md`) — so
  the erasure certificate keeps reporting engine-side deletion as
  `unconfirmed_pending_vendor_api` (pilot; DPDP erasure — SEC-COMP §4 — depends on it).
- **Residency — the option is real, it is Enterprise-gated, and OUR OWN ARCHITECTURE
  FORECLOSES IT (D-415); this line used to offer it as the answer for BFSI-adjacent
  clients and it is not one.** Default is the United States for EVERYTHING, not just
  storage: *"By default, all Bolna AI services operate in United States (US)-hosted
  infrastructure"* (`enterprise/data-residency.md:12`), *"By default, Bolna processes
  calls on infrastructure in the US (AWS us-east-1)"* (`concepts/security.md:29`). India
  residency stores audio, transcripts, logs and configurations in India and runs *"All
  inference, transcription, and response generation … within Indian borders"* on
  `ap-south-1` — **but its requirements exclude BYOK**: *"Use Bolna's default provider
  integrations. Do not connect your own API keys for the transcriber, synthesizer, or LLM
  providers"*, and *"If you connect your own API keys for any provider … calls will
  automatically route through US servers regardless of other configuration settings"*
  (`enterprise/indian-server-configuration.md:65,68`). BYOK on all three legs is what this
  product IS (D-31/D-36/D-410), so buying residency today would move **zero calls**, and
  its Indian-server routing names a single telephony provider — the 140-series promotional half of the
  business dialled through another carrier. What survived that correction was narrower and was still worth
  having: the MODEL legs stayed Indian (Sarvam sovereign by vendor; Azure OpenAI pinned to
  South India by gates 20/20b/20c), so the inference did not leave the country while the
  orchestration did. **D-449 WITHDREW THE LANGUAGE HALF OF THAT** — Azure OpenAI is
  `eastus2`, so the transcript reaches a US model on every turn. ⚠ **AND ON 27 AUG 2026 THE
  SPEECH HALF WENT TOO.** This line read *"only the SPEECH legs remain Indian"*. Sarvam is an
  Indian COMPANY; its own privacy policy says personal data *"may be transferred to and
  processed in countries outside India"*, naming US cloud infrastructure (AWS/GCP/Azure) and
  EU model and security vendors, and its India-storage carve-out covers voice biometric data
  in Content Studio and payment data rather than Saaras API traffic. So no leg of this
  product carries an India-processing claim any more; what remains Indian is the application
  host. VENDOR-PUBLISHED (Sarvam Privacy Policy "Cross-Border Data Transfers"; ToS v2.0 eff. 29 Jul 2026 ss.6.2/17.5 — read by the founder 27 Aug 2026 and relayed; `sarvam.ai` remains egress-blocked from this container). The gates survive re-aimed; the claim does not. The fork — accept US orchestration and say so in the DPA, or move to their
  integrations and lose BYOK — is gates 9 and 12, laid out in
  `docs/evidence/bolna-compliance-residency.md` §5. SEC-COMP §4's cross-border row is the
  client-facing statement of the same fact.
- **Multi-tenancy**: Enterprise **sub-accounts** — CRUD + per-sub-account usage APIs,
  auto-provisioned `sa-` API keys (org-admin controlled); isolates agents + call logs;
  phone numbers, providers and billing stay org-level (consolidated). Tenant ↔
  sub-account mapping lives in OUR db (D-16's reasoning unchanged); per-tenant
  metering derives from our usage_events, never their billing. **Since 29 Jun 2026 the
  platform also enforces per-account concurrency** — `min_concurrency` ("Guaranteed floor
  for the account") and `max_concurrency` ("Hard cap … Omit (or `null`) for **elastic** …
  `0` **pauses** the account"), org-admin only (`enterprise/concurrency-management.md:42-43,119`)
  — which is the thing `campaign_dispatch` reimplements in SQL. Adopting it is a founder
  decision with a compliance edge (a vendor-side queue we cannot DNC-scrub), not a
  refactor; gate 13.
- **Campaign built-ins** (configure, don't rebuild): batch APIs with per-contact retry
  on outcome (no-answer/busy/failed/error/voicemail, ≤3 attempts, spaced delays).
  **THE MECHANICS ARE PUBLISHED NOW AND THEY ARGUE AGAINST ADOPTING BATCHES, WHICH IS WHY
  `campaign_dispatch` DIALS PER CONTACT THROUGH `POST /call`.** A batch is a CSV upload
  (`contact_number` required, E.164 — `api-reference/batches/create.md:19`), started by
  `POST /batches/{id}/schedule`, and the only lever once it runs is
  `POST /batches/{id}/stop`, which answers *"Batch is not queued or running"* otherwise
  (`batches/stop.md:59`). So a per-contact DNC withdrawal mid-batch can only be honoured
  by stopping the WHOLE batch — a hard-rule-5 argument, not a preference. Two sharp edges
  we would inherit: the start time takes a **numeric UTC offset** (`Z` is rejected with a
  500) and Bolna **rounds the start up to the next 10-minute mark**, silently moving a
  window we told a client about (`batches/create.md:57`). Batch `status` is a DIFFERENT
  enum from execution status (`created → scheduled → running → completed`, plus `stopped`
  / `failed` — `batches/get_batch.md:79-87`); both are called "status" and neither maps to
  `CallStatus`. Built-in KB: rag_id CRUD
  API (POST /knowledgebase, GET /knowledgebase/all, GET|DELETE /knowledgebase/{rag_id}),
  multiple KBs per agent (`api-reference/knowledgebase/overview.md:7`); the dashboard
  label for multilingual mode names Hindi/Tamil while the API claims "cross-lingual
  retrieval across 100+ languages" (`knowledgebase/create.md:73-77`) and **no page
  enumerates Telugu — Telugu KB quality is a pilot gate**, and the mode is immutable at
  creation (*"cannot be switched … create a new one"*,
  `getting-started/knowledge-base.md:120-122`). **THE BUILT-IN KB IS DRIVABLE THROUGH OUR
  PORT AND THE ENGINE DECLARES THE CAPABILITY PRESENT (D-488, which reversed D-354).**
  D-354's two blockers were real, were RE-CONFIRMED against the vendor's own docs on
  20 Aug 2026, and are now HANDLED rather than avoided: the multipart upload carries a
  document the PUBLISHER renders (`KBSourceRef.document`), and the linkage is written on
  the AGENT, where it lives. The blockers as read:
  `POST /knowledgebase` is `multipart/form-data` taking a PDF (max 20 MB) OR a `url`,
  "not both" — never raw text, which is all `KBSourceRef` carries
  (`knowledgebase/create.md:31-80`) — and the created object has NO
  agent field (`get_knowledgebase.md:55-118`): an agent references a knowledge base by
  `vector_id` inside `llm_agent.llm_config.vector_store.provider_config.vector_ids`
  (`agent/v2/create.md:1302-1319`), not by the `rag_id`
  this port returned and deleted by. Both of gate 8's questions are therefore answered
  (the list carries no agent linkage, so `list_kb` reported every agent empty forever).
  Two things the mirror ADDS: create does not return `vector_id`
  (`create.md:86-127`), so the built path is create → wait for `processed` → GET the
  `vector_id` → **PUT** the agent with it added — a PUT rather than a PATCH because
  `PATCH /v2/agent/{id}` updates a closed attribute list and *"Any other field in the body
  is ignored"* (`agent/v2/patch_update.md:9,20-31`), so a PATCH carrying `vector_store`
  answers 200 and changes nothing (D-488);
  and `DELETE /knowledgebase/{rag_id}` says nothing about the agent's dangling
  `vector_ids` (`knowledgebase/delete.md:30-47`) where the *dispositions* delete page in
  the same API explicitly promises to "remove its link to any associated agents"
  (`dispositions/delete.md:39-41`) — a dangling vector id after an erasure is a DPDP
  finding, and it is a gate 8 probe rather than an inference. **So in-call retrieval is T0
  plus the engine's OWN store, which D-488 built and this port now drives** — it is not,
  and must not become, a retrieval endpoint of ours on the audio path: the `kb_chunks`
  pgvector store (D-502) serves the dashboard copilot and the CRM paths only, and
  `tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side` holds
  that arm shut by ROUTE INVENTORY. Custom functions follow
  the OpenAI function-calling schema (bearer/custom-header auth, pre_call_message
  filler line).
- **BYOK key custody — where the keys actually live.** First, a terminology fix: in this
  blueprint **"BYOK" means *we* bring *our* model keys to the *engine*.** Clients never
  hold or supply model keys — we are a managed service (D-10, flat tenancy). Three
  locations, and only three:
  1. **Canonical copy → the secrets manager.** `SARVAM_API_KEY`,
     `AZURE_OPENAI_API_KEY` (D-410 — the static key for BOTH LLM surfaces; it is a
     credential, so the name-fragment machinery seals it out of `platform_settings` and
     nothing may log it), `GOOGLE_OAUTH_CLIENT_SECRET` (D-703 — sign-in, Calendar and Sheets
     all use each client's own Google account; there is no platform Google key),
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
- **Not yet verified on Bolna** (pilot), NARROWED by the doc mirror on 20 Aug 2026 —
  what is left needs an ACCOUNT, not a page: agent draft/publish versioning,
  recording-consent + DNC built-ins, voicemail detection. Four things left this list:
  **KB size limit** is published (PDF ≤ 20 MB, `knowledgebase/create.md:36-80`);
  **concurrency by plan** is published *and readable* — free "Up to **2 concurrent
  calls**", paid "Starts at **10 concurrent calls**, scaling automatically with monthly
  usage" (`pricing/outbound-calling-concurrency.md:15,19`), with the account's live
  numbers on `GET /user/me` as `concurrency: {max, current}`
  (`api-reference/user/info.md:78-87`), so `PLATFORM_LINES_TOTAL` should be READ rather
  than typed (FLOWS §5, gate 13); **transfer** is an agent-object tool keyed
  `transfer_call` in their hosted OAS with **no REST route that transfers a live
  execution**, so `VoiceEngine.transfer(call_id, to, warm)` names a shape the vendor does
  not have and `warm` names a distinction no page in the mirror makes — no page uses
  warm, cold, attended, blind or consultative, and the only briefing channel offered is
  explicitly *"fire-and-forget … never blocks or delays the transfer"*
  (`tool-calling/transfer-calls.md:39`), which cannot be a warm handoff (gate 18);
  and **DTMF** is fully documented and is now PINNED OFF rather than unknown — digits
  arrive as a conversation message (`dtmf_number: <digits>`,
  `guides/inbound/dtmf.md:68`), i.e. into the transcript, and a short PIN passes straight
  through `text_redacted` (D-419). Whatever is missing lands in OUR layer
  (workers + compliance gate), never as a reason to bypass hard rule 5.
- **Commercials**: full BYOK leaves a flat per-minute platform fee — **unpublished**;
  negotiation target ₹0.9–1.5/min to hold the §10 all-in budget. Bundled tiers
  6¢ → 4.51¢/min otherwise; Pilots plan = 10k min @ 6¢ + 20% bonus, $5 free signup
  credits, "up to 100 concurrent" — **that last figure came from their marketing pricing
  page and NO page in the doc mirror repeats it**; what the docs publish is 2 concurrent
  on free and "Starts at 10" on paid (`pricing/outbound-calling-concurrency.md:15,19`),
  so treat 100 as a plan claim to confirm from `GET /user/me` and not as a number to
  size against. **The 6¢ is a SUM, not a floor, and the docs say so**: *"When you bring
  your own keys (BYOK), Bolna does not charge for those components. You only pay your
  providers directly, plus Bolna's platform fee"* (`pricing/call-pricing.md:75`) — so BYOK
  deletes the 3.5¢ voice-agent line rather than adding our provider bill on top of it, and
  the platform fee is OBSERVED at 2.0¢/min ≈ ₹1.84 on a founder dashboard screenshot
  (D-423, evidence class VERIFIED-DASHBOARD). That does **not** close gate 12 — one
  agent's configured models are not a universal constant and a panel is not a commercial
  term. INR/GST invoicing undocumented (ask in writing).
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
  (OPERATIONS §2 gate 4), never by a vendor number. **Compute region is no longer
  "unverified": it is DOCUMENTED as the US by default** — *"By default, Bolna processes
  calls on infrastructure in the US (AWS us-east-1)"* (`concepts/security.md:29`) — and
  the old inference from a recording URL is dead evidence twice over (the URL shape was
  retired 1 Jun 2026, and an India bucket demonstrably existed alongside it,
  `changelog/may-2026.md:105-109`). Gate 9 therefore tests a DECISION, not a measurement
  (D-415): the residency bullet above.

The ThinnestAI surface in v1.0 of this section was retired by D-31 (vendor due diligence
failed then); D-678 (6 Oct 2026) reversed that, and ThinnestAI is the engine in production.
Its current mapping onto this protocol is THINNEST-INTEGRATION §2.

## 6. RAG Subsystem (per-client knowledge) — REVISED per D-28, **SETTLED BY D-502**

**Knowledge belongs to the CLIENT, not to an agent (D-689, 8 Oct 2026).** A knowledge source
(`kb_sources`, its chunks, uploads and links) is the tenant's, and every agent of the tenant
answers from all of it: each agent's T0 block and knowledge documents are compiled from the
tenant's live sources, retrieval is scoped by tenant, and on an engine whose knowledge base
is per vendor agent (ThinnestAI) each source is pushed to every one of the client's agents
and kept in step on every version, withdrawal, new agent and archived agent.

**What a ThinnestAI call answers from.** The business facts leave the instructions and are one
knowledge document per agent (`agents/engine_facts.py`, the 6 Oct 2026 cost decision); the
facts callers ask most come back into the instructions as `[KNOWN FACTS]`, chosen per agent
from caller demand, knowledge gaps and the script within `hot_facts_max_chars`
(`agents/hot_facts.py`, D-896), which is the T0 tier below on this engine. Everything else is
a knowledge search inside ThinnestAI's pipeline, stated on at every publish
(`knowledgeOnCalls`, `engine/thinnest._knowledge_on_calls`, D-903). The engine takes text
only: a source with no text to send (a PDF or link while `kb_send_extracted_files` is off,
D-868) is not attached, and a copy an agent holds of it is withdrawn
(`kb/service._withheld_from_engine`, D-911). THINNEST-INTEGRATION §4 has the detail.

**THE BAKE-OFF HAS RUN AND THE STORE IS DECIDED, AND THE FINDING THAT MATTERS IS THAT THE
TWO PATHS GET DIFFERENT ANSWERS** (`docs/evidence/kb-retrieval-bakeoff.md`, 31 Aug 2026;
adopted as D-502 on 1 Sep 2026):

* **In-call retrieval is UNCHANGED — T0 and the engine's own KB, and nothing else.** Not
  because the store is slow (it is not, §2.3 of the evidence file) but because it was never
  the binding constraint: the voice pipeline already misses its own target by 100ms with
  ZERO retrieval in it, the engine→endpoint hop is India↔us-east-1 and has never been
  measured, and both of those are identical for every candidate store.
  `tests/kb_tiers_test.py` pins voice-runtime's route inventory as an equality so this
  cannot drift.
* **The dashboard copilot is served by `kb_chunks`, and CRM semantic search, past-call
  search and H3 caller memory by `caller_chunks`, both on pgvector in the Postgres we
  already run** (migrations `dc1aaeeeff02` and `c6b1f0d47e83`,
  `apps/api/retrieval/pgvector.py`, `apps/api/retrieval/caller_search.py`). ⚠ This bullet
  named `kb_chunks` for all four until D-503 split them, and the split is not cosmetic:
  `kb_chunks` holds the CLIENT'S OWN knowledge and `caller_chunks` holds a data
  principal's words, which is why only the second carries `subject_ref`, a
  `retention_category` per row and an explicit erasure arm. Hybrid: a dense arm fused with a `tsvector` arm by
  Reciprocal Rank Fusion, behind FORCEd RLS. Embeddings come from `text-embedding-3-small`
  on the EXISTING Azure OpenAI resource in East US 2 — **no new sub-processor**.
* **This is not "we operate vector infrastructure".** It adds no deployable, no backup unit,
  no restore drill, no region and no vendor — it adds an extension to a database this repo
  already runs. What is still refused is a separate vector service, self-hosted or managed.
* **The exit stays cheap, by construction and by the founder's condition.** Retrieval is
  behind `calevate_shared.retrieval.RetrievalProvider`; a managed vendor is one adapter
  module plus one branch in `retrieval/service.get_retriever`, with no caller touched.
  Vectors are stored at full precision and `text-embedding-3-small` is truncatable to 512
  or 768 dimensions without re-embedding, so an export is not a re-ingest.

### 6.1 Memory horizons (three; do not conflate them with RAG)

Only H3 touches the retrieval layer. H1 is orchestration, H2 is our existing pipeline.

| # | Horizon | Lifetime | Owner / store | Cost | In-call latency |
|---|---|---|---|---|---|
| **H1** | In-call working memory — the running dialogue the agent reasons over | the call only; **discarded at hangup** | the ENGINE's orchestrator (the LLM message array) | no line item — LLM input tokens, already inside the ₹0.10–0.24/min LLM leg (§10.1) | 0ms (nothing is retrieved) |
| **H2** | Call-level durable memory — transcript, AI summary, extraction fields, sentiment, resolved/needs-follow-up | retention policy (90-day recording floor) | OURS — Postgres, written by the post-call pipeline (§8) | ⚠ Sarvam extraction is **NOT ₹0.00/call** — `sarvam-105b` is priced per token (₹29.28/₹10.98/₹73.20 per 1M in/cached-in/out, §10.1's correction note). The pass has never run on a NON-Sarvam vendor (`GEMINI_EXTRACTION_DEFAULT is False`), which is a different statement from free, and it currently meters nothing | n/a (post-call) |
| **H3** | Caller / tenant long memory — repeat-caller context, semantic search over calls and leads | **NOT forever — 180 days for what an agent remembers about a CALLER (D-507), the tenant's own clock for the rest** | `caller_chunks` + `caller_memories` on pgvector in our own Postgres (D-503; D-502 supersedes D-28) — the DPDP erasure arm is BUILT (`retrieval/caller_erasure.py`, called from both erasure paths and the nightly sweep) because an embedding of a caller's words is a derived copy of those words. ⚠ **The caller-memory scope still has no PRODUCER and no route that switches it on**; the lead and transcript scopes are live. | Azure embedding tokens, metered per usage_event | injected **pre-call** via the context webhook (~5s budget), never mid-call |

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
  window limit, and whether it enables any provider-side caching on BYOK keys. ⚠ **A
  PARTIAL ANSWER EXISTS AND IS DELIBERATELY NOT GENERALISED**: *"The response LLM only sees
  the most recent **50 messages** of conversation history … on very long flows the agent can
  lose earlier turns"* (`bolna-findings/mirror/pages/graph-agent/debugging.md:73`). It is
  the first number we have, and it is stated of GRAPH agents — which we do not use — so it
  is a marked assumption about ours, not a fact. If it binds, H1 is a CAPPED window rather
  than a growing one, which changes the §10.1 LLM curve as well as what the agent remembers
  at minute 12. Gate 8 measures it on a call we place, not on this sentence.
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
| Telugu | dashboard label for multilingual mode names Hindi/Tamil, the API claims "100+ languages", and **no page names Telugu**; mode is immutable at KB creation | ours — no constraint |
| Ingestible shape | **PDF ≤ 20 MB or a URL, never prose** (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:31-80`) — so the PUBLISHER renders the approved prose into a PDF (D-488) | anything we parse |
| Portability | engine-locked | portable |

**Cost is not the deciding variable** (₹0.02–0.05 against ₹1.70–2.34/min of BYOK model
cost is noise; D-410 moved that subtotal by pennies and did not move this conclusion).
**Latency was going to be the decider and INGESTION got there first (D-424) — then D-488
ANSWERED the ingestion question and the built-in arm is what ships.** D-354 closed that
route on two blockers the vendor's own pages re-confirmed on 20 Aug 2026 (the create
endpoint takes a PDF or a URL and has no text field, so `KBSourceRef.text` had nothing to
be posted to; the knowledgebase object carries no agent id, so `list_kb` could never prove
a detach), and D-488 handled both rather than avoiding them: `KBSourceRef` gained
`document` — the approved prose RENDERED by the publisher, on the side of hard rule 2's
wall where the approval gate can see it — and the linkage is read and written on the
AGENT's `vector_ids`, which is where it always lived. `BOLNA_CAPABILITIES.knowledge_base`
is `True` and `attach_kb`/`detach_kb`/`list_kb` are wired.
**So the honest statement of the shipped system is: in-call retrieval is T0 — hot facts
compiled into the system prompt at publish time — PLUS the engine's own store, retrieved
inside the engine's pipeline with zero network hops from the orchestrator.** The EXTERNAL
arm stays UNBUILT and ungated, and nothing below is a plan with a date: it needs gate 8's
round-trip measurement, and `tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side`
holds it shut in the meantime, by ROUTE INVENTORY, so it cannot be opened by
accident. What D-488 does NOT settle is enumerated as OPERATIONS §2 gates 43a-43f: none of
it has run against a live account.

Latency doctrine (D-08's physics still binds — it now selects the provider REGION
instead of forbidding external services):
- **In-call retrieval (100ms budget)**: **T0 plus the built-in KB.** The built-in KB was
  the intended v1 home — zero network hops from their pipeline — D-354 closed it on
  ingestion shape rather than on latency, and D-488 re-opened it by rendering the document
  the route takes (above); Telugu multilingual quality remains a pilot gate (D-31, gate 8).
  An external store takes over in-call retrieval ONLY once its measured p95 from the
  engine's region (US by default, `concepts/security.md:29`; their India residency is
  Enterprise-gated AND foreclosed by our BYOK posture — §5, D-415) fits the budget — wired either as an engine custom function calling the
  provider directly, or through a thin endpoint of ours; whichever the bake-off shows
  is faster. Region-matching is the deciding
  factor, **and this paragraph used to match the wrong pair of regions**: it reasoned from
  Mumbai to a Singapore-class serverless region (~35–70ms RTT) as if the caller of our
  tool endpoint were in India. The orchestrator that calls it is documented as US-hosted
  by default (above), so the leg to measure is **engine → endpoint** from wherever their
  compute actually runs — a gate 9 question the pages settle only for the default. Measure,
  don't assume; and note the trend is against the built-in arm anyway — not one of the 15
  agents in their own template library is Telugu (`agents-library.md`, Quick Reference).
- **CRM/context paths (latency-tolerant)**: the `kb_chunks` pgvector store serves these
  (D-502, which reversed D-28: an extension in the Postgres this repo already runs, not a
  managed service) — repeat-caller context injection (their webhook's ~5s budget), post-call
  memory writes, CRM semantic features, knowledge-gap analysis.

**MEASURED, 15 Aug 2026 — the server half of the 100ms budget, which had never been
measured despite CLAUDE.md saying to.** The budget names an in-call RAG tool endpoint that
does not exist and must not: D-33 kept T3 out of our layer, D-488 put the engine's own
route back, so T3 is served INSIDE the engine's pipeline and
`tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side` fails
the day an endpoint of ours appears on the audio path. The table below measured the rented
engine's custom function `POST /tools/v1/{engine}/opt-out`, which shared every layer a
retrieval endpoint would need before it retrieved anything — source verification, bounded
read, JSON parse, ack accounting, ARQ hand-off. ⚠ HISTORICAL: that route, and the harness
that measured it, were deleted with the rented engine; it is kept as the only measurement
of that shape against the real handler and real Redis:

| in flight | 1 | 8 | 24 | 96 | 250 |
|---|---|---|---|---|---|
| server-measured ack p50 (ms) | 0.9 | 6.3 | 15.1 | 48.5 | 143.0 |
| server-measured ack p95 (ms) | 0.9 | 6.8 | 17.1 | 51.1 | 187.7 |

At one call in flight the handler spends **p50 1.0ms, p95 1.4ms, max 3.8ms** over n=500,
reaching Postgres **zero** times — 1.4% of the budget. The cost is CONCURRENCY, not the
handler: the distribution is flat at every width (D-55's convoy signature — one event
loop, ~1,750 acks/s per process), so `latency ≈ in-flight ÷ 1,750` and **100ms is reached
at ~175 concurrent in-flight tool calls per process**. D-32 records Bolna at 100
concurrent on Pilots and 250+ in production (the 100 is a marketing-page plan claim no
page in the doc mirror repeats — §5 Commercials; the 250+ is customer evidence and is the
half that matters here), so at production width our own server time
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
messy PDFs) → chunk → **approved on submission for the account's own people (D-658);
admin approve for anything else** → **English gloss (D-487)** →
push to BOTH targets (engine KB API for in-call, to every agent of the client; managed
service for CRM/memory) → version bump → T0 recompilation for every agent of the client.

**The English gloss (D-487), because the query form production produces is the one
retrieval is worst at.** Sarvam's Saaras STT returns **Tenglish** — Telugu grammar in
Latin script — and a Tenglish question scores recall@1 **0.250** against a Telugu-script
corpus on a dense ranker where an English control scores 0.958
(`docs/evidence/telugu-embedding-quality.md`, n=24). On the ranker this system runs today
(T0 token overlap) the same question scores **0.000**: there are no shared tokens at all.
So `apps/workers/kb_gloss.py` writes a short English rendering into
`kb_documents.gloss` once per chunk, at ingestion, deciding by SCRIPT which chunks need
one; retrieval scores it as a second key BEHIND A SCRIPT GATE and returns the original
line, taking Tenglish to **0.542** and English to **0.875** while leaving Telugu-script
questions bit-identical. It is a RETRIEVAL KEY and never an utterance, so it does not
widen the approval gate above it, and it is provider-independent — our own stored text,
written before the D-28 bake-off and given to whichever store wins. Since D-658 there is no human gate on what the account's own people add (the founder:
"if any knowledge is added from the owner's company/staff then no need to verify
anything"); what stands between a bad upload and a live call is the automated set —
the invisible-character refusal, the size and format ceilings, the OCR legibility filter,
the pack's shadow-text strip — plus rollback, whichever store serves it. Resolved-call transcripts are
indexed into the managed service as the per-client corpus (compounding, uncopyable).

⚠ **THE GATE BELOW IS CLOSED (D-502) AND IS KEPT AS THE SCORECARD A RE-OPENING WOULD BE
SCORED AGAINST.** It was run on 31 Aug 2026 and the result is in
`docs/evidence/kb-retrieval-bakeoff.md`; the winner is pgvector for the dashboard/CRM paths
and T0 for the call. Criterion (a) "measured retrieval p50/p95 from Mumbai" is the one the
run reframed: the store component is 12–42ms p95 and the terms that actually threaten the
budget — the US↔India hop and the question-embedding call — are IDENTICAL for every
candidate, so they do not discriminate. If the compute load ever forces the move the
founder's exit clause contemplates, this is the list to score against, and (b) and (f) are
the two that decide it: RLS gives us namespace isolation a forgotten predicate cannot defeat
and deletion proof with no second copy to prove anything about, and a managed vendor has to
match both.

D-28 bake-off gate (CLOSED by D-502; original text follows): candidates in two classes — vector-cloud (Qdrant Cloud,
Pinecone serverless [Singapore], Turbopuffer, Weaviate Cloud) and memory-API (Mem0,
Supermemory, Zep). Score: (a) measured retrieval p50/p95 from Mumbai; (b) hard
per-tenant namespace isolation; (c) hybrid (dense+sparse) search; (d) ingestion API
fit (files/text/URL + versioning); (e) memory semantics (per-caller session/user
memory) if a memory-API class provider; (f) DPDP posture (data residency, deletion
with proof via API); (g) unit cost at our volumes. Record the winner as a decision-log
entry with the scorecard committed to the repo.

### 6.3 The dashboard store: what stays in our Postgres, and the Supermemory option (D-502, D-604)

Nothing in this subsection touches a call: in-call knowledge is ThinnestAI's own knowledge
base, fed one document per published source on each of the client's agents (D-689). What
follows is the store behind the dashboard copilot and the CRM paths, selected per request by
`Settings.retrieval_provider` (`compiled-facts`, `pgvector` or `supermemory`; `applies: live`)
through `apps/api/retrieval/service.get_retriever`, behind
`calevate_shared.retrieval.RetrievalProvider`.

**Supermemory as a T3 provider.** A self-hosted Supermemory install is a candidate T3 member
behind that seam: dashboard copilot and CRM search read from it, and if it is down calls and
uploads do not notice — only dashboard search degrades to the Postgres fallback. Its local
build is **single-tenant with one auto-generated API key**; scoped per-tenant keys are an
Enterprise feature [VERIFIED-VENDOR-DOCS: supermemory.ai /docs/self-hosting/local-vs-enterprise,
read by the founder 14 Sep 2026]. Its default embedding model (`Xenova/bge-base-en-v1.5`) runs
on the host's CPU [same source, /docs/self-hosting/overview], so on a small VPS embedding must
be pointed at a hosted API (`SUPERMEMORY_EMBEDDING_PROVIDER` and siblings,
/docs/self-hosting/configuration) and the setting proven with one upload and `top`, because
upstream issue #1336 reports the variables ignored. Issues #1336, #1315 (empty searches on
Linux in 0.0.6) and #1320 (segfault under concurrent embedding) bear on which release is
pinned; their current state is **UNVERIFIED** (`supermemory.ai` is egress-blocked here). They
are a version gate, not a verdict. Caller memory is NOT behind this seam: its reader is
`compliance/caller_memory.recall` over our own `caller_memories` table, and a data principal's
durable profile does not go to a store whose local build cannot enforce tenancy.

**What stays in our Postgres whatever the T3 store is.** The document LEDGER, `kb_documents`:
which tenant uploaded what, which version is published, when it was erased. Four reasons:

1. **Tenant isolation we can prove.** Ours is FORCEd RLS enforced by Postgres (hard rule 1).
   Against Supermemory's local build, a container tag is a filter WE remember to send, not a
   wall the server enforces — so the wall stays on our side.
2. **DPDP erasure.** "Delete everything for this tenant" must be one statement we can prove
   returned zero rows. Where documents have been sent to Supermemory, `kb_index_documents`
   records what was sent, `retrieval/supermemory_index.purge_tenant_index` sends a scope-wide
   delete and empties those rows inside `execute_tenant_erasure`, and
   `scripts/check_erasure_coverage.py` walks that module. The vendor publishes no way to verify
   a deletion, so `deletion_proof` stays **False** and the certificate says the request was
   accepted rather than confirmed; if the credential is gone while rows remain, the erasure
   raises and issues no certificate rather than certifying a copy nothing can address.
3. **Provenance.** Records carry our `document_id` + `document_version`, so an answer traces
   to "brochure v3, chunk 12". The id has to be minted by us.
4. **Rebuildability.** If the T3 store is rebuilt, the ledger says what should be in it.

**When `kb_chunks` may be retired.** `kb_chunks` stays the populated pgvector store until each
of the following is a produced fact, not a judgement:

| # | Must be proven | How |
|---|---|---|
| a | **Reachable.** An install answers on `supermemory_base_url` and its responses match `retrieval/supermemory_wire.ASSUMED_CONTRACT`, or the contract is corrected to what it really sends | Requests from the host, the `top` check above; corrections land in `ASSUMED_CONTRACT` with page and date, and OPERATIONS §2 gets the gate |
| b | **Priced.** An operator has attested the embedding price, so `retrieval/supermemory.search_is_billable()` is True | Ops console. Until then the provider cannot be selected, so (c)–(e) are unreachable |
| c | **Ingested.** An ingestion path exists, has run over a real tenant's published sources, and every record carries the tenant tag and our `source_id`/`document_version` | The sweep's logs, plus a scoped search returning records `supermemory_wire.parse_search` keeps; `supermemory_records_out_of_scope` at zero |
| d | **Measured.** `retrieval/compare.py` scores both arms over the same corpus and `k`, and the challenger does not lose recall | `compare_arms` against the real `PgVectorRetriever` and `SupermemoryRetriever`; the number goes in `docs/evidence/` with the corpus named |
| e | **Agreed in production.** The shadow read has run on live dashboard traffic for enrolled tenants and every class of disagreement is explained | `retrieval_shadow_compared` log lines |
| f | **Rollback without a redeploy.** Setting `retrieval_provider` back serves the next question from Postgres | Already true: `get_retriever` is called per request and holds no state; it stays true only while `kb_chunks` is populated, which is why the drop is last |

The retirement is three releases, never one (hard rule 8): **stop reading**
(`retrieval_provider = supermemory` platform-wide; the projection keeps writing, so rollback
is one setting); **stop writing** (`kb/service.project_chunks` and `workers/kb_embeddings.py`
stop, after a sweep proves nothing reads `kb_chunks`; the table stays populated and readable);
**drop**, in a later release, with a reversible migration whose `downgrade` recreates the
table, indexes and RLS policy and a backfill from `kb_documents`, because every byte in
`kb_chunks` is derived (D-502). `kb_documents` stays in all three.

**The comparison machinery.** `apps/api/retrieval/shadow.py` asks the challenger the same live
question and serves the incumbent's answer regardless (`ShadowReadRetriever.retrieve` returns
the primary arm's own `RetrievalResult`; the challenger's answer reaches one log line). It is
sequential because both arms may hold the caller's one `AsyncSession`.
`apps/api/retrieval/compare.py` scores recall@1, recall@k, MRR and agreement keyed on the
DOCUMENT (`Provenance.source_id`), not chunk text, so it scores the two stores rather than two
chunkers; the same scoring runs offline over `tests/fixtures/telugu_gloss_corpus.json`. Two
live settings, both off: `retrieval_shadow_arm` names the store asked in the dark, and
`retrieval_shadow_tenant_ids` names whose questions may be asked (**empty means nobody**),
because a shadow search buys an embedding metered against the tenant whose question it was.

## 7. Schema-Driven Extraction (the product core)

Per-agent `extraction_schema`: ordered list of {key, label, type(text|number|bool|enum|
date), enum_values?, reason(optional AI hint — "why this variable is needed"; fed to the
extractor, name/label alone used when empty), required}. Editable by the client (owner
role, self-serve) AND by Calevate admins/superadmin (D-460, superseding D-21's admin-only
clause); vertical templates (clinic, real_estate, insurance, education) pre-fill it. Each
save is live: it inserts a new schema version pointed at the agent in one transaction and
the next call uses it immediately — no draft/publish gate. Old versions stay for history
(Leads render by the version active at extraction time), so nothing is lost.
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
Sarvam, D-410 moved it again to Azure OpenAI, and D-449 moved the region to `eastus2` —
NONE of the three moved THIS one**, and
that is the distinction both decisions turn on: the in-call leg and the dashboard assist see
the caller through the engine and through `text_redacted` respectively, and this pass is the
only one in the system that reads `turn.text`. This selector's caller is `workers/pipeline.py`, which hands
over the RAW transcript — `turn.text`, one line after `redacted.text` is computed, because
a CRM "callback number" field needs the actual digits. Until D-127 the ladder returned a
second-vendor client whenever that vendor's key was configured and a Sarvam key was not, so
one absent environment variable sent raw caller PII to a second processor. The other vendor
now serves only the USER-TRIGGERED work, through `workers/extraction.run_assist()`, over the
redacted copy, on Azure OpenAI in East US 2 — and `run_assist` re-runs `redact()` on its
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

The prompt names the AGENT's language (`agents.language_primary`, then `languages_extra`;
`te-IN` when none is given) rather than assuming Telugu, fences the transcript with
`End of transcript.` and repeats the output rule after it. Both model legs send the same
strict `json_schema` (`workers/extraction.build_response_schema`, with the key-moments list
when the request asks for moments) and fall back to `json_object` on a 400, logged as
`sarvam_json_schema_unsupported` / `azure_json_schema_unsupported`. The Sarvam leg states
`reasoning_effort` explicitly (`SARVAM_EXTRACTION_REASONING_EFFORT`, `low`, the vendor
default every pass has run on), so a vendor default change cannot move its cost. Whether
`off` extracts as well for fewer tokens is UNMEASURED until a credentialed golden run
(`scripts.eval --provider sarvam --provider sarvam_reasoning_off`) settles it (D-780).

## 8. Post-Call Pipeline (workers; idempotent; keyed by call_id)

On ThinnestAI the engine's signed webhooks (`call.completed`, `call.analysed`; verified in
voice-runtime by `signed_intake.py` and deduped on the event id, D-690) are HINTS, the
authenticated Get Execution (`engine/thinnest.get_execution`, `GET /calls/{id}`) is the TRUTH,
and `pipeline.reconcile_executions` walks the call list for anything a webhook missed.
A delivery stands as the call's record only when it is final in content
(`workers/engine_delivery.py`: `call.analysed`, with turns on an answered call); a
`call.completed` is a hint and Get Call is read instead, and an answered call settled
without its transcript is re-driven (D-848, D-850; THINNEST-INTEGRATION §3 step 3):
webhook(execution status) → **authenticate per §5** (HMAC where the engine signs; an unsigned
engine gets source-IP allowlist + execution-id dedupe, payload treated as a HINT) →
authenticated Get Execution is the TRUTH → persist CallEvent + turns → enqueue:
1. fetch/persist recording to our storage (presigned; engine copy is not our system of record).
   ThinnestAI's `recording.url` is a signed link that expires, so `engine/recording_source.py`
   copies it within the vendor's documented retention. The per-turn timings are fetched
   by their own job a minute later (`workers/call_timeline`, D-902, D-924).
2. PII redaction pass on transcript (Aadhaar/PAN/card/OTP patterns + LLM assist) →
   redacted transcript is the default view; raw restricted by role
3. extraction (per §7) → upsert Lead
4. usage metering → usage_events rows (see §9)
5. notifications: hot-lead rules → client email/WhatsApp; the business's own team told
   on the outcomes or choice answers the owner picked (`team_alerts.queue_after_call`, D-904)
6. campaign-contact resolution (close or re-queue on the FLOWS §5 retry ladder)
7. outbound CRM sync (`call.completed` through the outbox, D-23) — summary, never transcript;
   then the client's after-call actions (D-700)
8. the language pass, LAST and as its own job (`workers/call_translation.translate_call_job`,
   queued by `pipeline.queue_language_pass` in step 7's transaction, D-931): English for
   the turns and whichever summary the call lacks. Nothing in steps 3-7 reads what it
   writes; a summary it fills in after `call.completed` went out is sent as `call.updated`
*Planned, NOT in the shipped pipeline:* embeddings for resolved calls (KB corpus) — M3
per ROADMAP.
Retry budget is **3 attempts** — `WORKER_MAX_TRIES` in `apps/api/core/queue.py`,
the one number the ARQ worker and the delivery worker's exhaustion check both read.
A client webhook delivery follows its own persisted schedule, 8 attempts over about a day
(`integrations/service.WEBHOOK_RETRY_SCHEDULE`, WEBHOOKS §1.5); a Google Sheets append
backs off **30s then 120s**; a failed recording copy waits 30s.
Only transport failures, 5xx, 408, 425 and 429 are retried; any other 4xx stops on the
first attempt as `rejected {code}`. A worker earns a retry only by raising `arq.Retry`
— a plain `raise` is terminal on the first attempt under arq 0.28.
DLQ on repeated failure; pipeline lag is a monitored SLO
(target: lead visible < 2 min after hangup). ⚠ Under arq 0.28 a plain `raise` is
terminal on the first attempt, so a worker earns the ladder above only by raising
`arq.Retry`. Full note and the incident it caused:
FLOWS §6.

## 8a. Live updates in the consoles (D-774)

D-24 chose polling for freshness and named server-sent events as the upgrade; D-774 is the
upgrade, with polling kept underneath as the floor.

- **Capture at commit, not at each write site.** `apps/api/live/capture.py` listens on the
  engine (`after_cursor_execute`) for INSERT/UPDATE/DELETE targets that touched a row, keeps
  their TOPICS on the session, and hands them over in `after_commit`; a rollback discards
  them. `apps/api/live/topics.TABLE_TOPICS` maps every table to a topic (calls, leads,
  campaigns, callbacks, knowledge_gaps, knowledge, wallet, agents, numbers, dnc, account,
  integrations, assistant, quality, healer, alerts, platform) or lists it in `QUIET_TABLES`
  with a reason; `tests/live_updates_test.py` holds that against the migrated database.
  Installed by the API and the workers at startup, never by voice-runtime (hard rule 3).
- **Publish after commit, as a hint.** `live/publish.py` sends one pipeline of Redis
  `PUBLISH`es: the tenant's channel gets `{topic, at}`, the operator channel gets
  `{topic, at, tenant_id}`. No row ids, names, numbers, amounts or text (hard rule 6). A
  failed publish is logged (`live_publish_failed`, recorder `live_publish_failed`) and
  swallowed; the write has already committed. Redis pub/sub is not a broker here: nothing
  depends on delivery.
- **Serve one stream per realm.** `GET /v1/live` (`org:read`, any realm, so a view-as
  operator hears the viewed account) subscribes to `calevate:live:tenant:<id>` only;
  `GET /v1/admin/live` (`org:read`, admin realm) to the operator channel. One pattern
  subscription per process (`live/hub.py`) fans out to bounded per-stream queues; an
  overflow or a lost subscription becomes `resync`. Every 20 s the stream re-checks its
  caller with `core.auth.still_entitled`, which reads the session row without sliding the
  idle window or treating a rotated cookie as a replay (`authn.sessions.session_still_live`)
  and re-reads membership, role and grant; it ends after 30 minutes and on SIGTERM
  (`core.bootstrap.on_exit_signal`) so a deploy's drain is not held open. At most eight
  streams per person per process. FastAPI's SSE response sends `X-Accel-Buffering: no` and a
  keep-alive comment every 15 s, inside nginx's 60 s read timeout.
- **Refetch in the browser.** `apps/web/src/lib/live/` opens the stream once per shell
  (`components/live/LiveUpdates.tsx`), maps topics to TanStack query families
  (`topics.ts`, the one map; `tests/liveTopics.test.ts` fails on a query family with no
  topic and pins the topic list to the server's) and invalidates them, coalesced over
  400 ms (1.5 s on the operator stream). `ready` and `resync` refetch everything on screen;
  drops reconnect with full-jitter backoff (1 s to 30 s); a hidden tab lets go after 30 s.
  While the stream is healthy `livePoll` stretches feed intervals to a 5-minute safety
  poll; when it is down they return to their own.
- **Motion.** A row or item that arrives live enters with `live-enter` (220 ms fade and
  4 px drop) and a table row also takes the `value-flash` tint; removed table rows fade
  out over 150 ms; a `StatusPill` and a `Metric` mark a changed value; nothing moves on
  first load or when a page is replaced rather than continued; reduced motion makes every
  update instant. A reader scrolled away from a table's top gets the `NewItemsPill`
  instead of moved content.

## 9. Metering & Billing

> **D-707 (10 Oct 2026) supersedes the managed retainer described in this document.** Every
> client is prepaid: calls draw down credit lots, and the only other charge is the optional
> monthly platform fee (`billing/platform_fee.py`), raised per client per IST month while the
> ops switch is on, paid as a separate Razorpay order into the append-only
> `monthly_fee_payments` ledger, and enforced on OUTBOUND only by the dispatch gate after a
> seven-day grace. §10.2's reading of D-11 (setup fee and retainer carry the fixed base) is the
> record of that decision, not the current model.

Append-only `usage_events` (tenant_id, call_id, unit_type[telephony_s|stt_min|tts_chars|
llm_tok_in|llm_tok_out|platform_min|…; the full list is `billing/models.UNIT_TYPES`, of which
`llm_ktok_in` and `llm_ktok_out` are no longer written (D-763)], qty,
unit_cost_paid, occurred_at) — records OUR cost
next to billable qty; per-client margin is a query, and phase-2/3 build-vs-rent decisions
use months of real data. Plans are config rows {setup_fee, monthly_fee, included_min,
overage_rate, hard_cap_min, hard_cap_spend}; invoices derive from ledger + plan. Prepaid
credit balance; **caps enforced pre-dispatch in the compliance gate**
(`apps/api/compliance/service.py::check_dispatch` — the one function every outbound path
calls: campaign dispatch, "call this lead", instant lead callback). A capped tenant's
outbound is refused (`spend_state.capped`); a self-serve/trial tenant with an empty
wallet is refused too (D-34 credits). **Inbound never reaches this gate** — the caller
initiated it, which is D-38's consent-clean property — so there is no inbound fallback
line, and voice-runtime carries no cap logic (hard rule 3 keeps it thin). ⚠ **THIS
SENTENCE READ "Inbound is unaffected and never reaches this gate" UNTIL D-551 (8 Sep
2026), AND THE FIRST HALF IS WITHDRAWN.** Not reaching the gate is not the same as being
unaffected: an EMPTY WALLET (never a spend cap, a suspension or the halt, which are all
still outbound-only) now stops answering as well, enforced as durable state AT THE ENGINE
rather than at any gate of ours — `agents/service.py::reconcile_inbound_answering` writes
the neutral message on the ledger's crossing of zero and `publish_agent` re-decides it,
because nothing of ours runs before the vendor answers an incoming call.
A client-bought number's rental is collected monthly at the price frozen at purchase — a
wallet `usage` debit for a prepaid account, a `one_time_charges` invoice line for an
invoiced one — decided in `billing/number_rental.collect_number_rental` (D-665); a refunded
credit pack takes its bonus back in the refund's own transaction (D-672). Our cost per
call is §10.0's engine minute (plus the Cartesia characters on a Studio call), and the
client is billed in 30-second steps of the call's duration (D-681).
Razorpay for collection (phase 1 can invoice manually; ledger from day 1 is non-negotiable).

## 10. Cost Model (verified July 2026; re-verify quarterly)

> **What a call costs us today is §10.0.** ThinnestAI hosts the whole call (D-678..D-682), so a
> minute's cost is ThinnestAI's attested per-minute rate plus its wallet top-up fee, and on a
> Studio call Cartesia's charge for the characters spoken on our key. The rate card is BRD §6.1
> (D-728: Clear ₹4.50, Studio ₹6.00 on every pack) and the margins against these costs are BRD
> §6.2. The floors a card is judged at are code-derived in
> `apps/api/billing/rates.py::cost_floor_inr_per_min` and pinned by `tests/cost_floor_test.py`.
> Clients are billed in 30-second steps (D-681).
>
> Everything else in §10 before §10.0 and from §10.2 on is the cost model of the stacks that
> preceded ThinnestAI — the rented Bolna engine with our own STT, TTS and LLM keys, and the
> self-orchestration comparisons made against it. It is the record the July–September pricing
> decisions were made on, not a description of what a ThinnestAI call pays. §10.1 keeps the
> per-leg vendor rates that still price something on ThinnestAI (the Cartesia leg of a Studio
> call; Sarvam's first post-call extraction pass) and the model rates the code still holds.

Per-minute variable (₹), the own-stack summary: platform 1.5–2.0 (the Bolna BYOK fee, never
verified) · STT 0.50 · **TTS 2.22–3.33 on the Studio voice (Cartesia Sonic 3.5 — a MONTHLY
PLAN whose MARGINAL per-character rate past the included allotment is what this band is struck
at, `billing/rates.py::CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS`; it is also the one synthesis
leg a ThinnestAI call still buys from a vendor of ours, §10.0)**
· **LLM 0.10–0.24 (`gpt-4o-mini` on Azure OpenAI East US 2 — the band is the one- to
ten-minute curve, not a rate; supersedes D-400's 0.23–0.51 Gemini band and D-36's ₹0.00.
On the `gpt-4.1-mini` switch it is 0.27–0.64 — 2.67x, see §10.1)**
· telephony 0.40–0.90 inbound / 0.60–1.80 outbound. **Blended all-in ≈ 3.3–3.8 (launch)
→ 1.9–2.6 (phase 2)** — derived rather than adjusted. Launch is **D-36's ≈₹3.1–3.6 plus the
LLM leg at the five-minute reference (₹0.16)** = 3.26–3.76. Phase 2 is that minus the ₹1.50
platform fee plus ₹0.15–0.30 of self-orchestration compute = 1.91–2.56. These are blended mid-ladder
estimates of a stack we no longer run.


> ⚠ **THE LLM LEG IS NOT FREE AND IS NOT A FLAT PER-MINUTE RATE (D-400, repriced by D-410).**
> D-36 priced it at ₹0.00 because Sarvam 105B is free per token; it is now `gpt-4o-mini` on
> a paid Azure OpenAI deployment (South India at D-410, `eastus2` since D-449 — the
> region moved, the price did not: list price is per token and not per region). The
> computation is
> `billing/rates.py::llm_cost_inr_per_minute`, which takes a DURATION, because §6.1 resends
> the whole conversation to the model on every turn — so input tokens grow through the call
> and total input cost is quadratic in length. **The SHAPE of the calculation is unchanged
> by D-410; only the vendor price feeding it moved**, from $0.30/$2.50 per 1M tokens to
> `AZURE_LIST_PRICE_USD_PER_MTOK`'s **$0.15 in / $0.60 out** for `gpt-4o-mini` (and
> $0.40 / $1.60 for `gpt-4.1-mini`, the live switch). Cheaper on both legs and half the
> input price, which is where it lands because voice is input-dominated. On the reference
> conversation stated at `rates.REFERENCE_CALL`, on the DEFAULT model: **₹0.10/min on a
> one-minute call, ₹0.16/min at five minutes, ₹0.24/min at ten** — **less than half what
> the Gemini leg cost at every duration** (₹0.23 / ₹0.35 / ₹0.51). **The switch is not a
> free upgrade and the figures say so**: `gpt-4.1-mini` is **₹0.27 / ₹0.44 / ₹0.64**, which
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

On ThinnestAI the per-call cost is §10.0's: the attested rate per billed minute, with
ThinnestAI's own per-call charge (`costMicro`) reconciled against it and never metered.
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
| **Bolna** (primary, D-31) | **unpublished as a commercial term** — pilot gate 12; bundled ₹5.52→₹4.15; **OBSERVED at 2.0¢/min ≈ ₹1.84 on a dashboard panel (D-423, VERIFIED-DASHBOARD — the "rumoured ~₹1.8" line was closer than it deserved to be, and one agent's panel is still not a contract)**; target ≤₹1.5. **No monthly floor** (prepaid credits) | undefined "<300ms" marketing claim; compute region **documented as US by default** — *"Bolna processes calls on infrastructure in the US (AWS us-east-1)"* (`bolna-findings/mirror/pages/concepts/security.md:29`), not the URL inference this cell used to carry; India residency is Enterprise-gated and foreclosed by BYOK (D-415) |
| LiveKit Cloud (phase-2 candidate) | marginal ₹1.23 (agent + third-party SIP, two meters) but **$50/mo Ship floor dominates**: ₹4.40/min @1k min, ₹0.88/min @5k min; concurrency capped 5/20/600 | ✅ ap-south (Mumbai) VERIFIED — best-evidenced |
| Self-host (DO BLR / Vultr Mumbai) | ₹2.1/min @1k, ₹0.85–1.2/min @5k (₹2,112/node ≈ 8–9 concurrent) | best possible physics (co-located), unmeasured |
| ~~Cartesia **Line**~~ (D-88, re-examined Aug 2026) | ₹5.28/min ($0.06/min, Free→Startup) — **bundled, and now CONFIRMED bundled**: Line's LLM is fully BYOK via LiteLLM (`model=` + `api_key=`, 100+ providers) but **STT and TTS are not** — Ink 2 and Sonic 3.5 are the product and the SDK exposes no swap interface (first-party: the Line SDK README, `github.com/cartesia-ai/line`). So it is not comparable to a BYOK fee, and it **cannot host D-36's Sarvam stack**. Scale tier $0.014/min (₹1.23) is enterprise-negotiated with an unpublished commitment. Monthly plans to $299 (₹26,312); agent concurrency capped 1/3/5/10 by tier. Eliminated on **telephony**, not price: Cartesia numbers / imported Twilio / Voximplant, none of which is a DLT-registered Indian number. ⚠ **ELIMINATED AS AN ORCHESTRATOR, ADOPTED AS A TTS VENDOR — TWO DECISIONS ABOUT ONE COMPANY, AND CONFLATING THEM IS THE ERROR THIS CELL NOW NAMES (D-547, 7 Sep 2026).** The verdict above is unchanged and is about **Line**, their orchestration product: it is bundled, it cannot host D-36's Sarvam stack, and its telephony reaches no DLT-registered Indian number. What D-547 adopted is **Sonic 3.5 as our SECOND TTS leg on Bolna**, where Cartesia is a first-class voice provider (`bolna-findings/mirror/pages/providers/voice/cartesia.md:58-66`, VERIFIED-VENDOR-DOCS) and the credential store takes one `CARTESIA` entry (`providers.md:146-150`) — the MODEL layer of the table below, at the plan price §10.1 states, bought while the orchestrator stays Bolna. Nothing in this row is softened by that: buying a vendor's model is not buying their platform, which is the same like-for-like rule the paragraph under this table was written to enforce | India story is REAL but enterprise-shaped: Blue Machines AI partnership (~Feb 2026) for India-**resident** processing, Bangalore office, Sonic 3 across the top 9 Indic languages incl. Telugu, on-prem/VPC/air-gapped, SOC 2 Type II + HIPAA + PCI L1. The earlier "English-first TTS" reading was **stale and is withdrawn**. Self-serve India region still unverified — `docs.cartesia.ai` and `www.cartesia.ai` are unreachable from our build environment |
| ~~Vapi~~ | ~~₹4.40/min~~ — survives full BYOK; exceeds the entire all-in target alone | ❌ US/EU only: +230–260ms hairpin |

Two rules this table encodes (D-32): at launch volume **monthly floors dominate
per-minute rates**, and **no latency figure here is measured** — all of it ranks by
region physics until the pilot produces real PSTN numbers (gate 4).

**A third rule, learned the hard way while building this table — compare like with like.**
Vendors price at two different layers and the same-looking number means different things:

| Layer | What you buy | Representative price |
|---|---|---|
| **Model** (STT/TTS/LLM) | one leg of the pipeline | Cartesia Sonic TTS **₹3.29–4.40 / 1k chars by plan tier, sold only as a monthly bundle** (Startup $49 / 1.25M chars, Scale $299 / 8M; no pay-as-you-go — `docs/evidence/cartesia-tts-verification-2026-09-06.md`; this cell said "≈ ₹2.7–3.0" until 6 Sep 2026 and that figure was REPORTED and wrong) |
| **Orchestration, bundled** | the whole call, vendor's models included | Cartesia Line $0.06/min · Bolna bundled 6.00¢/min |
| **Orchestration, BYOK** | the whole call, *our* models | Bolna BYOK (target ≤₹1.50) · Vapi $0.05/min **on top of** your model spend |
| **Self-orchestrated** | nothing — you built it | ₹0 fee + ~₹0.20/min compute |

Reading a model price against a platform price (or a bundled fee against a BYOK fee)
produces a ~4× error. **Outpero is the worked example of the ERROR** — anyone assuming they
pay Line's ₹5.28/min has stacked two layers that never both apply. They buy Cartesia at the
*model* layer (~₹1.0–1.6/call-min for TTS); what they pay at the ORCHESTRATION layer is
**not established** (§10.3).

> ⚠ **This paragraph used to answer that question and had no right to.** It read "they pay
> **nothing** at the orchestration layer because they built it … they skipped the platform
> entirely", which is the self-orchestration inference §10.3 explicitly withdraws — stated
> here as the premise of a worked example, two hundred lines from the correction that
> retracts it. A reader who stopped here inherited a conclusion the document disowns
> elsewhere, which is the laundering-by-repetition that hard rule 11 exists to stop, and
> the one-fact-in-two-places drift D-103/D-105 exist for. The layer-confusion lesson is
> real and survives without it: it does not need to know who Outpero pays, only that the
> two layers are different.

### 10.0 What a ThinnestAI call costs us: `unit_cost_paid`

Hard rule 7 requires a real cost on every `usage_events` row, in an append-only ledger. There
is no vendor total to convert: ThinnestAI's call results carry a charge, but the meter is built
from independently sourced legs, and the charge is the check on it.

| Leg | Quantity | Price | Source and evidence |
|---|---|---|---|
| Engine minute (every call) | billed minutes = `ceil(seconds / 30) × 0.5` | the operator-attested ₹/min for the call's rate key (`engine_agent_routes.engine_rate_key`: the band sold as Clear, or `byok_voice` for Studio) × (1 + the attested wallet top-up fee, `billing/cost_attestations` subject `thinnest_topup_fee`, D-840) | `billing/engine_minutes.py` (D-678, D-723). Rates: Premium band ₹2.00, Studio band ₹2.50 (VENDOR-PUBLISHED, ThinnestAI console, founder-relayed 24 Oct 2026, D-878), voice-only BYOK ₹1.50 including the line (VENDOR-STATED); the 2.36% top-up fee is ThinnestAI's email of 12 Oct 2026 (D-754). An attested rate lives in `platform_engine_minute_prices` |
| Cartesia synthesis (Studio calls only) | characters our transcript says the agent spoke, in thousands (`tts_kchars`) | the operator-attested Cartesia rate; no top-up fee, because it is billed to our own Cartesia key and never passes through the wallet | `apps/workers/pipeline.py`; the vendor's plan and overage rates are §10.1's Cartesia card |

**Reconciliation, not metering.** ThinnestAI's `costMicro` (on `call.analysed` and
`GET /calls/{id}`) is kept on `calls.engine_charged_inr` and compared hourly by
`workers/engine_charges.py`: charge × (1 + top-up fee) against the attested minute, and a
Studio call must carry its Cartesia row. A difference alarms; it is never written as a
correction to the ledger (hard rule 4). Detail: THINNEST-INTEGRATION §5.

**The costing rule is the same on every leg.** Each figure passes through `billing/`, refuses
an unattested price, and never takes a catalogue number as `unit_cost_paid`. A minute with no
attested rate is UNPRICED — recorded with a NULL cost and alarmed — never priced at zero, and
`engine_minute_is_billable` is the door the offer and publish seams consult, so a minute
without a rate is not sold at all. Defaulting any leg to zero is the one response that is
never allowed: a leg we cannot price raises, exactly as `billing/rates.py::llm_inr_per_ktok`
does for a model.

**Client billing is separate** (D-681): the client is billed in the same 30-second steps on
the rung of the agent that took the call (`billing/rates.py::client_billed_minutes`), at the
rate frozen on the credit lot being spent (BRD §6.1).

### 10.1 Stack cost, computed from published rates (Aug 2026)

Every figure below is derived from a first-party rate card; the derivation is shown so it can
be re-checked when a rate moves. **What each card prices on ThinnestAI:** the Cartesia card
prices the synthesis leg of a Studio call (§10.0); the Sarvam card prices the first post-call
extraction pass (`sarvam-105b`) and Saaras speech-to-text where we transcribe outside a call.
A ThinnestAI call's own STT, LLM and Clear voice are inside its per-minute rate, so the STT and
in-call LLM rows of the per-call-minute table price no ThinnestAI call: they are the own-stack
margin model `billing/rates.py::llm_cost_inr_per_minute` still computes, and
`scripts/check_docs_drift.py` reconciles them against the code.

**Assumption used throughout:** the agent speaks 40–60% of a call, at ~900 characters/minute
of actual speech → **360–540 TTS characters per call-minute**. That ratio is the single biggest
lever on the Studio cost and is measured from our own transcripts:
`GET /v1/admin/spend/tts-speaking-rate` (`billing/tts_speaking_rate.py`, the "TTS speaking
rate — measured" card on the admin spend board) reads `length(COALESCE(text_redacted, text))`
over the AGENT's turns ÷ `calls.duration_s` for every call with a transcript, across every live
tenant one RLS session at a time, and publishes the p50, the p95 and the pooled (Σ chars / Σ
minutes) chars per call-minute. **The band is the FALLBACK until the sample reaches twenty
calls** (`TTS_SPEAKING_RATE_MIN_CALLS`; below that the route returns the sample size and
`measured: false` and no figure). The first reading, 571 agent characters per call-minute over
3 calls (D-728), is below that threshold. The band lives in code as
`billing/rates.py::TTS_ASSUMED_CHARS_PER_CALL_MINUTE` and `scripts/check_docs_drift.py` §4e
diffs it against every statement of it in this document. When the card reads measured,
re-derive the Studio floor from the POOLED figure: a month's bill divides by the pooled rate,
and the tail is published as exposure rather than multiplied into a floor. Indic scripts can
run denser than the band, which pushes a Studio minute's cost up; the measurement is what
confirms or reprices it.

**Sarvam rate card, read live from `sarvam.ai/api-pricing` on 11 Aug 2026 and RE-READ off
the founder's own Sarvam dashboard on 27 Aug 2026** (`indus.sarvam.ai/model-catalogue` and
`indus.sarvam.ai/pricing/buy-credits`; this supersedes the July figures and corrects two of
our own doc errors — see the ⚠ notes below):

| Sarvam API | Published rate |
|---|---|
| **Sarvam 105B (`sarvam-105b`, chat LLM)** | **₹29.28 / 1M input · ₹10.98 / 1M cached input · ₹73.20 / 1M output** — ⚠ **NOT free; see the correction note below** — *the first post-call extraction pass and the disclosed dashboard-assist fallback* |
| Speech-to-Text | ₹30 / hour |
| Speech-to-Text **and Translate** (Saaras) | ₹30 / hour |
| STT with diarization | ₹45 / hour |
Plans: pay-as-you-go with **no minimum**; ₹1,000 free credits; credits never expire and are
universal across APIs. **Rate limits are the real constraint, not price** — 60 rpm (Starter) /
200 rpm (Pro ₹10k) / 1,000 rpm (Business ₹50k).

**Cartesia rate card — the Studio voice (D-547, D-687).** On ThinnestAI a Studio agent speaks
Cartesia on our key through voice-only BYOK, and Cartesia bills that key directly. Cartesia is
**not per-character billed**: it is a monthly subscription with a character allotment and no
pay-as-you-go option, so the ₹/chars figure below is the plan's MARGINAL rate — the overage
rate past the included allotment.

| Cartesia API | Published rate | Marginal rate |
|---|---|---|
| Text-to-Speech **Sonic 3.5**, Pro plan (the plan we are on) | $5 / month, 100,000 credits (1 credit = 1 character), then **$65 / 1,000,000 credits** | ₹61.75 / 10,000 chars |

> **The overage rates are $65 / $45 / $38 per 1,000,000 credits on Pro / Startup / Scale**,
> and the smallest paid path is **Pro at $5/month**.
>
> **EVIDENCE CLASS: VENDOR-PUBLISHED.** Direct correspondence — an email reply from **Ege
> Tinmaz, Product Support Engineer, Cartesia (ege.tinmaz@cartesia.ai)** to a pricing enquiry
> the founder sent, relayed by the founder on 9 Sep 2026 and recorded at
> `docs/evidence/cartesia-tts-verification-2026-09-06.md` ADDENDUM 3. It outranks the Comet
> research run in the rest of that file, which is REPORTED. ⚠ **`cartesia.ai` and
> `docs.cartesia.ai` REMAIN EGRESS-BLOCKED FROM THIS CONTAINER** (re-measured 9 Sep 2026):
> nothing here was read from the vendor's site by this repository. The overage rates appear
> on no public page — third-party sources say to contact sales — so this correspondence is
> the ONLY source for them, which is what makes it authoritative rather than corroborative.
>
> **Conversion: this row is struck at ₹95 = US$1.00, the founder's planning rate for every frozen
> USD→INR conversion (`rates.PLANNING_USD_INR`, D-768: a founder decision, not a market reading);
> the live COST FLOOR is not.** Since 9 Sep 2026 the live floor converts at the published USD→INR rate
> (`core/fx.usd_inr_rate_now`), because Cartesia bills in dollars — see §10.3. **Below the
> allotment the real per-minute cost is higher** (the fee does not shrink and is paid
> whether or not it is spoken). The constants live at
> `billing/rates.py::CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS` (derived from the vendor's
> overage rate, never typed) and `scripts/check_docs_drift.py` §4b diffs this row against
> them in both directions.

**Cost per call-minute.** At the band above (360–540 characters a call-minute), the Studio
synthesis leg is **₹2.22–3.33** at the Pro overage rate. That is the worst MARGINAL cost — what
one more minute costs on the plan we are on — and only the refusal bound: below the allotment a
minute costs more, because the fee is paid whether or not it is spoken, so the honest cost is a
curve in the month's platform volume and the ops console prints it with the volume named
(D-556). THINNEST-INTEGRATION §5 prices the Cartesia leg of a ThinnestAI Studio call at
₹2.06–3.42 per call-minute at 571 characters a minute, by plan and volume (cartesia.ai/pricing
read 11 Oct 2026). The refusal stays frozen at ₹95 (D-768) so a currency tick cannot make a live card
un-recordable; the live-rate figure is published beside it as a warning.

| Leg | Rate | Per call-minute |
|---|---|---|
| STT — Saaras (STT+Translate) | ₹30/hr | **₹0.50** |
| TTS — Cartesia **Sonic 3.5** *(the Studio voice; the vendor's **Pro overage rate**, VENDOR-PUBLISHED — see the card above)* | ₹6.1750 / 1,000 chars | **₹2.22–3.33** |
| LLM — `gpt-4o-mini` on Azure OpenAI `eastus2` *(D-410's default and still the **base-rate** model `billing/rates.BASE_RATE_LLM_MODEL` freezes the plan rate against — no longer the platform default; region per D-449)* | $0.15/$0.60 per 1M tok | **₹0.10 (1 min) / ₹0.16 (5 min) / ₹0.24 (10 min)** |
| LLM — `gpt-4.1-mini` on Azure OpenAI `eastus2` *(the live switch, `azure_openai_model`; both allow-listed models are on the Regional-Standard matrix for this region — gate 20b reads the quota)* | $0.40/$1.60 per 1M tok | **₹0.27 (1 min) / ₹0.44 (5 min) / ₹0.64 (10 min)** |
| LLM — **`gemini-2.5-flash-lite` on Google Gemini Developer API** *(the cheapest leg we offer, and since 4 Sep 2026 the **platform default** — `Settings.platform_llm_model`. Cheaper than the base-rate model, so it carries **no** model surcharge)* | $0.10/$0.40 per 1M tok | **₹0.07 (1 min) / ₹0.11 (5 min) / ₹0.16 (10 min)** |
| LLM — `gemini-2.5-flash` on Google Gemini Developer API *(the vendor's own production recommendation; thinking budget zeroed by the engine)* | $0.30/$2.50 per 1M tok | **₹0.23 (1 min) / ₹0.35 (5 min) / ₹0.51 (10 min)** |
| LLM — `gpt-5.4-mini` on OpenAI direct `us` *(the engine's own voice recommendation, and the dearest thing we offer)* | $0.75/$4.50 per 1M tok | **₹0.54 (1 min) / ₹0.85 (5 min) / ₹1.23 (10 min)** |
| LLM — Sarvam 105B *(what D-400 superseded; the disclosed dashboard fallback and the extraction pass — **not an in-call leg**, so no per-minute curve is derived for it)* | ₹29.28/₹10.98/₹73.20 per 1M in/cached-in/out | **not ₹0.00 — see the correction note** |

> ⚠⚠ **CORRECTION (27 Aug 2026): THE SARVAM CHAT LEG IS NOT FREE, AND THIS DOCUMENT
> PRICED IT AT ₹0.00 EVERYWHERE.** The founder read his own Sarvam dashboard on 27 Aug 2026
> — Model Catalogue (`indus.sarvam.ai/model-catalogue`) and the buy-credits pricing modal
> (`indus.sarvam.ai/pricing/buy-credits`) — and `sarvam-105b` (and
> `sarvam-105b-conversations`) are priced **₹29.28 / 1M input tokens, ₹10.98 / 1M cached
> input, ₹73.20 / 1M output**. D-36's "free per token" premise, which this section reasoned
> from and which `calevate_shared/engine.py`, `workers/script_assist.py` and
> `copilot/service.py` each restate, is **withdrawn**. The card now lives in code at
> `billing/rates.py::SARVAM_LLM_INR_PER_MTOK`, where it is a REFERENCE with no path to
> `unit_cost_paid` (hard rule 7). **Re-read 10 Oct 2026 on the public page
> (https://www.sarvam.ai/api-pricing, VENDOR-PUBLISHED, founder-relayed): the same three
> figures.** The metering is now wired: the post-call extraction pass and the assistant's
> Sarvam standby are recorded at our cost (`ai_assist_ktok_*` under `call_extraction` /
> `assist_standby`, absorbed, never counted against a client's AI allowance — founder,
> 10 Oct 2026) once an operator attests the price (`POST /v1/ops/inr-llm-prices/sarvam-105b`,
> table `platform_inr_llm_prices`). Until that attestation exists the legs record nothing
> and log `ai_assist_unmetered_fallback` / `extraction_cost_unpriced` with the reason. Cached
> input is priced at the full input rate (an upper bound): the ledger has no cached-input
> unit, and the cached count rides `meta.cached_prompt_tokens`.
> ⚠ **One gap this correction does NOT close:** `sarvam-105b` is described as "always-on
> reasoning" and the pricing modal shows only Input / Cached input / Output — whether
> hidden reasoning tokens are billed at the Output rate is **not stated anywhere the
> founder could find**. If they are, this leg costs MORE than the card says. Do not assume
> either way; an invoice line against a request of known token counts settles it.
>
> **The same reading confirms the speech-to-text rate.**
> Confirmed: `saaras:v3` **and** `saaras:v4` both at **₹30 / hour** of audio (₹45/hour with
> diarization, which this product does not enable). The STT rate has a code home
> (`STT_INR_PER_HOUR` in `billing/rates.py`) and `scripts/check_docs_drift.py` §4d diffs it
> against this section in both directions and across both spellings.
> ⚠ **Rate limits are per ACCOUNT, not per key** (same reading): 40 requests/minute on
> `sarvam-105b` chat at the Starter tier, pooled across every key on the account — a second
> key buys no capacity.

⚠ **Every LLM rate above is the vendor's published LIST price and none of them is what a
bill is computed from.** The authoritative billing figure is an **operator attestation** —
the founder's reading of his own invoice, entered in the ops console — because a list price
is not what an account pays: Azure's mandated **Regional Standard** deployment is
vendor-confirmed at **+10%** on the two rows above (`$0.165/$0.66` and `$0.44/$1.76` in East
US 2, read 23 Aug 2026), Gemini 3.6/3.7 Flash carry a dated 2x step on 1 Jan 2027, and
negotiated rates appear on no page at all. These rows are the **margin model**: they are what
`scripts/check_docs_drift.py` scores against `llm_cost_inr_per_minute`, which reads the
catalogue reference deliberately so the figure is identical on a laptop, in CI and on a
founder's screen. `billing/rates.py::llm_inr_per_ktok` is the billing door and it **raises**
for a model nobody has attested — an unpriced minute is unmetered spend, not a free one.

### 10.3 Reconstructing Outpero's economics (why their ₹3/₹5/₹7 tiers work)

> **SUPERSEDED where it proposes a voice-quality ladder.** Our own voices are two rungs chosen
> per agent (D-547, D-687): **Clear** (ThinnestAI's own stack) and **Studio** (Cartesia on our
> key through ThinnestAI), on the card in BRD §6.1 (D-728: ₹4.50 and ₹6.00 on every pack). The
> v2 and v3 Sarvam figures below are the historical inputs this reconstruction was built on,
> and Outpero's own `rates.sarvam_per_min` is THEIR bundle's symbol for THEIR tier and was
> never ours. Whether Studio's Telugu beats Clear's is the ear test (OPERATIONS §2 gate T-6).

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

> ⚠⚠ **"SARVAM IS THEIR CHEAPEST TIER" IS TRUE AND HAS ALREADY MISLED A READER OF THIS
> DOCUMENT. THE VENDOR IS NOT THE MODEL.** On 6 Sep 2026 a session read that sentence and
> concluded that Outpero sell *"the identical Sarvam voice at ₹3/min — same inputs, 40%
> cheaper"*, and carried that into a pricing recommendation. It is wrong, and the arithmetic
> in this very section is what refutes it: **a ₹3/min tier cannot carry a Sarvam v3 TTS
> leg.** §10.1 prices v3 at **₹1.08–1.62/call-minute** and v2 at **₹0.54–0.81** (v2 was live
> at half the v3 rate). Add STT ₹0.50, an LLM leg and any telephony, and ₹3 does not close
> on v3 at any plausible margin; on v2 it closes at roughly break-even.
>
> **FOUNDER EAR-TEST, 6 Sep 2026 (FOUNDER-OBSERVED, relayed):** the ₹3 tier "literally
> robotic voices". That is consistent with **Sarvam TTS v2** and not with v3, and it is the
> evidence that settles which Sarvam model sits behind `rates.sarvam_per_min`. Their ₹7
> premium is Cartesia; so is our Studio voice. On the D-728 card our Clear voice is ₹4.50,
> ₹1.50 above their cheapest tier, and Studio is ₹6.00, under their ₹7 premium on every pack.
>
> So the honest competitive line is **not** "they undercut us on the same voice". ⚠ **WHAT IS
> STILL UNVERIFIED, AND MUST NOT BE WRITTEN AS FACT:** whether our Clear voice *matches*
> Cartesia's quality on Telugu. That is an ear judgement nobody in this tree has
> made on Telugu clinic sentences (§5 already lists it as "ear-test at verification"), so
> "premium voice at the standard price" stays a claim awaiting a dated founder attestation.
>
> **THE GENERAL LESSON, which is why this note is this long:** the tier table above is
> VERIFIED evidence about *which vendor* serves each rung, and says nothing about *which
> model*. A verified fact read one field wider than it was measured is exactly the hard
> rule 11 failure the rule was written for, and it happened here to a reader who had the
> refuting numbers on the same page.

| Input | Value | Confidence |
|---|---|---|
| STT (Sarvam) | ₹0.50/min | **verified rate** |
| LLM (Sarvam 105B) | ⚠ **NOT ₹0.00** — ₹29.28/₹10.98/₹73.20 per 1M in/cached-in/out (founder's dashboard reading, 27 Aug 2026; the "free per token" figure this row carried is withdrawn — see §10.1's correction note) | **VENDOR-PUBLISHED** *(theirs; ours moved to a paid leg at D-400, to Azure OpenAI at D-410 and to `eastus2` at D-449, so this row is a statement about a COMPETITOR's inputs and not about ours)* |
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
   selectable on Bolna). Our own rungs are chosen by measured Telugu quality rather than by their ordering.
2. **Sarvam is their *cheap* tier, which is a positioning fact worth knowing.** They sell
   Cartesia as the premium "native Telugu" experience. Whether Cartesia actually beats
   Sarvam TTS v3 on Telugu is an **ear test we should run** — if it does not, their premium tier
   is a pricing story rather than a quality one, and that is directly usable in a sales
   conversation. If it does, we should adopt Cartesia for our own premium tier.
3. **What their economics prove is nothing about orchestration** — only that a competitor
   retails Sarvam-served calls at ₹3/min. Since our Sarvam-served cost is ₹1.04–1.31/min in
   models plus telephony, **₹3/min retail is reachable for us too whenever the platform fee
   allows it.** That is the number to hold them to, and the one the Bolna BYOK fee decides.

### 10.2 Effective cost per minute WITH fixed monthly costs amortized

The ₹2.89–4.28 own-stack range (as §10.1 derived it in Aug 2026) is **variable cost only**. It is not what a minute actually costs us
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
40–60% ratio) it is broadly cost-comparable to Sarvam TTS v3 while removing a single point of
failure and hedging that model's unpinned beta price. Caveats to verify: Cartesia plans are
**credit pools** (the per-product minute figures assume the whole pool goes to that product,
so TTS and STT allowances are not simultaneously available), concurrency is tier-capped
(TTS 2–15), and **Telugu voice quality is an ear test, not a docs claim**.
Phase triggers (numeric, pre-committed):
- **Phase 2 (own orchestration on CPU hosts — models stay APIs):** when
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
| TTS | ₹0.54–0.81 (Sarvam TTS v2) · ₹1.08–1.62 (v3) | *in the fee (Sonic 3.5)* |
| LLM | ₹0.00 → **+₹0.16 (D-410, five-minute)** | ₹0.00 → **+₹0.16** (BYOK; Cartesia's own LLM line is "free for a limited time" — do not model on it) |
| Telephony, blended in/out | ₹0.50–1.35 | ₹0.50–1.35 |
| **Variable total** | **₹3.30–4.42** (v2) · **₹3.84–5.23** (v3) | **₹5.78–6.63** |
| Midpoint used below | **₹3.87** (v2 stack) | **₹6.21** |

> ⚠ **THE TOTALS AND MIDPOINTS ABOVE HOLD THE LLM LEG AT ₹0.00 ON BOTH SIDES, AND THAT IS
> DELIBERATE RATHER THAN STALE (D-400, repriced by D-410).** The leg is no longer free —
> `gpt-4o-mini` on Azure OpenAI East US 2 costs ₹0.10–0.24 per minute
> depending on call length (§10.1) — but it is BYOK on both platforms and therefore
> identical on both, which is exactly the class of input D-32's method removes from a
> platform comparison. Adding the same figure to each column moves both midpoints and moves
> the DELTA by nothing, so the break-even arithmetic below is unaffected. **What it does
> move is the absolute floor**, and §10.1 is where that lives: read the all-in number from
> there, never from this table.

Fixed monthly: infra ₹8,500 + ~₹300/client DID rental *(assumption — the Indian carrier
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
2. **The larger lever is Sarvam TTS v2 vs v3** — ₹0.68 vs ₹1.35 at the midpoint, which is
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
| BYOK TTS | yes (Sarvam) | **no** (Sonic) | agent voice picker becomes a lie unless capability-driven |
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
works, an Indian carrier (Exotel class) can front Line and the exit is live. If it
does not, §10.4a's window is unreachable regardless of price. **Ask this before anything
else; it is cheap to ask and it gates everything downstream.**

**Pre-committed triggers, in the style of §10.2's phase gates.** Re-evaluate the
orchestrator when ALL of:

1. sustained volume **> 12,500 min/month** (§10.4a's crossover), AND
2. Line **BYOC SIP from an Indian DLT-registered carrier is confirmed in writing**, AND
3. **Sonic Telugu passes the same ear test Sarvam TTS passed** for D-36 — a spec claim about
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

> ⚠ **THIS SECTION IS ABOUT CARTESIA THE ENGINE (Line), NOT CARTESIA THE TTS VENDOR.**
> D-547 adopted **Sonic 3.5 as our second voice on Bolna** — a MODEL-layer purchase, a
> `CARTESIA` credential in the engine's provider store, and a synthesizer block in
> `apps/api/engine/bolna.py`. It did **not** adopt `apps/api/engine/cartesia.py`, did not
> reopen the orchestrator decision, and changes nothing below. The two decisions share a
> company name and nothing else; §10's platform table now says so at the row itself.

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

### 10.7 Embedding cost is per document, not per minute

No ThinnestAI call buys an embedding of ours: in-call knowledge is ThinnestAI's own knowledge
base (D-689), and caller lookups at call start read our own tables. Our embedding traffic is:

- **Knowledge projection**, once per document version at publish: `kb_chunks` is embedded by
  `workers/kb_embeddings.py` with `retrieval/embedding.EMBEDDING_MODEL`
  (`text-embedding-3-small` on the existing Azure OpenAI resource, §6). A 50-page knowledge
  base is roughly 25,000 tokens (ESTIMATE).
- **Dashboard and CRM search**, one query embedding per search that reaches the dense arm.
- **Caller memory buys no embedding.** Its write, `workers/caller_memory_distil.py`, is an
  hourly chat completion after the call, metered through `record_ai_assist_usage`, so it
  reaches the client's bill and their spend cap can stop it.

**Hard rule 7 gates every one of them.** An embedding is bought only once its model's price is
attested (`retrieval/embedding.embedding_price_is_billable`); until then the leg is a no-op and
nothing is charged. When rupees are spent they are visible per client and separately from
dashboard AI, on the admin spend board (`AbsorbedAiSpendOut.kb_used_inr`) and on the client's
own screen (`AiQuotaOut.kb_used_inr`).

**What an attested price would cost is not a number anybody here has.** The volume scales with
what clients upload, not with how much they are called, and there is no client upload figure to
multiply; the formula is tokens published × the attested input rate, and the multiplicand is
UNKNOWN until there are clients uploading.

**If Supermemory is adopted (§6.3), the cost to watch is its ingestion, not embedding.** A
50-page document is about 200 chunks, each drawing a chat call far larger than an embedding call
(ESTIMATE). Ingestion must therefore be QUEUED, never inline: one client uploading a 300-page
manual must not sit in front of another client's work on a small box.

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
snapshots; storage versioning; RTO 4h / RPO 30min (D-928). Load: 20 concurrent calls v1 headroom
(engine handles media; our webhook path must be O(ms)). All external calls have timeouts +
circuit breakers; webhook handlers ack fast and defer to workers. Everything (including
DLT template text and system prompts) lives in git.
