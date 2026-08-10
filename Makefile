.DEFAULT_GOAL := help
.PHONY: help dev up down check lint types test db-reset eval gen-api conformance smoke

help:  ## List targets
	@echo Calevate targets:
	@echo   make up          - start postgres+pgvector, redis, minio
	@echo   make down        - stop local infra
	@echo   make dev         - run all four services
	@echo   make check       - ruff + mypy + pytest + web typecheck (CI gate)
	@echo   make db-reset    - drop, migrate, seed
	@echo   make eval CLIENT=slug - regression harness (core5)
	@echo   make gen-api     - OpenAPI -> typed TS client
	@echo   make conformance - both engine adapters

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

lint:
	uv run ruff check --fix .
	uv run ruff format .

types:
	uv run mypy .

test:
	uv run pytest

smoke:  ## tenant -> agent -> signed webhook -> lead with extraction
	uv run pytest -m smoke

check: lint types test  ## Full CI gate
	pnpm -C apps/web typecheck

db-reset:
	uv run alembic downgrade base
	uv run alembic upgrade head
	uv run python -m scripts.seed

eval:  ## make eval CLIENT=<slug>
	uv run python -m scripts.eval --client=$(CLIENT)

gen-api:
	pnpm -C apps/web gen:api

conformance:  ## Keep the exit door oiled — run both adapters
	uv run pytest -m conformance

guardrails:  ## Executable governance (ENGINEERING-PRACTICES.md §2); grows per milestone
	uv run lint-imports
	uv run python -m scripts.check_env_parity
	uv run python -m scripts.check_rls_coverage
