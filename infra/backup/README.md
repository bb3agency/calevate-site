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
scripts/backup/alert-to-app.sh               the default delivery hook: this host → the app's alert path
scripts/backup/heartbeat.sh                  the EXTERNAL dead man: fed only by a run in which everything passed
scripts/backup/app-python.sh                 sourced by both wrappers: one way to run a repo module as `postgres`
scripts/host_alert.py                        the entry point it execs; argues the subprocess and its cost
scripts/host_heartbeat.py                    the ping, and the vendor decision with its rejected alternatives
runbooks/database-restore.md                 PITR at 3am, with the step that proves it worked
runbooks/backup-restore-drill.md             the quarterly drill, executable and recordable
runbooks/backup-heartbeat-silent.md          what to do when the dead man pages: four causes, ordered
```

Ownership boundary, stated because it caused a real design choice: everything here runs on
the **host**, as `postgres`, outside every Python process. It cannot *call*
`apps/api/core/alerting.alert()` the way application code does — it reaches it across a
process boundary instead. §5 is that seam and what it costs.

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

And two more that answer a different question — not "did the run work" but **"did anything
run at all"** — because a backup that fails loudly is easy and a backup that silently
stops is what kills you:

5. **The schedule itself** (`systemctl show --property=ActiveState --property=LoadState
   --property=LastTriggerUSec`, per timer, every health run). Catches a masked unit, a
   disabled one, a unit file lost to a deploy that rewrote `/etc/systemd/system`, and a
   calendar expression edited into never matching. `OnFailure=` structurally cannot see
   any of those: nothing ran, so nothing failed. Read-only over D-Bus, so it works as
   `postgres`. A host where systemd does not answer is *not* alerted on — the same script
   is run by hand on a scratch host during the drill, where no Calevate timer exists.
6. **This script's own heartbeat.** Every run stamps `.calevate-health-heartbeat`; every
   run compares against the previous stamp and alerts `backup_health_gap` if the schedule
   was silent for more than three intervals. It is written on failing runs too — stamping
   only on success would put a permanent gap alert on top of a persistent backup failure.
7. **The EXTERNAL dead man** — the only detector here that reports by *not* running, and
   the only one that survives the host, systemd or the mail path being gone. A run in
   which 1-6 all passed pings a hosted check; silence pages. See "The detector that
   reports by NOT running" below — it has its own configuration and its own runbook.

### The alert path — where a host failure actually goes

`scripts/backup/notify.sh` writes a structured line to journald and stderr, in the same
shape `apps/api/core/alerting.alert()` emits, and then hands that line to
`BACKUP_ALERT_COMMAND` on stdin. **The default is `scripts/backup/alert-to-app.sh`**, which
execs `python -m scripts.host_alert` → `alert()` → the SMTP transport (D-49). So a host
that configures nothing still pages a human; the override exists for a site that wants a
pager instead, and it stays ONE command, because two delivery paths are two dedupe windows
and two rate limits and the day one of them stops, nobody notices.

That the hook was opt-in *was the bug*: while `alert()` was being given a real delivery
path, the alarms most worth waking someone for — WAL archiving stopped, last night's dump
failed — were the only ones in the system reaching nobody.

**What survives this wiring, and is the reason for its shape:** the boundary is a PROCESS
boundary, not a vocabulary one. This code cannot *call* `alert()` — it runs on the host, as
`postgres`, outside every Python process — so it emits the same shape and crosses into the
same function by subprocess. One alert vocabulary, one recipient, one transport, two ways
in. `failure_stage=HOST_BACKUP` is a real member of `alerting.FailureStage` (D-50) rather
than a private convention, which is what makes this a relay and not a translation; it is
its own stage because none of `ROUTE_HANDLER … PROCESS_RESTART` describes "the nightly base
backup did not run", and an alert that names the wrong stage lies about where to look.

**Three costs, because an operator pays them** (argued in `scripts/host_alert.py`):

- the application tree and its virtualenv must be present on the database host — true by
  construction under D-26, and the thing to revisit if the database ever moves to its own
  box;
- `Settings` is one class, so `DATABASE_URL`, `REDIS_URL` and the object-store keys must be
  *readable* by `postgres`, and so must `SMTP_*` and `ALERTS_EMAIL` — this process opens no
  database connection, so it cannot read a console-managed value. **`/etc/calevate/alerts.env`
  is the only shape**: a file owned by `root`, mode 0640, group-readable by `postgres`,
  carrying those keys and `BACKUP_HEARTBEAT_URL`, loaded by every unit here through
  `EnvironmentFile=-/etc/calevate/alerts.env`.
  **Nothing here opens either connection** — that property is deliberate in `alerting` and is re-proved end to end in
  `tests/backup_alert_relay_test.py` with both DSNs pointed at a closed port;

  > **The "simple shape" — put `SMTP_*` into the repo's `.env` and let `postgres` read it —
  > used to be offered here first, and it is withdrawn rather than demoted.** It cannot
  > work as written, because the repo `.env` is §6 tier 1 (the bootstrap eight plus the two
  > object-store credentials) and carries no `SMTP_*` and no `ALERTS_EMAIL`: those are
  > console-managed, i.e. rows in the database this process deliberately does not open, so
  > the relay exits **78 (`EX_CONFIG`) — "nowhere to deliver"** on every alarm, forever,
  > while backups look healthy.
  >
  > Adding them to that file is worse than not, and this is the part that is easy to miss:
  > **the environment always wins over the console** (`settings.apply_platform_overrides` —
  > `platform_config._resolve` never offers a key the environment declares). D-26 puts
  > PostgreSQL on the same VPS as the app, so there is ONE `/var/www/calevate/.env`, read by
  > `api`, `workers` and `voice-runtime` as well. An `SMTP_PASSWORD=` line placed there to
  > fix the backup relay silently pins the whole platform's SMTP credential to that file:
  > rotating it in the console changes a row nothing reads any more, and the failure is a
  > console screen that says the new value is live while every mail still goes out under the
  > old one. A separate `EnvironmentFile` the app processes never load has neither problem.

- **`SMTP_PASSWORD` therefore exists in two places, and there is no third option.** The
  console holds the platform's copy; `/etc/calevate/alerts.env` holds the database host's.
  That duplication is inherent — an alarm that says "the database is unrecoverable" must not
  need the database in order to be sent — so it is managed rather than removed: **rotating
  it means rotating BOTH, in the same sitting** (OPERATIONS §6's quarterly secret rotation
  names this). Rotating only the console leaves a healthy-looking platform and a host relay
  that authenticates with a dead credential, which is a *failing alarm path under a passing
  heartbeat*: the external dead man (§5) covers a check that stops running, not one that
  runs, goes red and cannot say so. Prove both after any rotation with
  `scripts/backup/notify.sh probe "delivery test"` (§8 step 11);
- an interpreter start and up to ~45s of SMTP wait per alert, paid by a backup script that
  has already failed, bounded by `timeout 90s` in the wrapper so a unit can never hang on
  its own alarm.

**The repeat window lives on disk here**, not in memory. `alert()` suppresses repeats of
one fingerprint for 15 minutes in process state; each relay is a fresh process, so that
state is empty on arrival and would suppress nothing, while `backup-health.sh` runs every
15 minutes and a broken chain emits several codes per run — roughly 96 mails a day, then a
filter rule, then an alarm reaching nobody again. So the stamp is a file per fingerprint
under `/var/lib/postgresql/.calevate-alert-state`, the *interval* is imported from
`alerting` rather than copied, and a delivery that FAILED does not start a window (the
window means "a human has been told").

### The detector that reports by NOT running — the external dead man (D-54)

Checks 5 and 6 close the schedule failures that happen **while this host is running**: a
timer that was disabled, masked, deleted or edited into silence, and a stretch during which
nothing ran, reported retroactively when it resumes.

They cannot close, and nothing inside this repository can close:

- **the host being off, wedged, out of disk or off the network** — no timer fires, no check
  runs, no alert is emitted, and the absence of alerts is indistinguishable from health;
- **systemd itself not running**, which takes checks 5 and 6 with it;
- **the alert path being broken at the far end** — a wrong `ALERTS_EMAIL`, an SMTP provider
  refusing us, a mailbox rule. Every alert then "succeeds" locally and lands nowhere.

All three are the same shape: **only an observer outside the failure domain can turn
SILENCE into a page.** That is the dead-man's-switch / Watchdog pattern — an always-firing
signal routed to a service that complains when it stops arriving (Prometheus's `Watchdog`
alert is literally `expr: vector(1)` routed to an external receiver; healthchecks.io-style
services are the same idea packaged as a URL you ping on success and that alerts on
silence).

**It is built** (D-54). The last line of `backup-health.sh` — reached only when
`failures == 0` — runs `scripts/backup/heartbeat.sh` → `python -m scripts.host_heartbeat`
→ one GET at `BACKUP_HEARTBEAT_URL`, a hosted Healthchecks.io check. The vendor comparison
and the rejected alternatives (self-hosting the same software, Sentry Crons, Dead Man's
Snitch, Cronitor, Better Stack/UptimeRobot) are argued with citations at the top of
`scripts/host_heartbeat.py`; the short version is that an observer we run is back inside
the failure domain, and routing this through Sentry would make the last alarm standing
depend on an optional credential and a shared quota.

**The asymmetry is the mechanism, not an implementation detail:**

| Situation | Ping | Who tells you |
|---|---|---|
| Every check passed | sent | nobody — that is the point |
| Any check failed | **not sent** | the email alert now, the dead man after the grace |
| Host off / systemd gone / mail path broken | **impossible to send** | the dead man, and only the dead man |

There is deliberately **no failure ping** (the vendor's `/fail` and `/start` endpoints go
unused, and a test fails if either appears in the code). Failure already has a delivery
path; a second one is a second dedupe window on one fact — the same argument that keeps
`BACKUP_ALERT_COMMAND` to ONE command — and it buys nothing for the three failures above,
which cannot send anything at all.

**Configuring it (both halves, or it is decoration):**

1. Create ONE check on the vendor: **period 15 minutes, grace 1 hour**. The grace is three
   missed runs, the same number `MAX_HEALTH_GAP_S` uses, so a slow boot or a long
   `wal-verify` does not page anyone and a stopped schedule does. Point its notification at
   the same person `ALERTS_EMAIL` reaches.
2. Put its ping URL in `BACKUP_HEARTBEAT_URL` **on the database host**, in
   `/etc/calevate/alerts.env` (§5 — the one shape), from the secrets manager.
   **It is a credential**: anyone holding it can silence the alarm by pinging it, so it is
   never committed, never pasted into a ticket, and never logged — operator output names a
   12-character digest of it instead. Rotating it = a new check, a new secret, nothing else.
3. Unset is not a quiet default. `backup-health.sh` says so in the journal on the
   transition ("backups are healthy but NOTHING outside this host is watching"), because a
   host that believes it has a dead man and does not is the failure this whole section
   exists to remove. Arming it is a line in OPERATIONS §8's pre-launch checklist.

**A heartbeat that cannot be sent is not a backup failure.** It is logged loudly
(`backup_heartbeat_undelivered`, journald + stderr) and changes neither the failure count
nor the exit status — the backup really was fine, and `basebackup.sh` exits on this
script's status, so failing the run would let one unreachable monitor mark a good backup
unproven. It deliberately does **not** send mail either: the consequence of a missing ping
is the dead man firing within the grace period, and a second notification about the first
notification is noise. Triage: `runbooks/backup-heartbeat-silent.md`.

**What remains uncovered, stated as plainly as the gap it replaces:** the monitoring vendor
itself being down tells nobody anything. That is accepted rather than solved — a monitor
watching the monitor is a regress that costs more than it buys for one operator — and it is
bounded by the quarterly drill (`runbooks/backup-restore-drill.md` §7.8), which proves the
check still turns red when the pings stop rather than assuming it.

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
11. **Write `/etc/calevate/alerts.env`** — `ALERTS_EMAIL`, `SMTP_*`, `BACKUP_HEARTBEAT_URL`
    and the three `Settings` requires to construct (`DATABASE_URL`, `REDIS_URL`, the
    object-store keys) — root-owned, 0640, group `postgres`; the units already load it
    optionally. Then prove it: `scripts/backup/notify.sh probe "delivery test"` must print
    `host_alert delivered` and put mail in the operator's inbox. `HOST_BACKUP` is already a
    member of `alerting.FailureStage` and the hook already defaults to the relay, so this is
    the only remaining step between a backup failure and a phone. **Not the app's `.env`**,
    for the reason §5 gives: the console-managed keys are not in it, and adding them pins
    the whole platform's SMTP credential to a file that outranks the console.
12. **Record the decisions this raises** in ROADMAP §6: the 35-day retention as a DPDP
    commitment (§6/§7), the external heartbeat dependency (§5 — still open, and now with
    exactly three named failures behind it), and whether `ERASURE_LIMITATIONS` gains a
    backup clause (§7).

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
- **The alert reaches the application's delivery path, end to end**
  (`tests/backup_alert_relay_test.py`, 20 tests): `notify.sh` with an EMPTY environment
  relays through `alert-to-app.sh` → `scripts/host_alert.py` → `alert()` → a transport;
  the on-disk repeat window collapses a repeated alarm and reports the count on the next
  one; a failed delivery does not start a window; an unwritable state directory sends
  anyway; an unset `ALERTS_EMAIL` exits non-zero so the journal records that nobody was
  told; a planted phone number does not survive into the mail (hard rule 6); and the whole
  path runs with `DATABASE_URL` and `REDIS_URL` pointed at a **closed port**, which is how
  "the alarm survives the thing it reports" is a tested fact rather than a claim.
  **The transport exercised is `ConsoleTransport`** — no SMTP server was contacted from
  this sandbox, so the last hop (a real mailbox) is step 11's job.
- **The schedule checks were executed against a STUBBED `systemctl`**: an inactive timer
  produces `backup_timer_inactive`, an armed-but-long-silent one `backup_timer_not_firing`,
  a healthy one nothing at all; a stale heartbeat produces `backup_health_gap` and is then
  renewed, and a first-ever run stays quiet. What that proves is the script's READING of
  systemd's answers. **It proves nothing about systemd** — see below.
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
- **`systemctl show`'s real output.** There is no systemd in this sandbox (`systemctl`
  answers "System has not been booted with systemd as init system"), so the property names
  and their formats — `ActiveState`, `LoadState`, `LastTriggerUSec` as a `date -d`-parsable
  string, `n/a` before a first trigger — are documentation-derived and exercised only
  against a stub. **The first real run may need the format corrected**; the failure mode if
  it is wrong is a `backup_timer_not_firing` alert on a healthy host, which is the safe
  direction and is the first thing to check before believing that alert.
- **Actual email delivery.** No SMTP server exists here. `alert()`'s SMTP transport is
  covered by `tests/alert_delivery_test.py`'s own doubles; nothing in this tree has put a
  message in a real inbox.

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
- **Dead-man's switch / heartbeat monitoring (§5).** The pattern named here is the standard
  one, not an invention: Prometheus's `Watchdog` alert is an always-firing rule
  (`expr: vector(1)`) routed to an EXTERNAL receiver precisely so that silence — including
  silence caused by the monitoring stack itself dying — becomes a page.
  https://runbooks.prometheus-operator.dev/runbooks/general/watchdog/ ·
  https://training.promlabs.com/training/monitoring-and-debugging-prometheus/metrics-based-meta-monitoring/end-to-end-watchdog-alerts/
  Healthchecks.io packages the same idea for scheduled jobs and documents the systemd
  shape — ping on success, `OnFailure=` for the failing run, and the service alerting when
  a ping does not arrive: https://healthchecks.io/docs/monitoring_systemd_tasks/ (egress
  blocked from this sandbox; read via search summaries).
- systemd `OnSuccess=` (the success half of `OnFailure=`, the natural place to hang a
  heartbeat ping) — **added in systemd v249**, so it is not available on older hosts and
  `ExecStartPost=` is the portable form: `systemd.unit(5)`,
  https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html (egress
  blocked; version confirmed via the man page text in search results).
- systemd timer introspection — `systemctl show -p ActiveState -p LastTriggerUSec
  -p NextElapseUSecRealtime` is the scriptable form of `list-timers`, and a timer's
  last-run state is a stamp file under `/var/lib/systemd/timers` (which is why a
  `Persistent=true` timer can be "enabled and never fired" after that file is lost):
  https://wiki.archlinux.org/title/Systemd/Timers ·
  https://documentation.suse.com/smart/systems-management/html/systemd-working-with-timers/index.html
  (both blocked from this sandbox; read via search summaries).
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
