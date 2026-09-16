# Calevate voice-worker — the conversation loop, as a Pipecat Cloud container (D-592).
#
# WHY THIS IS A SECOND DOCKERFILE AND NOT A FOURTH SERVICE ON THE FIRST ONE. The root
# `Dockerfile` builds ONE image for three services because "the three differ only in
# their command". This one differs in every other way: a different platform (Pipecat
# Cloud `ap-south`, box 1 of docs/PIPECAT-MIGRATION.md §8), a different base image
# (theirs, which supplies the entrypoint that calls `bot()`), a different dependency set
# (`--package calevate-pipecat-worker`: 76 distributions, none of them arq, sentry-sdk or
# uvicorn), and a different deploy verb (`pipecat cloud deploy`, not
# `docker compose up -d`). Adding it to the shared image would put the monolith's
# dependency surface in a latency-critical voice container, which is the whole argument
# hard rule 2's third home rests on.
#
# BUILD CONTEXT IS THE REPOSITORY ROOT, like the root Dockerfile and for the same reason:
# the workspace lock spans every member, and `calevate-shared` is a workspace
# distribution this deployable depends on. Build it with
#
#     docker build -f apps/voice-worker/Dockerfile .
#
# `.dockerignore` is what keeps `.env`, `.git`, both virtualenvs and node_modules out of
# that context, and `tests/dockerfile_context_test.py` holds this file's COPY sources
# against it (a path excluded there is not in the context AT ALL — `docker build` fails
# at the step rather than shipping an empty directory).
#
# ⚠ NOTHING BELOW HAS BEEN BUILT. `docker pull` cannot complete in the environment this
# file was written in — the registry's blob CDN answers 403 through the proxy (measured
# 15 Sep 2026, same failure the root Dockerfile records for ghcr.io) — so every claim
# here is from the vendor's own scaffold, which ships INSIDE the pinned
# `pipecat-ai==1.10.0` wheel and is a primary source we can read:
# `pipecat/cli/templates/server/Dockerfile.jinja2` and
# `pipecat/cli/agent_templates/AGENTS.md`. What that scaffold does NOT say is listed in
# docs/DEPLOYMENT.md §12 under "what is still UNKNOWN"; none of it is guessed at here.

# syntax=docker/dockerfile:1

# THE VENDOR'S BASE IMAGE, AND THE ONE UNPINNED BUILD INPUT IN THIS REPOSITORY.
#
# `dailyco/pipecat-base` is what the scaffold's Dockerfile starts `FROM`, and it is not
# decoration: it carries the process entrypoint that imports `bot.py` and calls
# `bot(runner_args)` per session, plus `uv` (the scaffold runs `uv sync` without ever
# installing it). We do not supply that entrypoint and must not: the contract between it
# and the platform is the thing we cannot read.
#
# THE BASE IMAGE IS PINNED BY DIGEST, AND THE DIGEST IS THE arm64 ONE.
#
# `:latest` is a tag somebody else can move, which hard rule 9 does not accept as a build
# input. It stays an ARG so a local build can override it, but the DEFAULT is now the
# resolved digest rather than the mutable tag, and that is not cosmetic — a Pipecat Cloud
# build cannot be given a `--build-arg` at all. `pipecatcloud`'s build request carries
# exactly three things (`_utils/deploy_utils.py` -> `api.py::_build_create`: `uploadId`,
# `dockerfilePath`, `region`), so whatever this line says IS what their builder builds on.
# Leaving `:latest` here would have meant every cloud build silently taking a tag nobody
# pinned, with the ARG looking like it was protecting something.
#
# ⚠ THE COMMENT THIS REPLACES SAID THE DIGEST COULD NOT BE RESOLVED FROM HERE, AND THAT
# WAS WRONG. It assumed resolving a digest meant PULLING the image, which this
# environment's proxy does block (Docker Hub's blob CDN answers 403). Reading a manifest
# list is a different request and is not blocked:
#
#     docker buildx imagetools inspect dailyco/pipecat-base:latest --raw
#
# VERIFIED 16 Sep 2026, from the Docker Hub registry, by that command. The index lists
# linux/amd64 `sha256:613244ff092d65f9d9b5c9ba8f6a405c7557639508680f6a57d38f59069ce071`
# and linux/arm64 (below). The arm64 one is the one that matters: EVERY Pipecat Cloud
# region is arm64 (`pipecat cloud regions list`, read on the deploy host 16 Sep 2026 --
# ap-south, eu-central, us-east, us-west, no amd64 anywhere), so an amd64 base produces a
# container that never starts, with nothing in any build or deploy output naming why.
#
# This is a statement about what one registry held on one day. Re-resolve it with the
# command above -- `pipecat-worker-setup.sh digest` is that command with the architecture
# check attached -- rather than trusting this line to still be current.
ARG PIPECAT_BASE=dailyco/pipecat-base@sha256:7dcc71f3e658b66fcb36fa420a16673d3ca1c52b932d496365763dbbb9844c4c
FROM ${PIPECAT_BASE}

