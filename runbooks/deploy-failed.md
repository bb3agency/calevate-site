# Runbook — a deploy failed

**Symptom**: `scripts/vps-deploy.sh` printed the `DEPLOY FAILED` banner, or the Deploy
workflow is red.

**Read the banner first.** It names the STEP. This runbook is ordered by that step,
because the recovery for a failed build and a failed container swap are not the same
procedure and doing the wrong one is how a red deploy becomes an outage.

> **Never executed.** Nothing in this repo has been deployed to anything. This procedure
> is written from the script, line by line, and has not been walked on a real host.

The first fact you need in every case: **the script aborts at the failing step and runs
nothing after it.** There is no partial continuation and no automatic rollback.

```
docker compose -p calevate -f compose.prod.yml ps
cat /var/www/calevate/.deploy-state/history | tail -5
```

`ps` says what is actually running. `history` says what the last *successful* deploy put
there (the script writes it only at the very end, so a failed deploy does not appear).
Each line is `<utc> <sha> image=<ref> migrations=<applied|skipped-rollback|none> <plan>` —
the image ref is the artefact you can roll back onto without a rebuild, and the migration
verdict answers "did that deploy move the schema?" without reading anything else.

**Use `-f compose.prod.yml`, always.** A bare `docker compose` in that directory picks
`docker-compose.yml`, which is the DEV file. It declares its own project name
(`calevate-dev`) so it can no longer collide with the production project, but it also
means a bare command shows you an empty stack rather than production.

---

## 1. Failed at `preflight` or `preflight (plan-scoped)`

Nothing was touched. The site is still serving the previous release.

**Two steps, and the banner says which.** `preflight` runs first and asks what is true of
every deploy. `preflight (plan-scoped)` runs after the component plan is resolved — it
cannot run earlier, because its questions are "is `web` in this plan?" and "is `nginx`?" —
and it still runs before anything is built, migrated or swapped. Between them only
`git pull --ff-only` happens.

