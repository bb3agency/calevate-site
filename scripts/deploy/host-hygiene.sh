#!/usr/bin/env bash
# Daily host hygiene. The thing DEPLOYMENT §7 listed as "still unbuilt".
#
# Installed as a systemd timer, NOT `/etc/cron.daily` — `infra/hygiene/README.md` §2 has
# the argument, and it is the same one `infra/backup/` already made: cron's failure mode is
# mail to a mailbox nobody reads, while `OnFailure=` gives a failed run somewhere to go and
# `systemd-analyze verify` checks the unit before it ever runs.
#
# ====================================================================================
# WHAT IT DOES NOT DO, AND WHY EACH ONE IS ABSENT
#
# This is adapted from `vps-cleanup-template.sh` in the reference repository
# (`docs/evidence/raghava-deploy-teardown.md` §6.4), and four of its nine steps are
# deliberately not here. An absent step with a reason is a decision; an absent step
# without one is something the next person adds back.
#
#  1. `rm -rf "$RUNNER_DIR/_work"/*` and `_tool/*`. REFUSED — teardown §8.6. That is a
#     CI job's staging area, and deleting it from a timer deletes it out from under
#     whatever job is running at that minute. The lock below stops OUR deploy from
#     overlapping, but the runner also runs CI, `workflow_dispatch` jobs and anything else
#     the repository grows, and none of those take our lock. `_work` is the runner's to
#     manage (it cleans between jobs) and it is not ours to delete, ever. `_diag` IS
#     trimmed, by age: those are diagnostic logs, they grow unbounded, and no job reads
#     one back.
#
#  2. `journalctl --vacuum-size=200M`. REPLACED, by `infra/hygiene/journald-cap.conf` —
#     a `SystemMaxUse=` drop-in that bounds the journal permanently, in journald itself.
#     Vacuuming daily is a privileged action that fixes yesterday's overflow; a cap is a
#     property that cannot overflow. It also removes the only step here that would have
#     needed root, which is what lets this whole unit run as the unprivileged deploy
#     account (see `infra/privileged/README.md` for why that matters).
#
#  3. `find /var/log -name '*.gz' -mtime +7 -delete`. REFUSED — that is logrotate's job,
#     configured by `rotate N` in the very files that produced those `.gz`s. Deleting
#     them behind logrotate's back is a second mechanism for one problem, needs root, and
#     silently defeats a retention setting somebody chose on purpose.
#
#  4. `rm -rf "$FRONTEND/.next/cache"/*`. REFUSED. That cache is what makes the next
#     `next build` incremental, and `next build` on this host is the step that peaks over
#     2GB and gets OOM-killed with no error message (DEPLOYMENT §2, §7a). Clearing it
#     nightly trades a bounded few hundred MB for a slower, hungrier build on the one
#     component whose build is already the riskiest thing the deploy does. Its size is
#     REPORTED instead, so a cache that does misbehave is visible rather than routinely
#     erased.
#
#  5. `npm cache clean --force`. REPLACED by `pnpm store prune` — this repo builds with
#     pnpm (`pnpm-workspace.yaml`) and has no npm cache to clean. The pnpm store is the
#     equivalent unbounded thing and `prune` is its supported, idempotent answer.
#
# ====================================================================================
# IDEMPOTENT, and that is a property rather than a hope: every step is either a prune (a
# no-op when there is nothing to prune), a truncation of a log this host owns, or a read.
# Nothing here is order-dependent, nothing accumulates state between runs, and a run that
# fires twice in a minute does the same thing as a run that fires once. `Persistent=true`
# on the timer is safe for exactly that reason.
#
# EXIT STATUS: 0 when every step succeeded, 1 when any step failed. Steps do not abort one
# another — a host with no pm2 must still get its Docker prune — so the run does everything
# it can and then reports. systemd's `OnFailure=` is what turns that 1 into a human.

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/deploy/host-lock.sh
source "$here/host-lock.sh"
# shellcheck source=scripts/deploy/docker-reclaim.sh
source "$here/docker-reclaim.sh"

ROOT=$(calevate_repo_root)
COMPOSE_PROJECT=${COMPOSE_PROJECT:-calevate}
IMAGE_REPO=${IMAGE_REPO:-calevate/app}
IMAGE_KEEP=${IMAGE_KEEP:-5}
PM2_APP=${PM2_APP:-calevate-web}

