# infra/backup/ — continuous WAL archiving, the offsite dump, and how their failure is seen

> **Nothing in this directory has been applied to anything.** No bucket, no credential, no
> cluster was touched to write it, and no command here was run against a real store. It is
> a mechanism for a human to review and then apply. Read §8 before believing any of it
> works, and §9 for the parts that could be checked here and the parts that could not.

---

## 1. The finding this answers

D-26 (ROADMAP §6) chose host PostgreSQL 16 over managed Postgres and closed the decision
by accepting a consequence, in its own words:

> nightly dumps alone would break OPERATIONS §5's RPO 15min, so continuous WAL archiving
> (wal-g → R2) is REQUIRED, plus nightly pg_dump offsite + quarterly restore drills.

None of it existed. `infra/` held Terraform and the recordings lifecycle policy and
nothing else; there was no wal-g configuration, no `pg_dump`, no restore procedure and no
drill. DEPLOYMENT §9 step 9 ("wal-g + backup crons + restore test") and §7 both wrote as
though the mechanism were present. So the RPO the runbooks promise was **unmet**, and the
way anyone would have found out is the way you always find out: during a restore.

The gap is not "we have backups but they are thin". It is that a database holding other
businesses' customer data, under DPDP and TRAI obligations, had **no recovery mechanism of
any kind**.

## 2. What is here

```
infra/backup/README.md                       this file — the design and its limits
infra/backup/postgresql-archiving.conf       the PostgreSQL 16 drop-in that turns archiving on
infra/backup/walg.json.template              wal-g settings; every secret is a REFERENCE
infra/backup/systemd/                        units + timers, including the OnFailure alert
scripts/backup/basebackup.sh                 nightly wal-g base backup + retention prune
scripts/backup/dump-offsite.sh               nightly encrypted logical dump, other provider
scripts/backup/backup-health.sh              the watchdog: four checks, four blind spots
scripts/backup/notify.sh                     the one place a host backup failure becomes visible
runbooks/database-restore.md                 PITR at 3am, with the step that proves it worked
runbooks/backup-restore-drill.md             the quarterly drill, executable and recordable
```

Ownership boundary, stated because it caused a real design choice: everything here runs on
the **host**, as `postgres`, outside every Python process. It cannot call
`apps/api/core/alerting.alert()`. §5 is how that is handled without pretending otherwise.

## 3. Two chains, on purpose, and why neither replaces the other

| | Chain A — PITR | Chain B — offsite dump |
|---|---|---|
| Tool | wal-g `wal-push` (continuous) + `backup-push` (nightly) | `pg_dump -Fc` + `age` + `rclone` |
| Destination | Cloudflare R2, **its own bucket**, own scoped token | **Any non-Cloudflare provider** (B2 / Hetzner Storage Box) |
| Answers | "restore the cluster to 14:32:10 today" | "give me back the `leads` table as of Tuesday", "Cloudflare locked our account" |
| Granularity | any instant since the oldest retained base | one snapshot per night |
| Cadence | segment-continuous, forced every 5 min | nightly |

The split is not belt-and-braces. Each chain has a failure the other survives:

- **WAL replay cannot survive a corrupt base backup.** If a heap page was already wrong
  when `backup-push` read it, every point-in-time restore from that base reproduces the
  corruption faithfully. `backup-push --verify` reads and checksums every page as it goes,
  which is our only routine full read of the heap and therefore our only corruption
  detector — but it needs `data_checksums = on`, which cannot be enabled by a config line
  (initdb, or `pg_checksums --enable` on a stopped cluster). **Verify this before trusting
  `--verify`:** `SHOW data_checksums;` must return `on`.
- **WAL replay is a poor answer to "someone dropped a table on Tuesday and we noticed on
  Friday."** PITR's answer is a whole-cluster restore to Tuesday somewhere else, which is
  correct and slow. `pg_restore -t` off Tuesday's dump is minutes. That is why chain B is a
  logical dump and not a second physical one.
- **WAL replay cannot survive losing the account.** DEPLOYMENT §7 already flagged this:
  our edge and our R2 archive are one Cloudflare account. A credential compromise or a
  suspension takes out the front door and the backups together — the exact scenario
  backups exist for. Chain B is the copy that survives it, which is why its provider and
  its credential must not be Cloudflare's. Collapsing chain B into R2 "to simplify" does
  not simplify anything; it deletes the second chain.

