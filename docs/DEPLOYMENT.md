# Calevate — VPS Deployment & CI/CD Blueprint

Version 1.0 · July 2026. Adapted from the battle-tested raghava-organics playbook
(`D:\Agency\Clients\raghava-organics\raghava-organics-site\backend\docs\` — canonical:
CLIENT_VPS_SETUP_GUIDE, CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE, MASTER_DEPLOYMENT_PLAYBOOK,
HARDENING_HISTORY). Where this doc says "raghava-proven" it means: running in production,
with the failure modes already found and fixed there. Decisions D-25…D-27 in ROADMAP §6.

## 0. Hosting decision (D-25 for the scope, D-180 for the provider and region)

The calevate.tech site is NOT in the live-call path — the rented engine (Bolna, D-31)
hosts the entire voice pipeline in v1. So the site stack (web, api, workers, webhook
receiver) needs only a **general-purpose VPS; India co-location is NOT REQUIRED for it.**

**The host is nevertheless an Indian one: a Hostinger India VPS (D-180).** Read the two
sentences together, because they are not in tension and the difference matters when
somebody quotes one of them: co-location is not a *requirement* of this stack, and the
founder bought it anyway. What that buys is one leg of the residency question and not the
question — the R2 buckets are hinted `apac`, i.e. deliberately placed in Asia-Pacific and
deliberately NOT in India, because R2 has no India jurisdiction to place them in (D-450;
`AWS_REGION=auto` is the signature scope and never said anything about placement, which
is what this line used to cite), Bolna **documents its whole platform as US-hosted by
default** (*"By default, Bolna processes calls on infrastructure in the US (AWS us-east-1)"*,
`bolna-findings/mirror/pages/concepts/security.md:29` — which is broader and better sourced
than the recording-URL observation this line used to carry, and their India option is
Enterprise-gated and foreclosed by our BYOK posture, D-415), and
Resend and Sentry are operated outside India, so **an Indian host does not make the data
plane India-resident and nothing here may claim it does** (D-180, LEGAL-SURFACE F-1).

Everything below that reasons from a EUROPEAN VPS — chiefly the ~150 ms worked example in
the amendment — was an argument about the host D-25 assumed, not about the one being
rented. The in-call carve-out it reaches survives on its own merits; the latency figure
does not, and is left in place struck rather than silently re-numbered, because a number
nobody re-measured is worth less than the record that it went stale.

The India-latency requirement survives in one place: **any in-call-path service**.
With D-28 (RAG/memory = managed API service), the likely M3 shape is the engine calling
the provider directly — putting NOTHING of ours in the call path.

> ⚠ **AMENDED (Aug 2026, after D-38 + SURFACES §2b).** "Nothing to co-locate" no longer
> holds unconditionally. **In-call actions put our endpoint in the audio path**: when the
> agent books a slot, sends a WhatsApp mid-call, or hits a custom API, the *engine* calls
> *us* while the caller waits. ~~A Hetzner-class European VPS answering a Bolna-India call
> adds ~150ms each way — enough to blow an in-call tool budget on its own, before our
> handler does any work.~~ **Struck by D-180**: the host is in India, so this particular
> figure is measuring a machine nobody is renting. The CONCLUSION below survives without
> it, on a different and weaker argument — an in-call endpoint's budget is 100ms total
> (CLAUDE.md), so it wants to be near the engine whatever the baseline is, and "near" is
> now a question to answer by measurement rather than one this paragraph already answered.
>
> Consequence, decided here so it is not discovered late: **the moment we ship the first
> in-call action, that endpoint (and only that endpoint) moves to an India-region host** —
> the same carve-out already reserved for the M3 RAG endpoint. It is a `voice-runtime`
> concern, which is why `hooks.calevate.tech` already has its own subdomain and its own
> relocation story (§1). The site stack does not move.
>
> Until an in-call action ships, the original conclusion stands: nothing of ours is in the
> call path, and the site can live anywhere. **Measure before relocating** (D-39: measure
> latency before optimising it) — but budget for the move rather than assuming it away.

Db: **host PostgreSQL 16 on the VPS** (D-26, raghava-proven; managed PG rejected for now).
Edge: **Cloudflare proxied (orange), Full (strict)** (D-27).

## 1. Target topology

One dedicated VPS (do not share with client production sites — isolation), **Ubuntu 24.04
LTS** (D-472). Sizing is §2b — the STARTER is 1 vCPU / 4 GB and scales up in place.

> **Why 24.04 and not 22.04**, which this line used to say. Three reasons, in the order
> they would cost. **(1) Python.** `requires-python = ">=3.12,<3.13"`; 24.04 ships 3.12,
> 22.04 ships 3.10. §2's "Python is NOT needed on the host" is false — D-188 found
> `scripts/backup/app-python.sh` and `scripts/bootstrap_admin.py` both need it, and the
> backup script DELIBERATELY refuses to fall back to a system interpreter without the
> app's venv. On 22.04 that venv needs a non-default interpreter before backups can alarm.
> **(2) The restore drill only ever ran on 24.04.** Every `docs/evidence/restore-drill-*`
> preflight records `postgres 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)` — the disaster-recovery
> path, the one thing that must work on the worst day, has been exercised on that archive
> and no other. **(3) nginx is NOT a reason either way**, and it is worth saying so: the
> config needs `http2 on;` (1.25.1+), 22.04 ships 1.18 and 24.04 ships 1.24, so BOTH are
> below the floor and the nginx.org repository is required on either — `preflight_plan`
> refuses below `NGINX_MIN_VERSION` before anything is built.


```
Cloudflare (proxied, Full strict, origin locked)
   │
nginx (host) ── admin.calevate.tech ─┐
   │            app.calevate.tech  ──┼──▶ web (Next.js, pm2, :3000)
   │            api.calevate.tech ───▶ api container (:8000)
   │            hooks.calevate.tech ─▶ voice-runtime container (:8100)
   │
Docker Compose (project: calevate): api · voice-runtime · workers · redis
Host: PostgreSQL 16 · pm2 (web) · certbot · GitHub Actions runner
           (pgvector only if the D-28 bake-off fails — it is contingency, not the plan)
