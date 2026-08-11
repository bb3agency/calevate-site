# AGENTS.md

Guidance for AI coding agents (Codex, Cursor, Copilot, Claude Code, etc.) working in the
Calevate monorepo. `CLAUDE.md` contains the same rules with extra detail; `docs/` is the
authoritative blueprint. Precedence: docs/ > AGENTS.md/CLAUDE.md > code comments.

## Project

Multi-tenant AI voice-agent SaaS (India, Telugu-first). Rented voice engine (Bolna —
D-31) + BYOK models — canonical stack per D-36: Sarvam Saaras STT, **Sarvam 105B LLM
(free, all-India)**, Sarvam Bulbul v3 TTS (v2 = value tier); Gemini is a configurable
fallback, not the default. Our code: admin console,
client dashboards, schema-driven extraction + mini-CRM, RAG (managed service — D-28), metering/billing,
TRAI/DLT/DPDP compliance. Stack: FastAPI + Python 3.12, Next.js 15 + TypeScript,
Postgres 16 (RLS; pgvector only as D-28 contingency), Redis + ARQ, Clerk auth
(two realms — reaffirmed D-37), DO Bangalore.

## Setup & commands

```
docker compose up -d          # pg16+pgvector, redis, minio
uv sync                       # python deps (uv only; no pip/poetry)
uv run alembic upgrade head
uv run python -m scripts.seed
pnpm install && pnpm -C apps/web dev
```

Checks that must pass before any commit:
```
uv run ruff check . && uv run ruff format --check .
uv run mypy .                 # strict
uv run pytest                 # includes RLS + engine-conformance suites
pnpm -C apps/web typecheck && pnpm -C apps/web lint
```

## Structure

- `apps/web` — Next.js; `(admin)` and `(client)` route groups; separate Clerk apps; typed
  API client via `pnpm gen:api` (never hand-write fetchers).
- `apps/api` — modular monolith; modules own their tables; no cross-module SQL.
- `apps/voice-runtime` — latency-critical webhooks + in-call tool endpoints; ack <500ms,
  defer to workers; deployed independently.
- `apps/workers` — ARQ jobs; idempotent, keyed by call_id; **3 attempts total** (i.e. 2
  retries — `WORKER_MAX_TRIES`, flat, no backoff curve) + DLQ.
- `packages/shared` — Pydantic models, VoiceEngine Protocol, normalized events.

## Non-negotiable rules

1. Every tenant table: `tenant_id` + forced Postgres RLS in the SAME migration + a
   cross-tenant zero-rows test. Never bypass RLS; never use the admin role in app paths.
2. Vendor SDKs/payloads only inside `engine/` adapters. All other code uses normalized
   models. Both adapters must pass `engine_conformance` tests.
3. `usage_events`, `consent_ledger`, `audit_log`: INSERT-only. Corrections are
   compensating entries.
4. Compliance: agent disclosure line non-null; campaign launch always goes through the
   compliance gate — no test bypasses; transcripts serialize as redacted by default; raw
   text requires role check + audit_log write.
5. No PII (phones, transcript text, extraction data) in logs or traces; ids only.
6. Money = NUMERIC INR. Time = timestamptz UTC. Phone = E.164. IDs = uuid_v7.
7. Migrations reversible; column removal is two-step across releases.
8. Don't add: vector DBs, brokers, second backend language, new deployables — those need
   a decision-log entry in `docs/ROADMAP.md §6` first.

## Testing expectations

- pytest for api/workers/voice-runtime; new tenant tables ⇒ RLS test; adapter changes ⇒
  conformance suite; extraction changes ⇒ golden-transcript fixtures under
  `apps/workers/tests/fixtures/transcripts/`.
- Voice-agent behavior changes (prompts, tools, KB logic) ⇒ run the regression harness
  (`uv run python -m eval.run --client <slug> --suite core5`) and attach the report to
  the PR.

## PR conventions

Small vertical slices aligned to `docs/ROADMAP.md` milestones. PR description links the
doc section it implements. Auth/billing/compliance code requires the review checklist in
`runbooks/review-checklist.md`. Terraform changes include `plan` output.

## Domain terms

tenant (client business) · agent (configured voice AI) · engine (rented platform) ·
extraction schema (per-agent fields → CRM columns) · T0–T4 (RAG latency tiers) ·
PE/TM (DLT: client is Principal Entity, Calevate is Telemarketer) · 140/160-series
(promotional vs service numbers) · compliance gate · big red switch (global outbound halt).
