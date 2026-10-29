#!/usr/bin/env bash
# Prune the pg_dump files taken before each deploy (/var/backups/calevate/*.dump).
#
# They exist to undo one bad deploy, not to be a backup chain: recovery is wal-g to R2
# (D-927). Each one is a full copy of every client's data, so keeping them indefinitely is
# what DPDP's storage limitation asks us not to do. A dump is deleted only when it is
# BOTH outside the newest KEEP_LAST and older than KEEP_DAYS, so a quiet fortnight never
# leaves fewer than KEEP_LAST and a busy day never deletes yesterday's.
#
# Called by basebackup.sh after a successful push, as `postgres` (the directory is
# postgres 0700). Exit 0 with nothing to do is normal.
set -euo pipefail

DUMP_DIR=${PREDEPLOY_DUMP_DIR:-/var/backups/calevate}
KEEP_LAST=${PREDEPLOY_DUMP_KEEP_LAST:-5}
KEEP_DAYS=${PREDEPLOY_DUMP_KEEP_DAYS:-14}

[[ -d "$DUMP_DIR" ]] || exit 0
[[ "$KEEP_LAST" =~ ^[0-9]+$ && "$KEEP_DAYS" =~ ^[0-9]+$ ]] || {
  echo "prune-predeploy-dumps: KEEP_LAST and KEEP_DAYS must be whole numbers" >&2
  exit 2
}

cutoff=$(( $(date +%s) - KEEP_DAYS * 86400 ))
deleted=0
index=0
# Newest first by modification time; names are ours (pre-<sha>-<date>.dump) and carry no
# newline, but -print0 keeps a stray name from splitting.
while IFS= read -r -d '' entry; do
  mtime=${entry%% *}
  path=${entry#* }
  index=$(( index + 1 ))
  (( index <= KEEP_LAST )) && continue
  (( ${mtime%.*} < cutoff )) || continue
  rm -f -- "$path"
  deleted=$(( deleted + 1 ))
done < <(find "$DUMP_DIR" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\0' | sort -z -rn)

logger -t calevate.backup -p daemon.info -- \
  "pre-deploy dumps pruned deleted=$deleted kept_last=$KEEP_LAST kept_days=$KEEP_DAYS" || true
echo "pre-deploy dumps pruned: deleted=$deleted"
