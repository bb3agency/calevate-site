# CLAUDE.md — Calevate Repository Guide for Claude Code

You are working in the Calevate monorepo: a multi-tenant AI voice-agent SaaS for Indian
SMBs (Telugu-first). Read `docs/README.md` for the full blueprint. `docs/` is the
authoritative blueprint and wins over everything else — when this file conflicts with the
docs set, the docs set wins; flag the conflict, don't silently pick. `docs/AGENTS.md`
mirrors this manual for other coding agents.

## What this system is (30 seconds)

Clients get AI phone agents (inbound receptionist + outbound campaigns). **The engine is
ThinnestAI (`ENGINE=thinnest`, production since 7 Oct 2026)**: it hosts the whole call — its
own numbers, telephony, STT, LLM, TTS and recording (D-678..D-682). `ENGINE` accepts
`thinnest` and `fake` (tests only). Our own Pipecat loop was removed by D-763 (13 Oct 2026);
the tag `pre-pipecat-removal` keeps it one checkout away. D-687 and D-688 (8 Oct 2026):

- **Clear** = ThinnestAI's speech-to-text and telephony, speaking the ThinnestAI voice band the
  console setting `thinnest_clear_voice_band` names: **Studio** (default, D-792; catalogue voices
  with `tier: studio` plus voices our **admin** clones; ₹2.50/min, switched on for our
  pay-as-you-go account with up to 25 clones, VENDOR-STATED 23 Oct 2026, replies §28) or
  **Premium** (pay-as-you-go, ₹2.00/min). Rates VENDOR-PUBLISHED in ThinnestAI's console
  (Voice section, founder-relayed 24 Oct 2026, D-878), operator-attested, never a constant.
  The model is our Gemini on our Google key (D-834), agent `byok: "llm"`, billed at the band's
  minute; while the `thinnest_own_model` switch is off it is ThinnestAI's own model, agent
  `byok: "off"` (`engine/thinnest._byok_value`, `agents/own_model.py`).
- **Studio** = Cartesia on OUR key with ThinnestAI's STT and telephony, and our Gemini (D-834):
  agent `byok: "llm_voice"`, ₹1.00/min flat (`snapshots/2026-10-19/pages/api-reference/
  bring-your-own-keys.md:28`), attested as `byok_llm_voice`. While `thinnest_own_model` is off
  it runs ThinnestAI's model on BYOK `scope: "voice"`, agent `byok: "voice"` (named outright
  since 20 Oct 2026, never `workspace`), ₹1.50/min plus Cartesia's charge. **Our key is switched on (voice only) in our
  developer workspace, where free-trial agents live, and in the customer workspace of each
  paying client that uses Studio** (D-727, founder 11 Oct 2026, over D-717): Voices, "Studio
  ready" switches the developer workspace on (`agents/studio_voices.ensure_developer_studio`)
  after setting every published non-Studio agent that would follow it `off` and reading it back
  (customer workspaces with no key of their own inherit ours, `bring-your-own-keys.md:128-133`);
  a paying client's first Studio publish installs the key in its own workspace, switches
  `scope: voice` on there and reads it back (`ensure_studio_workspace`), after keeping that
  client's Clear agents `off`. Every agent states `byok`; the adapter refuses one that does not
  (`engine_agent_byok_unstated`), because the vendor default is `workspace` (:304-306).
  Rotation fans out to every Studio workspace; an hourly check repairs drift in the developer
  workspace and each client one. Trial accounts may choose Studio: a trial publish only
  verifies the developer switch, and Studio test calls stop at `trial_studio_minutes`
  (console, default 15; `trial_studio_minutes_used`). Studio agents also get the
  in-call default model, which must be `voiceOnlyByok`. Admin screens call ThinnestAI's own
  bands "ThinnestAI Premium band" / "ThinnestAI Studio band"; clients see only Clear and Studio.
- **Knowledge belongs to the client** and every agent of that client carries it (D-689,
  founder 9 Oct 2026).
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
  their business details are approved. The developer workspace keeps our account, plan, the
  Cartesia key held with its switch off (D-717), the voice catalogue, and objects made before D-693 until
  their next publish recreates them. Never fall back to the developer workspace for a client
  resource. Plan cap: 100 customer workspaces on our pay-as-you-go account, raised from 3; agents
  are counted per workspace: 100 in the developer workspace, 2 in each customer workspace on
  pay as you go, raised per workspace on request (VENDOR-STATED 23 Oct 2026, OPERATIONS T-8,
  replies §28).