Object storage: Cloudflare R2 (recordings, raw payloads, exports) — location hint `apac`
```

- Python services (api, voice-runtime, workers) run in Compose — one image, three
  services. Redis in Compose with **no published host ports** (raghava rule).
- Postgres on the host; containers reach it via `host.docker.internal`
  (`extra_hosts: host.docker.internal:host-gateway`); Redis by service name.
- web runs under pm2 (`calevate-web`), not Docker (raghava-proven; `next build` peaks
  >2GB — the VPS needs ≥4GB RAM + 2GB swap or the runner gets OOM-killed mid-build).
- `hooks.calevate.tech` is voice-runtime's public face for engine webhooks +
  (later) in-call tool endpoints. Separate subdomain so its nginx location policy
  (never maintenance-gated, always reachable) and its M3 relocation are clean.

## 2. VPS baseline (once per VPS — raghava §2 verbatim)

Packages: Docker Engine + Compose plugin (v2.24+ for `!reset`), **nginx ≥1.25.1**, certbot,
PostgreSQL 16 (pgvector optional — D-28 contingency), Node 22 (for web builds + pm2;
see §7a — prefer building in CI), ~~Python is NOT needed on the
host (api/workers run containerized; builds happen in Docker)~~ — **struck by D-188, see
below**, jq, `systemd-timesyncd`
(webhook ±5-min skew checks depend on it).

> **"Python is NOT needed on the host" is false, and believing it costs backup alerting
> (D-188).** It is true of the three SERVICES — api, voice-runtime and workers all run
> from the image, and migrations run from it too (`compose --profile migrate`), which is
> the property §4a wants and which nothing here weakens. It is false of the host-side
> tooling this repository also ships, and there are two kinds:
>
> * **`scripts/backup/app-python.sh`**, sourced by `alert-to-app.sh` and `heartbeat.sh`.
>   It resolves `${CALEVATE_PYTHON:-$ROOT/.venv/bin/python}` and, finding nothing,
>   exits `78` with `app-python: no interpreter at …`. `notify.sh` DEFAULTS its sink to
>   `alert-to-app.sh`, so on a host built to the struck sentence **every backup alarm —
>   a failed base backup, a stalled WAL archive, the 15-minute health check — reaches
>   journald and nobody else.** The mechanism is not broken; it is uninstalled, and it
>   fails loudly into a log no one is tailing at 4am.
> * **`scripts/bootstrap_admin.py`**, whose §7a invocation is written as
>   `uv run python -m scripts.bootstrap_admin`. There is no `uv` and no venv on a host
>   built to §2, so as written it cannot run — **and it is the only way to create the
>   first administrator**. Prefer the container form, which needs nothing on the host and
>   is the same shape the deploy already uses for `scripts.seed`:
>
>   ```sh
>   docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
>     --entrypoint python api -m scripts.bootstrap_admin --email you@example.com --role superadmin
>   ```
>
> So: **the host needs Python 3.12 and `uv sync --all-packages` in the deploy root IF the
> backup alert relay is to reach anybody** — which OPERATIONS §8's "backups verified"
> requires — and otherwise does not. `runbooks/first-deploy.md` states it as a step rather
> than leaving it to be discovered. The alternative (a container-based relay) is rejected
> for now and named rather than assumed away: `alert-to-app.sh` runs on the DATABASE host
> as the `postgres` user, deliberately outside the compose project, and giving that user
> docker socket access to send an email would be a privilege trade far worse than the
> problem.

> **The nginx floor is 1.25.1 and it is not a preference — it was ≥1.24 here and both
> documented baselines were versions this config cannot load (D-188).**
> `infra/nginx/calevate.conf.template` uses the standalone `http2 on;` directive in all
> four TLS server blocks. That directive **appeared in nginx 1.25.1**, replacing the
> `listen ... http2` parameter deprecated in the same release. An older binary does not
> warn and does not ignore it: `nginx -t` answers `unknown directive "http2"` and **no
> server block loads at all** — the whole edge, not one vhost. Measured, not read:
> nginx/1.24.0 fails at that line, and the identical rendered set is `test is successful`
> on nginx/1.27. **Ubuntu 22.04 ships 1.18 and 24.04 ships 1.24**, so §1's "Ubuntu 22.04"
> plus a stock `apt install nginx` produced a host that could never serve the site. A
> stock VPS therefore needs the nginx.org mainline/stable repository, and that is now the
> first thing §9 step 5 checks. `scripts/vps-deploy.sh::preflight_plan` refuses below
> `NGINX_MIN_VERSION` before anything is built, migrated or swapped. **The template is
> right and must not be "fixed" backwards** to `listen 443 ssl http2` — that spelling is
> deprecated and warns on every reload, including the ones logrotate and certbot trigger.

Hardening (all raghava-proven): non-root deploy user in `docker` group; SSH
`PermitRootLogin no` + `PasswordAuthentication no`; ufw inbound 22/80/443 only;
fail2ban; unattended-upgrades; 2GB swap in `/etc/fstab`; `pm2 startup` once;
`systemctl disable --now redis-server` (Redis lives in Compose only); remove stock
nginx `sites-enabled/default` and install the `000-default.conf` pattern (§5); **the
sudoers policy and the root-owned scripts it names** (`infra/privileged/`, §11) — the deploy
account gets exactly one grant and it takes no arguments; **the daily hygiene timer**
(`infra/hygiene/`, §7) and the journald cap that goes with it.

> **ufw does not contain Docker, and the list above reads as though it does.** Docker
> writes its published-port rules into `nat`/`FORWARD`, which is upstream of the `INPUT`
> chain ufw filters, so **any container `ports:` mapping is reachable from the internet
> regardless of "inbound 22/80/443 only"**. That is why `compose.prod.yml` publishes redis
> nowhere and binds api/voice-runtime to `127.0.0.1:` explicitly rather than relying on the
> firewall, and why the dev `docker-compose.yml` — which publishes Postgres, redis and
> MinIO on all interfaces with committed passwords — declares its own compose project name
> (`calevate-dev`) and is refused by `preflight()` if that name goes missing. Treat every
> `ports:` line as a hole in the firewall, because it is one.

Directory layout: `/var/www/calevate/` = monorepo git root (our apps/ layout inside),
`/var/www/calevate/storage/` for any local artifacts. Ports: web 3000, api 8000,
voice-runtime 8100 (container-internal = host, single-tenant VPS so no slot offsets).

## 2a. Process count and connection budget (D-55 — the ack budget is a SIZING rule)

Hard rule 3's `ack < 500ms` is not a property of the handler alone. The handler's cost
is pinned and small (3 database statements + 2 Redis ops per delivery,
`tests/voice_runtime_ack_budget_test.py`); what breaches the budget is **how many
deliveries share one event loop**. Measured, not assumed (methodology and full numbers
in D-55):

> A voice-runtime process is CPU-saturated on ONE core from about 8 concurrent
> deliveries upward — ~3.5ms of CPU per delivery, spread across psycopg, SQLAlchemy,
> Starlette, redis-py and asyncio with no single hotspot. So it behaves as a single
> server queue and latency follows Little's Law:
>
>     ack_p50  ≈  in-flight deliveries  ÷  acks-per-second per process

On the measurement host (4 vCPU, Postgres on the same box, uvicorn + uvloop, one
worker) that rate was **≈250 acks/s per process**, and the measured latencies fit:

| in flight | 25 | 50 | 100 | 150 |
|---|---|---|---|---|
| measured ack p50 | 63–85ms | 168–186ms | 275–422ms | 531–589ms |

**The rule.** Let `T` = acks/s for ONE process on the target host. Then

    max in-flight per process for a 500ms ack  =  0.5 x T        (≈125 at T=250)
    processes needed                           =  peak in-flight ÷ (0.5 x T)
    plan at half that ceiling                  →  processes = peak ÷ (0.25 x T)

D-32 records Bolna at **100 concurrent on Pilots and 250+ in production** — one
campaign's calls hanging up together is exactly a burst of in-flight deliveries. (The 100
is a plan claim from their marketing pricing page; their documentation publishes 2
concurrent on free and "Starts at 10" on paid, `bolna-findings/mirror/pages/pricing/outbound-calling-concurrency.md:15,19`,
and the account's real number is on `GET /user/me`. The sizing below stands on the 250+
production datapoints, which are the conservative half.) So:

| environment | peak in flight | processes | why |
|---|---|---|---|
| staging / pilot | 100 | **2** | one process meets 500ms only at p50 with no headroom |
| production | 250 | **4** | 62 in flight each → ~250ms p50, half the budget spent |

Run it as `uvicorn main:app --app-dir apps/voice-runtime --workers N`. **Never more
workers than vCPU** — each one saturates a core, so oversubscribing trades throughput
for context switching. 4 workers therefore implies a ≥4 vCPU host; on a smaller box the
honest answer is fewer workers and a lower supported concurrency, not more workers.
Confirmed rather than assumed: at 100 in flight, one worker gave p50 275–422ms / max
640ms, two workers gave **p50 33ms / p95 ~200ms / max 318ms**.

**Re-measure on the target host before quoting T.** The shape generalises, the number
does not — it is a CPU rate and it moves with the CPU. The reproducible procedure is in
D-55; `X-Ack-Ms` on every response and the `webhook_ack_ms` metric are the instrument,
so this can be measured in staging with real traffic and no extra tooling.

**Connection budget.** Every process builds its own pool, so the cluster total is
`DB_POOL_SIZE x processes` and it must fit under Postgres `max_connections`. There is no
overflow (`apps/api/db/session.py` — overflow connections are single-use and cost ~6ms
of CPU each to re-authenticate under `scram-sha-256`, which is latency taken straight out
of the ack budget). Size each pool by Little's Law again: measured connection HOLD time
per delivery is ~10ms uncontended and ~35ms with the loop busy, so a process running at
250 acks/s keeps `250 x 0.035 ≈ 9` connections busy. 12 is that with headroom; going far
beyond it buys nothing but Postgres backends.

| service | processes | `DB_POOL_SIZE` | connections |
|---|---|---|---|
| voice-runtime | 4 | 12 | 48 |
| api | 2 | 16 | 32 |
| workers (ARQ) | 1 | 16 | 16 |
| migrations, psql, ops | — | — | ~5 |
| **total** | | | **~101** |

PostgreSQL's default `max_connections = 100` (minus 3 superuser-reserved) cannot hold
that, so **set `max_connections = 200` on the VPS** alongside the §2 baseline — or cut
the pools, but do the arithmetic first and re-check it whenever a worker count changes.
A pool exhausted at the receiver is not a slow ack: it is a 503 at the durable deadline
and a call that waits for the 10-minute poller.

## 2b. Host profiles (D-472) — the box we START on, and the trigger to leave it

§2a sizes the box for PRODUCTION concurrency and is unchanged. This section names the
smaller box the product LAUNCHES on, because "4 vCPU" was the only number written down and
that is not what the first months need. **Scaling up is a resize, not a migration** —
Hostinger resizes a KVM plan in place, the topology below is identical on every profile,
and nothing in this repo pins a core count. Move when the trigger fires, not before.

| | **STARTER (KVM1)** | KVM2 | PRODUCTION |
|---|---|---|---|
| vCPU / RAM | **1 / 4 GB** | 2 / 8 GB | ≥4 / ≥8 GB |
| Disk | 50 GB NVMe | 100 GB | 100 GB+ |
| `voice-runtime --workers` | **1** | 2 | 4 |
| Supported peak in-flight | ~1–20 (test + first client) | ~100 (pilot) | 250+ (§2a) |
| `DB_POOL_SIZE` | **6** | 12 | 12–16 (§2a table) |
| Postgres `max_connections` | **100** | 200 | 200 |
| Postgres `shared_buffers` | **768 MB** | 2 GB | 2 GB |
| Swap (`/etc/fstab`) | **4 GB** | 2 GB | 2 GB |
| GitHub Actions runner on-box | **NO** | no | no |

**Why the starter is honest and not a corner cut.** §2a's 500 ms breach is a CONCURRENCY
failure, not a baseline one: its own measured table gives one worker **63–85 ms at 25
in-flight** and only reaches 531–589 ms at 150. Bringing the site online, onboarding and
testing never approach that. What the starter cannot do is absorb a campaign whose calls
hang up together — which is the trigger below, and is a resize away.

**Two settings on the starter are not optional, and neither is about traffic.**

1. **4 GB of swap, not 2.** `next build` peaks over 2 GB (§1) and the image is built ON
   the box, beside a resident Postgres, Redis and three containers. On 4 GB of RAM the
   build is what OOMs, on the first deploy, before a single call exists. NVMe is cheap and
   there are 50 GB.
2. **`DB_POOL_SIZE=6`, not the default 16.** §2a's pools are sized for 7 processes; the
   starter runs 3. At the default that is 48 idle Postgres backends costing RAM the build
   spike needs — the pool is not free memory just because it is idle.

   ⚠ **`DB_POOL_SIZE=6` in `.env` DOES NOTHING, and this row said to put it there.**
   `compose.prod.yml` sets `DB_POOL_SIZE` in each service's `environment:` block
   (`:84,:134,:153`), and a compose `environment:` entry overrides `env_file:` — so the
   `.env` value is read and discarded. What those blocks interpolate is
   **`API_DB_POOL_SIZE`, `VOICE_RUNTIME_DB_POOL_SIZE` and `WORKERS_DB_POOL_SIZE`**, each
   defaulting to §2a's production number; compose resolves them from the project `.env`
   at parse time. Those three are the knobs. Set them, not `DB_POOL_SIZE`, and the
   `migrate` one-shot is fixed at 5 (`:181`) and is not tunable — correctly, it runs
   alone between the build and the swap.

**Better than either: stop building on the box.** Build the image in GitHub-hosted CI,
push it to a registry, and have the VPS pull. Then `docker build` and `next build` never
run beside a live call and 4 GB stops being tight — which also removes the reason §1 wants
the Actions runner co-located. This is the recommended starter shape; the swap and pool
figures above are what makes on-box building survivable if you keep it.

**THE TRIGGER TO SCALE UP — read it off the instrument, do not guess.** `X-Ack-Ms` is on
every voice-runtime response and `webhook_ack_ms` is the metric (§2a). Resize when EITHER:

- `webhook_ack_ms` p95 goes above **250 ms** — half the hard-rule-3 budget, spent; or
- a client starts running outbound CAMPAIGNS rather than taking inbound calls, because a
  campaign is the burst §2a sizes for.

Then: resize the plan, raise `--workers` to match the new vCPU (**never more workers than
vCPU**), and re-measure `T` on the new host before quoting any concurrency number. §2a's
`T ≈ 250 acks/s` was measured on 4 vCPU and does not transfer down — it is a CPU rate.


## 3. CI/CD (raghava model, adapted)

**CI workflow** (`.github/workflows/ci.yml`, ubuntu-latest): services postgres:16
(pgvector image) + redis:7 with healthchecks → `uv sync --all-packages` →
`make check` (ruff, mypy strict, pytest incl. RLS zero-rows + engine conformance,
web typecheck) → alembic upgrade head against the service DB → smoke test.

**Deploy workflow** (`.github/workflows/deploy.yml` — BUILT, and disabled until a repo
Variable says otherwise): `workflow_run` on CI success on main + `workflow_dispatch`.
Runs on the **self-hosted runner installed on the VPS** (label `calevate-vps`) — the
runner polls GitHub via outbound HTTPS; **no inbound SSH ever**. Paths in Secrets
(`VPS_CLIENT_PATH=/var/www/calevate`), booleans/labels in Variables (raghava rule:
paths are Secrets, flags are Variables). Concurrency group `deploy-production` prevents
overlapping deploys, with `cancel-in-progress: false` — cancelling a deploy between the
migration and the swap would manufacture the half-deployed state §4 exists to prevent.

**It cannot fire by accident, and that is enforced four times over**: repo Variable
`VPS_DEPLOY_ENABLED` must be the string `true` (unset = every job skipped, so merging the
file changes nothing); the job re-checks `workflow_run.conclusion == 'success'`, because
`workflow_run` fires on FAILED runs too and that is the classic way a deploy workflow
ships a red build; `head_branch` must be `main`, or CI on a pull request would deploy the
PR; and `environment: production` gives a required-reviewer rule somewhere to attach
without editing the workflow. **No credential is wired** — the runner is on the box, so
there is no SSH key, and application secrets are read from `.env` on the host.

**It uses no third-party action — not even `actions/checkout`** (hard rule 9). It does not
need one: the deploy target is the runner's own host and the checkout already lives at
`VPS_CLIENT_PATH`. Every action in a deploy workflow runs with production permissions on
the production host; the cost of avoiding that entirely is two lines of bash.

**One job, not the three this section originally sketched.** The property those three
bought — a docs-only change must not rebuild Docker — is kept, but it is enforced inside
`scripts/vps-deploy.sh`, which diffs the last deployed SHA against HEAD through an
explicit path→component map and exits before building when nothing maps. Three jobs would
need three `paths:` filters here, i.e. a second copy of that map in a different language,
drifting the first time a directory moves. The hard-rule-3 property (an `api` change never
restarts voice-runtime) comes from the same map plus `--no-deps`, not from job separation;
a single component is still deployable alone via `workflow_dispatch` with
`components: voice-runtime`.

**Rollback is reachable from the workflow, which is what makes the kill switch a last
resort rather than the first move.** `workflow_dispatch` takes an optional `commit_sha`;
when it is set the job runs `scripts/vps-deploy.sh --checkout <sha>` instead of
`--expected-sha <ci-sha>`, and the two are mutually exclusive by construction (§3b).

### 3a. The self-hosted runner — the exact steps, none of which has been run

**Nothing below has been executed.** There is no VPS, no runner, and no repo Secret. This
is a checklist for a human with a shell on the box, written out because the raghava
teardown (`docs/evidence/raghava-deploy-teardown.md`) shows every one of these choices
being made badly somewhere, and because a runner is the one component here that holds a
credential to this GitHub repository.

**As which user.** The `calevate` deploy user from §2 — the one that owns
`/var/www/calevate` and is in the `docker` group. NOT root: the runner executes whatever a
workflow file says, so a root runner turns every merge into root on the production host.
NOT a second service account either, because the deploy has to be able to write the
checkout and talk to the Docker socket, and a runner that needs `sudo` for the ordinary
path is a runner whose sudoers entry grows until it is root with extra steps. The only
privileged thing the deploy does is install nginx config, and that goes through
`infra/privileged/` — one command, empty argument list (§11).

1. **Get a registration token.** GitHub → repo → Settings → Actions → Runners → *New
   self-hosted runner* → Linux x64. The page shows the current release URL and a token
   that **expires in one hour**. Do not reuse a token from an older set of instructions.

2. **Install it, as the deploy user**, in a directory named for this project — one runner
   directory per repository, never a `cp -r` of a configured one (a copied runner carries
   the other repo's credentials in `.credentials` and will service its jobs):

   ```sh
   sudo -iu calevate
   mkdir -p ~/actions-runner-calevate && cd ~/actions-runner-calevate
   # URL and version exactly as the GitHub page shows them
   curl -o runner.tar.gz -L https://github.com/actions/runner/releases/download/v<X.Y.Z>/actions-runner-linux-x64-<X.Y.Z>.tar.gz
   tar xzf runner.tar.gz && rm runner.tar.gz
   ./config.sh --url https://github.com/<org>/calevate-site \
               --token <REGISTRATION_TOKEN> \
               --name calevate-vps \
               --labels self-hosted,calevate-vps \
               --unattended --replace
   ```

   **The label is not optional and is not a variable.** `.github/workflows/deploy.yml`
   targets `[self-hosted, calevate-vps]` literally. The reference implementation reads it
   from a repo Variable with a fallback to bare `self-hosted`, which is right for a
   template synced across many client repos and wrong here: the fallback is a misroute
   waiting for the day a second runner registers anywhere in the org, and this repo has
   exactly one VPS. A label typo therefore shows up as a job that queues forever, which is
   loud, rather than as a deploy landing on somebody else's host, which is not.

3. **Survive reboot.** The runner is a systemd unit, installed by its own script — this is
   the one place `sudo` is used, and it is used as the deploy user's shell:

   ```sh
   sudo ./svc.sh install calevate     # unit runs AS calevate, not as root
   sudo ./svc.sh start
   sudo ./svc.sh status               # must say "active (running)"
   systemctl is-enabled actions.runner.*.service   # must say "enabled"
   ```

   `svc.sh install <user>` writes `/etc/systemd/system/actions.runner.<org>-<repo>.<name>.service`
   with `User=calevate` and `WantedBy=multi-user.target`. Verify both in the unit file
   before believing it; `enabled` is what makes it come back after a reboot, and `active`
   alone does not.

4. **Confirm it is Online** in Settings → Actions → Runners, with the label
   `calevate-vps` shown beside it. Only now is it safe to restrict SSH (§2): deploys stop
   needing port 22 entirely, because the runner dials OUT to GitHub over 443 and GitHub
   never opens a connection to the VPS. There is no deploy key, no `VPS_SSH_PRIVATE_KEY`,
   and nothing in GitHub that can reach this host if the runner is stopped.

5. **Set the repo Secrets and Variables** (Settings → Secrets and variables → Actions).
   The split is raghava's convention and worth keeping: **paths are Secrets, flags and
   hostnames are Variables**, because a Variable is readable by anyone with repo read
   access and a path names our directory layout on a live host.

   | Type | Name | Value | Read by |
   |---|---|---|---|
   | Secret | `VPS_CLIENT_PATH` | `/var/www/calevate` | every step |
   | Variable | `VPS_DEPLOY_ENABLED` | `true` — **set this LAST** | the job `if` |
   | Variable | `NGINX_AUTO_RELOAD` | `1` only if you want CD to reload the edge; unset = render and print | `render_nginx` |
   | Variable | `ROOT_DOMAIN` | `calevate.tech` | `render_nginx` |
   | Variable | `TLS_LIVE_DIR` | `/etc/letsencrypt/live/calevate.tech` | `render_nginx` |
   | Variable | `ORIGIN_CERT_PATH` | `/etc/ssl/calevate/origin.pem` | `render_nginx` |
   | Variable | `ORIGIN_KEY_PATH` | `/etc/ssl/calevate/origin.key` | `render_nginx` |

   That is the whole list, and `scripts/check_deploy_workflow.py` fails CI if the workflow
   ever reads a name this table does not carry. **No application secret is here and none
   ever will be**: those live in `/var/www/calevate/.env`, placed by a human from the
   secrets manager (§6), and no workflow writes that file.

6. **Prove it before trusting it.** With `VPS_DEPLOY_ENABLED` still unset, run the
   workflow by hand from the Actions tab with `dry_run: true`. It must reach *Deploy* and
   print a plan. Then set `VPS_DEPLOY_ENABLED=true` and push a no-op commit; §9 step 8 is
   green when CI passes, the deploy job starts by itself, and the summary banner names the
   commit you pushed.

**Turning it off in an incident.** Settings → Variables → `VPS_DEPLOY_ENABLED` → `false`
(or delete it). Every job is skipped from the next event onwards; a run already in flight
is NOT cancelled, and that is deliberate — cancelling between the migration and the swap
manufactures the half-deployed state §4a exists to prevent. To stop a run in flight, stop
it at the box (`sudo ./svc.sh stop` in the runner directory) and finish the deploy by hand.
Prefer a rollback (`commit_sha` dispatch, §3b) over the kill switch when the problem is the
release rather than the pipeline.

**Revoking the runner** — do this if the VPS is rebuilt, sold, or suspected:

```sh
sudo ./svc.sh stop && sudo ./svc.sh uninstall
./config.sh remove --token <REMOVAL_TOKEN>    # Settings -> Runners -> the runner -> Remove
```

If the box is gone and you cannot run `config.sh remove`, delete the runner from
Settings → Actions → Runners; the registration is server-side and removing it there is
what actually revokes the credential. The `.credentials` file left on a disposed disk is a
long-lived token to this repository, so a wipe is not a substitute for the removal.

**Ongoing cost.** GitHub deprecates old runner versions once or twice a year and emails
about it. Re-registering is steps 1–3 again in the same directory (`--replace` makes it
idempotent), about five minutes.

### 3b. Rolling back without an SSH session

A deploy path with no reachable rollback is a deploy path whose only incident control is
the kill switch, and the kill switch does not undeploy anything. So `workflow_dispatch`
takes an optional **`commit_sha`**: Actions → Deploy → *Run workflow*, paste the previous
good sha, run it. `.deploy-state/history` on the box is where that sha comes from, and the
failure banner of the run that broke prints the same advice.

The workflow does no git work of its own. It passes `--checkout <sha>` to
`scripts/vps-deploy.sh`, which fetches, moves the checkout to exactly that commit, and
deploys it — **one flag, in the one file that already knows how to move a deploy
checkout**. It was two commands (`git checkout` then `--all --no-pull`) until the workflow
needed to reach it, and a workflow doing its own `git checkout` would be a second copy of
that knowledge in a file nobody runs by hand; `scripts/check_deploy_workflow.py` now
refuses one. `--expected-sha` is deliberately not passed alongside it: the flag that
chooses the commit and the flag that verifies it would be one value checking itself.

Three things follow from that, all of them deliberate:

- **The image is usually already there.** Each deploy tags `calevate/app:<12-char sha>`
  and the newest five are kept, so a rollback is a swap and not a serial `docker build` on
  a host that is by definition having a bad day.
- **The schema does not roll back with the code**, and by hard rule 8 it does not need to.
  The migrate step recognises a database that is ahead of the artefact, prints
  **MIGRATIONS SKIPPED**, and carries on to the swap (§4a).
- **The checkout is left detached, and the next automatic deploy REFUSES.** Otherwise the
  first green CI after a rollback pulls back to the branch tip and redeploys the release
  you just rolled away from, unattended, with nobody deciding it. The refusal names both
  ways out: another `commit_sha` dispatch to roll forward onto a fix, or
  `git -C /var/www/calevate checkout main` to resume automatic deploys.
  `tests/deploy_checkout_flag_test.py` drives both halves against a real git tree.

`commit_sha` accepts 7–40 hex characters and refuses a branch or tag name, because a ref
names whatever it points at when the line runs and this flag exists to deploy one specific
artefact.

**Unrun.** No rollback has ever been executed on a host — the flag's git behaviour is
tested, the deploy it triggers is not (§4d, `docs/evidence/push-to-deploy.md`).

## 4. vps-deploy.sh — BUILT (`scripts/vps-deploy.sh`)

The artefact this section used to specify now exists, together with the two things it had
no way to work without: a **`Dockerfile`** (one image, three services — see its header for
why one) and **`compose.prod.yml`** (api · voice-runtime · workers · redis; Postgres stays
on the host per D-26, web stays under pm2 per §1).

```
scripts/vps-deploy.sh                       # deploy whatever changed since the last deploy
scripts/vps-deploy.sh --all                 # everything
scripts/vps-deploy.sh voice-runtime         # exactly one component
scripts/vps-deploy.sh --dry-run --all       # resolve and print the plan, change nothing
scripts/vps-deploy.sh --expected-sha <sha>  # abort unless HEAD is that commit
```

Sequence, with the Calevate substitutions (uv/alembic for npm/prisma):

1. **Preflight, all refusals**: `.env` present (deploy scripts NEVER write secrets; abort
   if missing, warn if not mode 600), the two object-store credentials **and `PLATFORM_KEK`**
   present in it — by name, never by value; the KEK is not in `BOOTSTRAP_REQUIRED`, so without this a
   deployment that never had the key boots clean and answers `/healthz`;
   `runtime_config_missing_keys` does name it, so `/healthz/ready` goes 503
   `config_missing` — but only once the container is already swapped in, which is why the
   refusal belongs here and not only there — compose file and Dockerfile present, docker compose v2 present, the dev
   `docker-compose.yml` carrying a project name that is not the production one (§2's ufw
   caveat is why that matters), **checkout clean** (a deploy from an edited tree ships code
   CI never saw), and the Cloudflare IP list not older than 180 days (§5.3). Free disk is
   REPORTED here and DECIDED at step 5, because a refusal that runs before `git pull` is a
   refusal that cannot reclaim.
2. `git pull --ff-only`; **abort if HEAD ≠ `--expected-sha`**. CI validates one commit and
   `main` can move before the runner starts; without this gate that race ships silently.
   The image for this deploy is tagged here: `calevate/app:<12-char sha>`, exported as
   `CALEVATE_IMAGE_TAG` so every `build`, `run` and `up` in the deploy resolves the same
   artefact. It used to be one mutable `:local` tag that nothing set, which made a rollback
   a full rebuild on a degraded host and let an api-only build replace the image
   `voice-runtime` would use at its next recreate.
3. **Resolve the component plan** from `git diff <last deployed SHA> HEAD` through the
   path map in `components_for_paths`. This is where hard rule 3 is enforced — see §4c.
   **Then `preflight_plan`, a SECOND refusal step, and a separate one on purpose**: with
   `web` in the plan, `apps/web/.env.local` and `pnpm`/`pm2` on PATH; with `nginx` in it,
   the four exported variables `render_nginx` needs (`ACME_WEBROOT`, the fifth, has a real
   default). These cannot be asked in step 1 — the plan does not exist yet — and when they
   were written there anyway, guarded by `in_plan`, they read an unset array: under
   `set -u`, bash expands an unset array to nothing rather than erroring, so `in_plan`
   answered "no" to every question and **every check inside those two blocks silently never
   ran**. They still run before anything is built, migrated or swapped, which is the
   property that matters: each was previously discovered at the web step, after migrations
   and after all three container swaps. `--dry-run` runs them too, so §9 step 4's dry run
   is a real preflight rather than a plan printout.
   Two host facts are checked here as well, both stated as rules by this document and
   neither previously verified anywhere: **`VOICE_RUNTIME_WORKERS ≤ nproc`** (§2a — a
   refusal; oversubscribing cores is paid out of the 500ms ack budget) and **2GB of swap
   when `web` is in the plan** (§2 — a warning, since a large-RAM box legitimately needs
   none, and because the OOM killer takes `next build` with no error at all). With
   `NGINX_AUTO_RELOAD=1`, also: nginx installed, both target directories present, the
   staging directory writable, and `sudo -n -l /usr/local/sbin/calevate-nginx-apply`
   answering yes. **That last one is the exact command and not `sudo -n true`**, which the
   sudoers policy in `infra/privileged/` correctly REFUSES — probing with `true` would have
   failed a deploy for holding the right policy. Under CD a sudo that PROMPTS does not fail,
   it holds the deploy open until the job times out, with the containers already swapped.
4. **Dead-container check**: Docker `Dead`-state ghosts break compose's rename-on-recreate
   (§10). The script **detects and refuses with the exact command** rather than running
   the playbook's `sudo rm -rf /var/lib/docker/containers/<id>` unattended — an automated
   `rm -rf` under the daemon's state directory is a bigger hazard than the fault it fixes.
5. **Pre-build disk reclaim, an escalation and not a floor.** `docs/evidence/raghava-deploy-teardown.md`
   §9 row 3 is the finding: their post-build prune only runs after a SUCCESSFUL build, so a
   near-full disk kills the build and the cleanup that would have prevented it never runs —
   every later deploy is then wedged. Ours used to walk into the same trap from the other
   side, refusing at 3GB with two commands printed for a human. The ladder
   (`scripts/deploy/docker-reclaim.sh`, shared with the daily hygiene job) is:
   **tier 0** always — stopped containers *of our compose project*, dangling images, build
   cache capped at 3GB; then, only below **`RECLAIM_PURGE_FLOOR_GB` = 8**, in order,
   stopping at the first rung that clears the floor — **tier 1** the whole build cache
   (costs a slow build), **tier 2** every per-commit image but the newest (costs the cheap
   rollback of step 6), **tier 3** every unreferenced image (costs a cold build). Below
   **`RECLAIM_REFUSE_FLOOR_GB` = 3** after all of that, it refuses, before anything is
   built, migrated or swapped. The order is the design: the cheapest thing to lose goes
   first, and the artefact an incident needs is given up second-to-last. It runs after the
   dead-container sweep (a Dead container holds an image) and whether or not an image will
   be built, because `next build` needs the same disk.
6. **Serial builds** — parallel builds OOM small hosts, and the OOM kills the runner, so
   it reads as a CI flake rather than as a memory ceiling. **Skipped entirely when
   `calevate/app:<sha>` already exists**: preflight has proved the checkout clean, so the
   commit determines the artefact, and the case where it is already there is the case that
   matters — a rollback, on a host that is by definition having a bad day. Force one with
   `docker image rm calevate/app:<sha>`.
7. **Bootstrap-env preflight, run IN the new image** (`validate_bootstrap_env` +
   `Settings()`), before any swap. In the image rather than on the host because what
   matters is what the process about to serve traffic can read.
8. **Migrations** (`compose --profile migrate run --rm migrate`), before the swap — §4a —
   **then the seed** in the same profile. `scripts/seed.py` writes the reserved-slug list,
   the vertical templates and the retention defaults, and until this step existed it ran
   nowhere but `make db-reset`: production had none of them, so the first tenant could
   claim `admin` as a slug and every tenant was created with no retention policy at all.
   Idempotent by construction, so it runs on every deploy rather than only the first.
   **Both are skipped, loudly, when the database is at a revision this image has no script
   for** — i.e. on a rollback, where `alembic upgrade head` cannot resolve the stored
   `alembic_version` at all and used to abort the rollback before it swapped anything.
   §4a has the argument and `scripts/deploy_revision_check` is the mechanism.
9. **Redis, explicitly, before the swap loop and deliberately WITHOUT `--no-deps`.** Every
   swap below passes that flag — correctly, so an api deploy cannot restart the queue
   under a live call — but it was also the only way this stack was ever brought up, and
   `--no-deps` is exactly the flag that tells compose not to walk `depends_on`. So the
   redis container all three services declare a healthy dependency on was created by
   nothing: the first `--all` run started workers against no queue, then swapped api,
   whose `/healthz` pings redis and answers 503, and the deploy died **after** migrations
   had run. `up -d` on a healthy container is a no-op, so this costs a correct deploy
   nothing.
10. **Container swap**, one service at a time, `compose up -d --no-deps <service>`, in the
   order workers → api → voice-runtime (§4b), each followed by a health wait of
   **90×2s** on `/healthz` (§10's lesson: 60s was shorter than a migrate-on-boot, which
   trains operators to ignore red deploys).
11. **web**: `pnpm install --frozen-lockfile` + `pnpm -C apps/web build` + `pm2 reload
    calevate-web --update-env`, or `pm2 start apps/web/ecosystem.config.cjs && pm2 save`
    when pm2 has never heard of the app — `reload` exits non-zero on an unregistered
    process, and nothing in this repository had ever run `start`, so a first deploy on a
    fresh host aborted here with the database already migrated and all three containers
    already swapped. Then a health poll on :3000.
12. **nginx**: envsubst render → placeholder check → stage into
    `/var/lib/calevate/nginx-staging` → `sudo -n /usr/local/sbin/calevate-nginx-apply`,
    gated on `NGINX_AUTO_RELOAD=1`. Unset, it renders and prints the install commands.
    **The privileged half is a root-owned script the deploy account invokes with NO
    arguments** (§11) — it, and not the deploy, backs up the set on disk, installs, runs
    `nginx -t`, restores the previous files if the test fails (removing the ones this
    deploy introduced), re-tests, and only then reloads. The backup is not decoration:
    `nginx -t` can only test what is already in `/etc/nginx`, so a rejected render used to
    be left installed — the running edge was fine and the **next** reload was not, and
    reloads come from logrotate and from certbot's renewal deploy hook (§9.5a step 5) days
    later. The staging directory is emptied before each render, so a file a previous deploy
    produced and this one does not stops being installed instead of surviving forever.
13. Post-deploy prune — **tier 0 of the same ladder** plus app-image tags beyond the
    newest five (per-commit tags are not dangling, so nothing else would ever reclaim them;
    a tag referenced by any container is never a candidate, and a refusal warns rather than
    failing a deploy that has already succeeded). Tiers 1-3 are deliberately unreachable
    here: the deploy has succeeded, there is nothing to make room for, and tier 2 would
    throw away the rollback artefact this deploy just created. Then record SHA, image ref,
    migration verdict and plan to `.deploy-state/history`, and print the summary.

**The whole sequence runs under one host lock** (`scripts/deploy/host-lock.sh`), taken
before step 1 and released by the kernel when the process exits, however it exits. The
other holder is the daily hygiene timer (§7): its prunes are host-global, and a prune
racing a `docker build` removes the layer the build is about to reference, which fails with
a message naming neither the prune nor the timer. `flock` rather than a pid file, because
the pid file's cleanup is exactly what does not happen when an OOM takes `next build`.

A failed step prints a banner naming the step, the exit code and the alembic revision,
and stops — nothing after it runs, there is no automatic rollback, and
**`runbooks/deploy-failed.md`** is ordered by which step failed, because the recovery for
a failed build and a failed swap are not the same procedure.

### 4a. Migration ordering, and why it is this way round

**Migrations run BEFORE the container swap. Never after, and never automatically undone.**

Hard rule 8 forbids dropping a column in the same release that stops writing it. That
rule is exactly the statement *the OLD code can always run against the NEW schema* — an
expand-only migration adds things the old code ignores and removes nothing it still uses.
It says nothing about the reverse: **new code against the old schema is protected by
nothing**, and a release that reads a column added this release fails on every request
until the migration lands.

So the window between migrate and swap is safe by construction and the window between
swap and migrate is not. That asymmetry is the whole argument, and it is worth stating
because "deploy then migrate" is a defensible ordering in codebases that do *not* have
rule 8 — here it would throw away the property rule 8 buys.

On failure: PostgreSQL has transactional DDL and alembic runs each revision in its own
transaction — because `alembic/env.py` passes `transaction_per_migration=True`, which is
what makes this sentence true; alembic's default is one transaction for the WHOLE run, and
until that line was added a failure at revision 40 discarded the 39 before it. So a
failure leaves the database at the last revision that fully applied — a
valid intermediate state which, by the same argument, the still-running old containers can
serve on. **No automatic downgrade.** A downgrade can drop a column a partially deployed
system has already written to, turning a failed deploy into data loss; it is a judgement,
not a step, and `runbooks/deploy-failed.md` §3 is where that judgement is written down.
The revision is recorded before *and* after precisely so that a manual downgrade has a
target rather than a guess.

**On a ROLLBACK the migrate step is skipped, and that is the same rule read backwards.**
The documented rollback (`--checkout <previous-sha> --all`, §3b) puts the
python services in the plan, which runs migrations — from the older image. If the deploy
being rolled back carried a migration, the database is at a revision that image has no
script for, and alembic resolves `alembic_version` against its script directory before it
computes a path: `Can't locate revision identified by '<rev>'`, exit 255, **the rollback
dead before a single container was swapped, with production still on the broken release**.
Nothing about that was recoverable by trying harder — the older artefact genuinely cannot
migrate to a revision it does not contain, and it does not need to, because rule 8 is
exactly the statement that it can serve on the newer schema. So `run_migrations` asks
`scripts/deploy_revision_check`, inside the image, whether its own chain contains the
revision the database is at; on "no" it prints a MIGRATIONS SKIPPED banner naming the
revision, leaves the schema and the seed alone, records `migrations=skipped-rollback` in
`.deploy-state/history`, and proceeds to the swap. The checker answers with an exit code
rather than a message so that "the database is ahead" and "the check broke" cannot be
confused: only a clean `3` skips, and anything else stops the deploy, because guessing
"rollback" on a forward deploy would swap new code onto an old schema — the one direction
rule 8 does not protect.

