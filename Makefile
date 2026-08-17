.DEFAULT_GOAL := help
# EVERY target is phony — none of them produces a file of its own name. `guardrails`
# was missing from this list, which meant a stray file or directory named `guardrails`
# in the repo root would make `make guardrails` print "nothing to be done" and exit 0:
# the CI gate reporting success without running a single check.
.PHONY: help dev up down check lint lint-check types test db-reset eval eval-ci \
        qa-report qa-report-publish \
        gen-api conformance smoke guardrails web-check coverage-ratchet \
        coverage-ratchet-accept

# `check` fans out to prerequisites that share one database and one working tree.
# Under `make -j` they would interleave — guardrails reading a schema another target
# is migrating — and the failure would be unreproducible. Order is part of the gate.
.NOTPARALLEL:

# Every line is single-quoted: `(CI gate)` unquoted is a shell syntax error, which
# made the DEFAULT goal — plain `make` — exit 2 instead of printing this list.
help:  ## List targets
	@echo 'Calevate targets:'
	@echo '  make up          - start postgres+pgvector, redis, minio'
	@echo '  make down        - stop local infra'
	@echo '  make dev         - run all four services'
	@echo '  make lint        - ruff check --fix + format; rewrites files'
	@echo '  make check       - lint-check, mypy, pytest+ratchet, guardrails, eval, web [CI gate]'
	@echo '  make web-check   - frontend typecheck + vitest suite'
	@echo '  make db-reset    - drop, migrate, seed'
	@echo '  make eval CLIENT=slug - regression harness (core5)'
	@echo '  make qa-report CLIENT=slug VERTICAL=clinic - client-facing QA report'
	@echo '  make qa-report-publish CLIENT=slug VERTICAL=clinic - same, stored for their Quality screen'
	@echo '  make gen-api     - OpenAPI snapshot -> typed TS client'
	@echo '  make guardrails  - executable governance (D-29)'
	@echo '  make coverage-ratchet - suite under coverage + the per-surface ratchet [CI gate]'
	@echo '  make conformance - both engine adapters'
	@echo '  make restore-drill [SABOTAGE=kind] - local half of the backup/restore drill'

up:  ## Local infra
	docker compose up -d

down:
	docker compose down

## Four services. voice-runtime uses --app-dir because its directory is
## hyphenated (not importable as a module path); see README note.
dev:
	uv run uvicorn apps.api.main:app --reload --port 8000 & \
	uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime & \
	uv run arq apps.workers.settings.WorkerSettings & \
	pnpm -C apps/web dev

lint:  ## Fix in place — the dev loop
	uv run ruff check --fix .
	uv run ruff format .

lint-check:  ## Exactly what CI runs: report, never rewrite
	# `make check` uses this rather than `lint`: a gate that silently fixes the tree
	# passes locally and then fails in CI on the code that was actually committed.
	uv run ruff check .
	uv run ruff format --check .

types:
	# `apps packages`, not `.` — two conftest.py files with no package __init__
	# collide under mypy's module resolution, and it stops before checking anything.
	# This is the exact invocation CI runs.
	uv run mypy apps packages

test:
	uv run pytest

## D-29's `coverage:ratchet`. ONE suite run, instrumented — not a second suite on top
## of `make test`, which is what "must not double the suite" rules out. `make check`
## calls this INSTEAD OF `test` for that reason; plain `make test` stays uninstrumented
## because the loop a developer runs fifty times a day should not pay for a gate that
## only has to be right once per push.
##
## `-p scripts.check_coverage_ratchet` loads the gate's own pytest plugin, which records
## what the suite did — outcomes, deselection, whether Postgres and Redis were up, and
## whether EITHER still held data from an earlier run — into `.coverage-run.json`. The
## gate REFUSES to score (exit 2) a run that manifest cannot vouch for, instead of turning
## a partial or differently-seeded run into a fictional regression. Without the flag there
## is no manifest and the gate refuses, which is the intended failure: a measurement whose
## provenance is unknown is not a measurement this repo scores.
coverage-ratchet:  ## Full suite under coverage, then the per-surface ratchet [CI gate]
	uv run coverage run -m pytest -q -p scripts.check_coverage_ratchet
	uv run python -m scripts.check_coverage_ratchet

