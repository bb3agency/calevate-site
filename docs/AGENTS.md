# AGENTS.md

Guidance for AI coding agents (Codex, Cursor, Copilot, Claude Code, etc.) working in the
Calevate monorepo. `CLAUDE.md` contains the same rules with extra detail; `docs/` is the
authoritative blueprint. Precedence: docs/ > AGENTS.md/CLAUDE.md > code comments.

## Engine: `ENGINE=thinnest`

**Production runs `ENGINE=thinnest` (deployed 7 Oct 2026).** ThinnestAI hosts the whole call:
its own numbers, telephony, STT, LLM, TTS and recording (D-678..D-682). `ENGINE` accepts
`thinnest` and `fake` (tests only); our own Pipecat loop was removed by D-763 (13 Oct 2026)
and the tag `pre-pipecat-removal` keeps it recoverable. There is no second engine: a bad
release is rolled back by redeploying the previous image. D-687 and D-688 (8 Oct 2026):

- **Clear** = ThinnestAI's stack end to end, speaking the ThinnestAI voice band the console
  setting `thinnest_clear_voice_band` names: **Premium** (default; pay-as-you-go, ₹2.50/min)
  or **Studio** (catalogue voices with `tier: studio` plus voices our **admin** clones; needs
  ThinnestAI Pro, ₹3.00/min; `thinnest-findings/mirror/snapshots/2026-10-07b/pages/channels/
  voice-clone.md:9-12,81-89`). VENDOR-STATED rates, operator-attested. Agent `byok: "off"`.
- **Studio** = Cartesia on OUR key through ThinnestAI BYOK `scope: "voice"`, with ThinnestAI's
  STT, LLM and telephony (`api-reference/bring-your-own-keys.md:13-24`), ₹1.50/min plus
  Cartesia's charge. Agent `byok: "workspace"`. Our key is switched on (voice only) in our
  developer workspace, where free-trial agents live, and in the customer workspace of each
  paying client that uses Studio (D-727); every agent states `byok`, and the adapter refuses
  one that does not (`engine_agent_byok_unstated`). CLAUDE.md carries the detail.
- **Knowledge belongs to the client** and every agent of that client carries it (D-689).
- **The adapter follows ThinnestAI's 8 Oct docs** (D-690, D-691): built-in tools pinned at
  publish, `voice.language`, `answersCalls` pause, caller memory `recap`/`fresh`, signed
  (v2) webhooks deduped on the event id, numbers recorded and attached in our console, DNC
  and contact erasure pushed only into a client's OWN workspace, never the developer one.
- **Outbound needs no DLT** (D-692): a verified KYC record (manual review or DigiLocker,
  Aadhaar or PAN) and an accepted no-cold-calls pledge. Inbound is never gated.
- **One ThinnestAI customer workspace per client (D-693, built 9 Oct 2026).** Each client's
  agents, calls, numbers, contacts and do-not-call list live in its own customer workspace
  (`Thinnest-Workspace: org_…`), resolved only by `tenancy/engine_workspace.resolve_workspace`
  and sent only by `engine/thinnest_workspace.workspace_headers`; handles carry the workspace as
  `<id>@<org_…>`. Clients buy numbers in their own business name once KYC is verified and
  their business details are approved. Never fall back to the developer workspace for a
  client resource. Plan cap: 3 customers on pay-as-you-go (OPERATIONS T-8).
- **Clients never clone**; they pick and preview voices the admin added and enabled.
- **Client-facing text names no provider** (D-679).

Plan and build state: `docs/THINNEST-INTEGRATION.md`.

## Project

Multi-tenant AI voice-agent SaaS (India, Telugu-first) on the ThinnestAI engine. Outside the
call, two language legs are ours: **dashboard AI** on **Azure OpenAI in East US 2**
(`AZURE_LOCATION`, `eastus2`; default `AZURE_OPENAI_DEFAULT_MODEL`, `gpt-4o-mini`), under
D-127's redaction rules; and the **first post-call extraction on Sarvam, permanently**,
because it reads the raw transcript (`GEMINI_EXTRACTION_DEFAULT is False`). What a client
may pick is `agents/llm_models.offerable_models()` — selectable AND credentialled AND priced
— never a constant; a catalogue price has no path to `unit_cost_paid` (hard rule 7 is
structural), and every `gemini-3.*` stays refused because its Flash models cannot fully turn
thinking off, so a turn can return no content.