### 4b. The swap is low-downtime, not zero-downtime — and what absorbs the gap

`compose up -d --no-deps <service>` **recreates** the container: the old one stops, the new
one starts. That is a gap of a few seconds per service, and the honest thing is to name it
rather than to claim a rollout mechanism this repo does not have.

What is done about it:

- **Order.** workers first (no reader waits on them; a job landing in their gap sits in
  Redis), then api, then **voice-runtime last** — its gap is the only one that costs a
  call, so it is the shortest-lived and the last thing to happen.
- **Graceful stop.** `stop_grace_period` is 30s for api and voice-runtime (each longer
  than its uvicorn `--timeout-graceful-shutdown`, 25s and 20s, so the drain finishes and
  the lifespan's shutdown hooks still get to run) and 60s for workers, so in-flight work
  finishes instead of being killed. The api's was ABSENT until D-182, which meant Docker's
  10-second default against a 25-second drain: every api deploy ended in SIGKILL.
  `tests/worker_reliability_test.py` pins drain < grace for all three services.
- **The safety net already exists.** A delivery arriving in voice-runtime's gap gets no
  ack; whether Bolna retries it is UNSETTLED and we assume not (D-352 — the OSS deliverer
  is a different program from the hosted one and their hosted webhook page states no
  guarantee either way); the reconciliation poller recovers it on a 10-minute
  tick regardless, which is why the gap is survivable under either reading. Leads appear late, not never. This is the same net OPERATIONS §5 leans on.

**Rejected: a blue/green rollout plugin** (`docker rollout` and friends — scale to two,
wait for healthy, drop the old). It is the right shape and it would close the gap, but it
is a third-party CLI plugin installed on the production host, which is a supply-chain
surface (hard rule 9) and a new deployable-shaped dependency. Adopting one needs a
decision-log entry, not a line in a script. Until then the gap is measured at the first
attended deploy and recorded here.

### 4c. How voice-runtime stays decoupled from api (hard rule 3)

Not a caveat — a mechanism, in one reviewable table (`components_for_paths`):

| A change under… | deploys |
|---|---|
| `apps/api/` (crm, billing, admin, …) | api, workers |
| `apps/api/core/` | api, workers, **voice-runtime** |
| `apps/voice-runtime/` | voice-runtime |
| `apps/workers/` | workers |
| `packages/shared/`, `uv.lock`, `pyproject.toml`, `Dockerfile`, `compose.prod.yml`, `alembic/` | all three |
| `apps/web/`, `pnpm-lock.yaml` | web |
| `infra/nginx/` | nginx |

An `apps/api/crm/**` edit therefore does not rebuild, restart or touch the container
answering live calls, and `--no-deps` means the swap cannot walk `depends_on` into it
either. The map is deliberately conservative in the other direction: voice-runtime
*imports* `apps/api/core` and `packages/shared`, so a change to either does deploy it.
That is not coupling — it is the truth about what its process contains, and stating it in
one table is what makes it reviewable. A shared image does not change this; the header of
`Dockerfile` argues why one image is right anyway.

### 4d. What a human must do before the first real deploy

Stated here with pass conditions, the way §7 does for the backup drill, because **none of
this has been run**: no image has been built, no container started, no nginx config
loaded, no migration applied on a VPS.

1. **Pin the uv image by digest.** `Dockerfile` pins `ghcr.io/astral-sh/uv:0.8.17` by
   tag; a tag is mutable. Resolve the digest on a host with registry access and pin it.
   *Pass condition*: the `COPY --from=` line names a `sha256:`.
2. **Build the image once, by hand, and time it.** *Pass condition*: `docker compose -f
   compose.prod.yml build api` succeeds on the target host without an OOM, with 2GB swap
   present.
3. **First deploy attended, with `--dry-run` first.** *Pass condition*: the dry run's plan
   matches what you expected from the diff; the real run reaches the summary banner.
4. **`nginx -t` the rendered config** — never done, no nginx existed where it was written
   (`infra/nginx/README.md` §4). *Pass condition*: `nginx -t` passes and the four
   hostnames answer through Cloudflare.
5. **Measure the swap gap** (§4b) for api and voice-runtime, and write the numbers into
   §4b. *Pass condition*: a number replaces "a few seconds".
6. **Enable CD last.** Register the runner and set the Secrets/Variables per §3a, then
   set `VPS_DEPLOY_ENABLED=true` — only after steps 1–5, and only after one full manual
   deploy has succeeded. *Pass condition*: §9 step 8's full CD cycle verified green.
7. **Drill the rollback once, deliberately, before you need it** (§3b). Deploy a trivial
   commit, then dispatch the workflow with `commit_sha` set to the one before it. *Pass
   condition*: the run reaches the summary banner, `.deploy-state/history` shows the older
   sha, the image was reused rather than rebuilt, and the NEXT automatic deploy refuses
   with the detached-checkout message until `git checkout main` is run on the box. Nothing
   about this has been executed and the script's own tests cannot execute it.

Until step 6, **this repo has a deploy mechanism and no automatic deploys**, which is the
correct state for something nobody has run yet. Step 7 is the one people skip; the first
rollback should not be the first time anybody has seen one.

## 5. nginx + TLS + Cloudflare (raghava config, four adaptations)

Reuse: `client.conf.template` structure (envsubst placeholders), per-route
`limit_req_zone` snippet installed once at `/etc/nginx/snippets/`, security headers
block, TLS settings, maintenance-page machinery (single-hop `error_page 401 =503`,
inline fallback — do NOT re-derive; their HARDENING_HISTORY documents why the obvious
patterns fail), `certbot certonly --webroot` (NEVER `certbot --nginx` — it rewrites
templated config), `000-default.conf` with Cloudflare Origin CA cert on
`default_server` (the 525 fix), `cloudflare-only.conf` origin IP allowlist.

> **STATUS (Aug 2026): the config now lives in `infra/nginx/` and has never been loaded
> by an nginx process.** Read `infra/nginx/README.md` before this section — it is the
> authority on what is there, where each file installs, and what has never been run.
> `scripts/vps-deploy.sh` renders and installs it (§4 step 12). Two items of the
> inheritance above are deliberately NOT built and are named as gaps rather than
> approximated: the **maintenance gate** (its single-hop `error_page 401 =503` shape is
> hard-won and a half-remembered version fails exactly when it is needed — §10 keeps the
> lesson) and **`auth_request`**, which nothing here needs.

Calevate adaptations:
1. **Four server names**: admin./app. → :3000; api. → :8000; hooks. → :8100.
2. **hooks.calevate.tech policy**: never maintenance-gated, never behind auth_request,
   generous webhook rate zone, `client_max_body_size` sized for transcript payloads.
   Same doctrine as their payments-webhook location: provider callbacks must land
   during maintenance windows.
3. **real_ip restoration — fix their documented gap**: `set_real_ip_from` for the
   Cloudflare ranges + `real_ip_header CF-Connecting-IP`, so rate zones and audit
   logs see real caller IPs, not CF edge IPs. (Their config lacks this; the survey
   flagged it.)
4. **Rate zones** (ours): `auth` 20r/m · `admin_api` 180r/m · `client_api` 120r/m ·
   `webhooks` 600r/m (engine events burst on campaign completion) · `health` 60r/m ·
   `default` 90r/m. App-layer limits stay authoritative; nginx is edge defense.

5. **Where the files install, and the correction this forced.** `limit_req_zone` is an
   `http`-context directive, so the zone file goes in `/etc/nginx/conf.d/` (Debian
   auto-includes that inside `http {}`) and NOT in `/etc/nginx/snippets/`, which is
   auto-included by nothing — that path, inherited above, would have needed an `include`
   nobody would remember to add. `snippets/` is still right for the server/location
   fragments (`calevate-tls`, `calevate-origin`, `calevate-headers`, `calevate-proxy`),
   which is where they go. Full map: `infra/nginx/README.md` §1.
6. **The Cloudflare range list is one list, dated, and expiring.** `set_real_ip_from` and
   the origin `allow` lines are the same set of addresses stated twice, so they live as
   paired lines in one file; keeping two lists is how one gets refreshed and the other
   does not. It carries a `CLOUDFLARE_IPS_UPDATED` stamp and **the deploy fails when it is
   older than 180 days** — a stale allowlist does not degrade gracefully, it either blocks
   live traffic or trusts an address Cloudflare has released.

Cloudflare per zone: A records → VPS IP, proxied (orange); **Full (strict)** only
(Flexible = redirect loop with our port-80 301); no stray AAAA; origin locked to CF
ranges so the raw IP serves nothing; MX/TXT/DKIM independent of proxy status.

## 6. Secrets (three tiers, raghava model mapped to our stack)

1. **VPS `.env`** — **the bootstrap eight, plus the object-store credentials botocore
   reads for itself** (D-95, PLATFORM-CONFIG §4). It used to say "and nothing else", and
   an operator who followed that literally got a platform that boots, passes every
   container's fail-fast check, and cannot write one recording. Provisioning a VPS means
   writing these and only these:

   ```
   APP_ENV=prod
   DATABASE_URL=…            # host.docker.internal, the app role
   ALEMBIC_DATABASE_URL=…    # host.docker.internal, the owner role
   REDIS_URL=redis://redis:6379/0
   PLATFORM_KEK=…            # base64 of 32 random bytes — generate ONCE, back it up
   PLATFORM_KEK_RETIRED=     # empty until the first rotation
   OBJECT_STORE_ENDPOINT=…
   OBJECT_STORE_BUCKET=…
   AWS_ACCESS_KEY_ID=…        # the R2 token for the RECORDINGS bucket, not the backup one
   AWS_SECRET_ACCESS_KEY=…
   AWS_REGION=auto            # optional; `auto` is what R2 documents, and is the default
   ```

   **The three `AWS_*` lines are env-only for a THIRD reason, and it is neither of the two
   below**: nothing in this repository passes credentials to boto3 — botocore resolves
   them itself, from exactly these variable names (`workers/storage._client`,
   `infra/object-lifecycle/apply_lifecycle._client`). A value in `platform_secrets` would
   be a value the SDK never looks at, and the second consumer is a standalone script that
   runs with no database and could not read one anyway. They are not in `.env.example`
   because that file is the set a process needs to BOOT and these are not — a
   credential-less process starts perfectly well and then cannot copy a recording. What
   catches that is `/healthz/ready`, which reports both by name outside `local`, so a host
   missing them never goes green. `AWS_REGION` is genuinely optional: it defaults to
   `auto`, which is what Cloudflare R2 documents for its S3 API; set it only for a store
   that wants its own datacenter slug (a DO Spaces endpoint wants `blr1`, matching the
   host in `OBJECT_STORE_ENDPOINT`).

   **`AWS_REGION` IS THE SIGNATURE SCOPE AND HAS NOTHING TO DO WITH WHERE THE BYTES SIT**
   (D-450). R2 places a bucket permanently at its FIRST creation, from a location hint we
   have decided is **`apac`**, and there is no undo: deleting and recreating the same
   bucket NAME reuses the original placement, so a wrongly-placed bucket costs a full
   object copy to a differently-named one plus a re-apply of the lifecycle policy. Nothing
   in this repository creates a bucket, so the hint lives in a human checklist —
   `infra/README.md` §5 item 2 for the recordings bucket, `infra/backup/README.md` §8 step
   1 for the wal-g backup bucket, which is a **separate** one-shot decision on a separate
   day. Setting `AWS_REGION=apac` moves nothing and breaks everything with
   `SignatureDoesNotMatch`. And the hint is placement, not residency: R2's guaranteed
   residency feature is Jurisdictional Restrictions, whose only values are `eu`, `fedramp`
   and `us` — **no India** — which is why the legal pages say this data is stored outside
   India and must go on saying so.

   `RESEND_API_KEY` is the third env-only key and the ONLY credential that is (see the
   email block below for why). Everything else — `BOLNA_API_KEY`, the Sarvam stack, the
   four `AZURE_OPENAI_*` values (D-410), `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON`,
   `EMAIL_PROVIDER`, Razorpay, the GST
   invoice identity, `ENGINE`, calling windows, `USD_INR_RATE`, `ALERTS_EMAIL`, all 55 of
   them — is set afterwards from `admin.calevate.tech/ops`, live, without an SSH session
   and without a restart. *(**There are no authentication keys in that list any more.**
   This sentence led with "Clerk keys" until 20 Aug 2026; D-177 deleted the vendor and
   authentication is configured by nothing — not in the environment, not in the console,
   not in the browser. See `apps/web/.env.example`, which says the same about the two
   publishable keys that used to be build-time inputs.)* **That screen is now part of go-live** (§9): a freshly
   provisioned VPS boots into a running platform with unconfigured integrations, each of
   which refuses by name rather than pretending to work, and an operator finishes the
   configuration from a browser.

   **EMAIL IS THREE SETTINGS AND ONE EXTERNAL STEP.** Both channels that leave the
   platform by mail — hot-lead notifications to clients and operator alerts to Sri — go
   through one transport (`apps/workers/transport.py`), and it is selected by
   `EMAIL_PROVIDER` alone. Nothing is inferred from the presence of a credential, so a
   leftover `SMTP_HOST` does not quietly keep sending:

   - `EMAIL_PROVIDER=resend` — the platform's choice. `smtp` is still selectable and is
     the escape hatch for a suspended account or a provider outage; any other name
     refuses by name (`provider_not_implemented:<name>`) rather than looking configured.
   - `RESEND_API_KEY` — **ENVIRONMENT ONLY, on every host, and the one vendor credential
     that is not console-managed.** Create it in Resend with **Sending access** scoped to
     the sender domain, not Full access: this platform only ever sends.

     The reason is not encryption, it is reach. `scripts/host_alert.py` runs on the
     DATABASE host (§2 puts Postgres on its own box), opens no database connection, and
     is what pages a human when a backup fails or a disk fills — it can only read this
     from its own environment. Given that the key is required in an environment file
     anyway, ALSO offering it in the console would be two homes for one credential, and
     the environment wins silently (`apply_platform_overrides`): an operator would rotate
     the key on a screen, see it accepted, and watch mail keep going out under the old
     one. So the console shows it, names the variable and says whether this host declares
     it — and refuses to store it. `POST /v1/ops/secrets/resend_api_key/test` still works
     on a CANDIDATE value, which is the chance to catch a wrong key before the deploy.

     `EMAIL_PROVIDER` is deliberately NOT env-only: it is a selection, not a secret, and
     switching to `smtp` during a Resend outage must not need a deploy. The api/worker
     hosts read it from the store; the database host reads it from its own
     `EnvironmentFile` alongside the key.
   - `NOTIFICATIONS_FROM` — defaults to `support@calevate.tech`. It is also the alert
     sender, deliberately: one address, because a client who allowlists one and not the
     other has half a channel.

   The external step is **domain verification**, and it is the one thing no setting can
   stand in for: Resend refuses a send from an unverified domain outright (403), so the
   DNS records it issues for `calevate.tech` — a DKIM `TXT`, an SPF/`MX` pair on the
   sending subdomain, and the DMARC record if one is not already published — must be live
   and showing verified in the Resend dashboard BEFORE the first hot lead. A refusal is
   loud rather than silent: the transport logs `email_sender_rejected` at ERROR with the
   sender domain and both possible causes. `POST /v1/ops/secrets/resend_api_key/test`
   checks the key at the screen; it cannot check the domain, because it reads a status
   code and never a response body.

   **The bootstrap ordering problem, stated plainly: the console cannot configure the
   thing the console needs in order to start.** Resolution order is `os.environ` →
   `platform_settings`/`platform_secrets` → code default → refuse, so a key is only
   readable from the store by a process that already reached the store. `APP_ENV` decides
   the security posture (D-49), the two DSNs *are* the store, `REDIS_URL` carries the
   config sentinel, and `PLATFORM_KEK` decrypts every stored secret — a KEK inside the
   database it unlocks is theatre. The two `OBJECT_STORE_*` keys are here for a
   mechanical reason and are why the floor is 8 rather than §4's 6: they are REQUIRED
   `Settings` fields with no default, so `Settings()` cannot construct without them and
   the process cannot boot far enough to look them up. The console does manage them; set
   here, they display as source `env` and read-only.

   **Losing `PLATFORM_KEK` loses every stored secret.** It is not in the database, not in
   any backup of the database, and cannot be recovered from one — it belongs in the same
   offline custody as the `age` backup identity (§7, `infra/backup/README.md`). Restoring
   a database onto a host with a different KEK gives you a platform whose credentials all
   fail to decrypt. Back it up when you generate it, not later.

   **Env still wins over the store, deliberately** (§4): pasting a key into this file and
   restarting is the escape hatch for the night the console itself is what is broken.

   Never in git, never written by scripts; `vps-deploy.sh` aborts if absent, warns if it
   is not mode 600, and never prints a value. Pydantic Settings fails fast on missing
   keys, and §4 step 7 runs that check in the new image before any container is swapped.
   **Write the DSNs as the CONTAINERS see them**: `DATABASE_URL` and
   `ALEMBIC_DATABASE_URL` point at `host.docker.internal` (the host Postgres, D-26),
   `REDIS_URL` at `redis` by service name. Every Python process — including migrations —
   now runs in a container, so there is no second form of the URL and nothing rewrites
   one at deploy time. `.dockerignore` excludes `.env` so it cannot reach an image layer.
2. **DB-stored, encrypted** — per-tenant engine/BYOK keys already go through the
   secrets-manager references per SEC-COMP §5. (Raghava's AES-256-GCM
   `OpsConfigSecret` pattern is the reference implementation if we self-host this.)
3. **GitHub repo Secrets/Variables** — only paths + flags for CD (no app secrets in
   GitHub; the runner reads `.env` locally).

## 7. Backups / DR (host-PG consequence — this closes the RPO gap)

D-26 (host PG) breaks OPERATIONS §5's RPO 15min if we only do nightly dumps.

> **STATUS (Aug 2026): the mechanism now exists in the repo and has been applied to
> nothing.** It lives in **`infra/backup/`** — read `infra/backup/README.md` before this
> section, because that file is the authority on what it does and, more importantly, on
> what has never been run. This section previously described the design as if it were
> deployed; it was not built at all until now, which meant the RPO below was **unmet** and
> nobody would have discovered that until a restore. Everything in `infra/backup/` is
> reviewed-but-unapplied: §9 step 9 is where it becomes real.

What is in the repo, and where:

- **Chain A — continuous WAL archiving, wal-g → R2.** `infra/backup/postgresql-archiving.conf`
  (the `archive_command`, and the `archive_timeout = 300` that is what actually makes RPO
  15min true on a quiet night), `infra/backup/walg.json.template` (every secret a
  reference), `scripts/backup/basebackup.sh` (nightly base + `delete retain FULL 35`).
  REQUIRED, not optional, per D-26.
- **Chain B — nightly logical dump offsite.** `scripts/backup/dump-offsite.sh`:
  `pg_dump -Fc` + `age` encryption + `rclone` to a **non-Cloudflare** provider, plus the
  Redis RDB and a sha256 evidence JSON — raghava's `dr-backup-offsite.sh` pattern with the
  schedule actually installed (`infra/backup/systemd/*.timer`), which is the gap their
  script documents and does not close.
- **Failure visibility.** `scripts/backup/backup-health.sh` every 15 minutes: four checks
  chosen so each covers the previous one's blind spot, including the PostgreSQL behaviour
  that an archiver killed by a signal or exiting above 125 is *not* recorded in
  `pg_stat_archiver`. Plus `OnFailure=` on every unit and `Persistent=true` on the nightly
  timers. `scripts/backup/notify.sh` is the single seam to a real alert sink.
- **Restore and drill.** `runbooks/database-restore.md` (PITR to a chosen instant, with the
  verification that proves it worked and the erasure re-application that a restore makes
  necessary) and `runbooks/backup-restore-drill.md` (quarterly, alternating chains,
  recordable — OPERATIONS §6, evidence committed to `docs/evidence/`).
- **Retention: 35 days on both chains**, and that number is a data-protection commitment
  rather than a storage knob — see `infra/backup/README.md` §6–§7 for why, and for the DPDP
  consequence that erasure cannot reach into a backup. **It needs a decision-log entry.**
- **Daily host hygiene — BUILT, and it is a systemd timer.** `infra/hygiene/` (units, the
  journald cap) plus `scripts/deploy/host-hygiene.sh` (the job). Read
  `infra/hygiene/README.md` before this line; it is the authority on what the job does and
  on what has never been run. It prunes our compose project's stopped containers, dangling
  images and the build cache, flushes `calevate-web`'s pm2 logs, prunes the pnpm store and
  trims the runner's `_diag`, then reports disk and alerts through the same
  `scripts/backup/notify.sh` seam as the backup chain. Three corrections to the pattern it
  is adapted from, all named in the teardown (§8.6): **it never touches the runner's
  `_work`** — that is a CI job's staging area and deleting it from a timer deletes it under
  a running job; **it takes the deploy's lock**, and skips the day rather than racing a
  build; and **its prunes are scoped to our compose project**, so an operator's dev
  containers survive. The journal is bounded by a `SystemMaxUse=` drop-in rather than
  vacuumed daily, which is both a property instead of a repair and the reason this unit
  needs no privilege at all (§11).

**Systemd timers, not cron** — a deliberate departure from the raghava playbook. cron's
failure mode is mail to a mailbox nobody reads; `OnFailure=` gives a failed run somewhere
to go, `Persistent=true` catches up a night missed to a reboot instead of skipping it in
silence, and `systemd-analyze verify` checks the unit in CI-like fashion. For a mechanism
whose entire purpose is that silence is never mistaken for success, that is the difference
that matters.

**Tool choice re-validated (Aug 2026), and §7's open question now answered.** wal-g remains
the right pick for object-storage PITR — it pushes straight from the DB host to
S3-compatible storage with no backup server or local staging, which suits a single-VPS
topology. On the pgBackRest claim this section previously flagged as unverified: it was
**true and is no longer current**. pgBackRest was archived on 27 April 2026 after Crunchy
Data's sale ended its sponsorship, and was then rescued in May 2026 by a coalition of
sponsors (AWS, Supabase, Percona, pgEdge, Tiger Data, Eon). Still secondary sources
(percona.community, 28 Apr 2026), so still not first-party — but the conclusion is
unchanged and the *reason* recorded here was wrong: stay on wal-g because it fits the
topology, not because the alternative is dying.

**⚠ Vendor concentration — the mechanism now implements the fix, it is not applied.** The
edge (Cloudflare) and the WAL archive destination (Cloudflare R2) are the same vendor and
the same account. A credential compromise or account suspension takes out the front door
and the backups together, which is exactly the scenario backups exist for. Therefore:
- wal-g → R2 stays, but in **its own bucket with its own scoped token**, not the recordings
  bucket — a token that can write backups must not be able to read recordings, and the
  recordings lifecycle policy (`infra/object-lifecycle/policy.json`) must not be able to
  expire a backup.
- **The nightly `pg_dump` + Redis RDB offsite copy MUST land on a different provider and a
  different credential** (Backblaze B2, S3, or a Hetzner Storage Box — any non-Cloudflare
  target). This is the one that survives a Cloudflare-account event, and `dump-offsite.sh`
  will not work without one being configured.
- Additionally: **an R2 bucket lock on the backup prefix (30 days)** so a stolen write token
  cannot destroy the archive it can write to. Bucket locks take precedence over lifecycle
  rules and indefinite locks cannot be removed — never use `--retention-indefinite`.
- Restore drills alternate sources: prove the R2 PITR path one quarter, the offsite dump the
  next. A backup nobody has restored from is a hypothesis, not a backup.

**The largest unverified assumption**, called out here because it can invalidate chain A:
**wal-g has never been run against R2 by us.** R2's multipart implementation has a
documented history of rejecting uploads other S3 clients accept (Barman, s3fs, rclone and
the Docker registry all carry open issues), and wal-g #1639 records `backup-push` hanging at
full CPU after an S3 409. If the first hand-run `backup-push` (§9 step 9) hangs or fails,
chain A moves to the offsite provider and the vendor-concentration problem inverts. Find
this out on day one, not during a restore.

## 7a. Self-serve exposure (D-34 — this doc predates it)

Until D-34 the platform had **no public write surface**: every account was created by us,
so the internet could only reach a login page. Self-serve signup changes that, and the
single-VPS topology means one abusive account contends for the same CPU, Postgres and
Redis as client #1. The infra half of R-11 lives here; the product half is in
SECURITY-COMPLIANCE.

**Newly public, therefore newly attackable:** signup, org-create, credit top-up
(Razorpay callback), and the **lead-intake endpoint** — which by design accepts an
unauthenticated POST from a customer's website or ad platform, so it is internet-facing
with a per-agent token and nothing else.

Required before self-serve opens. This list used to say "all at the Cloudflare edge,
which we already run", and that is no longer where most of it lives: D-131 built the
app-level half in `apps/api/core/ratelimit.py` and D-144 finished it. What is still
external is marked **[edge]** and is a Cloudflare dashboard change, not a code change.

- **Rate limits** on `signup`, `org-create`, and per-token limits on lead intake — **in
  the repo now.** `PROFILES["auth"]` bounds `POST /v1/auth/signup` per minute and
  `tenancy/signup.py`'s hourly quota bounds it per identity and per real caller address
  (`SIGNUPS_PER_USER_PER_HOUR`, `SIGNUPS_PER_IP_PER_HOUR`), failing CLOSED when Redis is
  gone because nothing else bounds an unattended tenant factory. Lead intake is
  `PROFILES["webhook_ingest"]`, keyed on the `webhook_id` in the path — which is the
  per-*source* dimension this bullet asked for, since the caller is a customer's server
  and its address is not a tenant. **[edge]** zones stay as the outer bound (§5).
- **Bot protection (Turnstile) on signup only.** Never on lead intake: it is a
  machine-to-machine endpoint and a challenge there silently breaks a client's funnel.
  **[edge]** — nothing in the repo can turn this on.
- **WAF + DDoS** stays on for `app.` and `api.`. `hooks.calevate.tech` keeps its
  never-gated policy (§5) — engine webhooks must not meet a challenge page. **[edge]**.
- **Per-tenant resource ceilings enforced in-app, not just at the edge.** Three of them
  exist: the per-tenant REQUEST ceiling (`LimitProfile.per_tenant`, charged in
  `core/auth.charge_tenant_quota` at the first instant the tenant is a verified fact
  rather than a header a stranger typed), the spend cap checked pre-dispatch
  (`spend_state`, fail-closed) and the concurrency cap. Edge limits protect the box; only
  app-level caps protect *client #1 from tenant #47*, and the edge structurally cannot do
  per-tenant at all because it keys on `$binary_remote_addr` and one SMB behind one NAT
  is the ordinary case.
- **A noisy-neighbour budget**: workers already run in Compose, so cap the ARQ worker
  concurrency rather than letting a bulk campaign saturate the host and starve the
  webhook receiver's <500ms ack.

**Sizing.** §2's "≥4GB RAM + 2GB swap" was derived from `next build` peaking >2GB on a
single-tenant box. With Postgres, Redis, three Python services, and self-serve traffic on
one VPS, treat **8GB as the practical floor** once self-serve opens, and move `next build`
off the production host (build in CI, ship the artifact) rather than buying RAM to survive
a build. Revisit when real concurrency numbers exist (pilot gate 13).

## 8. Observability on the VPS

Sentry is hosted (TRD §2) — nothing to run on the VPS for it, and the Langfuse/PostHog
configuration that used to sit beside it was removed rather than wired (D-49).

> **"Nothing to run" is true and used to read as "configured" when it could not be.**
> `sentry-sdk` appeared in `pyproject.toml` only as a mypy override and not once in
> `uv.lock`, while `core/observability.py` guarded its import with
> `except ImportError: log.warning("sentry_dsn_set_but_sdk_missing")`, `sentry_dsn` was a
> real `Settings` field, and the ops console offered `sentry_` as a managed prefix. So an
> operator set the DSN on the go-live screen, the screen accepted it, and error reporting
> stayed off with one warning in a log nobody was reading yet — the fallback branch was
> the only reachable one.
>
> **It is now installable and is still OPT-IN: `uv sync --all-packages --group errors`
> on the api and worker host.** It is a `[dependency-groups]` entry rather than a runtime dependency of
> `apps/api`/`apps/workers` because `uv sync` builds ONE venv for the whole workspace and
> voice-runtime shares it — hard rule 3 makes that boot graph a thing to keep deliberately
> small, so the opt-in is per host rather than per package. `--all-packages` is not
> optional in that command: this is a uv WORKSPACE, and a bare `uv sync --group errors`
> drops every workspace member — measured, on a real environment, by running it. **A host
> that has not run that command has no error reporting**, whatever the DSN says, and the boot line still names
> it. What notices a failure either way is OPERATIONS §4's alerts and the health endpoints
> below.

Operator
alerts leave the VPS by whichever transport `EMAIL_PROVIDER` names — `resend` (the
`RESEND_API_KEY` secret plus a verified sender domain) or `smtp` (a host) — plus
`ALERTS_EMAIL`, or nobody is told. Neither one is selected by a stray credential:
`EMAIL_PROVIDER` is the single decision, and a deployment that sets none logs
`alert_delivery_has_no_transport` at boot with the reason, which is precisely so this is
not discovered at 3am.
Their Prometheus SLO-rules + promtool-in-CI pattern is the reference for when we add
metrics endpoints (M2+); adopt the recording-rule + burn-rate-alert structure for our
SLOs (pipeline lag, webhook ack, dashboard p95). Until then: health endpoints +
OPERATIONS §4 alerts (email/WhatsApp) carry the load.

## 9. Go-live order (maps to their phases 6–14)

1. VPS baseline (§2) → 2. DNS zones in Cloudflare (grey first) → 3. host PG + the two
roles + the database + `max_connections = 200` (§2a) — **exact sequence in 3a below,
because a migration will otherwise create the app role for you with a password that is in
this repository** → 4. clone repo, place `.env` from the secrets manager AND
`apps/web/.env.local`, export the nginx four (4a below), first manual deploy —
**`scripts/vps-deploy.sh --dry-run --all` first, then `--all --no-pull`**, attended,
working through §4d's six hand-first items →
5. nginx + TLS, **in the order 5a gives**, because the obvious order deadlocks →
6. flip Cloudflare orange + Full (strict), verify with `dig +short` (CF IPs) and the
525 checklist → 7. install runner + repo Secrets/Variables **exactly as §3a lists them**,
**the privileged scripts and
the hygiene timer (9.7a)**, **and only now set `VPS_DEPLOY_ENABLED=true`** → 8. one full CD cycle
(push → CI → auto-deploy) verified green, **then the rollback drill of §4d step 7** → **9. backups (below — the longest step, and
the one this order previously assumed away)** → 10. configure Bolna per-agent webhook URLs against hooks.calevate.tech + verify the
source-IP allowlist (13.203.39.153 via CF real_ip, D-27/D-31) rejects a spoofed test
delivery and accepts a real one → 11. pre-launch checklist (OPERATIONS §8).

### 9.3a Step 3 in full — the two roles, and why the sequence is written out

Two roles, never one. The **owner** role runs migrations (`ALEMBIC_DATABASE_URL`): DDL,
policies, triggers, `GRANT`. The **app** role is what every service connects as
(`DATABASE_URL`) and is `NOSUPERUSER NOBYPASSRLS` — hard rule 1's tenant isolation is only
real if the role serving requests cannot bypass a policy, and a superuser bypasses FORCEd
RLS entirely.

**Do this before the first `alembic upgrade`.** Revision `05bba2f3c19c` contains
`CREATE ROLE calevate_app LOGIN PASSWORD 'calevate_app' … IF NOT EXISTS` — a local-dev
default, and its own comment says "staging/prod set it from the secrets manager". Nothing
enforces that. If the role does not already exist when migrations run on the VPS, the
migration creates it, and **the production app role's password is then a string committed
to this repository**, reachable from a Docker-published port that ufw does not filter (§2).
The `IF NOT EXISTS` guard makes the migration safe only for a human who went first.

```sh
# As the postgres superuser on the VPS. Both passwords come from the secrets manager —
# generate them there first; do not type one you can remember.
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE calevate      LOGIN PASSWORD '<owner-password-from-secrets-manager>'
    NOSUPERUSER NOCREATEROLE CREATEDB;
CREATE ROLE calevate_app  LOGIN PASSWORD '<app-password-from-secrets-manager>'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE calevate OWNER calevate;
SQL

# Schema privileges, as the OWNER, in the new database. PostgreSQL 15+ no longer grants
# CREATE on `public` to PUBLIC, so without this the app role cannot even resolve the
# schema; CI does exactly this line before it migrates.
PGPASSWORD='<owner-password>' psql -h 127.0.0.1 -U calevate -d calevate -v ON_ERROR_STOP=1 \
  -c "GRANT ALL ON SCHEMA public TO calevate_app;"
```

Then `pg_hba.conf`: containers reach host Postgres over the Docker bridge, so it must admit
that CIDR (`172.16.0.0/12` covers the default bridge pools) with `scram-sha-256`, and
`listen_addresses` must include the bridge gateway. Set `max_connections = 200` in the same
edit (§2a's budget totals ~101 against a default of 100) and restart once.

The migration's own `GRANT`s (usage on `public`, DML on all tables, and the matching
`ALTER DEFAULT PRIVILEGES`) then apply to the role you created rather than to one it
invented. **Verify before deploying**: `\du` shows `calevate_app` with no attributes, and
`SELECT rolbypassrls FROM pg_roles WHERE rolname='calevate_app'` is `f`.

### 9.4a Step 4's exports — four variables that are not in `.env` and never will be

`render_nginx` substitutes `ROOT_DOMAIN`, `TLS_LIVE_DIR`, `ORIGIN_CERT_PATH`,
`ORIGIN_KEY_PATH` (plus `ACME_WEBROOT`, which has a working default). None is a `Settings`
field and the deploy script never sources `.env` — they are hostnames and paths, exported
in the operator's shell:

```sh
export ROOT_DOMAIN=calevate.tech
export TLS_LIVE_DIR=/etc/letsencrypt/live/calevate.tech
export ORIGIN_CERT_PATH=/etc/ssl/calevate/origin.pem
export ORIGIN_KEY_PATH=/etc/ssl/calevate/origin.key
```

CD supplies the same four from repo Variables (`.github/workflows/deploy.yml`); the human
first-deploy path had nothing, and the deploy discovered them at the last step — after
migrations and all three swaps. `preflight_plan` now refuses at the start, and
`--dry-run --all` refuses too, which is why the dry run comes first.

Step 4 also places **`apps/web/.env.local`** by hand from the secrets manager. It is a
second file because Next reads `.env*` from the PACKAGE directory and inlines every
`NEXT_PUBLIC_*` at BUILD time; a missing key there compiles to the empty string and ships
a console whose API base is the visitor's own localhost, behind a page that answers the
health poll 200.

### 9.5a Step 5 in full — the certificate order, which is not the obvious one

The obvious order deadlocks: `certbot certonly --webroot` needs nginx serving
`/.well-known/acme-challenge/`, that location lives in `calevate-site.conf`, and that file
references `${TLS_LIVE_DIR}/fullchain.pem` in all three server blocks — so `nginx -t`
fails on a missing certificate, so nginx will not load the config that would let certbot
obtain it.

Break it with the certificate that needs no ACME:

1. **Cloudflare Origin CA first.** Issue a `*.calevate.tech` origin certificate from the
   Cloudflare dashboard (15-year life, trusted by Cloudflare only) and place it at
   `ORIGIN_CERT_PATH`/`ORIGIN_KEY_PATH`, mode 0600, owned by root.
2. **Install `000-default.conf` alone** and reload. It listens on 80 and 443 as
   `default_server`, uses the origin certificate, and returns 444. This is also §10's
   first lesson: a certless `default_server` is what turns a healthy origin into
   Cloudflare 525.

   ⚠ **Its 444 is inside `location /`, and that is load-bearing rather than stylistic.**
   Because this block is the only port-80 listener loaded during issuance, it is also the
   block that has to serve `/.well-known/acme-challenge/` — so it carries a `^~` location
   for the webroot. A `return 444` written at SERVER scope, which is how this template
   originally shipped, is executed by ngx_http_rewrite_module in the server rewrite phase,
   **before nginx selects a location**: it fires for the challenge too, and step 3 fails
   with an empty response on a config that passes `nginx -t` cleanly. `tests/
   nginx_default_server_acme_test.py` fails if the `return` is ever hoisted back out.
3. **Obtain the Let's Encrypt certificates while only that file is loaded, WITH the
   renewal hook attached in the same command.** Its port-80 `default_server` answers the
   challenge for all four names:

   ```sh
   certbot certonly --webroot -w /var/www/certbot --cert-name calevate.tech \
     -d calevate.tech -d www.calevate.tech \
     -d admin.calevate.tech -d app.calevate.tech -d api.calevate.tech -d hooks.calevate.tech \
     --deploy-hook "systemctl reload nginx"
   ```

   **Six names, and `--cert-name` is not cosmetic.** `TLS_LIVE_DIR` is
   `/etc/letsencrypt/live/calevate.tech`; without the flag certbot names the lineage
   after the FIRST `-d` and the rendered config points at a directory that never exists.
   The apex and `www` are in the same lineage rather than served from the Cloudflare
   Origin CA cert that also covers them: that certificate exists for one job (a certless
   `default_server` is Cloudflare 525), and using it for a second is two mechanisms for
   one problem — one certificate, one renewal, one hook.

   `certonly`, never `--nginx` — that plugin rewrites templated config (§5). The
   `--deploy-hook` is part of issuance rather than a later step because a later step is
   where it does not happen; step 5 is why it is not optional and how to prove it fires.
4. **Now install `calevate-site.conf` + `calevate-rate-zones.conf` + the snippets**,
   `nginx -t`, reload. `TLS_LIVE_DIR` now exists, so the test passes.
5. **The renewal deploy hook — what step 3 attached, and why it is not decoration.**

   **Why it is not optional.** `certonly` deliberately never touches nginx (§5, §10 —
   `--nginx` rewrites templated config), which means a renewed certificate is a new file on
   disk that the running server has not read. certbot's own timer renews at ~day 60 and
   says nothing; nginx keeps serving the old certificate until something else reloads it,
   and the next reload is whenever logrotate or a deploy happens to run. On a 90-day
   certificate that is a 30-day fuse ending in an expired certificate on a live edge. This
   repository had the hook nowhere at all (`docs/evidence/raghava-deploy-teardown.md` §6.2,
   §9 row 15).

   **What `--deploy-hook` does, exactly**: certbot saves it into the lineage's renewal
   configuration as `renew_hook = …` in `/etc/letsencrypt/renewal/<lineage>.conf`, so every
   later `certbot renew` runs it — the flag is passed once, at issuance, and is not needed
   again. It runs ONLY when a certificate is actually issued or renewed, which is what
   separates it from `--post-hook` (every invocation) and from `--pre-hook`.

   `--deploy-hook` rather than dropping a script in `/etc/letsencrypt/renewal-hooks/deploy/`
   — both work and the directory form is the better answer on a host with many lineages,
   because the flag form runs **once per renewed certificate** and would reload nginx once
   per lineage. We have exactly one lineage covering all four names (one `certonly`, four
   `-d`), so the flag form fires once, keeps the intent in the command that created the
   certificate, and leaves nothing to be separately installed and separately forgotten.

   *Pass conditions*, and there are two because the obvious one does not test the hook:
   (a) `grep renew_hook /etc/letsencrypt/renewal/admin.calevate.tech.conf` shows the reload;
   (b) `certbot renew --dry-run` succeeds. **A plain `--dry-run` does NOT run deploy hooks**
   — that is documented certbot behaviour, not a bug — so proving the hook fires needs
   `certbot renew --dry-run --run-deploy-hooks`, which runs them against the currently
   active certificate. That flag is present in current certbot (user guide, 5.7.0) and
   absent in 2.6.0; **the release that introduced it is not verified here**. If the
   installed certbot rejects it, prove the hook by running `systemctl reload nginx` by hand
   and confirming the edge stays up — do not record the plain dry run as evidence the hook
   works, because it is not.

   Sources (accessed 17 Aug 2026): certbot User Guide 5.7.0, "Renewing certificates" and
   "Pre and Post Validation Hooks"; certbot issue #6180 (`--deploy-hook` is undocumented in
   the `certonly` reference and does save `renew_hook`); Let's Encrypt community thread
   "Missing --run-deploy-hooks option in Certbot 2.6.0".