| Message | What it means |
|---|---|
| `.env is missing` | Place it from the secrets manager. No script writes it (DEPLOYMENT §6). |
| `the object store has no credentials in .env` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. botocore reads those exact names, nothing in the tree passes them, so without them the platform boots green and cannot copy a recording. |
| `declares no top-level 'name:'` / `declares 'name: calevate'` | `docker-compose.yml` is the DEV file and must not share a compose project with `compose.prod.yml`. Restore `name: calevate-dev` at its top. Until it is there, a bare `docker compose up -d` in this directory recreates production redis from the dev definition. |
| `the checkout has local modifications` | Somebody edited the tree on the box. `git diff` it, decide, then commit or `git checkout --`. Do not deploy around it. |
| `only NGB free` | `docker image prune -af && docker builder prune --keep-storage 3GB`. If that does not clear it, the disk is being eaten by something else — check `journalctl --disk-usage` and the compose json-file logs. |
| `Cloudflare IP ranges ... days ago` | Refresh `infra/nginx/snippets/calevate-origin.conf` from cloudflare.com/ips, update the stamp, commit, redeploy. Do NOT raise `CLOUDFLARE_IPS_MAX_AGE_DAYS` to make it pass. |
| `HEAD is X but CI validated Y` | main moved after CI. This is the gate working. Re-run CI on HEAD, or deploy commit Y. |
| `apps/web/.env.local is missing` | Plan-scoped (`web`). Next inlines `NEXT_PUBLIC_*` at BUILD time from the package directory; without the file the bundle ships with an empty API base and empty Clerk publishable keys and the deploy still reports success. Place it from the secrets manager. |
| `pnpm`/`pm2 is not installed on this host` | Plan-scoped (`web`). DEPLOYMENT §2's baseline. |
| `PLATFORM_KEK is not set in .env` | It unwraps every console-managed credential. It is in neither `BOOTSTRAP_REQUIRED` nor `runtime_config_missing_keys`, so without this refusal the deploy goes green and the first vendor call fails. Take it from the secrets manager — never generate a new one on a deployment that already has stored secrets: the old ones become undecryptable. |
| `VOICE_RUNTIME_WORKERS is N on an M-vCPU host` | DEPLOYMENT §2a. Set it to the vCPU count. The supported concurrency drops with it (§2a's table) — that is the honest answer on a smaller box, and adding workers back is not. |
| `swap is NMB` (warning, not a refusal) | `next build` peaks over 2GB and an OOM kill produces no error at all. On a box with plenty of free RAM this is safe to ignore; check `free -m` before you do. |
| `NGINX_AUTO_RELOAD=1 but nginx is not installed` / `NGINX_AUTO_RELOAD=1 but /usr/local/sbin/calevate-nginx-apply is not installed` | Plan-scoped (`nginx`), and only when the script is going to write to `/etc/nginx`. The privileged script is installed by a human, once per host — `infra/privileged/README.md` §2. |
| `this account may not run /usr/local/sbin/calevate-nginx-apply without a password prompt` | The sudoers policy is missing, or is being IGNORED: sudo silently skips any file in `/etc/sudoers.d` whose name contains a `.`. Check with `sudo -l -U <deploy-user>` — if it lists nothing, that is the cause. Under CD a prompting sudo does not fail, it blocks until the job times out with the containers already swapped. Do NOT "fix" this by widening the policy; DEPLOYMENT §11. |
| `<path> is missing or not writable by this account` | The nginx staging directory. Create it per `infra/privileged/README.md` §2 — the deploy hands rendered config to root through that fixed path, because the sudoers grant permits no arguments. |
| `the nginx step needs these exported` | Plan-scoped (`nginx`). `ROOT_DOMAIN`, `TLS_LIVE_DIR`, `ORIGIN_CERT_PATH`, `ORIGIN_KEY_PATH` are exported in the operator's shell (CD supplies them from repo Variables) — DEPLOYMENT §9 step 4a. |

## 1b. Failed at `reclaim disk`

`not enough free disk to build, after pruning, purging the build cache, dropping every
per-commit image but the newest, and removing every unreferenced image.`

**Nothing has been built, migrated or swapped.** The step runs before all three precisely
so the disk is not discovered halfway through a layer extraction, and the ladder has
already taken everything Docker had to give (DEPLOYMENT §4 step 5). So this is not a Docker
problem: something else on the volume is. `du -xhd1 / | sort -rh`, then again one level
down on whatever is largest. Usual suspects on this host: the journal if the
`SystemMaxUse=` cap was never installed (`infra/hygiene/journald-cap.conf`), the pnpm
store, `apps/web/.next`, and Postgres's `pg_wal` if archiving has stalled — which is a
backup incident first and a disk incident second (`runbooks/backup-*`).

Note what the ladder may already have cost you: below the purge floor it drops per-commit
app images beyond the newest, so **a rollback to an older commit may now be a rebuild
rather than a swap.** The deploy says so when it does it.

Do not raise `RECLAIM_REFUSE_FLOOR_GB` to get past this. It is the number below which a
build fails halfway and leaves dangling layers, which makes the next attempt fail sooner.

`another deploy or the daily hygiene job has held …/host.lock` is the other refusal from
this area, and it happens before preflight. `fuser -v <path>` names the holder. A dead
deploy never leaves a stale lock — `flock` releases on exit, however the process exits.

## 2. Failed at `build` or `verify bootstrap env`

Still nothing swapped — the old containers are serving. The new image either did not
build or built and cannot read a usable environment.

- **Build failure**: read it as a normal build failure. The one deploy-specific cause is
  memory: builds are serial precisely because parallel ones OOM a 4GB host
  (DEPLOYMENT §10), and an OOM kills the runner rather than the build, so a build that
  "just stops" with no error is the signature. `free -m`, confirm 2GB swap exists.
- **`validate_bootstrap_env` failure**: the message names the variable. Fix `.env` on the
  host from the secrets manager and re-run. This step exists so that a missing `APP_ENV`
  is a refusal here rather than a container that boots into `local` mode and accepts a
  dev token whose subject the caller chooses (`apps/api/core/settings.py`).

## 3. Failed at `migrations` — the one that needs thinking

**Do not run `alembic downgrade` reflexively.** Read this whole section first.

> **First: did it FAIL, or did it SKIP?** A yellow **MIGRATIONS SKIPPED** banner is not a
> failure and the deploy carried on past it. It means the database is at a revision this
> commit has no script for, i.e. you are rolling back, and the schema was deliberately left
> where it is (§4). Nothing below applies to that case.

What is true at this moment:

- The database is at the last revision that fully applied. PostgreSQL has transactional
  DDL and alembic runs each revision in its own transaction (`alembic/env.py` passes
  `transaction_per_migration=True` — alembic's default is one transaction for the WHOLE
  run, and this line is what makes the sentence true), so there is no half-applied
  revision — there is a *partially applied migration set*.
- **CHECK FOR AN INVALID INDEX ANYWAY.** Three revisions build an index with
  `CREATE INDEX CONCURRENTLY` inside an `autocommit_block()`, which is a real commit point
  no transaction setting can wrap — that is what CONCURRENTLY means. A build interrupted
  there leaves an index that is **INVALID**: never used to answer a read, still enforcing
  uniqueness on every insert. One of them is on `credit_ledger`, which is money.

  ```sql
  SELECT indexrelid::regclass AS index, indrelid::regclass AS table
  FROM pg_index WHERE NOT indisvalid;
  ```

  If a row comes back, `DROP INDEX` it and let the re-run rebuild it. An INVALID index is
  not a state the revision can resume from.
- **The old containers are still serving, and they can serve on this schema.** That is
  hard rule 8 doing its job: a migration may not drop a column in the same release that
  stops writing it, which is the same statement as "old code runs against new schema".
- Nothing new has been deployed.

So the safe default is: **leave the database where it is, fix the migration, deploy
again.** The forward path is the supported one.

```
docker compose -p calevate -f compose.prod.yml run --rm --no-deps --entrypoint alembic api current
docker compose -p calevate -f compose.prod.yml run --rm --no-deps --entrypoint alembic api history -r-5:
```

Downgrade only if the applied revisions are themselves the problem, and only having
answered this out loud: **has anything written data through the new schema yet?** If the
swap never happened the answer is no, and a downgrade is merely undoing DDL. If a partial
swap did happen (you are here from §4, not §3), the answer may be yes, and a downgrade can
drop a column that now holds the only copy of something. That is why the script never does
this automatically — it is a judgement, not a step.

The revision to downgrade *to* is on the failure banner (`db rev`), which is the whole
reason it is recorded before the migration runs.

## 4. Failed at `swap <service>` — the new image is running and unhealthy

This is the only branch where production is degraded. The service was recreated with the
new image, and it did not answer `/healthz` within 180 seconds.

```
docker compose -p calevate -f compose.prod.yml logs --tail=200 <service>
curl -sS -i http://127.0.0.1:8000/healthz     # api
curl -sS -i http://127.0.0.1:8100/healthz     # voice-runtime
```

`/healthz` checks Postgres and Redis. A 503 there with a healthy `/healthz/live` means the
process is fine and a dependency is not — check host Postgres and the redis container
before assuming the release is bad.

**WHICH dependency is not in that body** (D-128): the health endpoints answer an
uncredentialled caller with the verdict only, because `/healthz/ready` used to name the
credentials a deployment was missing to anyone on the internet. The detail is in the
logs of the service you just curled — `health_db_unavailable` / `health_redis_unavailable`
per failed probe, and `health_not_ready` carrying `degradation_mode`, `queue_depth` and
`missing_config_keys` — which is the same `docker compose logs` you already have open.
A session holding `ops:manage` gets it in the response body instead.

**Rolling back the code** (fast, and it is the right first move if the logs point at the
release rather than at a dependency):

```
cat /var/www/calevate/.deploy-state/history | tail -5      # what was live, and its image
git -C /var/www/calevate log --oneline -5
git -C /var/www/calevate checkout <previous-sha>
/var/www/calevate/scripts/vps-deploy.sh --all --no-pull
```

`--no-pull` because the checkout has deliberately been moved off the branch tip;
without it the script would pull straight back to the commit you are rolling away from.

**It does not rebuild if it does not have to.** Each deploy tags its image
`calevate/app:<12-char sha>` and `history` records the ref, so if that artefact is still on
the host — the newest five are kept — the rollback skips the build entirely and is a
container swap. Only if it has been pruned do you pay for a serial `docker build` on a host
that is already degraded.

**The database does not roll back with it**, and by rule 8 it does not need to: the
previous release runs on the current schema. Do not pair a code rollback with a schema
downgrade by reflex — see §3.

**And the deploy no longer dies trying.** `--all` puts the python services in the plan, so
the migrate step runs — from the OLDER image. If the deploy you are rolling back carried a
migration, the database is at a revision that image has no script for, and
`alembic upgrade head` cannot even resolve it (`Can't locate revision identified by ...`,
exit 255): the rollback used to abort there, before swapping a single container, with
production still on the broken release. The script now asks
`scripts/deploy_revision_check` — inside the image — whether its own chain contains the
revision the database is at, and on "no" it prints a **MIGRATIONS SKIPPED** banner, leaves
the schema alone (the seed too), and carries on to the swap. That is the same policy the
paragraph above states, made executable. If the checker cannot answer, the deploy stops
rather than guessing, because guessing "rollback" on a forward deploy would swap new code
onto an old schema.

**If `voice-runtime` is the unhealthy one**, that is the urgent case: it is the engine's
only endpoint. Calls in progress are unaffected (the engine hosts the call), but their
completion webhooks are being refused. They are not lost — Bolna does not retry (D-31),
and the reconciliation poller recovers missed executions on a 10-minute tick, which is the
guarantee of record. Expect leads to appear late rather than never, and expect
`webhook_ack_slow` / reconciliation alerts. Roll back rather than debug forward.

## 5. Failed at `deploy web` or the nginx steps

Containers are already swapped and healthy; this is the tail of the deploy.

- **`pnpm install --frozen-lockfile` failed**: the lockfile and a manifest disagree. Do
  not "fix" it with a plain `pnpm install` on the production host — that rewrites the
  lockfile on the box, which is both a supply-chain hole (hard rule 9) and an
  un-reviewed dependency change. Fix it in a PR.
- **`next build` was killed**: memory. DEPLOYMENT §7a's answer is to move this build into
  CI and ship the artifact; until that happens, confirm swap exists and retry.
- **`nginx -t` failed**: nothing was reloaded — nginx keeps the previous config until a
  successful reload — **and the previous files have been put back on disk.** That second
  half is not cosmetic. `nginx -t` reads `/etc/nginx`, so a candidate config has to be
  installed before it can be tested, and this step used to leave a rejected config sitting
  there: the running nginx was fine, and the next reload was not — and reloads are
  triggered by Debian's daily logrotate and by certbot's renewal hook (DEPLOYMENT §9.5a
  step 5), days later, by nobody. The abort message comes from
  `/usr/local/sbin/calevate-nginx-apply` — the root-owned script that owns this whole
  install/test/restore sequence (DEPLOYMENT §11) — and names both directories: the staging
  set (to read the error against) and the backup of the set that was replaced, under
  `/var/tmp/calevate-nginx-backup.*`. If the message instead says the
  RESTORED config does not test either, stop and treat `/etc/nginx` as unknown — do not
  reload anything until `nginx -t` is clean.
- **`pm2 reload` succeeded but the site is stale**: `--update-env` is already passed;
  if a changed variable is still not visible, `pm2 delete calevate-web` and
  `pm2 start apps/web/ecosystem.config.cjs && pm2 save`, which is a fuller restart than a
  reload. (That file exists now. It did not when this line was first written, which is why
  the deploy could not start the web tier at all on a fresh host.)
- **`could not remove calevate/app:<tag>`** at the prune step: **the deploy succeeded.**
  This is disk housekeeping running after the fact — the newest five image tags are kept
  and older ones dropped — and a warning here means something still references that image.
  `docker ps -a --filter ancestor=<ref>` names it.

## 6. When it is over

A deploy that failed and was recovered still did not record itself — `.deploy-state/deployed-sha`
is unchanged, so the next `--changed` run will re-plan from the last *successful* deploy.
That is correct and needs no fixing.

Cross-references: DEPLOYMENT §4 (the script) · DEPLOYMENT §4b (the swap gap) ·
OPERATIONS §5 (`webhook_ack_slow` triage) · `runbooks/database-restore.md` (if a
migration did damage rather than merely failing).
