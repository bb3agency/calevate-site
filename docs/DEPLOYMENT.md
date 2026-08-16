# Calevate — VPS Deployment & CI/CD Blueprint

Version 1.0 · July 2026. Adapted from the battle-tested raghava-organics playbook
(`D:\Agency\Clients\raghava-organics\raghava-organics-site\backend\docs\` — canonical:
CLIENT_VPS_SETUP_GUIDE, CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE, MASTER_DEPLOYMENT_PLAYBOOK,
HARDENING_HISTORY). Where this doc says "raghava-proven" it means: running in production,
with the failure modes already found and fixed there. Decisions D-25…D-27 in ROADMAP §6.

## 0. Hosting decision (D-25 — supersedes D-13's scope, not its reasoning)

The calevate.tech site is NOT in the live-call path — the rented engine (Bolna, D-31)
hosts the entire voice pipeline in v1. So the site stack (web, api, workers, webhook receiver) hosts on a
**general-purpose VPS (Hetzner-class); India co-location is NOT required for it.**

The India-latency requirement survives in one place: **any in-call-path service**.
With D-28 (RAG/memory = managed API service), the likely M3 shape is the engine calling
the provider directly — putting NOTHING of ours in the call path.

> ⚠ **AMENDED (Aug 2026, after D-38 + SURFACES §2b).** "Nothing to co-locate" no longer
> holds unconditionally. **In-call actions put our endpoint in the audio path**: when the
> agent books a slot, sends a WhatsApp mid-call, or hits a custom API, the *engine* calls
> *us* while the caller waits. A Hetzner-class European VPS answering a Bolna-India call
> adds ~150ms each way — enough to blow an in-call tool budget on its own, before our
> handler does any work.
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

One dedicated VPS (do not share with client production sites — isolation), Ubuntu 22.04:

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
Object storage: Cloudflare R2 (recordings, raw payloads, exports)
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

Packages: Docker Engine + Compose plugin (v2.24+ for `!reset`), nginx ≥1.24, certbot,
PostgreSQL 16 (pgvector optional — D-28 contingency), Node 22 (for web builds + pm2;
see §7a — prefer building in CI), Python is NOT needed on the
host (api/workers run containerized; builds happen in Docker), jq, `systemd-timesyncd`
(webhook ±5-min skew checks depend on it).

Hardening (all raghava-proven): non-root deploy user in `docker` group; SSH
`PermitRootLogin no` + `PasswordAuthentication no`; ufw inbound 22/80/443 only;
fail2ban; unattended-upgrades; 2GB swap in `/etc/fstab`; `pm2 startup` once;
`systemctl disable --now redis-server` (Redis lives in Compose only); remove stock
nginx `sites-enabled/default` and install the `000-default.conf` pattern (§5).

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
campaign's calls hanging up together is exactly a burst of in-flight deliveries. So:

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

**Runner discipline** (raghava-proven): one runner dir per project
(`~/actions-runner-calevate`), installed via their `install-github-runner.sh` pattern
(`--labels "self-hosted,calevate-vps" --unattended --replace`, `svc.sh install/start`);
never `cp -r` a configured runner; `verify-cd-status.sh`-style preflight after setup.

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
   if missing, warn if not mode 600), compose file and Dockerfile present, docker compose
   v2 present, **checkout clean** (a deploy from an edited tree ships code CI never saw),
   ≥3GB free, and the Cloudflare IP list not older than 180 days (§5.3).
2. `git pull --ff-only`; **abort if HEAD ≠ `--expected-sha`**. CI validates one commit and
   `main` can move before the runner starts; without this gate that race ships silently.
3. **Resolve the component plan** from `git diff <last deployed SHA> HEAD` through the
   path map in `components_for_paths`. This is where hard rule 3 is enforced — see §4c.
4. **Dead-container check**: Docker `Dead`-state ghosts break compose's rename-on-recreate
   (§10). The script **detects and refuses with the exact command** rather than running
   the playbook's `sudo rm -rf /var/lib/docker/containers/<id>` unattended — an automated
   `rm -rf` under the daemon's state directory is a bigger hazard than the fault it fixes.
5. **Serial builds** — parallel builds OOM small hosts, and the OOM kills the runner, so
   it reads as a CI flake rather than as a memory ceiling.
6. **Bootstrap-env preflight, run IN the new image** (`validate_bootstrap_env` +
   `Settings()`), before any swap. In the image rather than on the host because what
   matters is what the process about to serve traffic can read.
7. **Migrations** (`compose --profile migrate run --rm migrate`), before the swap — §4a.
8. **Container swap**, one service at a time, `compose up -d --no-deps <service>`, in the
   order workers → api → voice-runtime (§4b), each followed by a health wait of
   **90×2s** on `/healthz` (§10's lesson: 60s was shorter than a migrate-on-boot, which
   trains operators to ignore red deploys).
9. **web**: `pnpm install --frozen-lockfile` + `pnpm -C apps/web build` +
   `pm2 reload calevate-web --update-env` + health poll on :3000.
10. **nginx**: envsubst render → placeholder check → `nginx -t` → `systemctl reload`,
    gated on `NGINX_AUTO_RELOAD=1`. Unset, it renders and prints the install commands.
11. Post-deploy prune, record the SHA and the plan to `.deploy-state/history`, summary
    with the before/after alembic revision and the rollback command.

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
transaction, so a failure leaves the database at the last revision that fully applied — a
valid intermediate state which, by the same argument, the still-running old containers can
serve on. **No automatic downgrade.** A downgrade can drop a column a partially deployed
system has already written to, turning a failed deploy into data loss; it is a judgement,
not a step, and `runbooks/deploy-failed.md` §3 is where that judgement is written down.
The revision is recorded before *and* after precisely so that a manual downgrade has a
target rather than a guess.

### 4b. The swap is low-downtime, not zero-downtime — and what absorbs the gap

`compose up -d --no-deps <service>` **recreates** the container: the old one stops, the new
one starts. That is a gap of a few seconds per service, and the honest thing is to name it
rather than to claim a rollout mechanism this repo does not have.

What is done about it:

- **Order.** workers first (no reader waits on them; a job landing in their gap sits in
  Redis), then api, then **voice-runtime last** — its gap is the only one that costs a
  call, so it is the shortest-lived and the last thing to happen.
- **Graceful stop.** `stop_grace_period` is 30s for voice-runtime (longer than its 2s
  durable deadline plus the ack budget) and 60s for workers, so in-flight work finishes
  instead of being killed.
- **The safety net already exists.** A delivery arriving in voice-runtime's gap gets no
  ack; Bolna does not retry (D-31); the reconciliation poller recovers it on a 10-minute
  tick. Leads appear late, not never. This is the same net OPERATIONS §5 leans on.

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
6. **Enable CD last.** Set `VPS_DEPLOY_ENABLED=true` only after steps 1–5, and only after
   one full manual deploy has succeeded. *Pass condition*: §9 step 8's full CD cycle
   verified green.

Until step 6, **this repo has a deploy mechanism and no automatic deploys**, which is the
correct state for something nobody has run yet.

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
> `scripts/vps-deploy.sh` renders and installs it (§4 step 10). Two items of the
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

1. **VPS `.env`** — **the bootstrap eight, and nothing else** (D-95, PLATFORM-CONFIG §4).
   Provisioning a VPS means writing these and only these:

   ```
   APP_ENV=prod
   DATABASE_URL=…            # host.docker.internal, the app role
   ALEMBIC_DATABASE_URL=…    # host.docker.internal, the owner role
   REDIS_URL=redis://redis:6379/0
   PLATFORM_KEK=…            # base64 of 32 random bytes — generate ONCE, back it up
   PLATFORM_KEK_RETIRED=     # empty until the first rotation
   OBJECT_STORE_ENDPOINT=…
   OBJECT_STORE_BUCKET=…
   ```

   Everything else — Clerk keys, `BOLNA_API_KEY`, Sarvam, SMTP, Razorpay, the GST
   invoice identity, `ENGINE`, calling windows, `USD_INR_RATE`, `ALERTS_EMAIL`, all 50 of
   them — is set afterwards from `admin.calevate.tech/ops`, live, without an SSH session
   and without a restart. **That screen is now part of go-live** (§9): a freshly
   provisioned VPS boots into a running platform with unconfigured integrations, each of
   which refuses by name rather than pretending to work, and an operator finishes the
   configuration from a browser.

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
   keys, and §4 step 6 runs that check in the new image before any container is swapped.
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
- Daily disk-hygiene cron (their `install-vps-cleanup.sh` pattern) is still unbuilt: docker
  prune, builder cache cap, pm2 log flush.

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
configuration that used to sit beside it was removed rather than wired (D-49). Operator
alerts leave the VPS by SMTP: `ALERTS_EMAIL` plus an SMTP host, or nobody is told.
Their Prometheus SLO-rules + promtool-in-CI pattern is the reference for when we add
metrics endpoints (M2+); adopt the recording-rule + burn-rate-alert structure for our
SLOs (pipeline lag, webhook ack, dashboard p95). Until then: health endpoints +
OPERATIONS §4 alerts (email/WhatsApp) carry the load.

## 9. Go-live order (maps to their phases 6–14)

1. VPS baseline (§2) → 2. DNS zones in Cloudflare (grey first) → 3. host PG + DB user
+ pgvector (and `max_connections = 200`, §2a) → 4. clone repo, place `.env` from the
secrets manager, first manual deploy — **`scripts/vps-deploy.sh --dry-run --all` first,
then `--all --no-pull`**, attended, working through §4d's six hand-first items →
5. nginx render + certbot certonly + `000-default.conf` + origin lock (§4 step 10 renders
it; `NGINX_AUTO_RELOAD` stays unset for this first pass so the config is installed by
hand after being read) →
6. flip Cloudflare orange + Full (strict), verify with `dig +short` (CF IPs) and the
525 checklist → 7. install runner + repo Secrets/Variables, **and only now set
`VPS_DEPLOY_ENABLED=true`** → 8. one full CD cycle
(push → CI → auto-deploy) verified green → **9. backups (below — the longest step, and
the one this order previously assumed away)** → 10. configure Bolna per-agent webhook URLs against hooks.calevate.tech + verify the
source-IP allowlist (13.203.39.153 via CF real_ip, D-27/D-31) rejects a spoofed test
delivery and accepts a real one → 11. pre-launch checklist (OPERATIONS §8).

**Step 4 places the bootstrap EIGHT only (§6 tier 1); the other 50 keys are step 10a.**
After the first deploy the platform is running and its integrations are unconfigured —
each refusing by name, none pretending to work. Open `admin.calevate.tech/ops` and set
them: engine + `BOLNA_API_KEY`, the Sarvam stack, the Clerk secrets, SMTP +
`ALERTS_EMAIL`, `USD_INR_RATE`, and the GST invoice identity when the entity exists.
`POST /v1/ops/secrets/{key}/test` asks the vendor a cheap authenticated question before a
credential goes live, so a wrong key is refused at the screen rather than at the first
call. `GET /v1/ops/config` is also the pre-launch audit: it shows every key with its
source, so "is anything still on a code default in production" is one screen rather than
an SSH session — worth reading before ticking OPERATIONS §8.

**Step 9 in full — `infra/backup/README.md` §8 is the ordered checklist; the shape of it:**
create the R2 **backup** bucket + a token scoped to it alone → install wal-g (v3.0.8,
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

Cross-references: TRD §1 (deployables) · OPERATIONS §5–6 (SLOs, drills) ·
SECURITY-COMPLIANCE §5 (secrets, TLS) · ROADMAP D-25/D-26/D-27 · SURFACES §3.
