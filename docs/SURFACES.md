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
   or guarded by processed-state; retries 3× exponential; DLQ + Sentry on exhaustion.
5. **Replay tooling exists BEFORE the first incident** (industry lesson): admin
   surface to inspect webhook_deliveries, re-run a delivery, and re-run a pipeline
   step for a call id. The engine's own per-delivery retry API supplements ours.
6. **Reconcile**: Bolna webhook delivery has NO retries at all (verified: docs + OSS
   delivery code — single POST, errors swallowed), so the 10-min List-Executions
   poller (FLOWS §3) is the guarantee of record, promoted from safety net (D-31).
   Reconciliation closes the loop: exactly-once PROCESSING = idempotency +
   reconciliation, not delivery magic.

Outbound webhooks (us → client tools, D-23) mirror the same doctrine from the sender
side: our envelope, HMAC signing, retry ladder with backoff, delivery log
(webhook_deliveries direction=out), and a per-endpoint disable switch on repeated failure.

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
  degrade to reconciliation mode, never drop work.
- No vendor OpenAPI spec (Bolna): typed adapter models are hand-maintained from
  docs.bolna.ai + pilot-captured payloads committed as fixtures; payload drift is
  caught by the conformance suite, diff-review before adopting new fields.

---

Cross-references: BRD §4–5 (scope + competitor floor) · TRD §5 (vendor surface) ·
FLOWS §3/§5 (lifecycles) · SECURITY-COMPLIANCE §5 (auth/audit) · ROADMAP D-21…D-24.
