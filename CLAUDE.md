# CLAUDE.md — Calevate Repository Guide for Claude Code

You are working in the Calevate monorepo: a multi-tenant AI voice-agent SaaS for Indian
SMBs (Telugu-first). Read `docs/README.md` for the full blueprint. `docs/` is the
authoritative blueprint and wins over everything else — when this file conflicts with the
docs set, the docs set wins; flag the conflict, don't silently pick. `docs/AGENTS.md`
mirrors this manual for other coding agents.

## What this system is (30 seconds)

Clients get AI phone agents (inbound receptionist + outbound campaigns) built on a rented
voice engine (Bolna primary per D-31) with BYOK models. **Speech is Sarvam** (Saaras STT ·
Bulbul v3 TTS, v2 = value tier — D-36, unchanged). **Language is Azure OpenAI in East US 2**
— `AZURE_LOCATION` (`eastus2`), whose deployment is made from `AZURE_OPENAI_DEFAULT_MODEL`
(`gpt-4o-mini`), with `gpt-4.1-mini` a live config switch.
⚠ **THE PLATFORM'S OWN DEFAULT MODEL IS NO LONGER THAT CONSTANT AND IS NO LONGER ON THIS
LEG (4 Sep 2026).** The founder's answer is **`gemini-2.5-flash-lite`**, carried by
`PLATFORM_DEFAULT_LLM_MODEL` and by its own live setting `Settings.platform_llm_model` —
because the platform rung of `agent → organization → platform` used to read
`Settings.azure_openai_model`, whose type is the Azure Literal and cannot hold a model on
either of the other two declared legs. `AZURE_OPENAI_DEFAULT_MODEL` keeps its two other
jobs unchanged and is still the right constant for both: the default of
`azure_openai_model` (which model the Azure DEPLOYMENT was made from, pushed to the
engine's credential store) and `billing/rates.BASE_RATE_LLM_MODEL`, the FROZEN model the
plan rate is struck against — so no account's bill moves and none is re-classified, and
TRD §10's fifteen cost points are unrepriced. ⚠ **A DEPLOYMENT CANNOT RUN THE NEW DEFAULT
UNTIL ITS GOOGLE KEY IS INSTALLED IN THE OPS CONSOLE AND ITS PRICE ATTESTED** — the Gemini
catalogue price is `verified=False` (vendor-published, founder-relayed, not fetchable from
here), so hard rule 7 keeps it out of `unit_cost_paid`; until both land, an account that
has chosen nothing runs the ENGINE's own default and the picker marks the row unavailable
with its ground. **D-410 supersedes D-400/D-404 on the in-call leg and
D-127 on the dashboard leg; Vertex is OUT of this product and Gemini is now OFFERED on its
two safe models (see the multi-provider paragraph below, which supersedes D-456 on the
offering question). D-449 (22 Aug 2026)
MOVED THE REGION OFF INDIA** — because the engine's
orchestrator is US-hosted (`bolna-findings/mirror/pages/concepts/security.md:29`, AWS
us-east-1), so every in-call turn was an ocean round trip inside an unmeasured 350ms TTFT
budget, and because Microsoft's Standard (regional) matrix does not offer our default model
in `southindia`. **The default model is UNCHANGED and TRD §10 is UNREPRICED** — that
contradiction was `southindia`-only. **The client-facing India warranty is WITHDRAWN, not
narrowed.** **D-456 (22 Aug 2026) THEN RENAMED THE POSTURE TO `multi-provider-byok`** and
made it THREE declared legs — `azure_openai`, `openai`, `google`. It is not a region change
and it moves no traffic: `eastus2`, the default model, the rate card and TRD §10 are all
untouched. The name lost its `us-` prefix because Google's Developer API has NO region to
request (its SDK raises before a packet leaves the machine), so a posture promising one
region would be a claim one of its own declared legs cannot keep.

**ALL THREE LEGS ARE NOW ON OFFER, AND D-456's "ONLY AZURE IS SELECTABLE" IS SUPERSEDED.**
Clients bring no BYOK: the founder holds all three vendor accounts and installs all three
keys in the ops console, so the product has to offer the choices. **`SELECTABLE_LLM_MODELS`
NO LONGER EQUALS `AZURE_OPENAI_MODELS`** — any assertion or sentence still saying it does is
out of date. It is `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-5.4-mini` (OpenAI direct) and
`gemini-2.5-flash` / `-flash-lite` (Google). Three things changed to allow it, and each
matters more than the widening:

1. **The billing price became an OPERATOR ATTESTATION and `LlmPrice` became a CATALOGUE
   REFERENCE.** Hard rule 7 is unweakened and is now structural rather than a flag: the
   catalogue price has NO path to `unit_cost_paid` at all, `billing/rates.py::
   llm_inr_per_ktok` is the one door and it opens only on an attested figure or a catalogue
   figure somebody read from the vendor, and it RAISES otherwise. `llm_cost_inr_per_minute`
   keeps reading the reference so TRD §10's margin model is the same number in CI.
2. **The GPT-5 traps are applied at the wire.** `LlmModelSpec.traps` had no runtime reader:
   the adapter sent `temperature: 0.1` unconditionally, which a GPT-5 model rejects at agent
   CREATE. `ModelConfig.llm_traps` carries them to `engine/bolna.py::_llm_trap_settings`.
3. **The Gemini trap is real and splits the leg.** Google's own docs say `thinkingBudget: 0`
   disables thinking on 2.5 flash/flash-lite (which the engine sends) and that Gemini 3
   Flash "do not support full thinking-off" — so 3.x can return a candidate with no content,
   which on a phone call is dead air. Every `gemini-3.*` is `selectable=False` with the
   ground recorded. ⚠ **The "Gemini retires 16 Oct 2026" claim was WRONG** — that date
   belonged to preview snapshots, the GA ids carry no announced shutdown, and it propagated
   out of our own `model_lifecycle.py` as if it were fact. Hard rule 11 is the response, and
   `ModelLifecycle.retirement_stance` now separates "the vendor announced nothing" from
   "nobody looked". `gpt-5.6-luna` is withheld solely because nobody has read a page for it.

**What a client may pick is `agents/llm_models.offerable_models()`, never a constant** —
selectable AND its provider's credential installed AND its price attested. Read the three
LLM surfaces separately — two moved, one deliberately did not:

1. **In-call** (inside the engine, BYOK) — the engine calls our Azure deployment on
   `azure_openai_base_url(resource)`, which emits
   `https://{resource}.openai.azure.com/openai/v1`. That is the **v1 surface**: it is
   OpenAI-compatible, has no `api-version` to keep current, and takes a **STATIC API KEY** in
   `Authorization: Bearer`. There is no rotation cron, no dead man, no org policy and no
   12-hour ceiling — D-404's whole machinery existed because a regional Vertex endpoint
   took no static key, and it is deleted. `engine/bolna.py::_llm_routing` maps our
   vocabulary to **`provider: "azure-openai"`** — a FIRST-CLASS Bolna provider, so the
   `custom` route (whose credential path was never verified, retired gate 16c) is not
   used. **THIS SAID `"azure"` UNTIL THEIR DOCS WERE READ (D-417)**: D-410 chose it from a
   provider matrix and a dashboard dropdown, both human-readable LABELS, which is the wrong
   class of evidence for a wire value; their docs print the machine-readable one twice
   (`bolna-findings/mirror/pages/providers/llm-model/azure-openai.md:20,59`).
   **`azure_openai_deployment` is NOT `azure_openai_model`**: on Azure you deploy a model
   under an id you choose and call THAT id, so the deployment name is config and can never
   be derived. **The credential-FIELDS assumption is CLOSED and the guess was wrong**
   (D-417): their Azure provider takes four flat entries — `AZURE_OPENAI_API_KEY`,
   `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION`
   (`providers.md:40,96-102`) — and the store is `{provider_name, provider_value}`, so it
   is **four** `POST /providers` calls, not one. `Settings.bolna_llm_credential_name`
   (`applies: live`) now defaults to `AZURE_OPENAI_API_KEY`; `AZURE` would have 401'd on
   the first turn of the first call. ⚠ ONE HALF STAYS OPEN: whether
   `AZURE_OPENAI_API_VERSION` is real on the v1 surface, where two of their own pages
   disagree — OPERATIONS §2 gate 16f, and no value is invented for it.
   `agents/service.py::in_call_llm` remains the ONE place the leg is decided for an agent.
   **The next Bolna work is still API calls**: `GET /providers`, four `POST /providers`,
   then `GET` again.
   **Where the vendor facts now come from**: their doc HOST is still egress-blocked here
   (`www.bolna.ai` → 403 on CONNECT, re-measured 20 Aug 2026), but their 335 pages were
   fetched elsewhere and delivered as a read-only mirror at `bolna-findings/mirror/` with a
   per-page SHA-256 `MANIFEST.json`. That is the **VERIFIED-VENDOR-DOCS** class every
   vendor claim in this tree now cites, page and line; the ten lane reports over it are
   `docs/evidence/bolna-*.md`. **Never edit, reformat or move it** — ruff is configured to
   exclude it (`force-exclude`) because a repo-wide `ruff format .`, the exact command the
   Commands section below tells you to run, once rewrote the vendor's code blocks inside
   nine pages that other lanes were citing by line number.
2. **Dashboard AI** (user-triggered, over redacted data) — same resource, same region,
   same model constants. D-127's rules (G-1..G-7: redaction before the call, no raw PII,
   the disclosed Sarvam fallback) are unchanged and now bind Azure.
