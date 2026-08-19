# CLAUDE.md — Calevate Repository Guide for Claude Code

You are working in the Calevate monorepo: a multi-tenant AI voice-agent SaaS for Indian
SMBs (Telugu-first). Read `docs/README.md` for the full blueprint. `docs/` is the
authoritative blueprint and wins over everything else — when this file conflicts with the
docs set, the docs set wins; flag the conflict, don't silently pick. `docs/AGENTS.md`
mirrors this manual for other coding agents.

## What this system is (30 seconds)

Clients get AI phone agents (inbound receptionist + outbound campaigns) built on a rented
voice engine (Bolna primary per D-31) with BYOK models. **Speech is Sarvam** (Saaras STT ·
Bulbul v3 TTS, v2 = value tier — D-36, unchanged). **Language is Gemini 2.5 Flash on a
PAID Google Cloud Vertex AI account, `asia-south1`, on all three LLM surfaces** — D-400
supersedes D-36's "Sarvam 105B, free per token" LLM leg outright, D-127 already having
taken the dashboard-AI surface. One model, one region, one retirement date. Read the
three surfaces separately, because they are at different stages and say so in code:

1. **In-call** (inside the engine, BYOK) — D-400's decision, delivered by **D-404:
   ROTATION, NOT PROXYING**. `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE is True`. The engine
   calls Vertex Mumbai DIRECTLY on an endpoint we construct
   (`vertex_openai_base_url`), so there is no proxy, no added hop on a live call and no
   new deployable; what it authenticates with is a GCP OAuth2 **access token**, minted at
   12 hours (`generateAccessToken`, `lifetime: "43200s"`) and replaced every 4 by
   `apps/workers/vertex_credential.py`. A failed refresh is a total LLM outage that is
   silent until the next call, so it pages: `vertex_llm_credential_refresh_failed`,
   `runbooks/vertex-llm-credential.md`. `agents/service.py::in_call_llm` is still the one
   switch, and it now needs THREE things — the constant, a `gcp_project_id`, and a
   resolvable service account. **An API key cannot be used here**: a key forces Vertex's
   GLOBAL endpoint, which is a residency inversion, not a shortcut (D-405..D-407 record
   the proxy, AI Studio, Vertex Express and Bolna's native Google provider as rejected,
   each with its reason). ⚠⚠ ONE THING IS STILL UNVERIFIED LIVE AND IT IS NOW IN DOUBT —
   which credential-store name the hosted engine reads `llm_key` from
   (`Settings.bolna_llm_credential_name`, OPERATIONS §2 gate 16c). A read-only browser
   sweep of 19 Aug 2026 found NO Provider Keys page in the current dashboard and NO
   `custom` entry in the agent LLM provider dropdown — neither of which our code uses
   (it calls the API, and `POST /providers` is in the OpenAPI spec verified by checksum),
   so this contradicts nothing yet. **But do not treat the leg as delivered.** If the
   platform stores no credential for a custom model, `llm_key` is None, Vertex 401s every
   turn, and the fallback is D-405's proxy. **The next Bolna work is one API call**:
   `GET /providers`, then `POST /providers`, then `GET` again — see gate 16c.
2. **Dashboard AI** (user-triggered, over redacted data) — D-127, live in code, and
   **`GEMINI_MODEL_CONFIRMED_IN_REGION is False`**: search points the right way but
   nobody has made the one call that settles it (OPERATIONS §2 gate 14).
3. **First post-call extraction** — stays on **Sarvam, permanently**, because it reads
   the RAW transcript; `GEMINI_EXTRACTION_DEFAULT is False` in `apps/workers/extraction.py`
   and D-400 does not move it.

2.5 rather than 3.x because Mumbai is the only region D-127 permits and no 3.x model is
reported there — a founder's decision that buys a **live 16 Oct 2026 retirement** (BRD
R-04, `GEMINI_DEFAULT_LLM_RETIRES`, OPERATIONS §2 gate 14). Our
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

