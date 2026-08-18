# AGENTS.md

Guidance for AI coding agents (Codex, Cursor, Copilot, Claude Code, etc.) working in the
Calevate monorepo. `CLAUDE.md` contains the same rules with extra detail; `docs/` is the
authoritative blueprint. Precedence: docs/ > AGENTS.md/CLAUDE.md > code comments.

## Project

Multi-tenant AI voice-agent SaaS (India, Telugu-first). Rented voice engine (Bolna —
D-31) + BYOK models — canonical stack per D-36: Sarvam Saaras STT, **Sarvam 105B LLM
(free, all-India)**, Sarvam Bulbul v3 TTS (v2 = value tier); **Gemini 2.5 Flash** serves
the user-triggered dashboard AI through Vertex AI `asia-south1` (D-127) — 2.5 because no
3.x model is reported in Mumbai and the region does not move, which makes BRD R-04's
**16 Oct 2026 retirement live for this leg** (`GEMINI_DEFAULT_LLM_RETIRES`, and the build
goes red 30 days out) —
`GEMINI_MODEL_CONFIRMED_IN_REGION is False`, so that is still a decision and not an
observation (OPERATIONS §2 gate 14) — and `GEMINI_EXTRACTION_DEFAULT is False`: the first
post-call extraction stays on
Sarvam because it reads raw transcript text. Our code: admin console,
client dashboards, schema-driven extraction + mini-CRM, RAG (managed service — D-28), metering/billing,
TRAI/DLT/DPDP compliance. Stack: FastAPI + Python 3.12, Next.js 15 + TypeScript,
Postgres 16 (RLS; pgvector only as D-28 contingency), Redis + ARQ, first-party auth
(two realms — reaffirmed D-37). Hosting is a general-purpose Hetzner-class VPS (D-25
superseded D-13's "DO Bangalore"; India co-location is required only for in-call-path
services), and nothing has been deployed — `infra/` is templates nobody has applied.

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
make guardrails               # executable governance (ENGINEERING-PRACTICES §2)
make web-check                # frontend: typecheck + lint + vitest (D-53)
```

## Structure

- `apps/web` — Next.js; `/admin` and `/c/<slug>` route trees; separate first-party
  session modules (`lib/authn/`, D-177) that share no logic; typed
  API client via `pnpm -C apps/web gen:api` (never hand-write fetchers).
- `apps/api` — modular monolith; modules own their tables; no cross-module SQL.
- `apps/voice-runtime` — latency-critical webhooks + in-call tool endpoints; ack <500ms,
  defer to workers; deployed independently.
- `apps/workers` — ARQ jobs; idempotent, keyed by call_id; **3 attempts total** (i.e. 2
  retries — `WORKER_MAX_TRIES`; outbound deliveries wait 30s then 120s) + DLQ. A job
  earns a retry only by raising `arq.Retry`; a plain `raise` is terminal.
- `packages/shared` — Pydantic models, VoiceEngine Protocol, normalized events.

## Non-negotiable rules

1. Every tenant table: `tenant_id` + forced Postgres RLS in the SAME migration + a
   cross-tenant zero-rows test. Never bypass RLS; never use the admin role in app paths.
2. Vendor SDKs/payloads only inside `engine/` adapters. All other code uses normalized
   models. Both adapters must pass `engine_conformance` tests.
3. Every table in `apps/api/db/registry.APPEND_ONLY_TABLES`: INSERT-only. Corrections are
   compensating entries. Named, not copied — this rule shipped listing three and the set
   has more than doubled; `check_ledger_immutability` reads the constant.
4. Compliance: an agent ALWAYS answers truthfully when asked whether it is an AI or
   whether the call is recorded — server-composed, appended to every prompt, verified
   against the engine, unreachable from any column or script. What it VOLUNTEERS at the
   start of a call is two per-agent toggles (D-163: AI disclosure and recording notice
   are separate obligations under separate regimes); both sentences stay NOT NULL and
   non-blank on the row, and the dial gate still refuses an agent with no AI sentence.
   Campaign launch always goes through the compliance gate — no test bypasses;
   transcripts serialize as redacted by default; raw text requires role check +
   audit_log write.
5. No PII (phones, transcript text, extraction data) in logs or traces; ids only.
6. Money = NUMERIC INR. Time = timestamptz UTC. Phone = E.164. IDs = uuid_v7.
7. Migrations reversible; column removal is two-step across releases.
8. Don't add: vector DBs, brokers, second backend language, new deployables — those need
   a decision-log entry in `docs/ROADMAP.md §6` first.

## Tempo: there is no later

This repository was built from nothing in about a week of continuous work and is still
being built that way. **There is no next sprint and no backlog.** Plan in hours.

- **If it can be done now, do it now.** Do not file a finding you can fix. The only
  things that legitimately wait are those needing something OUTSIDE this repo — a legal
  entity, a DLT registration, a vendor account, a signed commercial term. Name which.
- **"Ours" vs "not ours" is the only scheduling distinction.** An engineering task has no
  timeline; an external blocker has a real one and cannot be coded around.
- **Do not narrate schedules** — no "this week", no "a future milestone". A deferral is a
  decision-log entry naming what closes it, or it is not a deferral.
- **Finish the seam.** Half-wired is a defect shipped, not progress deferred.
- This licenses no shortcuts. The pace has held because nothing has had to be redone.

## Quality bar: write it the way the industry writes it

Working is the floor, not the target — this is multi-tenant SaaS holding other
businesses' customer data under Indian telecom and privacy law.

- Know the established pattern, then beat it if you can. The widely-used one is the
  DEFAULT, not a ceiling: reach for it when you have no reason to do better, invent when
  you do — but know the standard and why it exists before departing, say what the
  departure buys, and hold the invention to a higher bar (at least as correct under
  failure, no harder for the next reader, covered by a test that fails if it regresses).
  Nothing may break to accommodate it.
- One way per problem: follow this repo's existing solution or REPLACE it, moving the old
  callers in the same change. Two ways of doing one thing is where drift starts.
- **Search the web whenever you are not certain, and you are less certain than you feel.**
  Training cutoffs go stale: library APIs, security guidance, framework idioms and
  regulatory detail all move. Search before using an unfamiliar library (or a familiar
  one's unfamiliar corner), writing anything security- or crypto-shaped, implementing a
  spec (RFC, webhook signature, OAuth, payment callback, DLT/TRAI, DPDP), choosing between
  two plausible designs, or writing version-sensitive code (SQLAlchemy 2.0, Pydantic v2,
  Next.js 15 App Router, arq, alembic). Cite what you found in the comment or commit body
  so the next reader inherits the evidence, not just the conclusion.
- Vendor and regulator claims are verified or marked as assumptions — never silent premises.
- Name things for what they hold; put the WHY in the comment, since the what is in the code.
  Recording the rejected alternative is worth more than restating the line.
- Errors are part of the interface: an actionable message where a user can reach it, an
  actionable log line where only an operator can. Never swallow an exception to look green.
- Leave no half-wired feature — an unmounted route, an unregistered job, an unread column
  or an unapplied migration is a defect that looks like progress.
- Concurrency, money and time are where sloppiness gets expensive: CAS or a lock over
  read-then-write, NUMERIC over float, aware instants over naive ones.

## Testing expectations

- pytest for api/workers/voice-runtime; new tenant tables ⇒ RLS test; adapter changes ⇒
  conformance suite; extraction changes ⇒ golden-transcript fixtures under
  `apps/workers/tests/fixtures/transcripts/`.
- Voice-agent behavior changes (prompts, tools, KB logic) ⇒ run the regression harness
  (`uv run python -m scripts.eval --client=<slug>`) and attach the report to
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
