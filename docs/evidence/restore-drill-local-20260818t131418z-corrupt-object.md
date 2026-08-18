# Local restore drill — 20260818t131418z

Produced by `make restore-drill` (`scripts/restore_drill.py`). This is the LOCAL
harness record, not the quarterly drill record required by
`runbooks/backup-restore-drill.md` §9 — see §0a there for how the two relate.

- Run at: 2026-08-18 13:14 UTC
- Chain exercised: **B-local** — logical dump, `age`, S3-compatible object store,
  fetch, decrypt, `pg_restore`, verify. The offsite provider is stood in for by the
  MinIO in `docker-compose.yml`.
- Sabotage mode: corrupt-object
- **Verdict: RED**
- Wall clock: 4.8s

## Stages

| stage | result | seconds | detail |
|---|---|---:|---|
| `preflight` | ok | 0.39 | postgres 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1), age 1.1.1, s3 at http://127.0.0.1:9000 |
| `provision-source` | ok | 3.78 | calevate_drill_src_20260818t131418z at head f1c8b7d5a903, 14 leads across 2 tenants, 6 audit entries |
| `dump` | ok | 0.15 | 269976 bytes with production flags (--format=custom --compress=6 --file --dbname) |
| `encrypt` | ok | 0.02 | age --encrypt --recipients-file --output -> 270240 bytes, sha256 0c4c64b5b47d1ade…; plaintext removed |
| `upload` | ok | 0.07 | s3://calevate-drill-20260818t131418z/postgres/2026/08/18/calevate-20260818t131418z.dump.age + evidence json |
| `object-store-fidelity` | ok | 0.14 | multipart ETag is NOT a content hash; object-lock: refused (ObjectLockConfigurationNotFoundError); x-amz-checksum-sha256: supported |
| `fetch` | **FAIL** | 0.02 | artifact digest mismatch: the object in the bucket does not hash to its evidence file (1561b540400a07db… != 0c4c64b5b47d1ade…). Treat the backup as absent. |
| `cleanup` | ok | 0.18 | dropped 1 scratch db(s), deleted 4 objects, removed the decrypted working copy |

## Verification

| check | result | detail |
|---|---|---|

**Aborted:** artifact digest mismatch: the object in the bucket does not hash to its evidence file (1561b540400a07db… != 0c4c64b5b47d1ade…). Treat the backup as absent.

## Object store fidelity (measured against the stand-in)

- `additional_checksum_sha256`: supported
- `list_objects_v2`: 3 keys
- `multipart_etag`: f9563db4ff2e5e1eb5fcdf085124080b-2
- `multipart_etag_is_content_hash`: False
- `object_lock`: refused (ObjectLockConfigurationNotFoundError)
- `single_put_etag_is_md5`: True

## Coverage — what this run did NOT test

Each line needs the credential or account beside it. Until they are exercised on
real infrastructure, that part of the backup chain remains a hypothesis
(`infra/backup/README.md` §9).

| not tested | what it needs |
|---|---|
| **walg_pitr** — Chain A end to end: wal-g backup-push, WAL archiving, wal-fetch, recovery_target_time replay, and timeline handling. No wal-g command has been run by this harness or by anything else in this repository. | a wal-g binary on the host, an R2 bucket and its scoped token (infra/backup/walg.json.template), and a PGDATA to push |
| **r2_object_store** — Cloudflare R2 specifically. MinIO stands in for it here; DEPLOYMENT §7 records that R2's multipart implementation has rejected uploads other S3 clients accept, and wal-g #1639 records backup-push hanging after an S3 409. MinIO passing proves S3 semantics, not R2's. | a Cloudflare account and an R2 bucket + token |
| **offsite_provider** — The non-Cloudflare offsite destination and the rclone remote that reaches it (dump-offsite.sh's OFFSITE_REMOTE). rclone is not invoked here at all, so `rclone copy --checksum`, the read-back it performs and `rclone delete --min-age` retention pruning are all untested. | a Backblaze B2 / S3 / Hetzner Storage Box account and /etc/calevate/rclone.conf from the secrets manager |
| **age_identity_retrieval** — That the REAL age identity can still be produced from the secrets manager and still decrypts a real nightly dump. This harness generates a throwaway keypair per run, so it proves the age INVOCATION, never the key custody — and losing the identity makes every offsite dump permanently unreadable, which the drill runbook calls the most serious finding it can make. | the secrets manager and the production age identity |
| **libsodium_key** — WALG_LIBSODIUM_KEY: that chain A's backups are encrypted and that we still hold the key to decrypt them. | the secrets manager and a wal-g archive to decrypt |
| **systemd_schedule** — The timers themselves (calevate-basebackup, calevate-dump-offsite, calevate-backup-health), OnFailure= routing, Persistent=true catch-up, and backup-health.sh's reading of `systemctl show` — which infra/backup/README.md §9 flags as never exercised against a live systemd. | a host booted under systemd with the units installed |
| **alert_delivery** — That a host alert reaches a human inbox. tests/backup_alert_relay_test.py covers the relay down to a transport; nothing here or there has put a message in a real mailbox. | an SMTP provider, ALERTS_EMAIL, and somebody looking at the inbox |
| **external_dead_man** — The external dead-man's switch (heartbeat.sh -> scripts/host_heartbeat.py): that a healthy run pings, that stopped pings page a human, and that a FAILING run pings nothing. | BACKUP_HEARTBEAT_URL and the monitoring vendor's account |
| **recording_bucket** — That a recording referenced by a restored `calls` row is still readable. A database restore does not restore the recordings bucket, and a recording_url pointing at nothing is a half-recovery nobody notices until a client asks. | the production recordings bucket and its credential |
| **production_scale** — RTO and RPO at production data volume, on production hardware. Every timing below is a seeded fixture on a laptop and is evidence about the MECHANISM, never about the 4-hour RTO in OPERATIONS §5. | a scratch host sized to production and a production-sized backup |

## Scratch resources created and destroyed

- database `calevate_drill_src_20260818t131418z`
- object-store bucket `calevate-drill-20260818t131418z`
