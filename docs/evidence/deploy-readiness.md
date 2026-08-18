# Deploy readiness — can Calevate go onto a Hostinger India VPS today?

**Audit date:** 18 August 2026 · **Decision row:** D-188 · **Method:** every step below
was EXECUTED, not read. Where a step could not be executed it says so and is marked
UNVERIFIED rather than assumed.

---

## The verdict

> ## NO — it could not have deployed this morning, and three of the four reasons were
> ## ours. They are fixed. It can now go to a first attended deploy, and everything
> ## still standing between here and a live site is external.
>
> The single sentence that matters: **the production image shipped a virtualenv with
> three files in it and no Python package at all**, so the first deploy would have failed
> at `vps-deploy.sh` step 7 with `ModuleNotFoundError` — after the build, before the
> swap. Nothing downstream of that had ever been exercised because nothing could be.

**After the fixes in this pass**, the answer is a qualified yes: a competent operator with
a provisioned VPS can follow `runbooks/first-deploy.md` end to end. Qualified, because the
runtime image stage and everything that needs a real host, domain or vendor account remain
unexecuted here — listed under EXTERNAL below, honestly, rather than assumed.

---

## What was executed, step by step

Legend: **VERIFIED** = run here, observed to work · **BROKEN** = run here, observed to
fail (now fixed unless stated) · **ABSENT** = does not exist · **UNVERIFIED** = could not
be executed in this environment, and why.

### 1. Build

