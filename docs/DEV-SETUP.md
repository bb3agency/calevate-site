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
make up                               # = docker compose up -d: postgres:16+pgvector, redis:7, minio
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed         # reserved slugs, vertical templates, retention defaults
pnpm install
```

**Host ports are NOT the defaults**: compose publishes postgres on **5433** and redis on
**6380** (5432/6379 are taken by another project on the build machine). `.env.example`
already points at those — do not "fix" them back.

**No Docker? `bash scripts/dev_bootstrap.sh`.** Compose stays the documented default; the
script is the fallback for a machine where Docker is unavailable or its registry is
unreachable (sandboxed CI container, locked-down laptop). It provisions the same
postgres 16 on 5433, redis on 6380, the `calevate` owner and `calevate_app` app roles, and
runs the migrations — from distro packages, idempotently. It does NOT provision MinIO:
nothing in the suite needs it, and the one place that would (the recording copy) is
stubbed in the smoke test.

Run everything (four terminals or `make dev`):
```bash
uv run uvicorn apps.api.main:app --reload --port 8000
uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime  # D-18
uv run arq apps.workers.settings.WorkerSettings
pnpm -C apps/web dev                  # :3000 — /admin and /c/<slug> route groups
```

Smoke test: `make smoke` (= `uv run pytest -m smoke`) — creates a tenant and agent, posts
a completed-execution event to the real voice-runtime app at `/hooks/v1/engine/fake`,
asserts the ack is under 500ms and that a Lead appears with extraction populated. **No
HMAC is involved**: the local engine is `fake`, and Bolna does not sign at all (D-31) —
the source-IP allowlist is exercised separately in `tests/webhook_receiver_test.py`.

## 3. Local engine strategy

Default local mode uses the **fake engine adapter** (`ENGINE=fake`): deterministic
transcripts and events, no network — all pipeline/CRM/billing work happens offline.
Set `ENGINE=bolna` + staging keys only when testing real integration; expose your
webhook via `cloudflared tunnel` (never ngrok free tier for HMAC testing — URL churn) and
register the tunnel URL as a webhook endpoint via their API. Real PSTN test calls: staging
number only; they cost money — log them.

## 4. Environment variables (.env.example is canonical; highlights)

```
DATABASE_URL=postgresql+psycopg://calevate_app:calevate_app@localhost:5433/calevate
                          # the APP role: NOSUPERUSER NOBYPASSRLS. Hard rule 1 is only
                          # real if the role the app connects as cannot bypass a policy.
ALEMBIC_DATABASE_URL=postgresql+psycopg://calevate:calevate@localhost:5433/calevate
                          # the OWNER role — migrations only, never app code paths.
REDIS_URL=redis://localhost:6380/0
OBJECT_STORE_ENDPOINT=http://localhost:9000   # MinIO locally; R2/Spaces in cloud
OBJECT_STORE_BUCKET=calevate-dev
WEBHOOK_BASE_URL=http://localhost:8100        # baked into each agent's engine config at
                          # publish time, so it must be reachable BY THE ENGINE
ENGINE=fake|bolna
BOLNA_API_KEY=            # no webhook secret — Bolna webhooks are unsigned (TRD §5);
                          # authenticity = source-IP allowlist + dedupe + poller.
USD_INR_RATE=88.00        # engine costs arrive in USD cents; stamped into every
                          # usage_events row so the ledger stays reproducible
SARVAM_API_KEY=           # STT + LLM + TTS — the whole BYOK stack (D-36)
GEMINI_API_KEY=           # configurable FALLBACK LLM only, not the default (D-36)
COHERE_API_KEY=           # only if the D-28 RAG bake-off picks a store without
                          # bundled embeddings; otherwise leave empty
CLERK_ADMIN_* / CLERK_CLIENT_*                # two separate apps
CLERK_FRONTEND_API / CLERK_WEBHOOK_SECRET     # custom domain (D-37) + the Svix secret
                          # for the user/org mirror hook; unset = refuse every event
AUDIT_CHAIN_SECRET=       # HMAC material for the audit hash chain + idempotency scope
                          # fingerprints. Unset locally = derived constant; prod MUST set.
SMTP_* / NOTIFICATIONS_FROM                   # hot-lead alerts; unset locally = console
INBOUND_RESERVE_RATIO=0.3 # share of the engine line pool reserved for inbound (FLOWS §5)
SELF_SERVE_INR_PER_MIN=6.00                   # D-34 list price; runway framing + top-up
LANGFUSE_* / SENTRY_DSN / RELEASE_VERSION / POSTHOG_KEY   # optional locally
APP_ENV=local|staging|prod
```
Rules: `.env` never committed; prod values live only in the secrets manager, injected at
deploy; any new variable is added to `.env.example` + `packages/shared/config.py`
(Pydantic Settings — the app must fail fast on missing config, not at first use).

## 5. Database workflow

- New model → autogenerate migration → **hand-review** (autogen misses RLS) → add RLS
  policy + zero-rows test → `alembic upgrade head`.
- Local reset: `make db-reset` (drop, migrate, seed).
- `make guardrails` runs the RLS-coverage check against the migrated CI database — run it
  before opening a PR that adds a table, not after CI tells you.
- There is no local vector table to inspect: `kb_chunks` + pgvector are the D-28
  CONTINGENCY and are deliberately NOT created (see the migration's own note in
  `alembic/versions/842ba923796d_…`). The shipped KB tables are `kb_sources`,
  `kb_documents` and `kb_retrieval_logs`.

## 6. Repo Makefile targets

`make up` / `make down` (compose infra) · `make dev` (all four services from ONE shell —
plain `&` backgrounding, no honcho/process manager, so a crashed service dies quietly;
use four terminals when you need to watch one) · `make check` (= lint + types + test +
**guardrails** + web typecheck — the CI gate) · `make guardrails` (executable governance,
§2: `lint-imports`, env-parity, RLS coverage, ledger immutability, redaction exposure,
OpenAPI freshness) · `make lint` · `make types` (`mypy apps packages`, not `.`) ·
`make test` · `make smoke` · `make db-reset` · `make eval CLIENT=<slug>` (regression
harness core5) · `make gen-api` (OpenAPI → typed TS client) · `make conformance` (both
engine adapters).

## 7. First contribution path (suggested order for a new dev/agent)

1. Read docs/README.md → TRD → DATA-MODEL (30 min).
2. Run smoke test; break it on purpose (comment out RLS policy) and watch the zero-rows
   test fail — internalize the tenancy model.
3. Pick a ROADMAP M1 item; ship a vertical slice with tests; attach eval report if agent
   behavior changed.
