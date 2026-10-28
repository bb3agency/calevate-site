# Backup setup on the VPS — step by step

This turns `infra/backup/README.md` §8 into commands for the production VPS. Read that
README for the design (retention, DPDP, and the risk §3 records). **Production keeps ONE
chain, wal-g to Cloudflare R2 (D-927, founder 29 Oct 2026).** The offsite dump is not set
up: skip Phase 0 items 2 and 4 and Phase 6, and install only the units Phase 8 names.
Nothing here has been run yet. On 10 Oct 2026 the VPS had only `calevate-hygiene.timer`; no backup timer existed,
so the only backups were manual `pg_dump`s.

**What you end up with**

| Job | When (IST) | What it does |
|---|---|---|
| WAL archiving | continuous, at least every 5 min | every database change is pushed to the R2 backup bucket (point-in-time restore) |
| `calevate-basebackup.timer` | 02:30 nightly | full encrypted base backup to R2, verified page by page; prunes past 35 days |
| `calevate-backup-health.timer` | every 15 min | four checks plus the timers themselves; on success pings an external dead man |

**Rules while doing this:** run as `d_user`, one block at a time, read each result before the
next. Never paste a key, token, URL or password into chat, a ticket or a commit. Generate
secrets on your own machine. If a command's output surprises you, stop.

---

## Phase 0 — accounts and keys (browser and your own machine, not the VPS)

1. **R2 backup bucket** (Cloudflare dashboard → R2 → Create bucket). Name it e.g.
   `calevate-backups`, a NEW name, separate from the recordings bucket. **Location: choose
   Asia-Pacific (APAC) at creation** — R2 honours the hint only the first time a name is
   created. Then R2 → Manage API tokens → Create token: **Object Read & Write, this bucket
   only**. Note the Access Key ID, Secret Access Key and your account id (in the R2
   endpoint URL) in your password manager.
2. ~~Offsite provider~~ — **skip (D-927).** No offsite copy is kept.
3. **wal-g encryption key** (on your machine): `openssl rand -base64 32` — exactly 32 bytes,
   wal-g's libsodium key. Save it in the password manager AND one offline copy. Losing it
   loses every R2 backup.
4. ~~age key pair for the offsite dump~~ — **skip (D-927).**
5. **External dead man**: a Healthchecks.io check, **period 15 minutes, grace 1 hour**,
   notifying the same email as `ALERTS_EMAIL`. Its ping URL is a credential.

---

## Phase 1 — inspect the VPS

```sh
lsb_release -ds; uname -m
psql --version; sudo -u postgres psql -Atc "SHOW server_version" -c "SHOW data_directory" -c "SHOW data_checksums" -c "SHOW config_file"
ls /etc/postgresql/16/main/conf.d/ 2>/dev/null; grep -n "^include_dir" /etc/postgresql/16/main/postgresql.conf
df -h /var/lib/postgresql /tmp
for t in jq age rclone logger wal-g uv python3.12; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
sudo -u postgres test -r /var/www/calevate/scripts/backup/basebackup.sh && echo "postgres can read the scripts" || echo "postgres CANNOT read /var/www/calevate"
```

Send me the output. Points to read:
- `data_directory` should be `/var/lib/postgresql/16/main` (the units assume it). If not, the
  units' `PGDATA` needs changing first.
- `data_checksums` `off` means `--verify` verifies nothing until checksums are enabled on a
  stopped cluster (`pg_checksums --enable`) — a separate, planned downtime. Backups still
  work without it.
- `include_dir = 'conf.d'` must be present for the drop-in in Phase 4.
- If postgres cannot read `/var/www/calevate`, the units cannot run the scripts — fix the
  directory permissions (read + execute for others on the path) before Phase 8.

---

## Phase 2 — install the tools

```sh
sudo apt-get update && sudo apt-get install -y jq
```

**wal-g** — list the latest release's assets, pick the PostgreSQL build for this Ubuntu
release and CPU (from Phase 1), and check its published checksum if the release has one:

```sh
curl -s https://api.github.com/repos/wal-g/wal-g/releases/latest | jq -r '.tag_name, (.assets[].name | select(test("pg")))'
```

