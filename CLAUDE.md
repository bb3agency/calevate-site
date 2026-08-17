# CLAUDE.md — Calevate Repository Guide for Claude Code

You are working in the Calevate monorepo: a multi-tenant AI voice-agent SaaS for Indian
SMBs (Telugu-first). Read `docs/README.md` for the full blueprint. `docs/` is the
authoritative blueprint and wins over everything else — when this file conflicts with the
docs set, the docs set wins; flag the conflict, don't silently pick. `docs/AGENTS.md`
mirrors this manual for other coding agents.

## What this system is (30 seconds)

Clients get AI phone agents (inbound receptionist + outbound campaigns) built on a rented
voice engine (Bolna primary per D-31) with BYOK models — **canonical stack per D-36**:
Sarvam Saaras STT · **Sarvam 105B LLM (free per token, all-India residency)** · Sarvam
Bulbul v3 TTS (v2 = value tier). **Gemini 2.5 Flash** runs the USER-TRIGGERED dashboard
AI through Vertex AI `asia-south1` (D-127 supersedes D-36's LLM leg for that surface
only) — 2.5 rather than 3.x because Mumbai is the only region D-127 permits and no 3.x
model is reported there, which is a founder's decision that buys a **live 16 Oct 2026
retirement** (BRD R-04, `GEMINI_DEFAULT_LLM_RETIRES`, OPERATIONS §2 gate 14). And
**`GEMINI_MODEL_CONFIRMED_IN_REGION is False`, so that sentence is still a decision and
not yet an observation**: search now points the right way, but nobody has made the one
call that settles it (OPERATIONS §2 gate 14). The first post-call
extraction stays on Sarvam permanently because it reads the raw
transcript — `GEMINI_EXTRACTION_DEFAULT is False` in `apps/workers/extraction.py`. Our
code = admin console, client dashboards,
schema-driven lead extraction/CRM, RAG knowledge bases, metering/billing, compliance
(TRAI/DLT/DPDP). Latency-critical voice path is isolated in `apps/voice-runtime`.

## Repo layout

```
apps/web            Next.js 15 (App Router) + TS — admin.calevate.tech + app.calevate.tech
apps/api            FastAPI modular monolith — tenancy, agents, crm, billing, kb, ...
apps/voice-runtime  FastAPI — engine webhooks, in-call tool endpoints. LATENCY-CRITICAL.
apps/workers        ARQ workers — post-call pipeline, embeddings, campaigns, retention
packages/shared     Pydantic models, VoiceEngine protocol, normalized events
infra/              nginx templates, backup units + wal-g config, object-lifecycle policy,
                    and Terraform whose ONLY resource is that S3 lifecycle configuration.
                    No host, no network, no DNS, and NOTHING here has ever been applied.
.github/workflows/  CI (this used to be listed under infra/, where it does not live)
docs/               BRD, TRD, DATA-MODEL, SECURITY-COMPLIANCE, FLOWS, OPERATIONS, ROADMAP
runbooks/           Incident procedures
```

`docs/DEPLOYMENT.md` is the accurate account of what deployment IS, and this line used to
contradict it twice: it said "Terraform (DO Bangalore)" when the Terraform provisions no
host at all and D-25 moved hosting to a general-purpose Hetzner-class VPS (India
co-location is required only for in-call-path services). `infra/README.md` §5 lists what a
human must do before any of it is real — `terraform validate` has never been run.

## Commands

```
uv sync                          # install python deps (never pip install directly)
uv run pytest                    # all tests; -k rls for tenancy tests
uv run ruff check --fix . && uv run ruff format .
uv run mypy .                    # strict; must pass
uv run alembic upgrade head      # migrations (autogenerate + hand-review diff)
pnpm -C apps/web dev|build|typecheck|test   # or `make web-check` (typecheck+lint+test)
docker compose up -d             # local pg16+pgvector, redis, minio
uv run python -m scripts.seed    # reserved slugs, vertical templates, retention defaults
```

## Hard rules (violations = broken build or broken law; never bypass)

