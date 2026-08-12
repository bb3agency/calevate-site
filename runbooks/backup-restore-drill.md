# Runbook — the quarterly restore drill

When: once per quarter (OPERATIONS §6), and **once before client #1 goes live** — the
pre-launch checklist's "backups verified" (OPERATIONS §8) means this drill has passed, not
that a backup file exists.

Why it is a separate runbook from `runbooks/database-restore.md`: that one is a recovery
under pressure; this one is a *rehearsal with a scorecard*. The rehearsal has obligations
the recovery does not — it must measure, it must alternate its source, and it must produce
a record somebody can read a year later.

**An untested restore is a hypothesis.** Everything in `infra/backup/` is currently a
hypothesis: nothing in it has been run against a real cluster or bucket. This drill is what
converts it.

Budget: **half a day.** If it takes longer than that the first time, that is data, not
failure — write down where the time went, because that is your real RTO.

---

## 0. Alternate the source — this is the point of doing it quarterly

DEPLOYMENT §7: *"Restore drills alternate sources: prove the R2 PITR path one quarter, the
offsite dump the next."*

| Quarter | Source | Proves |
|---|---|---|
| Odd (Q1, Q3) | **Chain A** — wal-g PITR from R2 | continuous archiving, base backups, the libsodium key, point-in-time targeting |
| Even (Q2, Q4) | **Chain B** — encrypted dump from the offsite provider | the offsite credential, the age identity, that we can recover with Cloudflare unavailable |

Doing chain A twice in a row is the same as never testing chain B, and chain B is the one
that covers the scenario nobody plans for. Look at the previous drill record before you
start; if the last one was chain A, this one is chain B, regardless of which is more
convenient.

## 1. Before you start

- [ ] A **scratch host or VM** that is not the production VPS, with disk ≥ 2× the database
      size. A restore onto production is not a drill, it is an outage.
- [ ] The **age identity** and the **wal-g libsodium key** fetched from the secrets manager
      **into the drill shell only**. Fetching them is itself a test: if either cannot be
      produced, **stop and record a FAIL immediately** — every backup we hold is
      unreadable, and that is the most serious finding this drill can make. It is worth
      more than the rest of the drill combined, so do it first.
- [ ] `wal-g`, `rclone`, `age`, `psql`, `pg_restore`, PostgreSQL 16 on the scratch host.
- [ ] A copy of `runbooks/database-restore.md` open — **you follow that document, verbatim,
      and note every place it is wrong.** Correcting it is a deliverable of this drill.
- [ ] Nobody deploying to production for the next few hours.

## 2. Pick the target and record it before you look

Choose a recovery target and **write down what you expect to see there before you restore**.
A drill where you decide afterwards what "correct" means proves nothing.

```sql
-- On PRODUCTION, read-only, through the audited admin path. Ids and counts only.
SELECT now() AS drill_started_at;
SELECT count(*) AS calls_total, max(started_at) AS last_call FROM calls;
SELECT count(*) AS leads_total FROM leads;
SELECT count(*) AS usage_events_total, max(occurred_at) AS last_usage FROM usage_events;
SELECT version_num FROM alembic_version;
SELECT id FROM calls ORDER BY started_at DESC LIMIT 1;   -- the "known id" for §7.4
```

**Target: 24 hours before now**, rounded to a minute, written in the format from
`database-restore.md` §2 (numeric offset or full zone name — **never a timezone
abbreviation**). Twenty-four hours is chosen so the drill exercises real WAL replay across a
full nightly cycle, rather than replaying five minutes and proving nothing.

Then run the same counting queries with `WHERE <timestamp column> <= '<target>'` and write
those numbers down. **Those are the expected values.** Everything after §5 is a comparison
against them.

## 3. Start the clock

```sh
DRILL_T0=$(date -u +%s)
```

RTO is measured from here to the moment §7's checks all pass — not to the moment the
server starts. A cluster that boots and is wrong has not recovered.

## 4. Restore

**Chain A quarters:** follow `runbooks/database-restore.md` §3–§7, on the scratch host,
into a scratch `PGDATA` on a non-default port. Skip §1 (nothing to stop) and §8 (§8 below
replaces it).

**Chain B quarters:** follow `runbooks/database-restore.md` §10, restoring the *whole*
dump — not one table — into a scratch database. The point is to prove a full recovery is
possible from the offsite copy alone.

**Simulate the failure honestly.** On a chain B quarter, do the whole drill with
**`/etc/wal-g/walg.json` renamed on the scratch host** and no R2 credential in the
environment. If R2 is reachable during a drill of the "Cloudflare is gone" scenario, you
have not tested that scenario.

## 5. Stop the clock, and record both numbers

```sh
echo "RTO: $(( ($(date -u +%s) - DRILL_T0) / 60 )) minutes"
```

