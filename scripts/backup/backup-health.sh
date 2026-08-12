#!/usr/bin/env bash
# Does the backup chain still work? Asked every 15 minutes, answered from four
# independent places, because each one is blind to what the others see.
#
# THE PROBLEM THIS SOLVES. A backup that silently stops is worse than no backup: it buys
# false confidence and spends it at the worst possible moment. Every check below exists
# because some specific way of stopping is invisible to the checks above it.
#
#   1. pg_stat_archiver failure counters — the archiver's own view. BLIND SPOT, and it is
#      the one that matters: PostgreSQL documents that when the archive command is killed
#      by a signal, or exits with a status above 125 (`command not found` is 127), the
#      archiver process aborts and is restarted by the postmaster, and THE FAILURE IS NOT
#      REPORTED IN pg_stat_archiver. Deleting the wal-g binary is therefore a failure this
#      check cannot see. (postgresql.org/docs/16/monitoring-stats.html, pg_stat_archiver.)
#   2. Freshness of the last successful archive — catches (1)'s blind spot from the local
#      side: whatever the reason, the counter of "when did a segment last leave" stops
#      moving. BLIND SPOT: it trusts PostgreSQL's word that the segment left.
#   3. wal-g's own view of the DESTINATION — `wal-verify` walks the archive in the bucket
#      and reports holes in the WAL chain. This is the only check that looks at where the
#      data actually has to be, and the only one that can catch "archive_command returns 0
#      but the object is not in the bucket". BLIND SPOT: costs network, so it runs less
#      often than (1) and (2) would like.
#   4. pg_wal growth — the consequence check. If archiving has stalled, unarchived
#      segments pile up in pg_wal until the volume fills and the cluster stops accepting
#      writes. This one turns a backup incident into a downtime incident, so it is worth
#      alerting on separately and earlier.
#   5. THE SCHEDULE ITSELF — added because 1-4 all answer "did the backup that ran
#      work?", and the failure that actually kills you is the backup that STOPPED
#      RUNNING. `OnFailure=` cannot see it (nothing ran, so nothing failed), and neither
#      can any check that looks at PostgreSQL. So this asks systemd directly whether each
#      timer is still armed and when it last fired: a masked unit, a disabled one, a unit
#      file lost to a deploy that rewrote /etc/systemd/system, a calendar expression
#      edited into never matching. BLIND SPOT, and it is the honest one: this check runs
#      FROM a timer. It cannot report while nothing is running — see §6 and README §5.
#   6. THIS SCRIPT'S OWN HEARTBEAT — the gap check. Every run stamps the time; every run
#      compares against the previous stamp. A schedule that stopped for six hours is
#      reported the moment it resumes. That is retroactive detection, which is the most
#      an on-host check can honestly claim, and it is NOT a dead-man's switch: while the
#      host is off, nothing here observes anything. Turning silence into a page requires
#      an observer outside this host (the Watchdog/dead-man pattern — an always-firing
#      signal routed to a service that complains when it stops arriving). That dependency
#      is D-50's open question and is deliberately not invented here.
#
# WHAT NO CHECK HERE CAN DO: prove the archive is RESTORABLE. Only a restore proves that.
# That is `runbooks/backup-restore-drill.md`, quarterly, and it is not optional.
#
# Exit status: 0 = every check passed. 1 = at least one check alerted. The script runs all
# checks before exiting, so one failure never hides another.

set -uo pipefail   # NOT -e: a failing check must be reported, not abort the run.

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
notify="$here/notify.sh"

WALG_CONFIG_PATH=${WALG_CONFIG_PATH:-/etc/wal-g/walg.json}
export WALG_CONFIG_PATH