Then, with the exact asset name from that list (example name — confirm it):

```sh
cd /tmp && V=<tag> A=<asset name>.tar.gz
curl -fsSLO "https://github.com/wal-g/wal-g/releases/download/$V/$A" && sha256sum "$A"
# compare with the release's .sha256 asset if one is listed; then:
tar -xzf "$A" && sudo install -o root -g root -m 0755 wal-g-pg-* /usr/local/bin/wal-g && wal-g --version
```

`wal-g --version` must name the PostgreSQL build.

**Host Python for backup alerts.** The alert relay (`scripts/backup/app-python.sh`) runs the
app's alert code on the host. The services run in Docker, so the host has no venv, and
without one every backup alarm goes only to the journal (DEPLOYMENT, D-188). The host runs
Ubuntu 26.04, which ships no `python3.12`, so uv installs Python 3.12 itself — into
`/opt/calevate-python`, NOT uv's default under `/home/calevate/.local`, which postgres cannot
enter: there the relay exits 78 and every alarm reaches nobody (found on production, 29 Oct
2026). As `d_user`, then as `calevate`:

```sh
sudo install -d -o calevate -g calevate -m 0755 /opt/calevate-python
sudo -iu calevate
echo 'export UV_PYTHON_INSTALL_DIR=/opt/calevate-python' >> ~/.profile && . ~/.profile
cd /var/www/calevate && command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv python install 3.12
rm -rf .venv && ~/.local/bin/uv sync --frozen --all-packages
readlink -f .venv/bin/python        # must be under /opt/calevate-python
exit
```

The profile line keeps any later rebuild of `.venv` on that interpreter (a `uv sync` reuses an
existing compatible `.venv`; the deploy never runs one on the host). Then postgres must be
able to execute it: `sudo -u postgres /var/www/calevate/.venv/bin/python -c "print('ok')"`.

---

## Phase 3 — wal-g configuration

```sh
sudo install -d -o postgres -g postgres -m 0700 /etc/wal-g
sudo install -o postgres -g postgres -m 0600 /var/www/calevate/infra/backup/walg.json.template /etc/wal-g/walg.json
sudo editor /etc/wal-g/walg.json     # root edits; owner and mode stay postgres 0600
```

Replace each `<<SECRET:…>>` with the Phase 0 values (bucket name, access key id, secret,
account id, the wal-g key). Leave `AWS_REGION` as `auto`. Remove nothing else. Then:

```sh
sudo -u postgres jq . /etc/wal-g/walg.json >/dev/null && echo "valid json"
sudo grep -c '<<SECRET' /etc/wal-g/walg.json   # must print 0
sudo -u postgres wal-g --config /etc/wal-g/walg.json backup-list
```

`backup-list` must succeed and list nothing. This is the first proof that wal-g and R2 agree.

---

## Phase 4 — turn on WAL archiving (one Postgres restart)

The restart drops connections for a few seconds; do it at a quiet hour.

```sh
sudo install -o postgres -g postgres -m 0644 /var/www/calevate/infra/backup/postgresql-archiving.conf /etc/postgresql/16/main/conf.d/
sudo systemctl restart postgresql
sudo -u postgres psql -Atc "SHOW archive_mode" -c "SHOW wal_level"   # on / replica
sudo -u postgres psql -c "SELECT pg_switch_wal()"
sleep 20; sudo -u postgres psql -c "SELECT archived_count, last_archived_wal, last_archived_time, failed_count, last_failed_wal FROM pg_stat_archiver"
```

`archived_count` must move and `failed_count` stay 0. If `failed_count` rises, run
`sudo journalctl -u postgresql --since -10min` and send it to me.

---

## Phase 5 — first base backup, watched

```sh
sudo -u postgres env WALG_CONFIG_PATH=/etc/wal-g/walg.json wal-g backup-push /var/lib/postgresql/16/main --verify
sudo -u postgres wal-g --config /etc/wal-g/walg.json backup-list
```