6. Only then flip Cloudflare to orange + Full (strict) — step 6 of §9.

`NGINX_AUTO_RELOAD` stays unset for this whole pass: the deploy renders the files and
prints the install commands, and a human installs them in the order above having read
them. (The automated path backs up and restores on a failed `nginx -t` — in
`calevate-nginx-apply`, §11 — but the first pass is the one where reading the config
matters most, and it also comes before the privileged scripts are installed at all: those
land at step 7, §9.7a.)

**Step 4 places §6 tier 1 — the bootstrap eight plus the two object-store credentials;
the other 55 keys are step 10a.** After the first deploy the platform is running and its
integrations are unconfigured —
each refusing by name, none pretending to work. Open `admin.calevate.tech/ops` and set
them: engine + `BOLNA_API_KEY`, the Sarvam stack, the four `AZURE_OPENAI_*` values
(resource, key, deployment, model — D-410), `EMAIL_PROVIDER`
plus its credential (`RESEND_API_KEY` for `resend`, `SMTP_*` for `smtp`) and
`ALERTS_EMAIL`, `USD_INR_RATE`, and the GST invoice identity when the entity exists.
`POST /v1/ops/secrets/{key}/test` asks the vendor a cheap authenticated question before a
credential goes live, so a wrong key is refused at the screen rather than at the first
call. `GET /v1/ops/config` is also the pre-launch audit: it shows every key with its
source, so "is anything still on a code default in production" is one screen rather than
an SSH session — worth reading before ticking OPERATIONS §8.

