.DEFAULT_GOAL := help
# EVERY target is phony — none of them produces a file of its own name. `guardrails`
# was missing from this list, which meant a stray file or directory named `guardrails`
# in the repo root would make `make guardrails` print "nothing to be done" and exit 0:
# the CI gate reporting success without running a single check.
.PHONY: help dev up down check lint lint-check types test db-reset eval eval-ci \
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
	@echo '  make gen-api     - OpenAPI snapshot -> typed TS client'
	@echo '  make guardrails  - executable governance (D-29)'
	@echo '  make coverage-ratchet - suite under coverage + the per-surface ratchet [CI gate]'
	@echo '  make conformance - both engine adapters'

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
## The check scores whatever `.coverage` holds, so the run has to be the whole suite and
## has to be THIS run — `blind_spots()` refuses a measurement that is stale, filtered, or
## missing branch data rather than reporting a fictional regression.
coverage-ratchet:  ## Full suite under coverage, then the per-surface ratchet [CI gate]
	uv run coverage run -m pytest -q
	uv run python -m scripts.check_coverage_ratchet

coverage-ratchet-accept:  ## Lock in an improvement: rewrite the baseline (shrink-only)
	# The ONLY writer of tests/fixtures/coverage_baseline.json. It refuses to raise a
	# budget without a RAISED_BUDGETS waiver in the script, so this command can lock in
	# progress and can never quietly forgive a regression.
	uv run coverage run -m pytest -q
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

gen-api:
	pnpm -C apps/web gen:api

conformance:  ## Keep the exit door oiled — run both adapters
	uv run pytest -m conformance

guardrails:  ## Executable governance (ENGINEERING-PRACTICES.md §2); grows per milestone
	uv run lint-imports
	uv run python -m scripts.check_env_parity
	uv run python -m scripts.check_rls_coverage
	uv run python -m scripts.check_ledger_immutability
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
