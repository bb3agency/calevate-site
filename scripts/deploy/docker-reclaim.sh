#!/usr/bin/env bash
# How this host reclaims disk from Docker, in ONE place, because three callers need it and
# three copies would drift: the deploy's pre-build ladder, the deploy's post-deploy tidy,
# and the daily hygiene job.
#
# Sourced, never executed.
#
# ====================================================================================
# THE DEADLOCK THIS EXISTS TO BREAK
#
# `docs/evidence/raghava-deploy-teardown.md` §9 row 3 quotes the reference host's own
# comment, which is the clearest statement of the failure anyone has written down:
#
#     The post-build prune only runs AFTER a successful build. If the disk is already
#     near-full the build itself dies ("no space left on device" while extracting a
#     layer) and the cleanup that follows never runs — a deadlock that wedges every
#     subsequent deploy.
#
# Our deploy's answer used to be a single refusal at 3GB with two commands printed for a
# human. That walks into the same trap from the other side: it is correct at 2GB and
# useless at 4GB, where the disk is not yet fatal but the build is about to make it so,
# and the reclaim that would have prevented it is gated behind a success that never
# happens. A floor is not a strategy; an ESCALATION is.
#
# ====================================================================================
# THE LADDER, AND WHAT EACH RUNG COSTS
#
#   tier 0  routine     stopped containers of OUR compose project, dangling images, and
#                       the build cache capped at BUILD_CACHE_KEEP. Costs nothing but
#                       build time on the next cold layer. Runs every time, at every
#                       free-space level, including "plenty".
#   tier 1  cache       the ENTIRE build cache. Costs a slower next build.
#   tier 2  rollback    per-commit app image tags beyond the newest one. Costs the cheap
#                       rollback (DEPLOYMENT §4 step 6) — a rollback becomes a rebuild.
#   tier 3  everything  every image no container references, including base images.
#                       Costs a full cold pull-and-build.
#
# Tiers 1-3 only run below RECLAIM_PURGE_FLOOR_GB, they run in that order, and the ladder
# STOPS at the first rung that gets free space back above the floor. That ordering is the
# whole design: the cheapest thing to lose goes first, and the artefact an incident needs
# (the previous release's image) is given up second-to-last rather than first. The
# reference's version reaches for `image prune --all` immediately, which throws away the
# rollback artefact to save a build cache — exactly backwards on the day it matters.
#
# Below RECLAIM_REFUSE_FLOOR_GB after all of that, the caller refuses. There is nothing
# left to reclaim from Docker and the next thing to fail would be the build, halfway,
# leaving dangling layers that make the following attempt fail sooner.
#
# ====================================================================================
# WHY TWO FLOORS AND WHY THESE TWO NUMBERS
#
# One floor cannot express the two different facts:
#
#   * RECLAIM_PURGE_FLOOR_GB = 8 — "a build STARTED here would probably finish, but it is
#     close enough that I am not going to find out." A cold build of `Dockerfile` holds,
#     at once: the build context, the uv-resolved virtualenv layer, the BuildKit cache
#     (capped at 3GB by tier 0), and the finished image, while the PREVIOUS image is still
#     on disk because containers are running from it. 8GB is the reference host's number
#     (`vps-deploy.sh:221`, PREBUILD_MIN_FREE_GB) and it is kept because it is the only one
#     of the two that has ever been observed against a real build — ours has not been run
#     on a host at all (DEPLOYMENT §4d), so inventing a different number here would be
#     replacing evidence with taste.
#
#   * RECLAIM_REFUSE_FLOOR_GB = 3 — "a build started here WILL fail." Unchanged from what
#     this repo already refused at, and unchanged on purpose: the refusal threshold is not
#     what was wrong, the absence of everything above it was.
#
# Both are overridable by environment for a host with a different disk, and both are named
# constants rather than literals because the gap between them IS the mechanism — a reader
# who sets them equal has silently deleted the ladder.

# `log`/`warn` come from the caller when there is one (the deploy defines coloured ones);
# these are the fallback so this file is usable from a bare shell and from a systemd unit.
if ! declare -F log >/dev/null 2>&1; then
  log() { printf '==> %s\n' "$*"; }
fi
if ! declare -F warn >/dev/null 2>&1; then
  warn() { printf '[warn] %s\n' "$*" >&2; }
fi

RECLAIM_PURGE_FLOOR_GB=${RECLAIM_PURGE_FLOOR_GB:-8}
RECLAIM_REFUSE_FLOOR_GB=${RECLAIM_REFUSE_FLOOR_GB:-3}