**But the ops console has a door, and step 4 is also where somebody is given a key.**
`admin_users` is the allowlist the entire admin realm resolves against, it is
ops-managed and reconciled from nothing at all (the file that used to say so,
`core/clerk_identity.py`, went with the vendor at D-177 — the design statement survives
it and is now simply true by construction: there is no upstream to reconcile FROM), and
**nothing in this repository ever inserted a row** — not `seed.py`,
not the deploy script, not any migration. So a fresh deploy came up green with an empty
table and every admin request 403ing: no organization creatable, no platform setting
writable, no first campaign reviewable, and no way to reach the screen the paragraph
above sends you to. It fails closed, so this was never a security hole; it was a
deployment with no way in. After the first `vps-deploy.sh` run, once per host:

```sh
# ON THE VPS: through the IMAGE, because §2 puts no Python and no uv on the host and the
# `uv run` form this block used to carry therefore could not run there at all (D-188).
# `--no-deps` so this never starts redis; `--rm` so it leaves nothing behind. Verified end
# to end against a scratch database, including the no-mail-provider path below.
docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  --entrypoint python api -m scripts.bootstrap_admin \
  --email ops@yourdomain.example --role superadmin --name "…"

# ON A DEV BOX, where the venv exists:
DATABASE_URL=… ALEMBIC_DATABASE_URL=… uv run python -m scripts.bootstrap_admin \
  --email ops@yourdomain.example --role superadmin --name "…"
```

