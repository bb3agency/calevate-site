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
# PINNED BY DIGEST (D-188), which closes DEPLOYMENT §4d item 1. A tag is mutable; a
# digest is not, and hard rule 9 is why a build input that someone else can move is not
# acceptable. The tag is kept alongside the digest because Docker accepts
# `name:tag@sha256:…` and resolves on the DIGEST — the tag is then documentation of which
# release this is, and it cannot lie, because a mismatch is a pull failure rather than a
# silent substitution.
#
# HOW THIS DIGEST WAS OBTAINED, because "a digest someone pasted" is worth no more than a
# tag: `GET https://ghcr.io/v2/astral-sh/uv/manifests/0.8.17` with an anonymous pull token,
# then `sha256sum` of the response BODY — which equals the value below and equals the
# `docker-content-digest` header the registry returned. That is the digest's definition, so
# this was verified rather than trusted. The manifest is an OCI image index carrying
# linux/amd64. `docker pull` could not complete here (the blob CDN
# `pkg-containers.githubusercontent.com` is refused by this environment's egress policy),
# so the LAYERS behind this digest are unverified — the reference is exact, the bytes are
# still first fetched on the VPS.
COPY --from=ghcr.io/astral-sh/uv:0.8.17@sha256:e4644cb5bd56fdc2c5ea3ee0525d9d21eed1603bccd6a21f887a938be7e85be1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Phase 1: third-party dependencies only. `--no-install-workspace` skips every workspace
# member, so this layer is invalidated ONLY by uv.lock or a pyproject — not by app code,
# which is what makes a code-only deploy a sub-minute build instead of a full resolve.
#
# `--all-packages` IS NOT OPTIONAL, AND ITS ABSENCE SHIPPED AN EMPTY VIRTUALENV (D-188).
# This is a uv WORKSPACE whose root is `package = false` with `dependencies = []`. uv
# syncs the ROOT project by default, so a bare `uv sync` here resolved the root's empty
# dependency list, installed nothing, and exited 0 — the image's `/app/.venv` contained
# three files and not one third-party package. Every service, `alembic upgrade head` and
# every `scripts.*` module the deploy runs through `compose run` would have died on the
# first import. It went unseen because the whole deploy path is unverified (§4d) and
# because a successful `uv sync` that installs nothing looks exactly like a cache hit.
# The repository already knew: README.md's command table, `.github/workflows/ci.yml` and
# DEPLOYMENT §3/§8 all say `--all-packages`; this file was the one place that did not.
# Verified by building both ways and counting `site-packages` (3 entries vs 150+).
#
# `--group errors` installs `sentry-sdk`, and it belongs in the IMAGE rather than on the
# host. DEPLOYMENT §8 prescribed `uv sync --all-packages --group errors` "on the api and
# worker host" — an instruction from before this Dockerfile existed and which the shipped
# architecture cannot obey: §2 puts no Python on the host, and the venv lives inside an
# image layer owned by a non-root user. So there was no reachable command that could turn
# error reporting on, `core/observability.py`'s `except ImportError` branch was again the
# only one reachable, and a host with `SENTRY_DSN` set would fail
# `check_observability_ready` forever. Installing it costs voice-runtime nothing at import
# time — `init_observability` imports the SDK only when a DSN is set — so the boot graph
# hard rule 3 protects is unchanged. The opt-in is now `SENTRY_DSN`, which is the only
# switch an operator ever actually had.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-runtime/pyproject.toml apps/voice-runtime/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --group errors --no-install-workspace

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
# THE DEPLOY RUNS THESE, AND THEY WERE NOT HERE (D-168). `scripts/vps-deploy.sh` invokes
# `python -m scripts.deploy_revision_check`, `python -m scripts.seed` and now
# `python -m scripts.check_deploy_env` through `compose run` against this image — three
# call sites that would every one of them have died with `No module named 'scripts'`,
# because nothing ever copied the package in and no compose service bind-mounts the repo.
# It has been invisible for the reason the whole deploy path is unverified: nobody has run
# it. `.env.example` comes with them because the preflight compares this deployment's
# values against the shipped template, and a check that silently skips its most useful
# half is the defect class it exists to catch. Both are text this repository already
# publishes — no credential enters a layer, and `.dockerignore` still excludes the real
# `.env` (the allow-list line there is `!.env.example`, which is what makes this legal).
#
# AFTER the sync, deliberately: neither is a workspace member, so copying them first would
# invalidate the install layer on every edit to a shell script for nothing.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --group errors
COPY scripts scripts
COPY .env.example .env.example

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