RPO: on a chain A quarter, `SELECT pg_last_xact_replay_timestamp();` against the target —
the gap is your achieved point-in-time precision. On a chain B quarter, RPO is the age of
the dump you restored, which will be up to 24 hours. **Both are legitimate; record which
one you measured**, because a chain B RPO of 19 hours is a success for chain B and would be
a catastrophic failure for chain A.

## 6. Verify

Run **every** check in `runbooks/database-restore.md` §7 (7.1 through 7.6) and compare
against §2's written-down expectations. 7.6 (amcheck) is optional during a recovery; **it
is mandatory in a drill** — the drill is the only time anyone reads every page and index,
so it is the only time silent corruption in a cold table can be found.

Additionally, only in a drill:

- [ ] **Restore a single table** with `pg_restore --table` (chain B) or from the drill
      cluster (chain A). The `leads` table is the realistic case. Proves the "give me
      yesterday's table" path, which is the one you will actually need.
- [ ] **`uv run pytest -k rls`** against the restored database. Cross-tenant reads must
      return zero rows. A restored database that leaks across tenants is not a restored
      database.
- [ ] **Read one recording** referenced by a restored `calls` row from object storage. The
      database restore does not restore the bucket, and a `recording_url` pointing at
      nothing is a half-recovery nobody discovers until a client asks.

## 7. Break something on purpose

Ten minutes, once a year is not enough — do it every drill, because the detection path is
the part that rots.

1. On the **scratch** host (never production), point `archive_command` at a nonexistent
   binary and force a segment switch: `SELECT pg_switch_wal();`.
2. Wait 20 minutes. Run `scripts/backup/backup-health.sh`.
3. **Expected:** a non-zero exit and an `archive_stale` (and/or `archiver_failing`) alert
   line in the journal, tagged `calevate.alert`.
4. **The interesting case:** if `archive_command` was made *unfindable* rather than
   failing, `pg_stat_archiver` may show nothing at all — PostgreSQL does not record an
   archiver that aborted on a bad exit status. Confirm the **freshness** check
   (`archive_stale`) fires anyway. That is the check that exists solely to cover this hole,
   and this is the only time anyone proves it works.
5. Confirm the alert **reached a human** — an actual message in the operator's inbox, not
   a journald line and not a green exit status. Delivery is wired by default now
   (`notify.sh` → `alert-to-app.sh` → `alert()` → SMTP, `infra/backup/README.md` §5), so
   what this step tests is the part no test can: that `ALERTS_EMAIL` is right, that the
   SMTP provider accepts us, and that the mail is not sitting in a spam folder. The relay
   prints `host_alert delivered …` to the unit's journal when the transport accepted the
   message; **that line is not proof of receipt** — go and look at the inbox.
   If no message arrives, record the drill as **PARTIAL** with the reason "detection
   verified, delivery not confirmed". A detector nobody hears is not detection.
6. **Break the SCHEDULE, not the backup** — the failure `OnFailure=` cannot report,
   because nothing runs to fail. On the scratch host:
   `systemctl stop calevate-basebackup.timer`, then run `scripts/backup/backup-health.sh`.
   **Expected:** `backup_timer_inactive`, naming the unit. Re-arm it afterwards.
   Then, still on the scratch host, backdate the health heartbeat
   (`date -d '6 hours ago' +%s > /var/lib/postgresql/.calevate-health-heartbeat`) and run
   the check again: **expected** `backup_health_gap` with a `gap_s` of about 21600.
   **UNVALIDATED where it matters most:** the property names this reads from
   `systemctl show` were never exercised against a live systemd (README §9). If a healthy
   host reports `backup_timer_not_firing`, suspect the timestamp format before suspecting
   the timer — and fix the parser here, in the drill, which is what the drill is for.
7. **Write down what is still uncovered**, in the record, every quarter, so it stays a
   decision rather than a habit. Steps 1–6 all run inside the failure domain they watch;
   step 8 is the only one that does not.
