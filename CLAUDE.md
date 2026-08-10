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
Bulbul v3 TTS (v2 = value tier). Gemini Flash-Lite is a configurable fallback, not the
default. Our code = admin console, client dashboards,
schema-driven lead extraction/CRM, RAG knowledge bases, metering/billing, compliance
(TRAI/DLT/DPDP). Latency-critical voice path is isolated in `apps/voice-runtime`.

## Repo layout

```
apps/web            Next.js 15 (App Router) + TS — admin.calevate.tech + app.calevate.tech
apps/api            FastAPI modular monolith — tenancy, agents, crm, billing, kb, ...
apps/voice-runtime  FastAPI — engine webhooks, in-call tool endpoints. LATENCY-CRITICAL.
apps/workers        ARQ workers — post-call pipeline, embeddings, campaigns, retention
packages/shared     Pydantic models, VoiceEngine protocol, normalized events
infra/              Terraform (DO Bangalore), GitHub Actions
docs/               BRD, TRD, DATA-MODEL, SECURITY-COMPLIANCE, FLOWS, OPERATIONS, ROADMAP
runbooks/           Incident procedures
```

## Commands

```
uv sync                          # install python deps (never pip install directly)
uv run pytest                    # all tests; -k rls for tenancy tests
uv run ruff check --fix . && uv run ruff format .
uv run mypy .                    # strict; must pass
uv run alembic upgrade head      # migrations (autogenerate + hand-review diff)
pnpm -C apps/web dev|build|typecheck
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
4. **Append-only ledgers**: `usage_events`, `consent_ledger`, `audit_log` are INSERT-only.
   No UPDATE/DELETE anywhere in code; fixes are compensating entries.
5. **Compliance invariants**: agents always have a non-null disclosure line; campaign
   launch path must call the compliance gate (SECURITY-COMPLIANCE.md §3) — never add a
   bypass "for testing" (use staging fixtures instead); DNC additions propagate before
   next dispatch tick; transcripts default to `text_redacted` in every API response —
   raw text only behind role check + audit_log write.
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
- Frontend: typed client generated from OpenAPI (`pnpm gen:api`); TanStack Query; shadcn/ui;
  no ad-hoc fetch. Admin realm and client realm are separate route groups + separate Clerk
  apps — never share session logic.
- IDs: uuid_v7. Time: timestamptz, UTC in DB, IST at the edge. Phone: E.164 strings.
- Errors: RFC-9457 problem+json from api; user-safe messages (no internals).
- Tests: pytest; every module has unit tests; RLS tests mandatory for new tables; adapter
  work runs conformance; extraction changes run the golden-transcript fixtures.
- Feature flags via plain config rows, not a flag SaaS.

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
