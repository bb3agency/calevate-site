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

# Disk is not a constant in this file any more. It is a LADDER, and it lives in
# `scripts/deploy/docker-reclaim.sh` because the daily hygiene job needs the same
# primitives and two copies of "how this host reclaims Docker disk" would drift. Both
# floors (`RECLAIM_PURGE_FLOOR_GB`, `RECLAIM_REFUSE_FLOOR_GB`) are named and argued there.
#
# What used to be here was a single refusal at 3GB with two commands printed for a human,
# which is one side of the deadlock the reference host's own comment describes: a prune
# that only runs after a SUCCESSFUL build never runs on the host that needs it. A floor is
# not a strategy.

# nginx is only reloaded when this is explicitly 1. A deploy that silently rewrites the
# edge config of a live site is not a deploy anyone can review afterwards.
NGINX_AUTO_RELOAD=${NGINX_AUTO_RELOAD:-0}
# These two are the deploy's view of where the config lands: they are what `preflight_plan`
# probes and what the manual install instructions print. They are NOT what the automated
# path writes to — `calevate-nginx-apply` hardcodes both, because a root script that takes
# its destination from the caller is a root script with an argument, and the whole shape of
# `infra/privileged/` is that it has none. Overriding them here changes the probe and the
# printed commands and nothing else; if a host really does put nginx elsewhere, the
# privileged script's constants are the place to say so, once, as root.
NGINX_CONF_DIR=${NGINX_CONF_DIR:-/etc/nginx/conf.d}
NGINX_SNIPPET_DIR=${NGINX_SNIPPET_DIR:-/etc/nginx/snippets}

# The oldest nginx that can LOAD `infra/nginx/`. Not a preference and not a hardening
# floor: the templates use the standalone `http2 on;` directive, which appeared in nginx
# 1.25.1, and an older binary refuses the whole configuration rather than that one line.
# Read by `preflight_plan`; the argument is at the check.
NGINX_MIN_VERSION=${NGINX_MIN_VERSION:-1.25.1}

# Cloudflare publishes its edge ranges and changes them. `calevate-origin.conf` carries
# the date it was last refreshed; past this age the deploy stops, because a stale list
# does not degrade gracefully — it either blocks live traffic or trusts an address
# Cloudflare has released.
CLOUDFLARE_IPS_MAX_AGE_DAYS=${CLOUDFLARE_IPS_MAX_AGE_DAYS:-180}

# ONE IMAGE PER COMMIT, and this is what makes a rollback cheap enough to take.
#
# `compose.prod.yml` names the image `calevate/app:${CALEVATE_IMAGE_TAG:-local}` and
# NOTHING used to set that variable, so every build overwrote one mutable `:local` tag.
# Two consequences, both paid during an incident: a rollback had no artefact to go back to
# and meant a full serial `docker build` on a degraded host, and an api-only build replaced
# the image `voice-runtime` would use at its NEXT recreate — hard rule 3 held at the
# container level and not at the artefact level.
#
# The tag is the commit, so an artefact is identifiable, a rollback lands on a build that
# already exists, and `IMAGE_KEEP` bounds what that costs on disk. 12 hex characters: long
# enough that a collision is not a thing that happens to a repository, short enough to read
# in `docker image ls`.
IMAGE_REPO=${IMAGE_REPO:-calevate/app}
IMAGE_KEEP=${IMAGE_KEEP:-5}

# Where the nginx step hands its rendered files to root. FIXED, and that is the point:
# `infra/privileged/sudoers.d/calevate-deploy` grants exactly one command with an EMPTY
# argument list, so the privileged script cannot be told which files to install — it reads
# this directory and validates everything in it. See `infra/privileged/README.md`.
NGINX_STAGING_ROOT=${NGINX_STAGING_ROOT:-/var/lib/calevate/nginx-staging}
NGINX_APPLY=${NGINX_APPLY:-/usr/local/sbin/calevate-nginx-apply}

readonly ALL_COMPONENTS=(api voice-runtime workers web nginx)

# Set by `run_migrations` when it recognised a rollback and left the schema alone. Declared
# here because `set -u` is on and the summary reads it whether or not migrations ran.
MIGRATIONS_SKIPPED=0

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

