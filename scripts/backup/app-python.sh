#!/usr/bin/env bash
# SOURCED, never executed: the one way a host-side backup script reaches a module in
# this repository.
#
# WHY IT IS ITS OWN FILE. Two callers now need the identical three answers —
# `alert-to-app.sh` (the alert relay, D-49/D-50) and `heartbeat.sh` (the external dead
# man). Each answer is a deployment fact that is easy to get subtly wrong and impossible
# to notice when it IS wrong, because both callers run unattended on the database host:
#
#   1. WHICH INTERPRETER. `apps` is imported from the tree rather than installed into the
#      virtualenv (pyproject: the root is a virtual workspace), and the `postgres` user's
#      PATH has no reason to contain our venv.
#   2. FROM WHERE. Pydantic Settings reads `.env` RELATIVE TO THE WORKING DIRECTORY and a
#      systemd unit's working directory is not the repository, so the cwd decides whether
#      config is found at all.
#   3. FOR HOW LONG. A backup unit must never hang on a side channel.
#
# Copying those thirty lines into the second caller is how the two drift and how one of
# them is silently broken for a month. One implementation, two callers (CLAUDE.md, "one
# way per problem").
#
# NOT `set -e`: every failure here must be REPORTED by the caller, never silently
# inherited by it.

# Resolve from THIS file's location, so a caller needs to know no paths at all.
_app_python_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
_app_python_root=$(cd -- "$_app_python_here/../.." && pwd)

# EX_CONFIG — the same code `host_alert.py` and `host_heartbeat.py` use for "there is
# nowhere to deliver", so a caller reads one vocabulary rather than two.
APP_PYTHON_EX_CONFIG=78

# app_python_exec <timeout_s> <module> [args...]
#
# execs; does not return on success. Every exit path prints a line an operator can act
# on, because the alternative is a unit that "ran" and did nothing.
app_python_exec() {
  local timeout_s=$1
  local module=$2
  shift 2

  local python=${CALEVATE_PYTHON:-$_app_python_root/.venv/bin/python}
  if [[ ! -x "$python" ]]; then
    # Deliberately not falling back to `python3`: a system interpreter without the app's
    # dependencies would fail on an import three seconds later with a traceback nobody
    # reads. Say which file is missing, once, in words.
    echo "app-python: no interpreter at $python (set CALEVATE_PYTHON); $module NOT run" >&2
    exit "$APP_PYTHON_EX_CONFIG"
  fi

  # WHERE THE CONFIG COMES FROM, and why the working directory decides it:
  #   * repo `.env` readable by this user  -> run from the repo root, config as every
  #     other process on this host sees it (the simple deployment);
  #   * `.env` NOT readable (the hardened one: `postgres` must not hold the app's
  #     secrets) -> run from `/`, and the unit supplies
  #     `EnvironmentFile=/etc/calevate/alerts.env` with only the keys `Settings`
  #     requires plus SMTP_*, ALERTS_EMAIL and BACKUP_HEARTBEAT_URL.
  # Both work, and neither needs an argument. PYTHONPATH is what makes `apps` importable
  # from either place.
  export PYTHONPATH="$_app_python_root${PYTHONPATH:+:$PYTHONPATH}"
  if [[ -r "$_app_python_root/.env" ]]; then
    cd "$_app_python_root" || exit "$APP_PYTHON_EX_CONFIG"
  else
    cd / || exit "$APP_PYTHON_EX_CONFIG"
  fi

  # A hard ceiling on the whole thing. Each module already bounds its own waiting; this
  # only catches the case where the interpreter itself wedges. `timeout` is coreutils and
  # is on every host that has the rest of this directory's tools; if it is somehow
  # absent, still run rather than refusing.
  if command -v timeout >/dev/null 2>&1; then
    exec timeout --signal=TERM --kill-after=10s "${timeout_s}s" "$python" -m "$module" "$@"
  fi
  exec "$python" -m "$module" "$@"
}