## 4. Authentication — by reference, never by value

Nothing in this repository names a bucket, an account, an endpoint or a key.

| Secret | Lives at | Referenced as |
|---|---|---|
| R2 backup bucket + token | `/etc/wal-g/walg.json` (0600, `postgres`) | `<<SECRET:r2/backup/*>>` in `walg.json.template` |
| Offsite provider credential | `/etc/calevate/rclone.conf` (0600) | rclone **remote name** only (`OFFSITE_REMOTE`) |
| wal-g archive encryption key | `/etc/wal-g/walg.json` | `<<SECRET:walg/libsodium_key>>` |
| age recipients (public) | `/etc/calevate/backup-recipients.txt` | path only |
| age identity (private) | secrets manager **+ one offline copy** | never on the VPS |

Two properties worth naming because they are choices, not accidents:

- **The R2 token is scoped to a backup bucket that is not the recordings bucket.** A token
  that can write backups should not be able to read recordings, and a lifecycle policy
  written for recordings (`infra/object-lifecycle/policy.json`) must not be able to expire
  a backup. Separate bucket, separate token, separate policy.
- **The VPS can write the offsite dump but cannot read it.** `age` encrypts to recipient
  public keys; the identity is never on the host. A compromised VPS therefore cannot
  decrypt the DR copy — which is the difference between a breach and a total loss.
  The cost is a key that, if lost, makes every offsite dump permanently unreadable. That is
  why the quarterly drill decrypts a real one (§*drill*), so "we still have the key" is a
  tested fact and not an assumption.

## 5. How failure becomes visible

**A backup that silently stops is worse than none.** It buys confidence and spends it at
the worst moment. So the design question is not "does it run" but "what does it look like
when it stops, and who sees that".

Four detectors, arranged so each covers the one above's blind spot
(`scripts/backup/backup-health.sh`, every 15 minutes):

1. **`pg_stat_archiver` failure counters** — the archiver's own view. **Blind spot, and it
   is the important one:** PostgreSQL documents that if the archive command is killed by a
   signal or exits above 125 (`command not found` is 127), the archiver aborts and is
   restarted by the postmaster and *the failure is not reported in `pg_stat_archiver`*.
   Delete the wal-g binary and this check stays green.
2. **Freshness of `last_archived_time`** — catches (1)'s blind spot locally: whatever the
   reason, the "when did a segment last leave" clock stops. Threshold 15 minutes, which is
   the RPO, so the alert fires exactly when the promise starts breaking. Blind spot: it
   believes PostgreSQL that the segment left.
3. **`wal-g wal-verify integrity timeline`** against the bucket — the only check that looks
   at where the data actually has to be, and the only one that catches "`archive_command`
   returned 0 and the object is not there". Also the only one that finds a *hole* in the
   chain, which is what makes a point-in-time target unreachable. Hourly; it costs network.
4. **`pg_ls_waldir()` segment count** — the consequence check. A stalled archiver piles
   unarchived segments into `pg_wal` until the volume fills and the cluster stops accepting
   writes. This is how a backup incident becomes an outage, so it alerts earlier and
   separately.

Plus the failure a script cannot report about itself: **`OnFailure=` on every unit**
(`calevate-backup-alert@.service`) fires when the run was OOM-killed, died on a signal, or
never started. And `Persistent=true` on the nightly timers so a night missed to a reboot is
run late rather than skipped in silence.

### The alert sink, stated honestly

`scripts/backup/notify.sh` writes a structured line to journald and stderr, in the same
shape `apps/api/core/alerting.alert()` emits, with one hook point (`BACKUP_ALERT_COMMAND`)
where a real sink attaches. At the time this was written **`alert()` reached nobody** — a
structured ERROR log, with the sinks OPERATIONS §4 names unwired (ROADMAP §M1). A sibling
change on this branch is giving `alert()` a real delivery path (dedupe, a token bucket and
an SMTP transport on a background thread), so this is written against the interface, not
against the behaviour either of us can see today.

