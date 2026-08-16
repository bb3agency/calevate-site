# Calevate — Backend Construction Patterns (CORE BLUEPRINT)

Version 1.0 · July 2026. **This is the construction manual for every Python service
— read it with TRD and DATA-MODEL before writing backend code.** It is part of the
authoritative docs set and binding the same way; changing a pattern here requires a
decision-log entry (D-30 records this doc's adoption, nothing more).

Source: architectural survey of the raghava-organics production backend
(Fastify/TS/Prisma/BullMQ — patterns proven under live traffic) translated to our
stack (FastAPI/SQLAlchemy 2.0 async/ARQ), plus 2026 industry practice. Prescriptive
for `apps/api`, `apps/voice-runtime` and `apps/workers`; ADOPTED = do it,
ADAPTED = same idea different mechanics, SKIPPED = considered and rejected with reason.

## 1. Module anatomy (ADOPTED)

Per domain module (`apps/api/<module>/`): `routes.py` (endpoints + guards + response
models + rate-limit profile), `service.py` (business logic AND queries — **no
repository layer**; raghava runs ~25 domains this way and a repo layer would be
ceremony for a 2-person team), `schemas.py` (Pydantic request/response models — the
response model IS the output whitelist), `models.py` (SQLAlchemy). Tests colocated,
**one file per behavior** (`service_create_lead_dedupe_test.py`), not one giant
per-service file — raghava's orders service has ~30 such files and it keeps failures
legible.

Ports for external systems are Protocols in `packages/shared` (VoiceEngine already
exists); adapters live in the owning module (`engine/`). Services receive deps via
FastAPI `Depends()` — no globals, no singletons; async `AsyncSession` per request.

## 2. Locked bootstrap order (ADOPTED — deviations need a decision entry)

1. Bootstrap-env validation (DATABASE_URL/REDIS_URL class only — fail fast)
2. Tenant-safe config load (Pydantic Settings)
3. Tracing init (OTel) before the app exists
4. App build: body limit, **log redaction path list** (authorization, cookie,
   `*token*`, `*secret*`, phone fields), trust-proxy as a CIDR-driven predicate
5. Middleware/plugins in FIXED order: security headers → CORS → auth → rate limit →
   error handler → observability (correlation id) → routes
6. **Raw-body preservation for webhook routes** (voice-runtime): HMAC must see exact
   bytes, so the JSON parser keeps the raw buffer for `hooks.*` paths — raghava does
   this for exactly 3 webhook paths; we do it for the engine webhook path
7. Signal handlers: SIGINT/SIGTERM graceful drain; unhandled-exception handlers that
   alert THEN exit (never swallow)

Workers repeat the same boot sequence with a **tolerant contract** (ADOPTED): workers
hard-require only DB + Redis; a missing provider key must NOT crash-loop every queue —
completeness is enforced at `/health/ready` instead (see §6).

## 3. Errors (ADAPTED to RFC-9457)

We already decided problem+json; raghava's normalization ladder maps onto it as
extensions: `kind` (validation|auth|permission|business_rule|dependency|transient|
internal), `retryable: bool`, `remediation`, `trace_id`, and validation failures as
`fields[{field, rule, message}]`. The ladder to copy:
- Internal 500s: full detail logged server-side (redacted), generic body to client.
- 429 carries `Retry-After` from the limiter.
- 503 is the ONE status allowed to keep its detailed message (ops-UI contract).
- Every 5xx also fires the alert path with a `failure_stage` tag (§8).
Correlation id: accept `X-Correlation-Id` else generate; echo on response; stamp into
audit rows and, when an LLM-tracing pipeline exists, its traces (none does — D-49). Response models `extra="forbid"` everywhere —
serialization is the whitelist the redaction-exposure guardrail checks.

## 4. Idempotency + outbox + inbox (ADOPTED — the reliability triad)

**Idempotency table** (client-initiated mutations: call-this-lead, campaign launch,
KB publish): unique `(scope_key, route, method, idempotency_key)`; `scope_key` is an
HMAC fingerprint of tenant/user under `IDEMPOTENCY_SCOPE_SECRET` (raw ids never stored;
required outside `local`, since a keyed hash is a pseudonym only while the key is
secret, and NEVER accepted from the wire — it is derived from the verified principal, so
a predictable value cannot be submitted); `request_hash` of the body —
same key + different body = 409; `PROCESSING` in-flight = 409; `COMPLETED` = replay
stored response with an `Idempotent-Replayed: true` header; `FAILED` retried via
compare-and-swap. TTL ~24h.

**Outbox** (reliable side effects — notifications, outbound webhooks D-23, engine
calls triggered by domain writes): `outbox_messages(queue, job, payload, status
PENDING|PUBLISHED|FAILED, attempt_count, last_error)` written IN THE SAME TRANSACTION
as the domain write. ARQ dispatcher polls PENDING (oldest-first, batch 50), claims
rows via conditional UPDATE (rowcount 0 = another worker won), publishes, marks; ≥5
attempts → FAILED (= outbox DLQ) + alert; an ops "replay dead letter" action flips
FAILED→PENDING with an audit note. Emit `outbox_lag_seconds` and DLQ depth as metrics
— they become SLO recording rules later.

**Webhook inbox** (formalizes SURFACES §3.1 dedupe): `webhook_inbox_events(provider,
event_key UNIQUE-with-provider, payload_hash, status PROCESSING|ENQUEUED|PROCESSED|
FAILED, last_error)`. Claim on arrival (insert, or CAS FAILED→PROCESSING on retry);
**same event_key + different payload_hash = 409** (spoof/corruption signal); Redis
SETNX stays as the fast-path front door, the inbox row is the durable truth.

## 5. Concurrency doctrine (ADOPTED)

The pervasive primitive is **compare-and-swap via conditional UPDATE**: write the
guard into the WHERE clause, treat `rowcount == 0` as "lost the race" → 409 or skip.
Used for: outbox claims, inbox claims, idempotency retries, status transitions
(campaign draft→launched, lead status), invitation burn. State machines get a central
transition table + `INVALID_STATUS_TRANSITION` error (campaigns, calls, leads) with
explicit compensation jobs.

**Serialization where a chain needs strict ordering** (audit chain §7, `credit_ledger`):
`pg_advisory_xact_lock(hashtextextended('<key>', 0))`, NOT a Redis mutex. Both chains
append INSIDE the caller's transaction, and correctness requires that no second writer
read the head between our read and our COMMIT — a window of unknown length, which a
TTL-bounded lease cannot cover and a `SET NX PX` lease will silently outlive. An
advisory xact lock is released by COMMIT *or* ROLLBACK, i.e. by exactly the events that
decide whether the row exists, so there is no TTL to tune and no second system whose
outage forks the chain. Reach for a Redis mutex only where the critical section is NOT
a database transaction. See D-59 and `apps/api/compliance/audit.py`.

## 6. Health & readiness (ADOPTED)

Three endpoints per service: `/healthz/live` (no dependency touch), `/healthz`
(DB SELECT 1 + Redis PING; 503 problem+json when degraded), `/healthz/ready` adds:
queue depth + oldest-waiting age (stale-worker detection), and
`runtime_config_missing_keys` — the go-live gate that tolerant worker boot defers to.
Single `degradation_mode` enum, priority-ordered (db_down > redis_down > queue_stale >
config_missing > none) so dashboards get ONE word. Missing config keys render as
validation-style `fields[]` entries — one shape for "something's not right".

**THE VERDICT IS PUBLIC, THE DETAIL IS NOT (D-128).** A probe carries no credential, so
the status code and the status word answer everybody; `degradation_mode`, `checks`,
`queue` and `fields[]` answer only a caller who proves `ops:manage`, because
`fields[].field` NAMES the credentials a deployment has not installed and that is a
targeting oracle on an unauthenticated, rate-limit-exempt, publicly-proxied endpoint.
The gate is injected into `build_health_router`, never imported by it (voice-runtime's
pinned import surface), so a service with no auth layer discloses nothing to anybody.
Whatever is withheld is written to a `health_not_ready` WARNING instead — during
`db_down` nobody can authenticate, and a red light with no next step is its own outage.

Load-shed guard (big red switch's engineering face): mode normal|reduced|emergency|
maintenance durable in Postgres + Redis cache + 5s in-process memo;
ALWAYS_ALLOWED_PREFIXES = health, schema/docs, engine webhooks, ops/admin surface — the
operator must never lock themselves out, provider callbacks must always land, and the
platform must stay observable while degraded. Those three reasons are the whole list;
**a route is never exempt for being important to a customer**, which is what shedding
is for. It USED TO INCLUDE `/v1/auth` "so sign-in survives a shed", and that named a
route this API does not have — Clerk owns sessions (§7), and the one route the prefix
actually covered was `POST /v1/auth/signup`, a four-table write that kept manufacturing
tenants in the modes that exist because we cannot serve the tenants we have. An
exemption is per-prefix and inherited by whatever lands under it, so the reason is
recorded per prefix and asserted against the live route table
(`tests/loadshed_exemption_test.py`).

## 7. Auth & audit specifics worth copying (ADAPTED — Clerk owns sessions)

Clerk replaces raghava's hand-rolled JWT/refresh machinery (their rotation-with-grace
+ reuse-detection design is the reference if we ever self-host auth). Still ours to
apply: guards re-check `is_active`/ban state against the DB on sensitive surfaces
(instant deactivation despite cached sessions); **step-up confirmation** (fresh OTP /
Clerk re-auth bound to the specific action) for high-risk admin actions — big red
switch, cap raises, raw-transcript access; RBAC as a **policy registry validated at
boot** (endpoint→permission map asserted at startup, not discovered at first use) —
pairs with our route-discipline guardrail.

**Audit hash chain** (ADOPTED for `audit_log`): each entry's hash =
HMAC(`AUDIT_CHAIN_SECRET`, previous_hash + entry), written under
`pg_advisory_xact_lock('audit:chain')`
held on the caller's transaction (§5). **The head has exactly one home: the last row of
`audit_log`.** It is deliberately NOT cached in Redis — a head published inside the
caller's transaction is erased by a ROLLBACK, and one published after COMMIT is lost by
a process that dies in the gap; either way the next writer forks the chain off a head
that is not there, which is a durable break in the artefact whose whole purpose is
being unbreakable. Validating the cache against the table is the query the cache
existed to avoid, so there is no cache. `(at, id)` is indexed (`ix_audit_log_chain`)
because both the head read and the verification walk are ordered by it. The per-entry
JSONL artifact is the structured log stream (`audit.write` events), which is shipped off
the box and is therefore the second copy the chain is compared against. Makes tampering
detectable — strong DPDP/dispute evidence at trivial cost. Summary sanitizer:
depth-capped, length-capped, key-pattern-redacted before persisting.

`GET /v1/ops/audit/verify` walks the WHOLE log by default and reports
`entries_checked` / `complete` alongside the verdict: a bounded walk that renders as a
plain green tick is a verification of the part nobody was worried about.

**THE SIGNING KEY IS REQUIRED AND VERIFICATION WALKS A KEY RING.** `AUDIT_CHAIN_SECRET`
is mandatory outside `local` (>=32 bytes — RFC 2104 §3, NIST SP 800-107 Rev. 1 §5.3.4 —
with a present-but-short key refused exactly like an absent one, via the one ladder in
`core/settings.py::resolve_hmac_key`); absent, the API refuses to write or verify an
entry and `/healthz/ready` is red. It used to fall back to the constant
`local-dev:{app_env}` in EVERY environment, so a deploy that forgot it signed its
evidence with a string printed in the source.

Requiring it is only safe because verification dispatches PER ENTRY on which key
reproduces it, oldest generation being that same public constant. A chain outlives its
key, and a verifier that knows only the current one reports the whole history as
`content`-broken — every prior row, not one boundary — which would make our own deploy
manufacture the signal the ledger exists to produce. Rotation is therefore supported
rather than a drill: put the outgoing value in `AUDIT_CHAIN_SECRET_RETIRED` in the same
deploy. `entries_under_retired_key` on the verdict counts entries that verified under a
retired generation — intact, but attested only as well as that generation's key was
secret. **No entry is ever re-signed**: `audit_log` is append-only (hard rule 4) and
rewriting hashes from current content would launder tampering into a clean chain.
Monotonicity is enforced — an entry may not verify under a generation the chain has
already moved past — because generation 0 is public and would otherwise be a forgery
key for recent rows.

**Idempotency scope fingerprints have their OWN key** (`IDEMPOTENCY_SCOPE_SECRET`, §4),
not the chain's, which they used to share: that fingerprint must stay stable — changing
it makes in-flight `Idempotency-Key`s miss their stored record, so a retry re-executes —
and the chain's key is the one that rotates.

## 8. Alerting & metrics taxonomy (ADOPTED)

One alert function with a normalized `failure_stage` enum (ROUTE_HANDLER | CORE_LOGIC
| QUEUE_ENQUEUE | OUTBOX_DISPATCH | WORKER_DELIVERY | WORKER_TERMINAL | WORKER_STALL
| PROCESS_RESTART | HOST_BACKUP) — "where in the pipeline did this die" answerable without
reading code. `HOST_BACKUP` is not an application stage: it is the host-side backup chain
(D-50), emitted by `scripts/backup/notify.sh` from outside Python entirely, so no Python
call site passes it. It exists as a member rather than being mislabelled as
`WORKER_TERMINAL` to make it fit, because a wrong
stage on the one alarm that says the database is unrecoverable is the wrong place to be
tidy. **`alert()` DELIVERS** as well as logs (D-49): the ERROR log line first and
unconditionally, then email off the request path, with per-fingerprint suppression and a
global hourly bucket. It is the one side effect in this document that deliberately does
NOT go through the outbox of §4 — the alarms that matter most are the ones saying the
outbox is broken, so it touches no database and no Redis. Every call site passes a STABLE
code rather than a formatted string, because the code is the deduplication key.
Metrics are **named domain recorders** (`record_pipeline_lag`,
`record_webhook_ack_ms`, `record_extraction_failure`, `record_outbox_lag`), not
ad-hoc counters — the recorder names become the SLO rule vocabulary (OPERATIONS §4).

## 9. Testing structure (ADOPTED)

Suffix taxonomy: `*_test.py` (unit) / `*_integration_test.py` / `*_security_test.py`,
colocated with source; pytest markers mirror raghava's vitest split. Coverage ratchet
scoped to the HIGH-RISK surfaces (tenancy, billing, compliance, pipeline) rather than
a repo-wide number. Seams: worker/job factories accept a deps object; services take
injected sessions — partial fakes must typecheck. Fixtures as scripts with paired
cleanup (their seed/cleanup pattern), golden-transcript fixtures for extraction.

## 10. SKIPPED (considered, rejected)

- **Repository/DAO layer** — services own their queries; the swap seam is at
  EXTERNAL boundaries (VoiceEngine, RAG provider), not between us and our own DB.
- **Response envelope `{success, data}`** — RFC-9457 for errors + plain typed
  payloads for success is already decided; the envelope adds nothing typed clients need.
- **Their ops-config DB overlay for OUR bootstrap config** — Clerk + secrets-manager
  references (SEC-COMP §5) cover it; the overlay pattern IS the reference
  implementation for per-tenant engine/BYOK key storage (AES-256-GCM, versioned key,
  masked display, restart-to-apply).
- **BullMQ specifics** (repeatable-job jobIds, pause/resume recovery) — ARQ
  equivalents exist; the DISCIPLINES transfer (DLQ keeps failures forever, dedicated
  pub/sub connections, drain-then-quit shutdown), the APIs don't.

Cross-references: TRD §1 (modules) · SURFACES §3 (integration doctrine this deepens) ·
ENGINEERING-PRACTICES §2 (guardrails that enforce this doc) · DATA-MODEL (tables for
§4 land in M1 migrations) · ROADMAP D-30.
