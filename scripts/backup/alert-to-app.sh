#!/usr/bin/env bash
# The default `BACKUP_ALERT_COMMAND`: hand one host alert to the application's alert path.
#
# It reads the JSON line `notify.sh` built on stdin and execs `python -m scripts.host_alert`,
# which calls `apps.api.core.alerting.alert()` — ONE implementation of "an alarm reaches a
# human", one recipient, one transport, one set of bounds (D-49). `scripts/host_alert.py`
# argues why a subprocess and not an SMTP call from the shell, and what that costs.
#
# THIS FILE EXISTS SO THAT NOTHING ELSE HAS TO KNOW WHERE ANYTHING IS. A systemd unit's
# working directory is not the repository, `apps` is imported from the tree rather than
# installed into the virtualenv (pyproject: the root is a virtual workspace), and the
# `postgres` user's PATH has no reason to contain our venv. All three are resolved here,
# from this script's own location, so the units and `notify.sh` stay free of paths.

set -uo pipefail   # NOT -e: every failure below must be REPORTED, not silently inherited.

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$here/../.." && pwd)

python=${CALEVATE_PYTHON:-$root/.venv/bin/python}
if [[ ! -x "$python" ]]; then
  # Deliberately not falling back to `python3`: a system interpreter without the app's
  # dependencies would fail on an import three seconds later with a traceback nobody
  # reads. Say which file is missing, once, in words.
  echo "alert-to-app: no interpreter at $python (set CALEVATE_PYTHON); alert NOT delivered" >&2
  exit 78   # EX_CONFIG, the same code host_alert.py uses for "nowhere to deliver"
fi

# WHERE THE CONFIG COMES FROM, and why the working directory decides it. Pydantic Settings
# reads `.env` RELATIVE TO THE WORKING DIRECTORY, and the process environment wins over it.
# So:
#   * repo `.env` readable by this user  -> run from the repo root, config as every other
#     process on this host sees it (the simple deployment);
#   * `.env` NOT readable (the hardened one: `postgres` must not hold the app's secrets)
#     -> run from `/`, and the unit supplies `EnvironmentFile=/etc/calevate/alerts.env`
#     with only the keys `Settings` requires plus SMTP_* and ALERTS_EMAIL.
# Both work, and neither needs an argument. PYTHONPATH is what makes `apps` importable
# from either place.
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
if [[ -r "$root/.env" ]]; then
  cd "$root" || exit 78
else
  cd / || exit 78
fi

# A hard ceiling on the whole thing. `host_alert.py` already bounds its own wait
# (FLUSH_TIMEOUT_S = 45s), so this only catches the case where the interpreter itself
# wedges — a backup unit must never hang on its own alarm. `timeout` is coreutils and is
# on every host that has the rest of this directory's tools; if it is somehow absent,
# still deliver rather than refusing to alert.
#
# The repeat-suppression stamp directory is passed as an ARGUMENT, not read from the
# environment by the Python: a process in this repo reads config through `Settings` or not
# at all (`scripts/check_env_parity.py` enforces exactly that), and a host path is not
# application config. A shell wrapper is the right place for it, so it is read here.
args=()
[[ -n "${CALEVATE_ALERT_STATE_DIR:-}" ]] && args=(--state-dir "$CALEVATE_ALERT_STATE_DIR")

if command -v timeout >/dev/null 2>&1; then
  exec timeout --signal=TERM --kill-after=10s 90s "$python" -m scripts.host_alert ${args[@]+"${args[@]}"}
fi
exec "$python" -m scripts.host_alert ${args[@]+"${args[@]}"}
