#!/usr/bin/env bash
# Nightly wal-g base backup + retention prune. Runs on the database host as `postgres`.
#
# WHY A BASE BACKUP AT ALL, GIVEN CONTINUOUS WAL ARCHIVING. WAL is a *delta*. Replay has
# to start from a base, and it has to replay every segment written since that base — so
# with no recent base, RTO grows linearly with the age of the oldest one, and a 4-hour RTO
# (OPERATIONS §5) becomes a day of replay. A nightly base bounds replay at ~24h of WAL.
#
# WHAT THIS IS NOT. It is not the offsite copy. This lands in Cloudflare R2, the same
# vendor and account as our edge (DEPLOYMENT §7's vendor-concentration warning). The copy
# that survives a Cloudflare account event is `dump-offsite.sh`, on a different provider
# with a different credential. Neither replaces the other.
#
# Exit non-zero on any failure: systemd's OnFailure= turns that into an alert
# (infra/backup/systemd/). Do not add `|| true` anywhere in this file.

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
notify="$here/notify.sh"

WALG_CONFIG_PATH=${WALG_CONFIG_PATH:-/etc/wal-g/walg.json}
export WALG_CONFIG_PATH
PGDATA=${PGDATA:-/var/lib/postgresql/16/main}

# How many full backups to keep. `delete retain FULL N` keeps N fulls "and everything in
# the middle" — with one full per night that is N days of PITR reach, and it is also what
# prunes the WAL segments older than the oldest retained backup. Changing this number
# changes our data-retention posture, not just our storage bill: see infra/backup/README.md
# §6 (retention) and §7 (DPDP). It is not a tuning knob.
KEEP_FULL_BACKUPS=${KEEP_FULL_BACKUPS:-35}

fail() {
  "$notify" "$1" "$2" "${@:3}"
  exit 1
}

command -v wal-g >/dev/null || fail basebackup_walg_missing "wal-g is not on PATH for the postgres user"
[[ -r "$WALG_CONFIG_PATH" ]] || fail basebackup_config_unreadable "wal-g config not readable" "path=$WALG_CONFIG_PATH"
[[ -d "$PGDATA" ]] || fail basebackup_pgdata_missing "PGDATA is not a directory" "path=$PGDATA"

started=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# --verify reads and checks the checksum of every page as it is backed up
# (WALG_VERIFY_PAGE_CHECKSUMS). WHY IT IS ON DESPITE COSTING IO: silent page corruption in
# a cold table is invisible to a running database — nobody queries it — and gets copied
# faithfully into every backup until the day you restore. This is the only routine read of
# the whole heap we perform, so it is also our only corruption detector. It requires
# `data_checksums = on` on the cluster (infra/backup/README.md §3); on a cluster without
# checksums the flag has nothing to verify, which is a reason to fix the cluster, not to
# drop the flag.
if ! wal-g backup-push "$PGDATA" --verify; then
  fail basebackup_failed "wal-g backup-push exited non-zero — no new base backup exists tonight" \
    "started_at=$started"
fi

# Prune AFTER a successful push, never before. Pruning first would, on a night when the
# push then fails, leave us with fewer backups than we believe we have — the failure mode
# where the backup system itself destroys the recovery window.
#
# `delete` is a dry run unless --confirm is passed; --confirm is what makes it delete.
if ! wal-g delete retain FULL "$KEEP_FULL_BACKUPS" --confirm; then
  # A prune failure is NOT a backup failure — tonight's backup exists. It is still an
  # alert, because unpruned WAL grows the bill silently and, on a bucket with a lock
  # rule, a prune that fails every night is how you find out the lock window is longer
  # than the retention window (README §6).
  "$notify" basebackup_prune_failed \
    "backup-push succeeded but retention prune failed; storage will grow until this is fixed" \
    "keep_full=$KEEP_FULL_BACKUPS"
fi

"$here/backup-health.sh" || fail basebackup_health_failed \
  "the post-backup health check refused the archive; treat the new backup as unproven"

logger -t calevate.backup -p daemon.info -- \
  "base backup complete started_at=$started keep_full=$KEEP_FULL_BACKUPS"