3. **First post-call extraction** — stays on **Sarvam, permanently**, because it reads
   the RAW transcript; `GEMINI_EXTRACTION_DEFAULT is False` in `apps/workers/extraction.py`
   and D-410 does not move it.

**THERE IS NO INDIA RESIDENCY CLAIM ABOUT THE LANGUAGE LEG ANY MORE, AND YOU MUST NOT
WRITE AS IF THERE IS.** Vertex put `asia-south1` in the hostname AND the path, so the guard
could prove residency from the AST. `<resource>.openai.azure.com` names no region: the
region is a property of the RESOURCE. So `scripts/check_model_residency.py` proves what it
still can — one spelling of the region (`AZURE_LOCATION`), no `Settings` field carrying a
region, no Azure endpoint constructible outside `azure_openai_base_url()`, and a builder
that cannot emit a region other than the declared posture's — and the rest is **attested by
a human in the portal**: that the resource is really in East US 2 (gate 20) and that the
deployment is **Regional Standard and NOT Global** (gate 20c). Gates 20/20b/20c/20d all
SURVIVE D-449 re-aimed; none retires, because the posture still pins one region and is
still Regional Standard. Global is Azure's DEFAULT and processes worldwide, so it does not
downgrade the promise from India to America — it deletes the only enforceable property the
posture has left. Speech is still Sarvam and the first extraction pass is still Sarvam.
**⚠ "AND STILL INDIAN" WAS WITHDRAWN ON 27 AUG 2026, AND THIS LINE USED TO SAY IT — READ
THE CORRECTION BEFORE REPEATING EITHER HALF.** Sarvam is an Indian COMPANY; that is not a
residency claim, and the sentence that "what leaves India is the transcript" was wrong in
the direction that matters — **the AUDIO may leave too, on the SPEECH leg, before any
language model sees a word.** Sarvam's own privacy policy ("Cross-Border Data Transfers")
says personal data *"may be transferred to and processed in countries outside India"*,
naming **United States** cloud infrastructure (AWS, GCP, Azure) and analytics providers and
**European Union** model and security vendors, with EU SCCs, adequacy decisions and DPAs as
the safeguards; its *"Data Localization (Indian Users)"* carve-out storing **voice biometric
data in India** reads as scoped to **Content Studio**, not to Voice Agents / API traffic, and
payment data is likewise India-stored. **Two more facts from the same reading, both
load-bearing.** (a) Sarvam **ToS v2.0, effective 29 July 2026, s.17.5** permits Sarvam to use
Inputs, Outputs and usage data **to train its models**, per its Privacy Policy and applicable
law and *"(where required) subject to your consent, which you may decline or withdraw"*, with
access to certain Offerings possibly restricted if declined — **it does not vary by tier**
(free credits, Starter PAYG and paid alike), and **s.6.2** makes a signed order form or
enterprise agreement the ONLY instrument that can displace it. We have none, so **the
client-facing "no vendor trains on your data" promise is NARROWED, not softened**: ours is
unqualified, the vendor position is disclosed (`/legal/dpa` cl.2, `/legal/privacy` §6,
`/legal/subprocessors` §3.4). (b) Retention, for any sub-processor description: content
(Inputs/Outputs) 30 days after last access by default and described as user-configurable —
⚠ **nobody has located where that setting is changed, so do not write that we changed it**;
account data account + 90 days; voice samples until consent withdrawal + 30 days; security
incident logs 7 years; deletion within 30 days of request verification save for legal
retention, live proceedings, or technical limits (anonymised instead).
**EVIDENCE CLASS: VENDOR-PUBLISHED** (Sarvam Terms of Service v2.0, eff. 29 July 2026,
ss.6.2/17.5, and Sarvam Privacy Policy — read by the founder at `www.sarvam.ai` on
27 Aug 2026 and relayed). **⚠ `sarvam.ai` and `docs.sarvam.ai` REMAIN EGRESS-BLOCKED FROM
THIS CONTAINER** — the evidence arrived by another route; a fetch from here still 403s, and
saying "read this session" of it would be false. All of which is why OPERATIONS §2 gate
37(a) (is a voice recording SPDI biometric data?) now governs the LIVE CONVERSATION and not
only the archive, and why it now bites the SPEECH leg too. **OpenAI direct is still not adopted, but the
reason everyone quotes is SPENT**: D-448 refused it because it offers no Indian INFERENCE,
and D-449 stopped asking for Indian inference, so that ground no longer discriminates.
Azure is retained on an enterprise DPA, modified abuse monitoring, deployment-level model
and retirement control (`scripts/check_model_lifecycle.py` consumes it), and a migration
cost already specified. D-410 also records Sarvam-via-Custom-LLM, Krutrim and DeepSeek,
each with its reason. **BRD R-04's 16 Oct 2026 retirement is GONE** —
`GEMINI_DEFAULT_LLM_RETIRES` and the test that turned CI red thirty days out are deleted,
and no vendor deadline is currently running against this product. Our
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
uv sync --all-packages           # install python deps (never pip install directly).
                                 # --all-packages IS REQUIRED: plain `uv sync` installs the
                                 # root only and leaves every workspace member out, so
                                 # `import calevate_shared` fails and the suite cannot
                                 # collect. `.github/workflows/ci.yml:63` uses this form.
