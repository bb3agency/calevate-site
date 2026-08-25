# raghava-organics production baseline vs. the live Calevate KVM1 box — gap report

**Date:** 25 Aug 2026 · **Author:** deploy-gap lane · **Status:** source read, nothing executed
on either host.

**Why this file exists.** A Hostinger KVM1 (1 vCPU / 3.8 GiB / 48 G, Ubuntu 24.04.4,
`srv1929611`) is **half-provisioned right now**, and `docs/DEPLOYMENT.md` inherits from a
production repository by name ("raghava-proven", "raghava §2 verbatim", "the raghava rule")
that this lane could read directly. This is the comparison of what that production baseline
actually does against what the box has had done, plus a hard-rule-11 audit of our own
citations to it.

**Provenance and how to read the citations.**

* **REF:** = read-only clone at `/home/user/bb3agency/raghava-organics-site`, read 25 Aug 2026.
  Nothing in it was modified. Paths are relative to that clone's root.
* **CAL:** = this repository, same date.
* Every claim about either repo carries `file:line`. Nothing here was executed — no shell was
  run on the VPS, no script was run in either tree — so a claim about *behaviour* is a claim
  about what the code would do when run.

**Evidence classes used** (CLAUDE.md hard rule 11):

| Class | Meaning here |
|---|---|
| **VERIFIED-SOURCE** | Read this session at the cited `file:line` in one of the two trees. |
| **REPORTED** | A figure or state relayed by the founder (the VPS's current configuration) that this lane could not observe. Not re-stated as fact. |
| **UNVERIFIED-ATTRIBUTION** | Something one repo attributes to the other that the cited source does not say. |

> **The whole "already done on the box" list is REPORTED, not VERIFIED-SOURCE.** This lane has
> no shell on `srv1929611`. Swap, ufw, fail2ban, unattended-upgrades, timesyncd, nginx 1.30.4,
> the Postgres tuning and the two roles are taken from the founder's brief. Section 0 therefore
> opens by re-proving them with the reference's own verification commands
> (REF:`backend/docs/CLIENT_VPS_SETUP_GUIDE.md:50-56`) rather than trusting the list. That is
> not distrust of the founder; it is that a hardening claim nobody re-read is exactly the class
> of claim rule 11 exists for, and the commands cost thirty seconds.

**Related prior work — read it, do not re-derive it.**
`docs/evidence/raghava-deploy-teardown.md` (17 Aug 2026) is a file-by-file read of the same
reference repo and is still accurate everywhere this lane overlapped it. This file is **not** a
second teardown. It is narrower and later: it compares that baseline against **a specific host
that is half-built today**, and it audits our citations. Where the teardown already settled
something (the sudoers wildcard finding, the DR-evidence fabrication, the cron-vs-timer
argument) this file cites it and moves on.

---

## 0. DO THIS NEXT, IN THIS ORDER

For an operator at the `srv1929611` root prompt right now. Everything in **A** happens before
the box has a DNS record pointed at it. Steps are ordered so that nothing later invalidates
anything earlier.

### A. Before this box is reachable from the internet

**A1 — Re-prove the five hardening claims, from the box, with the reference's own commands.**
Source: REF:`backend/docs/CLIENT_VPS_SETUP_GUIDE.md:44-56`.

```sh
sudo systemctl status fail2ban --no-pager
sudo ufw status verbose
timedatectl status
sudo grep -E "^(PermitRootLogin|PasswordAuthentication)" /etc/ssh/sshd_config
free -h                     # the 4 GB swap must be ACTIVE, not only in /etc/fstab
nginx -v                    # must print >= 1.25.1  (CAL:runbooks/first-deploy.md:122)
```

The fourth command is the one expected to fail. See A2.

**A2 — Create the non-root deploy user and close root SSH. This is gap #1 and it blocks
everything else.** The reference requires both (REF:`.../CLIENT_VPS_SETUP_GUIDE.md:36` "Create a
**non-root deploy user** with sudo"; REF:`.../CLIENT_VPS_SETUP_GUIDE.md:44` `PermitRootLogin no`
+ `PasswordAuthentication no`). Our own `docs/DEPLOYMENT.md:166-167` lists both. Our runbook
does **not** — `runbooks/first-deploy.md:126-130` re-lists §2's baseline and silently drops SSH
hardening and the deploy user, which is very likely why a box that has fail2ban and ufw is still
being driven from a root shell. Do it now, because six later artefacts hard-code the account
name `calevate`: `infra/hygiene/systemd/calevate-hygiene.service` (`User=calevate`,
`Environment=HOME=/home/calevate`, `WorkingDirectory=/var/www/calevate`), `DEPLOY_USER` in
`infra/privileged/sbin/calevate-nginx-apply`, and the sudoers policy — "all three, or none"
(CAL:`infra/hygiene/README.md` §5 item 2).

```sh
adduser --disabled-password --gecos "" calevate
usermod -aG sudo,docker calevate
install -d -m 700 -o calevate -g calevate /home/calevate/.ssh
cp /root/.ssh/authorized_keys /home/calevate/.ssh/authorized_keys
chown calevate:calevate /home/calevate/.ssh/authorized_keys
chmod 600 /home/calevate/.ssh/authorized_keys
```

**Open a SECOND ssh session as `calevate` and prove `sudo -v` works before you touch sshd.**
Then:

```sh
printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
  > /etc/ssh/sshd_config.d/10-calevate-hardening.conf
sshd -t && systemctl reload ssh
```

Note `docker` group membership is root-equivalent by design and our own §11 says so rather than
pretending otherwise (CAL:`docs/DEPLOYMENT.md:1510`, "What this does NOT claim to contain").

**A3 — Narrow the Postgres listener and firewall it.** The box is REPORTED as
`listen_addresses='*'` with `pg_hba` admitting `172.16.0.0/12` scram. `*` binds the **public**
interface too. Today only ufw stands between 5432 and the internet, and ufw is exactly the
control that does not contain Docker (CAL:`docs/DEPLOYMENT.md:178-183`;
CAL:`runbooks/first-deploy.md:132-136`). The reference's host prerequisite is narrower than ours
and is the right one: "UFW: only `22/80/443` inbound (**+ Postgres restricted to the Docker
subnet**)" — REF:`backend/docs/CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:154`.

