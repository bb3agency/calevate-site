# Runbook — the backup heartbeat went silent (the dead man fired)

**What you received:** a notification from the external dead-man check (Healthchecks.io)
saying the backup heartbeat stopped arriving. Not an email from us. Ours are the alarms
that get SENT; this is the one that arrives because nothing was.

**What it means, exactly:** `scripts/backup/backup-health.sh` pings that check once every
15 minutes **and only when every backup check passed**. So the ping stops for one of four
reasons, and the notification cannot tell you which:

| Cause | What is actually wrong |
|---|---|
| A backup check is failing | The chain is broken. There should ALSO be an email (`HOST_BACKUP`) — if there is not, the mail path is broken too, which is cause 4 |
| The host is off, wedged, out of disk, or off the network | Nothing runs at all. This is the case the dead man exists for |
| systemd is not running, or the health timer was stopped/masked | Backups are unscheduled; the on-host schedule checks died with it |
| The ping cannot leave the host | Backups may be perfectly fine; egress, DNS, a rotated URL or the vendor is down |

**What it does NOT mean:** that data was lost. The heartbeat says *monitoring stopped*, not
*the database is gone*. Do not open `runbooks/database-restore.md` on the strength of this
alert alone — a restore is a much bigger event than the one you are probably in.

**Clock:** the grace time is 1 hour, so the silence began up to ~1h 15m before you were
told. The RPO promise is 15 minutes (OPERATIONS §5); if the cause turns out to be a broken
archive chain, assume the RPO has been missed for the whole window until you prove
otherwise.

---

## 1. Is the box alive? (30 seconds, and it rules out the worst case)

```sh
ping -c3 <vps-ip>
ssh <vps>            # if this works, causes 1, 3 and 4 remain
uptime               # a recent boot explains a gap that has already healed
df -h /var/lib/postgresql /var  # a full disk stops backups AND their alarms
```

**No SSH, no ping** → the host is down or off-network. That is cause 2, and it is a
hosting incident, not a backup incident: bring the box back (DEPLOYMENT §9), then come
back here — the heartbeat resumes by itself and the check goes green within 15 minutes.
While it is down, **there is no backup and no WAL archiving**, so record the outage window;
it is the exact window a restore could not reach past.

## 2. Ask the host what it thinks happened

```sh
systemctl status calevate-backup-health.timer calevate-basebackup.timer \
                 calevate-dump-offsite.timer
journalctl -t calevate.alert -t calevate.backup --since '-3h' --no-pager
```

- `Unit ... not found` / `masked` / `inactive` → cause 3. `systemctl enable --now` the
  timer, then find out who stopped it (a deploy that rewrote `/etc/systemd/system` is the
  usual answer — see `infra/backup/README.md` §5).
- Alert lines with `HOST_BACKUP` codes (`archive_stale`, `wal_chain_broken`,
  `no_base_backup`, `basebackup_failed`, `offsite_upload_failed`, …) → **cause 1: the
  chain is broken**. Fix that; the heartbeat is a symptom and will resume on its own.
  `infra/backup/README.md` §5 explains what each detector covers.
- `backup_heartbeat_undelivered` → **cause 4**: the backups are healthy and the ping is
  not getting out. Go to §3.
- `no BACKUP_HEARTBEAT_URL on this host` → the dead man is not armed at all on this host,
  and the page you received came from an OLD check that this host has stopped feeding.
  Restore the URL from the secrets manager (OPERATIONS §8).

## 3. The chain is fine and the ping is not leaving

```sh
sudo -u postgres /var/www/calevate/scripts/backup/heartbeat.sh; echo "exit=$?"
```

| exit | meaning | do |
|---|---|---|
| 0 | the ping went through just now | a transient network blip; confirm the vendor check went green and close it. If this repeats, note it — repeated blips at one time of day are a real network fault |
| 78 | `BACKUP_HEARTBEAT_URL` is not set/readable by `postgres` | re-inject it (repo `.env` or `/etc/calevate/alerts.env`, per `infra/backup/README.md` §5) |
| 69 | configured, undelivered | the printed reason distinguishes them: `ConnectError`/timeout = egress or DNS; `HTTP 404` = the check was deleted or the URL is stale — **create/rotate it and update the secret**; `HTTP 5xx` = the vendor is having an incident, check their status page and wait |

The output names the check as a digest (`check=abcd…`), never the URL — the URL is a
credential (anyone holding it can silence this alarm), so it is not printed, not pasted
into a ticket, and not committed. Rotating it means a new check on the vendor side, a new
secret, and nothing else.

## 4. Before you close it

- [ ] Confirm the vendor check has gone back to green — an alarm you silenced by fixing
      the SYMPTOM (e.g. pausing the check) is worse than the outage.
- [ ] If the cause was cause 1 or 2: was a nightly base backup or offsite dump missed?
      `journalctl -t calevate.backup --since '-2d'`. A missed night is not automatically
      re-run by `Persistent=true` unless the host was off at the scheduled time — check,
      and run `scripts/backup/basebackup.sh` by hand if the night was simply lost.
- [ ] If the silence lasted longer than the grace time by much, say so in the ops review:
      the grace is 1 hour precisely so that a page means "three runs in a row did not
      happen", and a long silence means the notification itself was slow or ignored.
- [ ] If this alert was FALSE (backups fine, ping fine, vendor flapped), record it. Two
      false pages and the next real one gets ignored — that is how a dead man dies, and
      the fix is to raise the grace time, not to mute the check.

## What this runbook cannot cover

The dead man is one check with one grace window, watched by one vendor. If **that vendor**
is down, nobody tells you anything at all — the same shape as everything it replaced, one
level out. That residual is accepted deliberately (D-54): the alternative is a second
monitor watching the first, which buys less than it costs for a single-operator platform.
The drill (`runbooks/backup-restore-drill.md` §7.8) is what keeps it honest, by proving
once a quarter that the check still turns red when the pings stop.
