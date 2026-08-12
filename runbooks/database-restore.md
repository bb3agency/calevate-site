# Runbook — restoring the production database

When: the database is corrupt, a migration or a bad deploy destroyed data, someone
dropped or truncated something, or the VPS is gone. Also: the quarterly drill, which runs
this document verbatim against a scratch host (`runbooks/backup-restore-drill.md`).

**Targets from OPERATIONS §5–6: RTO 4 hours, RPO 15 minutes.** RPO is bounded by
`archive_timeout = 300` plus upload time, so expect to lose at most ~6 minutes of writes,
not 15. If you find yourself losing more, that is the finding, and it goes in the
postmortem.

> **UNVALIDATED.** No step below has been executed against a real cluster or a real
> bucket — the mechanism was written without credentials or network (`infra/backup/README.md`
> §9). Every command is quoted from PostgreSQL 16 and wal-g documentation. The first
> person to run this is doing the drill, and the drill's job is to correct this file.
> Fix what is wrong here as you go; a runbook that survived one real use is worth more
> than one that was reasoned about carefully.

---

## Ground rules — read these before typing anything

1. **Never restore onto the broken cluster's data directory.** Move it aside; do not
   delete it. It is the forensic record, it is where the pre-restore erasure list lives
   (§8), and twice in this document it is the only copy of something.
2. **Restore to a new directory, and where you can, to a different port or host.** A
   restore that boots in an alternate location is a restore you can inspect before anyone
   depends on it. Cutting over is a separate, later decision.
3. **Read-only until §7 passes.** A restored cluster that starts accepting writes before
   it has been verified cannot be redone: new writes make it impossible to try a different
   recovery target.
4. **No PII in tickets, terminals you screenshot, or the incident channel** (hard rule 6).
   Everything below selects ids, counts and timestamps. Where you must confirm a specific
   record, confirm it by id.
5. **Say the time in a format PostgreSQL accepts.** See §2 — this is the single most
   common way a PITR silently lands on the wrong instant.

---

## 0. Which of the three restores is this?

| Symptom | Go to | Chain |
|---|---|---|
| Corruption, bad migration, bad deploy — "put the cluster back to just before 14:32" | §1 onwards | A (wal-g PITR) |
| "Someone dropped `leads` on Tuesday, everything since is fine" | §10 | B (offsite dump) |
| VPS is gone / Cloudflare account is gone | §11 | B first, then A if reachable |

Choosing wrong is recoverable but expensive. If a single object was lost and the rest of
the database has three days of good work in it, **do not** whole-cluster PITR to Tuesday —
that discards the three days. §10 is the right tool.

## 1. Stop the bleeding

Writes arriving during the restore are writes you will lose or have to reconcile.

```sh
# Stop the application, not the database — the database is still your source of truth
# until you have decided otherwise.
docker compose -p calevate stop api workers voice-runtime
pm2 stop calevate-web
```

`hooks.calevate.tech` will now 502 engine webhooks. That is acceptable and expected:
Bolna is at-most-once and does not retry (TRD §5), and the List-Executions poller is the
guarantee of record — it recovers missed executions once the workers are back
(`runbooks/webhook-delivery-failures.md`). **If the outage will exceed the poller's
window, throw the big red switch** so no campaign dials into a system that cannot record
the outcome (`runbooks/calls-stopped.md` §1).

## 2. Pick the recovery target, and write it in a format PostgreSQL accepts

Get the instant from the incident timeline: the last moment you believe the data was
good. Prefer a few minutes *before* the suspect event, not after — you can always replay
further forward with a second attempt, but you cannot un-replay.

**The trap.** `recovery_target_time` takes `timestamp with time zone` syntax but
**rejects timezone abbreviations**. `'2026-08-12 14:32:00 IST'` is not accepted, and IST is
ambiguous worldwide anyway. Use a numeric offset or a full zone name:

```
recovery_target_time = '2026-08-12 14:32:00+05:30'      # good — IST as an offset
recovery_target_time = '2026-08-12 14:32:00 Asia/Kolkata' # good — full zone name
recovery_target_time = '2026-08-12 09:02:00+00'          # good — the same instant in UTC
recovery_target_time = '2026-08-12 14:32:00 IST'         # REJECTED at startup
```

