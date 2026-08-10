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
| `check:engine-isolation` | Hard rule 2 — only `engine/` sees vendor SDKs/payloads | **import-linter**, 2 contracts SHIPPED and passing: (1) `calevate_shared` imports no `apps.*`; (2) no business module (`agents`, `billing`, `compliance`, `crm`, `integrations`, `reliability`, `tenancy`, `apps.workers`) may import `apps.api.engine` — they consume normalized models from `calevate_shared` instead. Add each new business module to the contract's `source_modules`. The voice-runtime twin is enforced by its own deploy boundary. |
| `check:rls-coverage` | Hard rule 1 — every tenant table has FORCEd RLS | script queries `pg_tables`⨝`pg_policies` in the CI database after `alembic upgrade head`; any tenant_id-bearing table without a FORCEd policy = fail |
| `check:redaction-exposure` | Hard rule 5 — raw transcript text never in default responses | serializer-exposure scan: any Pydantic response model exposing `text` (vs `text_redacted`) outside the role-gated endpoints = fail (raghava's `serializer:exposure-check` pattern) |
| `check:env-parity` | fail-fast config doctrine | `.env.example` keys ⟷ `calevate_shared.config.Settings` fields, both directions; drift = fail |

### Incremental (with the milestone that creates the surface)

| Check | Lands | Enforces |
|---|---|---|
| `check:ledger-immutability` | M1, with billing tables | no `UPDATE`/`DELETE` grants on `usage_events`/`consent_ledger`/`audit_log` (queries `information_schema.role_table_grants`) + grep for ORM `.update(`/`.delete(` on those models |
| `coverage:ratchet` | M1, once suites exist | per-module floors that only rise; ratchet tightest on tenancy/billing/compliance (raghava pattern; industry: ~80% is the knee of the curve — ratchet, don't chase 100%) |
| `check:docs-drift` | M2 | commands/targets named in docs exist in Makefile/package scripts; decision-log references (D-xx) resolve; rate-zone table in DEPLOYMENT.md matches `rate-zones.conf.template` (raghava's `edge:drift-check` + `docs:runtime-drift-check`) |
| `check:openapi-client-fresh` | M1, with first typed-client use | regenerating the TS client from the live OpenAPI produces no diff (stale `gen:api` = fail) |
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