coverage-ratchet-accept:  ## Lock in an improvement: rewrite the baseline (shrink-only)
	# The ONLY writer of tests/fixtures/coverage_baseline.json. It refuses to raise a
	# budget without a RAISED_BUDGETS waiver in the script, so this command can lock in
	# progress and can never quietly forgive a regression.
	#
	# START FROM EMPTY STORES: `make db-reset` AND a Redis with nothing in it
	# (`make down && make up`, or `redis-cli -n <db> flushdb`). What those two HOLD
	# changes which branches the suite executes — leftover tenants send the dispatch
	# tick down another path, and a warm cache deletes a read-through fallback from the
	# measurement entirely (`loadshed.get_platform_status` queries Postgres only on a
	# MISS) — and this gate is an equality, so
	# the difference lands as a failure on somebody else's PR. That is not hypothetical:
	# it happened twice, both times "fixed" by copying CI's number back into the fixture.
	#
	# A comment was the whole defence, which is why it failed twice: a rule enforced by a
	# comment is enforced by whoever read it last. It is executable now — the plugin
	# loaded below records the pre-suite state of both stores, and `--update-baseline`
	# REFUSES to write from a run that did not start empty. Neither reset is wired as a
	# prerequisite: a target that silently drops a developer's data is worse than one
	# that stops and says exactly what to run.
	uv run coverage run -m pytest -q -p scripts.check_coverage_ratchet
	uv run python -m scripts.check_coverage_ratchet --update-baseline

smoke:  ## tenant -> agent -> signed webhook -> lead with extraction
	uv run pytest -m smoke

# `coverage-ratchet` stands where `test` used to: it RUNS the suite (once, instrumented)
# and then scores it, exactly as CI does. Listing `test` as well would run the suite
# twice for one gate.
check: lint-check types coverage-ratchet guardrails eval-ci web-check  ## Full CI gate (mirrors .github/workflows/ci.yml)

web-check:  ## Frontend gate: typecheck, lint, vitest (CI adds `next build` on top)
	# Cheapest answer first, same order as the backend half of this gate. The SUITE is
	# the part `tsc` cannot give: the frontend carries fail-closed defaults,
	# server-authoritative verdicts (`is_verified`/`messageable`/`held`) and
	# money-as-string rules, and every one of them type-checks perfectly while being
	# wrong. `next build` is left to CI — it is the slowest check here and it catches a
	# different class of thing (route/bundle validity), so paying for it in the dev loop
	# buys nothing this target does not already have.
	pnpm -C apps/web typecheck
	pnpm -C apps/web lint
	pnpm -C apps/web test

db-reset:
	uv run alembic downgrade base
	uv run alembic upgrade head
	uv run python -m scripts.seed

# Expanded only when the `eval` recipe actually runs, so `make help` stays quiet.
# Without it `make eval` ran `--client=` and exited 0 — a harness reporting success
# for a client nobody named.
REQUIRE_CLIENT = $(or $(CLIENT),$(error make eval needs CLIENT=<slug>, e.g. CLIENT=ci))

eval:  ## make eval CLIENT=<slug>   [regression harness; fails on a REGRESSION, not on absolute red]
	uv run python -m scripts.eval --client=$(REQUIRE_CLIENT)

eval-ci:  ## The ratchet exactly as CI runs it — part of the gate, not an extra
	uv run python -m scripts.eval --client=ci

# G3 ships this to every client monthly, so VERTICAL is required for the same reason
# CLIENT is: a clinic's report listing property calls is not the asset it is sold as,
# and a default would produce one silently rather than refusing.
REQUIRE_VERTICAL = $(or $(VERTICAL),$(error make qa-report needs VERTICAL=<clinic|real_estate>))
# Its own CLIENT guard rather than `REQUIRE_CLIENT`: that one's message names `make eval`,
# and an error telling you to fix a different command than the one you ran is the kind of
# small lie that costs somebody ten minutes. The duplication is the message, not the rule.
REQUIRE_QA_CLIENT = $(or $(CLIENT),$(error make qa-report needs CLIENT=<slug>))

