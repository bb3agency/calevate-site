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

---

## 1. Failed at `preflight`

Nothing was touched. The site is still serving the previous release.

| Message | What it means |
|---|---|
| `.env is missing` | Place it from the secrets manager. No script writes it (DEPLOYMENT §6). |
| `the checkout has local modifications` | Somebody edited the tree on the box. `git diff` it, decide, then commit or `git checkout --`. Do not deploy around it. |
| `only NGB free` | `docker image prune -af && docker builder prune --keep-storage 3GB`. If that does not clear it, the disk is being eaten by something else — check `journalctl --disk-usage` and the compose json-file logs. |
| `Cloudflare IP ranges ... days ago` | Refresh `infra/nginx/snippets/calevate-origin.conf` from cloudflare.com/ips, update the stamp, commit, redeploy. Do NOT raise `CLOUDFLARE_IPS_MAX_AGE_DAYS` to make it pass. |
| `HEAD is X but CI validated Y` | main moved after CI. This is the gate working. Re-run CI on HEAD, or deploy commit Y. |

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

What is true at this moment:

- The database is at the last revision that fully applied. PostgreSQL has transactional
  DDL and alembic runs each revision in its own transaction, so there is no half-applied
  revision — there is a *partially applied migration set*.
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
git -C /var/www/calevate log --oneline -5
git -C /var/www/calevate checkout <previous-sha>
/var/www/calevate/scripts/vps-deploy.sh --all --no-pull
```

`--no-pull` because the checkout has deliberately been moved off the branch tip;
without it the script would pull straight back to the commit you are rolling away from.

**The database does not roll back with it**, and by rule 8 it does not need to: the
previous release runs on the current schema. Do not pair a code rollback with a schema
downgrade by reflex — see §3.

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
  successful reload, and this is why the script tests before reloading. The rendered
  files are in the temp directory named in the output; the error names the file and line.
- **`pm2 reload` succeeded but the site is stale**: `--update-env` is already passed;
  if a changed variable is still not visible, `pm2 delete calevate-web` and start it
  again from the ecosystem definition, which is a fuller restart than a reload.

## 6. When it is over

A deploy that failed and was recovered still did not record itself — `.deploy-state/deployed-sha`
is unchanged, so the next `--changed` run will re-plan from the last *successful* deploy.
That is correct and needs no fixing.

Cross-references: DEPLOYMENT §4 (the script) · DEPLOYMENT §4b (the swap gap) ·
OPERATIONS §5 (`webhook_ack_slow` triage) · `runbooks/database-restore.md` (if a
migration did damage rather than merely failing).
