#!/usr/bin/env bash
# The one place a host-side backup failure becomes visible.
#
# WHY A SEAM AND NOT A SINK. `apps/api/core/alerting.alert()` is the application's alert
# interface: it normalizes a failure stage and a code, and today it writes a structured
# ERROR log and nothing else — routable, routed nowhere (ROADMAP §M1, OPERATIONS §4).
# Backups run on the HOST, as `postgres`, outside every Python process, so they cannot
# call that function even once it has a sink. What they can do is emit the SAME SHAPE, so
# that when the sink is wired the two streams are one vocabulary rather than two.
#
# THE VOCABULARY GAP, STATED RATHER THAN PAPERED OVER. `alerting.FailureStage` is a
# closed Literal of pipeline stages (ROUTE_HANDLER … PROCESS_RESTART). None of them
# describes "the nightly base backup did not run". Rather than mislabel a host failure as
# a worker failure — which would make the alert lie about where to look — this script
# emits `failure_stage=HOST_BACKUP`. Adding that member to `FailureStage` is a one-line
# change in a file this change does not own; until it lands, an alert from here is
# correctly shaped and NOT a member of the app's enum. Do not "fix" that by picking the
# nearest existing stage.
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
logger -t calevate.alert -p daemon.err -- "$line"
echo "$line" >&2

# ---------------------------------------------------------------------------
# THE HOOK. This is where the real sink goes — the same sink OPERATIONS §4 names for
# `alert()` (WhatsApp/email to Sri). It is deliberately a single opt-in command rather
# than an inline curl to a hardcoded URL: no endpoint, token or phone number belongs in
# this repository.
#
#   BACKUP_ALERT_COMMAND=/usr/local/bin/calevate-page
#
# The command receives the JSON line on stdin. A failing hook must never mask the
# original failure, so its exit status is swallowed and reported, not propagated.
# ---------------------------------------------------------------------------
if [[ -n "${BACKUP_ALERT_COMMAND:-}" ]]; then
  if ! printf '%s\n' "$line" | "$BACKUP_ALERT_COMMAND"; then
    logger -t calevate.alert -p daemon.err -- \
      '{"failure_stage":"HOST_BACKUP","code":"alert_delivery_failed","detail":"BACKUP_ALERT_COMMAND exited non-zero; the alert above was not delivered"}'
  fi
fi