- **Clients never clone**; they pick and preview voices the admin added and enabled.
- **Client-facing text names no provider** (D-679).

`docs/THINNEST-INTEGRATION.md` is the engine's plan and build state. There is no second
engine to fall back to: a bad release is rolled back by redeploying the previous image.

### Language models outside the call

1. **Dashboard AI** (user-triggered) runs on **our Gemini first** (D-899, founder 27 Oct
   2026; `account_assist_leg`, `background_leg`), then **Azure OpenAI in East US 2**
   (`AZURE_LOCATION`, `eastus2`, deployment from `AZURE_OPENAI_DEFAULT_MODEL`, `gpt-4o-mini`)
   only where it is configured, then the Sarvam standby. D-127's rules G-1..G-7 (redaction before the call, no raw PII, the
   disclosed Sarvam fallback) bind it, with ONE exception for Pip (D-788): Pip is off for a
   client account until its OWNER turns it on (`copilot_consents`, `copilot/consent.py`),
   and after that what a person types, attaches and asks Pip to read (lead numbers,
   captured details, raw transcripts, each raw read audited) goes to Pip's primary model
   UNMASKED; the admin console's Pip is never masked. What stays masked whatever the
   consent: the Sarvam standby leg (its terms permit training), Pip memories and routine
   instructions, logs and traces (hard rule 6), and every non-Pip API response (hard rule
   5). `AZURE_OPENAI_DEFAULT_MODEL` is also
   `billing/rates.BASE_RATE_LLM_MODEL`, the frozen model the plan rate is struck against.
2. **First post-call extraction** stays on **Sarvam, permanently**, because it reads the RAW
   transcript; `GEMINI_EXTRACTION_DEFAULT is False` in `apps/workers/extraction.py`.

The platform's own default model is `PLATFORM_DEFAULT_LLM_MODEL` (`gemini-2.5-flash-lite`),
read through the live setting `Settings.platform_llm_model`. **What a client may pick is
`agents/llm_models.offerable_models()`, never a constant** — selectable AND its provider's
credential installed AND its price attested. Hard rule 7 is structural here: a catalogue
price has no path to `unit_cost_paid`; `billing/rates.py::llm_inr_per_ktok` is the one door
and it opens only on an operator-attested figure or one read from the vendor, and raises
otherwise. Every `gemini-3.*` is `selectable=False` (Gemini 3 Flash does not support full
thinking-off, so a candidate can come back empty), and `ModelLifecycle.retirement_stance`
separates "the vendor announced nothing" from "nobody looked".

**There is no India residency claim about any language leg, and you must not write as if
there is.** `<resource>.openai.azure.com` names no region, so `scripts/check_model_residency.py`
proves only what the code can (one spelling of the region, no endpoint built outside
`azure_openai_base_url()`); that the resource is really in East US 2 and is **Regional
Standard, not Global** is attested by a human in the portal (OPERATIONS §2 gates 20, 20c).
Sarvam is an Indian company, which is not a residency claim: its privacy policy says
personal data *"may be transferred to and processed in countries outside India"* (US cloud
and analytics, EU model and security vendors), and **Sarvam ToS v2.0 (eff. 29 July 2026)
s.17.5** permits training on Inputs/Outputs, displaceable only by a signed order form
(s.6.2), which we do not have. So our "no vendor trains on your data" promise is narrowed and
the vendor position is disclosed (`/legal/dpa` cl.2, `/legal/privacy` §6,
`/legal/subprocessors`). Sarvam retention: content 30 days after last access by default,
described as user-configurable — nobody has located that setting, so do not write that we
changed it. **Evidence class: VENDOR-PUBLISHED** (founder-relayed, 27 Aug 2026);
`sarvam.ai` and `docs.sarvam.ai` are egress-blocked from this container.

Our code = admin console, client dashboards, schema-driven lead extraction/CRM, knowledge
bases, metering/billing, compliance (TRAI/DLT/DPDP), and the engine adapter. ThinnestAI's
signed webhooks land on `apps/voice-runtime`; its in-call actions and caller lookups land on
`/v1/worker/engine-actions/**` and `/v1/worker/engine-lookups/**` on the api.

## Repo layout

