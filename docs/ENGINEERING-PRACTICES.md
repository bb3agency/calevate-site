# Calevate — Engineering Practices & Executable Governance

Version 1.0 · July 2026 · Decision D-29. Sources: the raghava-organics production
repo's guardrail system (~20 drift/parity/discipline checks in CI — the proof that
this style works for a tiny team) + 2026 industry practice (fitness functions,
trunk-based development, coverage ratchets).

Principle: **rules that matter are executable.** A Hard Rule enforced only by memory
or review will be violated exactly when the codebase grows fastest. Every check below
is a script in CI; docs describe them, they don't substitute for them.

## 1. Git workflow (D-29)

- **Trunk-based**: short-lived branches (hours–days), merged to `main` daily;
  `main` is always deployable (CD deploys it on green CI). No long-running branches.
- **Conventional Commits**, hook-enforced: `feat:` `fix:` `docs:` `refactor:`
  `test:` `chore:` `ci:` — scope optional (`feat(crm): …`). Machine-readable history
  feeds changelogs and makes `git log --oneline` a project narrative.
- **Pre-commit hooks** (`.pre-commit-config.yaml`): ruff check+format on staged
  files, commit-message lint. Fast (<2s) — anything slower belongs in CI, not hooks.
- Small changesets; a PR (even self-reviewed) for anything touching auth, billing,
  or compliance modules — mirrors SEC-COMP §5's two-person-review-while-team-of-2
  self-review checklist.

## 2. The guardrail pack (Calevate's fitness functions)

Adapted from raghava's checks to OUR hard rules. **Critical four ship in M1** with
the first real code; the rest land incrementally with the milestone that creates
what they guard. All run in `make check` + CI; a red guardrail blocks merge.

### Critical four (M1)

