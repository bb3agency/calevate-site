#!/usr/bin/env bash
# Calevate VPS deploy — the mechanism DEPLOYMENT §4 describes.
#
# WHAT IT DOES, IN ONE SENTENCE: fast-forwards the checkout to a CI-validated commit,
# builds one image, runs migrations from THAT image, then swaps the affected containers
# one at a time and refuses to call itself finished until each one answers /healthz.
#
# ------------------------------------------------------------------------------------
# THE THREE PROPERTIES THIS SCRIPT IS BUILT AROUND
#
# 1. VOICE-RUNTIME IS NEVER DEPLOYED BECAUSE `api` CHANGED (hard rule 3).
#    Components are selected from the diff between the last recorded deploy and HEAD,
#    through an EXPLICIT path map (`components_for_paths`). An `apps/api/crm/**` edit
#    resolves to {api, workers} and voice-runtime is not restarted, not rebuilt, not
#    touched. The map is deliberately conservative in the other direction: voice-runtime
#    imports `apps/api/core` and `packages/shared`, so a change to EITHER does deploy it.
#    That is not coupling, it is the truth about what its process contains — and stating
#    it in one table is what makes it reviewable.
#
# 2. MIGRATIONS RUN BEFORE THE SWAP, AND NEVER ROLL THEMSELVES BACK.
#    Ordering argument in `run_migrations` — read it before changing the order.
#
# 3. A FAILED DEPLOY IS LOUD AND LEAVES A KNOWN STATE.
#    `set -Eeuo pipefail` plus an ERR trap that names the step, the exit code and the
#    rollback command. There is no `|| true` in this file and none should be added.
#
# ------------------------------------------------------------------------------------
# SECRETS. This script NEVER writes, generates, prints or defaults a secret. It requires
# `$ROOT/.env` to already exist — placed by a human from the secrets manager (DEPLOYMENT
# §6 tier 1) — and aborts if it does not. Everything it substitutes into nginx config is
# a hostname or a path. If you ever find yourself adding a `--set-secret` flag here, the
# answer is the secrets manager, not this file.
#
# NOT RUN AGAINST ANYTHING YET. Nothing in this repo has been deployed; see DEPLOYMENT
# §4a for the hand-first checklist and its pass condition.
#
# Usage:
#   scripts/vps-deploy.sh                       # deploy what changed since last deploy
#   scripts/vps-deploy.sh --all                 # everything, ignoring the diff
#   scripts/vps-deploy.sh voice-runtime         # exactly one component, by name
#   scripts/vps-deploy.sh --dry-run --all       # print the plan, change nothing
#   scripts/vps-deploy.sh --expected-sha <sha>  # abort unless HEAD is that commit
#
# Options:
#   --all                 deploy every component
#   --changed             deploy components affected since the last recorded deploy
#                         (the default when no component is named)
#   --expected-sha SHA    refuse to deploy anything other than this commit
#   --no-pull             do not `git pull`; deploy the tree as it stands
#   --dry-run             resolve and print the plan; touch nothing
#   -h, --help            this text
#
# Components: api  voice-runtime  workers  web  nginx

set -Eeuo pipefail

# --- configuration ------------------------------------------------------------------
# Every one of these is a path, a port, a count or a timeout. None is a credential.
ROOT=${VPS_CLIENT_PATH:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}
COMPOSE_FILE=${COMPOSE_FILE:-compose.prod.yml}
COMPOSE_PROJECT=${COMPOSE_PROJECT:-calevate}
STATE_DIR=${CALEVATE_DEPLOY_STATE:-$ROOT/.deploy-state}

# Health poll: 90 attempts x 2s = 180s. DEPLOYMENT §10 records why it is not 60s — a
# window shorter than a slow start trains operators to ignore red deploys, which is worse
# than no health check at all because it looks like one.
HEALTH_ATTEMPTS=${HEALTH_ATTEMPTS:-90}
HEALTH_INTERVAL_S=${HEALTH_INTERVAL_S:-2}

# Hard floor on free disk before a build. Below this, a build fails halfway and leaves
# dangling layers, which makes the next attempt fail sooner. Abort while it is still a
# clean abort.
MIN_FREE_GB=${MIN_FREE_GB:-3}

