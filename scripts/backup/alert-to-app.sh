#!/usr/bin/env bash
# The default `BACKUP_ALERT_COMMAND`: hand one host alert to the application's alert path.
#
# It reads the JSON line `notify.sh` built on stdin and execs `python -m scripts.host_alert`,
# which calls `apps.api.core.alerting.alert()` — ONE implementation of "an alarm reaches a
# human", one recipient, one transport, one set of bounds (D-49). `scripts/host_alert.py`
# argues why a subprocess and not an SMTP call from the shell, and what that costs.
#
# THIS FILE EXISTS SO THAT NOTHING ELSE HAS TO KNOW WHERE ANYTHING IS. Interpreter,
# repository root, working directory and the hard timeout are all resolved by
# `app-python.sh`, which `heartbeat.sh` sources too — one implementation of "run a module
# from this repo as `postgres`, unattended", because two copies of that logic drift and
# nobody notices which one broke.

set -uo pipefail   # NOT -e: every failure below must be REPORTED, not silently inherited.

# shellcheck source=scripts/backup/app-python.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/app-python.sh"

# The repeat-suppression stamp directory is passed as an ARGUMENT, not read from the
# environment by the Python: a process in this repo reads config through `Settings` or not
# at all (`scripts/check_env_parity.py` enforces exactly that), and a host path is not
# application config. A shell wrapper is the right place for it, so it is read here.
args=()
[[ -n "${CALEVATE_ALERT_STATE_DIR:-}" ]] && args=(--state-dir "$CALEVATE_ALERT_STATE_DIR")

# 90s: `host_alert.py` bounds its own wait (FLUSH_TIMEOUT_S = 45s) plus an SMTP retry;
# this only catches an interpreter that wedges, because a backup unit must never hang on
# its own alarm.
app_python_exec 90 scripts.host_alert ${args[@]+"${args[@]}"}