# Both from the vendor's scaffold and both worth keeping: bytecode compiled at build time
# rather than on the first call (this is a latency-critical process), and `copy` because
# the uv cache below is a mounted volume that hard links cannot cross.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# NO `WORKDIR`, DELIBERATELY, AND IT IS THE ONE LINE MOST LIKELY TO BE "FIXED" BY A LATER
# READER. The base image sets one and the platform's entrypoint runs in it; the scaffold
# sets none and copies to relative paths, so that is what this does. It also happens to be
# what keeps the editable install honest: `uv sync` writes
# `_editable_impl_calevate_shared.pth` holding an ABSOLUTE path under whatever the
# inherited WORKDIR is, and because this is a single stage that never moves the tree, that
# path is still correct at runtime whatever it turns out to be. (That is why
# `scripts/check_image_paths.py` is not extended to this file: the failure it guards —
# a builder stage and a runtime stage disagreeing about where the tree lives — cannot
# happen where there is one stage and no cross-stage copy.)

# Phase 1: third-party dependencies only, so this layer is invalidated by the lockfile and
# the manifests and not by application code. Every member's pyproject is copied because
# the lock spans the workspace and uv reads all of them to resolve any one of them; only
# the voice worker's own dependency set is INSTALLED.
#
# `--package calevate-pipecat-worker` IS WHAT KEEPS THE MONOLITH OUT. The root Dockerfile
# uses `--all-packages` because its image runs api, workers and voice-runtime; here that
# flag would install arq, sentry-sdk, uvicorn, the payment and sheets clients and the rest
# of `apps/api`'s surface into the container that answers the phone. Measured on this
# lockfile, 15 Sep 2026: `--package calevate-pipecat-worker` resolves 76 distributions
# (75 third-party plus `calevate-shared`), and none of the three names above is among
# them.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-runtime/pyproject.toml apps/voice-runtime/pyproject.toml
COPY apps/voice-worker/pyproject.toml apps/voice-worker/pyproject.toml
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package calevate-pipecat-worker --no-install-workspace

# Phase 2: the workspace itself. `calevate-shared` is the only DISTRIBUTION (hatchling);
# `apps/voice-worker` is a `package = false` virtual member imported from source, which is
# why `voice_worker/` is copied to the image root and reached as a top-level package
# rather than installed.
#
# NOTHING ELSE OF `apps/` COMES WITH IT, and that is the boundary rather than a size
# optimisation: this container has no business holding tenancy, billing or the console
# (hard rule 2 / D-592).
COPY packages/shared packages/shared
COPY apps/voice-worker/voice_worker voice_worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package calevate-pipecat-worker

# The entrypoint module, last, because it is the file that changes most often. The NAME is
# the platform's convention, not ours — see `bot.py`'s docstring for the evidence and for
# what about it is still unverified.
COPY apps/voice-worker/bot.py bot.py

# NO `CMD` AND NO `ENTRYPOINT`, exactly like the vendor's scaffold. The base image owns
# the process: it is what imports `bot.py` and calls `bot(runner_args)` for each session.
# A command here would be a second, unowned way to start this container and the first
# thing to go stale when the base image's contract moves.