# The build cache tier 0 leaves behind. Same 3GB the post-deploy prune has always used.
BUILD_CACHE_KEEP=${BUILD_CACHE_KEEP:-3GB}

# --- measuring --------------------------------------------------------------------------

# Free whole gigabytes at a path, rounded DOWN, or 0 if the path cannot be measured.
#
# `df -Pk` and integer division rather than `df -BG`: `-BG` rounds UP to the next whole
# block, so 200MB free reports as `1G` and a check written against it is optimistic in
# precisely the situation it exists for. POSIX output format (`-P`) because the default
# wraps long device names onto a second line.
free_gb_at() {
  local path=$1
  [[ -e "$path" ]] || { printf '0'; return 0; }
  df -Pk "$path" 2>/dev/null | awk 'NR==2 {printf "%d", int($4/1048576)}' || printf '0'
}

# Where Docker actually writes. On a single-volume VPS this is the same filesystem as the
# checkout; on a host whose images live on an attached volume it is not, and the build
# fills THIS one. Asked of the daemon rather than assumed, with the packaged default as
# the fallback for a host where the daemon is not answering (in which case nothing below
# will work anyway, and a wrong path is not the reason).
docker_root() {
  docker info -f '{{.DockerRootDir}}' 2>/dev/null || printf '/var/lib/docker'
}

# The number the ladder is judged on: the SMALLER of "free where the checkout is" and
# "free where Docker writes". They are usually the same filesystem; when they are not,
# taking the larger would be measuring the volume that is not about to fill.
reclaim_free_gb() {
  local repo_free docker_free
  repo_free=$(free_gb_at "${1:-$PWD}")
  docker_free=$(free_gb_at "$(docker_root)")
  if (( docker_free < repo_free )); then printf '%s' "$docker_free"; else printf '%s' "$repo_free"; fi
}

# --- the build-cache flag, which moved ---------------------------------------------------
#
# `--keep-storage` is DEPRECATED; the replacement is `--reserved-space`. The deprecation
# notice on Docker Engine 28.x points at `--max-storage`, a name that was used internally
# and never shipped, so following the message gets an "unknown flag" — moby/moby#50120,
# open as of this writing. Both spellings are therefore wrong on some engine we might meet:
# the old one on an engine that has finished removing it, the suggested one on every engine
# that exists. So ASK the binary which flag it has rather than pinning either.
#
# Sources (accessed 17 Aug 2026): docs.docker.com/reference/cli/docker/builder/prune —
# `--reserved-space`, `--max-used-space`, `--min-free-space`; moby/moby#50120 "builder
# prune says keep-storage is deprecated but suggested replacement doesn't work".
_builder_cache_flag=""
builder_cache_flag() {
  if [[ -z "$_builder_cache_flag" ]]; then
    if docker builder prune --help 2>/dev/null | grep -q -- '--reserved-space'; then
      _builder_cache_flag="--reserved-space"
    else
      _builder_cache_flag="--keep-storage"
    fi
  fi
  printf '%s' "$_builder_cache_flag"
}

# --- tier 0: the routine reclaim ----------------------------------------------------------
#
# Safe at any free-space level, so it is unconditional. Nothing here can remove a running
# container, an image a container references, or a named volume — `redis-data` is on this
# host and `docker volume prune` is therefore not in this file at all, at any tier.
#
# SCOPED TO OUR COMPOSE PROJECT, which is teardown correction (c). `docker container prune`
# with no filter removes every stopped container on the box, and this host also runs the
# dev compose project (`calevate-dev`) during an operator's debugging session; removing
# somebody's stopped container while they are reading its logs is a small betrayal with no
# upside. Dangling IMAGES are not scoped — a dangling image belongs to nobody by
# definition, which is what dangling means.
reclaim_routine() {
  local project=${1:-calevate}
  log "reclaim tier 0: stopped containers ($project), dangling images, build cache -> $BUILD_CACHE_KEEP"
  docker container prune --force --filter "label=com.docker.compose.project=$project" >/dev/null
  docker image prune --force >/dev/null
  docker builder prune --force "$(builder_cache_flag)" "$BUILD_CACHE_KEEP" >/dev/null
}