# Thresholds. The archive-age one is derived, not chosen: `archive_timeout = 300` means a
# segment is forced out at least every 5 minutes even on an idle database, so three
# consecutive misses (15 min) is a real stall rather than a quiet hour. It is also exactly
# the RPO in OPERATIONS §5 — by construction, this alert fires at the moment the promise
# starts being broken, not after.
MAX_ARCHIVE_AGE_S=${MAX_ARCHIVE_AGE_S:-900}
# One nightly base backup, so 36h allows a single missed night to be noticed as a warning
# rather than a surprise, and does not fire because the timer ran at 03:05 instead of 02:55.
MAX_BASEBACKUP_AGE_S=${MAX_BASEBACKUP_AGE_S:-129600}
# pg_wal on a healthy cluster holds a handful of segments. 64 × 16MB = 1GB is far above
# normal and far below a full volume — the point is to alert while there is still room.
MAX_PG_WAL_SEGMENTS=${MAX_PG_WAL_SEGMENTS:-64}
# wal-verify walks the bucket; hourly is enough and keeps Class B operations negligible.
WAL_VERIFY_INTERVAL_S=${WAL_VERIFY_INTERVAL_S:-3600}
# One directory for every stamp this host keeps, so there is one thing to `chown postgres`
# and one thing to look at when a check believes the wrong thing about time.
HEALTH_STATE_DIR=${HEALTH_STATE_DIR:-/var/lib/postgresql}
WAL_VERIFY_STAMP=${WAL_VERIFY_STAMP:-$HEALTH_STATE_DIR/.calevate-wal-verify-stamp}
HEALTH_HEARTBEAT_STAMP=${HEALTH_HEARTBEAT_STAMP:-$HEALTH_STATE_DIR/.calevate-health-heartbeat}
# Three missed runs of a 15-minute timer. Two would fire on a slow boot or a long
# `wal-verify`; three is a schedule that stopped rather than one that slipped.
MAX_HEALTH_GAP_S=${MAX_HEALTH_GAP_S:-2700}
# The timers this backup chain is made of, each with the longest silence that is still
# normal for it. Nightly units get the same 36h the base-backup age check uses (one missed
# night is a warning, not a rounding error); the health timer gets an hour, four times its
# own interval — it is triggering the very run doing the asking, so anything older than
# that means the run came from somewhere else (a drill, a hand invocation) or the stamp is
# stale. Format: `unit:max_age_seconds`.
BACKUP_TIMERS=${BACKUP_TIMERS:-calevate-basebackup.timer:129600 calevate-dump-offsite.timer:129600 calevate-backup-health.timer:3600}

PSQL=(psql --no-psqlrc --tuples-only --no-align --quiet --dbname "${HEALTH_DB:-postgres}")

failures=0
alert() { "$notify" "$@"; failures=$((failures + 1)); }

now=$(date +%s)

# --- 6. Did WE run? The gap this script can see about itself ------------------------
# Read before anything else and written at the very end, so the window measured is
# run-to-run rather than check-to-check. A first run has no previous stamp and says
# nothing: "this host has never run the check" is what a new install looks like, and an
# alert there would train the operator to ignore this code.
last_heartbeat=0
[[ -r "$HEALTH_HEARTBEAT_STAMP" ]] && last_heartbeat=$(cat "$HEALTH_HEARTBEAT_STAMP" 2>/dev/null || echo 0)
if [[ "$last_heartbeat" =~ ^[0-9]+$ ]] && (( last_heartbeat > 0 )); then
  gap=$(( now - last_heartbeat ))
  if (( gap > MAX_HEALTH_GAP_S )); then
    # Reported ONCE, when the schedule resumes — nothing on this host can report during
    # the gap. What the number is worth: it dates the silence, so an operator can tell a
    # rebooted host (minutes) from a timer that was off all weekend (days), and knows
    # which nights to check for a missing base backup.
    alert backup_health_gap \
      "the backup health check did not run for a long stretch and has just resumed; backups were UNMONITORED for that period" \
      "gap_s=$gap" "threshold_s=$MAX_HEALTH_GAP_S"
  fi
fi

# --- 1 + 2. The archiver's own view -----------------------------------------------
# One query, so the two facts are consistent with each other. A NULL last_archived_time on
# a cluster that has been up for a while is itself the finding: archiving was configured
# and has never once succeeded.
read -r archived_count failed_count archive_age failed_after_archived < <(
  "${PSQL[@]}" -c "
    SELECT archived_count,
           failed_count,
           coalesce(extract(epoch FROM now() - last_archived_time)::bigint, -1),
           (last_failed_time IS NOT NULL
            AND (last_archived_time IS NULL OR last_failed_time > last_archived_time))
    FROM pg_stat_archiver;" 2>/dev/null | tr '|' ' '
) || true

if [[ -z "${archived_count:-}" ]]; then
  alert health_db_unreachable "could not read pg_stat_archiver; the archiver's state is unknown"