qa-report:  ## make qa-report CLIENT=<slug> VERTICAL=<clinic|real_estate>   [client-facing QA report, ROADMAP M3]
	uv run python -m scripts.qa_report --client=$(REQUIRE_QA_CLIENT) --vertical=$(REQUIRE_VERTICAL)

# The same document, ALSO filed against the tenant so it appears on their Quality screen
# (SURFACES §2 "rendered in-app, not just PDF"). A separate target rather than a flag on
# the one above, because the two have different requirements: `qa-report` needs no
# database and prints for any CLIENT string, while this one needs a database and refuses
# a CLIENT that is not a real tenant slug. One target that sometimes needs Postgres would
# be a target nobody could tell had half-worked.
qa-report-publish:  ## make qa-report-publish CLIENT=<slug> VERTICAL=<...>   [same report, stored for the client's in-app Quality screen]
	uv run python -m scripts.qa_report --client=$(REQUIRE_QA_CLIENT) --vertical=$(REQUIRE_VERTICAL) --store

gen-api:
	pnpm -C apps/web gen:api

conformance:  ## Keep the exit door oiled — run both adapters
	uv run pytest -m conformance

guardrails:  ## Executable governance (ENGINEERING-PRACTICES.md §2); grows per milestone
	uv run lint-imports
	uv run python -m scripts.check_env_parity
	# The same rule for the OTHER tier's config. `next build` INLINES every
	# NEXT_PUBLIC_* value, so an undeclared or misspelled browser key is not a build
	# error — it is the empty string in the bundle and a broken screen in production.
	# Reads come off the live `apps/web` tree, declarations off `apps/web/.env.example`
	# (a second file because a real `KEY=` line in the root one fails the check above).
	# Needs no Node and no database. Negative controls in tests/web_env_parity_guard_test.py.
	uv run python -m scripts.check_web_env_parity
	uv run python -m scripts.check_rls_coverage
	uv run python -m scripts.check_ledger_immutability
	# The ORM models are what the NEXT migration is autogenerated against, so a live
	# column no model declares is `--autogenerate` proposing to DROP it in a diff a human
	# skims. Eight had accumulated (P4.3) — including one created while the finding was
	# being fixed, which is why this is a check and not a list. Columns only: 38 of the 39
	# live `compare_metadata` diffs are indexes and constraints the ORM deliberately does
	# not declare. Needs the migrated database. Negative controls in
	# tests/metadata_columns_guard_test.py.
	uv run python -m scripts.check_metadata_columns
	# The six bootstrap keys may only ever be read from the environment (D-95 §4). A
	# change that lets APP_ENV resolve from the console store is a security-posture
	# inversion that reads like a harmless refactor, so it fails CI by name.
	uv run python -m scripts.check_bootstrap_keys
	# Every console-managed setting says WHEN a change takes effect, and is bounded.
	# `applies: live` on a key really read once at boot is a lie that costs an outage,
	# and a new Settings field arrives managed but unclassified (D-101).
	uv run python -m scripts.check_config_applies
	# The SAME doctrine as the two above, on the value whose change is a compliance event
	# rather than an outage: every Google model endpoint is Vertex AI `asia-south1`, and
	# the region is a `Final` constant rather than a console field (D-127). Runs BEFORE
	# the Vertex client exists (PLAN Part 12 before Part 13) — write the guard that makes
	# a global endpoint impossible before writing the client that could reach one. Needs
	# no network and no credential; it is decidable from syntax. `extraction.py`'s AI
	# Studio URL is a dated, self-expiring allowance IN the script, not a skip. Negative
	# controls, including a doctored `us-central1` tree, in tests/model_residency_guard_test.py.
	uv run python -m scripts.check_model_residency
	# `audit_log.ip` records the CALLER. Eighty handlers used to read the socket peer
	# inline — behind nginx that is our own edge — so SEC-COMP §5's fourth field was
	# satisfied in shape only on every audited route. Syntax-decidable; the one
	# permitted peer read is named, and the check fails if it leaves its function.
	uv run python -m scripts.check_audit_ip
	# How many pooled connections one task may hold at once (D-182). The pool's
	# `max_overflow` is 1, so two is survivable and three is a self-deadlock against a
	# saturated pool — and the shape that produces three is a cross-module call chain no
	# single-file reviewer can see. Syntax-decidable; needs no database. Negative
	# controls, including a doctored three-deep tree, in tests/session_nesting_guard_test.py.
	uv run python -m scripts.check_session_nesting
	uv run python -m scripts.check_redaction_exposure
	uv run python -m scripts.check_openapi_fresh
	# Half-wired features (CLAUDE.md). Here rather than in pytest because it needs no
	# database and its subject is the SHAPE of the tree — the same class of question
	# `lint-imports` and the redaction scan ask. Its negative controls, which need a
	# tmp tree and a doctored route table, live in tests/wiring_guard_test.py.
	uv run python -m scripts.check_wiring
	# Hard rule 5 over the whole tree (D-29's `check:compliance-invariants`). Here and
	# not in pytest for two reasons: its schema half reads pg_catalog exactly as
	# `check_rls_coverage` does, and its subject is the SHAPE of every dial path rather
	# than the behaviour of one — the pytest suites (compliance_audit, campaigns,
	# campaign_dispatch_audit) own the behaviour and keep it. Negative controls in
	# tests/compliance_guard_test.py.
	uv run python -m scripts.check_compliance_invariants
	# D-29's `check:docs-drift`. Here rather than in pytest for the reason the two above
	# are: no database, no app boot, and its subject is the SHAPE of the repo — the doc
	# set against the Makefile, the package scripts, the decision log and the code's own
	# vocabulary. Negative controls in tests/docs_drift_guard_test.py.
	uv run python -m scripts.check_docs_drift

