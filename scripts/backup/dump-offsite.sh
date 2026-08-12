#!/usr/bin/env bash
# Nightly logical dump, encrypted, to a NON-Cloudflare provider. Runs as `postgres`.
#
# WHY THIS EXISTS ALONGSIDE wal-g. They fail differently, and each one's failure is the
# other's reason to exist:
#
#   * WAL replay cannot survive a CORRUPT BASE. If a page was already wrong when the base
#     backup was taken, every point-in-time restore from that base reproduces the
#     corruption faithfully. A logical dump is re-read and re-parsed row by row: it cannot
#     carry a torn page forward, and a dump that restores is proof the logical contents
#     are coherent.
#   * WAL replay cannot easily give you YESTERDAY'S STATE OF ONE TABLE. Someone drops a
#     table at 14:00 and nobody notices for three days; PITR's answer is "restore the
#     whole cluster to 13:59 somewhere else", which is right but slow. `pg_restore -t` off
#     last night's dump is minutes.
#   * WAL replay cannot survive LOSING THE ACCOUNT. DEPLOYMENT §7: our edge and our R2
#     archive are one Cloudflare account. One credential compromise or suspension takes
#     out the front door and the backups together — which is the exact scenario backups
#     exist for. THIS file is the copy that survives that, which is why its destination
#     and its credential must not be Cloudflare's. If someone "simplifies" this to R2, the
#     whole second chain stops being a second chain.
#
# Exit non-zero on failure; systemd OnFailure= alerts (infra/backup/systemd/).

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
notify="$here/notify.sh"

# rclone remote name, configured in /etc/calevate/rclone.conf from the secrets manager.
# NO bucket name, account id, endpoint or key appears in this repository — the remote name
# is an indirection, and the thing it points at is operator-supplied.
OFFSITE_REMOTE=${OFFSITE_REMOTE:?set OFFSITE_REMOTE, e.g. calevate-offsite:calevate-dr}
RCLONE_CONFIG=${RCLONE_CONFIG:-/etc/calevate/rclone.conf}
export RCLONE_CONFIG
# age recipients (public keys). Public keys are not secrets, but they are deployment
# facts, so they live on the host next to the rclone config, not in git.
AGE_RECIPIENTS=${AGE_RECIPIENTS:-/etc/calevate/backup-recipients.txt}
STAGING=${STAGING:-/var/lib/postgresql/backup-staging}
OFFSITE_KEEP_DAYS=${OFFSITE_KEEP_DAYS:-35}
# The RLS tripwire, explained at the check below. 0 disables it (first run only).
MIN_DUMP_RATIO_PCT=${MIN_DUMP_RATIO_PCT:-50}
SIZE_STAMP=${SIZE_STAMP:-/var/lib/postgresql/.calevate-dump-size}

fail() { "$notify" "$1" "$2" "${@:3}"; exit 1; }

for tool in pg_dump rclone age sha256sum jq; do
  command -v "$tool" >/dev/null || fail offsite_tool_missing "required tool not installed" "tool=$tool"
done
[[ -r "$AGE_RECIPIENTS" ]] || fail offsite_recipients_missing "age recipients file unreadable" "path=$AGE_RECIPIENTS"
[[ -r "$RCLONE_CONFIG" ]] || fail offsite_rclone_config_missing "rclone config unreadable" "path=$RCLONE_CONFIG"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
day=$(date -u +%Y/%m/%d)
mkdir -p "$STAGING"
# The staging file is an unencrypted copy of every phone number and transcript in the
# platform. It exists for seconds and is removed on every exit path, success or not.
trap 'rm -f "$STAGING"/*.dump "$STAGING"/*.rdb' EXIT
chmod 700 "$STAGING"

dump="$STAGING/calevate-$stamp.dump"

# -Fc: the custom format, which is compressed and, unlike a plain SQL file, supports
# selective restore (`pg_restore -t leads`) — the "give me back yesterday's table" case
# above depends on it.
#
# ROLE, AND THE FAILURE THIS AVOIDS. Every tenant-scoped table has FORCEd RLS (hard rule
# 1). A pg_dump run by a role subject to those policies dumps ZERO ROWS from them and
# exits 0 — a perfect-looking backup of an empty database. pg_dump must therefore run as a
# role that bypasses RLS (the cluster superuser). That is not a hard-rule-1 violation:
# rule 1 forbids the admin role in APP code paths, and a host backup is not one. It is
# also why the size tripwire below is not optional.
if ! pg_dump --format=custom --compress=6 --file="$dump" \
     --dbname="${BACKUP_DSN:-postgresql:///calevate}"; then
  fail offsite_pgdump_failed "pg_dump exited non-zero; no logical dump exists tonight"
fi

size=$(stat -c %s "$dump")

# THE TRIPWIRE. A dump that suddenly shrinks by half is the signature of the RLS failure
# above, of a dropped schema, or of a disk that filled mid-write. Any of the three is worth
# waking someone for, and none of them makes pg_dump exit non-zero.
if [[ "$MIN_DUMP_RATIO_PCT" -gt 0 && -r "$SIZE_STAMP" ]]; then
  previous=$(cat "$SIZE_STAMP" 2>/dev/null || echo 0)
  if [[ "$previous" -gt 0 ]] && (( size * 100 < previous * MIN_DUMP_RATIO_PCT )); then
    fail offsite_dump_shrank \
      "tonight's dump is far smaller than last night's — suspect RLS-filtered dump, dropped objects, or a truncated write" \
      "bytes=$size" "previous_bytes=$previous"
  fi