**It needs `AUDIT_CHAIN_SECRET`, and that is a BOOTSTRAP ORDERING rather than a
preference (D-188).** Creating the first operator writes the `auth.admin_bootstrapped`
audit row, and the hash chain refuses to sign without a key outside `local` — the script
stops with `hmac_key_missing` before it touches the database. The key is normally
console-managed (`platform_secrets`), and on a fresh host **the console cannot be the
answer**: reaching it needs an operator, and creating one needs this key. So on the first
run it comes from the environment, which beats the store by design (D-95's
`env → db → default → refuse`). The compose form above reads `.env`, so add it there
alongside the bootstrap eight and leave it there — `IDEMPOTENCY_SCOPE_SECRET` and
`IMPERSONATION_GRANT_SECRET` are the same shape and `/healthz/ready` names all three
until they are set.

**BOTH URLs, and they are different roles.** `ALEMBIC_DATABASE_URL` is the owner role,
because this writes the operator allowlist and the app role has no business holding write
access to it. `DATABASE_URL` is the app role, because `auth_credentials` and
`auth_email_tokens` are FORCE-RLS'd against `app.auth`, a GUC set on the application
connection.

**What it does (D-171):** creates the `admin_users` row with NO password and mails a
**single-use setup link that expires in 60 minutes**. The operator opens
`https://admin.calevate.tech/auth/admin/bootstrap?token=…`, sets a password, and is then a working
administrator. **The link is also printed to stdout**, deliberately — a deployment whose
mail provider is not configured yet must still be able to acquire its first operator, and
the mail credentials are themselves stored by an operator, in the console. No password is
ever generated, printed or defaulted anywhere.

