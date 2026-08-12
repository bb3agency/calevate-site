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

**Deploy workflow** (`.github/workflows/deploy.yml`): `workflow_run` on CI success on
main + `workflow_dispatch`. Runs on the **self-hosted runner installed on the VPS**
(label `calevate-vps`) — the runner polls GitHub via outbound HTTPS; **no inbound SSH
ever**. Gated on repo Variable `VPS_DEPLOY_ENABLED=true`; paths in Secrets
(`VPS_CLIENT_PATH=/var/www/calevate`), booleans/labels in Variables (raghava rule:
paths are Secrets, flags are Variables). Concurrency group prevents overlapping
deploys; no cancel-in-progress.

Three jobs, independent (a docs-only change must not rebuild Docker):
1. **deploy-backend**: git pull `--ff-only` + **SHA-match against the CI run's SHA
   (abort on mismatch)** → `scripts/vps-deploy.sh` (§4).
2. **deploy-web**: `npm ci` + `next build` + `pm2 reload calevate-web --update-env`
   + health poll on :3000.
3. Both verify their required Secrets/Variables first and fail with instructions.

**Runner discipline** (raghava-proven): one runner dir per project
(`~/actions-runner-calevate`), installed via their `install-github-runner.sh` pattern
(`--labels "self-hosted,calevate-vps" --unattended --replace`, `svc.sh install/start`);
never `cp -r` a configured runner; `verify-cd-status.sh`-style preflight after setup.

## 4. vps-deploy.sh (adapt raghava's 650-line script — keep its scar tissue)

Sequence, with the Calevate substitutions (uv/alembic for npm/prisma):

1. Validate: `.env` present (deploy scripts NEVER write secrets; abort if missing),
   compose files present.
2. `git pull --ff-only`; **abort if HEAD ≠ CI-validated SHA**.
3. Env preflight: run a `verify-bootstrap-env` check (pydantic Settings import against
   `.env` — fail fast BEFORE any container swap).
4. **Dead/orphan container tombstone sweep** (their §1.75 — Docker `Dead`-state ghosts
   break compose's rename-on-recreate; sweep + `rm -rf /var/lib/docker/containers/<id>`
   via scoped sudoers).
5. **Pre-build disk reclaim**: container/image prune, `docker builder prune
   --keep-storage 3GB`; hard-abort below 3GB free.
6. **Serial builds** (`compose build api`, then `voice-runtime`, then `workers`) —
   parallel builds OOM small hosts.
7. Migrations from the host against 127.0.0.1: `uv run alembic upgrade head`
   (DATABASE_URL rewritten `host.docker.internal`→`127.0.0.1`).
8. nginx template render via envsubst + `nginx -t` before `systemctl reload`
   (gated on `NGINX_AUTO_RELOAD=1`; scoped sudoers grants — copy their exact
   `/etc/sudoers.d/deploy` list, §8 of the survey).
9. Container swap → health wait **90×2s** on `/healthz` for api AND voice-runtime
   (their lesson: 60s was shorter than a migrate-on-boot, training operators to
   ignore red deploys).
10. Post-deploy prune + summary.

**voice-runtime caveat**: it deploys with the same script but hard rule 3 still holds —
its deploy must not be COUPLED to api changes. The compose service split gives us
`compose up -d --no-deps voice-runtime` for independent restarts; a future split into
its own workflow job is allowed without a new decision.

## 5. nginx + TLS + Cloudflare (raghava config, four adaptations)

Reuse: `client.conf.template` structure (envsubst placeholders), per-route
`limit_req_zone` snippet installed once at `/etc/nginx/snippets/`, security headers
block, TLS settings, maintenance-page machinery (single-hop `error_page 401 =503`,
inline fallback — do NOT re-derive; their HARDENING_HISTORY documents why the obvious
patterns fail), `certbot certonly --webroot` (NEVER `certbot --nginx` — it rewrites
templated config), `000-default.conf` with Cloudflare Origin CA cert on
`default_server` (the 525 fix), `cloudflare-only.conf` origin IP allowlist.

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

Cloudflare per zone: A records → VPS IP, proxied (orange); **Full (strict)** only
(Flexible = redirect loop with our port-80 301); no stray AAAA; origin locked to CF
ranges so the raw IP serves nothing; MX/TXT/DKIM independent of proxy status.

## 6. Secrets (three tiers, raghava model mapped to our stack)

1. **VPS `.env`** — bootstrap only (DATABASE_URL, REDIS_URL, object-store keys,
   Clerk keys, BOLNA_API_KEY, APP_ENV=prod). Never in git, never written by scripts;
   `vps-deploy.sh` aborts if absent. Pydantic Settings fails fast on missing keys.
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

Required before self-serve opens (all at the Cloudflare edge, which we already run):
- **Rate limits** on `signup`, `org-create`, and per-token limits on lead intake. The
  intake limit is per *agent token*, not per IP — the caller is a customer's server.
- **Bot protection (Turnstile) on signup only.** Never on lead intake: it is a
  machine-to-machine endpoint and a challenge there silently breaks a client's funnel.
- **WAF + DDoS** stays on for `app.` and `api.`. `hooks.calevate.tech` keeps its
  never-gated policy (§5) — engine webhooks must not meet a challenge page.
- **Per-tenant resource ceilings enforced in-app, not just at the edge**: concurrency cap
  and spend cap checked pre-dispatch (`spend_state`, fail-closed). Edge limits protect the
  box; only app-level caps protect *client #1 from tenant #47*.
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
+ pgvector → 4. clone repo, place `.env`, first manual deploy (`vps-deploy.sh` by
hand) → 5. nginx render + certbot certonly + `000-default.conf` + origin lock →
6. flip Cloudflare orange + Full (strict), verify with `dig +short` (CF IPs) and the
525 checklist → 7. install runner + repo Secrets/Variables → 8. one full CD cycle
(push → CI → auto-deploy) verified green → **9. backups (below — the longest step, and
the one this order previously assumed away)** → 10. configure Bolna per-agent webhook URLs against hooks.calevate.tech + verify the
source-IP allowlist (13.203.39.153 via CF real_ip, D-27/D-31) rejects a spoofed test
delivery and accepts a real one → 11. pre-launch checklist (OPERATIONS §8).

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