**When that lands, `BACKUP_ALERT_COMMAND` should point at that same sink, not a second
one.** Two alert deliveries with two dedupe windows and two rate limits is the shape where
one of them quietly stops and nobody notices — one way per problem. The concrete wiring is
a one-line command that hands this JSON to the application's alert path; it is not written
here because the application change is not mine and its entry point is still moving.

One gap that must not be papered over: `alerting.FailureStage` is a closed `Literal` of
pipeline stages (`ROUTE_HANDLER` … `PROCESS_RESTART`). **None of them describes "the
nightly base backup did not run."** `notify.sh` therefore emits
`failure_stage=HOST_BACKUP`, which is correctly shaped and *is not currently a member of
that enum*. The fix is one line in a file this change does not own:

```python
FailureStage = Literal[..., "PROCESS_RESTART", "HOST_BACKUP"]
```

Mislabelling a host failure as `WORKER_TERMINAL` to make it fit would make the alert lie
about where to look, which is the one thing an alert must not do.

### The detector nobody has

Every check above runs **on the VPS**. If the VPS is off, the timers do not fire, nothing
fails, and nothing alerts — the classic dead-man's-switch hole. The fix is an external
heartbeat: the health timer pings a third-party dead-man endpoint on success, and *that*
service alerts on silence. It is **not built here** because it adds an external dependency
and a vendor, which needs a decision-log entry (ROADMAP §6), and because with no alert sink
wired yet it would page the same nobody. Until it exists, the honest statement is: **an
extended outage of the whole VPS is currently detected by a human noticing.**

## 6. Retention, and what it costs

| Chain | Kept | Mechanism |
|---|---|---|
| A — R2 PITR | **35 days** | `wal-g delete retain FULL 35 --confirm`, nightly, after a successful push |
| B — offsite dumps | **35 days** | `rclone delete --min-age 35d` |

**Why 35 and not 7, 90 or 365.** The floor is set by the longest routine reason to reach
backwards: the invoice run is monthly (OPERATIONS §6), so a billing dispute or a metering
bug can require the state at the last invoice — one full cycle, plus slack for it to be
noticed. The ceiling is set by §7: every extra day of retention is an extra day in which an
erasure request cannot fully reach our data. 35 days is the smallest number that covers the
first constraint, and it is deliberately not rounded up to a comfortable 90.

**There is deliberately no long-term archival copy.** No monthly-kept-for-a-year, no annual
snapshot. A backup is for recovery; any copy kept beyond the recovery horizon is a
*retention* of personal data and needs its own lawful basis and its own row in
`retention_policies`, not a quiet inheritance from the backup system.

**These numbers are a data-protection commitment, not a storage knob, and changing either
needs a decision-log entry** (ROADMAP §6) — as does the DPDP position in §7. Neither is
mine to close.

**Cost.** Published rates, August 2026: R2 standard storage $0.015/GB-month, Class A
$4.50/M, Class B $0.36/M, **egress free** — which matters more than the storage line,
because a restore drill that costs money is a drill that gets skipped. Offsite: Backblaze
B2 $0.006/GB-month with egress free up to 3× stored volume, or a Hetzner Storage Box at a
flat ~€3.20/month for 1 TB with unmetered traffic.

Worked example at a 20 GB database, compressed roughly 4:1, nightly fulls for 35 days:

- Chain A bases: 20 GB ÷ 4 × 35 ≈ **175 GB** ≈ $2.6/month.
- Chain A WAL: 288 forced segments/day × 16 MB = 4.6 GB/day **uncompressed worst case**;
  forced segments are mostly zeroes and compress hard, so the real figure should be a small
  fraction of that. **This ratio is UNMEASURED** — measure it in week one (§9) and revisit
  `archive_timeout` downward if it is as cheap as expected.
- Chain B: another ~175 GB at B2 ≈ $1/month, or inside a €3.20 Storage Box.
- Operations: ~300 Class A puts/day ≈ 9k/month, inside R2's 1M free tier.

Order of magnitude: **single-digit dollars a month**, which is the correct amount to spend
on not losing a client's CRM. If the real number is materially different, the compression
assumption was wrong — check that before changing the retention.

