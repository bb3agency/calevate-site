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
- `compliance/audit.py` — audit writer with the HMAC hash chain, Redis chain head under
  a compare-and-delete lock, `verify_chain()`. Writes in the CALLER's transaction so an
  audited read and its record commit together. Summaries go to the log stream, not the
  hashed payload (no summary column ⇒ hashing it would make the chain unverifiable).

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
- `extraction.py` — Sarvam (D-36 default) / Gemini (fallback, with its residency cost
  stated) / Offline deterministic. No silent failover between providers.
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
  against Gemini on these fixtures is exactly D-36's open question.
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

Also fixed: `pnpm lint` had never run. `eslint-config-next@15` still ships
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

### Where the next session should start

1. **Founder decisions, none of them code.** The retail value-tier rate
   (`plans.overage_rate_value` exists and is NULL everywhere); the retention TTL
   divergence (docs 24 months, seed 365/1095/90 — SEC-COMP §4 declares it open and names
   the founder); erasure vs the TRAI 90-day recording floor; a WhatsApp BSP, which is the
   single entry that unblocks the escalation path end to end.
2. **Gated on the Bolna pilot** (OPERATIONS §2) and deliberately unbuilt: number
   provisioning, transfer, the test-call gate, real latency numbers, and the KB questions
   at gate 8 (whether the list response carries agent linkage; whether deleting a KB
   clears the agent's reference).
3. **Known gaps with the evidence already gathered**: KYC-gated number purchase (D-34's
   last R-11 mitigation); `kb_retrieval_logs` has no producer and cannot have one until
   the engine reports a retrieval (dated in the model); T1/T2 tiers are absent by decision;
   and `inbound_webhooks` rows are still provisioned out-of-band because nothing writes
   them.
4. **The local database cannot reach head** and that is expected — see
   `runbooks/stale-dev-database.md`. Use a scratch DB; do not stamp past the credit-ledger
   index.
5. Run `bash scripts/dev_bootstrap.sh`, then `uv run pytest -q`, `uv run mypy apps packages`,
   `make guardrails` and `pnpm -C apps/web lint` before changing anything.
