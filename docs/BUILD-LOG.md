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

### Where the next session should start

1. `docs/ROADMAP.md` §2 — remaining M1: the wizard's **intake step** (FLOWS §1 step 3,
   which needs client #1 in the room rather than more code) and **OTel spans** (Sentry
   and the Langfuse hook are wired; distributed tracing is not).
3. Remaining M2 openers: WhatsApp alerts, self-serve signup UI, Razorpay top-ups into
   `credit_ledger`, outbound CRM sync (D-23).
4. Everything gated on the **Bolna pilot** (OPERATIONS §2) is deliberately unbuilt:
   number provisioning, transfer, the test-call gate, real latency numbers.
5. Run `bash scripts/dev_bootstrap.sh`, then `uv run pytest -q` (150 tests),
   `uv run mypy apps packages`, `make guardrails` and `pnpm -C apps/web lint` before changing anything.