1. **Tenancy/RLS**: every tenant-scoped table has `tenant_id` + FORCEd RLS (pattern in
   docs/DATA-MODEL.md §1). Never write queries that bypass RLS; never use the admin DB
   role in app code paths. Any new tenant table ships WITH its policy in the same
   migration and a cross-tenant zero-rows test.
2. **Engine isolation**: only `apps/api/engine/` (and its voice-runtime twin) may
   import vendor SDKs or see vendor payload shapes. Everything else consumes OUR
   normalized models (`CallEvent`, `TranscriptTurn`). Raw vendor payloads go to object
   storage refs, never into typed columns. Both adapters (bolna, fake) must pass the
   conformance suite in `packages/shared/tests/engine_conformance/`.
3. **voice-runtime discipline**: webhook handlers verify authenticity per engine (HMAC
   where the engine signs; for unsigned engines like Bolna: source-IP allowlist +
   execution-id dedupe, payloads as hints, poller as truth — TRD §5), ack < 500ms,
   defer all real work to ARQ. No heavy imports, no synchronous LLM calls, no DB writes beyond the
   minimal event row. Never couple its deploy to `api` changes.
4. **Append-only ledgers**: every table in `apps/api/db/registry.APPEND_ONLY_TABLES` is
   INSERT-only. No UPDATE/DELETE anywhere in code; fixes are compensating entries.
   The list is NAMED here rather than copied because this rule shipped enumerating three
   (`usage_events`, `consent_ledger`, `audit_log`) and the set has more than doubled since
   — a count in prose is the defect class D-103/D-105 exist for. `check_ledger_immutability`
   reads the constant and verifies the DB trigger on each; a bounded exception (D-97's
   KEK re-wrap) is one file-scoped entry there, never a relaxation of the trigger.
5. **Compliance invariants**: an agent ALWAYS answers truthfully when a caller asks
   whether it is an AI or whether the call is recorded — enforced server-side, appended
   to every prompt by `compose_engine_prompt`, and verified against the engine on every
   publish and every drift sweep; no column, config row or client-authored script can
   withdraw it. What an agent VOLUNTEERS at the start of a call is two per-agent toggles
   (D-163): the AI disclosure and the recording notice are separate obligations under
   separate regimes and are separately switchable, on inbound and outbound alike. Every
   agent still HAS both sentences on file — `agents.ai_disclosure_line` /
   `recording_notice_line` NOT NULL and non-blank — and the dial gate still refuses an
   agent with no AI sentence. Campaign launch path must call the compliance gate
   (SECURITY-COMPLIANCE.md §3) — never add a bypass "for testing" (use staging fixtures
   instead); DNC additions propagate before next dispatch tick; transcripts default to
   `text_redacted` in every API response — raw text only behind role check + audit_log
   write.
6. **PII in logs**: never log phone numbers, transcript text, or extraction payloads.
   Log ids. Langfuse traces go through the redaction hook.
7. **Money**: NUMERIC, INR, never floats. Costs recorded per usage_event with our
   unit_cost_paid.
8. **Migrations**: reversible, reviewed, RLS included. Never `drop` in the same release
   that stops writing a column (two-step deprecation).
9. **Supply Chain Security**: Be highly vigilant of supply chain attacks (e.g., the July 2025 ESLint malware which dropped trojanized DLLs via `postinstall` scripts). As an AI agent, you must actively monitor `package-lock.json`/`pnpm-lock.yaml` diffs for suspicious transient dependencies when installing new packages. Never blindly add unknown packages to `allowBuilds` in `pnpm-workspace.yaml`. If `pnpm` blocks a `postinstall` script, verify its legitimacy first. Use `pnpm audit` regularly and inject `resolutions`/`overrides` to pin safe versions if an upstream dependency is compromised.

## Conventions

- Python 3.12, FastAPI, Pydantic v2 everywhere at boundaries; SQLAlchemy 2.0 typed ORM;
  ARQ for jobs (idempotent, keyed, 3 retries + DLQ). Ruff + mypy strict are CI gates.