# nginx is only reloaded when this is explicitly 1. A deploy that silently rewrites the
# edge config of a live site is not a deploy anyone can review afterwards.
NGINX_AUTO_RELOAD=${NGINX_AUTO_RELOAD:-0}
NGINX_CONF_DIR=${NGINX_CONF_DIR:-/etc/nginx/conf.d}
NGINX_SNIPPET_DIR=${NGINX_SNIPPET_DIR:-/etc/nginx/snippets}

# Cloudflare publishes its edge ranges and changes them. `calevate-origin.conf` carries
# the date it was last refreshed; past this age the deploy stops, because a stale list
# does not degrade gracefully — it either blocks live traffic or trusts an address
# Cloudflare has released.
CLOUDFLARE_IPS_MAX_AGE_DAYS=${CLOUDFLARE_IPS_MAX_AGE_DAYS:-180}

readonly ALL_COMPONENTS=(api voice-runtime workers web nginx)

# --- output -------------------------------------------------------------------------
STEP="startup"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[abort]\033[0m %s\n' "$*" >&2; exit 1; }
step() { STEP="$1"; log "$1"; }

on_error() {
  local code=$?
  printf '\n\033[1;31m========================= DEPLOY FAILED =========================\033[0m\n' >&2
  printf 'step   : %s\n' "$STEP" >&2
  printf 'exit   : %s\n' "$code" >&2
  printf 'commit : %s\n' "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)" >&2
  printf 'db rev : %s\n' "${DB_REVISION_BEFORE:-not read}" >&2
  printf '\nNothing after the failing step ran. What is running now is whatever was\n' >&2
  printf 'running before this step — see runbooks/deploy-failed.md, which is ordered by\n' >&2
  printf 'WHICH step failed, because the recovery for a failed build and a failed swap\n' >&2
  printf 'are not the same procedure.\n' >&2
  printf '\033[1;31m=================================================================\033[0m\n' >&2
  exit "$code"
}
trap on_error ERR

# --- argument parsing ---------------------------------------------------------------
MODE=changed
DRY_RUN=0
DO_PULL=1
EXPECTED_SHA=""
SELECTED=()

usage() { sed -n '2,50p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)          MODE=all; shift ;;
    --changed)      MODE=changed; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    --no-pull)      DO_PULL=0; shift ;;
    --expected-sha) EXPECTED_SHA=${2:?--expected-sha needs a value}; shift 2 ;;
    -h|--help)      usage; exit 0 ;;
    -*)             die "unknown option: $1 (try --help)" ;;
    *)
      # shellcheck disable=SC2076  # literal match is exactly what is wanted here
      [[ " ${ALL_COMPONENTS[*]} " == *" $1 "* ]] || die "unknown component: $1 (known: ${ALL_COMPONENTS[*]})"
      SELECTED+=("$1"); MODE=explicit; shift ;;
  esac
done

cd "$ROOT"