**Ransomware / rogue-credential note.** R2 supports **bucket locks**: retention rules on a
prefix (`--retention-days`, `--retention-date`, or indefinite) that prevent deletion and
overwriting, and that **take precedence over lifecycle rules**. Locking the backup prefix
for **30 days** means a stolen write token cannot destroy the archive it can write to.
30 and not 35 on purpose: the lock window must sit *below* the retention window or
`wal-g delete` fails every night against locked objects and the prune alert becomes noise
that gets ignored. **Never use `--retention-indefinite`** — Cloudflare documents that
indefinite locks cannot be removed. Applying the lock is a step in §8; it is not applied.

## 7. Backups contain personal data, and DPDP erasure cannot reach into them

This must be stated, not skipped, because the erasure workflow already issues certificates
to data principals (`apps/api/compliance/deletion.py`, SECURITY-COMPLIANCE §4).

A backup of the Calevate database contains phone numbers, transcripts, leads and consent
records. It is therefore itself personal data, and it is **immutable by design** — the
property that makes a backup trustworthy is exactly the property that stops us reaching
into it to delete one person's rows. Selectively editing a base backup is not possible;
selectively editing a WAL stream is not coherent.

The position this design takes, and its three concrete consequences:

1. **Erasure is applied to the live database immediately and to backups by expiry.** A
   record erased today is gone from production today and gone from every backup within
   **35 days** (§6). That bound is the reason the retention window is short — it is the
   erasure SLA for backups, and it should be what the DPA and the certificate say.
2. **A restore un-erases.** Restoring to an instant before an erasure request completed
   brings that person's data back. This is the failure everyone forgets, so it is a
   **mandatory step in `runbooks/database-restore.md`**: before the restored cluster
   accepts traffic, replay the erasures that completed after the recovery target. The
   authoritative list must be read from the **pre-restore** database (still on disk as the
   moved-aside `PGDATA`), because requests raised after the target do not exist in the
   restored one at all.
3. **The certificate's limitations text may need a backup clause.** `ERASURE_LIMITATIONS`
   today names the object-store lifecycle rule and the unconfirmed engine-side deletion. It
   does not mention backups. Whether it should is a **founder decision and a DPA edit**,
   not an implementation detail — the same shape as the two open questions already recorded
   in SECURITY-COMPLIANCE §4. **This change does not edit that text**; it records that the
   decision is now owed, with the 35-day bound as the fact the decision can lean on.

## 8. What a human must do before any of this is real

Everything below needs credentials, a host and network access that did not exist where this
was written. **Do not assume any of it works.**

1. **Create the R2 backup bucket — separate from the recordings bucket** — and an API token
   scoped to it alone. Confirm which R2 account is live (`infra/README.md` §1 has the same
   caution for the recordings bucket).
2. **Install wal-g on the database host.** Latest release at time of writing: **v3.0.8,
   20 Jan 2026** — note the cadence (v3.0.7 was April 2025) when planning upgrades. Use the
   PostgreSQL-flavoured release binary; `wal-g --version` must report the build for `pg`.
3. **Place `/etc/wal-g/walg.json`** from `walg.json.template`, with real values from the
   secrets manager. `chown postgres:postgres`, `chmod 0600`. Then, as `postgres`:
   `wal-g backup-list` — it should succeed and return nothing. **This is the first moment
   anyone finds out whether wal-g and R2 actually agree**, and it is unvalidated here.
4. **Confirm `SHOW data_checksums;` is `on`.** If not, schedule `pg_checksums --enable` on
   a stopped cluster; until then `backup-push --verify` verifies nothing.
5. **Install the drop-in** (`postgresql-archiving.conf`), then **restart** (archive_mode and
   wal_level need one) and confirm with `SELECT * FROM pg_stat_archiver;` that
   `archived_count` moves.
6. **Take the first base backup by hand**, watching it: `wal-g backup-push $PGDATA --verify`.
   **Watch for a hang at high CPU with no progress** — wal-g issue #1639 records exactly
   that after an S3 `409 OperationAborted`, and R2's multipart implementation has a
   documented history of rejecting uploads other tools accept (Barman, s3fs, rclone and the
   Docker registry all have R2 multipart issues on file). If it happens, the mitigation is
   lower upload concurrency, and the honest fallback is that **R2 may not be a viable wal-g
   target**, in which case chain A moves to the offsite provider and the vendor-concentration
   problem inverts. **This is the single largest unverified assumption in this design.**