- Frontend: typed client generated from OpenAPI (`pnpm -C apps/web gen:api`); TanStack Query; shadcn/ui;
  no ad-hoc fetch. Admin realm and client realm are separate route groups + separate
  first-party session modules (`apps/web/src/lib/authn/`, D-177) — never share session
  logic. Authentication is OURS end to end: there is no identity vendor, the credential is
  an `HttpOnly` `__Host-` cookie, and `apps/api/authn/` is the only thing that mints one.
- IDs: uuid_v7. Time: timestamptz, UTC in DB, IST at the edge. Phone: E.164 strings.
- Errors: RFC-9457 problem+json from api; user-safe messages (no internals).
- Tests: pytest; every module has unit tests; RLS tests mandatory for new tables; adapter
  work runs conformance; extraction changes run the golden-transcript fixtures.
- Feature flags via plain config rows, not a flag SaaS.

## Tempo: there is no later

This repository was built from nothing in about a week of continuous work, and it is
still being built that way. **There is no next sprint, no backlog grooming, no "we will
get to it".** Plan in hours, not weeks.

What that means when you are working:

- **If it can be done now, do it now.** Do not file a finding you are able to fix. Do not
  write "worth doing later" about a one-line change. The only things that legitimately
  wait are the ones that need something OUTSIDE this repo — a legal entity, a DLT
  registration, a vendor account, a signed commercial term, a regulator's answer. Say
  which of those it is waiting on, by name.
- **"Ours" and "not ours" is the only scheduling distinction that matters.** An
  engineering task has no timeline; it is either done in this session or it is the next
  thing done. An external blocker has a real timeline and is nobody's to code around.
- **Do not narrate schedules.** No "this week", "next session", "in a future milestone".
  A deferral is a decision-log entry naming what closes it, or it is not a deferral.
- **Finish the seam.** Half-wired is not progress deferred; it is a defect shipped. The
  same clock that makes it tempting to leave a route unmounted is the one that guarantees
  nobody comes back for it.
- This does NOT license shortcuts. The quality bar below is unchanged and is not in
  tension with the tempo — the reason the pace has held is that nothing has had to be
  redone. Speed comes from not accumulating defects, not from skipping the gate.

## Quality bar: write it the way the industry writes it

Working is the floor, not the target. This is a multi-tenant SaaS holding other
businesses' customer data under Indian telecom and privacy law — the code has to be
the kind a competent reviewer at a serious company would sign off, not the kind that
passes its own test.

- **Know the established standard, then beat it if you can.** The widely-used pattern is
  the DEFAULT, not a ceiling — reach for it when you have no reason to do better, and
  invent when you do. A better idea is welcome; an uninformed one is not, so know what
  the standard is and why it exists before departing from it, and say in the code what
  the departure buys. The bar on an invention is higher, not closed: it must be at least
  as correct under failure, no harder for the next reader, and covered by a test that
  fails if it regresses. **Nothing may break to accommodate it.**
- **One way per problem, and migrate rather than accumulate.** If this repo already
  solved something, follow that solution or replace it — two ways of doing one thing is
  a defect even when both work, and the second one is where the drift starts. Replacing
  means the old callers move too, in the same change.
- **SEARCH THE WEB WHENEVER YOU ARE NOT CERTAIN — and you are less certain than you
  feel.** Your training has a cutoff; library APIs, security guidance, framework
  idioms and regulatory detail all move. Search before: using an unfamiliar library or
  a familiar one's unfamiliar corner; writing anything security- or crypto-shaped;
  implementing a spec (RFC, webhook signature, OAuth, payment callback, DLT/TRAI or
  DPDP rule); choosing between two plausible designs; or writing a version-sensitive
  incantation (SQLAlchemy 2.0, Pydantic v2, Next.js 15 App Router, arq, alembic).
  Guessing an API and finding out in review is slower than a 30-second lookup, and
  guessing a compliance rule is not recoverable. Cite what you found in the code
  comment or the commit body, so the next reader inherits the evidence rather than
  the conclusion.
- **Vendor and regulator claims get verified, never assumed.** An unverified vendor
  behaviour is a gate in OPERATIONS §2 or a marked assumption in the adapter — never
  a silent premise (D-31/D-32 exist because of this).