```sh
# 1. bind only loopback + the docker bridge gateway, not the world
ip -4 addr show docker0 | awk '/inet /{print $2}'        # confirm the gateway, usually 172.17.0.1
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = '127.0.0.1,172.17.0.1';"
systemctl restart postgresql
ss -tlnp | grep 5432                                     # must NOT show 0.0.0.0:5432

# 2. belt and braces at the firewall
ufw allow from 172.16.0.0/12 to any port 5432 proto tcp
ufw deny 5432/tcp
```

Our runbook already asks for the narrow form — "`listen_addresses` must include the Docker
bridge gateway" (CAL:`runbooks/first-deploy.md:180`) — which `*` satisfies literally and defeats
in spirit.

**A4 — Verify the two roles cannot bypass RLS.** REPORTED as done; it is hard rule 1, so prove
it rather than inherit it (CAL:`runbooks/first-deploy.md:183-186`):

```sh
sudo -u postgres psql -d calevate -c \
  "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'calevate%';"
```

`rolbypassrls` must be `f` for both. `max_connections=100` and `shared_buffers=768MB` are the
**correct KVM1 values** and must not be "fixed" up to §2's 200 —
CAL:`runbooks/first-deploy.md:84-86` is the authority, not `DEPLOYMENT.md`.

**A5 — Remove the stock nginx default server block, and install ours.** This is the reference's
single most-repeated edge rule and the root cause of a Cloudflare **525** on a demonstrably
healthy origin: the stock file ships a *certless* `listen 443 ssl default_server`, and
Cloudflare's strict validation probes the origin **without matching SNI**, so it lands on that
block (REF:`backend/docs/CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:12-13`, `:37-39`). We already
have the replacement: CAL:`infra/nginx/000-default.conf.template`.

Their own caveat is worth keeping even though it does not bind here: do **not** remove
`sites-enabled/default` until you have listed the directory, because on their shared VPS it
broke a co-tenant site (REF:`.../CLIENT_VPS_SETUP_GUIDE.md:505`;
REF:`backend/docs/CLIENT_VPS_DEPLOYMENT_LOG_TEMPLATE.md:96`; the incident itself,
REF:`backend/docs/PHASE7_VPS_DEPLOY_INCIDENT_PLAYBOOK.md:301`). On a single-tenant Calevate box
`ls /etc/nginx/sites-enabled/` will show nothing else and the removal is safe.

**A6 — Refresh the Cloudflare IP list before it fails the deploy.**
`CAL:infra/nginx/README.md` §4 item 2: the deploy **fails** when `CLOUDFLARE_IPS_UPDATED` in
`snippets/calevate-origin.conf` is older than 180 days. Check the stamp now rather than
discovering it inside the first deploy.

**A7 — `systemctl disable --now redis-server` if a host Redis is present.** Redis lives only in
Compose and publishes no host port (REF:`.../CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:153`;
REF:`.../CLIENT_VPS_SETUP_GUIDE.md:186`; CAL:`docs/DEPLOYMENT.md:99`).

### B. The deploy itself — follow `runbooks/first-deploy.md`, with the KVM1 deltas

Do **not** improvise here; §0a of that runbook is the KVM1 table (CAL:`runbooks/first-deploy.md:73-110`).
The two host-shaped things this comparison adds:

**B1 — Python 3.12 + `uv sync --all-packages` in `/var/www/calevate`.** Not for the services —
for the backup alert relay, which otherwise exits 78 and every backup alarm reaches journald and
nobody (CAL:`runbooks/first-deploy.md:137-143`; CAL:`docs/DEPLOYMENT.md:119-133`).

**B2 — `pm2 stop calevate-web` before the first `next build`, and watch it.** The build is the
step that OOMs on this profile, before any call exists (CAL:`runbooks/first-deploy.md:99-105`).
The reference measured the same ceiling independently: "`next build` … can peak >2 GB. On a 4 GB
box this OOM-kills the runner service mid-deploy (`Active: failed (Result: oom-kill)`)"
(REF:`.../CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:185`, and the pitfall row at `:203`).

### C. Day two, in this order

1. `pm2 startup` **and** `pm2 save` (CAL:`runbooks/first-deploy.md:401`;
   REF:`.../CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:152`).
2. The privileged scripts and sudoers policy — and check the filename has no dot in it, because
   sudo silently ignores those (CAL:`runbooks/first-deploy.md:402-405`).
3. The hygiene timer and the journald cap (CAL:`infra/hygiene/README.md` §5).
4. The backup units, **then the restore drill**. "Until that drill has run, you do not have
   backups — you have backup code" (CAL:`runbooks/first-deploy.md:424-431`).
