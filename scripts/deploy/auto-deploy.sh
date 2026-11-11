#!/usr/bin/env bash
# Deploy the tip of `production` automatically — run every few minutes by
# calevate-autodeploy.timer, as the deploy account.
#
# The host PULLS: it fetches `production` over its read-only deploy key and, when the tip is
# not what is live, takes a verified database backup and runs `vps-deploy.sh` pinned to that
# exact commit. GitHub holds no credential that reaches this host, and no Actions runner
# lives here (DEPLOYMENT §3c argues both).
#
# Order, and why:
#   1. fetch only — the working tree is untouched until vps-deploy.sh pulls under the host
#      lock, so a hand-run deploy in progress is never disturbed;
#   2. the backup, BEFORE anything changes; a failed backup stops the deploy;
#   3. vps-deploy.sh --expected-sha <tip>, which pulls, refuses any other commit, migrates,
#      swaps and health-checks, and records the live commit in .deploy-state/deployed-sha.
#
# A commit whose deploy fails is remembered in .deploy-state/autodeploy-failed-sha and not
# retried: a retry every few minutes would rebuild on a one-vCPU host beside live calls.
# The next push to `production` is tried normally.
#
# Pause:   touch /var/www/calevate/.deploy-state/autodeploy.paused   (rm to resume)
# Status:  systemctl list-timers calevate-autodeploy.timer
#          journalctl -u calevate-autodeploy.service -n 100

set -Eeuo pipefail

ROOT=${VPS_CLIENT_PATH:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}
STATE_DIR=${CALEVATE_DEPLOY_STATE:-$ROOT/.deploy-state}
BRANCH=${AUTODEPLOY_BRANCH:-production}
BACKUP=/usr/local/sbin/calevate-predeploy-backup

log() { printf '%s auto-deploy: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# The whole body is one function called on the last line: vps-deploy.sh pulls new commits
# into this checkout, and bash reads a script as it runs, so a body read lazily could be
# half old file and half new.
main() {
  mkdir -p "$STATE_DIR"

  if [[ -e "$STATE_DIR/autodeploy.paused" ]]; then
    log "paused ($STATE_DIR/autodeploy.paused exists) — nothing done"
    return 0
  fi

  local current
  current=$(git -C "$ROOT" symbolic-ref -q --short HEAD || true)
  if [[ "$current" != "$BRANCH" ]]; then
    # Detached means a rollback is in place (vps-deploy.sh --checkout); another branch means
    # someone is working on the box. Either way a human decides, not a timer.
    log "checkout is on '${current:-detached at $(git -C "$ROOT" rev-parse --short HEAD)}', not '$BRANCH' — nothing done"
    return 0
  fi

  git -C "$ROOT" fetch --quiet origin "$BRANCH"
  local target live failed
  target=$(git -C "$ROOT" rev-parse "origin/$BRANCH")
  live=$(cat "$STATE_DIR/deployed-sha" 2>/dev/null || true)
  failed=$(cat "$STATE_DIR/autodeploy-failed-sha" 2>/dev/null || true)

  if [[ "$target" == "$live" ]]; then
    return 0
  fi
  if [[ "$target" == "$failed" ]]; then
    log "${target:0:9} failed to deploy earlier — waiting for a new push (or rm $STATE_DIR/autodeploy-failed-sha to retry)"
    return 0
  fi
  if ! git -C "$ROOT" merge-base --is-ancestor HEAD "$target"; then
    log "origin/$BRANCH (${target:0:9}) is not a fast-forward of the checkout — nothing done"
    return 1
  fi

  log "deploying ${target:0:9} (live: ${live:0:9})"
  if ! sudo -n "$BACKUP"; then
    log "backup FAILED — deploy of ${target:0:9} not started"
    printf '%s\n' "$target" > "$STATE_DIR/autodeploy-failed-sha"
    return 1
  fi

  if "$ROOT/scripts/vps-deploy.sh" --expected-sha "$target"; then
    rm -f "$STATE_DIR/autodeploy-failed-sha"
    log "deployed ${target:0:9}"
  else
    local code=$?
    printf '%s\n' "$target" > "$STATE_DIR/autodeploy-failed-sha"
    log "deploy of ${target:0:9} FAILED (exit $code) — see the vps-deploy output above"
    return "$code"
  fi
}

main "$@"
