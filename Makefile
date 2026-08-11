.DEFAULT_GOAL := help
# EVERY target is phony — none of them produces a file of its own name. `guardrails`
# was missing from this list, which meant a stray file or directory named `guardrails`
# in the repo root would make `make guardrails` print "nothing to be done" and exit 0:
# the CI gate reporting success without running a single check.
.PHONY: help dev up down check lint lint-check types test db-reset eval eval-ci \
        gen-api conformance smoke guardrails

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
	@echo '  make check       - lint-check, mypy, pytest, guardrails, eval, web typecheck [CI gate]'
	@echo '  make db-reset    - drop, migrate, seed'
	@echo '  make eval CLIENT=slug - regression harness (core5)'
	@echo '  make gen-api     - OpenAPI snapshot -> typed TS client'
	@echo '  make guardrails  - executable governance (D-29)'
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

smoke:  ## tenant -> agent -> signed webhook -> lead with extraction
	uv run pytest -m smoke

check: lint-check types test guardrails eval-ci  ## Full CI gate (mirrors .github/workflows/ci.yml)
	pnpm -C apps/web typecheck

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