5. `scripts/backup/notify.sh probe "delivery test"` — the mail must land in a real inbox
   (CAL:`runbooks/first-deploy.md:434-440`).
6. **CD last, and see §2 below before installing any runner.**

---

## 1. Hardening gaps, ranked

Ranked by what an attacker or an outage reaches first. Class is VERIFIED-SOURCE for every
reference requirement cited; the "state on our box" column is REPORTED.

### 1.1 Must do before this box is reachable from the internet

| # | Gap | State on our box (REPORTED) | Protects against | Reference requirement | Fix |
|---|---|---|---|---|---|
| 1 | **`PermitRootLogin no` + `PasswordAuthentication no`** | Root shell in use; SSH config unconfirmed | Credential-stuffing straight to uid 0. fail2ban rate-limits guesses; it does not stop a leaked root key, and every automated action on the box is currently uid 0 | REF:`CLIENT_VPS_SETUP_GUIDE.md:44` | §0 A2 |
| 2 | **Non-root deploy user (`calevate`), in `docker`** | Not created | Blast radius, and it is a hard prerequisite: three of our own artefacts hard-code the account | REF:`CLIENT_VPS_SETUP_GUIDE.md:36` | §0 A2 |
| 3 | **Postgres bound to `*`** | `listen_addresses='*'` | A single ufw rule error, a Docker `ports:` line, or a provider firewall change exposes 5432 with a scram-only guard. ufw does not filter Docker's `nat`/`FORWARD` path at all (CAL:`docs/DEPLOYMENT.md:178-183`) | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:154` | §0 A3 |
| 4 | **Stock nginx `default_server` still present** | Unconfirmed | Cloudflare **525** on a healthy origin, and the raw VPS IP serving the site | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:12-13`, `:37-39`, `:90` | §0 A5 |
| 5 | **Origin not locked to Cloudflare ranges** | Not installed | Bypassing the WAF, rate limits and bot rules by hitting the IP directly | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:90-113` | CAL:`infra/nginx/snippets/calevate-origin.conf`; verify it does not lock *you* out first (CAL:`infra/nginx/README.md` §4 item 4) |
| 6 | **Cloudflare SSL/TLS mode** | Zone not configured yet | `Flexible` produces an infinite redirect loop against our port-80 301; `Full` (non-strict) accepts a forged origin cert | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:11`, `:67-72` | Set **Full (strict)** at the zone before the A record is proxied |
| 7 | **Unique per-service secrets** | `.env` not written yet | One leaked password reaching two services. Their pitfall table has a row for exactly this outcome | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:14`, `:201` | CAL:`runbooks/first-deploy.md:190-232`; generate in the secrets manager, `chmod 600 .env` |

### 1.2 Day two — real, but they hurt in weeks, not minutes