10. **Never push without a green coverage ratchet.** `uv run python -m scripts.check_coverage_ratchet`
    is the gate that has failed this repo's CI more than every other gate combined, and it
    fails for a reason that is invisible from a diff: it scores the run it is handed, so a
    suite that did not pass makes it **REFUSE TO SCORE** and exit 2 — CI red, on work that
    may be entirely fine. So before any push:

    ```
    make coverage-ratchet          # THE ONLY invocation. It is two commands:
                                   #   uv run coverage run -m pytest -q -p scripts.check_coverage_ratchet
                                   #   uv run python -m scripts.check_coverage_ratchet
    ```

    **RUN THE TARGET, NOT A PYTEST YOU TYPED YOURSELF**, and the reason is the trap that
    has now caught this rule's own author. A plain `uv run pytest tests packages -q`
    produces NO coverage data and does NOT load the `-p scripts.check_coverage_ratchet`
    plugin that records which tests passed — so the checker falls back to whatever
    `.coverage` artifact is lying around from an earlier run and scores THAT. It then
    reports failures from a run you did not do, on code it never executed. The output
    names both halves ("the suite that produced this measurement did not pass" AND "the
    measurement is older than N guarded source files"); the second line is the tell that
    you measured nothing. This rule used to print the plain-pytest pair here, which is
    how the mistake got made twice.

    **READ THE EXIT STATUS OF `make`, NOT OF THE LINE AFTER IT.** A ratchet run wrapped
    as `make coverage-ratchet; echo "EXIT=$?"` or piped into `tail` reports the status of
    the ECHO or the TAIL — so a run killed at 7% by an external SIGTERM (a container
    restart, a parent stopping it, an OOM) surfaces as **exit code 0** and reads exactly
    like a pass. This has already nearly produced a reported pass for a run that never
    finished. Capture `make`'s own status before anything else touches it, and treat a
    result with no `COVERAGE RATCHET:` line in the output as NOT RUN — never as OK. The
    gate's whole value is that it refuses to vouch for what it did not measure; a wrapper
    that launders a kill into a zero defeats it more quietly than any of the causes above.

    **THE DATABASE MUST BE MIGRATED *AND SEEDED*, AND REDIS EMPTY.** `alembic upgrade head`
    alone leaves `reserved_slugs` empty and four tests that assert a reserved slug is
    refused then fail with nothing to refuse — they are not defects and their fix is
    `uv run python -m scripts.seed`, which `.github/workflows/ci.yml` runs before pytest
    for exactly this reason. What the two stores HOLD changes which branches execute, so
    a stale one silently moves the number:

    ```
    make db-reset                        # drop, migrate, seed
    redis-cli -p 6380 -n <db> flushdb    # or: make down && make up
    make coverage-ratchet
    ```

    Read the refusal literally. **"REFUSED TO SCORE" is not a coverage problem** — it names
    a failing test, and the fix is that test, never the baseline. Three things make it
    refuse that are NOT your change, and each has its own answer:

    - **A dirty or stale store.** Run against a database migrated base→head and a Redis db
      nobody else is using; a sibling's rows, a sibling's `_tick_lease` or a half-applied
      chain all read as failures. `alembic heads` must print ONE head — a parallel branch's
      migration re-pointed at a stale parent forks the chain, and `upgrade head` then
      refuses to choose.
    - **CPU contention.** Several suites are speed-dependent (D-29 exists because of nine
      such CI runs). A failure that PASSES STANDALONE is contention, not a defect — say so
      rather than "fixing" it.
    - **Ambient credentials.** A real key in `.env` reaches `os.environ`, and the tests that
      assert a key is ABSENT fail on your machine and nowhere else. `tests/conftest.
      _no_ambient_credentials` strips the ones we know about; a NEW vendor variable must be
      added there, derived rather than retyped.

    **A FAIL is not a REFUSAL and has a different fix.** "REFUSED TO SCORE" means it could
    not measure; "COVERAGE RATCHET: FAIL — <surface>: N uncovered unit(s), budget M" means
    it measured fine and the number went UP. Note what counts as uncovered: a branch
    carrying a no-cover suppression is one, so ADDING a suppression on a hard-rule surface
    fails this gate exactly like leaving a branch untested. Before reaching for a
    `RAISED_BUDGETS` waiver, ask whether the branch should exist at all — a defensive arm
    that cannot be reached is usually a sign the data was fetched twice, and deleting the
    redundant fetch removes the branch, the suppression and a round trip together
    (`compliance/deletion.py::refile_erasure_for_late_records` is the worked example).
    Beware also that coverage's exclude regex matches the directive ANYWHERE on a line —
    including inside a comment that merely talks about it, which silently excludes that
    line.

    **Editing `tests/fixtures/coverage_baseline.json` to quiet it is the one forbidden
    response** — it is an equality gate that only shrinks, so a hand-widened baseline makes
    the next person's PR fail instead of yours. If uncovered units genuinely went up, write
    the tests; if a unit is genuinely unreachable, say which and why in the commit.

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
