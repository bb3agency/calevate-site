#!/usr/bin/env bash
# Feed the EXTERNAL dead-man's switch. Run by `backup-health.sh` ONLY when every backup
# check passed — never on a failing run, and obviously never on a host that is down.
#
# That asymmetry is the entire mechanism: what pages an operator here is SILENCE, not a
# message, which is the only way to report the three failures that take the observer away
# with the observed (host off, systemd gone, alert path broken beyond us — D-50,
# `infra/backup/README.md` §5). The vendor choice, the rejected alternatives and the
# reason there is deliberately no failure ping are argued in `scripts/host_heartbeat.py`.
#
# Runnable BY HAND, which is the point of it being a file: during the quarterly drill an
# operator runs it and watches the vendor dashboard register the ping (drill §7.8). Exit
# status is `host_heartbeat`'s: 0 fed, 69 not delivered, 78 not configured.

set -uo pipefail   # NOT -e: a failed heartbeat is reported by its exit code, not by a trap.

# shellcheck source=scripts/backup/app-python.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/app-python.sh"

# 60s: `host_heartbeat` bounds itself at ~21s (3 attempts × 5s timeout + backoff); this
# only catches an interpreter that wedges. A health run must never hang on a side channel
# whose failure mode is already "the dead man fires", which is the outcome we want anyway.
app_python_exec 60 scripts.host_heartbeat