```
apps/web            Next.js 15 (App Router) + TS — admin.calevate.tech + app.calevate.tech
apps/api            FastAPI modular monolith — tenancy, agents, crm, billing, kb, ...
apps/voice-runtime  FastAPI — the engine's signed webhooks. LATENCY-CRITICAL.
apps/workers        ARQ workers — post-call pipeline, embeddings, campaigns, retention
packages/shared     Pydantic models, VoiceEngine protocol, normalized events
infra/              nginx templates, backup units + wal-g config, object-lifecycle policy,
                    and Terraform whose ONLY resource is that S3 lifecycle configuration.
                    No host, no network, no DNS, and NOTHING here has ever been applied.
.github/workflows/  CI
docs/               BRD, TRD, DATA-MODEL, SECURITY-COMPLIANCE, FLOWS, OPERATIONS, ROADMAP
runbooks/           Incident procedures
```

`docs/DEPLOYMENT.md` is the accurate account of what deployment is: a general-purpose
Hetzner-class VPS (D-25); the Terraform provisions no host. `infra/README.md` §5 lists what a
human must do before any of it is real — `terraform validate` has never been run.

## Commands

```
uv sync --all-packages           # install python deps (never pip install directly).
                                 # --all-packages installs every workspace member, not
                                 # only those the root depends on. Every
                                 # `uv sync` in `.github/workflows/ci.yml` uses this form
                                 # and `tests/guardrail_audit_test.py` requires it of
                                 # every job.
uv run pytest                    # all tests; -k rls for tenancy tests
uv run ruff check --fix . && uv run ruff format .
uv run mypy apps packages        # strict; must pass. NOT `mypy .` — see below.
                                 # Needs `uv sync --all-packages --group errors` first:
                                 # without sentry-sdk installed mypy cannot see its real
                                 # types, `ignore_missing_imports` turns them into Any, and
                                 # observability.py type-checks in a shape production does
                                 # not run. See the comment above the `uv sync` step of
                                 # the `types` job in `.github/workflows/ci.yml`, which
                                 # argues it in full. Cited by job name: this note said
                                 # `ci.yml:404`, a deploy-preflight guardrail.
uv run alembic upgrade head      # migrations (autogenerate + hand-review diff)
pnpm -C apps/web dev|build|typecheck|test   # or `make web-check` (typecheck+lint+test+
                                 # test:a11y-browser — axe in real Chromium over every
                                 # public page, both palettes. It NEVER skips: no browser,
                                 # dead server or empty page list all FAIL. CI installs the
                                 # browser with `playwright-core install --with-deps
                                 # chromium`; never run a bare `playwright install` here.)
docker compose up -d             # local pg16+pgvector, redis, minio
uv run python -m scripts.seed    # reserved slugs, vertical templates, retention defaults
```

## Hard rules (violations = broken build or broken law; never bypass)

1. **Tenancy/RLS**: every tenant-scoped table has `tenant_id` + FORCEd RLS (pattern in
   docs/DATA-MODEL.md §1). Never write queries that bypass RLS; never use the admin DB
   role in app code paths. Any new tenant table ships WITH its policy in the same
   migration and a cross-tenant zero-rows test.
2. **Engine isolation**: only `apps/api/engine/` and its voice-runtime twin may import vendor
   SDKs or see vendor payload shapes. Everything else consumes OUR normalized models
   (`CallEvent`, `TranscriptTurn`). Raw vendor payloads go to object storage refs, never into
   typed columns. EVERY adapter must pass the conformance suite in
   `packages/shared/tests/engine_conformance/`; the guarded set is `pyproject.toml`'s
   `forbidden_modules` under `[tool.importlinter]` (named, not copied, so prose cannot drift
   from it).
3. **voice-runtime discipline**: it receives the engine's webhooks (ThinnestAI signs them;
   `signed_intake.py`). Handlers verify authenticity per engine (HMAC where the engine signs;
   an unsigned engine gets execution-id dedupe, payloads as hints, poller as truth — TRD §5),
   ack < 500ms, defer all real work to ARQ. No heavy imports, no synchronous LLM calls, no DB
   writes beyond the minimal event row. Never couple its deploy to `api` changes.
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
                                   #   uv run python -m coverage run -m pytest -q -p scripts.check_coverage_ratchet
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
    make db-reset       # drop, migrate, seed
    make redis-reset    # flush AND rewrite the snapshot — see below
    make coverage-ratchet
    ```

    **`redis-cli flushdb` IS NOT `make redis-reset`, and this line used to say it was.**
    `FLUSHDB` empties the live dataset and leaves `dump.rdb` sitting in the repo root
    holding every key it just removed; `redis-server` loads that file from its working
    directory at boot, so "flush, restart redis, run the gate" silently restores the
    contamination and the ratchet refuses to score, naming a cause you believe you already
    fixed. It cost exactly that, twice. `scripts/redis_reset.py` flushes and then `SAVE`s.

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