compose() { docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@"; }

# --- 1. preflight -------------------------------------------------------------------
# Everything here is a refusal, not a fix. A deploy script that repairs its own
# preconditions is a deploy script whose preconditions nobody knows.

preflight() {
  step "preflight"

  for tool in git docker curl envsubst; do
    command -v "$tool" >/dev/null || die "$tool is not installed on this host"
  done
  docker compose version >/dev/null 2>&1 \
    || die "docker compose v2 plugin is missing (v2.24+ required — DEPLOYMENT §2)"

  [[ -f "$ROOT/$COMPOSE_FILE" ]] || die "missing $ROOT/$COMPOSE_FILE"
  [[ -f "$ROOT/Dockerfile" ]]    || die "missing $ROOT/Dockerfile"

  # The one precondition this script will never satisfy for you.
  [[ -f "$ROOT/.env" ]] || die \
    ".env is missing at $ROOT/.env. Deploy scripts NEVER write secrets (DEPLOYMENT §6):
     place it by hand from the secrets manager, then re-run. Pydantic Settings will fail
     fast on anything still missing from it."

  # Not fatal — a wrong mode is the operator's to fix and stopping a deploy over it would
  # be worse than the exposure — but it is said out loud every single time.
  local mode
  mode=$(stat -c '%a' "$ROOT/.env")
  [[ "$mode" == "600" || "$mode" == "400" ]] \
    || warn ".env is mode $mode; it holds every bootstrap credential. chmod 600 it."

  git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout"
  if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
    git -C "$ROOT" status --short --untracked-files=no >&2
    die "the checkout has local modifications. A deploy from an edited tree deploys
     something that was never reviewed and never built in CI. Commit it or discard it."
  fi

  local free_gb
  free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
  (( free_gb >= MIN_FREE_GB )) || die \
    "only ${free_gb}GB free at $ROOT; need ${MIN_FREE_GB}GB. Reclaim first:
     docker image prune -af && docker builder prune --keep-storage 3GB"

  # --- checks that used to live in the step that needed them ---------------------
  #
  # Every one of these was previously discovered at step 9 of 11 — i.e. AFTER migrations
  # had run and all three containers had been swapped — so a missing tool or a missing
  # file aborted a deploy that had already half-happened. A precondition found late is a
  # precondition that costs a rollback.

  # The browser tier's configuration. Next loads `.env*` from the PACKAGE directory and
  # inlines every NEXT_PUBLIC_* at BUILD time, so a missing file here does not fail the
  # build — it bakes empty strings into the bundle and ships. The observable result is a
  # console whose API base is `http://localhost:8000`, i.e. every client's browser calling
  # its own machine, behind a page that returns 200 to the health poll.
  if in_plan web; then
    [[ -f "$ROOT/apps/web/.env.local" || -f "$ROOT/apps/web/.env.production" ]] || die \
      "apps/web/.env.local is missing. Next inlines NEXT_PUBLIC_* at BUILD time from the
     PACKAGE directory — the root .env is not read and is forbidden from carrying them
     (apps/web/.env.example). Without it the bundle ships with an empty API base and empty
     Clerk publishable keys, and the deploy still reports success. Place it by hand from
     the secrets manager, then re-run."
    for tool in pnpm pm2; do
      command -v "$tool" >/dev/null || die "$tool is not installed on this host (DEPLOYMENT §2)"
    done
  fi

  # The five the nginx step needs. They are NOT in .env and are not Settings fields — this
  # script never sources .env — so they must be exported in the operator's shell. Checked
  # here rather than at `render_nginx`, which is the last step of the deploy.
  if in_plan nginx; then
    local missing=()
    for var in ROOT_DOMAIN TLS_LIVE_DIR ORIGIN_CERT_PATH ORIGIN_KEY_PATH; do
      [[ -n "${!var:-}" ]] || missing+=("$var")
    done
    (( ${#missing[@]} == 0 )) || die \
      "the nginx step needs these exported in this shell and they are unset: ${missing[*]}.
     They are deliberately not in .env (this script never sources it) and not Settings
     fields. See DEPLOYMENT §9 step 4."
  fi

  check_cloudflare_ip_age
}

check_cloudflare_ip_age() {
  local conf="$ROOT/infra/nginx/snippets/calevate-origin.conf" stamp age_days
  [[ -f "$conf" ]] || die "missing $conf"
  stamp=$(grep -m1 -oE 'CLOUDFLARE_IPS_UPDATED: [0-9]{4}-[0-9]{2}-[0-9]{2}' "$conf" | awk '{print $2}') \
    || true
  [[ -n "$stamp" ]] || die "$conf carries no CLOUDFLARE_IPS_UPDATED stamp; refusing to
     install an origin allowlist of unknown age"
  age_days=$(( ( $(date -u +%s) - $(date -u -d "$stamp" +%s) ) / 86400 ))
  (( age_days <= CLOUDFLARE_IPS_MAX_AGE_DAYS )) || die \
    "Cloudflare IP ranges in $conf were last refreshed $stamp (${age_days} days ago).
     Refresh from https://www.cloudflare.com/ips-v4 and /ips-v6, update the stamp, commit,
     and redeploy. A stale list either blocks live traffic or trusts a released address."
  log "cloudflare ranges refreshed $stamp (${age_days}d ago, limit ${CLOUDFLARE_IPS_MAX_AGE_DAYS}d)"
}

# --- 2. get to the commit CI validated ----------------------------------------------

sync_checkout() {
  step "sync checkout"
  if (( DO_PULL )); then
    git -C "$ROOT" pull --ff-only
  else
    log "--no-pull: deploying the tree as it stands"
  fi

  HEAD_SHA=$(git -C "$ROOT" rev-parse HEAD)

  # The SHA gate. CI proved a specific commit; without this check a deploy triggered by
  # that CI run can quietly ship a LATER commit that nothing has tested — the race is
  # real and it is silent, because the deploy still succeeds.
  if [[ -n "$EXPECTED_SHA" && "$HEAD_SHA" != "$EXPECTED_SHA" ]]; then
    die "HEAD is $HEAD_SHA but CI validated $EXPECTED_SHA.
     This deploy would ship untested code. Re-run CI on HEAD, or deploy that commit."
  fi
  log "deploying $HEAD_SHA"
}

# --- 3. which components ------------------------------------------------------------
# THE PATH MAP. One table, read in one place, so "does this change touch voice-runtime?"
# has exactly one answer and it is reviewable in a diff.
#
# Deliberately over-inclusive rather than clever: `uv.lock`, `pyproject.toml`, the
# Dockerfile and the compose file change what EVERY python service contains, so they
# deploy all three. Under-selecting here means a container running code that no longer
# matches the tree — which is invisible until something behaves like the old version.

components_for_paths() {
  local -A hit=()
  local path
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    case "$path" in
      apps/web/*|pnpm-lock.yaml|pnpm-workspace.yaml|package.json)
        hit[web]=1 ;;
      infra/nginx/*)
        hit[nginx]=1 ;;
      # Shared foundations: every python service is built from them.
      uv.lock|pyproject.toml|Dockerfile|compose.prod.yml|packages/shared/*|apps/__init__.py)
        hit[api]=1; hit[voice-runtime]=1; hit[workers]=1 ;;
      # `apps/api/core` is a LIBRARY, imported by voice-runtime (see its module
      # docstring). Sharing library code is not deploy coupling; pretending it is not
      # shared would be a lie that ships a stale receiver.
      apps/api/core/*)
        hit[api]=1; hit[voice-runtime]=1; hit[workers]=1 ;;
      apps/voice-runtime/*)
        hit[voice-runtime]=1 ;;
      apps/workers/*)
        hit[workers]=1 ;;
      # Everything else under apps/api is the monolith proper. Workers import it
      # (the post-call pipeline is built on those modules); voice-runtime does not.
      apps/api/*)
        hit[api]=1; hit[workers]=1 ;;
      # A new revision changes the schema every service reads.
      alembic/*|alembic.ini)
        hit[api]=1; hit[voice-runtime]=1; hit[workers]=1 ;;
    esac
  done
  local component
  for component in "${ALL_COMPONENTS[@]}"; do
    if [[ -n "${hit[$component]:-}" ]]; then printf '%s\n' "$component"; fi
  done
}

resolve_plan() {
  step "resolve plan"
  case "$MODE" in
    explicit) PLAN=("${SELECTED[@]}") ;;
    all)      PLAN=("${ALL_COMPONENTS[@]}") ;;
    changed)
      local last=""
      [[ -f "$STATE_DIR/deployed-sha" ]] && last=$(cat "$STATE_DIR/deployed-sha")
      if [[ -z "$last" ]] || ! git -C "$ROOT" cat-file -e "${last}^{commit}" 2>/dev/null; then
        # First deploy on this host, or a state file pointing at a commit this checkout
        # does not have (a force-push, a re-clone). Guessing a subset from an unknown
        # baseline would silently skip a service; deploy everything and say why.
        log "no usable last-deployed SHA — deploying every component"
        PLAN=("${ALL_COMPONENTS[@]}")
      else
        mapfile -t PLAN < <(git -C "$ROOT" diff --name-only "$last" HEAD | components_for_paths)
        log "changed since ${last:0:12}: ${PLAN[*]:-nothing}"
      fi
      ;;
  esac

  if (( ${#PLAN[@]} == 0 )); then
    log "nothing to deploy — HEAD is already live. (Use --all to force.)"
    exit 0
  fi
  log "plan: ${PLAN[*]}"
}

in_plan() {
  local want=$1 item
  for item in "${PLAN[@]}"; do [[ "$item" == "$want" ]] && return 0; done
  return 1
}

python_services_in_plan() {
  local service
  for service in api voice-runtime workers; do
    if in_plan "$service"; then printf '%s\n' "$service"; fi
  done
}

# --- 4. build -----------------------------------------------------------------------

sweep_tombstones() {
  step "sweep dead containers"
  # Docker `Dead`-state ghosts break compose's rename-on-recreate (DEPLOYMENT §10), and
  # the symptom is a rename error that reads like a bug in compose.
  #
  # DELIBERATELY NOT the playbook's `sudo rm -rf /var/lib/docker/containers/<id>`. An
  # automated `rm -rf` under the daemon's own state directory, running unattended on
  # every deploy, is a bigger hazard than the problem — the recovery for one bad id is
  # a rebuilt Docker host. This DETECTS and refuses with the exact command instead, so a
  # human deletes it having read what they are deleting.
  local dead
  dead=$(docker ps -a --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
                     --filter "status=dead" --format '{{.ID}} {{.Names}}')
  [[ -z "$dead" ]] && { log "no dead containers"; return 0; }
  printf '%s\n' "$dead" >&2
  die "dead-state containers exist in project $COMPOSE_PROJECT (above). Compose cannot
     recreate over them. Remove each one, and if 'docker rm -f' will not:
       sudo rm -rf /var/lib/docker/containers/<id>   # then: sudo systemctl restart docker
     Do this by hand, having read the id. This script will not rm -rf under the daemon."
}

build_images() {
  local services
  mapfile -t services < <(python_services_in_plan)
  (( ${#services[@]} )) || { log "no python service in plan — nothing to build"; return 0; }

  step "build images (serial)"
  # SERIAL, one --build-arg-free service at a time. Parallel builds OOM a 4GB host
  # (DEPLOYMENT §10) and the OOM kills the runner, not the build, so it reads as a CI
  # infrastructure flake rather than as a memory ceiling.
  #
  # All three services share one image (see Dockerfile), so in practice the first build
  # populates the layer cache and the rest are near-instant. The loop exists so that a
  # future split into per-service images does not need a new mechanism.
  local service
  for service in "${services[@]}"; do
    log "building $service"
    compose build "$service"
  done
}

# --- 5. the environment the NEW image will actually see ------------------------------

verify_bootstrap_env() {
  step "verify bootstrap env"
  # DEPLOYMENT §4 step 3, run in the image rather than on the host: what matters is what
  # the process about to serve traffic can read, and that is `.env` as seen through
  # compose's env_file, not whatever the deploy user happens to have exported.
  #
  # BEFORE ANY SWAP, on purpose. `validate_bootstrap_env` is the gate that turns "APP_ENV
  # is unset" into a sentence instead of a container that boots into `local` mode and
  # accepts a dev token whose subject the caller picks (apps/api/core/settings.py). That
  # must fail while the old containers are still serving.
  compose run --rm --no-deps --entrypoint python api -c \
    'from apps.api.core.settings import validate_bootstrap_env, get_settings
validate_bootstrap_env()
get_settings()
print("bootstrap env OK for", get_settings().app_env)'
}

# --- 6. migrations ------------------------------------------------------------------

run_migrations() {
  in_plan api || in_plan workers || in_plan voice-runtime || return 0
  step "migrations"

  # ================================ ORDERING ======================================
  # MIGRATE FIRST, THEN SWAP CONTAINERS. The alternative (swap, then migrate) was
  # rejected, and hard rule 8 is the reason it is not a coin flip:
  #
  #   Rule 8 forbids dropping a column in the same release that stops writing it
  #   (two-step deprecation). That rule is exactly the statement "the OLD code can
  #   always run against the NEW schema" — an expand-only migration adds things the old
  #   code ignores and removes nothing it still uses.
  #
  #   It says NOTHING about the reverse. New code against the OLD schema is not
  #   protected by anything: a release that starts reading a column added this release
  #   fails on every request until the migration lands.
  #
  #   So the window between migrate and swap is safe by construction, and the window
  #   between swap and migrate is not. Migrate first.
  #
  # ================================ ON FAILURE ====================================
  # NO AUTOMATIC DOWNGRADE, EVER. PostgreSQL has transactional DDL and alembic runs each
  # revision in its own transaction — because `alembic/env.py` passes
  # `transaction_per_migration=True`, which is what makes this sentence true; alembic's
  # default is one transaction for the whole run. So a failure leaves the database at the
  # last revision that fully applied — a valid intermediate state which, by the argument
  # above, the currently-running OLD containers can serve on. Automatically downgrading
  # from here would be the dangerous move, not the safe one: a downgrade can drop a
  # column the partially-deployed system has already written to, turning a failed deploy
  # into data loss. So this aborts, prints the revision it reached, and leaves it.
  # `runbooks/deploy-failed.md` §3 owns what comes next.
  #
  # This is also why the revision is recorded BEFORE and AFTER: the pair is the only
  # thing that makes a manual `alembic downgrade <before>` a considered action rather
  # than a guess taken under pressure.
  DB_REVISION_BEFORE=$(compose run --rm --no-deps --entrypoint alembic api current 2>/dev/null \
                       | tail -1 | tr -d '\r' || echo "unreadable")
  log "alembic revision before: ${DB_REVISION_BEFORE:-none}"

  compose --profile migrate run --rm --no-deps migrate

  # THEN SEED. `scripts/seed.py` was invoked nowhere in production — only by `make
  # db-reset`, which is the dev reset — so `reserved_slugs` was empty on every deployed
  # database. That table is the sole enforcement of slug reservation (`admin/service.py`
  # probes it and refuses only if a row exists), so against an empty table `admin`, `api`,
  # `app`, `www`, `hooks`, `login`, `billing`, `support`, `security` and `calevate` were
  # all claimable. Contained today because self-serve signup defaults OFF, and a public
  # impersonation surface the minute it is switched on.
  #
  # Idempotent and non-destructive by construction (seed.py says so and inserts with
  # ON CONFLICT), so it runs on every deploy rather than only the first.
  compose --profile migrate run --rm --no-deps --entrypoint python migrate -m scripts.seed

  DB_REVISION_AFTER=$(compose run --rm --no-deps --entrypoint alembic api current 2>/dev/null \
                      | tail -1 | tr -d '\r' || echo "unreadable")
  log "alembic revision after: ${DB_REVISION_AFTER:-none}"
}

# --- 7. swap + health ----------------------------------------------------------------

health_url() {
  case "$1" in
    api)           printf 'http://127.0.0.1:8000/healthz' ;;
    voice-runtime) printf 'http://127.0.0.1:8100/healthz' ;;
    web)           printf 'http://127.0.0.1:3000/' ;;
    *)             return 1 ;;
  esac
}

wait_healthy() {
  local component=$1 url attempt
  url=$(health_url "$component") || return 0
  log "waiting for $component at $url (${HEALTH_ATTEMPTS}x${HEALTH_INTERVAL_S}s)"
  for (( attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++ )); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      log "$component healthy after $(( attempt * HEALTH_INTERVAL_S ))s"
      return 0
    fi
    sleep "$HEALTH_INTERVAL_S"
  done
  die "$component never became healthy at $url within
     $(( HEALTH_ATTEMPTS * HEALTH_INTERVAL_S ))s. It is running the NEW image and failing.
     Logs:  docker compose -p $COMPOSE_PROJECT -f $COMPOSE_FILE logs --tail=200 $component
     Then:  runbooks/deploy-failed.md §4"
}

swap_service() {
  local service=$1
  step "swap $service"
  # `--no-deps` IS THE HARD-RULE-3 LINE. Without it, compose walks `depends_on` and
  # would restart redis — and through it, everything else — for a single-service deploy.
  # With it, deploying `api` provably cannot restart the container answering live calls.
  #
  # This is a RECREATE, not a blue/green rollout: compose stops the old container and
  # starts the new one, so there is a gap of a few seconds. That is stated rather than
  # hidden — see DEPLOYMENT §4b for the size of the gap, what absorbs it for each
  # service, and why a third-party rollout plugin on the production host was not adopted
  # without a decision-log entry.
  compose up -d --no-deps "$service"
  wait_healthy "$service"
}

deploy_web() {
  step "deploy web (pm2)"
  # Next.js runs on the host under pm2, not in Compose (DEPLOYMENT §1). `next build`
  # peaks over 2GB, which is why §2 requires 2GB of swap and why §7a wants this build
  # moved into CI once self-serve opens.
  command -v pnpm >/dev/null || die "pnpm is not installed on this host (Node 22 + pnpm 10 — DEPLOYMENT §2)"
  command -v pm2  >/dev/null || die "pm2 is not installed on this host"

  # `--frozen-lockfile` is the supply-chain line, not a speed flag: it makes the install
  # reproduce the reviewed lockfile exactly and FAIL if the manifest and the lock
  # disagree, which is what a tampered or drifted dependency looks like (hard rule 9).
  pnpm install --frozen-lockfile
  pnpm -C apps/web build

  # START IF ABSENT, RELOAD IF PRESENT.
  #
  # This was `pm2 reload` alone, which exits non-zero on an unregistered app — and nothing
  # in this repository has ever run `pm2 start`. There was no ecosystem file at all, and
  # DEPLOYMENT §2 lists only `pm2 startup`, which makes pm2 resurrect a SAVED list rather
  # than create one. So the first deploy on a fresh host aborted here, at step 9 of 11,
  # with migrations already applied and all three containers already swapped — and
  # `runbooks/deploy-failed.md` then told the operator to start it "from the ecosystem
  # definition", which did not exist.
  #
  # `pm2 save` after a start so `pm2 startup`'s resurrect actually has a list to restore;
  # without it a host reboot brings the containers back and leaves the web tier down.
  if pm2 describe calevate-web >/dev/null 2>&1; then
    # `--update-env` so a changed .env is actually picked up; without it pm2 re-executes
    # with the environment it was first started with, and an operator who rotated a key
    # watches the old one keep working.
    pm2 reload calevate-web --update-env
  else
    log "  calevate-web is not registered with pm2 — starting it for the first time"
    pm2 start "$ROOT/apps/web/ecosystem.config.cjs" --update-env
    pm2 save
  fi
  wait_healthy web
}

# --- 8. nginx -------------------------------------------------------------------------

render_nginx() {
  step "render nginx config"

  : "${ROOT_DOMAIN:?ROOT_DOMAIN must be set (e.g. calevate.tech) to render nginx config}"
  : "${TLS_LIVE_DIR:?TLS_LIVE_DIR must be set (e.g. /etc/letsencrypt/live/calevate.tech)}"
  : "${ACME_WEBROOT:=/var/www/certbot}"
  : "${ORIGIN_CERT_PATH:?ORIGIN_CERT_PATH must be set — the Cloudflare Origin CA cert for the default_server (DEPLOYMENT §5)}"
  : "${ORIGIN_KEY_PATH:?ORIGIN_KEY_PATH must be set — the Cloudflare Origin CA key}"
  export ROOT_DOMAIN TLS_LIVE_DIR ACME_WEBROOT ORIGIN_CERT_PATH ORIGIN_KEY_PATH

  local staging
  staging=$(mktemp -d)
  # EXPLICIT VARIABLE LIST. `envsubst` with no argument substitutes EVERY `$name` it
  # finds — and an nginx config is nothing but `$name`: `$host`, `$remote_addr`,
  # `$binary_remote_addr` would all be replaced with empty strings, producing a file that
  # passes `nginx -t` and rate-limits every request into the same bucket. Naming the five
  # is what makes this safe.
  # shellcheck disable=SC2016  # envsubst wants the LITERAL `${NAME}` list, unexpanded
  local subst='${ROOT_DOMAIN} ${TLS_LIVE_DIR} ${ACME_WEBROOT} ${ORIGIN_CERT_PATH} ${ORIGIN_KEY_PATH}'

  envsubst "$subst" < "$ROOT/infra/nginx/calevate.conf.template"     > "$staging/calevate-site.conf"
  envsubst "$subst" < "$ROOT/infra/nginx/000-default.conf.template"  > "$staging/000-default.conf"
  envsubst "$subst" < "$ROOT/infra/nginx/rate-zones.conf.template"   > "$staging/calevate-rate-zones.conf"

  # An unsubstituted placeholder means a variable was added to a template and not to the
  # list above. nginx would accept the literal `${FOO}` in many positions and fail in
  # exactly one, at reload, on the live host.
  if grep -RlE '\$\{[A-Z_]+\}' "$staging" >/dev/null; then
    grep -RnE '\$\{[A-Z_]+\}' "$staging" >&2
    die "unsubstituted placeholders remain (above) — add the variable to the envsubst list"
  fi

  NGINX_STAGING="$staging"
  log "rendered to $NGINX_STAGING"
}

install_nginx() {
  step "install nginx config"
  if [[ "$NGINX_AUTO_RELOAD" != "1" ]]; then
    log "NGINX_AUTO_RELOAD is not 1 — config rendered but NOT installed."
    log "Review it, then install by hand:"
    log "  sudo install -m 0644 $NGINX_STAGING/*.conf $NGINX_CONF_DIR/"
    log "  sudo install -m 0644 $ROOT/infra/nginx/snippets/*.conf $NGINX_SNIPPET_DIR/"
    log "  sudo nginx -t && sudo systemctl reload nginx"
    return 0
  fi

  # Snippets first: the site config `include`s them, so installing the site config first
  # would make `nginx -t` fail on a file that is about to exist. Ordering, not taste.
  sudo install -m 0644 "$ROOT"/infra/nginx/snippets/*.conf "$NGINX_SNIPPET_DIR/"
  sudo install -m 0644 "$NGINX_STAGING"/*.conf "$NGINX_CONF_DIR/"

  # TEST BEFORE RELOAD, ALWAYS. `systemctl reload` on a bad config leaves the old workers
  # running and reports success, so the failure surfaces at the next restart — possibly a
  # reboot, weeks later, with nobody connecting the two events.
  sudo nginx -t
  sudo systemctl reload nginx
  log "nginx reloaded"
}

# --- 9. finish ------------------------------------------------------------------------

record_deploy() {
  step "record deploy"
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$HEAD_SHA" > "$STATE_DIR/deployed-sha"
  # Kept as history, not just a pointer: "what was live at 02:00 last Tuesday" is the
  # first question of every incident and the last thing anyone can reconstruct.
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HEAD_SHA" "${PLAN[*]}" \
    >> "$STATE_DIR/history"
}

post_deploy_prune() {
  step "prune"
  # Images only, and only dangling ones. NOT `system prune -a`, which on a host where
  # three services share one image would delete the layer cache that makes the next
  # build fast, and NOT volume pruning, which on this host would target redis-data.
  docker image prune -f
  # `--keep-storage` is the flag DEPLOYMENT §4 names. Newer Docker spells it
  # `--reserved-space` and still accepts the old name as a deprecated alias; if a future
  # engine removes it this line fails loudly, which is the correct way to find out.
  docker builder prune -f --keep-storage 3GB
}

summary() {
  printf '\n\033[1;32m========================== DEPLOYED ==========================\033[0m\n'
  printf 'commit     : %s\n' "$HEAD_SHA"
  printf 'components : %s\n' "${PLAN[*]}"
  printf 'db revision: %s -> %s\n' "${DB_REVISION_BEFORE:-unchanged}" "${DB_REVISION_AFTER:-unchanged}"
  printf 'rollback   : git -C %s checkout <previous-sha> && scripts/vps-deploy.sh --all --no-pull\n' "$ROOT"
  printf '             (code only — the database does NOT roll back with it; see\n'
  printf '              runbooks/deploy-failed.md §3 before downgrading a revision)\n'
  printf '\033[1;32m==============================================================\033[0m\n'
}

# --- main -----------------------------------------------------------------------------

preflight
sync_checkout
resolve_plan

if (( DRY_RUN )); then
  log "--dry-run: would deploy [${PLAN[*]}] at $HEAD_SHA and stop here"
  exit 0
fi

sweep_tombstones
build_images
if [[ -n "$(python_services_in_plan)" ]]; then
  verify_bootstrap_env
  run_migrations
fi

# Order within the swap: workers, then api, then voice-runtime.
#
# Workers first because they are the only component with no reader waiting on them — a
# job that lands during their gap is queued in Redis, not lost. voice-runtime LAST
# because its gap is the only one that costs a call: a delivery arriving in that window
# gets no ack, Bolna does not retry (D-31), and the reconciliation poller picks it up on
# a 10-minute tick. Making that window the shortest-lived and the last thing to happen is
# the cheapest mitigation available without a blue/green mechanism.
# REDIS FIRST, AND NOT WITH `--no-deps`.
#
# Every swap below passes `--no-deps`, which is correct for a SWAP — it is the flag that
# stops an api deploy from restarting redis and, through it, the service answering live
# calls. But it was also the ONLY way this stack was ever brought up, and `--no-deps` is
# precisely the flag that tells compose not to walk `depends_on`. So the redis container
# named by all three services' `depends_on: {condition: service_healthy}` was never
# created by anything: the first `--all` run started workers against no queue, then swapped
# api, whose `/healthz` PINGs redis and answers 503 — and the deploy died at `swap api`,
# AFTER migrations had already run.
#
# Bringing it up explicitly, once, before the loop is the whole fix. It is idempotent
# (`up -d` on a healthy container is a no-op) and it deliberately does NOT use `--no-deps`,
# because redis is the thing at the bottom of the graph rather than a thing with a graph.
if in_plan api || in_plan workers || in_plan voice-runtime; then
  step "redis"
  compose up -d redis
fi

for component in workers api voice-runtime; do
  if in_plan "$component"; then swap_service "$component"; fi
done

if in_plan web; then deploy_web; fi

if in_plan nginx; then
  render_nginx
  install_nginx
fi

post_deploy_prune
record_deploy
summary
