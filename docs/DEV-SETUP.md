# Calevate — DEV-SETUP.md

Version 1.0. From zero to a running local stack. Target machine: Linux/macOS/WSL2.

## 1. Prerequisites

Docker + Compose v2 · Python 3.12 + `uv` · Node 20 + `pnpm` · `terraform` (infra work
only) · accounts/keys: Bolna (API key, D-31), Sarvam (₹1,000 free credits), a **Google
Cloud project with Vertex AI enabled in `asia-south1` and a service-account key**
(`GCP_PROJECT_ID` + `GCP_SERVICE_ACCOUNT_JSON` — **not** a Google AI Studio API key, which
D-127 disqualifies for having no data-residency guarantee), Clerk (two applications:
calevate-admin, calevate-client), Cloudflare R2 or DO Spaces (local dev uses MinIO
instead).

> ⚠ **READ BEFORE YOU SPEND AN HOUR ON THE GCP CONSOLE.**
> `GEMINI_MODEL_CONFIRMED_IN_REGION is False` — nobody has verified that `asia-south1`
> serves `calevate_shared.engine.GEMINI_DEFAULT_LLM`, which is **`gemini-2.5-flash`**. As
> of 16 Aug 2026 the public evidence points the RIGHT way for the first time (search
> places the 2.5 class in Mumbai and no 3.x model there, which is why the model moved to
> 2.5), but every page that would settle it is refused by this environment's egress proxy,
> so the flag stays False. **The first `generateContent` you make is the test.** A 404 is
> the answer "no", and the worker logs `vertex_model_not_served_in_region` naming the
> region, the model and this flag rather than the bare word `HTTPStatusError`.
>
> ⏰ **AND IT HAS A DEADLINE.** `gemini-2.5-flash` retires **16 Oct 2026** (BRD R-04) —
> the cost of picking the model Mumbai serves over the one with a longer life.
> `GEMINI_DEFAULT_LLM_RETIRES` holds that date and CI goes red on 16 Sep 2026 asking for
> the replacement. See OPERATIONS §2 gate 14b before you plan any work that assumes this
> identifier is still answering.
>
> When it is a 404, try `gemini-2.5-flash-lite` (the founder's stated fallback), then
> whatever `asia-south1` does serve — and flip this flag when one answers 200.
> **Do NOT widen the region and do NOT reach for `locations/global`** —
> Google's own words on the global endpoint are that you cannot control or know which
> region processes the request, which is the sentence D-127 disqualifies AI Studio over.
> `scripts/check_model_residency.py` will refuse the commit either way.
> Nothing is blocked meanwhile: `assist_capability()` answers `provider_unavailable` and
> the disclosed Sarvam fallback carries the dashboard assistant (OPERATIONS §2).

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

**The dev compose project is named `calevate-dev`**, declared at the top of
`docker-compose.yml` rather than defaulted from the directory name. The reason is in that
file's header and it is a production one: on the VPS the deploy directory is
`/var/www/calevate`, so an unnamed dev file resolved to the same compose project as
`compose.prod.yml` and a bare `docker compose up -d` there would have recreated
production redis from the dev definition. **If you ran `make up` before this line
existed**, your old containers and volumes still exist under the previous project name
(your directory's basename) and this file no longer sees them: `docker compose ps` looks
empty and Postgres comes up fresh. `make db-reset` reseeds it; `docker volume ls` still
lists the old volumes if anything in there mattered.

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

## 4. Environment variables — eight, and everything else is a screen

`.env.example` used to carry 58 keys. It carries **8**, and they are exactly the ones
without which no process can start (D-95, PLATFORM-CONFIG §4). The other **50** — 33
core-config values and 17 credentials — are set from the ops console at
`admin.calevate.tech/ops`, live, with no SSH session and no restart.

```
APP_ENV=local|staging|prod
DATABASE_URL=postgresql+psycopg://calevate_app:calevate_app@localhost:5433/calevate
ALEMBIC_DATABASE_URL=postgresql+psycopg://calevate:calevate@localhost:5433/calevate
REDIS_URL=redis://localhost:6380/0
PLATFORM_KEK=                                 # blank locally, see below
PLATFORM_KEK_RETIRED=                         # blank until you have rotated
OBJECT_STORE_ENDPOINT=http://localhost:9000   # MinIO locally; R2/Spaces in cloud
OBJECT_STORE_BUCKET=calevate-dev
```

**The bootstrap ordering problem — the whole reason these eight stayed.** Resolution
order is `os.environ` → `platform_settings`/`platform_secrets` → code default → refuse.
Reading a key from the store therefore requires a process that has already reached the
store. **The console cannot configure the thing the console needs in order to start.**
Concretely:

| Key | Why it can never move |
|---|---|
| `APP_ENV` | decides whether `dev:<realm>:<clerk-id>` tokens are accepted (D-49). Reading it from the store means the store decides the security posture. |
| `DATABASE_URL` | it *is* how you reach the store. |
| `ALEMBIC_DATABASE_URL` | migrations run before the store is guaranteed to exist — including the migration that creates it. |
| `REDIS_URL` | workers need it before settings resolve, and the config sentinel (the cheap poll that tells every process the console changed something) lives in Redis. |
| `PLATFORM_KEK` | it is the key that decrypts every console-managed secret. A database holding both the lock and the key is theatre. |
| `PLATFORM_KEK_RETIRED` | same, for the previous key during a rotation. Unwraps only, never wraps. |
| `OBJECT_STORE_ENDPOINT` | **the floor is 8, not §4's 6, for a mechanical reason.** Both are REQUIRED `Settings` fields with no default, so `Settings()` cannot construct without them — a process whose environment lacks them cannot boot far enough to look them up. The console does manage them; when they are set here they show as source `env`, read-only. |
| `OBJECT_STORE_BUCKET` | same. |

`tests/env_example_bootstrap_floor_test.py` proves both halves: copying the template
boots, and dropping any one type-required key refuses.

**Rules.** `.env` is never committed. A NEW variable goes in
`packages/shared/src/calevate_shared/config.py` and is console-managed from that moment —
it belongs in `.env.example` only if a process cannot reach the store without it, which
is a claim the floor test will check. Env still wins over the store everywhere, so
pasting a key into `.env` is the 3am escape hatch when the console itself is what is
broken; the console renders any such key read-only, with that as the stated reason.

**Local work needs no console.** Every one of the 50 has a local-safe default or a
named refusal — `ENGINE=fake`, the console/dev sinks for SMTP, WhatsApp and Sheets, a
derived constant for each HMAC secret. The API boots and reports `/healthz/ready` on the
8 alone against a migrated database (verified, D-95 phase 6). When you do
need a real vendor key locally, either add the line to your own `.env` (env wins) or set
it in the console against your local database; a real Sarvam or Bolna key is worth
adding to `.env` rather than typing into a screen every reset.

**The browser's variables are a SECOND file: `apps/web/.env.example`.** Next loads `.env*`
from the package directory, not from the repo root, so the file above configures the API,
the workers and voice-runtime and reaches the browser never. Nothing to do for local work —
every value in it is the local default — but `cp apps/web/.env.example apps/web/.env.local`
is the starting point when you have real Clerk keys. Two things make it a different kind of
file from the one above: `next build` INLINES each `NEXT_PUBLIC_*` value, so changing one
needs a rebuild rather than a restart and a missing one is the empty string rather than an
error; and nothing prefixed `NEXT_PUBLIC_` is private, because it ships in the bundle to
every visitor. Both directions are a CI gate (`scripts/check_web_env_parity.py`), so a new
browser key goes in `apps/web/.env.example` in the same change as its first read — never in
the root `.env.example`, where it would fail the API's parity check instead.

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
**guardrails** + eval-ci + **web-check** — the CI gate) · `make guardrails` (executable
governance, §2, seven checks: `lint-imports`, env-parity, RLS coverage, ledger
immutability, redaction exposure, OpenAPI freshness, wiring) · `make web-check`
(frontend: typecheck + lint + vitest; `next build` is CI-only) ·
`make lint` · `make types` (`mypy apps packages`, not `.`) ·
`make test` · `make smoke` · `make db-reset` · `make eval CLIENT=<slug>` (regression
harness core5) · `make gen-api` (OpenAPI → typed TS client) · `make conformance` (both
engine adapters).

## 7. First contribution path (suggested order for a new dev/agent)

1. Read docs/README.md → TRD → DATA-MODEL (30 min).
2. Run smoke test; break it on purpose (comment out RLS policy) and watch the zero-rows
   test fail — internalize the tenancy model.
3. Pick a ROADMAP M1 item; ship a vertical slice with tests; attach eval report if agent
   behavior changed.