7. **Install the timers**: copy `infra/backup/systemd/*` to `/etc/systemd/system/`,
   `systemctl daemon-reload`, `systemctl enable --now` the three timers. Check
   `systemctl list-timers 'calevate-*'`.
8. **Configure `/etc/calevate/rclone.conf`** for the non-Cloudflare provider and
   `/etc/calevate/backup-recipients.txt` with the age recipients. Generate the age identity
   somewhere that is not the VPS; store it in the secrets manager plus one offline copy.
9. **Apply the R2 bucket lock** on the backup prefix, 30 days (§6). Never indefinite.
10. **Run the drill before go-live, not after** — `runbooks/backup-restore-drill.md`. Until
    it has passed once, the correct description of this directory is "a backup system we
    believe in", and D-26's requirement is not met.
11. **Add `HOST_BACKUP` to `alerting.FailureStage`** (§5) and wire a sink, or these alerts
    remain log lines nobody reads.
12. **Record the decisions this raises** in ROADMAP §6: the 35-day retention as a DPDP
    commitment (§6/§7), the external heartbeat dependency (§5), and whether
    `ERASURE_LIMITATIONS` gains a backup clause (§7).

## 9. What could and could not be checked here

**Checked, in this sandbox, with no network and no credentials:**

- All four shell scripts pass `bash -n`.
- All seven systemd units parse under `systemd-analyze verify`; the only diagnostic is that
  `/var/www/calevate/scripts/backup/*.sh` does not exist here, which is the deploy path, not
  a unit error. That proves directive names and syntax, and nothing about behaviour.
- `walg.json.template` parses as JSON.
- **`notify.sh` was executed.** It emits valid JSON with quotes and newlines in the detail
  correctly escaped (which is why `jq` builds the line instead of string concatenation),
  the `BACKUP_ALERT_COMMAND` hook receives the line on stdin, and a hook that exits
  non-zero is reported without masking the original alert or changing the exit status.
- **`backup-health.sh` was executed** with no PostgreSQL, no wal-g and no config present.
  It ran *all* checks rather than stopping at the first, emitted `health_db_unreachable`,
  `health_pg_wal_unreadable` and `walg_unavailable`, and exited 1. That is the watchdog's
  failure path validated end to end, in the only way it can be here.
- **Both guard paths were executed**: `basebackup.sh` refuses with `basebackup_walg_missing`;
  `dump-offsite.sh` refuses with `offsite_tool_missing` and refuses outright when
  `OFFSITE_REMOTE` is unset.
- **The `jq` filters were tested against synthetic wal-g JSON**: an all-OK `wal-verify`
  document passes; one containing `FAILURE`/`MISSING_DELAYED` at any depth is caught; a
  document with no `status` field anywhere produces the empty result that triggers the loud
  `wal_verify_unparseable` alert rather than a silent pass; `backup-list` timestamps are
  found under `time`, `finish_time` or `start_time`, and an empty list yields nothing.
- Every wal-g command string used is quoted from wal-g's own `docs/` (§10) rather than
  recalled.

**NOT checked, and marked as such wherever it appears:**

- **No wal-g command was ever run.** wal-g is not installed in this sandbox. Every
  invocation is documentation-derived.
- **wal-g against R2 specifically** — see §8 step 6. Documented-compatible, not verified.
- **`wal-verify --json` and `backup-list --json` field names.** `backup-health.sh` parses
  both defensively (any `status` anywhere must be `OK`; timestamps tried under three
  plausible keys) and **alerts loudly rather than passing silently** when the shape is not
  recognised. That is the correct behaviour for an unverified contract, but it means the
  first real run may produce a `wal_verify_unparseable` alert that is a parser problem, not
  a backup problem. Expect it; fix the filter, do not loosen it.
- **No PostgreSQL cluster was restored, promoted, or point-in-time recovered.** The restore
  runbook is derived from PostgreSQL 16 documentation and wal-g's, and it is a *hypothesis*
  until the drill runs.