Watch it: if it sits at high CPU with no progress for many minutes (wal-g issue #1639, seen
with R2 multipart), stop it with Ctrl-C and send me what it printed.

---

## Phase 6 — offsite dump: skipped (D-927)

Production keeps one chain. Nothing to do here; `infra/backup/README.md` §3 records the risk.

---

## Phase 7 — where backup alarms go

```sh
sudo install -d -o root -g postgres -m 0750 /etc/calevate
sudo install -o root -g postgres -m 0640 /dev/null /etc/calevate/alerts.env
sudo editor /etc/calevate/alerts.env
```

Put in it (values from the password manager; never the app's `.env`, see README §5):
`ALERTS_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
`BACKUP_HEARTBEAT_URL`, plus the four `Settings` needs to start: `APP_ENV=prod`,
`DATABASE_URL`, `REDIS_URL`, `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_BUCKET` (copied as
strings; nothing connects to them). Then prove delivery:

```sh
sudo -u postgres bash -c 'set -a; . /etc/calevate/alerts.env; set +a; exec /var/www/calevate/scripts/backup/notify.sh probe "delivery test"'
```

It must print `host_alert delivered`, and the mail must arrive. Remember: `SMTP_PASSWORD`
now lives in two places (console and this file) — rotate both together.

---

## Phase 8 — install and start the timers

```sh
cd /var/www/calevate
sudo install -o root -g root -m 0644 infra/backup/systemd/calevate-backup-alert@.service infra/backup/systemd/calevate-basebackup.service infra/backup/systemd/calevate-basebackup.timer infra/backup/systemd/calevate-backup-health.service infra/backup/systemd/calevate-backup-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/calevate-basebackup.service /etc/systemd/system/calevate-backup-health.service
sudo systemctl enable --now calevate-basebackup.timer calevate-backup-health.timer
systemctl list-timers 'calevate-*' --all
```

The offsite units (`calevate-dump-offsite.*`) are NOT installed (D-927), and the health
check does not expect them. Run the health check once by hand and read the result:

```sh
sudo systemctl start calevate-backup-health.service; journalctl -u calevate-backup-health.service --since -5min --no-pager | tail -n 30
t=$(systemctl show -p LastTriggerUSec --value calevate-basebackup.timer); echo "$t"; date -u -d "$t"
```

The first health run may raise `wal_verify_unparseable` — that is a parser question about
wal-g's JSON, not a backup failure (README §9). Send it to me rather than loosening anything.

---

## Phase 9 — protect the archive

R2 dashboard → the backup bucket → Settings → **Bucket lock**: a rule on the `postgres/`
prefix, **30 days**. Never "indefinite" (it cannot be removed). 30, not 35, so nightly
pruning never fights the lock.

---

## Phase 10 — prove a restore

Until a restore has worked once, these are backups we believe in, not backups we have.
Follow `runbooks/backup-restore-drill.md` on a scratch machine: restore last night's base
backup plus WAL to a point in time.

## Afterwards

Record in ROADMAP §6 the decisions README §8 step 12 names (35-day retention as a DPDP
commitment, the external heartbeat, the erasure certificate's backup clause).

---

## Moving Calevate to another server (not a backup task)

Backups protect against loss; a planned move does not need them. If you move servers:

1. Build the new server with DEPLOYMENT's steps (Docker, nginx and certificates, the repo, the
   `calevate` user, and the `.env` secrets copied by hand — never through chat or git).
2. On the old server, stop writes (pause outbound with the big red switch, or a maintenance
   window), then `sudo -u postgres pg_dump -Fc calevate -f /var/backups/calevate/move.dump`.
3. Copy the dump to the new server (`scp`), create the database and roles as DEPLOYMENT
   describes, then `sudo -u postgres pg_restore -d calevate --no-owner /path/move.dump` and run
   the deploy (it migrates to head).
4. Recordings and uploads live in the object-store bucket, not on the server: point the new
   server's `.env` at the same bucket; nothing to copy.
5. Point DNS at the new server, check `/healthz/ready`, place a test call, then switch the old
   server off.
6. Set up this runbook's backups on the NEW server (doing it before a move means doing it twice).