# --- Backup/restore drill (OPERATIONS §6, runbooks/backup-restore-drill.md) ---
# Its own .PHONY line, same reasoning as the pilot block below.
.PHONY: restore-drill

## THE LOCAL HALF of the quarterly drill, and the target `scripts/restore_drill.py`'s own
## usage block has always named — there was no rule for it, so a committed 1500-line
## harness naming a command that did not exist was reachable from nothing and had almost
## certainly never run. That is the same class of finding as an unapplied terraform tree,
## and it is worse here, because the whole point of this harness is proving the verifier
## goes RED.
##
## NEEDS `make up` (Postgres on 5433 for the scratch databases, MinIO on 9000 standing in
## for R2) plus `age`, `pg_dump` and `pg_restore` on PATH. It creates and drops its own
## `calevate_drill_*` databases and touches nothing else — every destructive statement in
## it checks the name against `SCRATCH_DB_PATTERN` first.
##
## Its verdict is `GREEN (local scope)`, never `PASS`: it does not test wal-g, R2, the
## offsite provider, the age identity in the secrets manager, the systemd timers or
## rclone, and it prints that list next to its verdict every run. **A green run here does
## NOT tick "backups verified" on OPERATIONS §8** — only the quarterly runbook does, and
## §0a there maps what this covers onto what it does not.
##
##   make restore-drill                              # the chain, green path
##   make restore-drill SABOTAGE=drop-rls-policy     # prove it goes red, naming that defect
##
## SABOTAGE kinds: corrupt-object, drop-rls-policy, disable-append-only-trigger,
## tamper-audit-row.
restore-drill:  ## Local half of the backup/restore drill [GREEN (local scope), never PASS]
	uv run python -m scripts.restore_drill $(if $(SABOTAGE),--sabotage=$(SABOTAGE),)

# --- Bolna pilot (OPERATIONS §2, ROADMAP gate G0) -----------------------------
# Its own .PHONY line rather than an edit to the one at the top: these targets were
# added while other slices were editing this file, and an append cannot collide.
.PHONY: pilot-preflight pilot

pilot-preflight:  ## What the Bolna pilot still needs — credentials, tunnel, number, credit
	uv run python -m scripts.pilot preflight

## DRY RUN. Placing a real call needs the explicit opt-in flag and --max-calls, which
## are deliberately NOT in this target: a make target that can dial a telephone is a
## make target somebody runs by accident. Exit 2 is normal here and means "nothing went
## red, and nothing was verified either" — a dry run proves nothing about the vendor.
pilot:  ## Dry run of the API-executable pilot gates (1 webhook trust, 2 provisioning, 6 webhook loss)
	uv run python -m scripts.pilot run --gates 1,2,6