# --- shared with the daily hygiene job ------------------------------------------------
# Sourced AFTER `log`/`warn` exist, deliberately: `docker-reclaim.sh` only defines its own
# plain-text fallbacks when the caller has none, so this file's coloured output is what a
# deploy prints and a systemd unit still gets readable lines.
# shellcheck source=scripts/deploy/host-lock.sh
source "$ROOT/scripts/deploy/host-lock.sh"
# shellcheck source=scripts/deploy/docker-reclaim.sh
source "$ROOT/scripts/deploy/docker-reclaim.sh"

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

  check_dev_compose_cannot_collide

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

  # The object store's credentials, checked by NAME and never by value. botocore resolves
  # these itself — nothing in the tree passes them to boto3 — so a `.env` without them
  # produces a platform that boots, passes every fail-fast check, reports 200 on
  # `/healthz`, and then cannot copy a single recording: `NoCredentialsError` at the first
  # `put_object`, three arq retries, DLQ, and a recording that TRAI says we must hold for
  # 90 days and that the vendor's link does not promise to keep. `/healthz/ready` reports
  # them by name too, but that is after the swap; this is before it.
  #
  # `grep`, not a source: this script never sources `.env` (see the mode warning above),
  # and reading a key's PRESENCE never needs its value.
  local credential missing_credentials=()
  for credential in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
    grep -qE "^${credential}=." "$ROOT/.env" || missing_credentials+=("$credential")
  done
  (( ${#missing_credentials[@]} == 0 )) || die \
    "the object store has no credentials in .env: ${missing_credentials[*]}.
     They are not Settings fields — botocore reads these exact names — so nothing
     refuses at boot and the first failure is a recording copy that lands in the DLQ.
     See DEPLOYMENT §6 tier 1. AWS_REGION is optional and defaults to 'auto' (R2)."

  # PLATFORM_KEK, by NAME, for the same reason and by the same means. It is the key that
  # opens the credential store: every console-managed secret is ciphertext until it
  # unwraps them. It is deliberately NOT in `BOOTSTRAP_REQUIRED` (a worker must boot
  # tolerantly), and it is not in `runtime_config_missing_keys` either — so a deployment
  # that never had it boots clean, answers /healthz, answers /healthz/ready `ready`, and
  # fails at the first read of the first vendor credential, which is the first outbound
  # call. Losing it later is worse and is not recoverable by any means: every stored
  # credential becomes permanently undecryptable. Both cases were guarded by prose only.
  #
  # PRESENCE, never the value or its length: `apps/api/core/envelope.py` owns the
  # encoding and the length rule and refuses on a short key at read time, and a second
  # copy of that rule here would be a second thing to keep in step. This check moves the
  # ABSENT case from "the first outbound call in production" to "before anything is
  # deployed", which is all it is for.
  grep -qE "^PLATFORM_KEK=." "$ROOT/.env" || die \
    "PLATFORM_KEK is not set in .env. It unwraps every console-managed credential
     (PLATFORM-CONFIG §3/§4), it is env-only by design — the store cannot hold the key to
     itself — and nothing refuses at boot without it: the deploy would go green and the
     first vendor call would fail. Generate it into the secrets manager, once per
     deployment, and never lose it:
       python -c \"import base64,os; print(base64.b64encode(os.urandom(32)).decode())\""

  git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout"
  if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
    git -C "$ROOT" status --short --untracked-files=no >&2
    die "the checkout has local modifications. A deploy from an edited tree deploys
     something that was never reviewed and never built in CI. Commit it or discard it."
  fi

  # Disk is REPORTED here and DECIDED at `reclaim_disk`, which runs immediately before the
  # build. Two reasons it is that way round. Reclaiming needs to run after the tombstone
  # sweep (a Dead container holds an image) and as close to the build as possible, because
  # anything measured earlier is a number, not a guarantee. And a refusal here would be a
  # refusal that could not RECLAIM — which is exactly the half-answer this repo used to
  # have. `--dry-run` exits before the ladder, so the warning below is the only disk signal
  # a dry run gets, and it is worth having.
  local free_gb
  free_gb=$(reclaim_free_gb "$ROOT")
  log "disk: ${free_gb}GB free (min of $ROOT and the docker root)"
  (( free_gb >= RECLAIM_PURGE_FLOOR_GB )) || warn \
    "that is below the ${RECLAIM_PURGE_FLOOR_GB}GB build floor. The pre-build step will
     escalate through the reclaim ladder before building, and may give up this host's
     rollback images to do it (scripts/deploy/docker-reclaim.sh)."

  check_cloudflare_ip_age
}

# --- 1b. the refusals that need to know the PLAN --------------------------------------
#
# SEPARATE FUNCTION, AND THIS IS WHY. These checks arrived inside `preflight()` guarded by
# `in_plan web` / `in_plan nginx` — and `preflight` runs BEFORE `resolve_plan`, so `PLAN`
# was an unset array. Under `set -u`, bash 4.4+ expands `"${PLAN[@]}"` of an unset array to
# nothing rather than erroring, so `in_plan` answered "no" to every question and every
# check inside those two blocks silently never ran. Not a check that was wrong: a check
# that was NOT THERE, while three documents said it was and the deploy printed nothing
# either way. The class of defect is the one CLAUDE.md calls half-wired, and the only
# reason it was survivable is that nobody has run this script.
#
# Called from `main` immediately after `resolve_plan` and BEFORE `--dry-run` exits, so
# `scripts/vps-deploy.sh --dry-run --all` — the first command DEPLOYMENT §9 step 4 tells an
# operator to run — reports a missing browser env file or an unexported ROOT_DOMAIN
# instead of printing a plan that cannot execute. Nothing between it and `preflight` mutates
# anything: only `git pull --ff-only` runs in between.

preflight_plan() {
  step "preflight (plan-scoped)"

  # Every one of these was previously discovered at the step that needed it — i.e. AFTER
  # migrations had run and all three containers had been swapped — so a missing tool or a
  # missing file aborted a deploy that had already half-happened. A precondition found
  # late is a precondition that costs a rollback.

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
     browser configuration, and the deploy still reports success. Place it by hand from
     the secrets manager, then re-run."
    # The ONLY copy of this check. `deploy_web` used to repeat it, which is two ways of
    # asking one question and is a defect here even though both worked: the copy at step
    # 10 is the one that fires after migrations have run.
    local tool
    for tool in pnpm pm2; do
      command -v "$tool" >/dev/null || die "$tool is not installed on this host (DEPLOYMENT §2)"
    done
  fi

  # The five the nginx step needs. They are NOT in .env and are not Settings fields — this
  # script never sources .env — so they must be exported in the operator's shell. Checked
  # here rather than at `render_nginx`, which is the last step of the deploy. ACME_WEBROOT
  # is the fifth and is not listed: it has a real default in `render_nginx`, and demanding
  # an export for a value that defaults correctly trains people to export noise.
  if in_plan nginx; then
    local missing=() var
    for var in ROOT_DOMAIN TLS_LIVE_DIR ORIGIN_CERT_PATH ORIGIN_KEY_PATH; do
      [[ -n "${!var:-}" ]] || missing+=("$var")
    done
    (( ${#missing[@]} == 0 )) || die \
      "the nginx step needs these exported in this shell and they are unset: ${missing[*]}.
     They are deliberately not in .env (this script never sources it) and not Settings
     fields. See DEPLOYMENT §9 step 4."

    # THE VERSION, and it is a REFUSAL because the config does not degrade (D-188).
    # `infra/nginx/calevate.conf.template` uses the standalone `http2 on;` directive in all
    # four TLS server blocks. That directive APPEARED IN nginx 1.25.1, replacing the
    # `listen ... http2` parameter deprecated in the same release
    # (https://nginx.org/en/docs/http/ngx_http_v2_module.html#http2 — read Aug 2026). An
    # older nginx does not warn and does not ignore it: `nginx -t` answers
    # `unknown directive "http2"` and the ENTIRE edge fails to load — measured on
    # nginx/1.24.0, and the same file is `test is successful` on 1.27.
    #
    # This matters because DEPLOYMENT §2 said "nginx >= 1.24" and §1 says Ubuntu 22.04:
    # 22.04 ships 1.18 and 24.04 ships 1.24, so BOTH documented baselines were versions
    # this config cannot load. §2 now says 1.25.1 and this is the check that means it.
    #
    # Checked whenever nginx is installed, not only under NGINX_AUTO_RELOAD: an operator
    # following the printed install commands by hand hits the identical wall, and the
    # useful moment to learn it is before the deploy rather than at `sudo nginx -t`.
    if command -v nginx >/dev/null; then
      # `nginx -v` writes to stderr, always, on every version.
      local nginx_version
      nginx_version=$(nginx -v 2>&1 | sed -n 's|^nginx version: nginx/\([0-9.]*\).*|\1|p')
      # `sort -V` rather than arithmetic on three fields: it is the tool for this and it
      # gets 1.10 vs 1.9 right, which hand-rolled comparisons famously do not.
      if [[ -z "$nginx_version" ]]; then
        warn "could not parse 'nginx -v' output; skipping the >= $NGINX_MIN_VERSION check.
     Confirm by hand that this nginx knows the 'http2' directive (1.25.1+)."
      elif [[ "$(printf '%s\n%s\n' "$NGINX_MIN_VERSION" "$nginx_version" | sort -V | head -1)" \
              != "$NGINX_MIN_VERSION" ]]; then
        die "nginx is $nginx_version and this config needs >= $NGINX_MIN_VERSION.
     infra/nginx/calevate.conf.template uses the standalone 'http2 on;' directive, which
     appeared in nginx 1.25.1. On $nginx_version 'nginx -t' fails with
     'unknown directive \"http2\"' and NO server block loads — the whole edge, not one
     vhost. Ubuntu 22.04 ships 1.18 and 24.04 ships 1.24, so a stock VPS needs the
     nginx.org mainline/stable repository. Do not 'fix' this by reverting the template to
     'listen 443 ssl http2' — that spelling is deprecated and warns on every reload."
      fi
    fi

    # Only when the script is going to touch /etc/nginx. Unset, it renders and prints the
    # install commands, and none of this is needed.
    if [[ "$NGINX_AUTO_RELOAD" == "1" ]]; then
      command -v nginx >/dev/null || die "NGINX_AUTO_RELOAD=1 but nginx is not installed
     on this host (DEPLOYMENT §2 baseline)."
      for var in NGINX_CONF_DIR NGINX_SNIPPET_DIR; do
        [[ -d "${!var}" ]] || die "$var is ${!var}, which is not a directory. nginx is
     either not installed the way DEPLOYMENT §5 expects or these overrides point at
     nothing; either way the install step would create files nginx never reads."
      done
      # THE EXACT COMMAND, not `sudo -n true`. The policy in
      # `infra/privileged/sudoers.d/calevate-deploy` grants ONE command and nothing else, so
      # `sudo -n true` is refused on a correctly configured host — it would have failed the
      # deploy for having the right policy. `sudo -n -l <path>` asks the question actually
      # worth asking ("may this account run THAT, without a prompt?") and exits non-zero
      # when the answer is no.
      #
      # `-n` matters for the same reason it always did: the install step is unattended under
      # CD, and a sudo that PROMPTS there does not fail — it blocks, holding the deploy open
      # until the job times out 45 minutes later, with the container swap already done and
      # the edge config not.
      [[ -x "$NGINX_APPLY" ]] || die "NGINX_AUTO_RELOAD=1 but $NGINX_APPLY is not
     installed. It is the root-owned, argument-free script that installs and tests the edge
     config; install it per infra/privileged/README.md §2 before enabling auto-reload."
      sudo -n -l "$NGINX_APPLY" >/dev/null 2>&1 || die "this account may not run
     $NGINX_APPLY without a password prompt. Install infra/privileged/sudoers.d/calevate-deploy
     and check it with 'sudo -l -U <deploy-user>' — sudo silently IGNORES any file in
     /etc/sudoers.d whose name contains a dot, so a policy installed under the wrong name
     is not a policy. Under CD a prompting sudo does not fail, it hangs until the job times
     out — with the containers already swapped."

      # The fixed handover directory. Checked here rather than at the nginx step, which is
      # the LAST thing a deploy does: a missing staging directory discovered there costs a
      # deploy that has already migrated the database and swapped all three containers.
      local staged
      for staged in "$NGINX_STAGING_ROOT/conf.d" "$NGINX_STAGING_ROOT/snippets"; do
        [[ -d "$staged" && -w "$staged" ]] || die "$staged is missing or not writable by
     this account. It is where the deploy hands rendered config to root; the privileged
     script reads that path and nothing else, because the sudoers grant permits no
     arguments. Create it per infra/privileged/README.md §2."
      done
    fi
  fi

  # --- host capacity, for the two components that have a hard requirement ------------
  #
  # Both are stated as rules in DEPLOYMENT §2/§2a and neither was ever checked, so the
  # first symptom of each is a deploy that has already half-happened.

  # `next build` peaks over 2GB. §2 requires 2GB of swap for exactly this, and the OOM
  # killer takes the build with no error message — `deploy-failed.md` §5 lists it as the
  # first cause of "the build just stopped". Read from /proc rather than `free`, whose
  # output format is localised.
  if in_plan web; then
    local swap_kb=0
    if [[ -r /proc/meminfo ]]; then
      swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
    fi
    (( swap_kb >= 1000000 )) || warn "swap is $(( swap_kb / 1024 ))MB; DEPLOYMENT §2 wants
     2GB for the web build. \`next build\` peaks over 2GB and an OOM kill leaves no error,
     only a build that stopped. This is a warning rather than a refusal because a bigger
     box legitimately needs no swap — check free RAM before ignoring it."
  fi

  # §2a is unambiguous: "NEVER more workers than vCPU — each one saturates a core, so
  # oversubscribing trades throughput for context switching." The default is 4, sized for
  # the production box; on a smaller host it silently costs ack latency, which is the one
  # budget hard rule 3 spends. A refusal, not a warning: the honest fix is fewer workers
  # and a lower supported concurrency, and it is one environment variable.
  if in_plan voice-runtime; then
    local vcpu workers
    vcpu=$(nproc)
    workers=${VOICE_RUNTIME_WORKERS:-4}
    (( workers <= vcpu )) || die \
      "VOICE_RUNTIME_WORKERS is $workers on a ${vcpu}-vCPU host. DEPLOYMENT §2a: never more
     workers than vCPU — each saturates a core, and oversubscription is paid out of the
     500ms ack budget on the service carrying live calls. Set VOICE_RUNTIME_WORKERS=$vcpu
     (and read §2a's table: fewer workers means a lower supported concurrency, which is the
     honest answer on this box)."
  fi
}

# The deploy root is a checkout of this repository, so `docker-compose.yml` — the DEV
# infra file — is always sitting next to `compose.prod.yml`, and `docker compose` with no
# `-f` picks the dev one. What made that dangerous was not its presence, it was its
# ABSENT project name: compose falls back to the directory basename, `/var/www/calevate`
# is `calevate`, and `compose.prod.yml` declares `name: calevate`. One project, two files,
# both defining a service called `redis` — so a bare `docker compose up -d` recreated
# PRODUCTION redis from the dev definition (no `--appendonly yes`, no `redis-data`
# volume: the ARQ queue and the webhook dedupe keys, gone), published Postgres and MinIO
# on 0.0.0.0 behind ufw rules that do not filter Docker's nat/FORWARD entries, and
# `docker compose down -v` took the production volumes with it.
#
# So this refuses a MISSING OR COLLIDING project name rather than the file itself —
# refusing the file would refuse every deploy, since it is committed and always there.
check_dev_compose_cannot_collide() {
  local dev="$ROOT/docker-compose.yml" declared
  [[ -f "$dev" ]] || return 0

  # Top-level `name:` only — column 0, so a `name:` nested under a service cannot answer
  # for the project. `if grep` rather than `grep || true`: no-match is an expected answer
  # here, and the header of this file promises no `|| true` anywhere in it.
  declared=""
  if declared=$(grep -m1 -E '^name:[[:space:]]*[^[:space:]]' "$dev"); then
    declared=${declared#name:}
    declared=${declared//[[:space:]]/}
  fi

  [[ -n "$declared" ]] || die \
    "$dev declares no top-level 'name:', so compose would default its project to this
     directory's basename ($(basename "$ROOT")). If that equals the production project
     ($COMPOSE_PROJECT), a bare 'docker compose up -d' here recreates production redis
     from the DEV definition — no appendonly, no redis-data volume — and 'down -v'
     deletes the production volumes. Add 'name: calevate-dev' to it."

  [[ "$declared" != "$COMPOSE_PROJECT" ]] || die \
    "$dev declares 'name: $declared', which is the production compose project. Two files
     addressing one project both define a 'redis' service; the dev one has no persistence.
     Give the dev file its own project name."
}

check_cloudflare_ip_age() {
  local conf="$ROOT/infra/nginx/snippets/calevate-origin.conf" stamp age_days
  [[ -f "$conf" ]] || die "missing $conf"
  # `if grep`, not `grep || true`. The header of this file says there is no `|| true` in
  # it and none should be added; there was one, here, and it made that sentence false in
  # the one place a reader checks it. A no-match is an expected answer, and `if` is how
  # bash asks for one without turning off the setting that makes every OTHER failure loud.
  stamp=""
  if stamp=$(grep -m1 -oE 'CLOUDFLARE_IPS_UPDATED: [0-9]{4}-[0-9]{2}-[0-9]{2}' "$conf"); then
    stamp=${stamp##* }
  fi
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

  # EXPORTED, because compose reads it from the environment for every `build`, `run` and
  # `up` in this script. Set here rather than at the build step so that the migrate `run`,
  # the bootstrap-env `run` and each swap all resolve the SAME artefact as the build did —
  # a deploy where those disagree is one nobody can reason about afterwards.
  export CALEVATE_IMAGE_TAG="${HEAD_SHA:0:12}"
  IMAGE_REF="$IMAGE_REPO:$CALEVATE_IMAGE_TAG"

  log "deploying $HEAD_SHA as $IMAGE_REF"
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

  # THE ARTEFACT FOR THIS COMMIT MAY ALREADY EXIST, and on the rollback path it usually
  # does. The checkout is verified clean in `preflight`, so the commit fully determines
  # what a build would produce; rebuilding it would burn a serial `docker build` on a host
  # that is, in the case this matters, already degraded. To force one, delete the tag:
  #   docker image rm $IMAGE_REF
  if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
    step "build images"
    log "$IMAGE_REF already exists — reusing it (this is what makes a rollback fast)"
    return 0
  fi

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
  # DEPLOYMENT §4 step 7, run in the image rather than on the host: what matters is what
  # the process about to serve traffic can read, and that is `.env` as seen through
  # compose's env_file, not whatever the deploy user happens to have exported.
  #
  # BEFORE ANY SWAP, on purpose. `validate_bootstrap_env` is the gate that turns "APP_ENV
  # is unset" into a sentence instead of a container that boots into `local` mode and
  # accepts a dev token whose subject the caller picks (apps/api/core/settings.py). That
  # must fail while the old containers are still serving.
  # AND THE VALUES BEHIND THOSE KEYS (D-168). `check_deploy_env` IS the gate above —
  # it calls `validate_bootstrap_env` and constructs `Settings()`, so this step is still
  # exactly what DEPLOYMENT §4 step 6 describes — plus the questions nothing anywhere
  # asked: do the two DSNs name the same database through different roles, does `REDIS_URL`
  # name a host this container can reach, is a value still the placeholder `.env.example`
  # ships. Each of those produces a deploy that swaps cleanly and fails AFTERWARDS, which
  # is the one class this step exists to move earlier. Every problem at once, no value
  # printed, non-zero exit ends the deploy here.
  #
  # It replaced an inline `python -c` that ran the same two calls: two implementations of
  # one step, and two `compose run`s. The host-side `preflight` above keeps its `grep`s for
  # the same keys' PRESENCE — that is the cheap refusal saving a ten-minute serial build,
  # and it is the only question answerable there, since DEPLOYMENT §2 says Python is not
  # installed on the host. One question split by WHEN it can be answered, not two
  # implementations of one check.
  compose run --rm --no-deps --entrypoint python api -m scripts.check_deploy_env
}

# --- 6. migrations ------------------------------------------------------------------

# Is the database at a revision this image has never heard of?
#
# THE ROLLBACK CASE, and the only one this answers. `runbooks/deploy-failed.md` §4 and the
# summary banner both tell an operator to roll back with `git checkout <previous-sha>` and
# `--all --no-pull`. `--all` puts the python services in the plan, so `run_migrations`
# would run `alembic upgrade head` FROM THE OLDER IMAGE — and if the deploy being rolled
# back carried a migration, alembic resolves the stored `alembic_version` against its own
# script directory first and dies with `Can't locate revision identified by '<rev>'`
# (verified against the installed alembic; exit 255). The rollback aborted before swapping
# a single container, in exactly the incident it exists for.
#
# The right behaviour is the one the docs already promise for the other direction: **code
# rolls back, the schema does not.** Rule 8 makes that safe — the older release can serve
# on the newer schema, because a migration may not remove anything the previous release
# still uses. So the upgrade is not merely impossible here, it is unwanted, and the fix is
# to recognise it rather than to attempt it.
#
# THE SEED IS SKIPPED WITH IT. It is idempotent and rule 8 says the older seed can run
# against the newer schema — but the newer release has already seeded everything the older
# one knows about, so the upside is nil, and a rollback is the worst moment to discover an
# edge of rule 8. Nothing is skipped silently: both are named in the banner below and in
# `.deploy-state/history`.
#
# `scripts/deploy_revision_check` answers with an EXIT CODE, in the image, so that "the
# database is ahead" and "the check broke" cannot be confused. Only a clean `3` skips;
# anything else migrates, or dies trying, which is the safe direction.
rolling_back_onto_a_newer_database() {
  local revision=${DB_REVISION_BEFORE%% *}   # `alembic current` prints "<rev> (head)"
  # An empty version table is a first deploy and an unreadable one is a database problem;
  # neither is a rollback, and both belong to the migrate step that follows.
  [[ -n "$revision" && "$revision" != "unreadable" ]] || return 1

  local verdict=0
  compose run --rm --no-deps --entrypoint python api \
    -m scripts.deploy_revision_check "$revision" || verdict=$?

  case "$verdict" in
    0) return 1 ;;   # this image knows the revision — an ordinary forward deploy
    3) ;;            # it does not: the database is ahead of this artefact
    *) die "could not decide whether the database is ahead of this image (checker exit
     $verdict, database at '$revision'). Refusing to guess: guessing 'ahead' would skip a
     migration this release needs and swap new code onto an old schema. Fix the checker or
     run the migration by hand — runbooks/deploy-failed.md §3." ;;
  esac

  printf '\n\033[1;33m===================== MIGRATIONS SKIPPED =====================\033[0m\n' >&2
  printf 'The database is at revision %s, which this commit does not contain.\n' "$revision" >&2
  printf 'That means this deploy is a ROLLBACK: the code is going backwards and the\n' >&2
  printf 'schema is staying where it is. "alembic upgrade head" from here cannot work\n' >&2
  printf "(alembic cannot resolve a revision it has no script for) and is not wanted —\n" >&2
  printf 'hard rule 8 is what makes the previous release able to serve on this schema.\n' >&2
  printf 'The seed is skipped with it. Containers WILL be swapped.\n' >&2
  printf 'If you meant to move the schema back, that is a considered manual downgrade:\n' >&2
  printf 'runbooks/deploy-failed.md §3.\n' >&2
  printf '\033[1;33m==============================================================\033[0m\n' >&2
  return 0
}

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

  if rolling_back_onto_a_newer_database; then
    MIGRATIONS_SKIPPED=1
    return 0
  fi

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
  #
  # `pnpm` and `pm2` are NOT checked here any more — `preflight_plan` owns that, before
  # anything has been built, migrated or swapped. Two copies of one refusal is a defect
  # even while both work: the survivor is always the one that fires late.

  # `--frozen-lockfile` is the supply-chain line, not a speed flag: it makes the install
  # reproduce the reviewed lockfile exactly and FAIL if the manifest and the lock
  # disagree, which is what a tampered or drifted dependency looks like (hard rule 9).
  pnpm install --frozen-lockfile
  # STATED, never inferred. `apps/web/next.config.ts` refuses to build when this is set
  # and the browser tier's three build-time values are empty — which is the only moment
  # anyone can catch it, because `next build` inlines `NEXT_PUBLIC_*` and an absent key
  # compiles to "" rather than throwing. It is a flag rather than an unconditional check
  # because CI builds this package as a COMPILE check with no environment at all, and
  # that is a legitimate build; see the config's comment for the full argument.
  CALEVATE_DEPLOY_BUILD=1 pnpm -C apps/web build

  # START IF ABSENT, RELOAD IF PRESENT.
  #
  # This was `pm2 reload` alone, which exits non-zero on an unregistered app — and nothing
  # in this repository has ever run `pm2 start`. There was no ecosystem file at all, and
  # DEPLOYMENT §2 lists only `pm2 startup`, which makes pm2 resurrect a SAVED list rather
  # than create one. So the first deploy on a fresh host aborted here, at the web step,
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

  # ===================== WHY THIS STEP DOES ALMOST NOTHING NOW =======================
  #
  # It used to run six privileged commands of its own construction: `sudo cp -p` per file
  # for the backup, two `sudo install` globs, `sudo nginx -t`, `sudo rm -f` per introduced
  # file on the restore path, and `sudo systemctl reload`. Every one of those needs a
  # sudoers grant, and a grant for `sudo install <anything> /etc/nginx/...` is a grant with
  # a wildcard in an argument position — which sudo matches as one concatenated string, so
  # the wildcard spans `/` and words and the grant is not scoped to /etc/nginx at all. That
  # is precisely the escalation `docs/evidence/raghava-deploy-teardown.md` §8.3 found on the
  # reference host, and copying its shape while criticising it would have been the worst
  # available outcome.
  #
  # So the privileged half moved WHOLE into a root-owned, argument-free script
  # (`infra/privileged/sbin/calevate-nginx-apply`), including the backup-and-restore dance
  # that used to live here — the reasoning for that dance is now in that file's header,
  # where the code it explains actually is. What is left for this account is: put the files
  # somewhere agreed, then name the action.
  #
  # THE HANDOVER IS A DIRECTORY, NOT AN ARGUMENT LIST, and that is the whole trick. The
  # deploy cannot tell root WHICH files to install, so root does not have to trust a path
  # it was handed; it reads one fixed location and validates every name in it.

  local staged_conf="$NGINX_STAGING_ROOT/conf.d" staged_snippets="$NGINX_STAGING_ROOT/snippets"

  # Emptied first. The staging directories persist between deploys, and a file that a
  # previous deploy rendered and this one does not would otherwise be installed forever —
  # a config nothing in the repository produces any more, silently surviving the change
  # that removed it. `find -delete` on regular files at depth 1 only: never `rm -rf` on the
  # directory itself, which would take the ownership and mode that root checks.
  find "$staged_conf" "$staged_snippets" -maxdepth 1 -type f -delete

  cp "$NGINX_STAGING"/*.conf "$staged_conf/"
  cp "$ROOT"/infra/nginx/snippets/*.conf "$staged_snippets/"
  log "staged $(find "$staged_conf" "$staged_snippets" -maxdepth 1 -type f | wc -l) file(s) in $NGINX_STAGING_ROOT"

  # No arguments, by policy and by the script's own first refusal. A failure here reaches
  # the ERR trap with the script's own message already printed — it restores the previous
  # config before it exits, so a red banner at this step means the edge is unchanged.
  sudo -n "$NGINX_APPLY"
}

# --- 9. finish ------------------------------------------------------------------------

record_deploy() {
  step "record deploy"
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$HEAD_SHA" > "$STATE_DIR/deployed-sha"
  # Kept as history, not just a pointer: "what was live at 02:00 last Tuesday" is the
  # first question of every incident and the last thing anyone can reconstruct. The image
  # ref is on the line because it is the thing you can actually `docker run`, and the
  # migration verdict is on it because "did that deploy move the schema?" is the second
  # question and it now has three answers, not two.
  local migrations=none
  if (( MIGRATIONS_SKIPPED )); then
    migrations=skipped-rollback
  elif [[ -n "${DB_REVISION_AFTER:-}" ]]; then
    migrations=applied
  fi
  printf '%s %s image=%s migrations=%s %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HEAD_SHA" "${IMAGE_REF:-unknown}" "$migrations" "${PLAN[*]}" \
    >> "$STATE_DIR/history"
}

post_deploy_prune() {
  step "prune"
  # Tier 0 of the shared ladder, plus the per-commit tag cap. Both live in
  # `scripts/deploy/docker-reclaim.sh` because the daily hygiene job runs exactly these two
  # and a second copy of either is a second thing to keep in step — including the
  # `--keep-storage` / `--reserved-space` question, which that file answers by asking the
  # binary rather than by pinning a flag that is wrong on some engine either way.
  #
  # Tiers 1-3 are deliberately NOT reached here. The deploy has already succeeded; there is
  # nothing to make room for, and tier 2 would throw away the rollback artefact this deploy
  # just created.
  reclaim_routine "$COMPOSE_PROJECT"
  reclaim_app_image_tags "$IMAGE_REPO" "$IMAGE_KEEP"
}

summary() {
  printf '\n\033[1;32m========================== DEPLOYED ==========================\033[0m\n'
  printf 'commit     : %s\n' "$HEAD_SHA"
  printf 'image      : %s\n' "${IMAGE_REF:-unknown}"
  printf 'components : %s\n' "${PLAN[*]}"
  if (( MIGRATIONS_SKIPPED )); then
    printf 'db revision: %s (UNCHANGED — rollback detected, see the banner above)\n' \
      "${DB_REVISION_BEFORE:-unknown}"
  else
    printf 'db revision: %s -> %s\n' "${DB_REVISION_BEFORE:-unchanged}" "${DB_REVISION_AFTER:-unchanged}"
  fi
  printf 'rollback   : git -C %s checkout <previous-sha> && scripts/vps-deploy.sh --all --no-pull\n' "$ROOT"
  printf '             (code only — the database does NOT roll back with it, and the\n'
  printf '              deploy will SAY SO and skip the migration rather than failing on\n'
  printf '              a revision the older image has no script for. It reuses that\n'
  printf '              commit'"'"'s image if it is still on the host, so it is a swap and\n'
  printf '              not a rebuild. See runbooks/deploy-failed.md §4.)\n'
  printf '\033[1;32m==============================================================\033[0m\n'
}

# --- 3b. pre-build disk reclaim ---------------------------------------------------------

reclaim_disk() {
  step "reclaim disk"
  # The ladder is in `scripts/deploy/docker-reclaim.sh`, which argues both floors and what
  # each rung costs. Here is only the placement and the refusal.
  #
  # WHY HERE. After `sweep_tombstones`, because a Dead container holds an image and
  # reclaiming before the sweep would leave that image unreclaimable. Before `build_images`,
  # because that is the step disk kills — and because the reference host's own comment
  # (quoted in the library) records the deadlock of only reclaiming AFTER a successful
  # build: on a near-full host the build dies, the post-build prune never runs, and every
  # later deploy is wedged.
  #
  # UNCONDITIONAL, even when no image will be built. `next build` needs the same disk and
  # peaks over 2GB (DEPLOYMENT §2), and tier 0 is free.
  reclaim_for_build "$COMPOSE_PROJECT" "$IMAGE_REPO" "$ROOT" || die \
    "not enough free disk to build, after pruning, purging the build cache, dropping every
     per-commit image but the newest, and removing every unreferenced image. Docker has
     nothing left to give back on this host, so this is not a Docker problem any more.
     Find it — 'du -xhd1 / | sort -rh' — and re-run. Nothing has been built, migrated or
     swapped: the deploy stops here precisely so it is not discovered halfway through a
     layer extraction."
}

# --- main -----------------------------------------------------------------------------

# ONE LOCK ON THIS HOST, taken before anything is read, and held until this process exits
# however it exits (`scripts/deploy/host-lock.sh` argues flock over a pid file). The other
# holder is the daily hygiene timer, which prunes images and the build cache host-globally
# — a prune racing a `docker build` can remove the layer the build is about to reference,
# and the build then fails with a message about a missing parent layer that names neither
# the prune nor the timer. `docs/evidence/raghava-deploy-teardown.md` §8.6 is the reference
# host's version of this defect, discovered in production.
#
# The concurrency group in `.github/workflows/deploy.yml` already serialises DEPLOYS; this
# also covers a hand-run deploy during a CD run, and it is the only thing that covers the
# timer.
if ! take_host_lock vps-deploy; then
  die "another deploy or the daily hygiene job has held $CALEVATE_HOST_LOCK for
     ${CALEVATE_LOCK_WAIT_S}s. 'fuser -v $CALEVATE_HOST_LOCK' names the process. If it is a
     dead deploy the lock is already gone — flock releases on exit, so a stale lock file is
     never the problem."
fi

preflight
sync_checkout
resolve_plan
preflight_plan

if (( DRY_RUN )); then
  log "--dry-run: would deploy [${PLAN[*]}] at $HEAD_SHA and stop here"
  exit 0
fi

sweep_tombstones
reclaim_disk
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
