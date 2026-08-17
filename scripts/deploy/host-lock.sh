#!/usr/bin/env bash
# The ONE mutex on this host, and the two things that contend for it.
#
# Sourced, never executed. `scripts/vps-deploy.sh` takes it around the whole deploy;
# `scripts/deploy/host-hygiene.sh` takes it around the whole daily clean. They are the
# only two callers and they must agree on the path, which is why the path is computed
# HERE and nowhere else.
#
# WHY. `docs/evidence/raghava-deploy-teardown.md` §8.6 records the reference host's
# version of this: a `/etc/cron.daily` cleanup that ran unsynchronised with the CI runner
# and deleted the runner's staging area out from under a deploy that happened to be in
# flight at 06:25. Our hygiene job does not touch `_work` at all (that is the first of
# three corrections, and the strongest), but the second failure is not fixed by scoping:
# `docker image prune` and `docker builder prune` are host-global operations, and a prune
# racing a `docker build` can remove the layer the build is about to reference. The build
# fails with a message about a missing parent layer that names neither the prune nor the
# timer. So the two hold one lock and the interleaving cannot happen.
#
# WHY flock AND NOT A PID FILE. A pid file has to be cleaned up by the process that wrote
# it, which is exactly the thing that does not happen when a deploy is killed — an OOM
# during `next build` (DEPLOYMENT §2) is the ordinary case here, not the exotic one — and
# a stale pid file then blocks every later run until a human deletes it. `flock` holds the
# lock on an open file descriptor: the kernel releases it when the process dies, however it
# dies, so there is no stale state to clean up and no "is that pid still alive" heuristic
# to get wrong.
#
# WHY THE REPO'S STATE DIRECTORY AND NOT /var/lock. `/run/lock`'s mode is a distribution
# decision (0755 root:root on some systemd builds, 1777 on others) and a lock the deploy
# user cannot create is a lock nobody takes. `$ROOT/.deploy-state/` is created and owned by
# the deploy account by construction — it is where `vps-deploy.sh` already writes
# `deployed-sha` and `history` — so both callers can always take it, as the same user, with
# no privileged step in between.

# --- where -----------------------------------------------------------------------------
# Same computation as `vps-deploy.sh`'s ROOT/STATE_DIR, deliberately: CD exports
# VPS_CLIENT_PATH (DEPLOYMENT §3), and a hand-run script falls back to the checkout it is
# part of. Two callers resolving the lock differently is the one bug this file cannot have.
calevate_repo_root() {
  printf '%s' "${VPS_CLIENT_PATH:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}"
}

CALEVATE_STATE_DIR=${CALEVATE_DEPLOY_STATE:-$(calevate_repo_root)/.deploy-state}
CALEVATE_HOST_LOCK=$CALEVATE_STATE_DIR/host.lock

# How long a caller waits before giving up. The deploy waits: it is attended (or it is CD,
# where the concurrency group already serialises deploys) and a hygiene run is minutes at
# worst, so blocking is better than failing a deploy over housekeeping. The hygiene job
# does NOT wait long — see its own call site.
CALEVATE_LOCK_WAIT_S=${CALEVATE_LOCK_WAIT_S:-900}

# --- take ------------------------------------------------------------------------------
# Returns 0 with the lock held for the lifetime of this process, or 1 on timeout. The
# caller decides what a timeout means, because the two callers mean different things by it.
take_host_lock() {
  local holder=${1:?take_host_lock needs a holder name} wait_s=${2:-$CALEVATE_LOCK_WAIT_S}

  mkdir -p "$CALEVATE_STATE_DIR"
  # `>>` and not `>` for the LOCK fd: opening with `>` truncates before flock is called,
  # i.e. it writes to a file another process is holding — a write we have no business
  # making while waiting for a lock.
  exec {CALEVATE_HOST_LOCK_FD}>>"$CALEVATE_HOST_LOCK"

  flock -w "$wait_s" "$CALEVATE_HOST_LOCK_FD" || return 1

  # Who holds it, for a human reading `cat .deploy-state/host.lock` during an incident.
  # Written only AFTER the lock is held, through a separate truncating open, so the file
  # stays one line instead of growing a line per run. `fuser` answers the same question
  # from the kernel; this answers it after the fact, which `fuser` cannot.
  printf '%s %s pid=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$holder" "$$" > "$CALEVATE_HOST_LOCK"
  return 0
}
