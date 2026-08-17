# infra/hygiene/

The daily host clean. `docs/DEPLOYMENT.md` §7 listed this as "still unbuilt" for as long as
that section has existed; it is built now, and this file is the authority on what it does.

> **Nothing here has been installed on a host.** No VPS exists (`infra/README.md`,
> `docs/evidence/raghava-deploy-teardown.md` §9.1 item 1). `systemd-analyze verify` has not
> been run against these units because there is no systemd in the environment that wrote
> them. Read §5 before believing any of it works.

---

## 1. What is here

```
infra/hygiene/systemd/calevate-hygiene.service   the unit
infra/hygiene/systemd/calevate-hygiene.timer     daily, 19:00 UTC (00:30 IST), Persistent
infra/hygiene/journald-cap.conf                  journald drop-in — the cap that replaces a vacuum
scripts/deploy/host-hygiene.sh                   the job itself; its header lists every
                                                 step it deliberately does NOT do
scripts/deploy/docker-reclaim.sh                 the Docker reclaim primitives, shared with the deploy
scripts/deploy/host-lock.sh                      the mutex, shared with the deploy
```

The split matches `infra/backup/`: units under `infra/`, executables under `scripts/`. It
is not decoration — a unit file and the script it runs have different install destinations
and different owners on the host.

## 2. Why a systemd timer and not `/etc/cron.daily`

The same argument `infra/backup/README.md` makes, and it is a deliberate departure from the
reference playbook, which installs its cleanup as `/etc/cron.daily/vps-cleanup-<CLIENT_ID>`:

- cron's failure mode is mail to a mailbox nobody reads. `OnFailure=` gives a failed run
  somewhere to go.
- `Persistent=true` catches up a day missed to a reboot instead of skipping it in silence.
- `systemd-analyze verify` checks the unit before it ever fires.
- `run-parts` — which is what runs `/etc/cron.daily` — **silently skips any filename
  containing a dot**, so the reference's installer produces a cleanup job that never runs
  and never says so for any client id with a `.` in it (teardown §8.11). A unit file has no
  such rule.

## 3. The three corrections the teardown demanded

`docs/evidence/raghava-deploy-teardown.md` §9 row 21 names three, and all three are load-
bearing:

**(a) It never touches the runner's `_work`.** The reference does `rm -rf
"$RUNNER_DIR/_work"/*` and `_tool/*` from cron (§8.6), unsynchronised with GitHub Actions:
a job in flight at 06:25 has its staging area deleted underneath it. Ours touches neither.
`_diag` — diagnostic logs, unbounded, never read back — is trimmed by age and is the only
thing under the runner directory this job knows about. `tests/host_hygiene_test.py` fails if
`_work` or `_tool` ever appears outside a comment in the script.

**(b) It holds the lock the deploy holds.** `scripts/deploy/host-lock.sh` defines one lock
path and both callers compute it identically. The interleaving this prevents is not
hypothetical even with (a) fixed: `docker image prune` and `docker builder prune` are
host-global, and a prune racing a `docker build` can remove the layer the build is about to
reference — the build then fails with a message about a missing parent layer that names
neither the prune nor the timer. If a deploy holds the lock for ten minutes, this run
**skips the day and exits 0**: hygiene is daily and idempotent, so a skipped run costs one
day of dangling images, while a hygiene run racing a build costs the build.

**(c) Prunes are scoped to our compose project.** `docker container prune` with no filter
removes every stopped container on the box; this host also runs the dev compose project
(`calevate-dev`) during an operator's debugging session. Dangling *images* are not scoped,
because a dangling image belongs to nobody by definition.

## 4. Idempotence, and what "failed" means

Every step is a prune (a no-op when there is nothing to prune), a truncation of a log this
host owns, or a read. Nothing is order-dependent and nothing carries state between runs,
which is what makes `Persistent=true` safe.

Two different signals, kept apart deliberately:

| Signal | Means | Reached how |
|---|---|---|
| unit exits 1 → `OnFailure=` | a step did not complete | the script collects failed step names and exits 1 |
| `disk_pressure` / `disk_below_build_floor` alert | the host needs more disk | `scripts/backup/notify.sh`, from a run that otherwise succeeded |

Collapsing them would send two mails about one event and one mail about two. A host that
needs disk and a job that broke have different first actions.

The `OnFailure=` target is `calevate-backup-alert@%n.service` — the existing relay, reused
rather than copied. **Its detail text says "a backup systemd unit terminated abnormally",
which is inaccurate for this caller.** It is reused anyway: the payload carries `unit=%i`,
which names `calevate-hygiene.service` exactly, and a second alert unit would be a second
delivery path with its own dedupe window and its own rate limit — the drift `notify.sh`'s
own header warns about. Flagged here rather than silently forked.

The disk alerts ride the same seam and therefore carry `failure_stage=HOST_BACKUP`. That is
not a mislabel: a full disk on this VPS takes the backup chain out first and hardest —
`pg_wal` stops draining, unarchived segments pile up, and PostgreSQL stops accepting writes,
which is why `scripts/backup/backup-health.sh` check 4 already watches `pg_wal` growth.

## 5. What a human must do before any of this is real

1. **Install the unit and timer.**
   ```sh
   sudo install -o root -g root -m 0644 infra/hygiene/systemd/calevate-hygiene.service \
       infra/hygiene/systemd/calevate-hygiene.timer /etc/systemd/system/
   sudo systemd-analyze verify /etc/systemd/system/calevate-hygiene.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now calevate-hygiene.timer
   ```
   *Pass condition*: `systemctl list-timers calevate-hygiene.timer` shows a next elapse.
2. **Check the user and paths in the unit against the host.** `User=calevate`,
   `Environment=HOME=/home/calevate` and `WorkingDirectory=/var/www/calevate` are written
   for the account and layout `DEPLOYMENT.md` §2 describes. A different deploy user means
   editing three lines here, the `DEPLOY_USER` constant in
   `infra/privileged/sbin/calevate-nginx-apply`, and the sudoers policy — all three, or
   none.
3. **Install the journald cap** (`infra/hygiene/journald-cap.conf` → its own header says
   where) and restart `systemd-journald`. *Pass condition*: `journalctl --disk-usage`
   reports a figure at or under 512M and stays there.
4. **Run it once by hand, attended**: `scripts/deploy/host-hygiene.sh`. *Pass condition*: it
   prints a disk line, every step either does something or says why it skipped, and it exits
   0.
5. **Prove the lock**: start a `--dry-run` deploy in one shell and the hygiene script in
   another; the second must print that a deploy holds the lock and exit 0. This is the one
   property no test in the repository can prove, because it needs two processes and a real
   filesystem lock.
6. **Confirm the alert seam reaches somebody.** The disk alert goes through
   `scripts/backup/notify.sh`, which needs `EMAIL_PROVIDER` + `ALERTS_EMAIL` configured
   (DEPLOYMENT §6). Until then it reaches journald and nothing else, and says so.
