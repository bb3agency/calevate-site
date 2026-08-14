# Calevate — ONE image, three services (api, voice-runtime, workers).
#
# DEPLOYMENT §1 fixes this shape: "Python services (api, voice-runtime, workers) run in
# Compose — one image, three services." The three differ only in their command, so one
# image means one build, one uv resolution, one CVE surface to patch, and no way for the
# three to drift onto different dependency versions of the same lockfile.
#
# WHY THAT DOES NOT BREAK HARD RULE 3 (voice-runtime's deploy is never coupled to api's).
# The rule is about DEPLOY coupling — an api change must not restart the container that
# is answering live calls. A shared image does not cause that: `compose.prod.yml` gives
# voice-runtime its own service, `scripts/vps-deploy.sh` swaps services INDEPENDENTLY
# (`up -d --no-deps <service>`), and the script's change detection maps paths to
# components so an `apps/api/crm/**` edit produces no voice-runtime restart at all. What
# the shared image does mean is that a change to `packages/shared`, `apps/api/core` or
# the lockfile is a change to voice-runtime too — which is TRUE, because voice-runtime
# imports those (see apps/voice-runtime/main.py's docstring). Separate images would hide
# that fact, not remove it.
#
# Build context is the repo root because the workspace lock spans every member.
# `.dockerignore` is what keeps that from shipping `.venv`, `.git` and node_modules.
#
# References (read Aug 2026): docs.astral.sh/uv/guides/integration/docker/ for the
# `COPY --from=ghcr.io/astral-sh/uv:<version>` pattern, the cache mounts, and the
# two-phase sync that keeps the dependency layer cacheable.

# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12-slim-bookworm

# --- build ---------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder

# PINNED, and pinned to the version this repo's uv.lock was written by (`uv --version`
# on the dev host, Aug 2026). A floating `:latest` here would be a supply-chain hole AND
# a reproducibility hole: uv's resolver output is version-sensitive, so an unpinned uv
# can produce a different tree from the same lockfile.
#
# NOT YET PINNED BY DIGEST. A tag is mutable; a digest is not. The digest could not be
# resolved where this was written (no registry access), so it is left as a tag with this
# note rather than a made-up sha256. Pinning it is a one-line change and belongs in the
# first PR that runs a build with a network — see infra/nginx/README.md's sibling note
# in DEPLOYMENT §4 on hand-first steps.
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Phase 1: third-party dependencies only. `--no-install-workspace` skips every workspace
# member, so this layer is invalidated ONLY by uv.lock or a pyproject — not by app code,
# which is what makes a code-only deploy a sub-minute build instead of a full resolve.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-runtime/pyproject.toml apps/voice-runtime/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

# Phase 2: the workspace. `calevate-shared` is the only real distribution here (hatchling
# build backend); apps/* are `package = false` virtual members that run from source, which
# is why PYTHONPATH below is /app rather than a site-packages install.
COPY packages/shared packages/shared
COPY apps/api apps/api
COPY apps/voice-runtime apps/voice-runtime
COPY apps/workers apps/workers
COPY apps/__init__.py apps/__init__.py
COPY alembic alembic
COPY alembic.ini alembic.ini
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime -------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runtime

# curl is here for ONE reason: the compose healthcheck. Without an in-image HTTP client
# the healthcheck has to be a python one-liner that imports httpx and pays an interpreter
# start every few seconds on the box that also has to ack webhooks in 500ms.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root. The container writes nothing to disk in normal operation (recordings and raw
# payloads go to object storage — hard rule 2), so there is no volume to chown.
RUN useradd --create-home --uid 10001 calevate

WORKDIR /app
COPY --from=builder --chown=calevate:calevate /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER calevate

# Deliberately no CMD. Three services share this image and each names its own command in
# compose.prod.yml; a default here would be a fourth, unowned way to start the process
# and the first thing to go stale when one of the three changes.
