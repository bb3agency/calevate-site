#!/usr/bin/env bash
# The one place a host-side backup failure becomes visible.
#
# TWO PROCESSES, ONE VOCABULARY — the distinction that outlives any wiring. Backups run
# on the HOST, as `postgres`, under systemd, outside every Python process, so this script
# can never CALL `apps/api/core/alerting.alert()` the way application code does. What it
# can do is emit the same shape and hand it across a process boundary, which is what
# `BACKUP_ALERT_COMMAND` does (default: `alert-to-app.sh` → `python -m scripts.host_alert`
# → `alert()`). So there is one alert vocabulary and one delivery path, reached two ways:
# in-process for the app, by subprocess from here. Keep the shape identical — the moment
# these two diverge, an operator has two things to grep at 3am.
#
# THE STAGE IS THE APP'S, NOT OURS. `failure_stage=HOST_BACKUP` is a member of
# `alerting.FailureStage` (D-50), which is what lets the line above be a relay rather
# than a translation. It exists as its own stage because none of the pipeline stages
# (ROUTE_HANDLER … PROCESS_RESTART) describes "the nightly base backup did not run", and
# an alert that names the wrong stage lies about where to look. That reasoning is the
# durable part: do NOT "simplify" this to the nearest existing stage, and do not invent a
# new one here — a stage this script emits and the enum does not hold is relayed as
# HOST_BACKUP with the declared value carried along as an id (`scripts/host_alert.py`).
#
# NO PII, EVER (hard rule 6). Everything here is ids, counts, ages and our own message
# text. Nothing reads a row, a phone number or a transcript.

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: notify.sh <code> <detail> [key=value ...]" >&2
  exit 64
fi

code=$1
detail=$2
shift 2

# jq builds the JSON so that a detail containing a quote or a newline cannot forge a
# field. Hand-rolled string concatenation here is how a log line becomes injectable.
args=(--arg failure_stage "HOST_BACKUP" --arg code "$code" --arg detail "$detail")
filter='{failure_stage: $failure_stage, code: $code, detail: $detail, host: $host, ts: $ts}'
args+=(--arg host "$(hostname -s)" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)")

for pair in "$@"; do
  key=${pair%%=*}
  value=${pair#*=}
  args+=(--arg "$key" "$value")
  filter="$filter + {\"$key\": \$$key}"
done

line=$(jq -cn "${args[@]}" "$filter")

# Two destinations on purpose. journald is what an operator greps during an incident and
# what `systemctl status` shows inline; stderr is what systemd captures for the unit and
# what a human sees when running the script by hand.
#
# The `||` is not decoration: with `set -e`, a host whose journal socket is missing (a
# container, a rescue boot, a broken systemd — all situations in which backups are
# exactly what you need) would exit HERE, before the delivery below. The durable log is
# the first destination, never the gate on the other two.
logger -t calevate.alert -p daemon.err -- "$line" \
  || echo "notify.sh: journald unavailable; the line below is the only local record" >&2
echo "$line" >&2

# ---------------------------------------------------------------------------
# DELIVERY. The command receives the JSON line on stdin; the default is this repo's relay
# into `alert()` (`alert-to-app.sh`), so a host that configures NOTHING still pages a
# human. That default is the fix: while this was opt-in, the alarms most worth waking
# someone for — WAL archiving stopped, last night's dump failed — were the only ones in
# the system reaching nobody.
#
# Override to send somewhere else instead (a pager, an SMS gateway):
#
#   BACKUP_ALERT_COMMAND=/usr/local/bin/calevate-page
#
# It stays an indirection because no endpoint, token or phone number belongs in this
# repository — and because ONE command, not a list: two delivery paths are two dedupe
# windows and two rate limits, and the day one of them stops nobody notices.
#
# A failing hook must never mask the original failure, so its exit status is reported,
# not propagated: the run's own exit code still describes the BACKUP, not the alert.
# ---------------------------------------------------------------------------
alert_command=${BACKUP_ALERT_COMMAND:-}
if [[ -z "$alert_command" ]]; then
  default_command="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/alert-to-app.sh"
  [[ -x "$default_command" ]] && alert_command=$default_command
fi

if [[ -n "$alert_command" ]]; then
  if ! printf '%s\n' "$line" | "$alert_command"; then
    logger -t calevate.alert -p daemon.err -- \
      '{"failure_stage":"HOST_BACKUP","code":"alert_delivery_failed","detail":"the alert command exited non-zero; the alert above reached journald and NOBODY ELSE"}' \
      || true
    echo "notify.sh: alert delivery FAILED; the alert above reached journald only" >&2
  fi
else
  # Neither configured nor present. Said out loud, because a backup host that believes
  # it has paging and does not is the failure this whole file exists to prevent.
  logger -t calevate.alert -p daemon.err -- \
    '{"failure_stage":"HOST_BACKUP","code":"alert_delivery_unconfigured","detail":"no BACKUP_ALERT_COMMAND and no alert-to-app.sh beside this script; host alerts reach journald only"}' \
    || true
  echo "notify.sh: no alert delivery configured; this alert reached journald only" >&2
fi
