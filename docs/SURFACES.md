# Calevate — Surfaces & Integration Patterns

Version 1.0 · July 2026. Three parts, per the product framing: the **admin panel**
(authoritative, operated by us), the **client-facing CRM** (SaaS-like, near-identical per
client, Outpero is the floor — teardown in BRD §5), and the **integration layer** with
the rented engine — Bolna per D-31 (no compromises).

Status of each section: §1 and §2 are researched FEATURE INVENTORIES that seed the
build-time design discussions — items here are candidates, not commitments, unless they
carry a decision-log reference. §3 is DECIDED engineering doctrine.

---

## 1. Admin Panel (admin.calevate.tech) — inventory for the build-time discussion

What it is: the operations console for a managed voice-agent business. It does NOT
replicate the client UI; it shows operational internals the client never sees.
Already decided: two-realm auth (TRD §11), admin roles superadmin|operator, MFA,
read-only audited impersonation (D-22), always-audited admin reads (SEC-COMP §5).

Client lifecycle
- New-client wizard (FLOWS §1) with draft/resume; compliance status surfaced per step.
- Account lookup with full operational context: org, plan, engine refs, numbers,
  DLT state, caps, credit balance, recent errors — one screen per client.
- Controlled mutations with audit: plan changes, credit adjustments (compensating
  entries, never edits), cap raises, suspend/reactivate, offboarding trigger.
- Batched onboarding pattern (industry: weekly cohorts once client count grows).

Tenant health board (the core admin screen — industry-standard for voice agencies)
- Per-client tiles: call volume, answer rate, latency p50/p95 vs budget, pipeline lag,
  error rate, spend vs cap, engine webhook delivery health.
- Alert-before-the-client-notices doctrine: latency drift, answer-rate dips, and
  webhook failures alert us first (OPERATIONS §4 alert list).
- QA sampling: spot-check ~5% of calls per client per week (queue surfaced in admin;
  ties into the regression harness and knowledge-gap reports).

Engine & config management
- Per-client engine refs (agents, numbers, KB attachments), BYOK key status,
  staging→live promote (maps to engine draft/publish), prompt version history +
  rollback, extraction schema editor (admin-only, D-21).
- Secrets: references only, never values (SEC-COMP §5); key rotation reminders.
- Per-tenant feature flags (config rows, TRD conventions) — enable beta features or
  debug modes per client without deploys.

Commercials
- Margin per client (usage_events cost vs plan revenue — the D-12 payoff).
- Invoice run surface (M2); dunning states; usage anomaly review.

## 2. Client CRM (app.calevate.tech/c/<slug>) — inventory for the build-time discussion

Floor: everything in the Outpero teardown (BRD §5). Already decided: schema-driven
Leads table (D-09), fixed status enum + admin-only schemas (D-21), "Call this lead"
with context note (M1), AI callback on needs-follow-up (M2), outbound sync (D-23),
staff/owner role split (SEC-COMP §5).

Table UX (2026 CRM patterns worth adopting when we build)
- Saved views: named filter+column combinations per user (e.g. "Hot this week").
- Inline edit for status and assignment (exit via Enter/click-out; no modal for
  single-field edits); full record in a detail drawer, not a page navigation.
- Bulk actions with the researched guardrails: progress indicator, result summary
  (n succeeded / n failed), inline warnings before destructive/irreversible batches.
- Faceted filters driven by the extraction schema (enum fields → facet values).
- Column chooser mirrored in CSV export (choose-what-you-export, Outpero parity).

Dashboard (role-adaptive; the 2026 pattern is "prioritized operating surface")
- Owner default: outcomes + spend (calls, resolved-by-AI %, after-hours captured,
  minutes used vs included, hot leads awaiting action).
- Staff default: work queue (needs-follow-up first, repeat callers flagged).
- Live tiles for in-progress calls (transport: §3.2).

Trust surfaces (our differentiators made visible)
- Per-call: transcript (redacted by default), recording player, AI summary, extracted
  fields, latency badge.
- Monthly QA report (D-15) rendered in-app, not just PDF.
- "Why customers call" themes and knowledge-gap-driven "your agent couldn't answer
  these" list — turns T4 refusals into KB update requests.

## 2b. Self-serve surfaces (D-34) + patterns adopted from the Outpero teardown

Lands M2 (D-39: schema in M1, surface when a user needs it). These are **additions to the
same client app** — a self-serve org is the same `organizations` row with a different
`plan_tier`, so nothing forks.