| # | Gap | Protects against | Reference | Ours |
|---|---|---|---|---|
| 8 | **Disk hygiene job installed** | Disk exhaustion taking Postgres down. Theirs hit 83% and found ~18 GB of build cache surviving a daily cleanup that pruned the wrong builder | REF:`backend/scripts/vps-cleanup-template.sh:42-46`; REF:`backend/docs/HARDENING_HISTORY.md:104` | Already built and better: CAL:`infra/hygiene/` — install it (§0 C3) |
| 9 | **journald cap** | The journal filling the volume between daily runs | REF: (they vacuum daily instead) | CAL:`infra/hygiene/journald-cap.conf` — a continuous `SystemMaxUse=512M` rather than a nightly vacuum, and the reasoning is in the file |
| 10 | **Backups installed AND drilled** | The only recovery path there is | REF:`backend/scripts/dr-backup-offsite.sh` | CAL:`infra/backup/` + `runbooks/backup-restore-drill.md`. **Do not copy their evidence pattern — see §3.5** |
| 11 | **Alert delivery proven** | Every alarm above being invisible | REF:`.../CLIENT_VPS_SETUP_GUIDE.md:612+` (§15 observability) | CAL:`runbooks/first-deploy.md:434-440` |
| 12 | **TLS renewal hook attached at issuance** | A renewed certificate the running nginx never reads. `certonly` never reloads nginx | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:16` ("never `certbot --nginx`") | CAL:`infra/nginx/README.md` §4 item 3 — `--deploy-hook` in the issuance command; `certbot renew --dry-run` does **not** prove it |
| 13 | **Maintenance page** | Every backend stutter rendering as a fatal outage | REF:`backend/docs/HARDENING_HISTORY.md:442` | **Deliberately not built** (CAL:`infra/nginx/README.md` §3). See §3.1 — this is the one thing worth adopting |

**Not a gap, and worth saying so.** Swap, ufw 22/80/443, fail2ban, unattended-upgrades and
timesyncd cover **five of the five rows** in the reference's own §2.1 hardening checklist
(REF:`.../CLIENT_VPS_SETUP_GUIDE.md:44-48`) except the SSH row. nginx 1.30.4 clears both floors —
theirs is 1.24+ (REF:`.../CLIENT_VPS_SETUP_GUIDE.md:33`) and ours is the higher 1.25.1
(CAL:`docs/DEPLOYMENT.md:151-165`, the `http2 on;` directive). The box is further along than the
reference's baseline in every dimension except the SSH row and the Postgres listener.

---

## 2. The self-hosted runner on KVM1 — verdict

**Question:** D-472 says do not install the Actions runner on KVM1. Is that overstated?

**Answer: no. D-472 is correct, and if anything it understates the load.** The runner on their
box is not a thin pull-and-restart agent. It is the build machine.

**What the runner actually executes, from the source:**

| Step | Where | Cost |
|---|---|---|
| `git fetch` / `pull --ff-only` | REF:`.github/workflows/deploy.yml:82-85` | negligible |
| **`npm ci`** on the host | REF:`backend/scripts/vps-deploy.sh:103` | minutes of IO, hundreds of MB |
| **`docker compose build`** | REF:`backend/scripts/vps-deploy.sh:267` | a full image build, on the box |
| `prisma migrate deploy` | REF:`backend/scripts/vps-deploy.sh:278` | small |
| container stop / rm / up | REF:`backend/scripts/vps-deploy.sh:523-539` | 3–5 s window per service |
| **`npm ci` again**, frontend | REF:`backend/scripts/vps-frontend-deploy.sh:122` | minutes |
| **`npm run build`** (`next build`) | REF:`backend/scripts/vps-frontend-deploy.sh:130` | **peaks >2 GB** |
| `pm2 reload` + health poll | REF:`backend/scripts/vps-frontend-deploy.sh:199`, `:223-237` | small |

**So the plain answer to "does it build, or only pull and restart?" is: it builds, twice.** Any
recommendation premised on "the raghava flow is only `git pull` + `docker compose up` + `pm2
reload`" is premised on something the source does not say. `SKIP_FRONTEND_BUILD=true` exists but
its own header forbids the case that matters: "Never use after frontend code changed"
(REF:`backend/scripts/vps-frontend-deploy.sh:18-19`).

**How much RAM.** Not an estimate — the reference measured the failure on the same class of
host: "`next build` … can peak >2 GB. On a 4 GB box this OOM-kills the runner service mid-deploy
(`Active: failed (Result: oom-kill)`)" (REF:`.../CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:185`),
with a dedicated pitfall row for "CD runner service `failed (Result: oom-kill)` mid-deploy"
(`:203`). Our own tree reached the same number independently (CAL:`docs/DEPLOYMENT.md:102`,
CAL:`scripts/vps-deploy.sh:462`). Two sources, one figure, and the reference's is a post-mortem
rather than a projection.

**CPU is the half D-472 gets right that the reference never had to face.** Their box is a shared
VPS running 5–10 sites (REF:`.../CLIENT_VPS_SETUP_GUIDE.md:31`), and the worst outcome of a
build storm there is a slow page. Ours is 1 vCPU carrying a **latency-critical voice path** with
an unmeasured 350 ms TTFT budget and a 500 ms webhook ack ceiling (hard rule 3). A `next build`
saturating the single core is not "slow deploys" — it is `webhook_ack_ms` breaching while a call
is live. The reference has no equivalent to that, so its silence on CPU is not evidence that CPU
is fine.

**Recommendation for KVM1 — build in GitHub-hosted CI, ship an image, and let the box pull.**

That is already this repository's stated better shape rather than a new idea:
CAL:`runbooks/first-deploy.md:106-110` — "build the image in GitHub-hosted CI, push it to a
registry and have the VPS pull it. That is the better shape on this profile anyway … and it
removes the only reason §10 wanted a runner here."

The honest tradeoff, both directions:

* **What you give up.** Push-to-deploy latency (a registry push and pull, versus a local build),
  a container registry to run and pay for, and one more credential on the box. You also lose the
  reference's genuinely nice property that the runner needs **no inbound SSH** — it polls GitHub
  outbound (REF:`backend/scripts/vps-frontend-deploy.sh:5-7`). A pull-only runner keeps that
  property, so this is only a real loss if you replace CD with SSH-from-CI, which you should not.
* **What you keep.** A runner that only pulls a pre-built image, runs migrations and swaps
  containers is roughly the bottom half of their `vps-deploy.sh` and costs tens of MB, not
  gigabytes. If you want CD on this box, **that** is the runner to install — not the one whose
  workflow calls `npm ci` and `next build`.
* **What is not a real cost.** Our `scripts/vps-deploy.sh` already selects components from the
  diff (CAL:`scripts/vps-deploy.sh:8-20`), so a backend-only push never triggers the web build
  at all. The OOM risk is concentrated on pushes that touch `apps/web/**`, `pnpm-lock.yaml`,
  `pnpm-workspace.yaml` or `package.json` (CAL:`scripts/vps-deploy.sh:627`) — a minority of
  pushes, but the ones you cannot predict.

**Concretely, and in order:** (a) leave `VPS_DEPLOY_ENABLED` unset until one full **manual**
deploy has succeeded (CAL:`runbooks/first-deploy.md:410-412`); (b) do not install a runner at
all for the first deploy; (c) when you do want CD, move `web`'s build into GitHub-hosted CI
first and only then install a runner whose job is pull-migrate-swap. Installing the runner
first and "being careful about when we push" is the version that fails at 2 a.m. during a call.

**One thing to copy verbatim if a runner is ever installed:** a **unique label per repo**, set
as the repo Variable `VPS_RUNNER_LABEL`, and never a cloned runner directory. Without the label
GitHub can route one repo's deploy to another repo's runner
(REF:`.../CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:180-183`;
REF:`.github/workflows/deploy.yml:54-57`). Their workflow warns rather than fails when it is
missing (`:55`) — ours should fail.

---

## 3. What to reuse — and what we have already solved better

The instruction is "one way per problem". Most of this list is **already solved here**, and the
finding is that we should *install* what we have rather than adopt theirs. Three genuine gaps.

### 3.1 Maintenance page — **ADOPT (the one real gap)**

**What it is.** A branded static page at `/etc/nginx/maintenance/maintenance.html` that nginx's
`error_page 502 503 /maintenance.html;` resolves to, plus an installer that is idempotent and
that also **validates the live vhost actually has the directives**
(REF:`backend/scripts/install-maintenance-page.sh:103-113`).

**Why it matters, in their words:** without the file on disk, "any backend 5xx (transient
slowness, a single failing health check, a maintenance window …) → Nginx tries to render
`error_page 502 503 /maintenance.html` → file not on disk → Nginx falls back to its compiled-in
default 500 page … what should have been a friendly 15-second downtime page looked like a fatal
site outage every time the backend so much as stuttered"
(REF:`backend/docs/HARDENING_HISTORY.md:442`).

**Do we have it? No, deliberately.** CAL:`infra/nginx/README.md` §3 names it as not built,
because the gate's shape is hard-won and "a half-remembered version of that is worse than none".
That reasoning is sound **for the auth_request gate** and this lane does not propose reversing
it. But the reasoning does not extend to the static file, and the two have been collapsed into
one deferral. The three hard-won facts are all recorded and all now re-verified against source:

* `if` in the rewrite phase runs **before** `auth_request` populates its variable in the access
  phase, so `if ($maintenance_active = "1")` never fires
  (REF:`backend/docs/HARDENING_HISTORY.md:386-391`);
* a two-hop `error_page` chain dies because `recursive_error_pages` is off by default
  (REF:`backend/docs/HARDENING_HISTORY.md:243`, `:255`), and turning it on has "subtle
  interactions with `proxy_intercept_errors`" globally (`:282`);
* the pattern is single-hop: gate returns **401**, each gated location carries
  `error_page 401 = @maintenance_block;`, one server-level
  `location @maintenance_block { internal; return 503; }`
  (REF:`backend/docs/HARDENING_HISTORY.md:398`, `:528`).

**Recommendation, smallest thing that closes the real damage:** add
`error_page 502 503 /maintenance.html;` plus `location = /maintenance.html { try_files $uri
@maintenance_inline; }` and an inline fallback to `CAL:infra/nginx/calevate.conf.template`, and
ship the static page. **This needs no `auth_request` and no gate at all** — a 502/503 from a
dead upstream is generated by nginx itself and hits `error_page` directly. Their inline-fallback
choice (`try_files` over `error_page 404 = @…`, precisely to avoid needing
`recursive_error_pages on`) is at REF:`backend/docs/HARDENING_HISTORY.md:294` and transfers
unchanged. Keep `hooks.calevate.tech` exempt (CAL:`docs/DEPLOYMENT.md:822-825`) — an engine
callback meeting a maintenance page is a lost call.

### 3.2 Dead-container tombstone recovery — **ALREADY SOLVED, better**

Theirs: REF:`backend/scripts/cleanup-stale-compose-state.sh:1-52` — Docker leaves `Dead`-state
tombstones under `/var/lib/docker/containers/<id>/` when an image is pruned before its container
is cleanly removed; compose then tries to recreate them on every `up`. Their recovery restarts
the Docker daemon.

Ours **detects and refuses with the exact command** instead of running an unattended `rm -rf`
under the daemon's state directory, on the stated ground that the automated fix is a bigger
hazard than the fault (CAL:`docs/DEPLOYMENT.md:583-586`). Keep ours. Do not add their script.

### 3.3 Disk hygiene — **ALREADY SOLVED, better; just install it**

CAL:`infra/hygiene/README.md` §3 already documents three corrections over theirs, and all three
check out against source:

* Theirs deletes the runner's `_work/*` and `_tool/*` from cron, **unsynchronised with GitHub
  Actions** — REF:`backend/docs/GITHUB_CD_SELF_HOSTED_RUNNER_GUIDE.md:314-325`, which calls it
  "fully safe" because the runner recreates the folders. That is true of an idle runner and
  false of a job in flight at 06:25. Ours touches neither.
* Theirs prunes host-globally from `/etc/cron.daily`; ours scopes prunes to our compose project
  and holds the same lock the deploy holds.
* `run-parts` silently skips any filename containing a dot, so their installer
  (REF:`backend/scripts/install-vps-cleanup.sh:20`, `/etc/cron.daily/vps-cleanup-${CLIENT_ID}`)
  produces a job that never runs for any client id with a `.` in it.

One thing of theirs **is** worth keeping and we already have: `docker builder prune`, **not**
`docker buildx prune` — the latter can target a different builder and leave the real cache
uncapped, which is how ~18 GB accumulated despite a daily cleanup
(REF:`backend/scripts/vps-cleanup-template.sh:42-46`; ours,
CAL:`scripts/deploy/docker-reclaim.sh` via `docs/DEPLOYMENT.md:583-598`).

### 3.4 Pre-build disk reclaim — **ALREADY SOLVED, and their bug is the reason**

Their post-build prune runs only after a **successful** build
(REF:`backend/scripts/vps-deploy.sh:609-611`, after the health gate), so a near-full disk kills
the build and the cleanup that would have prevented it never runs — every later deploy is then
wedged. Ours reclaims **before** the build, in a four-tier ladder, and refuses below 3 GB before
anything is built, migrated or swapped (CAL:`docs/DEPLOYMENT.md:583-598`). On a 48 G disk that
also holds Postgres, this matters more here than there.

### 3.5 Offsite DR backup — **DO NOT ADOPT THE PATTERN; ours already supersedes it**

Their script does the right shape — `pg_dump | gzip`, a size floor, a sha256, an rsync to a
remote, and an evidence JSON (REF:`backend/scripts/dr-backup-offsite.sh:48-124`). Two reasons
not to take it:

1. **The evidence file hardcodes its own verdict:** `"pass": true` is a literal in the heredoc
   (REF:`backend/scripts/dr-backup-offsite.sh:122`), emitted unconditionally on a run where the
   Redis half may have been skipped entirely (`:79`, `:82`). It is an artefact that asserts
   success by construction — the defect class `docs/evidence/raghava-deploy-teardown.md` already
   records.
2. Ours is a superset: wal-g WAL archiving, a nightly base backup, a **non-Cloudflare** offsite
   dump so one vendor event cannot take both copies, and a 15-minute health timer
   (CAL:`infra/backup/`, CAL:`runbooks/first-deploy.md:418-431`).

**What does transfer verbatim is the size floor** — `if [ "${PG_SIZE}" -lt 100 ]; then … exit 1`
(REF:`backend/scripts/dr-backup-offsite.sh:51-54`). A `pg_dump` that fails still produces a small
valid gzip, so byte-count is the cheapest way to catch a dump of nothing. Confirm
CAL:`scripts/backup/dump-offsite.sh` has an equivalent floor before the first nightly run.

### 3.6 Credential rotation runbook — **ADOPT THE SHAPE**

REF:`docs/clients/raghava-organics/CREDENTIAL_ROTATION_RUNBOOK.md`. What makes it good is §1,
"Symptom → which credential is dead" (`:14`): it starts from what an operator *observes* at 3
a.m. rather than from an inventory of secrets. We have rotation procedures scattered across
`runbooks/` but no single symptom-first index for "CD is red / the VPS cannot pull / the token
expired". Their §4 is also a decision worth copying: **VPS git auth over SSH deploy key, so
there is no PAT to rotate on the box at all** (`:86`), with HTTPS+PAT explicitly marked
"temporary only" (`:118`).

### 3.7 Deployment log template — **ADOPT**

REF:`backend/docs/CLIENT_VPS_DEPLOYMENT_LOG_TEMPLATE.md` is a phase-by-phase form filled in *as
the deploy happens* (Phase 6 baseline → 7 backend → 7.4 nginx → 7.5 TLS → 7.6 smoke → … → 13 DNS
cutover). We have the procedure (`runbooks/first-deploy.md`) and the evidence convention
(`docs/evidence/`) but no artefact that records **what was actually done on this host, when, and
what it printed**. Given that our first deploy is attended and unrun, that record is worth more
here than it was there. Concretely: open `docs/evidence/first-deploy-srv1929611.md` at the start
of §0 A1 and fill it as you go — including the commands that failed.

### 3.8 Incident playbook — **ALREADY SOLVED, mostly**

REF:`backend/docs/PHASE7_VPS_DEPLOY_INCIDENT_PLAYBOOK.md` is symptom-indexed (`:99-265`, failure
signatures A–K). Ours is `runbooks/deploy-failed.md`, "ordered by the step that failed"
(CAL:`runbooks/first-deploy.md:449`), which is the same idea keyed differently. Two of their
signatures are stack-independent and worth having in ours if they are not:

* `P1001 Can't reach database at host.docker.internal` during host-side migrate (`:144`) — the
  `extra_hosts: host.docker.internal:host-gateway` / `pg_hba` seam, which is exactly our seam;
* the "observed second-run works" anti-pattern (`:77`) — a deploy that fails then succeeds on
  retry is a state bug being masked, not a flake.

### 3.9 Health-check window sized for migrate-on-boot — **ADOPT THE NUMBER IF OURS IS SMALLER**

REF:`backend/scripts/vps-deploy.sh:32-34`: their 30×2s = 60s window was shorter than a cold
migrate-on-boot on a shared VPS, so deploys went red while succeeding — "training operators to
ignore red deploys". They moved to 90×2s = 3 min. On 1 vCPU a cold boot is slower still, so
check our poll window against that before the first attended deploy. A deploy that is red while
correct is worse than a slow one.

---

## 4. Hard-rule-11 audit of our own "raghava-proven" citations

Ten citations checked against the source. **Six hold. Four do not.** Each finding names the fix.

### 4.1 FINDING — "raghava §2 verbatim" is not verbatim (CAL:`docs/DEPLOYMENT.md:108`)

Their §2 (REF:`.../CLIENT_VPS_SETUP_GUIDE.md:26-36`) specifies **Ubuntu 22.04**, **nginx 1.24+**,
Node.js 22, 2 vCPU / 4 GB, 40 GB. Ours specifies Ubuntu 24.04 and **nginx ≥1.25.1** — a floor
their §2 does not meet and which our own D-188 note says was raised precisely because both
documented baselines were versions our config cannot load (CAL:`docs/DEPLOYMENT.md:151-165`).
Our §2 also adds swap, `pm2 startup`, the redis disable, the sudoers policy and the hygiene
timer, none of which appear in their §2. It is a well-reasoned **adaptation**; the word
"verbatim" is false and invites the next reader to go looking for a source that says 1.25.1.
**Fix:** retitle to "adapted from raghava §2 — the floor and the additions are ours".

### 4.2 FINDING — "Hardening (all raghava-proven)" sweeps in two things that are explicitly ours, and one that is nowhere (CAL:`docs/DEPLOYMENT.md:166-172`)

Row by row:

| Item | Verdict | Source |
|---|---|---|
| non-root deploy user | **holds** | REF:`CLIENT_VPS_SETUP_GUIDE.md:36` |
| SSH `PermitRootLogin no` + `PasswordAuthentication no` | **holds** | REF:`CLIENT_VPS_SETUP_GUIDE.md:44` |
| ufw 22/80/443 | **holds** | REF:`CLIENT_VPS_SETUP_GUIDE.md:45` |
| fail2ban | **holds** | REF:`CLIENT_VPS_SETUP_GUIDE.md:46` |
| unattended-upgrades | **holds** | REF:`CLIENT_VPS_SETUP_GUIDE.md:47` |
| `systemctl disable --now redis-server` | **holds** | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:153` |
| remove `sites-enabled/default` | **holds, minus a caveat we dropped** | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:13`; the caveat, REF:`CLIENT_VPS_SETUP_GUIDE.md:505` |
| `pm2 startup` once | **holds** | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:31`, `:152` |
| "**in `docker` group**" | **UNVERIFIED-ATTRIBUTION** | No occurrence of a docker-group grant found anywhere in REF:`backend/docs/*.md` or REF:`docs/*.md`. Plausible and probably true of their host; not stated in the source we are citing |
| "**2GB swap in `/etc/fstab`**" | **holds as a floor, and contradicts our own runbook** | Their text is "≥2 GB" (REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:152`, `:202`). Our KVM1 profile requires **4 GB** (CAL:`runbooks/first-deploy.md:79`), and `DEPLOYMENT.md:102` and `:169` both still say 2 |
| "**the sudoers policy and the root-owned scripts it names**" | **contradicts our own §11** | §11 reads their sudoers grants and concludes "it is the pattern to **invert**" (CAL:`docs/DEPLOYMENT.md:1494-1503`). Calling the inversion raghava-proven is self-contradictory |
| "**the daily hygiene timer**" | **contradicts `infra/hygiene/README.md` §2** | Which calls it "a deliberate departure from the reference playbook" |

**Fix:** cut "all" from the parenthetical, split the list into "from raghava §2.1" and "ours",
move the swap figure to 4 GB (or delete the number and point at `first-deploy.md` §0a, which is
the profile-aware authority), and drop the docker-group claim or cite something real.

### 4.3 FINDING — "Parallel docker builds OOM 4GB hosts; build serially" is ours, not theirs (CAL:`docs/DEPLOYMENT.md:1477`)

§10 is titled "Known raghava lessons to NOT relearn (**their HARDENING_HISTORY**, our
checklist)". Nothing in the reference tree discusses parallel Docker builds or serialising them;
searches for "parallel" and "serially" across REF:`backend/docs/*.md` and REF:`docs/*.md` return
only unrelated application-level hits. Their OOM lessons are about **`next build`**, singular
(REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:185`, `:202-203`). The serial-build reasoning is
our own and is argued properly in our own §4 (CAL:`docs/DEPLOYMENT.md:600`). **Fix:** move it out
of §10 into the list of our own decisions. It is good engineering wearing someone else's badge.

### 4.4 FINDING — "`auth_request` buffers request bodies → big uploads 500" is not in the source (CAL:`docs/DEPLOYMENT.md:1472-1473`)

Every `auth_request` entry in REF:`backend/docs/HARDENING_HISTORY.md` (`:250`, `:273`, `:371-398`,
`:424`, `:442`, `:488`, `:511`, `:528`) is about the maintenance-gate phase-ordering bug and the
missing static file. None concerns request-body buffering or an upload exemption. Their own
`deploy.yml:101` refers to "the admin upload exemption stayed missing (see HARDENING_HISTORY
2026-08-09)" — and **no 2026-08-09 entry exists in the HARDENING_HISTORY in this clone**, so the
reference's internal citation is itself dangling. The underlying nginx behaviour is real and
documented upstream, but **we are citing them for it and they do not say it.** Note our
`infra/nginx/README.md` §3 states the same fact ("it buffers request bodies, which breaks large
uploads") without attributing it, which is the correct form. **Fix:** in §10, either drop the
line or mark it as a general nginx property with a link to nginx's own docs — not to their
HARDENING_HISTORY.

### 4.5 Citations that HOLD (recorded so nobody re-checks them)

* **Redis publishes no host port** (CAL:`docs/DEPLOYMENT.md:99`) — REF:`CLIENT_VPS_SETUP_GUIDE.md:186`,
  `docker-compose.prod.yml` sets `redis.ports: !reset []`. ✅
* **web under pm2, not Docker** (CAL:`docs/DEPLOYMENT.md:102`) — REF:`vps-frontend-deploy.sh:198-209`,
  REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:31`. ✅
* **host PostgreSQL 16** (CAL:`docs/DEPLOYMENT.md:61`) — REF:`CLIENT_VPS_SETUP_GUIDE.md:36` (install list), `:105` (§5 "PostgreSQL (host)"). ✅
* **paths in Secrets, flags and labels in Variables** (CAL:`docs/DEPLOYMENT.md:329`, `:431`) —
  REF:`.github/workflows/deploy.yml:48` (`secrets.VPS_CLIENT_PATH`) vs `:37`, `:39`, `:110`
  (`vars.*`). ✅
* **the sudoers wildcard finding** (CAL:`docs/DEPLOYMENT.md:1494-1500`) — verbatim confirmed:
  REF:`CLIENT_VPS_SETUP_GUIDE.md:1244` grants `NOPASSWD: /usr/bin/rm -rf /var/lib/docker/containers/*`
  and `:1264`, `:1267` grant `cp /tmp/*.nginx.conf` and `cp /tmp/tmp.*` into
  `/etc/nginx/sites-available/*.conf`. Their own "Security note" (`:1273`) claims the wildcard
  "only matches paths under `/var/lib/docker/containers/`", which is the misreading our §11
  rebuts. Our §11 is correct and well-sourced. ✅
* **525 = certless `default_server`; `certbot --nginx` destroys templated config; the single-hop
  `error_page 401 =503` maintenance pattern; health windows sized for migrate-on-boot (90×2s);
  Dead-container tombstones; one runner directory per repo, never clone a configured runner**
  (CAL:`docs/DEPLOYMENT.md:1468`, `:1469`, `:1470-1472`, `:1474`, `:1475`, `:1476`) — REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:12`, `:16`,
  `:183`; REF:`HARDENING_HISTORY.md:398`; REF:`vps-deploy.sh:32-34`;
  REF:`cleanup-stale-compose-state.sh:10-22`. ✅
* **`dr-backup-offsite.sh` sha256 evidence-JSON pattern** (CAL:`docs/DEPLOYMENT.md:1015`) —
  REF:`dr-backup-offsite.sh:101-124`. ✅ (with §3.5's caveat about `"pass": true`).

### 4.6 Cosmetic

CAL:`docs/DEPLOYMENT.md:801` is headed "**four** adaptations" and lists six (`:820-846`). Not a
truth defect; fix while touching the section.

---

## 5. KVM1 fitness — what in their setup assumes a bigger box

| Their assumption | Source | On 1 vCPU / 3.8 GiB |
|---|---|---|
| 2 vCPU / 4 GB minimum, 4/8 recommended | REF:`CLIENT_VPS_SETUP_GUIDE.md:31` | We are **below their stated minimum on vCPU**. Say it plainly rather than round up. Our profile is viable because we run 3 processes, not 7 (CAL:`runbooks/first-deploy.md:83-88`) and because §2a's measured table gives one worker 63–85 ms at 25 in-flight (CAL:`runbooks/first-deploy.md:107-110`) — but the headroom is small |
| Builds run on the box | REF:`vps-deploy.sh:103`, `:267`; REF:`vps-frontend-deploy.sh:122`, `:130` | **The single biggest misfit.** §2 |
| Swap ≥2 GB | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:152` | Ours is **4 GB** and must stay — the box already has it. `DEPLOYMENT.md`'s 2 GB is stale |
| `max_connections` sized for many stacks | REF:`CLIENT_VPS_SETUP_GUIDE.md:105+` (§5) | Ours is **100**, and `DB_POOL_SIZE=6` not 16. Do not raise either to match `DEPLOYMENT.md` §2a (CAL:`runbooks/first-deploy.md:83-87`) |
| Worker count not tied to vCPU | — | Ours is **1** voice-runtime worker, "never more workers than vCPU" (CAL:`runbooks/first-deploy.md:88`) |
| Multi-client port slots 300N/310N, per-client compose projects, shared host Postgres | REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:24-35`; REF:`CLIENT_VPS_SETUP_GUIDE.md:74-84` | **Does not apply.** Single tenant, one compose project. Ignore the slot table; do not adopt the shared-VPS caveats (they cost clarity and buy nothing here) |
| Daily cleanup at 06:25 local | REF:`install-vps-cleanup.sh:46` | Ours runs 19:00 UTC / 00:30 IST, chosen against **TRAI calling windows** and the base-backup schedule (CAL:`infra/hygiene/systemd/calevate-hygiene.timer`). Their clock has no such constraint; keep ours |
| `docker builder prune --keep-storage 5GB` | REF:`vps-cleanup-template.sh:46` | Ours caps at **3 GB** (CAL:`docs/DEPLOYMENT.md:588`). On a 48 G disk shared with Postgres and WAL, the smaller cap is right |
| Node.js 22 on the host | REF:`CLIENT_VPS_SETUP_GUIDE.md:36` | Still needed for pm2 + the web build (CAL:`docs/DEPLOYMENT.md:110`) — **unless** §2's recommendation lands and web is built in CI, in which case the host needs Node only for pm2 to run an already-built `.next` |
| Certbot **nginx plugin** installed | REF:`CLIENT_VPS_SETUP_GUIDE.md:36` | Install certbot, but **never invoke `--nginx`** (REF:`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:16`; CAL:`infra/nginx/README.md` §3). Having the plugin present is a footgun sitting next to a templated config; prefer `certbot` + the webroot plugin only |

---

## 6. What this file does NOT close

Stated rather than left to be discovered:

1. **Nothing was executed.** No command in §0 has been run by this lane, on either host. The
   "already done" list for `srv1929611` remains **REPORTED** until §0 A1 prints.
2. **`docs/DEPLOYMENT.md` is not edited by this lane.** The four findings in §4 are defects in a
   live document; this file records them with citations, and closing them is a doc edit that
   should happen in the same session as somebody reading §4. They are not external blockers.
3. **The maintenance-page adoption (§3.1) is a proposal, not a change.** No nginx template was
   touched.
4. **The reference's own dangling citation** (their `deploy.yml:101` → a HARDENING_HISTORY entry
   dated 2026-08-09 that is not in this clone) may exist in a newer revision of their repo than
   the one cloned here. Recorded as unresolved rather than as their defect.