8. **Prove the dead man is alive — BOTH halves.** This is the check that reports by not
   running, so a drill that only proves it can ping proves nothing: an always-red check
   and an always-green one are equally useless, and the failure mode of this control is
   silence that nobody notices. Do it in this order, **on the production host**, because
   the thing being tested is that host's URL, egress and the vendor check it feeds — a
   scratch host does not have any of the three.

   a. **It fires when things are healthy.** With the chain green, run
      `sudo -u postgres scripts/backup/heartbeat.sh` and confirm the vendor dashboard
      shows a ping received within seconds. Exit 78 means the URL is not configured on
      this host and the dead man is not armed at all (OPERATIONS §8's gate).
   b. **It goes RED when the pings stop.** Stop the health timer
      (`systemctl stop calevate-backup-health.timer`), then leave it stopped for the
      period plus the grace time (15m + 1h) and confirm the notification actually reaches
      the operator — the same "look at the inbox, not at the exit status" rule as step 5,
      and the only proof that the vendor's notification channel is configured to a person
      who exists. **Re-arm the timer immediately afterwards** and confirm the check
      returns to green on the next run.
   c. **It stays silent for a FAILING run** — the asymmetry the whole design rests on.
      With the timer re-armed, break a check (step 6's `systemctl stop
      calevate-basebackup.timer` is enough), run `scripts/backup/backup-health.sh` by
      hand, and confirm the vendor shows **no new ping** from that run while the email
      alert does arrive. If a failing run pings, the dead man has been converted into a
      "this script ran" indicator and will sit green through a completely broken chain —
      stop and fix that before continuing.

   Also record the vendor's configured period and grace, because they are the alarm's
   real thresholds and they live outside this repository: a check quietly re-created at a
   24-hour period is a dead man that sleeps through a whole day of missing backups.

## 8. Clean up — the scratch database is a full copy of everyone's personal data

```sh
dropdb calevate_restore
rm -rf <scratch PGDATA> ./restore/
# Destroy the VM if it was created for this. It contains unredacted phone numbers,
# transcripts and leads, and it is not covered by any retention policy row.
```

- [ ] Scratch database dropped, scratch `PGDATA` removed, decrypted dump deleted.
- [ ] Drill VM destroyed.
- [ ] Secrets removed from the drill shell; shell history discarded.
- [ ] Any credential created for the drill revoked.

Leaving a drill VM running is the most likely way this exercise causes the breach it is
meant to protect against.

## 9. Record the result

Commit the filled template to `docs/evidence/restore-drill-<YYYY>-Q<N>.md`. It contains no
personal data and no credential by construction — ids, counts, durations and outcomes only.
Reference it from the incident/ops review.

```markdown
# Restore drill — <YYYY> Q<N>

- Date (IST): 
- Run by: 
- Chain exercised: A (wal-g PITR from R2) | B (offsite encrypted dump)
- Source alternation correct vs previous drill: yes | no — <why>

## Target
- Recovery target (as written into recovery_target_time): 
- Expected counts recorded before restore: calls / leads / usage_events / alembic head

## Measured
- RTO (T0 → all §6 checks green): ___ minutes   (target 4h — OPERATIONS §5)
- RPO achieved: ___    (measured as: replay gap | dump age)
- Base backup age used: ___
- Restored database size: ___

## Verification (database-restore.md §7)
- [ ] 7.1 cluster sound
- [ ] 7.2 alembic head matches expectation
- [ ] 7.3 data stops at the target, nothing after
- [ ] 7.4 known record present by id: <id>
- [ ] 7.5 RLS forced on every tenant-scoped table; `pytest -k rls` green
- [ ] 7.6 amcheck clean (MANDATORY in a drill)
- [ ] single-table restore proved
- [ ] a recording referenced by a restored row is readable from object storage
- [ ] secrets-manager retrieval of the age identity / libsodium key succeeded (§1)

## Detection test (§7)
- Induced failure: 
- Alert code observed: 
- Time to alert: ___ minutes
- Alert **received in the operator's inbox**: yes | no — <what was wrong>
- Schedule test: `backup_timer_inactive` observed: yes | no
- Gap test: `backup_health_gap` observed, gap_s ≈ ___ : yes | no
- `systemctl show` output parsed correctly (README §9's unvalidated assumption): yes | no — <correction made>

## External dead man (§7.8 — D-54)
- Vendor check period / grace as configured: ___ / ___   (expected 15 min / 1 hour)
- (a) healthy run pinged, vendor registered it: yes | no
- (b) check went RED after pings stopped, and the notification **reached a human**: yes | no — <what was wrong>
- (c) a FAILING health run produced NO ping (the asymmetry holds): yes | no
- Timer re-armed and check back to green: yes | no
- Still uncovered: the monitoring vendor itself being down (accepted, D-54): yes

## Erasure re-application (database-restore.md §8)
- Completed deletion_requests after the target: ___
- Re-applied through the compliance path: yes | n/a

## Result
**PASS | PARTIAL | FAIL** — <one sentence>

## Corrections made to the runbooks
- <every step of database-restore.md that was wrong, and what it now says>

## Findings and follow-ups
- <issue> → <owner> → <ticket / decision-log entry>

## Cleanup confirmed
- [ ] scratch database and PGDATA destroyed
- [ ] drill VM destroyed
- [ ] drill credentials revoked
```

**PASS requires all of:** every §6 check green, RTO inside 4 hours, the detection test
firing **and arriving in a human's inbox**, the schedule and gap tests firing, all three
parts of the dead-man test in §7.8 passing, and the cleanup complete. Anything less is PARTIAL or FAIL — and a PARTIAL with a
named follow-up is a good drill. A PASS recorded over a skipped check is worse than no
drill, because next quarter someone will read it and believe it.