**Self-serve-only screens**
- **Sign-up + org create**: email/password or Google (FLOWS §2), slug validated against
  `reserved_slugs`.
- **Credit wallet**: balance, **runway in minutes** ("₹X · ≈ N min, M min on premium" —
  their money-UX is genuinely good), top-up packs, auto-receipt with GST.
- **Plan/usage**: agents live vs draft, minutes used, spend against cap.
  - **Spend cap, client-editable** — `GET /v1/billing/caps` (`billing:read`) and
    `PUT /v1/billing/caps` (`org:manage`; mutating, so D-22 refuses an impersonating
    admin). There are TWO caps per plan: `hard_cap_min`/`hard_cap_spend` are admin-owned
    and `client_cap_min`/`client_cap_spend` are the client's, and the effective ceiling
    is `LEAST(admin, client)` with NULL meaning "no constraint from this side". A client
    may lower theirs to anything including zero and may clear it (falling back on the
    admin's), and may **never** set one looser than the admin's —
    `client_cap_exceeds_plan_cap`, refused rather than clamped. A cap set BELOW this
    month's spend is accepted and **binds immediately**: the write recomputes
    `spend_state.capped` from the counters already in the row, so the next dial is
    refused rather than the dial after the next call happens to meter. Inbound is
    unaffected — the gate is outbound-only — which is what makes an immediate stop a
    safe control to hand a client. The reasoning is in `apps/api/billing/caps.py`.
  - **Two overage rates.** `plans.overage_rate_value` prices the value TTS rung
    separately (D-36's ladder; `usage_events.meta.tts_tier` already says which rung a
    call ran on). **NULL means the plan quotes no separate value rate — everything bills
    at `overage_rate`**, which is every plan that predates the column, so no bill moved
    when it landed. The included allowance is consumed on the DEARER rung first, leaving
    the cheaper minutes to be charged for, and unattributed minutes bill at the value
    rate (the same honesty rule `billing/rates.py` applies to cost). The invoice prints
    one line per rung so each still multiplies out. **No retail value rate is set
    anywhere in the codebase** — TRD §10.1's bands are unmeasured, so the number is a
    founder decision, not a derivation.
- **Number purchase + KYC**: gated; calling stays disabled until verification clears.

**Patterns worth adopting (evidence: teardown §9c/§9d — all verified in their product)**
- **"Needs attention" queue** — leads on hold or awaiting retry, with early release. This
  is the operational work-queue our dashboard inventory (§2) is missing; it belongs next to
  the Leads table for both motions.
- **Webhook activity view** — every inbound delivery shown as **accepted / deduplicated /
  rejected**, with the raw payload. Pair it with a **"Test webhook"** button that runs a
  sample lead end-to-end *without placing a call*. Together these are the single biggest
  integration-DX win available, and they cost us little because the reliability triad
  (D-30) already records everything needed.
- **Two-speed publishing** — script/flow/actions/webhook edits require an explicit
  **"Apply to live calls"**; voice, extraction fields and training apply immediately.
  Split by blast radius, with an unsaved-changes banner offering Apply or Undo. Nothing
  goes live silently.
- **Precedence rule, stated in the UI** — *script decides content, rules decide conduct,
  voice only changes delivery*. Cheap to say, removes a whole class of support question.
- **Cost-runaway guard** — a per-agent max call length (their default 10 min, adjustable).
  We have no equivalent today and should.
- **Honest degraded-tier billing** — if a premium voice is unavailable the call runs on the
  cheaper voice and is **billed at the cheaper rate**, never silently upgraded.

**Where we deliberately go further** (teardown §9d table): HMAC-signed webhooks with
timestamp + replay protection (they use a URL-path token and an *optional* header);
outbox-backed delivery (publish retried up to `OUTBOX_MAX_ATTEMPTS` = 5 by the dispatcher,
plus a per-delivery ladder of `WORKER_MAX_TRIES` = 3 attempts at 30s/120s — no longer a
gap: the delivery worker raises `arq.Retry(defer=…)`, see §3.1 and the FLOWS §6 note), a
delivery log and **replay** (they fire
once and can arrive with null fields); a **published, versioned** outbound payload schema
(theirs is undocumented); **a direct lead-ingest endpoint** —
`POST /hooks/v1/ingest/{webhook_id}` with per-endpoint secret, field mapping and a
no-call dry run, no Zapier in the middle (*`meta_lead_ads` is today only a value of the
`inbound_webhooks.source` enum; a **native** Meta Lead Ads integration — their
`X-Hub-Signature-256` verification and the form-field mapping — is NOT built, so do not
claim it in sales copy yet*); typed+validated extraction (theirs is untyped — the "Delhi
in a quantity field" bug); full version history with diffs and audit (they keep 3
versions, no diff); and **DNC on every dispatch path** including instant, which is where
their compliance actually fails.

## 2c. Shipped today — no longer candidates

§1 and §2 above are inventories (candidates). This section is the short list of what has
actually landed, so nobody re-proposes a screen that exists. Verified against the route
tree in `apps/web/src/app` and the OpenAPI paths in `apps/web/src/lib/api/schema.d.ts`.

Client realm (`/c/<slug>/…`)
- **Leads** with a **list ⇄ board toggle** — the board is one column per D-21 status,
  so the "work the pipeline stage by stage" pattern is built, not pending.
- **`/performance`** (`GET /v1/performance`) · **`/attention`** (`GET /v1/attention` — the
  §2b "needs attention" queue, shipped) · **`/agents`** (read-only agent roster) ·
  **`/lead-sources`** (`GET /v1/lead-sources/activity`, `POST /v1/lead-sources/{id}/test` —
  the §2b webhook-activity view and its no-call "test webhook", shipped) ·
  **`/integrations`** (endpoints + delivery log) · `/calls`, `/campaigns`, `/knowledge`,
  `/usage`.

Admin realm (`/admin/…`)
- **Prompt history + rollback** per agent (`/admin/tenants/{id}/agents/{agentId}/prompt`;
  `GET|POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt`, `…/prompt/rollback`).
  Rollback is copy-forward, never pointer-rewind (FLOWS §7).
- **Printable invoice statement** (`/admin/tenants/{id}/invoice`;
  `GET /v1/admin/tenants/{tenant_id}/invoice`) — a white, print-first document. It is a
  DERIVED statement, not a stored row (see DATA-MODEL §8).
- **Credit top-up** (`POST|GET /v1/admin/tenants/{tenant_id}/credits`) — admin-recorded
  today; the self-serve wallet UI in §2b is still M2.
- **Ops** (`/admin/ops`; `/v1/ops/platform`, `/v1/ops/outbox/replay`, `/v1/ops/audit/verify`).
- **Calevate's own TM registration** (`POST /v1/ops/platform/tm-registration`, `ops:manage`)
  — the company half of SEC-COMP §3's first bullet, recorded on `platform_state` (D-43)
  and returned by `GET /v1/ops/platform`. Step-up confirmed in BOTH directions, with the
  header naming which one: `X-Confirm-Action: record_tm_registration` to make it live,
  `withdraw_tm_registration` to take it out of `active`. Audited in the same transaction
  as the write. While it is not `active`, NO tenant can launch an outbound campaign,
  however complete their own PE registration is; inbound answering is unaffected.
- **Client DLT Principal Entity registration**
  (`POST /v1/admin/tenants/{tenant_id}/dlt-registration`, `admin:tenants`) — upsert; the
  fact `launch_blockers` reads as `pe_registration_*` / `tm_link_not_active`. Deliberately
  has no client-realm twin: a client who could mark their own PE registration `active`
  would be marking the launch gate green on a registration that does not exist. Tenant in
  the PATH, not inferred from the session — an admin-realm mutation that infers its tenant
  is un-callable by construction under D-22.

Compliance API (client realm)
- **DNC**: `GET|POST /v1/dnc`, `POST /v1/dnc/check`, `DELETE /v1/dnc/{entry_id}`.
- **DPDP subject export**: `POST /v1/compliance/subject-export`.
- **DPDP erasure**: `POST /v1/compliance/deletion-requests` (201; idempotent per open
  request — a duplicate is a 200-shaped body with `already_open`, not a 409) and
  `GET /v1/compliance/deletion-requests/{request_id}` for the proof certificate. Filing
  and status reads carry DIFFERENT permissions on purpose: filing is mutating, so D-22
  refuses it to an impersonating admin; a status read discloses no personal data and
  stays available to them. Every response carries the erasure's stated limitations
  (SEC-COMP §4). Both surfaces speak `subject_ref`, never the phone number.
- **Voice catalog**: `GET /v1/agents/voices` (D-36's premium/value ladder as data).
- **Consent provenance for a campaign list**:
  `POST /v1/campaigns/{campaign_id}/consent-provenance` (`leads:dispatch`, drafts only,
  audited) — SEC-COMP §3's fourth bullet, and the answer path for a draft created before
  the columns existed. It refuses on a non-draft campaign, so a declaration cannot be
  back-filled after the dialling it was supposed to authorise.

Self-serve + payments (D-34/D-39) — **read the caveat, this is not a working checkout**
- **Signup**: `POST /v1/auth/signup` (201). Under `rbac.PUBLIC_PREFIXES`, which is the
  honest classification: no permission can gate a caller who has no organization yet. The
  locks are a verified Clerk identity, a quota of 5 signups per user and 30 per IP per hour
  consumed on every
  ATTEMPT (a refused slug is not free — free failures are what make a limiter enumerable),
  and two switches: `self_serve_signup_enabled`, which **defaults to OFF** (R-11's kill
  switch — public tenant creation should be something someone switched on), and the
  platform load-shed mode, which `/v1/auth` is otherwise exempt from because that
  exemption is right for signing IN and wrong for signing UP. Creates the organization, its
  receptionist agent, its extraction schema and its retention policies, and makes the
  caller the owner; `plan_tier` is `self_serve` or `trial` — `managed` is the invoiced
  motion and is not self-assignable. The wallet starts empty, so the compliance gate
  refuses outbound until it is topped up, and the response says so in `next_steps`.
- **Top-up intent**: `POST /v1/billing/topups/intent` (`org:manage` — spending the client's
  money is not a read, and being mutating is what makes D-22 refuse it to an impersonating
  admin). Prices the top-up (₹100–₹100,000), binds it to the session's tenant, and refuses
  a `managed` tenant (`topup_not_available`) or a deployment whose payment capability is
  not configured (`payments_not_configured`). **Whether the capability exists is now a
  STATEMENT, not an inference**: `PAYMENT_PROVIDER` names it, `payments.payment_capability()`
  is the ONE selector both this route and the receiver ask (so a second read of settings
  cannot disagree), the only name with an adapter behind it is `razorpay` and any other
  resolves to `provider_not_implemented`, and a known provider still needs BOTH the key
  id and the webhook secret — a deployment that could take money and never credit it is
  refused on both surfaces. The refusal writes nothing. Same shape as the Google Sheets
  seam (§2 integrations). **NOT IMPLEMENTED: server-side order creation.** Creating
  the provider-side order needs API credentials this deployment does not hold, so the
  response carries `provider_order_id: null` and `provider_order_pending: true` — the gap
  is in the contract rather than discovered at integration time. There is no checkout that
  can be opened from this response today.
- **Payment webhook**: `POST /hooks/v1/razorpay` → one `credit_ledger` entry, signature
  verified before anything is read, inbox-claimed on `payment.captured:<payment id>` and
  idempotent on the ledger `ref` under the per-tenant credit lock. Never load-shed (a
  payment landing during degraded mode is still a payment); fails CLOSED with no secret
  configured. **The signing scheme and every payload path it reads are UNVERIFIED against
  a live Razorpay account** (`billing/payments.py` marks each one) — if they are wrong,
  every event is refused and nothing is credited. Treat the pair above as scaffolding with
  an honest hole in it, not as a payment flow.

Shared shape across all three compliance surfaces: a phone number is submitted in a POST
body and everything afterwards is keyed by an opaque id, never `GET /…/{phone}`. The
identifier IS the personal data, and a number in a URL lands in access logs, proxy logs,
referrers and browser history (hard rule 6).

## 3. Integration Layer (our site ⇄ engine [Bolna, D-31]) — DECIDED doctrine

The verified vendor surface lives in TRD §5 (events, HMAC, rate limits, Get Call).
This section fixes HOW we consume it. No compromises means: no lost events, no
duplicate side effects, no stale UI lying to a client.

### 3.1 Webhook intake pipeline (applies to every engine event)

Queue-first, idempotent, replayable — the industry-standard shape, mapped to our stack:

1. **Verify**: per engine capability (TRD §5). Signed engines: HMAC over raw body,
   timestamp window, timing-safe compare. **Bolna (unsigned)**: source-IP allowlist
   (13.203.39.153, via D-27 real_ip restoration) at nginx AND in-app; payloads are
   hints — truth comes from the authenticated Get Execution fetch. Unexpected
   source ⇒ 401 + alert (treat as attack until proven config drift — runbook).
2. **Dedupe**: replay-cache on the event key (Redis SETNX, 24h TTL; for Bolna:
   execution_id + status) AND idempotency keys on processing — dedupe at the door and
   at every side effect. Bolna delivery is at-most-once (no vendor retries), but OUR
   poller re-surfaces the same executions, so duplicates still occur downstream.
3. **Persist-then-ack**: write the minimal event row + archive raw payload to object
   storage, ack 2xx < 500ms. Never process inline (hard rule 3).
4. **Process async**: ARQ jobs keyed by event/call id; every side effect is an upsert
   or guarded by processed-state; **3 attempts**, outbound deliveries waiting 30s
   then 120s (`WORKER_MAX_TRIES` in `apps/api/core/queue.py`, `RETRY_BACKOFF_S` in
   `apps/workers/outbound_webhooks.py`); retried for transport failures / 5xx / 408 /
   425 / 429 only, any other 4xx stopping immediately as `rejected {code}`; DLQ +
   Sentry on exhaustion. ⚠ A plain `raise` in a worker is terminal on the first attempt
   under arq 0.28 — see the note in FLOWS §6 — so a job that wants the ladder must raise
   `arq.Retry`. The reconciliation poller in step 6 remains the guarantee of record
   either way (D-31).
5. **Replay tooling exists BEFORE the first incident** (industry lesson): admin
   surface to inspect webhook_deliveries, re-run a delivery, and re-run a pipeline
   step for a call id. The engine's own per-delivery retry API supplements ours.
6. **Reconcile**: Bolna webhook delivery has NO retries at all (verified: docs + OSS
   delivery code — single POST, errors swallowed), so the 10-min List-Executions
   poller (FLOWS §3) is the guarantee of record, promoted from safety net (D-31).
   Reconciliation closes the loop: exactly-once PROCESSING = idempotency +
   reconciliation, not delivery magic.

Outbound webhooks (us → client tools, D-23) mirror the same doctrine from the sender
side: our envelope, HMAC signing, the same flat 3-attempt ladder (`MAX_ATTEMPTS` is
`WORKER_MAX_TRIES` — deliberately ONE budget so the last try knows it is the last and the
`outbound_webhook_exhausted` alert has a moment to fire; the FLOWS §6 arq trap that made
that alert unreachable is FIXED — `deliver_outbound_webhook` raises `arq.Retry(defer=…)`,
so the ladder walks and the exhaustion branch is live), delivery log (webhook_deliveries direction=out, one
row per delivery with `endpoint_id`), and a per-endpoint disable switch on repeated
failure. The client-facing form of these rules is WEBHOOKS §1.5.

### 3.2 Real-time UI sync (D-24)

- **v1 (M1): TanStack Query polling.** Dashboard/leads refetch on interval + on window
  focus; post-call data appears within the 2-min SLO without any new infra. Boring
  solution first, per doctrine.
- **Upgrade (with M3 moat work): SSE, not WebSockets.** One `/events` stream per
  client session (live call tiles, lead-created toasts); server pushes invalidation
  hints, TanStack Query refetches — events carry "what changed", never payloads
  (avoids auth/staleness bugs in the stream). SSE chosen because our flow is strictly
  server→client, it's plain HTTP (no proxy/infra changes), and it's materially
  cheaper per connection than WebSockets. WebSockets are explicitly NOT planned — we
  have no client→server streaming need; revisit only via a decision-log entry.

### 3.3 Engine API usage rules (adapter-internal)

- Client-side throttle with 429 ⇒ backoff + jitter; Bolna's API/dispatch rate limits
  are unpublished (pilot) — OUR dispatcher paces outbound creation regardless
  (FLOWS §5), with the pilot-measured limit as the config value.
- Get Execution on `completed` (webhook and poller share the payload shape — TRD §5;
  cost/recording/extraction fields are null before `completed`); recording copy is
  the first pipeline step (Bolna URLs have no documented expiry — copy-first anyway,
  our storage is system of record).
- All engine calls carry timeouts + circuit breakers (TRD §12); breaker-open ⇒
  degrade to reconciliation mode, never drop work. **Shipped today: the timeout only**
  (`REQUEST_TIMEOUT_S = 10.0` in `apps/api/engine/bolna.py`). The 429 throttle above and
  the breaker are DECIDED and unbuilt — the dispatcher's own pacing and the
  reconciliation poller are what currently stand in for them, so treat both bullets as
  intent until an adapter carries them.
- No vendor OpenAPI spec (Bolna): typed adapter models are hand-maintained from
  docs.bolna.ai + pilot-captured payloads committed as fixtures; payload drift is
  caught by the conformance suite, diff-review before adopting new fields.

---

Cross-references: BRD §4–5 (scope + competitor floor) · TRD §5 (vendor surface) ·
FLOWS §3/§5 (lifecycles) · SECURITY-COMPLIANCE §5 (auth/audit) · ROADMAP D-21…D-24.