| Check | Enforces | Mechanism |
|---|---|---|
| `check:engine-isolation` | Hard rule 2 — only `engine/` sees vendor SDKs/payloads | **import-linter** (`make guardrails` → `lint-imports`), 2 contracts SHIPPED and passing, both in `pyproject.toml`: (1) `calevate_shared` imports no `apps.*`; (2) no business module may **directly** import a VENDOR ADAPTER — `forbidden_modules` is `apps.api.engine.bolna` / `apps.api.engine.fake`, **not** `apps.api.engine`, and `allow_indirect_imports = true`. That narrowing is deliberate: hard rule 2 is about vendor PAYLOAD SHAPES, not about the word "engine". Workers and business modules legitimately need an engine (the post-call pipeline and the reconciliation poller cannot exist without one, TRD §8) — they reach it through the `apps.api.engine` factory, which hands back the `VoiceEngine` Protocol and normalized models. A factory necessarily imports its adapters, so banning the transitive chain would ban having a factory; what leaks a vendor shape is a module NAMING an adapter in its own imports, and that stays banned. Add each new business module to `source_modules` (currently `admin`, `agents`, `billing`, `campaigns`, `compliance`, `core`, `crm`, `ingest`, `integrations`, `kb`, `ops`, `reliability`, `tenancy` under `apps.api`, plus `apps.workers`). The voice-runtime twin is enforced by its own deploy boundary. |
| `check:rls-coverage` | Hard rule 1 — every tenant table has FORCEd RLS | script queries `pg_tables`⨝`pg_policies` in the CI database after `alembic upgrade head`; any tenant_id-bearing table without a FORCEd policy = fail |
| `check:redaction-exposure` | Hard rule 5 — raw transcript text never in default responses | serializer-exposure scan: any Pydantic response model exposing `text` (vs `text_redacted`) outside the role-gated endpoints = fail (raghava's `serializer:exposure-check` pattern) |
| `check:env-parity` | fail-fast config doctrine | `.env.example` keys ⟷ `calevate_shared.config.Settings` fields, both directions; drift = fail |

### Incremental (with the milestone that creates the surface)

| Check | Lands | Enforces |
|---|---|---|
| `check:ledger-immutability` | M1, with billing tables — **SHIPPED** (`scripts/check_ledger_immutability.py`, in `make guardrails`) | no `UPDATE`/`DELETE` grants on `usage_events`/`consent_ledger`/`audit_log` (queries `information_schema.role_table_grants`) + grep for ORM `.update(`/`.delete(` on those models |
| `check:wiring` | **SHIPPED** (`scripts/check_wiring.py`, in `make guardrails`; D-48) — not on D-29's original list, added when the rule proved it needed enforcing | CLAUDE.md's "leave no half-wired feature". Three questions, each asked against a live REGISTRY rather than against symbol references: every module declaring an `APIRouter` is mounted by the running app (**including `apps/voice-runtime`, which import-linter structurally cannot see** — D-18's hyphen is not a legal module name, so grimp's package walk misses the service); alembic has exactly one head; every ORM column is named by some executable line. Deliberate deferrals live in `UNWIRED_BASELINE`, keyed **per column** and each stating what closes it. Deliberately does NOT check read-vs-write (most access is raw `text()` SQL), enum-member reachability, or ARQ crons (`cron()` takes the coroutine by reference; `tests/job_registration_test.py` covers the real failure — a job enqueued by a name no worker answers to) |
| `coverage:ratchet` | M1, once suites exist | per-module floors that only rise; ratchet tightest on tenancy/billing/compliance (raghava pattern; industry: ~80% is the knee of the curve — ratchet, don't chase 100%) |
| `check:docs-drift` | M2 | commands/targets named in docs exist in Makefile/package scripts; decision-log references (D-xx) resolve; rate-zone table in DEPLOYMENT.md matches `rate-zones.conf.template` (raghava's `edge:drift-check` + `docs:runtime-drift-check`) |
| `check:openapi-client-fresh` | M1, with first typed-client use — **SHIPPED** (`scripts/check_openapi_fresh.py`, in `make guardrails`) | regenerating the TS client from the live OpenAPI produces no diff (stale `gen:api` = fail) |
| `check:compliance-invariants` | M2, with campaigns | static asserts: campaign-launch path calls the compliance gate; `disclosure_line` NOT NULL in schema; DNC propagation job registered |
| `stress:webhook-storm` | M2 | replay N campaign-completion webhook bursts against intake; assert dedupe, ack-latency SLO, zero duplicate side effects (raghava's `flash-sale-contention` analog) |
| `release:guard` (error-budget gate) | M3+, needs Prometheus | deploy blocked while SLO error budget is burned (raghava's `release:guard` + burn-rate rules; OPERATIONS §4 alerts become recording rules first) |

### Patterns deliberately adopted from raghava

- **Evidence artifacts**: DR drills, stress runs, and the engine-verification
  scorecard write JSON/markdown evidence committed to the repo — auditable history,
  and DPDP/client-facing proof material for free.
- **Contract-proposal flow** for config keys: new Ops-config/env keys go through a
  script that updates example + Settings + docs together (their
  `ops:config-contract-proposal`) — the anti-drift move is making the RIGHT way the
  EASY way.
- **`parity:scorecard`** idea: one command that runs every guardrail and prints a
  single pass/fail table — `make guardrails`.

### Explicitly NOT adopted (and why)

- **core-drift / core-sync / release-train** (their template-repo→client-repo
  versioning): Calevate is ONE multi-tenant product, not a repo-per-client agency
  model — there is no template repo to drift from. If a white-label tier ever
  un-defers (ROADMAP §7), this machinery is the reference.
- **Design-token contract check**: no cross-repo design system to protect yet.

## 3. Dev loop conventions

- `make dev` / `make check` stay the only two commands a session needs; every new
  routine task gets a Makefile target (discoverability beats memory).
- Fixtures over mocks-of-our-own-code: fake-engine adapter for pipeline work
  (DEV-SETUP §3), golden-transcript fixtures for extraction, recorded Telugu
  utterances for the regression harness.
- Windows-first dev reality (this machine): scripts must run under Git Bash/cmd;
  no bash-isms in Makefile recipes that Windows make can't run; see the
  scaffold-gotchas memory for the uv/pnpm traps already found.
- AI-agent hygiene: rememory search before non-trivial work; store decisions after;
  the docs set is authoritative and drift-checked (see §2), so agents cite docs
  rather than re-deriving.

## 4. Release discipline trajectory

M1: green `make check` + guardrails = deployable; CD auto-deploys main (DEPLOYMENT §3).
M2: + regression harness red blocks promote (OPERATIONS §3 wiring); webhook-storm in CI.
M3: + error-budget release gating once Prometheus recording rules exist.
Always: migrations reversible, RLS in-migration, two-step column deprecation
(hard rule 8) — checked by `check:rls-coverage` and migration review.

Cross-references: root CLAUDE.md (hard rules) · OPERATIONS §3 (regression harness) ·
DEPLOYMENT §3 (CD) · SECURITY-COMPLIANCE §5 (SDLC) · ROADMAP D-29.