Two things a new agent must not overstate. **(a) There is no India residency claim on any
language leg.** `<resource>.openai.azure.com` names no region, so the guard proves only that
one constant spells it and no endpoint is built outside `azure_openai_base_url()`; the
resource's region and its **Regional-not-Global** deployment type are attested by a human
(OPERATIONS §2 gates 20 and 20c). **(b) Sarvam is an Indian company, which is not a residency
claim.** Its privacy policy says personal data *"may be transferred to and processed in
countries outside India"*, and its ToS v2.0 (eff. 29 Jul 2026) s.17.5 permits training on
Inputs/Outputs, displaceable only by a signed order form (s.6.2) — we have none, so the
client-facing no-training promise is narrowed to OUR conduct. VENDOR-PUBLISHED, read by the
founder 27 Aug 2026 and relayed; `sarvam.ai` is egress-blocked from this container.

Our code: admin console, client dashboards, schema-driven extraction + mini-CRM, knowledge
bases (`kb_chunks` + pgvector in our own Postgres for the dashboard copilot and CRM, D-502;
in-call retrieval is the engine's own KB), metering/billing, TRAI/DLT/DPDP compliance, and
the engine adapter. Stack: FastAPI + Python 3.12, Next.js 15 + TypeScript, Postgres 16 (RLS;
pgvector — an extension, not a deployable), Redis + ARQ, first-party auth (two realms —
reaffirmed D-37). Hosting is a general-purpose Hetzner-class VPS (D-25); `infra/` is
templates nobody has applied.

## Setup & commands

```
docker compose up -d          # pg16+pgvector, redis, minio
uv sync --all-packages        # python deps (uv only; no pip/poetry). --all-packages
                              # installs every workspace member; every `uv sync` in
                              # `.github/workflows/ci.yml` uses this form, and
                              # `tests/guardrail_audit_test.py` requires it of each.
uv run alembic upgrade head
uv run python -m scripts.seed
pnpm install && pnpm -C apps/web dev
```

Checks that must pass before any commit:
```
uv run ruff check . && uv run ruff format --check .
uv run mypy apps packages     # strict. NOT `mypy .` — two conftest.py files collide
                              # under module resolution and it stops before checking
                              # anything. Needs `--group errors` synced first, or
                              # sentry-sdk is missing and observability.py is checked
                              # against Any (Makefile `types:`, and the comment above
                              # the `uv sync` step of ci.yml's `types` job). By job
                              # name, not a line: this said `ci.yml:404`, a
                              # deploy-preflight guardrail.
uv run pytest                 # includes RLS + engine-conformance suites
make guardrails               # executable governance (ENGINEERING-PRACTICES §2)
make web-check                # frontend: typecheck + lint + vitest + browser axe gate (D-53).
                              # The last one serves the app and runs axe in real Chromium
                              # over every public page in both palettes — the contrast
                              # rules jsdom cannot run. It FAILS on a missing browser
                              # rather than skipping; CI installs it with
                              # `playwright-core install --with-deps chromium`.
```

## Structure

- `apps/web` — Next.js; `/admin` and `/c/<slug>` route trees; separate first-party
  session modules (`lib/authn/`, D-177) that share no logic; typed
  API client via `pnpm -C apps/web gen:api` (never hand-write fetchers).
- `apps/api` — modular monolith; modules own their tables; no cross-module SQL.
- `apps/voice-runtime` — latency-critical: the engine's signed webhooks; ack <500ms, defer
  to workers; deployed independently. ThinnestAI's in-call actions and caller lookups land
  on the api at `/v1/worker/engine-actions/**` and `/v1/worker/engine-lookups/**`.
- `apps/workers` — ARQ jobs; idempotent, keyed by call_id; **3 attempts total** (i.e. 2
  retries — `WORKER_MAX_TRIES`; outbound deliveries wait 30s then 120s) + DLQ. A job
  earns a retry only by raising `arq.Retry`; a plain `raise` is terminal.
- `packages/shared` — Pydantic models, VoiceEngine Protocol, normalized events. An agent
  never reveals its instructions (D-674): `calevate_shared.engine.CONFIDENTIALITY_RULE` is
  composed into every engine prompt and verified at publish
  (`CONFIDENTIALITY_MARKER`) and by the drift sweep like the truthful-answer block, so an
  agent published before D-674 reads as drift until republished (SECURITY-COMPLIANCE §6.1,
  PROMPT-GUIDE §1.6).

## Non-negotiable rules

1. Every tenant table: `tenant_id` + forced Postgres RLS in the SAME migration + a
   cross-tenant zero-rows test. Never bypass RLS; never use the admin role in app paths.
2. Vendor SDKs/payloads only inside `apps/api/engine/` and its voice-runtime twin. All other
   code uses normalized models. Every adapter must pass the `engine_conformance` tests.
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
6. Money = NUMERIC INR. Time = timestamptz (an absolute instant); IST (`Asia/Kolkata`) is the
   standard time for everything shown, logged, scheduled or bucketed by day/week/month
   (D-709) — always name the zone; app DB sessions run UTC so Python holds UTC-aware instants.
   Phone = E.164. IDs = uuid_v7.
7. Migrations reversible; column removal is two-step across releases.
8. Don't add: a SEPARATE vector service (managed or self-hosted), brokers, a second backend
   language, new deployables — those need a decision-log entry in `docs/ROADMAP.md §6` first.
   ⚠ D-502 reversed the older "no pgvector" reading: an extension in the Postgres we already
   run, back up and drill adds no deployable, no backup unit and no vendor. A second database
   still does.

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

### The coverage ratchet gates every push (CLAUDE.md hard rule 10)

Before pushing anything, from EMPTY STORES, in this order:

```
make db-reset          # drop, migrate, seed — `upgrade head` alone leaves reserved_slugs empty
make redis-reset       # flush AND rewrite the snapshot
make coverage-ratchet  # THE ONLY invocation
```

**Run the make target, not a pytest you typed yourself.** This section used to print
`uv run pytest tests packages -q` followed by the checker, and that pair is the trap, not
the recipe: a plain pytest produces NO coverage data and does not load the
`-p scripts.check_coverage_ratchet` plugin that records which tests passed. The checker
then falls back to whatever `.coverage` artifact is lying around from an earlier run and
scores THAT — reporting failures from a run you did not do, on code it never executed.
CLAUDE.md hard rule 10 was corrected after this caught its own author twice; this mirror
was not, until now.

**Read the exit status of `make`, not of the line after it.** `make coverage-ratchet; echo
"EXIT=$?"` reports the status of the ECHO, so a run killed at 7% by an OOM or a container
restart surfaces as exit 0 and reads exactly like a pass. Output with no `COVERAGE
RATCHET:` line in it is NOT RUN, never OK.

It scores the run it is handed, so a suite that did not pass makes it **REFUSE TO SCORE**
and exit 2 — CI goes red on work that may be entirely fine. "REFUSED TO SCORE" names a
failing TEST, not a coverage shortfall, and the fix is that test.

Three causes are not your change: a dirty or stale store (`alembic heads` must print ONE
head), CPU contention (a failure that passes standalone is contention — say so rather than
"fixing" it), and a real vendor key in `.env` reaching `os.environ` (`tests/conftest.
_no_ambient_credentials` strips the known ones; a new vendor variable must be added there,
derived rather than retyped).

**Never edit `tests/fixtures/coverage_baseline.json` to quiet it.** It is an equality gate
that only shrinks, so a hand-widened baseline makes the next person's PR fail instead of
yours. CLAUDE.md hard rule 10 carries the full argument.

## PR conventions

Small vertical slices aligned to `docs/ROADMAP.md` milestones. PR description links the
doc section it implements. Auth/billing/compliance code requires the review checklist in
`runbooks/review-checklist.md`. Terraform changes include `plan` output.

## Domain terms

tenant (client business) · agent (configured voice AI) · engine (voice runtime `ENGINE` selects; ThinnestAI in production) ·
workspace (a client's ThinnestAI customer workspace, D-693) · Clear/Studio (the two voice rungs) ·
extraction schema (per-agent fields → CRM columns) · T0–T4 (RAG latency tiers) ·
PE/TM (DLT: client is Principal Entity, Calevate is Telemarketer) · 140/160-series
(promotional vs service numbers) · compliance gate · big red switch (global outbound halt).