uv run pytest                    # all tests; -k rls for tenancy tests
uv run ruff check --fix . && uv run ruff format .
uv run mypy apps packages        # strict; must pass. NOT `mypy .` — see below.
                                 # Needs `uv sync --all-packages --group errors` first:
                                 # without sentry-sdk installed mypy cannot see its real
                                 # types, `ignore_missing_imports` turns them into Any, and
                                 # observability.py type-checks in a shape production does
                                 # not run (`.github/workflows/ci.yml:404`).
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

- Run a SEPARATE vector service, add a message broker, or a second backend language.
  ⚠ **D-502 (1 Sep 2026) REVERSED D-28 ON THE STORE, AND THIS BULLET USED TO READ
  "self-host vector infrastructure (RAG/memory is a managed API service per D-28)".**
  What the rule protects is "no new deployable, no new backup unit, no new restore drill,
  no new region, no new vendor" — and `pgvector` is an EXTENSION in the Postgres this repo
  already runs, backs up and drills, so `kb_chunks` adds none of those. A managed vector
  cloud, a self-hosted Qdrant/Weaviate container, or a second database still do, and are
  still refused. The bake-off (`docs/evidence/kb-retrieval-bakeoff.md` §5.2) took that
  reading deliberately; if it is ever rejected, the whole of D-502 falls and option 1 is
  the answer. **The founder's condition is part of the decision**: adopt it now, and move
  to Pinecone or Weaviate if the compute load makes it necessary once there are clients —
  which is what `calevate_shared.retrieval.RetrievalProvider` and
  `apps/api/retrieval/service.get_retriever` exist to keep to one adapter.
  ⚠ **IN-CALL RETRIEVAL DID NOT CHANGE AND MUST NOT**: it is T0 and the engine's own KB,
  `tests/kb_tiers_test.py` pins voice-runtime's route inventory as an equality, and this
  store serves the dashboard copilot and the CRM paths only.
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