# The self-hosted runner's directory. DEPLOYMENT §3: one runner dir per project,
# `~/actions-runner-calevate`. Only `_diag` is touched, and only by age.
RUNNER_DIR=${RUNNER_DIR:-$HOME/actions-runner-calevate}
RUNNER_DIAG_KEEP_DAYS=${RUNNER_DIAG_KEEP_DAYS:-7}

# Disk usage at which this run alerts rather than merely reporting. 80% is the reference
# host's number and it is kept: it is far enough from full that a human has days, and high
# enough that a healthy host does not cry wolf. The second trigger is the interesting one —
# free space below the deploy's own purge floor means the NEXT DEPLOY will start its
# reclaim ladder, and knowing that at 00:30 IST is worth more than discovering it mid-push.
DISK_WARN_PCT=${DISK_WARN_PCT:-80}

# How long to wait for the deploy's lock before giving this run up. A deploy is minutes;
# 10 of them is generous. Giving up is correct rather than forcing the issue: hygiene is
# daily and idempotent, so a skipped run costs one day of accumulated dangling images,
# while a hygiene run racing a build costs the build.
LOCK_WAIT_S=${LOCK_WAIT_S:-600}

notify="$ROOT/scripts/backup/notify.sh"

log()  { printf '==> %s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*" >&2; }

FAILED_STEPS=()

# errexit is suppressed for the whole dynamic extent of a function called in an `if`
# condition, so a step's internal failure returns here instead of killing the run — the
# same bash property `vps-deploy.sh`'s `install_nginx` documents and relies on. This is not
# a swallowed failure: the step name is collected and re-reported at the end, and the exit
# status carries it to systemd.
run_step() {
  local name=$1; shift
  if "$@"; then
    return 0
  fi
  warn "step '$name' failed (message above); continuing with the rest of the clean"
  FAILED_STEPS+=("$name")
  return 0
}

# --- the steps -----------------------------------------------------------------------

# Docker: tier 0 only. The deploy's ladder (tiers 1-3) is deliberately NOT reachable from
# here. Tier 2 destroys the per-commit images a rollback lands on, and a nightly job that
# quietly removes the rollback artefact is a job that costs you the one thing you wanted at
# 03:00 during an incident. Hygiene reports disk pressure; the deploy — which is attended,
# or is at least a thing a human just triggered — is what escalates.
hygiene_docker() {
  command -v docker >/dev/null || { log "docker is not installed here — skipping"; return 0; }
  # `|| return 1` on each, EXPLICITLY. `run_step` calls these in an `if` condition, which
  # suppresses errexit for the whole dynamic extent — so without this a failing first prune
  # would be overwritten by a succeeding second one and the step would report clean. The
  # suppression is what makes one step's failure survivable; it must not also make it
  # invisible.
  reclaim_routine "$COMPOSE_PROJECT" || return 1
  reclaim_app_image_tags "$IMAGE_REPO" "$IMAGE_KEEP" || return 1
}

# pm2 owns `calevate-web`'s stdout/stderr files and nothing rotates them by default.
# `pm2 flush <app>` truncates that app's two log files and only that app's — never the
# bare `pm2 flush`, which would truncate every process on the host including ones this
# platform did not start.
hygiene_pm2() {
  command -v pm2 >/dev/null || { log "pm2 is not installed here — skipping"; return 0; }
  if ! pm2 describe "$PM2_APP" >/dev/null 2>&1; then
    log "pm2 has no process named $PM2_APP — skipping"
    return 0
  fi
  pm2 flush "$PM2_APP" || return 1
  # Reopen the (now truncated) files. Without this the pm2 daemon keeps writing at its old
  # offset into a truncated file, which on most filesystems produces a sparse file that
  # reports the ORIGINAL size — i.e. the flush appears to have reclaimed nothing.
  pm2 reloadLogs
}

# The pnpm content-addressable store keeps every version of every package this host has
# ever installed. `prune` removes what no reachable lockfile references; it is the
# supported operation and it is idempotent.
hygiene_pnpm_store() {
  command -v pnpm >/dev/null || { log "pnpm is not installed here — skipping"; return 0; }
  pnpm store prune
}

# The runner's DIAGNOSTIC logs only. `_work` and `_tool` are not touched here or anywhere
# else in this file — see the header, item 1.
hygiene_runner_diag() {
  local diag="$RUNNER_DIR/_diag"
  [[ -d "$diag" ]] || { log "no runner diagnostics at $diag — skipping"; return 0; }
  find "$diag" -maxdepth 1 -type f -name '*.log' -mtime "+$RUNNER_DIAG_KEEP_DAYS" -delete
  log "trimmed runner diagnostics older than ${RUNNER_DIAG_KEEP_DAYS}d in $diag"
}

# Report, then decide whether a human should hear about it. Both numbers are printed every
# run so `journalctl -u calevate-hygiene` is a disk-usage history for free.
#
# DISK PRESSURE IS NOT A STEP FAILURE, and keeping those two apart is deliberate. This
# function returns 0 even when it alerts, so the unit's exit status keeps meaning "the
# clean did not complete" and `OnFailure=` keeps meaning "this job broke". A host that
# needs more disk is a different sentence from a job that could not run, they have
# different first actions, and collapsing them would send two mails about one event and
# one mail about two.
hygiene_report() {
  local used_pct free_gb next_cache
  used_pct=$(df -Pk "$ROOT" | awk 'NR==2 {printf "%d", int($5)}')
  free_gb=$(reclaim_free_gb "$ROOT")

  next_cache="absent"
  if [[ -d "$ROOT/apps/web/.next/cache" ]]; then
    next_cache=$(du -sh "$ROOT/apps/web/.next/cache" 2>/dev/null | cut -f1)
  fi
  log "disk: ${used_pct}% used, ${free_gb}GB free (min of checkout and docker root); .next/cache: $next_cache"

  if (( used_pct >= DISK_WARN_PCT )); then
    alert disk_pressure \
      "host disk is at or above the hygiene warning threshold after a full clean" \
      used_pct="$used_pct" threshold_pct="$DISK_WARN_PCT" free_gb="$free_gb"
  elif (( free_gb < RECLAIM_PURGE_FLOOR_GB )); then
    alert disk_below_build_floor \
      "free space is below the deploy's pre-build purge floor, so the next deploy will start its reclaim ladder and may give up the rollback image" \
      free_gb="$free_gb" purge_floor_gb="$RECLAIM_PURGE_FLOOR_GB"
  fi
  return 0
}

# One alert vocabulary on this host, reached the one way (`scripts/backup/notify.sh` →
# `alert-to-app.sh` → `alert()`), rather than a second delivery path with its own dedupe
# window and its own rate limit.
#
# The stage is HOST_BACKUP and that is not a mislabel, it is the correct place to send
# somebody. A full disk on this VPS takes the backup chain out first and hardest: `pg_wal`
# stops draining, unarchived segments pile up until the volume fills, and PostgreSQL stops
# accepting writes — which is exactly why `scripts/backup/backup-health.sh` check 4 already
# watches pg_wal growth. The alternative was a new `FailureStage` member for hygiene, which
# would be a second name for the same 3am question.
alert() {
  local code=$1 detail=$2; shift 2
  if [[ -x "$notify" ]]; then
    "$notify" "$code" "$detail" "$@"
  else
    warn "no alert seam at $notify; this is the only record: $code — $detail $*"
  fi
}

# --- run ------------------------------------------------------------------------------

if ! take_host_lock host-hygiene "$LOCK_WAIT_S"; then
  # Not a failure. Deliberately exit 0 so systemd does not page for a race that resolved
  # itself correctly — the whole point of the lock is that ONE of the two runs, and the
  # deploy is the one with a person waiting on it.
  log "a deploy holds $CALEVATE_HOST_LOCK and did not release it within ${LOCK_WAIT_S}s — skipping this run"
  exit 0
fi
log "hygiene: lock held, starting"

run_step docker       hygiene_docker
run_step pm2          hygiene_pm2
run_step pnpm-store   hygiene_pnpm_store
run_step runner-diag  hygiene_runner_diag
run_step report       hygiene_report

if (( ${#FAILED_STEPS[@]} )); then
  warn "hygiene finished with failures: ${FAILED_STEPS[*]}"
  exit 1
fi
log "hygiene: done, every step clean"
