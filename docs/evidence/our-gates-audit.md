# Our own gates, audited — can each of the twenty actually fail? (D-176)

**Twenty**, counted from `scripts/check_*.py` and not from memory: `check_audit_ip`,
`check_bootstrap_keys`, `check_compliance_invariants`, `check_config_applies`,
`check_coverage_ratchet`, `check_deploy_env`, `check_docs_drift`, `check_drill_freshness`,
`check_env_parity`, `check_ledger_immutability`, `check_metadata_columns`,
`check_model_residency`, `check_observability_ready`, `check_openapi_fresh`,
`check_public_routes`, `check_raw_sql`, `check_redaction_exposure`, `check_rls_coverage`,
`check_web_env_parity`, `check_wiring`. `lint-imports` is the twenty-first gate and is not
one of our scripts.

**Date**: 17 August 2026 · **Decision**: D-176 · **Subject**: every `scripts/check_*.py`,
plus `make guardrails`, `make check` and `.github/workflows/ci.yml`.

## Why this document exists

`docs/evidence/raghava-platform-teardown.md` §1.11 and §3.1 and
`raghava-deploy-teardown.md` §5.3 record four independent instances, in one reference
repository, of a gate that validates what its own run produced:

- the DR freshness gate (`dr-stale-drill-check.js` reading an artifact
  `dr-ephemeral-pack.js:35-45` writes without touching a database, generator and
  validator back to back in `reliability-ci.yml:199-200`);
- the error-budget release gate (`release-policy-state.js:11,97` writes the file
  `reliability-release-guard.js:6-43` reads back, `artifacts/` gitignored, no
  `PROMETHEUS_BASE_URL` → always "100% remaining, approved");
- the contention harness, run with `FLASH_SALE_ENFORCE_INVARIANTS=false`
  (`reliability-ci.yml:226`), computing oversell and acting on nothing;
- `parity-scorecard.js:24-27`, calling same-run output "evidence that the gate was
  recently run".

