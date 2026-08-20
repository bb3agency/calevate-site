# Calevate — DEV-SETUP.md

Version 1.0. From zero to a running local stack. Target machine: Linux/macOS/WSL2.

## 1. Prerequisites

Docker + Compose v2 · Python 3.12 + `uv` · Node 20 + `pnpm` · `terraform` (infra work
only) · accounts/keys: Bolna (API key, D-31), Sarvam (₹1,000 free credits), an **Azure
subscription with an Azure OpenAI resource created in South India and a `gpt-4o-mini`
deployment** (`AZURE_OPENAI_RESOURCE` + `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_DEPLOYMENT`
— D-410; **not** an OpenAI platform key, which is disqualified because OpenAI's India
residency covers storage at rest only and inference runs in the US), Cloudflare R2 or DO
Spaces (local dev uses MinIO instead). Authentication is first-party and needs no vendor
account (D-165/D-170/D-177 — Clerk is deleted).

> ⚠ **READ BEFORE YOU CREATE THE AZURE RESOURCE — TWO DROPDOWNS DECIDE THE RESIDENCY
> POSTURE AND NEITHER IS VISIBLE AFTERWARDS FROM THE ENDPOINT.**
>
> **(1) Region.** Create the resource in **South India**. `AZURE_LOCATION` is
> `southindia` and is the only spelling of the region in shipped code, but
> `https://<resource>.openai.azure.com/openai/v1` — the URL `azure_openai_base_url()`
> builds — **names no region at all**. Nothing in this repository can prove where your
> resource lives; `scripts/check_model_residency.py` proves only that the code cannot
> construct a non-India one. Confirming the resource itself is OPERATIONS §2 gate 20, and
> it is a human reading the portal.
>
> **(2) Deployment type.** Choose **Regional Standard**, NOT Global. **Global is the
> default and it processes requests worldwide.** A Global deployment inside a South India
> resource passes every check in this tree and breaks the client DPA. It also costs
> roughly 5–10% less, which is the wrong reason to pick it — that difference is the price
> of the residency posture. This is OPERATIONS §2 gate 20c.
>
> **The deployment NAME is not the model name.** On Azure you deploy a model under an id
> you choose and call THAT id, so `AZURE_OPENAI_DEPLOYMENT` and `AZURE_OPENAI_MODEL` are
> separate settings and the deployment id can never be derived. `AZURE_OPENAI_MODEL`
> defaults to `AZURE_OPENAI_DEFAULT_MODEL` (`gpt-4o-mini`) and accepts only what
> `AZURE_OPENAI_MODELS` allows; `gpt-4.1-mini` is the live switch, and its availability in
> Indian regions is **not confirmed** — check quota before switching (gate 20b).
>
> **The key is static.** No rotation cron, no service account, no org policy: the v1
> surface takes the key in `Authorization: Bearer`. Put it in the secrets manager, never in
> a committed file, and never log it.
>
> Nothing is blocked meanwhile: with no Azure credential, `assist_capability()` answers
> `no_credential` and the disclosed Sarvam fallback carries the dashboard assistant, while
> the in-call leg simply does not run (OPERATIONS §2).

## 2. Bootstrap

```bash
git clone <repo> calevate && cd calevate
cp .env.example .env                  # fill values per §4
make up                               # = docker compose up -d: postgres:16+pgvector, redis:7, minio
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed         # reserved slugs, vertical templates, retention defaults
uv run python -m scripts.seed_dev     # LOCAL ONLY: demo accounts + a tenant with calls in it
pnpm install
```

### Signing in to the two panels

`scripts/seed.py` deliberately creates no account: on a real host the first operator
arrives through `scripts/bootstrap_admin.py` (which mails a single-use link and refuses to
run twice) and the first client through the onboarding wizard. That is correct for a
deployment and useless for looking at a screen, so `scripts/seed_dev.py` is the other
motion — `make seed-dev`, or the command above.

It creates a superadmin, a client owner, a client staff member, an ACTIVE tenant
(`Sunrise Dental Care`, `sunrise-dental`) with a LIVE agent, and six completed calls with
transcripts, extractions, leads and usage rows behind them — so the calls list, the CRM,
the needs-attention queue, the funnel and the usage panel all have something in them. It
prints the credentials when it finishes. Re-running it is safe and is the supported way
back to a known state: the demo rows are keyed and are not duplicated, and the three
passwords are re-set on every run.

**It refuses to run unless `APP_ENV=local`, and there is no override** — the passwords are
published in its own source, so the gate is the same equality `core/auth.py` requires
before it will accept a `dev:` bearer token. `tests/seed_dev_guard_test.py` pins that, and
the pin is sabotage-verified.

Two things about it that are honest rather than convenient:

- **The admin realm still wants a second factor** (TRD §2, and MFA there is mandatory, not
  a setting). The code is emailed; with no mail provider configured locally
  `ConsoleTransport` prints the message in the API server's log, so read it from there.
- **The agent is published through `agents.service.publish_agent`**, the same call the
  console makes — on `ENGINE=fake` it really reaches `live`. If publishing fails, the seed
  finishes anyway and prints the failure: an agent left in `draft` is an honest screen,
  and one set to `live` by an UPDATE would be a lie the compliance drift sweep would later
  have to catch.

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
the source-IP allowlist is exercised separately in `tests/voice_runtime_security_test.py`,
and the per-engine choice of authenticity method (allowlist vs HMAC, and the refusal to
fall back from one to the other) in `tests/signing_engine_intake_security_test.py`.

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
is the starting point when you have real values for the browser-side keys. Two things make it a different kind of
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