**If the link expires, run the command again.** That is the supported recovery and it is
safe: re-running before anyone has set a password re-issues a fresh link for the SAME row
(and retires the previous link), so it is a resend rather than a second account.

**Once any operator holds a password the script REFUSES** with `already_bootstrapped`, and
there is no `--force`. Adding further operators is an ordinary audited act in the admin
console, where an existing operator vouches for the next one. A flag that minted an
unattached administrator from a shell would be reachable by anyone who has ever held
database credentials — a contractor, a restored backup, a compromised CI runner — which is
exactly the back door this is designed not to be.

Both halves are audited: `auth.admin_bootstrapped` when the link is minted (naming the
address) and `auth.admin_bootstrap_completed` when the password is set. This is the most
privileged act in a deployment's life and it leaves a record of when and to whom.

*(This used to take `--clerk-user-id`. Clerk is gone — D-170 — so there is no vendor
dashboard in which to make the first account, and that flag was deleted rather than
deprecated: it cannot work, and a flag that cannot work is worse than one that is absent.)*

**Step 9 in full — `infra/backup/README.md` §8 is the ordered checklist; the shape of it:**
create the R2 **backup** bucket **with location hint `apac`** (one-shot, and a
separate one-shot from the recordings bucket — D-450) + a token scoped to it alone →
install wal-g (v3.0.8,
Jan 2026) → place `/etc/wal-g/walg.json` from the template with real values from the
secrets manager → `wal-g backup-list` (this is the first moment anyone learns whether
wal-g and R2 actually agree — **budget for it failing**) → confirm `SHOW data_checksums`
is `on` → install the archiving drop-in and **restart** PostgreSQL (`archive_mode` and
`wal_level` need one) → first `backup-push --verify` by hand, watched → install the three
systemd timers → configure the offsite `rclone.conf` and the age recipients, with the age
identity generated off-host → apply the R2 bucket lock (30 days, never indefinite) →
**run `runbooks/backup-restore-drill.md` end to end.** Until that drill has passed once,
"backups verified" on the OPERATIONS §8 pre-launch checklist cannot be ticked, because
what exists is a backup system we believe in rather than one anyone has recovered from.