Our convention is UTC in the database, IST at the edge (CLAUDE.md). Incident timelines are
usually written in IST. Convert once, deliberately, and paste the same string everywhere
below.

Confirm the target is inside the retained window before you start:

```sh
sudo -u postgres wal-g backup-list --pretty
```

If the oldest base backup is *after* your target, the target is unreachable — retention is
35 days (`infra/backup/README.md` §6). Stop and say so; do not restore to the wrong
instant and call it done.

## 3. Preserve what is there now

```sh
systemctl stop postgresql
mv /var/lib/postgresql/16/main /var/lib/postgresql/16/main.broken-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /var/lib/postgresql/16/main
chown postgres:postgres /var/lib/postgresql/16/main
chmod 0700 /var/lib/postgresql/16/main
```

**Do not delete `main.broken-*` until the postmortem is written and §8 is done.** It is the
only place the post-target erasure list exists.

Check free space first — you need room for both copies:

```sh
df -h /var/lib/postgresql
```

If there is not room, restore to a scratch host instead. Deleting the broken cluster to
make space for its own replacement is how a recoverable incident becomes a permanent one.

## 4. Fetch the base backup

```sh
sudo -u postgres wal-g backup-fetch /var/lib/postgresql/16/main LATEST
```

`LATEST` is right when the target is after the newest base backup, which is the usual
case. If the target is *older* than the newest base, fetch the newest base that precedes
it, by name from the `backup-list` output above — recovery can replay forward from a base,
never backward.

## 5. Configure recovery

```sh
sudo -u postgres tee -a /var/lib/postgresql/16/main/postgresql.auto.conf >/dev/null <<'EOF'
restore_command = '/usr/local/bin/wal-g --config /etc/wal-g/walg.json wal-fetch "%f" "%p"'
recovery_target_time = '<<the string from §2>>'
recovery_target_action = 'pause'
recovery_target_inclusive = on
EOF

# PostgreSQL 12+ enters archive recovery because this file exists. Without it the server
# starts normally, ignores every setting above, and you have restored a stale base backup
# with no replay — which looks like a successful restore until someone checks the data.
sudo -u postgres touch /var/lib/postgresql/16/main/recovery.signal
```

**`recovery_target_action = 'pause'` is not a default and not optional here.** It stops the
cluster at the target in a read-only state so §7 can inspect it *before* anything is
irreversible. `'promote'` makes the server writable at the target — at which point choosing
a different target means starting this runbook again from §3.

## 6. Start it and watch the log

```sh
systemctl start postgresql
sudo -u postgres tail -f /var/log/postgresql/postgresql-16-main.log
```

What you are looking for, in order: `starting point-in-time recovery to <target>`,
`restored log file ... from archive` repeating, then `recovery stopping before/after ...`
and `recovery has paused`.

Failure modes and what they mean:

- **`restore_command` fails on a segment (exit 74 from wal-g = archive unavailable).**
  Recovery continues past a *missing tail*; that is normal at the end of the chain. A gap
  in the *middle* is not, and it means the target is unreachable — `wal-g wal-verify
  integrity` would have told you this before you started, and `backup-health.sh` should
  have alerted when the gap appeared.
- **`FATAL: requested recovery stop point is before consistent recovery point`.** Your
  target is earlier than the base backup you fetched. Go back to §4 and fetch an older base.
- **The server starts and is immediately writable.** You forgot `recovery.signal` (§5).
  Stop, go back to §3 — this cluster is now a stale base backup with unknown writes on it.
- **`invalid value for parameter "recovery_target_time"`.** §2's timezone trap.

Confirm where you are:

```sql
SELECT pg_is_in_recovery(), pg_last_wal_replay_lsn(), pg_last_xact_replay_timestamp();
```

`pg_is_in_recovery()` must be `t`, and `pg_last_xact_replay_timestamp()` must be at or just
before your target.

## 7. Prove the restore actually worked

**An unverified restore is a hope.** Do not skip this because the log said "recovery has
paused"; that sentence means WAL was replayed, not that the data is right.

Run all six. Any failure means do not cut over.

**7.1 — The cluster is structurally sound.**