fi

# Encrypted BEFORE it leaves the host, so the offsite provider never holds plaintext
# personal data (SECURITY-COMPLIANCE §5: "backups encrypted"). age with recipient public
# keys means this host can WRITE a backup it cannot itself READ — a compromised VPS cannot
# decrypt the DR copy. That property is worth the extra key to manage.
#
# THE OBVIOUS FAILURE MODE, SAID OUT LOUD: lose the age identity and every dump here is
# permanently unreadable. The identity lives in the secrets manager AND in one offline
# copy, and the quarterly drill decrypts a real dump precisely so that "we still have the
# key" is a tested fact rather than an assumption (runbooks/backup-restore-drill.md).
if ! age --encrypt --recipients-file "$AGE_RECIPIENTS" --output "$dump.age" "$dump"; then
  fail offsite_encrypt_failed "age encryption failed; refusing to upload plaintext"
fi
rm -f "$dump"

digest=$(sha256sum "$dump.age" | cut -d' ' -f1)
encrypted_size=$(stat -c %s "$dump.age")

# Evidence, not decoration. This is what the quarterly drill quotes and what an auditor is
# shown: an artifact name, a hash, a size and a wall-clock instant. It contains no personal
# data and no credential, so it can be committed to docs/evidence/ verbatim.
evidence="$STAGING/calevate-$stamp.evidence.json"
jq -n \
  --arg artifact "calevate-$stamp.dump.age" \
  --arg sha256 "$digest" \
  --arg created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg pg_version "$(psql --no-psqlrc -Atqc 'SHOW server_version;' 2>/dev/null || echo unknown)" \
  --argjson plaintext_bytes "$size" \
  --argjson encrypted_bytes "$encrypted_size" \
  '{artifact:$artifact, sha256:$sha256, created_at:$created_at, pg_version:$pg_version,
    plaintext_bytes:$plaintext_bytes, encrypted_bytes:$encrypted_bytes, encryption:"age"}' \
  > "$evidence"

if ! rclone copy "$dump.age" "$OFFSITE_REMOTE/postgres/$day/" --checksum; then
  fail offsite_upload_failed "rclone could not upload the encrypted dump to the offsite provider"
fi
rclone copy "$evidence" "$OFFSITE_REMOTE/postgres/$day/" --checksum \
  || fail offsite_evidence_upload_failed "the dump uploaded but its evidence file did not"

# Read the object back and compare hashes. WHY: `rclone copy --checksum` compares what the
# provider REPORTS, which on some S3-compatible stores is a multipart ETag that is not a
# hash of the content at all. Re-downloading and hashing is the only end-to-end proof that
# what is in the bucket is what we made, and at these sizes it is cheap — B2 egress is free
# up to 3x stored volume, and a Hetzner Storage Box has no traffic charge at all.
verify_dir=$(mktemp -d)
trap 'rm -f "$STAGING"/*.dump "$STAGING"/*.rdb; rm -rf "$verify_dir"' EXIT
if ! rclone copyto "$OFFSITE_REMOTE/postgres/$day/calevate-$stamp.dump.age" "$verify_dir/roundtrip.age"; then
  fail offsite_readback_failed "the dump uploaded but could not be read back; treat it as absent"
fi
if [[ "$(sha256sum "$verify_dir/roundtrip.age" | cut -d' ' -f1)" != "$digest" ]]; then
  fail offsite_digest_mismatch \
    "the object in the offsite bucket does not hash to what we uploaded; the copy is corrupt"
fi

# Redis RDB. Not a database of record — it is the ARQ queue and the caches — so its loss
# costs in-flight jobs, not client data. Copied because replaying a lost queue by hand is
# hours we would rather not spend, and skipped without failing the run if it is not there.
rdb=${REDIS_RDB_PATH:-/var/lib/redis/dump.rdb}
if [[ -r "$rdb" ]]; then
  cp "$rdb" "$STAGING/redis-$stamp.rdb"
  age --encrypt --recipients-file "$AGE_RECIPIENTS" --output "$STAGING/redis-$stamp.rdb.age" "$STAGING/redis-$stamp.rdb"
  rm -f "$STAGING/redis-$stamp.rdb"
  rclone copy "$STAGING/redis-$stamp.rdb.age" "$OFFSITE_REMOTE/redis/$day/" --checksum \
    || "$notify" offsite_redis_upload_failed "the Redis RDB copy failed; Postgres dump was unaffected"
  rm -f "$STAGING/redis-$stamp.rdb.age"
else
  "$notify" offsite_redis_missing "no Redis RDB found to copy; in-flight jobs are not covered tonight" "path=$rdb"
fi

printf '%s' "$size" > "$SIZE_STAMP"

# Retention on the offsite copy. See infra/backup/README.md §6 — this number is a
# data-protection commitment (DPDP: every extra day is an extra day an erasure request
# cannot reach), not a storage-cost knob.
rclone delete "$OFFSITE_REMOTE/" --min-age "${OFFSITE_KEEP_DAYS}d" \
  || "$notify" offsite_prune_failed "offsite retention prune failed; old personal data is being kept longer than committed" \
     "keep_days=$OFFSITE_KEEP_DAYS"

rm -f "$dump.age" "$evidence"
logger -t calevate.backup -p daemon.info -- "offsite dump complete sha256=$digest bytes=$encrypted_size"
