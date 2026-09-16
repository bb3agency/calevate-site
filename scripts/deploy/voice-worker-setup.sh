#!/usr/bin/env bash
# Bring the Pipecat Cloud voice worker up on a host, and repair it on the next host.
#
# WHY THIS EXISTS AS A SCRIPT AND NOT A RUNBOOK SECTION. `docs/DEPLOYMENT.md` §12.5 lists
# seven things a human must do before the first deploy, and every one of them is a command
# somebody retypes from a document — which is the shape of every drift this repository has
# a guard for. The founder's requirement is the real argument: *"if I change to another VPS
# I'll just have to run that script and everything can be setup"*. A runbook cannot be run.
#
# IT IS A REPAIR TOOL, NOT AN INSTALLER. Every subcommand is idempotent and re-runnable,
# `doctor` changes nothing, and a host that is half-configured is the case this is FOR —
# not an error state it refuses. Run `doctor` first on any host, including this one.
#
# ⚠ WHAT IS VERIFIED HERE AND WHAT IS NOT, because the distinction decides how this script
# behaves when it is wrong (hard rules 11 and 12):
#
# * VERIFIED: uv's image digest (`Dockerfile:54`, already trusted by every build this repo
#   has ever done), the worker's environment contract (`voice_worker/boot.py`, indexed by
#   DEPLOYMENT §12.2), the preflight verb (`bot.py --preflight`), and the build invocation
#   (`apps/voice-worker/Dockerfile`).
# * NOT VERIFIED: the Pipecat Cloud CLI's own interface. `docs.pipecat.ai` is egress-blocked
#   from the development container and the `cli` extra is not installed there, so NO flag of
#   `pipecat cloud ...` has ever been read by the author of this file. DEPLOYMENT §12.1
#   records `pipecat cloud secrets set <set> --file <file>` as REPORTED.
#
#   So this script DISCOVERS that interface instead of assuming it: `require_cli_shape`
#   reads the CLI's own `--help` and refuses, printing the real help, when what it finds
#   does not match. A guess that silently sent a secret to the wrong flag is the failure
#   this avoids — it would look like success and leave the key unset.
#
# SECRETS NEVER TOUCH THIS REPOSITORY, THIS SHELL'S HISTORY, OR THIS SCRIPT'S ARGV.
# They are read with `read -rs` (no echo), written to a file created under `umask 077` in a
# private mktemp directory OUTSIDE the checkout, handed to the CLI by PATH, and shredded on
# every exit path including a signal. Hard rule: "store secrets in DB/env-committed files"
# is what that is avoiding; DEPLOYMENT §12.2's own instruction is that a human puts the
# value into the vendor's secret set, which is exactly this.
#
# RUN IT AS THE DEPLOY ACCOUNT. The checkout is `calevate:calevate` and the tooling this
# installs lands in that account's `~/.local/bin`:
#
#     sudo -u calevate bash -lc '/var/www/calevate/scripts/deploy/voice-worker-setup.sh doctor'
#
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

# The disk measurement, taken from the reclaim ladder rather than re-implemented. That file
# is a pure function library — it defines functions and sets defaults, and invokes nothing —
# which is why sourcing it here is safe and why `free_gb_at` has exactly one implementation
# in this tree. It also gives us `reclaim_free_gb`, which takes the SMALLER of the checkout's
# filesystem and Docker's, and that is the number a build actually fills.
# shellcheck source=scripts/deploy/docker-reclaim.sh
source "$SCRIPT_DIR/docker-reclaim.sh"

#: uv, by the digest the root Dockerfile already pins and every build already trusts
#: (`Dockerfile:54`). PINNED BY DIGEST AND EXTRACTED FROM AN IMAGE, rather than
#: `curl https://astral.sh/uv/install.sh | sh`, for hard rule 9's reason: piping a remote
#: script into a shell is the exact supply-chain shape that rule names, and it would also
#: be a SECOND way this repository obtains uv. ghcr.io is reachable from a deploy host by
#: demonstration — it is where every image build already pulls this same layer from.
UV_IMAGE=${UV_IMAGE:-ghcr.io/astral-sh/uv:0.8.17@sha256:e4644cb5bd56fdc2c5ea3ee0525d9d21eed1603bccd6a21f887a938be7e85be1}