- **Compression ratios and therefore all cost figures** (§6).
- **`rclone`, `age`, `jq` and `logger` presence on the host** — assumed, listed in §8.

## 10. Sources

Command syntax and settings are quoted from first-party documentation rather than recalled.

- wal-g `docs/PostgreSQL.md` — `backup-push`/`backup-fetch`/`wal-push`/`wal-fetch`/
  `wal-verify`/`backup-list`/`delete` syntax, and `restore_command = 'wal-g wal-fetch "%f" "%p"'`:
  https://github.com/wal-g/wal-g/blob/master/docs/PostgreSQL.md
- wal-g `docs/STORAGES.md` — `WALG_S3_PREFIX`, `AWS_ENDPOINT`, `AWS_S3_FORCE_PATH_STYLE`,
  `AWS_REGION`: https://github.com/wal-g/wal-g/blob/master/docs/STORAGES.md
- wal-g `docs/README.md` — `--config`/`WALG_CONFIG_PATH`, `WALG_COMPRESSION_METHOD`
  (default lz4), `WALG_LIBSODIUM_KEY`(+`_TRANSFORM`), `delete retain FULL N` and the
  dry-run-unless-`--confirm` rule: https://github.com/wal-g/wal-g/blob/master/docs/README.md
- wal-g releases (v3.0.8, 20 Jan 2026): https://github.com/wal-g/wal-g/tags
- wal-g issue #1639 — `backup-push` hangs at high CPU after an S3 409
  `OperationAborted`: https://github.com/wal-g/wal-g/issues/1639
- R2 multipart-compatibility precedent in other tools: Barman
  https://github.com/EnterpriseDB/barman/issues/954 · s3fs-fuse
  https://github.com/s3fs-fuse/s3fs-fuse/issues/2095 · distribution
  https://github.com/distribution/distribution/issues/3873
- Cloudflare R2 bucket locks — prefix rules, `--retention-days`/`--retention-date`/
  `--retention-indefinite`, precedence over lifecycle rules, indefinite locks cannot be
  removed: https://developers.cloudflare.com/r2/buckets/bucket-locks/ (fetch was blocked by
  this sandbox's egress proxy; read via search summaries and the docs source at
  https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/r2/buckets/bucket-locks.mdx
  — **re-read the live page before applying a lock**)
- PostgreSQL 16 — `pg_stat_archiver`, and the caveat that archiver aborts on a signal or an
  exit status above 125 are *not* recorded there:
  https://www.postgresql.org/docs/16/monitoring-stats.html (blocked by egress here; the
  caveat is quoted in EDB's write-up
  https://www.enterprisedb.com/blog/how-monitoring-wal-archiving-improves-postgresql-94-and-pgstatarchiver)
- PostgreSQL — `recovery_target_time` takes `timestamp with time zone` syntax but **rejects
  timezone abbreviations**; use a numeric offset or a full zone name:
  https://www.postgresql.org/docs/current/runtime-config-wal.html#RUNTIME-CONFIG-WAL-RECOVERY-TARGET
  (via https://postgresqlco.nf/doc/en/param/recovery_target_time/)
- R2 pricing (Aug 2026): storage $0.015/GB-mo, Class A $4.50/M, Class B $0.36/M, egress
  free — https://developers.cloudflare.com/r2/pricing/
- Backblaze B2 $6/TB-mo with free egress to 3× stored volume —
  https://www.backblaze.com/cloud-storage/pricing ; Hetzner Storage Box BX11 1 TB at
  €3.20/mo, unmetered traffic — https://www.hetzner.com/storage/storage-box
- **DEPLOYMENT §7's open question, now answered (secondary sources, corroborated).**
  pgBackRest **was** archived on 27 April 2026 after Crunchy Data's sale ended its
  sponsorship, and was then **rescued** in May 2026 by a coalition (AWS, Supabase, Percona,
  pgEdge, Tiger Data, Eon). So the "unmaintained" claim was true and is no longer.
  It does not change the choice — wal-g still suits a single-VPS, no-backup-server topology
  better — but the *reason* recorded in DEPLOYMENT §7 was wrong and is corrected there.
  https://percona.community/blog/2026/04/28/pgbackrest-is-archived-what-now/