11. **Never state a fact you have not verified, and a value already in this repo is NOT
    verification of itself.** This rule exists because a vendor retirement date sitting in
    `model_lifecycle.py` — a REPORTED figure a past session wrote — was repeated downstream
    as if it were fact, propagated into an evidence doc and a lane brief, and was simply
    WRONG: the model had no announced retirement at all, and the date belonged to a
    different (preview) identifier. The number looked authoritative because it was in our
    own code, which is exactly the trap.
    - **A claim about the outside world** — a price, a retirement date, a model id, an API
      field, a rate limit, a law, what a vendor's endpoint returns — is asserted only from a
      PRIMARY SOURCE you actually read this session: the vendor's own page/docs/OSS at a
      named URL or pinned commit, the hash-pinned `bolna-findings/` mirror, or a reading the
      user/founder relays from one. Cite it (URL/file:line + date) at the point of use, so
      the next reader inherits the evidence, not the conclusion.
    - **Repo-internal values are claims, not evidence.** A constant, a comment, a decision
      row, a prior agent's report, or a figure in `docs/evidence/` carries its OWN evidence
      class (VERIFIED-VENDOR-DOCS / VENDOR-PUBLISHED / REPORTED / ESTIMATE / UNKNOWN). If it
      is REPORTED or worse, it may not be re-stated as fact and may not reach money, a wire
      value, or a client-facing claim without being re-verified — re-verify it or label it,
      never launder it by repetition.
    - **When you cannot verify, say so in those words** ("UNKNOWN — <host> is egress-blocked
      here" / "REPORTED, not confirmed"), mark the artefact accordingly, and route the gap to
      a human or an operator-attested input. Do NOT fill the gap with a guess dressed as a
      finding, and do NOT soften a guess with hedges ("likely", "~", "treat as") to make it
      read like knowledge. If pressed for an answer you do not have, the answer is "I have
      not verified this," not a plausible number.
    - This binds visible reasoning and lane briefs too: an unverified premise passed to a
      subagent becomes its foundation. Verify before you delegate a fact.

12. **Verify the PREMISE before you act on it. Rule 11 governs what you SAY; this governs
    what you DO, and an unchecked premise you act on costs more than one you merely state.**
    Every failure in the session that produced this rule was the same shape: a check that
    was available, cheap, and not run.
    - **If a check exists and is cheap, run it — do not reason about what it would say.**
      A `grep`, an `ls`, a `--dry-run`, reading the config, is seconds. Being wrong about a
      live system is not. "It's probably X" is the sentence to notice: it means a
      verification is available and you are choosing inference over it.
    - **Grep before you name.** A name you invent may already be fixed somewhere in this
      tree. The deploy account was named `deploy` from habit while
      `infra/hygiene/systemd/calevate-hygiene.service:24`, `infra/privileged/sbin/
      calevate-nginx-apply:55` and `infra/privileged/sudoers.d/calevate-deploy` all
      hard-code `calevate` — and `infra/privileged/README.md:87` already SAID the three must
      agree. One grep would have found it. The failure mode is the expensive kind: nothing
      errors, and a timer, a guard and a sudoers grant each break silently, days apart.
    - **Enumerate the contract; do not recall it.** Which gates exist is a fact in
      `.github/workflows/ci.yml`, not in memory. Guessing produced two consecutive red CI
      runs (`lint-imports`, then OpenAPI snapshot freshness) that a single read of that file
      would have prevented. The same holds for any registry the repo keeps: the append-only
      table list, `BOUNDED_LISTS`, the guarded surfaces. Read the source of truth.
    - **Satisfying the WORDS of an instruction while defeating its PURPOSE is not
      compliance.** The runbook says `listen_addresses` "must include the Docker bridge
      gateway"; `*` includes it, and also binds the public interface, leaving only ufw in
      front — the one control that explicitly does not contain Docker. Before implementing
      an instruction, ask what it is protecting against; if your implementation does not
      protect against that, it is wrong however literally it complies.
    - **A speculation may never become a recommendation.** Asking "does their runner build,
      or only pull?" was right; offering to reverse a decision on the guess was not. The
      source said it runs `npm ci`, `docker compose build`, then `npm ci` and `next build`
      again. Say "I don't know yet, I'm checking" and then check — the answer usually costs
      one command.
    - **On a live system, INSPECT BEFORE YOU MUTATE, and never hand over a destructive
      command for a path you have not looked at.** `rm -rf`, `DROP`, `deluser`, a config
      overwrite: list it, check what it holds, confirm nothing irreplaceable is inside, then
      act. A file holding `PLATFORM_KEK` is not a re-clone away.
    - **When acting through a person at a terminal, prove the outcome rather than assuming
      it.** Have the command print what changed and assert the property that matters
      (`ss -tlnp` showing no `0.0.0.0`, `sshd -T` showing the daemon's resolved value, not
      the file you think it read). Their paste is your only instrument.
    - **A repo-internal claim is not evidence of itself, and this includes attribution.**
      Four "raghava-proven" claims in `docs/DEPLOYMENT.md` were false the whole time because
      nobody had read the source they cited. If you cite something, open it.

13. **A comment explains the CODE. It is not a diary, a defence, or a changelog.**
    This rule exists because the practice drifted badly and nobody stopped it: comments in
    this tree had grown into session narration — what an agent measured today, what a brief
    asked for, what a previous version of the same comment said and why that was wrong,
    addressed to a reader arguing back. That is noise wearing the costume of rigour, it
    buries the two or three lines that actually matter, and it is now the single most
    common defect in this repository.

    **The test is one question: does a competent reader who has never seen this session
    need this sentence to work on this code?** If no, it does not go in a comment.

    **WRITE:**
    - WHY this and not the obvious alternative, naming the alternative. The single highest
      value comment in this tree is "we do X rather than Y because Y does Z".
    - A constraint the code cannot state itself: an ordering that is load-bearing, a lock
      that must be taken first, a budget the line is inside, a legal or regulatory reason.
    - The failure this line prevents, when it is not obvious from the line.
    - For a vendor fact that reaches money, a wire value or a client-facing claim: the
      figure, its source and its date, in ONE clause. Hard rule 11 requires the evidence to
      travel with the claim — it does NOT require a paragraph about the act of checking.

    **DO NOT WRITE:**
    - **Session narration.** "Re-measured 19 Sep 2026", "I checked and", "the brief named",
      "verified this session". The reader does not care who looked; they care what is true.
      A date belongs beside a FACT THAT CAN EXPIRE, not beside your act of reading it.
    - **Self-defence and self-congratulation.** "and that is a measurement, not a shrug",
      "this is the stronger kind of absence", "deliberately, and the reason is the paragraph
      above". If the code is right the comment does not need to win an argument.
    - **Restating the line.** The `what` is already in the code.
    - **Correction archaeology.** "⚠ THIS USED TO SAY X" is worth keeping ONLY while a
      reader could still act on the old belief — a value that propagated, a claim other
      files cite, an instruction somebody might follow. Once the wrong version is gone from
      the tree and from every reader's head, the correction is history and belongs in the
      decision log, not above the code. A ⚠ block whose subject no longer exists anywhere
      is pure cost. **Corrections do not stack: never leave two or three generations of
      "this said A, then B, and both were wrong" above one line.**
    - **Shouting.** Bold and caps are for the one sentence in a module that is genuinely
      load-bearing. When every paragraph shouts, none does.

    **LENGTH IS THE SYMPTOM, NOT THE DISEASE — do not fix this by truncating.** A
    twenty-line comment that records a hard-won design decision is correct. A four-line one
    that narrates a measurement is not. Cutting the second is the job; cutting the first is
    a different defect, and the more expensive one, because the reasoning cannot be
    recovered from the code.

    **WHAT THIS DOES NOT LICENSE.** Do not delete a rejected alternative, a regulatory
    reason, an evidence class on a live vendor figure, or a warning that an instruction
    below it is wrong. Hard rules 11 and 12 are unweakened: the evidence still travels with
    the claim. What goes is the prose around it.


## Conventions

- Python 3.12, FastAPI, Pydantic v2 everywhere at boundaries; SQLAlchemy 2.0 typed ORM;
  ARQ for jobs (idempotent, keyed, 3 retries + DLQ). Ruff + mypy strict are CI gates.
- Frontend: typed client generated from OpenAPI (`pnpm -C apps/web gen:api`); TanStack Query; shadcn/ui;
  no ad-hoc fetch. Admin realm and client realm are separate route groups + separate
  first-party session modules (`apps/web/src/lib/authn/`, D-177) — never share session
  logic. Authentication is OURS end to end: there is no identity vendor, the credential is
  an `HttpOnly` `__Host-` cookie, and `apps/api/authn/` is the only thing that mints one.
- IDs: uuid_v7. Phone: E.164 strings. Time: `timestamptz` (an absolute instant; storage has no
  zone). **IST (`Asia/Kolkata`) is the standard time (D-709)** for everything shown, logged,
  scheduled, or bucketed into a day, week or month — name the zone every time
  (`AT TIME ZONE 'Asia/Kolkata'` in SQL, `billing.plans.IST` in Python), never lean on a
  session or host zone. App database sessions run UTC on purpose
  (`db/session.APP_SESSION_TIMEZONE`), so Python holds UTC-aware instants and renders IST.
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

tenant/organization (client business) · agent (a configured voice AI) · engine (the voice
runtime `ENGINE` selects; ThinnestAI in production) · workspace (a client's ThinnestAI
customer workspace, D-693) · Clear/Studio (the two voice rungs clients see) · extraction
schema (per-agent field list driving CRM columns) · T0–T4 (RAG tiers, TRD §6) · PE/TM (DLT
Principal Entity = client, Telemarketer = Calevate) · 140/160-series (promotional vs service
number classes) · compliance gate (campaign launch blocker) · big red switch (global
outbound halt).

## When implementing backend code

docs/BACKEND-PATTERNS.md is the CONSTRUCTION MANUAL for apps/api, apps/voice-runtime
and apps/workers — binding, not advisory. Before writing a module, endpoint, worker,
or migration, follow its module anatomy, bootstrap order, error ladder, reliability
triad (idempotency/outbox/inbox), and CAS concurrency doctrine. Deviations need a
decision-log entry.

## When touching agent prompts

**An agent never reveals its instructions (D-674).**
`calevate_shared.engine.CONFIDENTIALITY_RULE` is composed by `compose_engine_prompt` after
the client's fence and before the truthful-answer block, and is verified like that block:
the publish verifier refuses an engine prompt missing `CONFIDENTIALITY_MARKER`, and the
drift sweep reports it — so an agent published
before D-674 reads as drift until republished. Never weaken it to make a prompt change pass,
and keep hard rule 5's two truthful answers outside it (SECURITY-COMPLIANCE §6.1,
PROMPT-GUIDE §1.6).