#: Where the extracted uv and the CLI's shims go. The invoking account's own bin, so nothing
#: here needs root; a host that wants them system-wide sets this to /usr/local/bin and runs
#: the install step as a user who may write there.
UV_BIN_DIR=${UV_BIN_DIR:-$HOME/.local/bin}

#: The agent and the secret set, read from the deploy manifest rather than retyped, so this
#: script cannot come to disagree with what `pipecat cloud deploy` reads.
PCC_MANIFEST="$REPO_ROOT/apps/voice-worker/pcc-deploy.toml"

#: Free gigabytes required before a build is allowed to start. The worker resolves 76
#: distributions on top of a vendor base image of UNKNOWN size (it has never been pulled
#: from the development container), so this is a floor chosen to fail EARLY and loudly
#: rather than at 80% of a layer, which is how a full disk usually presents.
BUILD_FLOOR_GB=${BUILD_FLOOR_GB:-6}

C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'; C_OFF=$'\033[0m'
[[ -t 1 ]] || { C_OK=""; C_BAD=""; C_WARN=""; C_OFF=""; }

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s  OK  %s %s\n' "$C_OK" "$C_OFF" "$*"; }
bad()  { printf '%s FAIL %s %s\n' "$C_BAD" "$C_OFF" "$*"; }
warn() { printf '%s NOTE %s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()  { bad "$*"; exit 1; }
rule() { printf -- '--------------------------------------------------------------------\n'; }

have() { command -v "$1" >/dev/null 2>&1; }

#: How long any probe of the docker daemon may take before it counts as "not answering".
DOCKER_PROBE_TIMEOUT=${DOCKER_PROBE_TIMEOUT:-10}

# A DAEMON THAT NEVER REPLIES IS NOT ONE THAT REFUSES, and only a clock tells them apart.
# `docker info` against a wedged daemon BLOCKS rather than erroring — measured here, where
# this script's own DISK section hung on it after the daemon was left mid-pull. A diagnostic
# that can hang is worthless on the only kind of host it matters for, so every probe of the
# daemon in this file goes through a timeout.
daemon_answers() {
  timeout "$DOCKER_PROBE_TIMEOUT" docker info >/dev/null 2>&1
}

# `pipecat` ON PATH IS NOT `pipecat cloud` AVAILABLE, and this script learned that on the
# first real host: `install-cli` reported success and `login` then answered *"The `pipecat
# cloud` command requires the optional `pipecatcloud` plugin, which isn't installed."* The
# base `pipecat-ai[cli]` extra does NOT carry it, and every verb this script exists to run
# is a `cloud` verb.
#
# EVIDENCE: the CLI's own message, read on a deploy host on 16 Sep 2026 — which is the first
# VERIFIED thing this repository knows about that CLI's interface. Its second remedy,
# `uv pip install pipecatcloud` alone, is what establishes that `pipecatcloud` is the single
# distribution the `cloud` verb needs. Their first remedy also lists
# `pipecat-ai-context-hub`, which is NOT passed here: hard rule 9 says not to ask for what
# nothing needs. ⚠ It arrives anyway as a transitive dependency (observed in the install on
# the deploy host, `pipecat-ai-context-hub==0.8.0`), so omitting it from `--with` is
# redundant rather than exclusionary — stated because the earlier wording implied the
# package would be absent, and it is not.
#
# Checked by RUNNING the verb rather than by reading the tool's package list: the plugin is
# the vendor's mechanism and what matters is whether the verb answers.
have_pipecat_cloud() {
  have pipecat || return 1
  local out
  out=$(pipecat cloud --help 2>&1) || return 1
  ! grep -qi "requires the optional" <<<"$out"
}

# uv and the CLI land in a directory that is not on a non-login shell's PATH by default, and
# a script that installs a tool the next line cannot find is worse than one that installs
# nothing. Prepended rather than appended so this run uses what this run installed.
export PATH="$UV_BIN_DIR:$PATH"

# --- the manifest, read rather than retyped ----------------------------------------------

manifest_value() {
  local key=$1
  [[ -f "$PCC_MANIFEST" ]] || die "no deploy manifest at $PCC_MANIFEST"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$PCC_MANIFEST" | head -1
}

# --- where a value already lives on this host --------------------------------------------
#
# MOST OF THE WORKER'S CONTRACT IS ALREADY ON THE BOX. DEPLOYMENT §12.2 says a human puts the
# same value in two places — the ops console for the VPS stack, the vendor's secret set for
# this container — and the VPS half is sitting in the deploy checkout's `.env`. Retyping a
# DSN by hand is how a worker ends up talking to the wrong database, or to the OWNER role
# that RLS depends on it not being, so this offers what is already there and lets ENTER take
# it.
#
# ⚠ WHAT CANNOT BE OFFERED, AND WHY THAT IS CORRECT: a credential stored in the ops console
# is sealed with `PLATFORM_KEK` and `ops/secret_service.read_secrets` returns METADATA ONLY
# — version, kek id and `last_four`. There is no read-back of a platform secret anywhere in
# this product, deliberately. So for those the source of truth is the VENDOR'S dashboard, and
# the most this script can do is show the last four of what the platform already holds so an
# operator can confirm the value they are pasting is the same one.
ENV_FILE=${ENV_FILE:-$REPO_ROOT/.env}

# The value for one key from the deploy `.env`, or nothing. `tail -1` because a later
# assignment wins in a dotenv, and the quote stripping is deliberate: a DSN is routinely
# quoted there and the quotes are not part of it.
env_file_value() {
  local key=$1
  [[ -r "$ENV_FILE" ]] || return 1
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
    | tail -1 \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

# A VALUE THAT WORKS ON THIS HOST CAN BE MEANINGLESS IN THE CONTAINER THAT WILL READ IT.
#
# ⚠ THE CASE THIS GUARDED IS GONE, AND THE REASON IT IS GONE IS WORTH KEEPING (D-621).
# `DATABASE_URL` used to be in the contract above, and `host_local_dsn` refused a value
# naming `host.docker.internal`, `localhost` or any RFC1918 address — because this
# deployment runs Postgres ON THE HOST behind the Docker bridge (`compose.prod.yml:36`) and
# the worker is box 1 on Pipecat Cloud, a different network. Found the first time `sources`
# was run on the real host: `psql` could not translate `host.docker.internal`.
#
# That was §12.5 gate 6, and it is CLOSED the only way it could be without putting the
# database on the public internet: the worker no longer touches Postgres. It reads its
# configuration and posts its calls' events over HTTPS to `apps/api`, so what this secret
# set now carries is a base URL and a token. There is nothing left here to refuse — a wrong
# base URL fails loudly at `bot.py --preflight`, which is the check that replaced the DSN
# probe and proves strictly more than it did (it proves the credential too).

# NEVER the value — only enough to recognise it. Four characters is what the ops console
# itself shows (`SecretRecord.last_four`), so the two surfaces agree on how much is safe.
tail4() {
  local v=$1
  (( ${#v} > 4 )) && printf '…%s' "${v: -4}" || printf '…'
}

# --- the environment contract, in ONE list -----------------------------------------------
#
# Derived from DEPLOYMENT §12.2, whose own authority is `voice_worker/boot.py`. Each row is
# NAME|REQUIRED|WHAT IT IS. The prompts below are generated from this, so adding a variable
# to the worker means adding one row here and nothing else.
#
# ⚠ `boot.py` demands AT LEAST ONE of the three LLM keys rather than any particular one,
# which no per-row flag can express — `secrets_cmd` enforces that separately, and the three
# rows are marked `llm`.
readonly ENV_CONTRACT=(
  "VOICE_WORKER_API_BASE_URL|yes|where apps/api is, e.g. https://api.calevate.tech — the worker reads its config and posts its calls' events here (D-621). NOT a database DSN: this container cannot reach Postgres at all"
  "VOICE_WORKER_API_TOKEN|yes|the Bearer token this deployment issued its worker. The SAME value goes in the ops console under voice_worker_api_token; nothing copies one to the other"
  "OBJECT_STORE_ENDPOINT|yes|the R2 endpoint the knowledge pack is fetched from"
  "OBJECT_STORE_BUCKET|yes|the R2 bucket holding knowledge packs"
  "AWS_ACCESS_KEY_ID|yes|R2 credential; botocore resolves it itself"
  "AWS_SECRET_ACCESS_KEY|yes|R2 credential; botocore resolves it itself"
  "SARVAM_API_KEY|yes|STT on every call"
  "PLIVO_AUTH_ID|yes|read by Pipecat to hang the call up; a leg nobody hung up goes on billing"
  "PLIVO_AUTH_TOKEN|yes|read by Pipecat to hang the call up; a leg nobody hung up goes on billing"
  "AZURE_OPENAI_API_KEY|llm|in-call LLM, Azure leg"
  "OPENAI_API_KEY|llm|in-call LLM, OpenAI direct leg"
  "GEMINI_API_KEY|llm|in-call LLM, Google leg"
  "CARTESIA_API_KEY|no|the Studio voice tier only"
  "GNANI_API_KEY|no|the Gnani TTS leg (D-618); no Gnani voice is offerable until a minute is ATTESTED"
)

# --- doctor -------------------------------------------------------------------------------

doctor_cmd() {
  local failures=0

  rule; say "HOST"; rule
  say "  user            $(id -un) (uid $(id -u))"
  say "  home            $HOME"
  say "  checkout        $REPO_ROOT"
  say "  tool dir        $UV_BIN_DIR"

  rule; say "PREREQUISITES"; rule
  local daemon_ok=0
  if have docker; then
    if daemon_answers; then
      daemon_ok=1
      ok "docker  $(docker --version 2>/dev/null | head -1)"
    else
      bad "docker is installed but the daemon did not answer within ${DOCKER_PROBE_TIMEOUT}s:
     not running, not permitted for this account (group 'docker'?), or wedged."
      failures=$((failures + 1))
    fi
  else
    bad "docker is not installed"; failures=$((failures + 1))
  fi

  if have uv; then ok "uv      $(uv --version 2>/dev/null)"
  else bad "uv is not on PATH — run: $0 install-cli"; failures=$((failures + 1)); fi

  if ! have pipecat; then
    bad "pipecat CLI is not on PATH — run: $0 install-cli"; failures=$((failures + 1))
  elif have_pipecat_cloud; then
    ok "pipecat $(pipecat --version 2>/dev/null | head -1) (cloud plugin present)"
  else
    bad "pipecat is installed but the 'cloud' plugin is MISSING — run: $0 install-cli"
    failures=$((failures + 1))
  fi

  rule; say "DISK"; rule
  # SKIPPED, NOT ATTEMPTED, when the daemon is silent: the measurement asks the daemon where
  # it writes (`docker_root`), so on a wedged host this is where a doctor would hang forever
  # — which is exactly the host somebody is running a doctor ON.
  if (( daemon_ok == 0 )); then
    warn "skipped: needs the docker daemon, which did not answer above"
    rule
    bad "$failures check(s) failed — each line above says its remedy"
    return 1
  fi
  local free; free=$(reclaim_free_gb "$REPO_ROOT")
  if (( free >= BUILD_FLOOR_GB )); then
    ok "${free}GB free (floor ${BUILD_FLOOR_GB}GB)"
  else
    bad "${free}GB free, below the ${BUILD_FLOOR_GB}GB build floor"
    warn "reclaim with: $SCRIPT_DIR/docker-reclaim.sh   (tier 1 drops the build cache)"
    failures=$((failures + 1))
  fi

  rule; say "DEPLOY MANIFEST"; rule
  if [[ -f "$PCC_MANIFEST" ]]; then
    ok "agent_name      $(manifest_value agent_name)"
    ok "secret_set      $(manifest_value secret_set)"
  else
    bad "missing $PCC_MANIFEST"; failures=$((failures + 1))
  fi

  rule; say "BASE IMAGE"; rule
  if [[ -n "${PIPECAT_BASE:-}" ]]; then
    ok "PIPECAT_BASE is set: $PIPECAT_BASE"
  else
    warn "PIPECAT_BASE unset — the build would use the vendor's MUTABLE :latest tag, which"
    warn "hard rule 9 does not accept as a build input. Run: $0 digest"
  fi

  rule
  if (( failures == 0 )); then
    ok "host is ready for: $0 login"
  else
    bad "$failures check(s) failed — each line above says its remedy"
    return 1
  fi
}

# --- install-cli ---------------------------------------------------------------------------

install_cli_cmd() {
  have docker || die "docker is required to extract the pinned uv image"
  daemon_answers || die "the docker daemon did not answer within ${DOCKER_PROBE_TIMEOUT}s"

  mkdir -p "$UV_BIN_DIR"

  if have uv; then
    ok "uv already present: $(uv --version)"
  else
    say "pulling the digest-pinned uv image ..."
    docker pull "$UV_IMAGE" >/dev/null
    # `create` without `run`: the image's binaries are copied OUT of a container that is
    # never started, so nothing from it executes on this host. `docker cp` from a created
    # container is the documented way to lift a file out of an image.
    local cid
    cid=$(docker create "$UV_IMAGE")
    # shellcheck disable=SC2064
    trap "docker rm -f '$cid' >/dev/null 2>&1 || true" RETURN
    docker cp "$cid:/uv"  "$UV_BIN_DIR/uv"
    docker cp "$cid:/uvx" "$UV_BIN_DIR/uvx"
    chmod 0755 "$UV_BIN_DIR/uv" "$UV_BIN_DIR/uvx"
    ok "uv installed to $UV_BIN_DIR: $("$UV_BIN_DIR/uv" --version)"
  fi

  if have pipecat && have_pipecat_cloud; then
    ok "pipecat CLI with the cloud plugin already present: $(pipecat --version 2>/dev/null | head -1)"
  else
    if have pipecat; then
      say "pipecat is installed WITHOUT the cloud plugin; reinstalling with it ..."
    else
      say "installing the Pipecat CLI as a uv tool ..."
    fi
    # `--force` because the case this repairs is an EXISTING tool install that lacks the
    # plugin, and `uv tool install` is a no-op on an already-installed tool without it.
    uv tool install "pipecat-ai[cli]" --with pipecatcloud --force
    have pipecat || die "installed, but 'pipecat' is still not on PATH — add $UV_BIN_DIR to PATH"
    have_pipecat_cloud || die "installed, but 'pipecat cloud' still reports a missing plugin.
     Their message names what it wants; send it back rather than guessing another --with."
    ok "pipecat CLI installed: $(pipecat --version 2>/dev/null | head -1)"
  fi

  warn "add this to the account's shell profile so future logins find both:"
  say  "    export PATH=\"$UV_BIN_DIR:\$PATH\""
}

# --- the CLI's own interface, discovered rather than assumed --------------------------------

# Refuse unless the CLI really offers what we are about to use. Prints the vendor's OWN help
# on a mismatch, because at that point their help is the primary source and this file's
# expectation is the thing that is out of date.
require_cli_shape() {
  local -a argv=("$@")
  local needle=${argv[-1]}
  unset 'argv[-1]'
  local help
  if ! help=$("${argv[@]}" --help 2>&1); then
    say "$help"
    die "'${argv[*]} --help' failed — the CLI is not authenticated, or this verb does not exist"
  fi
  if ! grep -q -- "$needle" <<<"$help"; then
    rule; say "$help"; rule
    die "expected '$needle' in the help above and it is not there.
     This script's expectation came from docs/DEPLOYMENT.md §12.1, which records it as
     REPORTED and never verified. THE HELP ABOVE IS THE TRUTH. Send it back and the
     doc and this script both get corrected — do not edit around this check."
  fi
}

# --- login ------------------------------------------------------------------------------

login_cmd() {
  have pipecat || die "pipecat CLI is not installed — run: $0 install-cli"
  warn "this opens a browser login. On a headless host the CLI's behaviour is UNKNOWN to
     this script (nobody here has read its docs); if it prints a URL or a device code,
     complete it from your laptop."
  pipecat cloud auth login
  ok "authenticated"
}

# --- digest -----------------------------------------------------------------------------

digest_cmd() {
  have docker || die "docker is required"
  local repo=${1:-dailyco/pipecat-base} tag=${2:-latest}
  say "resolving $repo:$tag ..."
  docker pull "$repo:$tag" >/dev/null
  local digest
  digest=$(docker inspect --format='{{index .RepoDigests 0}}' "$repo:$tag")
  [[ -n "$digest" ]] || die "could not resolve a digest for $repo:$tag"
  rule
  ok "base image digest resolved"
  say "    $digest"
  rule
  say "Use it for every build on this host:"
  say "    export PIPECAT_BASE='$digest'"
  say
  warn "RECORD IT. docs/DEPLOYMENT.md §12.5 gate 3 is only closed once this digest is
     written down — a digest that lives in one shell is not a pinned build input."
}

# --- secrets ------------------------------------------------------------------------------

secrets_cmd() {
  have pipecat || die "pipecat CLI is not installed — run: $0 install-cli"
  local set_name; set_name=$(manifest_value secret_set)
  [[ -n "$set_name" ]] || die "no secret_set in $PCC_MANIFEST"

  require_cli_shape pipecat cloud secrets set --file

  # OUTSIDE THE CHECKOUT, and mode 0700/0600 from creation rather than chmod'd afterwards:
  # a chmod leaves a window in which the file exists world-readable, and on a shared host
  # that window is the whole vulnerability.
  local workdir; workdir=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/calevate-secrets.XXXXXXXX")
  local envfile="$workdir/worker.env"
  # Shredded on EVERY exit path, signals included. `shred` then `rm -rf` because shred alone
  # leaves the directory, and on a filesystem where shred cannot overwrite in place the rm
  # is what actually removes it.
  # shellcheck disable=SC2064
  trap "shred -u '$envfile' >/dev/null 2>&1 || true; rm -rf '$workdir'" EXIT INT TERM

  rule
  say "SECRET SET: $set_name"
  say "Values are not echoed and are never written inside the repository."
  say "Press ENTER to skip any optional variable, or to keep it unset."
  rule

  local llm_given=0 row name required what value
  : >"$envfile"
  for row in "${ENV_CONTRACT[@]}"; do
    IFS='|' read -r name required what <<<"$row"
    local label="  $name"
    case "$required" in
      yes) label="$label [required]" ;;
      llm) label="$label [one LLM key required overall]" ;;
      no)  label="$label [optional]" ;;
    esac
    say ""
    say "$label"
    say "    $what"
    local prefill=""
    prefill=$(env_file_value "$name" 2>/dev/null || true)
    if [[ -n "$prefill" ]]; then
      say "    found in $ENV_FILE ($(tail4 "$prefill")) — press ENTER to use it"
    fi
    printf '    > '
    IFS= read -rs value || true
    printf '\n'
    if [[ -z "$value" && -n "$prefill" ]]; then
      value=$prefill
      say "    using the value from $ENV_FILE"
    fi
    if [[ -z "$value" ]]; then
      if [[ "$required" == yes ]]; then
        die "$name is required by voice_worker/boot.py and cannot be blank.
     It is not in $ENV_FILE either — run '$0 sources' to see where each value comes from."
      fi
      continue
    fi
    printf '%s=%s\n' "$name" "$value" >>"$envfile"
    [[ "$required" == llm ]] && llm_given=1
  done

  (( llm_given == 1 )) || die "no LLM credential given. boot.py requires at least one of
     AZURE_OPENAI_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY — which one a call needs is
     decided per agent by ModelConfig.llm_provider."

  rule
  say "sending $(wc -l <"$envfile") variable(s) to '$set_name' ..."
  pipecat cloud secrets set "$set_name" --file "$envfile"
  ok "secret set updated"
  warn "the Gnani key alone changes nothing a client can see: no Gnani voice is offerable
     until somebody ATTESTS what a Gnani minute costs (hard rule 7, OPERATIONS §2 gate 56).
     Gnani publishes no price, and a reseller's figure is not Gnani's."
}

# --- sources --------------------------------------------------------------------------------

# WHERE EVERY VALUE COMES FROM, ANSWERED PER VARIABLE INSTEAD OF PER DOCUMENT. The question
# this closes is the one an operator actually has in front of the prompt — "I do not know
# how to find them all" — and the honest answer differs by variable in a way no single
# sentence covers: some are in the deploy `.env`, some are sealed in the ops console and
# CANNOT be read back at all, and some exist only in a vendor's dashboard.
#
# It prints NO value. The last four characters are the most it will show, which is exactly
# what the ops console shows for the same credentials.
sources_cmd() {
  local row name required what found=0 missing=0

  rule; say "WHERE EACH WORKER CREDENTIAL COMES FROM"; rule
  if [[ -r "$ENV_FILE" ]]; then
    say "deploy env file: $ENV_FILE"
  else
    warn "deploy env file NOT READABLE at $ENV_FILE — nothing can be offered from it"
  fi
  say ""

  for row in "${ENV_CONTRACT[@]}"; do
    IFS='|' read -r name required what <<<"$row"
    local v; v=$(env_file_value "$name" 2>/dev/null || true)
    if [[ -n "$v" ]]; then
      ok "$name  — in $ENV_FILE ($(tail4 "$v")); 'secrets' will offer it"
      found=$((found + 1))
    else
      case "$name" in
        VOICE_WORKER_API_TOKEN)
          warn "$name  — A NEW CREDENTIAL YOU CREATE (D-621). It exists nowhere yet.
     Generate a long random string, install it in the ops console as
     'voice_worker_api_token', and put THE SAME VALUE here. Nothing copies it between the
     two — the console is what \`apps/api\` checks the header against, this secret set is
     what the worker presents. Until both hold it, every /v1/worker route answers 401 to
     everybody, which is the deliberate posture of an unconfigured deployment." ;;
        VOICE_WORKER_API_BASE_URL)
          warn "$name  — NOT a secret: the https:// base of THIS deployment's API, the one
     the worker calls instead of opening a database connection (D-621). The origin your
     own console is served from, with no trailing path." ;;
        PLIVO_*)
          warn "$name  — NOT on this host. Plivo dashboard; this secret set is its only home." ;;
        GNANI_API_KEY)
          warn "$name  — NOT on this host. Gnani account; this secret set is its only home." ;;
        SARVAM_API_KEY|CARTESIA_API_KEY|AZURE_OPENAI_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY)
          warn "$name  — sealed in the ops console and NOT readable back (PLATFORM_KEK).
     Source of truth is the vendor's own dashboard. See the last four below to confirm
     you are pasting the same key this platform already uses." ;;
        *)
          warn "$name  — not in $ENV_FILE. DEPLOYMENT §12.2 names its origin." ;;
      esac
      missing=$((missing + 1))
    fi
  done

  rule
  say "$found offered from the env file, $missing to be supplied by hand."
  rule
  say "WHAT THE OPS CONSOLE ALREADY HOLDS (last four only — no secret is readable back):"
  say ""
  # Read through the RUNNING api container rather than reimplementing the query or needing a
  # psql on the host: that process already holds the pool and the role, and this asks it for
  # the same metadata the console renders. Degrades to the SQL when it cannot.
  # THIS HOST'S database, and not the worker's: since D-621 the worker has no DSN at all.
  # It is read here only to show the last four of what the ops console already holds, so an
  # operator can confirm the value they are pasting into the secret set is the same one.
  local dsn; dsn=$(env_file_value DATABASE_URL 2>/dev/null || true)
  if [[ -n "$dsn" ]] && have psql; then
    psql "${dsn/postgresql+psycopg:/postgresql:}" -At -F' ' -c \
      "SELECT DISTINCT ON (key) key, version, last_four FROM platform_secrets ORDER BY key, version DESC" \
      2>/dev/null | sed 's/^/    /' \
      || warn "could not query platform_secrets with the DSN from $ENV_FILE"
  else
    warn "no psql on this host (or no DATABASE_URL), so run this yourself to see them:"
    say  "    SELECT DISTINCT ON (key) key, version, last_four"
    say  "      FROM platform_secrets ORDER BY key, version DESC;"
  fi
  rule
  warn "A CREDENTIAL IS NOT COPIED FROM THE CONSOLE TO THE SECRET SET BY ANY MACHINERY, and
     that is deliberate: PLATFORM_KEK is not in the worker image and must never be, so the
     container cannot open this platform's store. DEPLOYMENT §12.2: a human puts the same
     value in both places, and nothing fetches one from the other."
}

# --- build --------------------------------------------------------------------------------

build_cmd() {
  have docker || die "docker is required"
  local free; free=$(reclaim_free_gb "$REPO_ROOT")
  (( free >= BUILD_FLOOR_GB )) || die "${free}GB free, below the ${BUILD_FLOOR_GB}GB floor.
     Reclaim first: $SCRIPT_DIR/docker-reclaim.sh"

  local -a args=(build -f apps/voice-worker/Dockerfile -t calevate/voice-worker:local)
  if [[ -n "${PIPECAT_BASE:-}" ]]; then
    args+=(--build-arg "PIPECAT_BASE=$PIPECAT_BASE")
    ok "building on pinned base: $PIPECAT_BASE"
  else
    warn "PIPECAT_BASE unset — building on the vendor's MUTABLE :latest tag. Acceptable to
     PROVE the image builds; not acceptable as the image you deploy (hard rule 9). Run
     '$0 digest' and rebuild before deploying."
  fi
  args+=(.)

  # The build context is the REPOSITORY ROOT — see the Dockerfile's own header. Running it
  # from anywhere else silently changes which files the COPY lines can see.
  ( cd "$REPO_ROOT" && docker "${args[@]}" )
  ok "image built: calevate/voice-worker:local"
}

# --- preflight ------------------------------------------------------------------------------

preflight_cmd() {
  have docker || die "docker is required"
  rule
  say "Running the image's own configuration proof (DEPLOYMENT §12.2)."
  warn "with no secret set injected this is EXPECTED to print FAIL and list every missing
     variable at once. What it proves here is the LAYOUT — that bot.py and voice_worker/
     are where the base image's entrypoint will look. An ImportError is the real failure."
  rule
  docker run --rm calevate/voice-worker:local python bot.py --preflight || true
}

# --- deploy ---------------------------------------------------------------------------------

deploy_cmd() {
  have pipecat || die "pipecat CLI is not installed — run: $0 install-cli"
  [[ -n "${PIPECAT_BASE:-}" ]] || die "refusing to deploy an image built on a mutable tag.
     Run '$0 digest', export PIPECAT_BASE, rebuild, then deploy (hard rule 9)."
  ( cd "$REPO_ROOT/apps/voice-worker" && pipecat cloud deploy )
  ok "deploy submitted"
  say "logs:  pipecat cloud agent logs $(manifest_value agent_name)"
}

# --- usage ------------------------------------------------------------------------------------

usage() {
  cat <<EOF
Bring up (or repair) the Pipecat Cloud voice worker.

  doctor        report this host's readiness and change nothing   <-- start here
  install-cli   install digest-pinned uv, then the Pipecat CLI
  login         authenticate the CLI against Pipecat Cloud
  digest        resolve and print the vendor base image's sha256 digest
  sources       say where each credential comes from; prints no value
  secrets       prompt for every worker credential and push the secret set
  build         build the worker image (needs PIPECAT_BASE for a real deploy)
  preflight     run the image's own configuration proof
  deploy        pipecat cloud deploy

Run them in that order on a new host. Every one is idempotent.

Environment:
  PIPECAT_BASE    dailyco/pipecat-base@sha256:...  (from 'digest')
  UV_BIN_DIR      where uv and the CLI shims go     (default \$HOME/.local/bin)
  BUILD_FLOOR_GB  free GB required before a build   (default $BUILD_FLOOR_GB)
EOF
}

main() {
  case "${1:-doctor}" in
    doctor)      shift || true; doctor_cmd "$@" ;;
    install-cli) shift || true; install_cli_cmd "$@" ;;
    login)       shift || true; login_cmd "$@" ;;
    digest)      shift || true; digest_cmd "$@" ;;
    secrets)     shift || true; secrets_cmd "$@" ;;
    sources)     shift || true; sources_cmd "$@" ;;
    build)       shift || true; build_cmd "$@" ;;
    preflight)   shift || true; preflight_cmd "$@" ;;
    deploy)      shift || true; deploy_cmd "$@" ;;
    -h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
