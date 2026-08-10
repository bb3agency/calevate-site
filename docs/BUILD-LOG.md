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

### Where the next session should start

1. `docs/ROADMAP.md` §2 — remaining M1: **notification transport** (email;
   `notifications.py` deliberately returns False rather than faking a send),
   **observability wiring** (Sentry, Langfuse, OTel — `bootstrap.py` marks the spot and
   does not stub it), and the wizard's **intake step** (FLOWS §1 step 3), which needs
   client #1 in the room rather than more code.
2. Everything gated on the **Bolna pilot** (OPERATIONS §2) is deliberately unbuilt:
   number provisioning, transfer, the test-call gate, real latency numbers.
3. Run `bash scripts/dev_bootstrap.sh`, then `uv run pytest -q` (87 tests) and
   `make guardrails` before changing anything.