else
  if [[ "$failed_after_archived" == "t" ]]; then
    # Deliberately not logging last_failed_wal's value here — it is harmless, but the rule
    # is ids and counts only, and the segment name is in the PostgreSQL log for whoever
    # opens the runbook.
    alert archiver_failing \
      "pg_stat_archiver reports the most recent archive attempt FAILED; WAL is not reaching the bucket" \
      "failed_count=$failed_count" "archived_count=$archived_count"
  fi
  if [[ "$archive_age" -lt 0 ]]; then
    alert archiver_never_succeeded \
      "pg_stat_archiver has no last_archived_time: archiving has never succeeded on this cluster"
  elif [[ "$archive_age" -gt "$MAX_ARCHIVE_AGE_S" ]]; then
    alert archive_stale \
      "no WAL segment has been archived recently; RPO 15min (OPERATIONS §5) is being missed right now" \
      "archive_age_s=$archive_age" "threshold_s=$MAX_ARCHIVE_AGE_S"
  fi
fi

# --- 4. The consequence check ------------------------------------------------------
# pg_ls_waldir() needs pg_monitor (or superuser). Running this as `postgres` on the host
# satisfies that; running it as an application role will not, and the failure is silent
# unless we say so.
wal_segments=$("${PSQL[@]}" -c "SELECT count(*) FROM pg_ls_waldir();" 2>/dev/null) || wal_segments=""
if [[ -z "$wal_segments" ]]; then
  alert health_pg_wal_unreadable \
    "could not count pg_wal segments (pg_ls_waldir needs pg_monitor); the disk-fill precursor is unmonitored"
elif [[ "$wal_segments" -gt "$MAX_PG_WAL_SEGMENTS" ]]; then
  alert pg_wal_backlog \
    "unarchived WAL is accumulating in pg_wal; if this keeps growing the cluster stops accepting writes" \
    "segments=$wal_segments" "threshold=$MAX_PG_WAL_SEGMENTS"
fi

# --- 3. The destination ------------------------------------------------------------
if command -v wal-g >/dev/null && [[ -r "$WALG_CONFIG_PATH" ]]; then
  last_verify=0
  [[ -r "$WAL_VERIFY_STAMP" ]] && last_verify=$(cat "$WAL_VERIFY_STAMP" 2>/dev/null || echo 0)

  if (( now - last_verify >= WAL_VERIFY_INTERVAL_S )); then
    if verify_json=$(wal-g wal-verify integrity timeline --json 2>/dev/null); then
      # Parsed structurally rather than by field name: wal-g's JSON shape for wal-verify
      # is NOT pinned by any version-stable contract we have verified, so this collects
      # every `status` field anywhere in the document and requires all of them to be OK.
      # If a future version renames the checks, this still works; if it renames `status`,
      # the extraction returns nothing and the `-z` branch below alerts rather than
      # silently passing. Failing loud on an unrecognised shape is the whole point.
      statuses=$(printf '%s' "$verify_json" | jq -r '[.. | objects | select(has("status")) | .status] | .[]' 2>/dev/null)
      if [[ -z "$statuses" ]]; then
        alert wal_verify_unparseable \
          "wal-g wal-verify returned JSON with no recognisable status field; the archive is UNVERIFIED"
      elif printf '%s' "$statuses" | grep -qv '^OK$'; then
        alert wal_chain_broken \
          "wal-g wal-verify reports a gap or a timeline problem: point-in-time recovery across that gap is impossible" \
          "statuses=$(printf '%s' "$statuses" | tr '\n' ',')"
      fi
    else
      alert wal_verify_failed \
        "wal-g wal-verify could not run (credentials, network or bucket); the archive is UNVERIFIED"
    fi

    # Freshness of the newest base backup, read from the bucket rather than from a local
    # timestamp — a local success marker survives the bucket being emptied.
    if backups_json=$(wal-g backup-list --json 2>/dev/null); then
      newest=$(printf '%s' "$backups_json" \
        | jq -r '[.[] | (.finish_time // .time // .start_time // empty)] | sort | last // empty' 2>/dev/null)
      if [[ -z "$newest" || "$newest" == "null" ]]; then
        alert no_base_backup \
          "wal-g backup-list returned no base backup with a readable timestamp; WAL alone cannot be restored"
      else
        newest_epoch=$(date -d "$newest" +%s 2>/dev/null || echo "")
        if [[ -z "$newest_epoch" ]]; then
          alert backup_list_unparseable \
            "could not parse the newest base backup timestamp from wal-g backup-list; backup age is UNKNOWN"
        else
          age=$(( now - newest_epoch ))
          if (( age > MAX_BASEBACKUP_AGE_S )); then
            alert base_backup_stale \
              "the newest base backup is older than expected; every hour past this lengthens restore time" \
              "age_s=$age" "threshold_s=$MAX_BASEBACKUP_AGE_S"
          fi
        fi
      fi
    else
      alert backup_list_failed "wal-g backup-list failed; we cannot tell whether a base backup exists"
    fi

    printf '%s' "$now" > "$WAL_VERIFY_STAMP" || true
  fi
