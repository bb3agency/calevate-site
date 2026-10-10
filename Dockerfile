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

# Pinned by digest for the same reason as the uv image below (D-188, hard rule 9): a tag
# can be moved under us. The digest is the multi-arch index of `python:3.12-slim-bookworm`
# (`docker buildx imagetools inspect`, 4 Oct 2026). Base-image security fixes therefore
# arrive as Dependabot pull requests (the `docker` block in .github/dependabot.yml), not
# silently on the next build. Written out in both FROM lines rather than through an ARG,
# because Dependabot updates literal image references.

# --- build ---------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS builder

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
# THE SYNC TARGET IS THE WORKSPACE ROOT, WHOSE `dependencies` ARE EXACTLY THE THREE
# MEMBERS THIS IMAGE RUNS (D-667). Not `--all-packages`: that also installs
# `calevate-pipecat-worker`, whose pipecat-ai/onnxruntime/numpy/sympy/sarvamai tree (41
# distributions, 111 against 70) nothing here imports, on the hosts that hold
# PLATFORM_KEK. Not a repeated `--package`: uv only accepts that on sync from 0.9.8, and
# the binary above is 0.8.17. Root `pyproject.toml` carries the full argument.
#
# D-188 is the failure this line must never return to: the root once declared no
# dependencies, a bare `uv sync` installed nothing and exited 0, and the image shipped an
# empty venv. `tests/server_image_dependency_set_test.py` reads `uv.lock` and fails if
# the root stops reaching api, voice-runtime and workers, or starts reaching the voice
# worker's tree.
#
# `--group errors` installs `sentry-sdk` IN THE IMAGE, because §2 puts no Python on the
# host and the venv lives in a layer owned by a non-root user, so there is no host-side
# command that could add it. It is a ROOT group, which is the other reason the target is
# the root: `--package <member> --group errors` refuses. Installing it costs voice-runtime
# nothing at import time — `init_observability` imports the SDK only when a DSN is set —
# so the operator's switch is `SENTRY_DSN`.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-runtime/pyproject.toml apps/voice-runtime/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group errors --no-install-workspace

# Phase 2: the workspace. `calevate-shared` is the only DISTRIBUTION here (hatchling build
# backend); apps/* are `package = false` virtual members, which is why PYTHONPATH below is
# /app rather than a site-packages install.
#
# BOTH OF THEM RUN FROM SOURCE, and this comment used to imply otherwise. `uv sync`
# installs a workspace distribution EDITABLE, so site-packages gets no package — it gets
# `_editable_impl_calevate_shared.pth`, whose whole content is one absolute path:
#
#     /app/packages/shared/src
#
# baked from THIS stage's WORKDIR at build time. `COPY --from=builder /app /app` below
# lands the tree back at that same path, which is the only reason `import calevate_shared`
# resolves at runtime — not a site-packages copy. Move either WORKDIR, or copy the tree
# anywhere but `/app`, and the build still succeeds, the venv still lists
# `calevate-shared 0.1.0`, and all four entrypoints die on their first import. That is
# D-188's shape one layer along, so it is guarded rather than remembered:
# `scripts/check_image_paths.py`, negative controls in tests/image_paths_guard_test.py.
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
    uv sync --frozen --no-dev --group errors
COPY scripts scripts
COPY .env.example .env.example
# THE OPERATOR RUNBOOKS, because the admin copilot answers out of them (D-499,
# `apps/api/copilot/runbooks.py`). Not documentation shipped for its own sake: it is the
# corpus a running process reads, so leaving it out would make `search_runbooks` work in
# every test and return nothing in production — the half-wired shape CLAUDE.md names by
# hand. ~412 KB of markdown, after the sync for the same reason `scripts` is: it is not a
# workspace member and copying it earlier would invalidate the install layer on every
# runbook edit. `docs/` is deliberately NOT copied — 5.5 MB of blueprint that nothing
# reads at runtime.
COPY runbooks runbooks

# --- runtime -------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS runtime

# curl is here for ONE reason: the compose healthcheck. Without an in-image HTTP client
# the healthcheck has to be a python one-liner that imports httpx and pays an interpreter
# start every few seconds on the box that also has to ack webhooks in 500ms.
#
# tzdata because `TZ=Asia/Kolkata` below names a zone file, and without one glibc falls
# back to UTC silently. The bookworm-slim base already carries it (tzdata 2025b-0+deb12u2
# in `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, 10 Oct 2026); naming it makes that a
# property of this file rather than of the base.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tzdata \
 && rm -rf /var/lib/apt/lists/*

# Non-root. The container writes nothing to disk in normal operation (recordings and raw
# payloads go to object storage — hard rule 2), so there is no volume to chown.
RUN useradd --create-home --uid 10001 calevate

WORKDIR /app
COPY --from=builder --chown=calevate:calevate /app /app

# IST is the platform's standard time (D-709). TZ sets the process's LOCAL zone, which is
# what anything that names no zone falls back to. What matters names its own and is not
# moved by this: `core/logging.LOG_TIMEZONE`, `workers/settings.CRON_TIMEZONE`, and the UTC
# database session (`db/session.APP_SESSION_TIMEZONE`).
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata

USER calevate

# Deliberately no CMD. Three services share this image and each names its own command in
# compose.prod.yml; a default here would be a fourth, unowned way to start the process
# and the first thing to go stale when one of the three changes.