| Check | Verdict | Evidence |
|---|---|---|
| Every file the `Dockerfile` COPYs exists | **VERIFIED** | All 11 COPY sources resolve; the builder stage completes with every layer `DONE`. |
| `uv sync` produces a usable environment | **BROKEN → FIXED** | `ls /app/.venv/lib/python3.12/site-packages \| wc -l` → **3**. After adding `--all-packages`: **127**, and `import fastapi, sqlalchemy, alembic, arq, uvicorn, psycopg, boto3, sentry_sdk, opentelemetry, pgvector, argon2, jwt` succeeds inside the image. |
| `scripts/` reaches the image (D-168) | **VERIFIED** | `/app/scripts` present; `python -m scripts.bootstrap_admin` runs from the image. |
| uv base image pinned by digest (§4d item 1) | **BROKEN → FIXED** | Digest resolved from `ghcr.io/v2/astral-sh/uv/manifests/0.8.17` and **verified by hashing the response body**, which equals both the pin and the registry's `docker-content-digest`. |
| Runtime stage (`apt-get install curl`, non-root user, healthcheck) | **UNVERIFIED** | `deb.debian.org` returns 403 through this environment's egress proxy, and ghcr's blob CDN (`pkg-containers.githubusercontent.com`) is likewise refused, so `docker pull ghcr.io/astral-sh/uv` cannot complete here. The builder stage was proven by substituting only those two blocked references (`mirror.gcr.io` for the base, a local image holding the host's own uv 0.8.17 — the exact pinned version). **The runtime stage has still never been built anywhere.** |

**The finding, in full.** The workspace root is `package = false` with `dependencies = []`.
`uv sync` syncs the ROOT project by default, so it resolved an empty list, installed
nothing and **exited 0** — indistinguishable from a cache hit. Every service command in
`compose.prod.yml`, the `migrate` profile's `alembic upgrade head`, and all three
`scripts.*` modules the deploy runs through `compose run` would have died on their first
import. The repository already knew the rule: `README.md`'s command table says *"Must be
`uv sync --all-packages`. A bare `uv sync` installs only the virtual root's dev group, not
the workspace members"*, `.github/workflows/ci.yml` uses it twice, and DEPLOYMENT §3 and §8
both state it. The one file that builds the production artefact did not.

`--group errors` was added in the same line. DEPLOYMENT §8 prescribed `uv sync
--all-packages --group errors` *"on the api and worker host"* — written before this
Dockerfile existed, and an instruction the shipped architecture **cannot obey**: §2 puts no
Python on the host and the venv lives in an image layer owned by a non-root user. There was
no reachable command that could turn error reporting on, so `SENTRY_DSN` could never be
more than a setting and `check_observability_ready` would fail forever on a host that set
it.

### 2. Configuration

| Check | Verdict | Evidence |
|---|---|---|
| `.env.example` ⟷ `Settings` parity | **VERIFIED** | `check_env_parity` → `OK (60 keys aligned, 7 direct environment reads accounted for)`. |
| Refuses to boot on a missing critical setting | **VERIFIED** | `APP_ENV` has no default; `validate_bootstrap_env` converts a Pydantic traceback into one actionable sentence. |
| Refuses a dangerous default | **VERIFIED** | Booting `APP_ENV=prod` with the published dev DB password was refused by name: *"DATABASE_URL carries the development credential … That password is published in .env.example … Create the role with a generated password before running migrations (DEPLOYMENT §9.3a)."* |
| Deploy preflight catches a wrong value | **VERIFIED** | `check_deploy_env --env-file` correctly refused `127.0.0.1` DSNs with `dsn_host_unreachable_from_container`, and returned `OK` once rewritten to `host.docker.internal`. |
| **`Settings()` can load the `.env` the deploy demands** | **BROKEN → FIXED** | Three `extra_forbidden` errors, deterministically, every time. |

**The second finding, in full.** `Settings.model_config` is `env_file=".env",
extra="forbid"`, and pydantic-settings applies `forbid` to keys read from the **dotenv
file** (unrelated `os.environ` entries are not policed). DEPLOYMENT §6 tier 1 requires
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` in `.env`;
`vps-deploy.sh::preflight` **aborts the deploy** without the first two; `check_deploy_env`
validates all three. So the exact file four separate mechanisms demand was one
`Settings()` refused to construct, for any process whose working directory is the deploy
root.

The three containers escaped **by accident** — `.dockerignore` excludes `.env`, and
compose's `env_file:` delivers the same values as process environment. What did not escape
is `scripts/bootstrap_admin.py`, which runs from the repo root on the VPS by design. **The
first administrator could not be created on a correctly provisioned host.**

Fixed with an explicit allow-list (`SDK_OWNED_ENV_KEYS` + a `DotEnvSettingsSource`
subclass) rather than `extra="ignore"` or `dotenv_filtering="only_existing"`: both of those
would have been one word, and both would have silently swallowed a **misspelled** key —
`DATABSE_URL=` becoming silence instead of a refusal, in a file operators hand-edit over
SSH. `tests/deploy_env_file_loadable_test.py` pins both halves and was run red against the
unfixed tree first.

### 3. Migrations — **VERIFIED**

Against a scratch database created for this audit (`calevate_d188_scratch`; the shared dev
database was never touched):

```
alembic upgrade head        → exit 0, from genuinely empty
alembic heads               → c7a1e93d40b8 (head)   — one head, no branches
tables in public            → 62
RLS enabled AND forced      → 48 of 62
check_rls_coverage          → OK (44 tenant-column tables, 48 policied, GUC-checked;
                                  12 exempt-with-reason; 8 append-only triggers)
```

The `transaction_per_migration=True` property DEPLOYMENT §4a rests on is real
(`alembic/env.py`). One note, not a defect: migration `05bba2f3c19c` **hardcodes the role
name `calevate_app`**, so §9.3a's "create the role first with a generated password" is
mandatory in a way the `IF NOT EXISTS` guard does not enforce — get the order wrong and the
production app role's password is a string committed to this repository. The bootstrap gate
now catches that specific mistake at boot (see §2 above), which is a second net under the
same hole.

### 4. First boot — **VERIFIED**, with one caveat

The api booted under `APP_ENV=prod` against the scratch database:

```
GET /healthz/live   → 200  {"status":"ok","service":"api"}
GET /healthz        → 200  {"status":"ok","service":"api"}
GET /healthz/ready  → 503  {"status":"not_ready","service":"api"}
```

That is **honest**: readiness is red because vendor configuration is absent, and it does
not leak which keys to an unauthenticated caller (D-101). Boot also logged
`alert_delivery_unconfigured` exactly as OPERATIONS §4 promises.

**Caveat, and it is a real one.** With Redis unreachable, `/healthz/live` returned **500**,
not 200. `compose.prod.yml`'s healthcheck polls `/healthz/live` precisely so a Postgres or
Redis blip cannot make Docker restart every container — the design comment says so — and
under the fault it is meant to survive, it does not. The proximate cause here was the
`Settings()` failure of finding 2 (the per-request `settings_scope()` rebuilds `Settings`
when the config sentinel cannot be read from Redis, and that rebuild hit the
`extra_forbidden` error), so **fixing finding 2 removes this instance**. Whether
`/healthz/live` can 500 for any *other* reason under a dependency outage was not proven
either way here and is the one thing in this section worth re-testing on the real host.

### 5. The first administrator — **VERIFIED**, and the standing assumption was wrong

`scripts/bootstrap_admin.py` was run end to end against the scratch database, **both** from
the repo root and through the container image. Both created the `admin_users` row, minted
an `auth_email_tokens` row of purpose `admin_bootstrap`, wrote the `auth.admin_bootstrapped`
audit row, and printed:

```
email sent: NO — use the link below
Setup link (single use):
https://admin.calevate.tech/bootstrap?token=…
```

**So email delivery does NOT block the first login.** That was the standing assumption
going into this audit and it is wrong: the link goes to stdout by explicit design, and a
human at the terminal can follow it. Two real obstacles were found instead:

1. **The documented command cannot run on the VPS.** DEPLOYMENT §7a gives
   `uv run python -m scripts.bootstrap_admin`, and §2 says there is no Python and no uv on
   the host. The container form is what works, and it works **only because of the
   Dockerfile fix** — against the unfixed image it dies on `import sqlalchemy`. Both are
   now documented at the command.
2. **`AUDIT_CHAIN_SECRET` is a bootstrap ordering, and it very nearly deadlocks.** The
   first run failed with `hmac_key_missing`: the audit chain refuses to sign without a key
   outside `local`. That key is normally console-managed — and on a fresh host **the
   console cannot be the answer**, because reaching it requires an operator and creating an
   operator requires the key. The escape is that `env` beats the store by design (D-95), so
   it goes in `.env` for the first run and stays. Nothing said so; `.env.example` does not
   list it, and neither preflight demands it (correctly — they cannot distinguish "absent"
   from "stored in the console", so demanding it would refuse every correct redeploy). It
   is now written down at the command and in the runbook.

*Can a human follow this on a fresh VPS at 2am?* **Yes, now.** Before this pass: no — the
documented command could not execute, the image it would have to run in was empty, and the
key it needs was named nowhere.

### 6. The deploy script — **VERIFIED**

`scripts/vps-deploy.sh` is the strongest artefact in the deployment path, and it earned that
by refusing correctly at every step it was given a reason to:

```
envsubst missing            → aborts, names the tool
dirty checkout              → aborts, prints the diff
.env missing                → aborts, and says deploy scripts never write secrets
apps/web/.env.local missing → aborts in preflight_plan, BEFORE anything is built
pm2 missing                 → aborts, cites DEPLOYMENT §2
clean run                   → "would deploy [api voice-runtime workers nginx] at <sha>"
```

`preflight_plan` running before `--dry-run` exits is the property that matters, and it
holds: the dry run is a real preflight, not a plan printout. The disk report, the
Cloudflare-IP staleness check (`refreshed 2026-06-29, 50d ago, limit 180d`), the dev-compose
project-name collision check and the `VOICE_RUNTIME_WORKERS <= nproc` refusal all fired
correctly. **One first-run assumption was added by this pass**: an nginx version check (see
§7). No rollback path was executed — `deploy_revision_check`'s skip-on-rollback logic is
reviewed and **UNVERIFIED**.

### 7. nginx / TLS / DNS — **BROKEN → FIXED** (config), **UNVERIFIED** (edge)

DEPLOYMENT §4d item 4 records that `nginx -t` has never been run on the rendered config.
It has now:

```
render (envsubst, 5 vars)                  → OK, no unsubstituted placeholders
nginx -t  on nginx/1.24.0 (Ubuntu)         → [emerg] unknown directive "http2"  ← FAILS
nginx -t  on nginx/1.27                    → syntax is ok; test is successful   ← PASSES
```

`infra/nginx/calevate.conf.template` uses the standalone `http2 on;` directive in all four
TLS server blocks. **That directive appeared in nginx 1.25.1**, replacing the `listen …
http2` parameter deprecated in the same release. An older binary does not warn and does not
skip the line — it refuses the entire configuration, so **no server block loads at all**.
DEPLOYMENT §2 said `nginx ≥1.24` and §1 says Ubuntu 22.04, which ships **1.18**; 24.04 ships
**1.24**. Both documented baselines were versions this config cannot load, and a stock `apt
install nginx` produced a host that could never serve the site.

The template is *right* — `listen … http2` is the deprecated spelling and warns on every
reload, including the ones logrotate and certbot's renewal hook trigger. So the fix is the
floor, not the config: §2 now says **1.25.1**, and `preflight_plan` refuses below
`NGINX_MIN_VERSION` before anything is built, migrated or swapped (boundary tested: 1.25.0
refused, 1.25.1 accepted, and `sort -V` gets 1.9 vs 1.10 right).

**What a human must still do that no runbook can do for them:** create the Cloudflare zone
and the four A records; obtain the Cloudflare Origin CA certificate and key; run the
certificate order in §9.5a's non-obvious sequence (the obvious one deadlocks — the ACME
challenge location lives in a file that references a certificate that does not exist yet);
flip the zone to proxied + Full (strict). All **UNVERIFIED** here: no domain, no Cloudflare
account, no public IP.

### 8. Backups — **ABSENT in the sense that matters**

The mechanism is genuinely built and `infra/backup/README.md` is honest that it has been
applied to nothing. What was executed here:

```
bash -n over all 12 shell scripts                   → all pass
systemd-analyze verify on all 9 units               → no directive errors
                                                      (only "no such file" for /var/www/calevate)
executable bits                                     → correct: the three non-executable
                                                      scripts are `source`d, never run
```

**That is syntax, not a restore.** OPERATIONS §8's "backups verified" tick is earned by
`runbooks/backup-restore-drill.md`, which **has never run**. What a first-day operator
actually has: two chains of code that have never moved a byte, no wal-g credentials, no
offsite provider, and no evidence file in `docs/evidence/`. Until the drill runs, the
correct statement is *"backups are written but unproven"* — a backup nobody has restored
from is a hypothesis.

**And one live defect found here**: `scripts/backup/notify.sh` defaults its alert sink to
`alert-to-app.sh`, which sources `app-python.sh`, which resolves
`${CALEVATE_PYTHON:-$ROOT/.venv/bin/python}` and exits **78** when there is none. On a host
built to DEPLOYMENT §2's *"Python is NOT needed on the host"*, **every backup alarm reaches
journald and nobody else** — a failed base backup, a stalled WAL archive, the 15-minute
health check, all of them. The mechanism is not broken; it is uninstalled, and it fails
loudly into a log nobody is tailing at 4am. §2 is corrected and the runbook makes the host
venv a step.

### 9. Day two

| Concern | Verdict |
|---|---|
| Container log rotation | **VERIFIED (by inspection)** — `compose.prod.yml` caps json-file at 10×10MB per service. This is the one day-two control that is right by default. |
| Disk filling | **Built, never installed** — `infra/hygiene/` timer + the reclaim ladder in `vps-deploy.sh` (tier 0 always; tiers 1–3 below 8GB; refuse below 3GB). The escalation ordering is well argued. Installing the timer is a go-live step nobody has performed. |
| Certificate renewal | **Documented unusually well, UNVERIFIED** — `--deploy-hook` saved as `renew_hook` at issuance, and the doc correctly notes that a plain `certbot renew --dry-run` does **not** run deploy hooks. Needs a real certificate to exercise. |
| Container restart policy | **VERIFIED (by inspection)** — `restart: unless-stopped` on all four services; `init: true`. |
| Machine reboot | **Partly ABSENT** — Docker's restart policy brings the four containers back. `pm2 startup` + `pm2 save` (for `web`), the systemd timers and the GitHub runner service are all one-time installs that have never been done; miss any and that component does not survive a reboot. The runbook lists them. |
| Alerting reaching a human | **BROKEN, external** — no `EMAIL_PROVIDER`, no verified sender domain. Boot says `alert_delivery_unconfigured`, which is the correct behaviour and also means nothing pages anyone today. |
| Three OPERATIONS §4 alarms | **ABSENT** — complaint-spike, engine-5xx-spike and cert-expiry still have no call site, as D-183 recorded. Cert-expiry is the one that bites on day two and is a systemd timer beside the backup units. |

---

## What must happen first

### OURS — fixed in this pass

1. ✅ **`Dockerfile`: `uv sync --all-packages --group errors`** in both phases. Without it
   no container can start. *(3 → 127 packages, measured.)*
2. ✅ **`Dockerfile`: uv image pinned by digest** — closes DEPLOYMENT §4d item 1.
3. ✅ **`Settings` accepts the prescribed `.env`** — `SDK_OWNED_ENV_KEYS` + a filtered
   dotenv source, keeping the typo refusal. Without it the first administrator cannot be
   created. *(Regression test run red first.)*
4. ✅ **One spelling of the SDK key set** — `check_deploy_env` aliases the constant,
   `check_env_parity` asserts against it.
5. ✅ **nginx floor corrected to 1.25.1**, with a `preflight_plan` refusal that fires before
   anything is built.
6. ✅ **DEPLOYMENT §2's "no Python on the host" struck**, naming the two host-side paths
   that need it and what silently breaks without it.
7. ✅ **The first-administrator command rewritten to its container form**, with
   `AUDIT_CHAIN_SECRET`'s bootstrap ordering documented at the command.
8. ✅ **`runbooks/first-deploy.md` written**, every command in it executed here except the
   ones that need a real host.

### OURS — still open, and named rather than implied

- **The runtime image stage has never been built.** Blocked here by egress policy, not by
  the repo. It is the first thing to do on the VPS, before anything else — DEPLOYMENT §4d
  item 2 already says so and it remains unticked.
- **`/healthz/live` under a dependency outage** — one instance explained and fixed via
  finding 2; whether another path exists was not proven. Re-test on the host by stopping
  redis and polling it.
- **The rollback path has never run** — `deploy_revision_check`'s skip-on-rollback is
  reviewed and unexercised.
- **Three OPERATIONS §4 alarms have no call site** (D-183); cert-expiry is the day-two one.
- **`terraform validate` has never run** (`infra/README.md` §5).

### EXTERNAL — nobody can code around these

| # | Blocker | Who must do what |
|---|---|---|
| E1 | **A provisioned Hostinger India VPS** (≥4 vCPU for §2a's 4 voice-runtime workers, ≥4GB RAM + 2GB swap for `next build`) | Founder buys and provisions it. Nothing in `infra/` provisions a host. |
| E2 | **nginx ≥ 1.25.1** — not available from stock Ubuntu | Operator adds the nginx.org mainline/stable repository during §2 baseline. |
| E3 | **DNS + Cloudflare zone** — four A records, proxied, Full (strict) | Founder owns `calevate.tech`; operator creates records and the Origin CA certificate. |
| E4 | **Cloudflare R2** — recordings bucket, plus a **separate backup bucket with its own scoped token** (§7's vendor-concentration rule) | Founder opens the account; operator creates buckets, tokens and the bucket lock. |
| E5 | **A non-Cloudflare offsite target** for the nightly dump (Backblaze B2 / S3 / Hetzner Storage Box) | Founder chooses and pays for it. `dump-offsite.sh` will not run without one, and this is the copy that survives a Cloudflare account event. |
| E6 | **A verified Resend sender domain + `RESEND_API_KEY`** | Founder creates the account and verifies the domain (DNS records). Until then alerts and the admin setup link reach nobody by mail — the bootstrap link still works via stdout. |
| E7 | **A Sentry project + DSN** | Founder creates it. The SDK now ships in the image, so this becomes purely a configuration step. |
| E8 | **Secrets generated into a secrets manager** — `PLATFORM_KEK`, the two DB role passwords, `AUDIT_CHAIN_SECRET`, `IDEMPOTENCY_SCOPE_SECRET`, `IMPERSONATION_GRANT_SECRET` | Operator generates them; none may be typed from memory and none may be committed. |
| E9 | **The backup restore drill** (`runbooks/backup-restore-drill.md`) | Operator, after E4/E5 exist. This is what earns OPERATIONS §8's "backups verified", and it cannot be earned any other way. |
| E10 | **OPERATIONS §2 gates** — the Bolna pilot, gate 14 (a GCP project + service-account key), gate 15 (delivery actually arriving) | Founder + operator. These gate going LIVE, not deploying. |

---

## What this audit could not do, stated plainly

No VPS, no domain, no Cloudflare account, no R2 bucket, no vendor credentials of any kind.
`deb.debian.org`, `docs.astral.sh` and ghcr's blob CDN are refused by this environment's
egress proxy, which is why the runtime image stage is unbuilt. Everything above marked
VERIFIED was run against a scratch Postgres database created and dropped for this audit,
a local Redis, and locally installed nginx 1.24 plus a containerised nginx 1.27. **The
shared development database was not touched.**