**The LLM's output is spoken, so the prompt must forbid what cannot be** — markdown, bullets,
asterisks, headings, emoji — and reads phone numbers and OTPs digit by digit. Those
sentences live in `calevate_shared/engine.py`; carry them into any prompt change rather than
rewriting around them.

## When implementing, prefer

- Thin vertical slices matching ROADMAP milestones; client #1 needs beat platform polish.
- Configure engine built-ins (KB, custom functions; consent/DNC/transfer where verified —
  TRD §5) over rebuilding them; unverified built-ins land in OUR layer.
- Boring solutions: Postgres before new infra; ARQ before Temporal; monolith module before
  new service. New deployables require a decision-log entry (docs/ROADMAP.md §6).

## Do NOT

- Run a SEPARATE vector service, add a message broker, or a second backend language.
  `pgvector` is an extension in the Postgres this repo already runs, backs up and drills, so
  `kb_chunks` adds no deployable, backup unit, restore drill, region or vendor (D-502, which
  reversed D-28 on the store); a managed vector cloud, a self-hosted Qdrant/Weaviate
  container or a second database would add them, and are refused. The founder's condition
  is part of D-502: move to Pinecone or Weaviate if the compute load makes it necessary once
  there are clients — which is what `calevate_shared.retrieval.RetrievalProvider` and
  `apps/api/retrieval/service.get_retriever` keep to one adapter. In-call retrieval is the
  engine's own knowledge base; this store serves the dashboard copilot and the CRM paths.
- Call model providers directly from request handlers (workers or engine only).
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
