# Calevate

Multi-tenant AI voice-agent SaaS for Indian SMBs (Telugu-first).

`docs/` is the authoritative blueprint — start at [docs/README.md](docs/README.md).
The operating manual for coding agents is [CLAUDE.md](CLAUDE.md) (and
[docs/AGENTS.md](docs/AGENTS.md) for non-Claude agents).

## Layout

```
apps/web            Next.js 15 (App Router) + TS — admin.calevate.tech + app.calevate.tech
apps/api            FastAPI modular monolith
apps/voice-runtime  FastAPI — engine webhooks, in-call tools. LATENCY-CRITICAL.
apps/workers        ARQ workers — post-call pipeline, embeddings, campaigns
packages/shared     Pydantic models, VoiceEngine protocol, normalized events
infra/              nginx templates, backup units + wal-g config, object-lifecycle
                    policy, and Terraform whose only resource is that S3 lifecycle
                    config. No host, no network, no DNS; nothing applied (D-25 moved
                    hosting off DigitalOcean — this line said "DO Bangalore" for months)
.github/workflows/  CI (listed under infra/ here until D-102's sweep; it never lived there)
```

Python members are a **uv workspace** (one `uv.lock`, one venv, `packages/shared`
editable). `apps/web` is a **pnpm workspace** package. No Turborepo/Nx — there is
only one JS app.

## Quick start

```bash
docker compose up -d          # postgres:16+pgvector, redis, minio
uv sync --all-packages        # NOTE: --all-packages, not bare `uv sync`
pnpm install
cp .env.example .env
make check                    # ruff + mypy + pytest + web typecheck
```

Run the four services:

```bash
uv run uvicorn apps.api.main:app --reload --port 8000
uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime
uv run arq apps.workers.settings.WorkerSettings
pnpm --filter web dev
```

## Local environment notes

These are deviations from `docs/DEV-SETUP.md` forced by this machine; the docs
remain authoritative on intent.

| Topic | Note |
|---|---|
| Host ports | Postgres is on **5433** and Redis on **6380** — 5432/6379 are held by another project on this machine. Container-internal ports are unchanged. |
| `uv sync` | Must be `uv sync --all-packages`. A bare `uv sync` installs only the virtual root's dev group, not the workspace members. |
| Nested workspace | `create-next-app` drops a `pnpm-workspace.yaml` **and** a `pnpm-lock.yaml` inside `apps/web`. Both were deleted: the nested file marks `apps/web` as a second workspace root with `ignoredBuiltDependencies`, which breaks `pnpm -C apps/web <script>`. Delete them again if a scaffold or upgrade recreates them. |
| voice-runtime | Started with `--app-dir apps/voice-runtime` because the directory is hyphenated and therefore not importable as `apps.voice_runtime`. |
| Platform | Windows 11 native. Postgres/Redis/MinIO run in Docker, so Linux parity holds where it matters. |

## Resolved docs conflicts

Three v1.0 conflicts surfaced during scaffolding and are now settled in the
decision log ([docs/ROADMAP.md](docs/ROADMAP.md) §6). The affected docs have
been updated to match; changing any of these needs a new entry.

| # | Conflict | Resolution |
|---|---|---|
| D-17 | `apps/api/src/engine/` (CLAUDE.md) vs `apps.api.main:app` (DEV-SETUP §2) — mutually exclusive | Flat layout: `apps/api/engine/`. Hard rule 2 governs the isolation boundary, not the path. |
| D-18 | `apps/voice-runtime` (layout) vs `apps.voice_runtime` (run command) — hyphens are illegal in Python module names | Keep the hyphen; start with `--app-dir apps/voice-runtime`. |
| D-19 | `create-next-app@latest` installs Next 16; TRD §2 locks 15 | Pin 15.5.21. Major bumps are deliberate migrations, not scaffold side effects. |

## Before writing feature code

[ROADMAP.md](docs/ROADMAP.md) Milestone 0 gates the build: the legal-entity
decision → DLT registration, and the **Bolna pilot** ([OPERATIONS.md](docs/OPERATIONS.md)
§2) — 13 gates that confirm Bolna as primary engine (D-31) and close the two
remaining unverified cost inputs, the BYOK platform fee and telephony rates.
The adapter interface in
`packages/shared/src/calevate_shared/engine.py` is deliberately engine-agnostic
so this scaffold is safe to build on before that session; the adapter
implementations are not.
