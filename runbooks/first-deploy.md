# Runbook — the first deploy onto a fresh VPS

**For:** an operator who has never seen this repository, standing in front of an empty
Hostinger India VPS (D-180), with the domain and the vendor accounts already bought.

**Read this whole file before typing anything.** Two steps must happen in an order that is
not the obvious one — the database roles (step 4) and the TLS certificates (step 9) — and
getting either wrong is expensive to undo.

> **STATUS — read it, it changes how you work.** No part of this has run on a real VPS.
> Every command below was executed during the D-188 readiness audit
> (`docs/evidence/deploy-readiness.md`) against a scratch database, a local Redis and a
> containerised nginx, EXCEPT the ones needing a host, a domain or a vendor account —
> those are marked **[unrun]**. Treat this as a careful first draft that has been tested
> where testing was possible, and **do the first deploy attended**.

**Budget half a day.** Most of it is waiting on DNS and reading output.

---

## 0. What you need in hand before you start

Nothing below can be improvised, and each is somebody else's to provide:

- [ ] Root or sudo on a VPS running **Ubuntu 24.04 LTS**, sized by DEPLOYMENT §2b.
      The STARTER profile is **1 vCPU / 4 GB / 50 GB** and is what a launch and the first
      client need; §2a's ≥4 vCPU is the PRODUCTION profile, for 250 concurrent in-flight
      deliveries, and Hostinger resizes in place when §2b's trigger fires. On the starter,
      two §2b settings are load-bearing before you begin: **4 GB of swap** (not the §2
      baseline's 2 — `next build` peaks over 2 GB and the image is built on the box) and
      **`DB_POOL_SIZE=6`** (not the default 16 — §2a's pools assume 7 processes; you run 3).
      24.04 rather than 22.04: it ships the Python 3.12 the host scripts need, and it is the
      only archive the restore drill has ever been exercised against (DEPLOYMENT §1).
- [ ] `calevate.tech` in a Cloudflare account you control.
- [ ] Cloudflare R2: a recordings bucket, **and a separate backup bucket with its own
      scoped token**. One token must not be able to do both jobs (DEPLOYMENT §7).
      **Create each one with an explicit LOCATION HINT of `apac` — there is no second
      chance** (D-450). R2 honours a hint only at the FIRST creation of a bucket NAME and
      reuses the original placement if you delete and recreate it, so the only undo is a
      bucket with a DIFFERENT name plus a copy of every object. Left unset, the permanent
      home of every Indian call recording — and of the database backups, which hold every
      phone number and transcript in the product — becomes a property of which VPN exit
      you happened to be on. In the dashboard it is "Create bucket" → **Location** →
      choose a region instead of leaving *None*. The full argument, both buckets, and why
      a hint is placement and NOT residency: `infra/README.md` §5 item 2.
- [ ] A **non-Cloudflare** offsite target for the nightly dump — B2, S3 or a Hetzner
      Storage Box. The edge and the WAL archive are already the same vendor; this copy is
      the one that survives a Cloudflare account event.
- [ ] A secrets manager holding, generated there and never typed from memory:
      `PLATFORM_KEK`, the two Postgres role passwords, `AUDIT_CHAIN_SECRET`,
      `IDEMPOTENCY_SCOPE_SECRET`, `IMPERSONATION_GRANT_SECRET`.
- [ ] (Optional, but alerts reach nobody without it) a Resend account with a **verified
      sender domain**, and a Sentry project DSN. **If the Sentry ORGANISATION does not
      exist yet, choose its region deliberately rather than accepting the default**
      (D-451, OPERATIONS §2 gate 38): Sentry runs two and only two data regions — US
      (Iowa) and EU (Frankfurt), no India — the choice is made at organisation creation,
      it is baked into the DSN host (`o<org>.ingest.sentry.io` vs
      `o<org>.ingest.de.sentry.io`), and moving means a new organisation, a new DSN and
      the loss of every issue and alert rule behind it. Nothing in this repository can
      detect it or constrain it, so this line and that gate are the only places it is
      owned. It decides where our STACK TRACES live, not where a transcript goes — hard
      rule 6 keeps personal data out of Sentry at the source either way. Record the region
      you picked in the decision log entry for D-451.

Generate a 32-byte key like this — the same command for all of them:

```sh
python3 -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

---

## 1. Host baseline

Follow DEPLOYMENT §2. The parts people get wrong:

```sh
# nginx MUST be >= 1.25.1. Ubuntu 22.04 ships 1.18 and 24.04 ships 1.24, and BOTH are
# too old: infra/nginx/ uses the standalone `http2 on;` directive, which appeared in
# 1.25.1. On an older nginx `nginx -t` says `unknown directive "http2"` and NO server
# block loads — the whole edge, not one vhost. Add nginx.org's repository:
#   https://nginx.org/en/linux_packages.html#Ubuntu
nginx -v          # must print 1.25.1 or newer before you go on

docker compose version    # v2.24+
```

Also from §2, and each one is a thing that silently does not happen if you skip it:
2GB swap in `/etc/fstab`; `systemctl disable --now redis-server` (Redis lives only in
compose); remove `sites-enabled/default`; ufw 22/80/443; fail2ban; unattended-upgrades;
`systemd-timesyncd`.

> **ufw does not contain Docker.** Published container ports are written into
> `nat`/`FORWARD`, upstream of the `INPUT` chain ufw filters. Every `ports:` line is a
> hole in the firewall regardless of your ufw rules. This is why `compose.prod.yml`
> publishes redis nowhere and binds api and voice-runtime to `127.0.0.1:` explicitly.

**Python on the host: you need it, despite what DEPLOYMENT §2 used to say.** Not for the
services — those all run from the image — but `scripts/backup/notify.sh` defaults its
alert sink to `alert-to-app.sh`, which needs `$ROOT/.venv/bin/python` and **exits 78
without it**. Skip this and every backup alarm reaches journald and nobody else. Install
Python 3.12 and `uv`, and run `uv sync --all-packages` in the deploy root at step 3.

---

## 2. Postgres, and the two roles — **do this BEFORE the first migration**

Migration `05bba2f3c19c` contains `CREATE ROLE calevate_app LOGIN PASSWORD 'calevate_app'
… IF NOT EXISTS`. That password is published in this repository. **If the role does not
already exist when migrations run, your production app role's password is a string
anybody can read.** The `IF NOT EXISTS` guard makes the migration safe only for someone
who went first.

The role NAME must be exactly `calevate_app` — it is hardcoded in that migration's
`GRANT`s. Only the password comes from you.

```sh
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE calevate      LOGIN PASSWORD '<owner-password-from-secrets-manager>'
    NOSUPERUSER NOCREATEROLE CREATEDB;
CREATE ROLE calevate_app  LOGIN PASSWORD '<app-password-from-secrets-manager>'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE calevate OWNER calevate;
SQL

# PostgreSQL 15+ no longer grants CREATE on `public` to PUBLIC, so without this the app
# role cannot even resolve the schema.
PGPASSWORD='<owner-password>' psql -h 127.0.0.1 -U calevate -d calevate -v ON_ERROR_STOP=1 \
  -c "GRANT ALL ON SCHEMA public TO calevate_app;"
```

Then edit `postgresql.conf` / `pg_hba.conf` and restart **once**:

- `max_connections = 200` — §2a's budget totals ~101 against a default of 100.
- `listen_addresses` must include the Docker bridge gateway.
- `pg_hba.conf` must admit `172.16.0.0/12` with `scram-sha-256` (containers reach the
  host database over the bridge).

**Verify before going on** — `rolbypassrls` must be `f`, or hard rule 1's tenant isolation
is not real:

```sh
sudo -u postgres psql -d calevate -c "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'calevate%';"
```

---

## 3. Clone, and place the two env files by hand

```sh
sudo mkdir -p /var/www/calevate && sudo chown "$USER" /var/www/calevate
git clone <repo> /var/www/calevate
cd /var/www/calevate
uv sync --all-packages     # for the backup alert relay only (step 1); NOT for the services
```

**`/var/www/calevate/.env`** — no script will ever write this, and the deploy aborts
without it. The eight bootstrap keys plus the object-store credentials plus the three HMAC
secrets:

```sh
APP_ENV=prod
# As the CONTAINERS see them. Postgres is on the HOST (D-26).
DATABASE_URL=postgresql+psycopg://calevate_app:<app-pw>@host.docker.internal:5432/calevate
ALEMBIC_DATABASE_URL=postgresql+psycopg://calevate:<owner-pw>@host.docker.internal:5432/calevate
REDIS_URL=redis://redis:6379/0
PLATFORM_KEK=<32 random bytes, base64>
PLATFORM_KEK_RETIRED=
OBJECT_STORE_ENDPOINT=https://<account>.r2.cloudflarestorage.com
OBJECT_STORE_BUCKET=<recordings bucket>
# botocore reads these itself; the deploy ABORTS without the first two.
AWS_ACCESS_KEY_ID=<r2 key id>
AWS_SECRET_ACCESS_KEY=<r2 secret>
AWS_REGION=auto
# Required outside `local`. AUDIT_CHAIN_SECRET is needed by step 7 — see the note there.
AUDIT_CHAIN_SECRET=<32 random bytes>
IDEMPOTENCY_SCOPE_SECRET=<32 random bytes>
IMPERSONATION_GRANT_SECRET=<32 random bytes>
```

```sh
chmod 600 .env
```

**`/var/www/calevate/apps/web/.env.local`** — a second file, and it is not optional. Next
reads `.env*` from the PACKAGE directory and inlines every `NEXT_PUBLIC_*` at **build**
time. A missing key here does not fail the build; it compiles to the empty string and
ships a console whose API base is the visitor's own machine, behind a page that answers
the health poll 200. Copy `apps/web/.env.example` and fill it.

**Check the `.env` before you deploy with it.** This is the only guard that looks at
values, and it prints every problem at once and never prints a value:

```sh
uv run python -m scripts.check_deploy_env --env-file .env
```

Expect `DEPLOY ENV: OK`. If it says `dsn_host_unreachable_from_container` you used
`localhost` where you needed `host.docker.internal`.

---

## 4. Export the four nginx variables

These are hostnames and paths, not secrets. They are deliberately not in `.env` — the
deploy script never sources it — so they live in your shell. **Export them before the dry
run**, or it refuses (which is the point; they used to be discovered at the last step,
after migrations and all three container swaps):

```sh
export ROOT_DOMAIN=calevate.tech
export TLS_LIVE_DIR=/etc/letsencrypt/live/calevate.tech
export ORIGIN_CERT_PATH=/etc/ssl/calevate/origin.pem
export ORIGIN_KEY_PATH=/etc/ssl/calevate/origin.key
```

---

## 5. Build the image once, by hand, and time it — **[unrun]**

DEPLOYMENT §4d item 2, and it has never been done anywhere. Do it separately from the
deploy so that if it OOMs you learn that and nothing else:

```sh
docker compose -p calevate -f compose.prod.yml build api
```

Then **prove the image is not empty** — this is the exact defect D-188 found, and it
exited 0 and looked like a cache hit:

```sh
docker run --rm calevate/app:local sh -c 'ls /app/.venv/lib/python3.12/site-packages | wc -l'
```

**Expect 120+. If it prints 3, the build is broken** and nothing downstream will work.

---

## 6. First deploy — dry run first, then attended

```sh
scripts/vps-deploy.sh --dry-run --all
```

The dry run is a real preflight, not a plan printout: it runs both refusal phases. Read
what it says it would do, and only then:

```sh
scripts/vps-deploy.sh --all
```

Leave `NGINX_AUTO_RELOAD` unset on this first run — the deploy renders the nginx config
and prints the install commands rather than touching `/etc/nginx`. Step 9 installs it.

It will take a while: a serial build, then migrations, then the seed, then redis, then
`workers → api → voice-runtime` one at a time with a health wait on each. If it fails, it
stops there and runs nothing after — read the banner and go to `runbooks/deploy-failed.md`,
which is ordered by the step that failed.

---

## 7. Create the first administrator — **without this nobody can log in**

`admin_users` is the allowlist the entire admin realm resolves against, and nothing else
in the repository ever inserts a row. After `alembic upgrade head` the table is empty and
every admin request 403s: no organization creatable, no platform setting writable, no
vendor credential storable. It fails closed, so this is not a security hole — it is a
deployment with no way in.

**Run it through the image.** DEPLOYMENT §2 puts no Python on the host for the app, and the
`uv run` form that used to be documented cannot execute there:

```sh
docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  --entrypoint python api -m scripts.bootstrap_admin \
  --email you@yourdomain.example --role superadmin --name "Your Name"
```

> **If it stops with `hmac_key_missing`, you skipped `AUDIT_CHAIN_SECRET` in step 3.**
> Creating the first operator writes an audit row, and the hash chain refuses to sign
> without a key outside `local`. That key is normally set from the ops console — and on a
> fresh host the console **cannot** be the answer, because reaching it needs an operator
> and creating an operator needs the key. So it comes from `.env`, which beats the store by
> design. Add it and re-run; re-running is safe.

**Expected output** (verified during the D-188 audit, against a deployment with no mail
provider configured):

```
created admin_users row 0…  (superadmin)
email sent: NO — use the link below
expires:    …
Setup link (single use):
https://admin.calevate.tech/bootstrap?token=…
```

**`email sent: NO` is fine and expected before Resend is configured.** The link is printed
deliberately, because the mail credentials are themselves stored by an operator, in the
console. Open it, set a password, and you are an administrator.

- The link is **single use** and expires in **60 minutes**. If it expires, run the command
  again — that re-issues a fresh link for the same row and retires the old one.
- Once any operator holds a password the script **refuses** with `already_bootstrapped`,
  and there is no `--force`. Add further operators from the console.
- Note the link points at `https://admin.calevate.tech`, so you need step 9 finished before
  you can open it. Do steps 8–9 first if you would rather not wait on a 60-minute clock.

---

## 8. Health check before you point DNS at it

```sh
curl -fsS http://127.0.0.1:8000/healthz/live    # {"status":"ok","service":"api"}
curl -fsS http://127.0.0.1:8000/healthz         # 200 = database and Redis both answer
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz/ready
```

**`/healthz/ready` answering 503 here is correct**, not a failure: readiness is the
go-live gate and it stays red until the vendor configuration is in the ops console. Sign in
to `admin.calevate.tech/ops/config` (after step 9) and fill it — **Platform configuration**
in the sidebar, which only the superadmin sees; `GET /v1/ops/config` shows every key with
its source, which is the pre-launch audit OPERATIONS §8 asks for.

---

## 9. nginx, TLS and Cloudflare — **in this order, it is not the obvious one** — **[unrun]**

The obvious order deadlocks: `certbot certonly --webroot` needs nginx serving
`/.well-known/acme-challenge/`, that location lives in `calevate-site.conf`, and that file
references `${TLS_LIVE_DIR}/fullchain.pem` in all three server blocks — so `nginx -t`
fails before a certificate can be obtained. **Follow DEPLOYMENT §9.5a step by step**; it is
written out precisely because this trips everyone.

Two things to carry into it:

- **Use `certbot certonly --webroot`, never `certbot --nginx`** — the latter rewrites
  templated config.
- **Attach the renewal deploy hook at issuance**, in the same command. Without it a renewed
  certificate is a new file the running server has never read, and the next reload is
  whenever logrotate or a deploy happens to run. Verify with
  `grep renew_hook /etc/letsencrypt/renewal/<lineage>.conf`, then
  `certbot renew --dry-run --run-deploy-hooks` — a plain `--dry-run` does **not** run
  deploy hooks.

Then in Cloudflare: four A records to the VPS IP, **proxied (orange)**, SSL mode **Full
(strict)** only — Flexible causes a redirect loop with the port-80 301. No stray AAAA.

Finally enable the automatic install:

```sh
export NGINX_AUTO_RELOAD=1
scripts/vps-deploy.sh nginx
```

---

## 10. Day two — the one-time installs that decide whether you survive a reboot

Each of these is installed once and never again, and if you miss one the failure appears
weeks later:

- [ ] `pm2 startup` **and** `pm2 save` — otherwise `web` does not come back after a reboot.
      (The four containers do: `restart: unless-stopped`.)
- [ ] The privileged scripts and sudoers policy — `infra/privileged/README.md` §2.
      **sudo silently ignores any file in `/etc/sudoers.d` whose name contains a dot**, so
      a policy installed under the wrong name is not a policy. Check with
      `sudo -l -U <deploy-user>`.
- [ ] The daily hygiene timer and the journald cap — `infra/hygiene/`. Without it the disk
      fills and takes Postgres with it.
- [ ] The backup units — `infra/backup/systemd/`. See below.
- [ ] The GitHub Actions runner, and only then set the repo Variable
      `VPS_DEPLOY_ENABLED=true`. **Enable CD last**, after one full manual deploy has
      succeeded (DEPLOYMENT §4d item 6).

---

## 11. Backups — and what you actually have on day one

Install `infra/backup/` per its README: the wal-g WAL archiving drop-in (which needs a
PostgreSQL **restart**, because `archive_mode` is not reloadable), the nightly base backup,
the nightly offsite dump to the non-Cloudflare target, and the 15-minute health timer.

**Then run the drill.** `runbooks/backup-restore-drill.md`, and commit its evidence to
`docs/evidence/`.

> **Until that drill has run, you do not have backups — you have backup code.**
> OPERATIONS §8's "backups verified" is earned by the drill and by nothing else. As of the
> D-188 audit it has never run: `bash -n` passes on all twelve shell scripts and
> `systemd-analyze verify` finds no directive errors in the nine units, but that is syntax,
> not a restore. A backup nobody has restored from is a hypothesis.

Also confirm alerts leave the box, or none of the above tells you when it breaks:

```sh
scripts/backup/notify.sh probe "delivery test"
```

The mail must land in a real inbox. Local acceptance is not receipt — this is OPERATIONS
§2 gate 15(c), and it needs `EMAIL_PROVIDER`, `RESEND_API_KEY`, `ALERTS_EMAIL` and a
**verified sender domain**. An unverified sender is refused per send with a 403 that
appears as `email_sender_rejected`.

---

## If something goes wrong

| Symptom | Go to |
|---|---|
| `DEPLOY FAILED` banner | `runbooks/deploy-failed.md`, ordered by the step that failed |
| Backup alarm, or silence where one should be | `runbooks/backup-heartbeat-silent.md` |
| Need to restore | `runbooks/database-restore.md` |
| Site up, calls not arriving | `runbooks/calls-stopped.md`, `runbooks/webhook-delivery-failures.md` |

**Do not** deploy from an edited tree (the preflight refuses, correctly), add a compliance
bypass "for testing", or weaken a Hard Rule to make something start.