else
  alert walg_unavailable \
    "wal-g or its config is missing on this host; the destination cannot be checked from here" \
    "config=$WALG_CONFIG_PATH"
fi

# --- 5. Is the schedule still armed? -----------------------------------------------
# The one failure mode `OnFailure=` structurally cannot report: nothing ran, so nothing
# failed. `systemctl show` is read-only over D-Bus and needs no privilege, so this works
# as `postgres`.
#
# If systemd cannot be reached at all we say so on stderr and DO NOT alert. That is not
# timidity: this script is also run by hand on a scratch host during the quarterly drill,
# where there are no Calevate timers and an alert would be false. A host that is supposed
# to have these timers and cannot answer for them has a bigger problem than this check,
# and it shows up as the gap above on the next real run.
if command -v systemctl >/dev/null 2>&1; then
  for spec in $BACKUP_TIMERS; do
    unit=${spec%%:*}
    max_age=${spec##*:}
    if ! properties=$(systemctl show "$unit" \
        --property=ActiveState --property=LoadState --property=LastTriggerUSec 2>/dev/null); then
      echo "backup-health: systemd is not answering; the schedule was not checked" >&2
      break
    fi
    active=$(printf '%s\n' "$properties" | sed -n 's/^ActiveState=//p')
    loaded=$(printf '%s\n' "$properties" | sed -n 's/^LoadState=//p')
    last_trigger=$(printf '%s\n' "$properties" | sed -n 's/^LastTriggerUSec=//p')

    if [[ "$loaded" == "not-found" || "$loaded" == "masked" ]]; then
      # A deploy that rewrites /etc/systemd/system, or a masked unit somebody forgot to
      # unmask after an incident. Both look exactly like "backups are fine" from every
      # other check in this file.
      alert backup_timer_missing \
        "a backup timer's unit is not installed on this host; that backup is not scheduled at all" \
        "unit=$unit" "load_state=$loaded"
      continue
    fi
    if [[ -n "$active" && "$active" != "active" ]]; then
      alert backup_timer_inactive \
        "a backup timer is not armed; nothing will trigger that backup until someone starts it" \
        "unit=$unit" "active_state=$active"
      continue
    fi
    last_epoch=""
    [[ -n "$last_trigger" && "$last_trigger" != "n/a" && "$last_trigger" != "0" ]] \
      && last_epoch=$(date -d "$last_trigger" +%s 2>/dev/null || echo "")
    if [[ -z "$last_epoch" ]]; then
      # Armed and never fired. On a freshly installed host this is true for a few hours
      # and it is still worth saying: "enabled" is not "has run", and the difference is
      # exactly what people assume away.
      alert backup_timer_not_firing \
        "a backup timer is armed but has never fired; being enabled is not the same as having run" \
        "unit=$unit" "last_trigger=never"
    elif (( now - last_epoch > max_age )); then
      alert backup_timer_not_firing \
        "a backup timer is armed but has not fired for longer than its schedule allows" \
        "unit=$unit" "since_s=$(( now - last_epoch ))" "threshold_s=$max_age"
    fi
  done
else
  echo "backup-health: no systemctl on this host; the schedule was not checked" >&2
fi

# Written LAST and unconditionally, including on a failing run: the heartbeat records
# that the check RAN, not that it was happy. Stamping it only on success would turn a
# persistent backup failure into a permanent `backup_health_gap` on top of it.
printf '%s' "$now" > "$HEALTH_HEARTBEAT_STAMP" || \
  echo "backup-health: could not write $HEALTH_HEARTBEAT_STAMP; the gap check is blind" >&2

if (( failures > 0 )); then
  exit 1
fi
logger -t calevate.backup -p daemon.info -- "backup health checks passed" || true