- **Name things for what they hold**, keep functions small enough to hold in your head,
  and put the WHY in the comment — the what is already in the code. A comment that
  restates the line is noise; a comment that records the rejected alternative is worth
  more than the code it sits above.
- **Errors are part of the interface.** Every failure path a user can reach has a
  message they can act on, and every failure path they cannot reach has a log line an
  operator can act on. Never swallow an exception to make a path look green.
- **Leave no half-wired feature.** A route nobody mounted, a job nobody registered, a
  column nobody reads and a migration nobody applied are not progress — they are
  defects that look like progress on a screen. Finish the seam or say plainly that you
  did not.
- **Concurrency, money and time are where sloppiness becomes expensive**: CAS or a lock
  rather than read-then-write, NUMERIC rather than float, timezone-aware instants
  rather than naive ones. When in doubt on any of the three, search for the current
  best practice before writing.

## Domain vocabulary (use these exact terms)

tenant/organization (client business) · agent (a configured voice AI) · engine (rented
voice platform) · extraction schema (per-agent field list driving CRM columns) ·
T0–T4 (RAG tiers, TRD §6) · PE/TM (DLT Principal Entity = client, Telemarketer = Calevate) ·
140/160-series (promotional vs service number classes) · compliance gate (campaign launch
blocker) · big red switch (global outbound halt).

## When implementing backend code

docs/BACKEND-PATTERNS.md is the CONSTRUCTION MANUAL for apps/api, apps/voice-runtime
and apps/workers — binding, not advisory. Before writing a module, endpoint, worker,
or migration, follow its module anatomy, bootstrap order, error ladder, reliability
triad (idempotency/outbox/inbox), and CAS concurrency doctrine. Deviations need a
decision-log entry.

## When implementing, prefer

- Thin vertical slices matching ROADMAP milestones; client #1 needs beat platform polish.
- Configure engine built-ins (Bolna campaigns/KB/custom functions; consent/DNC/transfer
  where verified — TRD §5) over rebuilding them; unverified built-ins land in OUR layer.
- Boring solutions: Postgres before new infra; ARQ before Temporal; monolith module before
  new service. New deployables require a decision-log entry (docs/ROADMAP.md §6).

## Do NOT

- Self-host vector infrastructure (RAG/memory is a managed API service per D-28 —
  the old "no vector DB" rule now means: don't run one), add a message broker, or a
  second backend language.
- Call model providers directly from request handlers (workers or engine only), except the
  in-call RAG tool endpoint which has a 100ms budget — measure it.
- Store secrets in DB/env-committed files; use the secrets manager references.
- Touch `infra/` prod without the plan output in the PR.
- Weaken any Hard Rule to make a test pass.

## Development memory (rememory MCP)

This machine runs a local memory system (Qdrant + Ollama) exposed through the
`rememory` MCP server. Project name here: `calevate`.

**Before non-trivial work** — search first, don't re-derive or re-decide:

- `search_memory` — prior decisions, bug root causes, implementation notes from
  past sessions. Omit `project` to search across all projects.
- `search_docs` — the indexed blueprint (BRD, TRD, DATA-MODEL, FLOWS, ...).
  Results cite file:line; prefer citing them over paraphrasing from recall.
- `search_code` — find existing implementations before writing new ones.

**After significant work** — store the conclusion with `store_memory`:

- a decision and its WHY (memory_type `decision`)
- a bug's root cause and fix (`bug`)
- non-obvious implementation knowledge (`implementation`)
- API contracts (`api`), feature summaries (`feature`), deploy notes (`deployment`)

Write memories self-contained (a future session has no context from this one),
distilled (no transcripts), 2–5 lowercase tags. If a stored decision changes,
`update_memory` supersedes it — never silently contradict an active memory.

**After creating or heavily editing files**, call `sync_index` with project
`calevate` so the new code is searchable immediately (a scheduled task also
syncs every 30 minutes).

**Session continuity**: when a work session wraps up (user says goodbye, a
milestone lands, or context is getting tight), call `save_session` with a
self-contained summary, next steps, and the files the next session should
read first. At session start, `get_briefing` returns that handoff on top —
continue from it instead of re-exploring the repo.
