# Calevate — DEV-SETUP.md

Version 1.0. From zero to a running local stack. Target machine: Linux/macOS/WSL2.

## 1. Prerequisites

Docker + Compose v2 · Python 3.12 + `uv` · Node 20 + `pnpm` · `terraform` (infra work
only) · accounts/keys: Bolna (API key, D-31), Sarvam (₹1,000 free credits), Google AI
Studio (Gemini), Clerk (two applications: calevate-admin, calevate-client), Cloudflare R2
or DO Spaces (local dev uses MinIO instead).

## 2. Bootstrap

```bash
git clone <repo> calevate && cd calevate
cp .env.example .env                  # fill values per §4
docker compose up -d                  # postgres:16 + pgvector, redis:7, minio
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed         # reserved slugs, vertical templates, retention defaults
pnpm install
```

Run everything (four terminals or `make dev`):
```bash
uv run uvicorn apps.api.main:app --reload --port 8000
uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime  # D-18
uv run arq apps.workers.settings.WorkerSettings
pnpm -C apps/web dev                  # :3000 — /admin and /c/<slug> route groups
```

Smoke test: `uv run pytest -m smoke` (creates a tenant, agent, simulated call.ended
webhook with valid HMAC, asserts a Lead appears with extraction populated).

## 3. Local engine strategy

Default local mode uses the **fake engine adapter** (`ENGINE=fake`): deterministic
transcripts and events, no network — all pipeline/CRM/billing work happens offline.
Set `ENGINE=bolna` + staging keys only when testing real integration; expose your
webhook via `cloudflared tunnel` (never ngrok free tier for HMAC testing — URL churn) and
register the tunnel URL as a webhook endpoint via their API. Real PSTN test calls: staging
number only; they cost money — log them.

## 4. Environment variables (.env.example is canonical; highlights)

```
DATABASE_URL=postgresql+psycopg://calevate:calevate@localhost:5432/calevate
REDIS_URL=redis://localhost:6379/0
OBJECT_STORE_ENDPOINT=http://localhost:9000   # MinIO locally; R2/Spaces in cloud
OBJECT_STORE_BUCKET=calevate-dev
ENGINE=fake|bolna
BOLNA_API_KEY=            # no webhook secret — Bolna webhooks are unsigned (TRD §5);
                          # authenticity = source-IP allowlist + dedupe + poller.
                          # (Settings still carries legacy THINNEST_* fields until the
                          # adapter build removes them — tracked under D-31.)
SARVAM_API_KEY= / GEMINI_API_KEY= / COHERE_API_KEY=
CLERK_ADMIN_* / CLERK_CLIENT_*                # two separate apps
LANGFUSE_* / SENTRY_DSN / POSTHOG_KEY         # optional locally
APP_ENV=local|staging|prod
```
Rules: `.env` never committed; prod values live only in the secrets manager, injected at
deploy; any new variable is added to `.env.example` + `packages/shared/config.py`
(Pydantic Settings — the app must fail fast on missing config, not at first use).

## 5. Database workflow

- New model → autogenerate migration → **hand-review** (autogen misses RLS) → add RLS
  policy + zero-rows test → `alembic upgrade head`.
- Local reset: `make db-reset` (drop, migrate, seed).
- Inspect vectors: `SELECT id, left(content,60) FROM kb_chunks ORDER BY embedding <=> $1 LIMIT 3;`

## 6. Repo Makefile targets

`make dev` (all four services via honcho) · `make check` (ruff+mypy+pytest+web typecheck) ·
`make db-reset` · `make eval CLIENT=<slug>` (regression harness core5) ·
`make gen-api` (OpenAPI → typed TS client) · `make conformance` (both engine adapters).

## 7. First contribution path (suggested order for a new dev/agent)

1. Read docs/README.md → TRD → DATA-MODEL (30 min).
2. Run smoke test; break it on purpose (comment out RLS policy) and watch the zero-rows
   test fail — internalize the tenancy model.
3. Pick a ROADMAP M1 item; ship a vertical slice with tests; attach eval report if agent
   behavior changed.