Four is a pattern. D-166 turned it into a constraint — **a check must be able to name
what would make it fail, and that thing must not be produced by the run** — and enforced
it on the one check it shipped with (`scripts/check_drill_freshness.py`, whose
`check_this_module_cannot_write` at `:156` walks the module's own AST on every run).
This is that constraint turned on the other nineteen.

Three questions per check, answered with evidence:

1. **What would make it fail?** If no failing input can be constructed, the check is
   decorative and that is the finding.
2. **Does anything on its own run path produce the evidence it reads?**
3. **Can it pass vacuously?** Zero items scanned, an empty registry, a glob matching
   nothing, an exception swallowed into a pass, an `exit 0` on a missing input.

## The headline

**No check in this repo has the reference's closed loop.** The one that had to be looked
at hardest — `check_openapi_fresh` — compares a **committed** snapshot
(`apps/web/src/lib/api/openapi.json`, tracked in git) against a freshly built app; the
only writer is `--write` (`check_openapi_fresh.py:146-151`), which appears in no Makefile
recipe, no CI step and no deploy script, and `pnpm -C apps/web gen:api` **reads** that file to emit
TypeScript (`apps/web/package.json:13`) rather than refreshing it. `check_metadata_columns`,
`check_config_applies` and `check_env_parity` were checked for the same shape and have it
in no form: all three read the live database, the live `Settings` model and a committed
template respectively.

**What the audit did find is the other shape — a gate whose evidence can be ABSENT and
read as agreement.** Six instances, all now closed. The last two were found by VERIFYING
this document rather than trusting it: the first pass cleared `check_ledger_immutability`
and `check_observability_ready` by reading them, and running them against an empty tree
disagreed. That is the finding applied to the audit itself — a verdict reached by reading
is not a verdict reached by watching something fail.

| # | Check | The vacuous pass | Fix |
|---|---|---|---|
| 1 | `check_metadata_columns` | Against an EMPTY database it printed `OK (61 tables agree in both directions)`. `compare_metadata` reports a table the database lacks as ONE `add_table` op, not one `add_column` per column, so every column of every missing table sat outside the verdict | `absent_model_tables()` (`:124`) + exit 2 REFUSED (`:98`) |
| 2 | `check_wiring` | `unmounted_routers()` reports no offenders when `declared_routers()` finds none — `rglob` over a renamed `apps/api` yields nothing and raises nothing, giving `WIRING: OK (0 routers all mounted)` | `blind_spots()` (`:396`) |
| 3 | `check_env_parity` | The third direction is a SEARCH over `SEARCH_DIRS`; a renamed directory silently turns `7 direct environment reads accounted for` into `0`, on the direction that exists to catch a worker calling `os.getenv` | `blind_spots()` (`:201`) |
| 4 | `check_config_applies` | Four of its sections iterate `classified_keys()`, and `managed_fields()` is computed from `Settings` BY EXCLUSION — a widened exclusion empties it with no list edited, and four checks over an empty set are four green ones | `blind_spots()` (`:129`) |
| 5 | `check_ledger_immutability` | Check 1 — hard rule 4's CODE half — is an `rglob` over `SEARCH_DIRS`: `check_sources(root=<empty dir>)` returns `[]` and the run prints `... no mutating statements in app code` having read no code. It looked anchored and was not: the only thing that failed on an empty tree was `check_allowances`, and only because `BOUNDED_MUTATIONS` happens to hold ONE entry naming a real file — an exception registry whose correct end state is empty, so removing D-97's KEK re-wrap allowance (a desirable change) deletes check 1's only floor | `blind_spots()` (`:298`), run first in `main()` |
| 6 | `check_observability_ready` | The langfuse rung asserts an ABSENCE, and an absence is the one verdict a scan over nothing produces for free. `langfuse_footholds` swallowed a missing `IMPORT_ROOTS` entry with `continue` and a missing manifest with `if manifest.exists():`, so a renamed `apps/` turns "no langfuse import anywhere" into "none anywhere I looked", printed as the former | `ObservabilityBlindError` on either surface; `main()` exits **2 REFUSED**, not 1 — nothing was shown to be misconfigured |

Plus one in the wiring test itself:

| # | Artefact | The defect | Fix |
|---|---|---|---|
| 7 | `tests/guardrail_audit_test.py::test_every_guardrail_script_runs_in_both_gates` | `assert f"scripts.{script}" in makefile` was a substring search over the WHOLE file, and both the Makefile and `ci.yml` are heavily commented with several comments naming the script beside them (`Makefile:75`, `ci.yml:119` both name `scripts.check_coverage_ratchet` in a comment). A check deleted from the recipe and left in its comment passed | the test now reads Makefile RECIPE lines only and the workflow's parsed `run:` scalars only, with `test_the_command_accessors_are_not_reading_everything` as the control on the reduction |

And one that is not a vacuous pass but is the same species of rot:

| # | Artefact | The defect | Fix |
|---|---|---|---|
| 8 | `docs/ENGINEERING-PRACTICES.md` §2 | The guardrail catalogue — the page a reader goes to for "what guards what" — had a row for twelve of the twenty scripts. The eight it had never heard of (`check_audit_ip`, `check_bootstrap_keys`, `check_config_applies`, `check_deploy_env`, `check_drill_freshness`, `check_metadata_columns`, `check_model_residency`, `check_observability_ready`) are precisely the ones nobody would think to run, argue with, or notice the absence of. Three of the rows it DID have said "in `make guardrails`" of a check that is also a CI step, and `check:ledger-immutability`'s row enumerated three ledgers in prose where the constant holds eight — the exact defect class hard rule 4's own commentary names | eight rows added, the four "critical four" rows now name their script path, the three wiring claims corrected, the ledger row rewritten to name the CONSTANT, and `test_every_guardrail_script_is_named_in_the_catalogue` globs `scripts/check_*.py` so the list cannot fall behind again |

## The table

`P` = would a plausible failing input be reported. `E` = does anything on its run path
produce the evidence it reads. `V` = could it pass vacuously.

| Check | What makes it fail | What it reads | E: self-produced? | V: vacuous pass? | Wired |
|---|---|---|---|---|---|
| `check_audit_ip` | any `request.client` read outside the two permitted functions; **and** a permitted entry that has stopped reading the peer (`:162`) | `apps/` AST | No — source it does not write | **No.** The allowance is verified live: an empty scan makes every `PERMITTED` entry (`:69`) unmatched and fails | `Makefile:221`, `ci.yml:238` |
| `check_bootstrap_keys` | `ENV_ONLY_KEYS` losing one of the six (`check_list`, `:73`); the override filter accepting a store value, proved by pushing one through it (`check_filter_applied`, `:93`); either console surface offering one | `core/settings`, `ops/secret_service`, live `Settings` | No | **No.** The six are spelled independently of the constant they check, so an empty `ENV_ONLY_KEYS` fails all six | `Makefile:203`, `ci.yml:172` |
| `check_compliance_invariants` | a dial path that does not pass the gate, a bypass, a schema invariant lost | tree AST + `pg_catalog` | No | **No** — `blind_spots()` (`:320`) fails when the gate registry cannot resolve or the chokepoint exemption matches nothing. DB unreachable is a named non-verdict locally and a FAIL under `CI` | `Makefile:265`, `ci.yml:206` |
| `check_config_applies` | an unclassified managed key, a stale entry, a classification with no reason, an unbounded field | `managed_fields()`, `FIELD_APPLIES`, `manageable_secret_keys()` | No | **WAS YES → fixed** (`blind_spots()`, `:129`) | `Makefile:207`, `ci.yml:176` |
| `check_coverage_ratchet` | uncovered-unit count ≠ budget per hard-rule surface, in EITHER direction; an unguarded surface; a stale waiver | `.coverage` + `.coverage-run.json` from the suite run in the SAME job | Yes, and deliberately — it scores a RUN, which cannot be anything but the run's own output. What makes that safe is that it refuses rather than scores: `unvouched_run` (`:812`) and `blind_spots` (`:839`) exit 2 on a partial, failing, unserviced run or one started against non-empty stores | **No.** Missing data file → refuse; no branch data → refuse; area with zero executed statements → refuse | `Makefile:83-84,106-107`, `ci.yml:138,148` |
| `check_deploy_env` | an incoherent VALUE — two DSNs naming different databases, a reused HMAC secret, a placeholder still carrying `.env.example`'s text, a missing bootstrap variable | the process environment (or `--env-file`) + `.env.example` | No | **No, with a stated limit.** A missing `.env.example` is a named WARN listing the checks that did not run (`:226`), never a silent skip; most refusals are scoped to `APP_ENV != local`, so CI exercises a subset and `tests/deploy_env_preflight_test.py` builds a bad `.env` per refusal | `Makefile:182`, `ci.yml:253` |
| `check_docs_drift` | a doc command that resolves to nothing, a dangling `D-xx`, a duplicated decision number, a SEC-COMP §3 name the code lost, a rate-zone/TTS/capability mismatch, a stale deferral | the doc set, Makefile, package manifests, ROADMAP §6, nginx template | No | **No** — `blind_spots()` (`:1336`) is the model the four fixes above copied: floors on documents, targets, command claims and decision ids, plus "§3 quotes no rule the gate emits" | `Makefile:270`, `ci.yml:220` |
| `check_drill_freshness` | a quarterly record more than one quarter old, post-dated, duplicated, unfilled, verdict-less or FAIL; a misnamed record | committed `docs/evidence/restore-drill-<YYYY>-Q<N>.md` | **No, structurally** — `ALLOWED_IMPORTS`, `FORBIDDEN_CALLS` and the self-AST audit at `:156`; the clock is read off the FILENAME, never an mtime | **No.** NOT RUN is a distinct third state, printed loudly on every build, and never called a pass | `Makefile:237`, `ci.yml:195` |
| `check_env_parity` | a key in one side and not the other, a duplicate, an `os.getenv` outside `Settings`, a `BOOTSTRAP_REQUIRED` key with a default, a preflight key nothing reads | `.env.example`, `Settings`, `apps`/`packages`/`scripts` AST | No | **WAS YES (third direction) → fixed** (`blind_spots()`, `:201`) | `Makefile:174`, `ci.yml:242` |
| `check_ledger_immutability` | an `UPDATE`/`DELETE`/`TRUNCATE` against a ledger in code or the ORM, a cascade, a trigger missing/disabled/non-raising/`ENABLE ORIGIN`/uncovered on a verb | tree AST + `pg_trigger` | No | **WAS YES (check 1, the code half) → fixed** (`blind_spots()`, `:298`). The TRIGGER half never could: an unmigrated database has no triggers → fail, and DB-unreachable prints `code OK; database unchecked` locally while FAILING under `CI` — a named degradation, not a silent one | `Makefile:191`, `ci.yml:161` |
| `check_metadata_columns` | a live column no model declares, or a model column the database lacks | `Base.metadata` vs the live schema | No | **WAS YES (empty database) → fixed**: refuse, exit 2 (`:98`, `:124`) | `Makefile:199`, `ci.yml:168` |
| `check_model_residency` | a Google model host that is not Vertex `asia-south1`; the region becoming settable from the console | tree AST | No | **No** — `blindness_failures()` (`:622`) fails when the provenance scan drops below `MINIMUM_TEMPLATES`, and the check plants its own canary constant for the scan to find | `Makefile:216`, `ci.yml:230` |
| `check_observability_ready` | a component declared ON and misconfigured; a lost Sentry scrubber or unwrapped span exporter; a langfuse import, dependency or settings field appearing | `Settings` + `core/observability` AST + `apps`/`packages`/`scripts` AST + `pyproject.toml` | No | **WAS YES (the langfuse rung) → fixed**: both its surfaces now raise `ObservabilityBlindError` and `main()` exits 2. The other rungs never could — exit 2 REFUSED when no `Settings` can be built, and `check_sentry_hooks` reads a NAMED file and reports "cannot see its subject" rather than passing | `Makefile:230`, `ci.yml:186` |
| `check_openapi_fresh` | any contract difference — a path, a schema, a property type, a required list, a parameter, an `x-calevate-permission` | **committed** `apps/web/src/lib/api/openapi.json` vs `app.openapi()` | **No — checked hardest.** `--write` is the only writer and runs in no gate; `gen:api` reads the file to emit TS | **No.** A missing snapshot is an explicit FAIL (`:154`), not an exit 0 | `Makefile:247`, `ci.yml:273` |
| `check_public_routes` | an undeclared exempt route, a declaration matching no live route, a `PUBLIC_PREFIXES` entry covering nothing, a mutating exempt route with no named credential, an exempt route carrying `x-calevate-permission` | the LIVE app's route table + RBAC registry | No | **No.** "no exempt routes found" is an explicit refusal (`:520`) | `Makefile:253`, `ci.yml:281` |
| `check_raw_sql` | a `text(...)` whose string is not literal-derived, including through a parameter followed to its CALL SITES; `exec_driver_sql`/`literal_column` by name | `apps/` + `packages/` AST | No | **No — the house idiom.** Zero modules loaded → exit 2; zero `text(...)` found → exit 2 (`:777`) | `Makefile:246`, `ci.yml:269` |
| `check_redaction_exposure` | a raw-PII field reachable from a default response (transitively), a stale allowlist entry, an allowlisted route that lost its role check or audit write | the live OpenAPI + route AST | No | **No.** An empty spec makes all four `ALLOWED_ROUTES` stale → fail; a permission walk that finds nothing announces "this check is blind" (`:382`) rather than passing | `Makefile:238`, `ci.yml:199` |
| `check_rls_coverage` | a tenant table with no FORCEd `tenant_isolation` policy, a policy not reading the GUC, a permissive policy reopening a table, a stale or too-thin exemption, registry drift, an unregistered `platform_*` or object-ref table | `pg_catalog` + the registry | No | **No.** An empty database makes `actual` ≠ `expected` and fails on registry drift (`:264`) | `Makefile:190`, `ci.yml:157` |
| `check_web_env_parity` | an undeclared read, an unread declaration, a secret-shaped `NEXT_PUBLIC_` key, an uninlinable `process.env` access, an empty declaration overriding a `??` default, a duplicate, a stale `PUBLIC_BY_DESIGN` entry | `apps/web` tree + `apps/web/.env.example` | No | **No** — `blind_spots()` (`:424`) refuses on a missing/empty declaration file, fewer than 20 source files, zero `process.env` reads, or zero `NEXT_PUBLIC_*` reads beside a populated declaration file | `Makefile:189`, `ci.yml:261` |
| `check_wiring` | an unmounted router, more than one alembic head, a column no executable line names, a baseline entry that is stale or has been wired | the live route table, alembic's revision map, tree AST | No | **WAS YES (router half) → fixed** (`blind_spots()`, `:396`). The column half was covered only by accident, via `stale_baseline` (`:435`) failing on entries naming columns that no longer parse | `Makefile:258`, `ci.yml:214` |

`lint-imports` (hard rule 2) is the twenty-first gate and is `import-linter`'s own
contract evaluation: it fails on a forbidden import, and it cannot go blind by losing its
subject. **Checked, not assumed** — a contract whose `source_modules` name a module that
does not exist exits **1** with `Module 'apps.api.module_that_does_not_exist' does not
exist.`, so a renamed business module fails the gate rather than silently emptying it. The
two live contracts (`pyproject.toml`) report `Contracts: 2 kept, 0 broken`.

## Wiring

- **Every one of the twenty runs in both gates.** Verified by
  `tests/guardrail_audit_test.py::test_every_guardrail_script_runs_in_both_gates`, which
  globs `scripts/check_*.py` (never a typed list) and — since D-176 — asks for the script
  in a Makefile RECIPE LINE and in a parsed CI `run:` scalar rather than anywhere in the
  file text.
- **A failure genuinely fails the job.** Each guardrail is its own CI step, so one red
  guardrail does not hide the other nineteen: `if: ${{ !cancelled() }}` on every step
  (`ci.yml:141-281`) is what makes the rest still run when an earlier one fails, and
  `tests/coverage_ratchet_guard_test.py:1143` bans `continue-on-error` from the workflow
  outright. This is precisely what the reference's single 23-command
  `ci:reliability-gates` chain loses.

  **Grepped, not assumed.** `continue-on-error` appears in `ci.yml` only inside two
  comments explaining why it is absent (`:134`, `:146`). The only `&&` in the workflow is
  in a MinIO health-poll loop (`:87`), which is a readiness wait and not a gate chain; the
  only `&&` in the Makefile is inside a comment (`:92`). Every one of the twenty scripts
  has its own `- name: "Guardrail: …"` step carrying its own `if: ${{ !cancelled() }}` and
  a `run:` naming exactly one script.
- **`make guardrails` is fail-fast, not a table.** Make aborts the target at the first
  failing recipe line, so the local gate reports one problem at a time. That is right for
  the dev loop and it is NOT the CI behaviour; ENGINEERING-PRACTICES §2's
  `parity:scorecard` bullet said "prints a single pass/fail table" and now says what the
  target actually does.
- **`make check`** = `lint-check types coverage-ratchet guardrails eval-ci web-check`
  (`Makefile:115`), prerequisite-based rather than chained.

## Negative controls run for this audit

Every fix was watched failing before it was believed.

1. **`check_metadata_columns`** — `compare_entries("sqlite://")` (an empty in-memory
   database): `column_failures(...) == []` and `absent_model_tables(...)` = all 61 model
   tables. Running the entry point with `ALEMBIC_DATABASE_URL=sqlite://` printed
   `METADATA COLUMNS: REFUSED (61 table(s) ...)` and exited **2**; before the fix the same
   input printed `OK`. Pinned by
   `tests/metadata_columns_guard_test.py::test_an_unmigrated_database_is_refused_rather_than_reported_clean`,
   which needs no Postgres. Against the real migrated database the check still prints
   `METADATA COLUMNS: OK (61 tables agree in both directions)`.
2. **`check_wiring`** — with `API_ROOT` and `VOICE_RUNTIME_ROOT` pointed at an empty
   directory, `declared_routers() == []` and `unmounted_routers() == []` (the vacuous
   pass), while `blind_spots()` names it. Same for `SCAN_ROOTS` and the column half.
   `tests/wiring_guard_test.py`, two tests.
3. **`check_env_parity`** — `direct_env_reads(tmp_path) == {}` with `blind_spots(root=…)`
   naming the missing scan root, and `blind_spots(reads={})` naming the matcher.
   `tests/guardrail_audit_test.py::TestEnvParity::test_a_search_that_looks_at_nothing_refuses`.
4. **`check_config_applies`** — with `managed_fields` monkeypatched to return nothing,
   `check_every_key_is_classified()` and `check_bounds()` both return `[]` and
   `blind_spots()` reports the empty registry.
   `tests/guardrail_audit_test.py::TestConfigApplies`.
5. **`check_ledger_immutability`** — `check_sources(root=<empty dir>) == []` (the vacuous
   pass) beside a `blind_spots(root=…)` naming all three missing search dirs AND the
   zero-file scan. `main()` with `SEARCH_DIRS = ("no_such_directory",)` printed
   `LEDGER IMMUTABILITY: FAIL — this check cannot see its own subject` and exited **1**;
   before the fix the same input printed `OK (8 ledgers, ... no mutating statements in app
   code)` and exited 0. The ORM half separately: `ledger_model_classes` monkeypatched to
   `dict` makes `blind_spots()` name the empty class map.
   `tests/guardrail_audit_test.py::TestLedgerImmutability`, three tests.

   **The first version of this fix failed its own control**, and that is worth recording:
   `dirs: tuple = SEARCH_DIRS` binds the tuple once at import, so rebinding the module
   constant changed nothing and `main()` still printed OK. Reading the constant at call
   time — which is what `check_env_parity.blind_spots` already does — is the fix, and one
   way per problem is why it is spelled the same way.
6. **`check_observability_ready`** — `langfuse_footholds(roots=(<missing dir>,))` and
   `langfuse_footholds(pyproject=<absent file>)` both refuse by name; before the fix both
   returned `[]`, which `check_langfuse` renders as `[skip] langfuse: Not present in the
   tree` — a claim about a tree it never opened. `main()` with `IMPORT_ROOTS` pointed at a
   missing directory printed `OBSERVABILITY READINESS: REFUSED — the langfuse rung is
   blind: …` and exited **2**.
   `tests/observability_readiness_guard_test.py::TestLangfuse`, two tests added plus one
   existing test corrected: it isolated the import surface by passing an ABSENT manifest,
   which is now a refusal, and passes an empty one instead — a surface that exists and
   declares nothing rather than one that was never read.
7. **The wiring test** — every command running `scripts.check_coverage_ratchet` deleted
   from copies of both files, leaving the two comments that name it: the OLD rule reported
   it wired in both gates (`True`/`True`); the NEW rule reports it wired in neither
   (`False`/`False`). Also proved live by deleting `check_wiring`'s recipe line from the
   Makefile and watching the test say *"check_wiring is named in no COMMAND in the
   Makefile. A mention in a comment is not a gate."*

## Cleared, by name

Examined, a failing input identified, and left alone — fourteen of twenty, plus
`lint-imports`. Each was probed against the input that would make it go blind, not only
read:

| Check | The probe | What it did |
|---|---|---|
| `check_audit_ip` | `SCOPE` pointed at an empty directory | `AUDIT IP: FAIL`, exit 1 — both `PERMITTED` entries reported unmatched. The allowance is verified LIVE, so an empty scan is a failure, not a pass |
| `check_raw_sql` | `load_modules(root=<empty dir>)` | raised `RawSqlError: scan root 'apps' does not exist` — the house idiom, refusing rather than returning `[]` |
| `check_rls_coverage` | reasoned from `:264` | an empty database gives `actual = ∅` against 44 registry tables → `registry drift` fails. Not probed live: the database is shared and this check reads `pg_catalog` |
| `check_public_routes` | read at `:513-539` | `audit()` raises `PublicRouteError("no exempt routes found …")` before any comparison; `main()` exits **2** |
| `check_openapi_fresh` | read at `:153`, plus a tree-wide grep for `--write` | a missing snapshot is an explicit FAIL, and `--write` appears in NO Makefile recipe, CI step, deploy script or package manifest — only in prose. `gen:api` reads the file |
| `check_redaction_exposure` | read at `:377-383` | `routes and not any(route.enforced …)` returns "this check is blind"; and an EMPTY spec makes all four `ALLOWED_ROUTES` stale, so both shapes fail |
| `check_bootstrap_keys` | read at `:61-90` | `BOOTSTRAP_KEYS` spells the six independently of `ENV_ONLY_KEYS`, so emptying the constant under test fails `check_list` six times. `check_filter_applied` pushes a real value through the real door |
| `check_drill_freshness` | read at `:156-189`, `:371` | `check_this_module_cannot_write()` runs inside `main()`, not only in a test; `ALLOWED_IMPORTS` + `FORBIDDEN_CALLS` walked over its own AST; clock off the filename |
| `check_deploy_env` | read at `:218-227` | `env_file_missing` and `settings_unbuildable` are REFUSAL codes and `example_file_unreadable` is a named WARNING — no path returns 0 on an input it could not read |
| `check_docs_drift` | `blind_spots()` at `:1336`, called at `:1424` | wired as a section of `main()`, not a helper nobody calls |
| `check_compliance_invariants` | `blind_spots()` at `:320`, called at `:1103` | same, and DB-unreachable is a named non-verdict locally / FAIL under `CI` |
| `check_web_env_parity` | `blind_spots(state)` at `:424`, called at `:653` | same |
| `check_model_residency` | `blindness_failures()` at `:622`, called at `:653` | same, with `MINIMUM_TEMPLATES` and a canary constant the scan must find |
| `check_coverage_ratchet` | READ ONLY — see below | — |

`check_compliance_invariants` carries a documented soft edge worth knowing rather than
fixing: it degrades to a NAMED partial verdict when no database answers, and is a hard
failure under `CI` — the environment where it blocks a merge.
`check_ledger_immutability` shares that edge and, after finding #5, no longer shares the
clearance.

## What could not be determined here

`check_coverage_ratchet` was audited by reading and was NOT executed: its pytest plugin
refuses any run whose stores were not empty before the first test, which this environment
cannot provide, and the instruction for this work forbade running it. Its three-way exit
and its two refusal families are read off the source (`:812`, `:839`), not observed. It is
the one check in this document whose verdict is inherited rather than watched — and
findings #5 and #6 are what that distinction costs, since both were CLEARED BY READING in
the first pass of this audit and both fell over the moment they were run against an empty
tree. Treat the coverage-ratchet row accordingly.

`check_rls_coverage`'s empty-database refusal is likewise reasoned from `:264` rather than
observed: the Postgres on port 5433 is shared with the main working tree, and pointing a
guardrail at an empty database means creating one, which this work had no mandate to do.
The reasoning is short and the code is one comparison, but it is not a negative control.

`mypy scripts` (as opposed to the gate's `mypy apps packages`) reports ten pre-existing
errors in six files, none of them in a `check_*.py` touched here. `scripts/` is outside
the typed surface CI checks; naming it here rather than fixing it because widening the
mypy target is a change to what the gate MEANS, and that is a decision-log entry.