# --- the per-commit tag cap ---------------------------------------------------------------
#
# Per-commit tags (DEPLOYMENT §4 step 2) are NOT dangling, so `docker image prune` will
# never reclaim one and they would otherwise accumulate one image per deploy forever. This
# is the other half of that decision: keep the newest `keep`, drop the rest.
#
# Two rules make it safe. Nothing referenced by a container — running OR stopped — is a
# candidate, so it cannot delete what is serving traffic or what `docker start` would need.
# And a removal that fails is reported and does not abort: at the post-deploy call site the
# deploy has already succeeded, and turning a housekeeping refusal into a DEPLOY FAILED
# banner teaches operators that the banner does not mean anything.
reclaim_app_image_tags() {
  local repo=${1:?} keep=${2:?}
  local in_use candidate
  in_use=$(docker ps -a --format '{{.Image}}' | sort -u)

  local -a stale=()
  while IFS= read -r candidate; do
    [[ -n "$candidate" && "$candidate" != *"<none>"* ]] || continue
    if ! grep -qxF "$candidate" <<<"$in_use"; then stale+=("$candidate"); fi
  done < <(docker image ls --filter "reference=$repo" --format '{{.Repository}}:{{.Tag}}' \
           | tail -n +$(( keep + 1 )))

  (( ${#stale[@]} )) || { log "app images: nothing beyond the newest $keep to remove"; return 0; }

  log "removing ${#stale[@]} app image(s) older than the newest $keep"
  local ref
  for ref in "${stale[@]}"; do
    if ! docker image rm "$ref"; then
      warn "could not remove $ref (message above). This is disk housekeeping, not a
     deploy failure. 'docker ps -a --filter ancestor=$ref' names what is holding it."
    fi
  done
}

# --- the ladder ----------------------------------------------------------------------------
#
# THE VERDICT IS THE MEASUREMENT, NOT AN EXIT CODE, and that is deliberate. Callers invoke
# this in a condition (`|| die`), which suppresses errexit for its whole dynamic extent, so
# a prune that fails does not stop the ladder — it falls through to the next rung and the
# next `reclaim_free_gb`. That is the right semantic: reclaim is best-effort and free space
# is the fact that matters. A Docker daemon that is not answering makes every rung a no-op
# and then fails loudly at `docker build`, naming itself, one step later.
#
# Returns 0 when free space is at or above RECLAIM_REFUSE_FLOOR_GB when it finishes, and 1
# when it is not. It prints what it did and what that cost; it never exits, because the two
# callers refuse differently — the deploy dies with a message about the build it is not
# going to start, and any future caller may want to do something else.
reclaim_for_build() {
  local project=${1:?} repo=${2:?} root=${3:-$PWD}
  local free

  reclaim_routine "$project"
  free=$(reclaim_free_gb "$root")
  if (( free >= RECLAIM_PURGE_FLOOR_GB )); then
    log "disk: ${free}GB free (floor ${RECLAIM_PURGE_FLOOR_GB}GB) — no purge needed"
    return 0
  fi

  warn "disk: only ${free}GB free, below the ${RECLAIM_PURGE_FLOOR_GB}GB build floor. Escalating."

  log "reclaim tier 1: the entire build cache (costs a slower next build)"
  docker builder prune --all --force >/dev/null
  free=$(reclaim_free_gb "$root")
  if (( free >= RECLAIM_PURGE_FLOOR_GB )); then
    log "disk: ${free}GB free after tier 1"
    return 0
  fi

  warn "reclaim tier 2: dropping per-commit app images except the newest. THE CHEAP
     ROLLBACK IS GONE after this — 'git checkout <sha> && vps-deploy.sh --all --no-pull'
     will rebuild rather than reuse an image (DEPLOYMENT §4 step 6)."
  reclaim_app_image_tags "$repo" 1
  free=$(reclaim_free_gb "$root")
  if (( free >= RECLAIM_PURGE_FLOOR_GB )); then
    log "disk: ${free}GB free after tier 2"
    return 0
  fi

  warn "reclaim tier 3: every image no container references, base images included. The
     next build is fully cold."
  docker image prune --all --force >/dev/null
  free=$(reclaim_free_gb "$root")

  if (( free < RECLAIM_REFUSE_FLOOR_GB )); then
    warn "disk: ${free}GB free after every tier — below the ${RECLAIM_REFUSE_FLOOR_GB}GB hard floor."
    return 1
  fi
  warn "disk: ${free}GB free after every tier. Above the ${RECLAIM_REFUSE_FLOOR_GB}GB hard
     floor so the build may proceed, but this host is out of Docker-shaped space to
     reclaim: the next deploy has nothing left to escalate to. Find what is using the
     volume ('du -xhd1 / | sort -rh') before it is an incident."
  return 0
}