```sql
SELECT count(*) FROM pg_database WHERE datname = 'calevate';   -- 1
\c calevate
SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';
```

**7.2 — The schema is at the version the application expects.** A restore to a target
before a migration ran leaves the code ahead of the database, which fails in ways that
look like application bugs.

```sql
SELECT version_num FROM alembic_version;
```

Compare against the deployed release. If they differ, the application must be pinned to
the matching commit *before* cutover, or the migration re-run — decide that here, not
after traffic arrives.

**7.3 — The data stops where you asked it to.** This is the check that catches a restore
that landed on the wrong instant, and it is the one people skip.

```sql
SELECT max(started_at) AS last_call,
       max(created_at) AS last_call_row
FROM calls;

SELECT max(occurred_at) FROM usage_events;   -- append-only ledger, hard rule 4
SELECT max(created_at)  FROM audit_log;      -- append-only ledger, hard rule 4
```

Every one of these must be **at or just before your recovery target, and none after**. A
timestamp after the target means recovery did not stop where you think it did. A timestamp
much *before* it means replay stopped early — check §6's log for a gap.

**7.4 — A record you know about is there, by id.** Take a call or lead id from the incident
timeline that you know existed before the target:

```sql
SELECT id, tenant_id, status, started_at FROM calls WHERE id = '<<known id>>';
```

Present, and the row looks right. This is the only check that tests *content* rather than
shape, so do not substitute a count for it.

**7.5 — Tenancy still holds.** Restores rebuild tables from WAL; policies come along, but
"came along" is an assumption and hard rule 1 is not a thing to assume.

```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema='public' AND table_name = c.relname AND column_name = 'tenant_id')
  AND NOT (c.relrowsecurity AND c.relforcerowsecurity);
```

**This must return zero rows.** Any tenant-scoped table without FORCEd RLS is a
cross-tenant leak the moment the application connects.

Then run the repository's own gate against the restored database — it is stronger than the
query above and it already exists:

```sh
DATABASE_URL='postgresql://…@127.0.0.1:<restore-port>/calevate' uv run pytest -k rls
uv run python -m scripts.check_rls_coverage
uv run python -m scripts.check_ledger_immutability
```

**7.6 — Physical integrity, when corruption is the reason you are here.** Skip on a clean
DR restore; do not skip if a page error is what started this.

```sql
CREATE EXTENSION IF NOT EXISTS amcheck;
SELECT bt_index_check(index => c.oid, heapallindexed => true)
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relam = (SELECT oid FROM pg_am WHERE amname = 'btree');
```

Runs long on a large database and takes locks; run it on the restored copy, never on
production.

## 8. Re-apply erasures — do this BEFORE anyone can reach the cluster

**A restore un-erases people.** Anyone whose DPDP erasure request completed *after* your
recovery target has their data back in this cluster, and their certificate says it is gone.
That is the failure everyone forgets, and it is the one that is a regulatory problem rather
than an availability problem (`infra/backup/README.md` §7).

The list cannot come from the restored database — requests raised after the target do not
exist in it at all. It comes from the **broken cluster you preserved in §3**. That is why
§3 says do not delete it.

```sh
# Start the preserved cluster read-only on a scratch port, or read it from a copy of the
# most recent offsite dump if the preserved one will not start.
sudo -u postgres pg_ctl -D /var/lib/postgresql/16/main.broken-<stamp> -o "-p 5433" start
```

```sql
-- On the PRESERVED cluster. subject_ref is the hash that survives erasure (D-44); the
-- phone number is already cleared on a completed request, which is the point.
SELECT id, subject_ref, tenant_id, completed_at
FROM deletion_requests
WHERE status = 'completed'
  AND completed_at > '<<the recovery target from §2>>'
ORDER BY completed_at;
```

- **Zero rows** — nothing to re-apply. Write that down; it is a finding, not a non-event.
- **Any rows** — each one must be executed again against the restored cluster, through the
  normal compliance path (`POST /v1/compliance/deletion-requests`, FLOWS §9), so it
  produces a fresh proof and an audit row. **Do not hand-delete rows**: hard rule 4 makes
  the ledgers insert-only, and a hand-deletion produces no proof for the principal whose
  certificate is now, briefly, false.