### 9.7a Step 7's other half — the privileged scripts and the daily timer

Step 7 is where the runner account stops being a login and starts being the thing that runs
every merged pull request. That is the moment its privileges must already be decided, and
they are: **one sudoers grant, one root-owned script, no arguments** (§11,
`infra/privileged/README.md` §2 for the exact install commands and §5 for the five pass
conditions). Two of those pass conditions are worth repeating here because they are the ones
an operator skips:

- `sudo -l -U <deploy-user>` must LIST the script. If it lists nothing, the policy file is
  being ignored — sudo silently skips any name in `/etc/sudoers.d` containing a `.`.
- `sudo -n /usr/local/sbin/calevate-nginx-apply --help` must be refused **by sudo**, before
  the script runs. That is the argument restriction working.

Then the hygiene timer (`infra/hygiene/README.md` §5): install the unit and timer, run
`systemd-analyze verify`, install the journald cap, and run the job once by hand. It is
placed here rather than with the backups because it shares the deploy's lock — installing it
before there is a deploy to lock against proves nothing.

**`NGINX_AUTO_RELOAD` stays unset until all of that is done and step 5's certificate order
has been walked by hand.** The first nginx install is the one where reading the config
matters most (§9.5a), and the privileged path is for every deploy after it.

## 10. Known raghava lessons to NOT relearn (their HARDENING_HISTORY, our checklist)

- 525 on healthy origin = certless `default_server` (SNI-less strict validation).
- `certbot --nginx` destroys templated config; `certonly` only.
- Maintenance gate: `if` in rewrite phase can't see auth_request vars; two-hop
  error_page dies on `recursive_error_pages off`; single-hop `=503` is the pattern.
- `auth_request` buffers request bodies → big uploads 500; exempt upload locations +
  `proxy_request_buffering off`.
- Health windows sized for migrate-on-boot (90×2s), or operators learn to ignore red.
- Docker Dead-container tombstones break compose recreate; sweep before up.
- One runner directory per project; never copy a configured runner.
- Parallel docker builds OOM 4GB hosts; build serially; swap mandatory.
- Redis never publishes host ports; unique passwords per service.
- Wildcards in a sudoers argument position are a root escalation, not a convenience: sudo
  matches the argument list as one string and the wildcard spans `/` and words (§11).
- A daily cleanup that is not synchronised with the deploy will eventually delete something
  a deploy is using; and one that prunes host-globally on a host with a second compose
  project will eventually delete somebody's debugging session (§7).
- `certonly` never reloads nginx, so a renewed certificate is invisible until something
  else does — attach `--deploy-hook` at issuance (§9.5a).

## 11. Privilege on the host (D-167)

**The deploy account holds exactly one root grant, and it takes no arguments.**
`infra/privileged/` is the authority — the policy, the script it names, the install
procedure, and the five things a human must prove. This section is the summary and the
reason.

`docs/evidence/raghava-deploy-teardown.md` §8.3 found the reference host granting its runner
`NOPASSWD: /usr/bin/rm -rf /var/lib/docker/containers/*` and two `cp` grants with wildcards
on both sides. **sudo matches a command line as one concatenated string and a wildcard in it
spans `/` and words**, so the first grant permits deleting any path on the box and the
others permit writing any file into `/etc/nginx` from a world-writable source — held by the
account that runs code from every merged pull request. That is not a hardening detail to
copy carefully; it is the pattern to invert.

Ours:

| | |
|---|---|
| **What is granted** | `calevate ALL=(root) NOPASSWD: /usr/local/sbin/calevate-nginx-apply ""` — and nothing else. The trailing `""` is sudoers for "may be run only with an empty argument list". |
| **How variation travels** | a fixed staging directory (`/var/lib/calevate/nginx-staging`) that the root script validates: no symlinks, no subdirectories, no non-regular files, one basename shape, and an owner and mode it checks before reading anything. |
| **Why the script is root-owned in `/usr/local/sbin`** | a script the caller can rewrite is a command the caller can construct. `/var/www/calevate` is rewritten by every deploy, so nothing privileged may live there. |
| **What is refused** | `rm` under `/var/lib/docker` at any path (§4 step 4 refuses with the command instead), `systemctl restart docker`, a bare `systemctl reload nginx`, anything for the hygiene timer, and `certbot`. |
| **What this does NOT claim to contain** | `docker` group membership, which §2 grants and which is root-equivalent by design. The policy neither worsens it nor is excused by it; what the policy governs is the one action that is not Docker. |

**Nothing here has been installed.** Root on a VPS is external blocker 9 in the teardown's
§9.1, and `visudo -c` has never been run against this policy on a host with sudo.

Cross-references: TRD §1 (deployables) · OPERATIONS §5–6 (SLOs, drills) ·
SECURITY-COMPLIANCE §5 (secrets, TLS) · ROADMAP D-25/D-26/D-27 · SURFACES §3.
