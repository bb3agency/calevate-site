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

The India-latency requirement survives in one place: **any future in-call-path service**.
With D-28 (RAG/memory = managed API service), the likely M3 shape is the engine calling
the provider directly — putting NOTHING of ours in the call path. Only if the bake-off
selects the thin-endpoint variant does a small India-region host enter the picture
(that endpoint + nothing else). Until measured, there is nothing to co-locate.

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
Host: PostgreSQL 16 (+pgvector) · pm2 (web) · certbot · GitHub Actions runner
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
PostgreSQL 16 + pgvector, Node 22 (for web builds + pm2), Python is NOT needed on the
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

D-26 (host PG) breaks OPERATIONS §5's RPO 15min if we only do nightly dumps. So:
- **WAL archiving with wal-g to R2** (continuous; restores to any point) — this is
  REQUIRED to honor RPO 15min with host PG, not optional.
- Plus raghava's `dr-backup-offsite.sh` pattern nightly: `pg_dump | gzip` + Redis RDB
  → rsync offsite + sha256 evidence JSON. Cron installed explicitly (their script
  documents but does not install the schedule — install it, don't repeat that gap).
- Quarterly restore drill stays (OPERATIONS §6); evidence files committed.
- Daily disk-hygiene cron (their `install-vps-cleanup.sh` pattern): docker prune,
  builder cache cap, pm2 log flush.

## 8. Observability on the VPS

Langfuse/Sentry/PostHog are hosted (TRD §2) — nothing to run on the VPS for them.
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
(push → CI → auto-deploy) verified green → 9. wal-g + backup crons + restore test →
10. configure Bolna per-agent webhook URLs against hooks.calevate.tech + verify the
source-IP allowlist (13.203.39.153 via CF real_ip, D-27/D-31) rejects a spoofed test
delivery and accepts a real one → 11. pre-launch checklist (OPERATIONS §8).

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