- Also re-apply anything else that is *legally* one-way and was rolled back: DNC additions
  after the target (`dnc_list`, `added_at > target`). Dialling someone who opted out
  between the target and now is a hard-rule-5 breach caused by the restore
  (`runbooks/dnc-complaint.md`).

Record the count of re-applied erasures in the incident record. If any principal's data was
restored and then re-erased, the DPO decision on whether that is a notifiable event belongs
to the founder, not to whoever is running this at 3am — flag it, do not decide it.

## 9. Promote and cut over

Only after §7 passed and §8 is done.

```sql
SELECT pg_wal_replay_resume();   -- leaves the pause; recovery ends at the target
```

```sql
SELECT pg_is_in_recovery();      -- must now be f
```

Then:

```sh
# Point the application at the restored cluster and bring it back.
docker compose -p calevate up -d api workers voice-runtime
pm2 start calevate-web
curl -fsS https://api.calevate.tech/healthz && curl -fsS https://hooks.calevate.tech/healthz
```

Clear the big red switch if you set it (§1), and only then.

## 10. Restoring one table from last night's dump (chain B)

For "someone dropped `leads` on Tuesday" — no cluster restore, no lost days.

```sh
# Pull the night you want. Path layout is postgres/YYYY/MM/DD/ (dump-offsite.sh).
rclone copy calevate-offsite:<remote>/postgres/2026/08/11/ ./restore/ --include '*.dump.age'
rclone copy calevate-offsite:<remote>/postgres/2026/08/11/ ./restore/ --include '*.evidence.json'

# Verify the artifact against its evidence file BEFORE using it.
sha256sum -c <(jq -r '"\(.sha256)  \(.artifact)"' ./restore/*.evidence.json)

# Decrypt with the age identity from the secrets manager. It is NOT on the VPS by design.
age --decrypt --identity <(pass_or_secret_manager_fetch) -o ./restore/calevate.dump ./restore/*.dump.age
```

Restore into a **scratch database**, never over production, then move what you need:

```sh
createdb calevate_restore
pg_restore --dbname=calevate_restore --jobs=2 ./restore/calevate.dump
pg_restore --dbname=calevate_restore --table=leads --data-only ./restore/calevate.dump
```

Copy rows across deliberately, tenant by tenant, with `tenant_id` in every predicate. A
bulk `INSERT … SELECT` across the whole table is how one client's rows land in another
client's account. Then delete the scratch database — it is a full unredacted copy of the
platform's personal data.

## 11. The VPS or the Cloudflare account is gone

1. Stand up a new host per DEPLOYMENT §2 (baseline) and §9 steps 1–5.
2. **Chain B first.** It is on a different provider and a different credential, so it is
   reachable when chain A may not be: §10's fetch and decrypt, then `pg_restore` into a
   fresh `calevate` database. You are back to last night — RPO is one day, not 15 minutes,
   and that is the price of the Cloudflare-account scenario. Say so in the incident record.
3. If R2 is reachable after all, prefer chain A (§3–§9): it costs minutes of data instead
   of hours.
4. Rotate every credential before the application starts. If this is an account-compromise
   scenario, the old R2 token, the old wal-g key and the old rclone credential are all
   suspect, and a restore that reuses them re-opens the door you are closing.

## 12. Afterwards — do not stop here

- **Take a new base backup immediately.** Recovery started a new timeline; the archive now
  contains one history you restored from and one you are living in.
  `sudo -u postgres systemctl start calevate-basebackup.service` and watch it succeed.
- **Confirm archiving resumed**: `SELECT * FROM pg_stat_archiver;` — `archived_count`
  moving, `last_failed_time` not after `last_archived_time`. Or just
  `sudo -u postgres /var/www/calevate/scripts/backup/backup-health.sh` and expect exit 0.
- **Reconcile the engine.** Calls that completed while the workers were down were not
  recorded; the List-Executions poller is the guarantee of record and needs a clean run
  (`runbooks/webhook-delivery-failures.md`).
- **Record actual RTO and RPO**, measured, in the postmortem. Not the target — the number
  you got. If it missed OPERATIONS §5, that is the finding.
- **Fix this runbook** where it was wrong. It has never been executed against a real
  cluster (see the banner); the first person through owes the next one their corrections.
