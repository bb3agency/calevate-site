# Rename map: infrastructure, build, deploy, CI and environments

Companion to `docs/REBRAND-MAP.md` (§2C covers these names at a high level). This file lists
every place outside application logic where the name `calevate` lives, how to rename each,
and what breaks if it is done in the wrong order. Mapped at commit `6ef0c49e`, 29 Oct 2026.

Placeholders used below:

- `<new>` — the new lowercase slug (e.g. for paths, users, units, compose project).
- `<new>_shared` / `<new>-shared` — the new Python import name / distribution name.
- `<New>` — the display spelling, only used in comments and descriptions.

What is NOT in this file: the domain (`calevate.tech`, REBRAND-MAP §2B), cookies, browser
storage keys, Redis key prefixes, ThinnestAI metadata keys, WhatsApp template names and R2
bucket names. Those are application or vendor-side names; they are only mentioned here where
an infra file carries them.

Evidence level: everything under "Where" for the repository was read with `git grep` on the
commit above. Everything under the VPS section is DERIVED from the repo (DEPLOYMENT.md,
runbooks/, infra/) plus the founder's list of known host facts; nothing on the host was
inspected. §9.0 gives the read-only commands that turn each derived row into a checked one.
Rows marked **UNCHECKED** are conclusions that need that inventory before anyone acts.

---

## 0. The five things that can actually hurt

1. **Moving `/var/www/calevate` silently disarms the backup alarms.** Every backup and
   hygiene unit runs `ExecStart=/var/www/calevate/scripts/...`, and the failure handler
   `calevate-backup-alert@.service` itself runs `/var/www/calevate/scripts/backup/notify.sh`.
   Move the directory and the nightly base backup fails AND the unit that would tell you so
   fails too. The host `.venv` that the alert relay uses (`scripts/backup/app-python.sh`) also
   breaks, because a venv hard-codes its absolute path. Mitigation: leave a symlink
   `/var/www/calevate -> /var/www/<new>` until every unit is reinstalled and verified.
2. **Changing the compose project name throws away production Redis.** `compose.prod.yml:24`
   says `name: calevate`, so the Redis volume on the host is `calevate_redis-data`. A new
   project name makes compose create an empty `<new>_redis-data`: the ARQ job queue, webhook
   dedupe keys and locks are gone, and the old project's containers keep holding ports
   127.0.0.1:8000 and :8100, so the new api and voice-runtime cannot bind. Docker has no
   volume rename; "renaming" a volume means create-new + copy while Redis is stopped, or pin
   the old name with `volumes: redis-data: {name: calevate_redis-data}`.
3. **Renamed nginx files collide with the old ones, because the root installer never deletes.**
   `calevate-nginx-apply` installs what is staged and "never removes a file it did not
   introduce in this run" (`infra/privileged/sbin/calevate-nginx-apply:136-137`). The deploy
   writes `calevate-site.conf`, `calevate-rate-zones.conf`, `calevate-origin-trust.conf`,
   `00-calevate-log-format.conf` (`scripts/vps-deploy.sh:1167-1174`). Rename them and the old
   files stay in `/etc/nginx/conf.d`: the rate zones (`auth`, `admin_api`, ... are not
   prefixed) are then defined twice and `nginx -t` refuses the whole set. If it did not
   refuse, the old `calevate-site.conf` would sort first and silently keep serving. A sudo
   user must move the old files out of `conf.d` in the same maintenance step.
4. **Three places must agree on the deploy user name, or every nginx deploy is refused**:
   `/etc/sudoers.d/calevate-deploy` (user `calevate`, line 51 and 57), `DEPLOY_USER=calevate`
   in `/usr/local/sbin/calevate-nginx-apply:55`, and the owner of
   `/var/lib/calevate/nginx-staging` (`infra/privileged/README.md` §3). The sudoers file is
   loaded by its name and silently ignored if the name contains a `.`.
5. **A rollback across the rename boundary uses the OLD defaults.** `--checkout <old sha>`
   runs the old `vps-deploy.sh`, whose defaults are `COMPOSE_PROJECT=calevate`,
   `IMAGE_REPO=calevate/app`, `/var/lib/calevate/nginx-staging`,
   `/usr/local/sbin/calevate-nginx-apply` (`scripts/vps-deploy.sh:65,135,142,143`). After the
   rename those name a different compose project and paths that no longer exist. Every one of
   them is an environment override, so a cross-boundary rollback must export the new values
   (§9.4). Say this in the release notes of the rename commit.

---

## 1. nginx (`infra/nginx/`)

Rendered by `render_nginx` in `scripts/vps-deploy.sh:1160-1174`, staged to
`/var/lib/calevate/nginx-staging/{conf.d,snippets}` and installed by
`/usr/local/sbin/calevate-nginx-apply`.

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| Template file `calevate.conf.template` | `infra/nginx/calevate.conf.template`; read at `scripts/vps-deploy.sh:1168`; tests `tests/nginx_*_test.py` (about 10 files) | `git mv` to `<new>.conf.template`; update the `envsubst` line and every test that opens it | Missed test paths fail CI only. |
| Installed name `calevate-site.conf` | output name at `scripts/vps-deploy.sh:1168`; host `/etc/nginx/conf.d/calevate-site.conf` | change the output name; on the host move the old file out of `conf.d` (to `/root/nginx-pre-rename/`) in the same window as the first deploy | Old file is never removed by the installer (§0 item 3). Both files define the same `server_name`s; nginx keeps the first in sort order, so the OLD config keeps serving. |
| `calevate-rate-zones.conf` | `scripts/vps-deploy.sh:1170`; host `/etc/nginx/conf.d/` | as above | Zones `auth`, `admin_api`, `client_api`, `webhooks`, `worker`, `health`, `browser` (`rate-zones.conf.template:39-103`) are unprefixed: two files = `duplicate zone`, `nginx -t` fails, installer restores, deploy fails. Safe but blocking. |
| `calevate-origin-trust.conf` | `scripts/vps-deploy.sh:1174`; host `conf.d` | as above | `geo`/`map` variables `$calevate_from_cloudflare`, `$calevate_from_loopback`, `$calevate_origin_denied` (`origin-trust.conf.template:49,77,84`). If variables are renamed and the old file stays, both `map`s coexist, harmless; if not renamed, nginx refuses a duplicate `geo` variable. Move the old file out. |
| `00-calevate-log-format.conf` | `scripts/vps-deploy.sh:1167`; host `conf.d` | keep the `00-` prefix (load-bearing: must sort before the site file, `vps-deploy.sh:1162-1166`) | Dropping `00-` makes every vhost fail with `unknown log format`. Old file left behind defines `log_format calevate_redacted` twice if not renamed: `nginx -t` fails. |
| `000-default.conf` | `scripts/vps-deploy.sh:1169` | no name to change; its content includes `snippets/calevate-tls.conf` (`000-default.conf.template:36`) | Must follow the snippet rename in the same commit. |
| Snippet files `calevate-headers.conf`, `calevate-origin.conf`, `calevate-origin-pull-{on,off,optional}.conf`, `calevate-proxy.conf`, `calevate-tls.conf` | `infra/nginx/snippets/`; host `/etc/nginx/snippets/`; included by absolute path about 60 times in `calevate.conf.template` and `000-default.conf.template` | `git mv` each; replace every `include /etc/nginx/snippets/calevate-` | Old snippet files remain on the host (harmless, nothing includes them) but confuse the next reader; remove them by hand after verification. `check_cloudflare_ip_age` reads `infra/nginx/snippets/calevate-origin.conf` by path (`vps-deploy.sh:592`): a missed path aborts every deploy with `missing ...`. |
| `$calevate_origin_pull` include pattern `calevate-origin-pull-${CF_ORIGIN_PULL}.conf` | `calevate.conf.template:134,254,315,455,572,694` | rename with the snippet files | A half rename makes nginx fail to open the include. |
| Origin-pull CA file `/etc/nginx/certs/calevate-origin-pull-ca.pem` | `snippets/calevate-origin-pull-on.conf:26`, `-optional.conf:8`; probed at `vps-deploy.sh:1147-1148` | optional; if renamed: copy (not move) the file to the new name, deploy, then remove the old | Only matters when `CF_ORIGIN_PULL` is `on`/`optional`; the deploy refuses if the file is missing. |
| Upstream names `calevate_web`, `calevate_api`, `calevate_hooks` | `calevate.conf.template:27-29` and every `proxy_pass` | sed inside the template | None if done in one file. |
| Variables `$calevate_logged_uri`, `$calevate_logged_referer`, captures `calevate_log_*`, log format `calevate_redacted` | `00-log-format.conf.template:79-137`; `access_log ... calevate_redacted` in every server block | sed; keep the format name in step across both templates | `tests/nginx_log_redaction_test.py` asserts the redaction; a mismatched name is a load failure. |
| Referrer map `$calevate_referrer_policy` | `calevate.conf.template:72`, `snippets/calevate-headers.conf:22` | sed both | Unknown variable = load failure. |
| Internal location `/_calevate_not_found` | `calevate.conf.template:162,182,361,381,501,521` | sed | None; never published. |
| TLS session cache `shared:CalevateTLS:10m` | `snippets/calevate-tls.conf:17` | rename | A renamed cache starts empty: TLS resumption from Cloudflare restarts once. Harmless. |
| Backup dirs `/var/tmp/calevate-nginx-backup.*` | `calevate-nginx-apply:185,190` | follows the script rename | Old dirs are no longer trimmed by the 30-day sweep; delete them by hand after 30 days. |

## 2. systemd units, sudoers, privileged script, host hygiene (`infra/backup`, `infra/hygiene`, `infra/privileged`)

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| `calevate-basebackup.service` / `.timer` | `infra/backup/systemd/`; host `/etc/systemd/system/` | `git mv`; on host: install the new pair, `daemon-reload`, `enable --now <new>-basebackup.timer`, THEN `disable --now calevate-basebackup.timer`, remove old files, `daemon-reload` | Both enabled = two base backups a night (double R2 cost, contention). Neither enabled = no base backups; the health check alarms after 36 h (`MAX_BASEBACKUP_AGE_S`, `backup-health.sh:66`). |
| `calevate-backup-health.service` / `.timer` | same | same order | The health script checks timers BY NAME (`BACKUP_TIMERS` default, `backup-health.sh:93`). Repo names and host unit names must change together or it alarms "unit not found" every hour. |
| `calevate-backup-alert@.service` (template) | same; referenced as `OnFailure=calevate-backup-alert@%n.service` in 4 units and in `calevate-hygiene.service:14` | install the new template FIRST, before any unit that points at it | A unit whose `OnFailure=` names a template that does not exist fails silently: the failure alarm is lost. |
| `calevate-dump-offsite.service` / `.timer` | same | rename in repo for consistency | Not installed in production (D-927, `infra/backup/README.md:56-58`). Confirm with `systemctl list-unit-files 'calevate-*'`. |
| `calevate-hygiene.service` / `.timer` | `infra/hygiene/systemd/`; `User=calevate`, `Group=calevate`, `WorkingDirectory=/var/www/calevate`, `HOME=/home/calevate`, `ExecStart=/var/www/calevate/scripts/deploy/host-hygiene.sh` (lines 24-34) | rename file and every value; same install order | Wrong `User=` = unit fails at start. Shares the deploy's lock (`host-lock.sh`), so it must be switched in the same window as the deploy root. |
| Unit `Description=Calevate ...` strings | every unit, line 2 | sed | Cosmetic. |
| `EnvironmentFile=-/etc/calevate/alerts.env` | 4 backup units | change to `/etc/<new>/alerts.env` | The leading `-` makes a missing file SILENT: alerts then go only to the journal. Copy the file first, verify, then switch the units. |
| `RCLONE_CONFIG=/etc/calevate/rclone.conf`, `AGE_RECIPIENTS=/etc/calevate/backup-recipients.txt`, `OFFSITE_REMOTE=calevate-offsite:calevate-dr` | `calevate-dump-offsite.service:12-17`, `scripts/backup/dump-offsite.sh:33-38` | only if the offsite chain is ever reinstalled; the rclone remote name and the provider-side bucket `calevate-dr` are names inside a config file / at a vendor | Not in production use (D-927). |
| Journald cap `/etc/systemd/journald.conf.d/calevate-cap.conf` | `infra/hygiene/journald-cap.conf:1` | install under the new name, remove the old, `systemctl restart systemd-journald` | Two caps: the smaller wins; harmless. |
| PostgreSQL drop-in `/etc/postgresql/16/main/conf.d/10-calevate-archiving.conf` | `infra/backup/postgresql-archiving.conf:3` | rename only the file; content has no name | A rename is a file move; no restart needed if content is unchanged. Do NOT delete it: losing `archive_mode` requires a PostgreSQL restart to restore and stops WAL archiving. Optional; recommend leave. |
| Sudoers file `/etc/sudoers.d/calevate-deploy` | `infra/privileged/sudoers.d/calevate-deploy` (user on lines 51, 57; script path on 57) | write `/etc/sudoers.d/<new>-deploy` with the new user and new script path; `visudo -c -f`; `sudo -l -U <new>` must list it; then remove the old file | A file name containing `.` is silently skipped by sudo. A wrong user = every nginx deploy prompts for a password, which under CD blocks rather than fails (`calevate-deploy:52-56`). |
| Root script `/usr/local/sbin/calevate-nginx-apply` | `infra/privileged/sbin/calevate-nginx-apply`; constants `DEPLOY_USER=calevate` (:55), `STAGING_ROOT=/var/lib/calevate/nginx-staging` (:57); log prefix (:74-75) | install as root:root 0755 under the new name; the sudoers line must name the new path exactly | The script must stay root-owned and not writable by the deploy user, or the grant is full root (`infra/privileged/README.md` §2). |
| Staging dir `/var/lib/calevate/nginx-staging/{conf.d,snippets}` | `calevate-nginx-apply:57`; `vps-deploy.sh:142`; `infra/privileged/README.md:52-55` | `install -d -o <new> -g <new> -m 0750` the new tree; keep mode 0750 | The script refuses a staging root owned by anyone other than `DEPLOY_USER`, or world-writable. |

## 3. Deploy and backup scripts (`scripts/`)

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| `COMPOSE_PROJECT` default `calevate` | `scripts/vps-deploy.sh:65`; `scripts/deploy/host-hygiene.sh:70`; `scripts/deploy/docker-reclaim.sh:157` | change all three with `compose.prod.yml:24` in one commit | `docker-reclaim.sh` prunes stopped containers by `label=com.docker.compose.project=$project`; a mismatch means it prunes nothing (disk grows) — never more than that. The deploy's `-p` always overrides the file's `name:` (`vps-deploy.sh:225`). |
| `IMAGE_REPO` default `calevate/app` | `vps-deploy.sh:135`; `host-hygiene.sh:71`; `compose.prod.yml:30` | change together | Old `calevate/app:<sha>` images are never trimmed by the per-commit tag cap after the switch (it scans only `IMAGE_REPO`); remove them by hand once no rollback needs them. |
| `NGINX_STAGING_ROOT`, `NGINX_APPLY` defaults | `vps-deploy.sh:142-143` | change with §2 | Mismatch = deploy cannot hand config to root. |
| `PM2_APP=calevate-web` | `host-hygiene.sh:73`; `vps-deploy.sh:1115-1121`; `apps/web/ecosystem.config.cjs:27` | change all three; on host `pm2 delete calevate-web` only after the new name is started and saved | If the deploy reloads a name pm2 does not know, `vps-deploy.sh` starts a SECOND web process on port 3000; it fails to bind while the old one keeps serving old code. |
| `RUNNER_DIR=$HOME/actions-runner-calevate` | `host-hygiene.sh:77`; `docs/DEPLOYMENT.md:492` | change if a runner is ever installed | No runner is installed (`runbooks/first-deploy.md:10`). |
| Lock and state: `CALEVATE_DEPLOY_STATE`, `CALEVATE_STATE_DIR`, `CALEVATE_HOST_LOCK`, `CALEVATE_HOST_LOCK_FD`, `CALEVATE_LOCK_WAIT_S`; file `$ROOT/.deploy-state/host.lock` | `scripts/deploy/host-lock.sh:38-69`; `vps-deploy.sh:66,1392`; `host-hygiene.sh:224`; function `calevate_repo_root` (`host-lock.sh:38`) | rename variables and function in one commit; the state dir moves with the deploy root | Deploy and hygiene must use the SAME lock file. A deploy on the new script and a hygiene run on the old unit (old path) lock different files and can prune Docker mid-deploy. Switch the hygiene unit in the same window. `.deploy-state` holds the deploy record (last deployed SHA per component): it must move with the checkout, or `--changed` redeploys everything. |
| `CALEVATE_IMAGE_TAG` | `compose.prod.yml:30`; `vps-deploy.sh:664-665` | rename both | A mismatch makes compose fall back to `:local`, an image that does not exist under the new repo name: swap fails. |
| `CALEVATE_DEPLOY_BUILD`, `CALEVATE_DEPLOY_BUILD_MIRROR` | `vps-deploy.sh:1099`; `apps/web/next.config.ts:39,79`; `tests/web_env_parity_guard_test.py` | rename in web and script together | If only one side changes, the deploy build loses its deploy-only refusals. |
| `CALEVATE_PYTHON` | `scripts/backup/app-python.sh:42,47` | rename; also any host drop-in that sets it (UNCHECKED) | Unset = falls back to `$ROOT/.venv/bin/python`; that is fine if the venv was rebuilt at the new path. |
| `CALEVATE_ALERT_STATE_DIR` | `scripts/backup/alert-to-app.sh:25` | rename; host drop-ins (UNCHECKED) | Unset = the relay's default state dir; duplicate-suppression state restarts once. |
| `CALEVATE_A11Y_CHROMIUM`, `CALEVATE_A11Y_SERVER` | `apps/web/tests/browser/gate.ts:206-233`; `Makefile:168` | rename | Developer-only. |
| Stamp files `/var/lib/postgresql/.calevate-wal-verify-stamp`, `.calevate-health-heartbeat`, `.calevate-heartbeat-state`, `.calevate-dump-size` | `scripts/backup/backup-health.sh:76-81`; `dump-offsite.sh:43` | rename in the script; on the host `cp -p` each old stamp to the new name before the first run | Missing heartbeat stamp = the gap check is blind for one run; missing heartbeat-state = one extra state-change line. Not data loss. |
| Syslog tags `calevate.backup`, `calevate.alert` | `backup-health.sh:343-376`; `basebackup.sh:75`; `notify.sh:59-97`; `dump-offsite.sh:170` | sed | Anyone grepping `journalctl -t calevate.backup` (runbooks, `backup-heartbeat-silent.md`) must use the new tag; old journal lines keep the old tag. |
| Offsite artifact name `calevate-<stamp>.dump` | `dump-offsite.sh:61-137` | sed | Not in production use. |
| `.calevate-write-probe` | `vps-deploy.sh:389-396` | sed | None. |
| `pg_dump` target DB `postgresql:///calevate` | `dump-offsite.sh:74` | follows the database decision (§7) | — |
| Restore-drill scratch DBs `calevate_drill_{src,restore}_<stamp>` | `scripts/restore_drill.py:103,630-631`; `Makefile:487` | rename the pattern | The drill refuses to drop anything not matching `SCRATCH_DB_PATTERN`; leftover old-named scratch DBs then need a manual `DROP DATABASE`. |
| Dev bootstrap defaults `DB_NAME=calevate`, `OWNER_ROLE=calevate`, `APP_ROLE=calevate_app` | `scripts/dev_bootstrap.sh:21-23`; `scripts/db_reset.py:71` | follows §7 | Dev only. |

## 4. Docker images and compose

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| Production compose project `calevate` | `compose.prod.yml:24` | see §9.3 for the Redis volume. Either pin `volumes: redis-data: {name: calevate_redis-data}` (keeps the data, keeps one old name), or stop the stack, copy the volume, start under the new project | Host objects named after it: containers `calevate-{redis,api,voice-runtime,workers}-1`, network `calevate_default`, volume `calevate_redis-data` (container names are compose's default `<project>-<service>-<n>`; check with `docker ps`). §0 item 2. |
| Image `calevate/app:<sha>` | `compose.prod.yml:30`; `vps-deploy.sh:135` | change the repo name; first deploy builds `<new>/app:<sha>` | Local-only image name (no registry push), so nothing outside the host references it. |
| Container user `calevate` (uid 10001) | `Dockerfile:163-178` | `useradd ... <new>`, `--chown=<new>:<new>` | Ownership is by uid 10001, which does not change, so the read-only rootfs and file ownership keep working. |
| Editable install path inside the image | `Dockerfile:94-108` (`_editable_impl_calevate_shared.pth` holds `/app/packages/shared/src`) | follows the Python package rename (§5) | If the distribution is renamed but the `.pth` path is not rebuilt, all four entrypoints die on their first import (the Dockerfile comment documents this exact failure). Caught by the image build smoke in CI. |
| Dev compose project `calevate-dev` | `docker-compose.yml:26` | rename to `<new>-dev`; MUST NOT equal the production project (`vps-deploy.sh:545-584` refuses; CI step at `.github/workflows/ci.yml:642-665` refuses) | New name = new empty volumes `<new>-dev_pgdata`, `<new>-dev_miniodata` (§10). |
| Dev Postgres env `POSTGRES_USER/PASSWORD/DB=calevate`, healthcheck `pg_isready -U calevate` | `docker-compose.yml:32-41` | change only together with a fresh volume | These variables only act when the data directory is EMPTY. On an existing volume, changing them does nothing to the cluster and the healthcheck then names a role that does not exist: the container is reported unhealthy forever. |
| Dev MinIO `MINIO_ROOT_USER=calevate`, `MINIO_ROOT_PASSWORD=calevate123` | `docker-compose.yml:68-69`; CI `ci.yml:152` | change with `.env` `OBJECT_STORE_*` keys | MinIO stores its root credential in the volume on first start (UNCHECKED for this MinIO build); on an existing volume a changed root user may not log in. Safer with a fresh volume. |
| Dev MinIO image `calevate-dev-minio` | built by compose from `infra/minio/Dockerfile` (project-derived name) | follows the project name | Old image stays until removed by hand. |

## 5. Python packaging and the `calevate_shared` import

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| Workspace root distribution `calevate` | `pyproject.toml:2,4` | rename | None outside the lock. |
| Members `calevate-api`, `calevate-voice-runtime`, `calevate-workers` | `apps/*/pyproject.toml:2`; root `pyproject.toml:16-18,35-38` | rename in all four manifests | Each member depends on `calevate-shared` by name (`apps/*/pyproject.toml:7/9`). |
| Distribution `calevate-shared`, import package `calevate_shared` | `packages/shared/pyproject.toml:2,16`; directory `packages/shared/src/calevate_shared/` (25 modules) | `git mv packages/shared/src/calevate_shared packages/shared/src/<new>_shared`; sed `calevate_shared` → `<new>_shared` and `calevate-shared` → `<new>-shared` everywhere | 832 import lines in 555 Python files; 1,146 mentions in 629 `.py` files; 1,458 mentions in 726 files overall. Also string targets for `monkeypatch`/`mock.patch("calevate_shared....")` in tests, which a careless regex limited to `import` lines would miss. |
| import-linter roots | `pyproject.toml:91,96` | sed | A missed name makes `lint-imports` fail in CI ("root package not found"), not silently pass. |
| `uv.lock` | 22 mentions (`uv.lock:158-296`) | do NOT hand-edit; after the manifests change run `uv lock` then `uv sync --all-packages` | A hand-edited lock fails `uv sync --locked` in CI. |
| Workspace `--all-packages` rule | `CLAUDE.md` Commands; every CI `uv sync` | unchanged | Workspace packages must come from `uv sync --all-packages`, never PyPI; a renamed `<new>-shared` that happens to exist on PyPI would be a supply-chain hazard only if someone ran a plain `pip install`. Check the new name is not taken on PyPI and keep `--all-packages`. |
| Local `.venv` editable link | `D:\Agency\calevate\.venv\Lib\site-packages\_editable_impl_calevate_shared.pth` (holds `D:\Agency\calevate\packages\shared\src`), `calevate_shared-0.1.0.dist-info`, `pyvenv.cfg` `prompt = calevate` | after the package rename, `uv sync --all-packages` rewrites them | Until re-synced, `import <new>_shared` fails and the old dist-info lingers. Never fix by reinstalling Python (machine rulebook). |
| VPS host `.venv` at `/var/www/calevate/.venv` | `runbooks/backup-setup-vps.md:93-108` | rebuild: `uv sync --frozen --all-packages` as the deploy user with `UV_PYTHON_INSTALL_DIR=/opt/<new>-python` | Holds absolute paths; the backup alert relay uses it (§0 item 1). |
| Web package | `apps/web/package.json:2` is `"web"`; root `package.json` has no name | nothing to rename | — |

## 6. CI/CD and GitHub

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| Repository `bb3agency/calevate-site` | `git remote -v` (local); VPS checkout remote (UNCHECKED, presumably the same) | rename in GitHub settings; then `git remote set-url origin` locally and on the VPS | GitHub redirects the old URL, so nothing breaks immediately; a NEW repository later created under the old name kills the redirect. |
| Self-hosted runner label `calevate-vps` | `.github/workflows/deploy.yml:98`; `docs/DEPLOYMENT.md:426` | change label in the workflow and on the runner together | No runner is installed (`runbooks/first-deploy.md:10`; `VPS_DEPLOY_ENABLED` unset), so today this is a text change only. If installed later, its systemd unit is `actions.runner.<org>-<repo>.<name>.service` (`DEPLOYMENT.md:521`), which embeds the repo name: re-register rather than rename. |
| Secret `VPS_CLIENT_PATH` (expected `/var/www/calevate`) | `deploy.yml:106,125` | update the secret value and the error text when the deploy root moves | Wrong value = deploy job refuses at "Verify required configuration". |
| Variables `ROOT_DOMAIN`, `TLS_LIVE_DIR`, `ORIGIN_CERT_PATH`, `ORIGIN_KEY_PATH`, `NGINX_AUTO_RELOAD`, `VPS_DEPLOY_ENABLED` | `deploy.yml:92,110-114`; values in `DEPLOYMENT.md:543-545` | update TLS paths if `/etc/ssl/calevate/` moves (§8) | — |
| Environment `production`, concurrency `deploy-production` | `deploy.yml:83,99` | no name in them | — |
| CI Postgres service `POSTGRES_USER/PASSWORD/DB=calevate`, role `calevate_app`, DSNs | `.github/workflows/ci.yml:43-44,60-65,168-171` | follows §7 | CI is a fresh database every run, so it follows whatever the migrations say. |
| CI bucket `calevate-ci`, MinIO creds | `ci.yml:47,152` | sed | CI only. |
| Workflow headers `Calevate CI`, `Calevate CD` | `ci.yml:1`, `deploy.yml:1` | sed | Cosmetic. Job display names carry no product name. |
| Guards that assert infra names | tests: `deploy_checkout_flag_test.py`, `deploy_workflow_guard_test.py`, `deploy_records_only_installed_nginx_test.py`, `host_hygiene_test.py`, `nginx_apply_snapshot_test.py`, `nginx_config_parses_test.py`, `nginx_hooks_vhost_test.py`, `nginx_log_redaction_test.py`, `nginx_origin_pull_test.py`, `nginx_origin_trust_test.py`, `edge_route_policy_test.py`, `backup_heartbeat_test.py`, `backup_alert_relay_test.py`, `restore_drill_test.py`, `server_image_dependency_set_test.py`, `web_env_parity_guard_test.py`, `deploy_env_preflight_test.py`, `env_example_bootstrap_floor_test.py` and others | update with the code they test | These fail loudly, which is what you want. Run `make coverage-ratchet` (hard rule 10) before pushing the rename. |

## 7. Database names and environment keys

| Name | Where | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| App role `calevate_app` | created by migration `alembic/versions/05bba2f3c19c_db_core_with_rls.py:593-601`; granted in 16 more migration files (39 mentions); `alembic/env.py:29,43`; `apps/api/core/settings.py:83,156-168` (`_DEV_DB_CREDENTIAL`); `scripts/check_deploy_env.py:296`; `scripts/db_reset.py:71`; `.env.example:60-64` | (a) repo: sed the role name in ALL migration files plus the code above; (b) production: `ALTER ROLE calevate_app RENAME TO <new>_app;` in the same window the new code ships, then update `DATABASE_URL` in `.env` | Grants, RLS policies and default privileges reference the role by OID, so `ALTER ROLE ... RENAME` keeps them. PostgreSQL clears an MD5 password on rename (the role name is the MD5 salt); a SCRAM password survives. Check `rolpassword` begins `SCRAM-SHA-256` first (§9.0), or have the password from the secrets manager ready to reset. If the repo migrations still said `calevate_app` after production renamed the role, any later migration that GRANTs to it fails mid-deploy. |
| Owner role `calevate` | `DEPLOYMENT.md:1419-1430`; `.env.example:65` (`ALEMBIC_DATABASE_URL`); `docker-compose.yml:32`; CI | `ALTER ROLE calevate RENAME TO <new>;` then update `ALEMBIC_DATABASE_URL` | Same MD5/SCRAM caveat. Owner of every table: renaming keeps ownership. |
| Database `calevate` | `walg.json.template:43` (`PGDATABASE`); `scripts/backup/dump-offsite.sh:74`; runbooks (`sudo -u postgres psql -d calevate`, `pg_dump -d calevate`); `.env` DSNs | `ALTER DATABASE calevate RENAME TO <new>;` — needs ZERO connections to it, so api, voice-runtime, workers, the hygiene and backup timers must be stopped first; then update `/etc/wal-g/walg.json` and both DSNs | Forgetting `walg.json`: the next nightly `backup-push` fails to connect (the alert unit fires, if §0 item 1 is intact). WAL-G backups are cluster-level, so existing backups stay valid; a restore yields the database under whichever name it had at the restore point. `pg_hba.conf` lines that name the database or user (UNCHECKED; the runbook only requires a CIDR + `scram-sha-256` line) would also need editing. |
| `pg_hba.conf` | host, `/etc/postgresql/16/main/pg_hba.conf` | `grep -v '^#' pg_hba.conf` first; edit only lines naming `calevate`; `SELECT pg_reload_conf();` | Editing a working `pg_hba.conf` blind can lock the containers out of the database. |
| `.env.example` keys and defaults | `DATABASE_URL` and `ALEMBIC_DATABASE_URL` values (`.env.example:64-65`), `OBJECT_STORE_BUCKET=calevate-dev` (:105), comments naming `admin.calevate.tech/ops` (:6,92) | sed the values; key NAMES carry no product name | `tests/env_example_bootstrap_floor_test.py:51,129` and `tests/deploy_env_preflight_test.py:163,355` pin `calevate-dev`; the preflight treats the example value verbatim in production as an error, so the test list follows. |
| VPS `.env` (`/var/www/calevate/.env`) | key names only: `DATABASE_URL`, `ALEMBIC_DATABASE_URL` (hold role and database names), `OBJECT_STORE_BUCKET` (`calevate-call-recordings`, `DEPLOYMENT.md:107`), domain-bearing keys (REBRAND-MAP §2B) | edit by hand from the secrets manager; never by script | The bucket CANNOT be renamed (REBRAND-MAP §2C); keep `calevate-call-recordings` and `calevate-db-backups` unless a copy project is planned. `.env` moves with the deploy root. |
| `CALEVATE_*` variables (14 names) | `CALEVATE_IMAGE_TAG`, `_ALERT_STATE_DIR`, `_HOST_LOCK`, `_HOST_LOCK_FD`, `_LOCK_WAIT_S`, `_STATE_DIR`, `_DEPLOY_STATE`, `_DEPLOY_BUILD`, `_DEPLOY_BUILD_MIRROR`, `_PYTHON`, `_A11Y_CHROMIUM`, `_A11Y_SERVER`, `_NUMBER_PREFIX`; `CALEVATE_PAISE_PER_MIN` is a TypeScript constant in `apps/web/src/lib/roi.ts:46`, not an environment variable | see §3 per variable | Any of these set by hand on the VPS (shell profile, systemd drop-in) is invisible to `git grep`: check with §9.0 before renaming. |

## 8. Production VPS (Hostinger srv1929611, Ubuntu 26.04.1) — what exists by name

Derived from the repo; every row is to be confirmed with §9.0 before acting.

| Name on host | Source in repo | Rename steps | Risk / what breaks if done wrong |
|---|---|---|---|
| User and group `calevate`, home `/home/calevate` (holds `~/.local/bin/uv`, `~/.profile` with `UV_PYTHON_INSTALL_DIR`, `~/.pm2/`) | `calevate-hygiene.service:24-33`; `DEPLOYMENT.md:139,172`; `backup-setup-vps.md:98-100` | stop every process of the user (pm2 daemon, hygiene timer); `usermod -l <new> calevate`; `groupmod -n <new> calevate`; `usermod -d /home/<new> -m <new>`; `id <new>` must show the `docker` group | `usermod` refuses while the user has running processes. The uid is unchanged, so file ownership everywhere stays correct; only NAMES in config break (sudoers, units, nginx-apply). The pm2 dump in `~/.pm2/dump.pm2` stores the process name and `cwd`. |
| Deploy root `/var/www/calevate` (git checkout, `.env`, `.deploy-state/`, `.venv`, `apps/web/.next`) | `vps-deploy.sh:63` (`VPS_CLIENT_PATH`), all units, `ecosystem.config.cjs` `cwd: __dirname` | `mv /var/www/calevate /var/www/<new>` then `ln -s /var/www/<new> /var/www/calevate`; rebuild `.venv`; remove the symlink only after every unit and the founder's deploy command point at the new path | §0 item 1. Compose's default project would be the directory basename; the deploy always passes `-p`, but a bare `docker compose` typed in that directory would address a new project. |
| `/etc/calevate/alerts.env` (also `rclone.conf`, `backup-recipients.txt` if they were ever placed) | 4 backup units; `infra/backup/README.md:99-101,200-226` | `install -d -m 0750 /etc/<new>`; `cp -p` each file; switch units; keep the old dir until verified, then remove | `EnvironmentFile=-` makes a missing file silent. |
| `/opt/calevate-python` (uv-managed CPython 3.12 for the relay venv) | `runbooks/backup-setup-vps.md:93-104`; `DEPLOYMENT.md:72,211` | install a fresh one: `install -d -o <new> /opt/<new>-python`, set `UV_PYTHON_INSTALL_DIR`, `uv python install 3.12`, rebuild `.venv` | The venv's `python` is a symlink into this directory; moving it without rebuilding the venv breaks the relay (exit 78, alarms reach nobody). Keep the old dir until the new venv passes `sudo -u postgres /var/www/<new>/.venv/bin/python -c "print('ok')"`. |
| `/var/backups/calevate/` (pre-migration `pg_dump -Fc` files, owner postgres, 0700) | `runbooks/first-deploy.md:549-550`; `DEPLOYMENT.md:936,1205` | create `/var/backups/<new>` with the same owner and mode; MOVE nothing until a newer dump exists; then move or keep | These dumps are the only same-host rollback point for a migration. Never delete. |
| `/var/lib/calevate/nginx-staging/` | §2 | new tree owned by the new user | §0 item 4. |
| `/var/log/calevate/web-{out,error}.log` | `apps/web/ecosystem.config.cjs:63-64`; `vps-deploy.sh:374-396` | `install -d -o <new> -g <new> -m 0755 /var/log/<new>`; ship the ecosystem change | The deploy probes the directory and refuses if missing. Old logs stay where they are. |
| `/etc/wal-g/walg.json` (`PGDATABASE: calevate`) | `infra/backup/walg.json.template:43` | edit `PGDATABASE` only if the database is renamed, in the same window | Path itself carries no name. Holds secrets: edit in place, never print. |
| systemd: `calevate-basebackup.{service,timer}`, `calevate-backup-health.{service,timer}`, `calevate-backup-alert@.service`, `calevate-hygiene.{service,timer}` (and `calevate-dump-offsite.*` only if ever installed) | §2 | §9.3 step 13 | Active timers: a timer disabled before its replacement is enabled is a gap; both enabled is a double run. |
| pm2 process `calevate-web`; pm2 boot unit (pm2's default name is `pm2-<user>.service`, so `pm2-calevate.service`, UNCHECKED) | `ecosystem.config.cjs:27`; `DEPLOYMENT.md:172` | after the user rename: `pm2 unstartup` (old), `pm2 startup systemd -u <new> --hp /home/<new>`, start the new name, `pm2 save`, `pm2 delete calevate-web`, `pm2 save` | A stale `pm2-calevate.service` with `User=calevate` fails at boot: web does not come back after a reboot. |
| nginx: `/etc/nginx/conf.d/{00-calevate-log-format,calevate-site,calevate-rate-zones,calevate-origin-trust}.conf`, `/etc/nginx/snippets/calevate-*.conf`, `/etc/nginx/certs/calevate-origin-pull-ca.pem` | §1 | §9.3 steps 10-11 | §0 item 3. |
| `/usr/local/sbin/calevate-nginx-apply`, `/etc/sudoers.d/calevate-deploy` | §2 | §2 | §0 item 4. |
| `/etc/ssl/calevate/origin.{pem,key}` (Cloudflare Origin CA cert for the default server) | `DEPLOYMENT.md:544-545,1453-1454` | optional: `install -d -m 0750 /etc/ssl/<new>`; `cp -p` both; update `ORIGIN_CERT_PATH`/`ORIGIN_KEY_PATH` (operator export and GitHub Variables) | A new DOMAIN needs a new origin certificate anyway (REBRAND-MAP §3 Cloudflare). The key is a secret: copy, never print. |
| `/etc/letsencrypt/live/calevate.tech/` lineage; renewal config | `DEPLOYMENT.md:1525-1571` | the lineage follows the DOMAIN, not the product name: issue a new lineage with `--cert-name <newdomain>` and the same `--deploy-hook "systemctl reload nginx"`; keep the old lineage while the old domain still serves | The runbook names the renewal file both `calevate.tech.conf` and `admin.calevate.tech.conf` (`DEPLOYMENT.md:1533` vs `:1570`); which one exists is UNCHECKED — `certbot certificates` answers it. Deleting the old lineage while nginx still references it = nginx fails its next reload. |
| `/etc/systemd/journald.conf.d/calevate-cap.conf` | §2 | §2 | Harmless. |
| `/etc/postgresql/16/main/conf.d/10-calevate-archiving.conf` | §2 | recommend leave | Removing it stops WAL archiving. |
| Stamps `/var/lib/postgresql/.calevate-*` | §3 | `cp -p` to new names | One blind run. |
| `/var/tmp/calevate-nginx-backup.*` | §1 | leave; delete by hand after 30 days | — |
| Docker: project `calevate`, containers `calevate-{redis,api,voice-runtime,workers}-1`, network `calevate_default`, volume `calevate_redis-data`, images `calevate/app:<sha>` | §4 | §9.3 | §0 item 2. |
| PostgreSQL: database `calevate`, roles `calevate`, `calevate_app`; drill scratch DBs `calevate_drill_*` if any were left | §7 | §7 | Rename needs zero connections; MD5 passwords are cleared by a role rename. |
| R2 prefixes and buckets | `walg.json` `WALG_S3_PREFIX` (from the secrets manager), `calevate-call-recordings`, `calevate-db-backups` | keep (REBRAND-MAP §2C) | A bucket cannot be renamed. Pointing wal-g at a new bucket starts a new, empty backup chain: the old chain would no longer be checked or pruned. |
| Host name | not in repo (`srv1929611` is Hostinger's) | `hostnamectl` to check; optional | — |
| Founder's deploy habit | `cd /var/www/calevate && sudo -u calevate scripts/vps-deploy.sh --expected-sha <sha> api voice-runtime workers web` (auto-memory `vps-deploy-command.md`) | update the memory and `runbooks/first-deploy.md` when the path and user change | The symlink keeps the old command working during the transition; `sudo -u calevate` stops working the moment the user is renamed. |

## 9. Cutover runbook (infra side)

Order: repository first, then the VPS, then the local machine. Every VPS step runs as the
sudo-capable login (`d_user` per `runbooks/backup-setup-vps.md:96`), inside the maintenance
window of `runbooks/maintenance-window.md`. Decide up front, per row of §0, whether that name
is renamed or kept; "keep" is always the cheaper and safer answer for the Redis volume, the R2
buckets and the PostgreSQL archiving drop-in.

### 9.0 Read-only inventory on the VPS (before writing a single line of the rename)

Run each, read it, save the output to the change record:

```sh
id calevate; getent group calevate docker
ls -la /var/www /etc/calevate /opt /var/backups /var/lib/calevate /var/log/calevate /etc/ssl/calevate
systemctl list-unit-files 'calevate-*' 'pm2-*' 'actions.runner.*'
systemctl list-timers --all | grep -i calevate
sudo -u calevate pm2 ls
ls -l /etc/nginx/conf.d /etc/nginx/snippets /etc/nginx/certs /etc/sudoers.d /usr/local/sbin
sudo certbot certificates
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Label "com.docker.compose.project"}}'
docker volume ls; docker network ls
docker image ls calevate/app
sudo -u postgres psql -c "SELECT datname FROM pg_database ORDER BY 1;"
sudo -u postgres psql -c "SELECT rolname, left(rolpassword, 14) AS hash_kind FROM pg_authid WHERE rolname LIKE 'calevate%';"
sudo grep -v '^\s*#' /etc/postgresql/16/main/pg_hba.conf | grep -v '^\s*$'
sudo grep -rn -i calevate /etc/systemd/system /etc/environment /home/calevate/.profile 2>/dev/null
git -C /var/www/calevate remote -v
```

The `pg_authid` query prints only the first 14 characters of the hash (its algorithm), never
the hash. If any role shows `md5`, have its password from the secrets manager ready before
renaming it.

### 9.1 Back up first (nothing in the rename starts until all of these exist)

1. Fresh logical dump: `sudo -u postgres pg_dump -Fc -d calevate -f /var/backups/calevate/pre-rename-$(date +%F-%H%M).dump`.
2. A fresh wal-g base backup, verified: run `calevate-basebackup.service` by hand and confirm
   `wal-g backup-list` shows it.
3. Redis snapshot: `docker exec calevate-redis-1 redis-cli SAVE`, then copy the volume
   contents out (`docker run --rm -v calevate_redis-data:/from -v /var/backups/calevate:/to alpine tar -C /from -czf /to/redis-pre-rename.tgz .`).
4. Copies of everything under `/etc/calevate`, `/etc/nginx/conf.d`, `/etc/nginx/snippets`,
   `/etc/sudoers.d/calevate-deploy`, `/usr/local/sbin/calevate-nginx-apply`,
   `/etc/systemd/system/calevate-*`, `/etc/wal-g/walg.json`, `/home/calevate/.pm2/dump.pm2`
   into one root-only directory (`install -d -m 0700 /root/pre-rename`). These hold secrets:
   copy with `cp -a`, never `cat`.
5. Note the deployed SHA (`.deploy-state`) so a rollback target is known.

### 9.2 Repository (one branch, one PR, CI green, `make coverage-ratchet` green)

1. Python package: `git mv packages/shared/src/calevate_shared packages/shared/src/<new>_shared`;
   sed `calevate_shared`/`calevate-shared` and the member names; `uv lock`;
   `uv sync --all-packages`; `uv run lint-imports`; `uv run mypy apps packages`.
2. Migrations, `alembic/env.py`, settings, `db_reset.py`, `dev_bootstrap.sh`, CI service
   definitions, `.env.example`: role and database names (only if §7 is in scope).
3. nginx: rename the template and snippet files and every include, upstream, variable and
   log format; keep `00-` and `000-` prefixes.
4. systemd units, sudoers, privileged script: file names and every user, path and
   `OnFailure=` value.
5. Scripts: `COMPOSE_PROJECT`, `IMAGE_REPO`, staging and apply paths, `PM2_APP`, lock and
   state variables, `CALEVATE_*` variables, stamp names, syslog tags, drill DB pattern.
6. Compose and Dockerfile: `name:` (prod and dev, still different), image name, container
   user; decide the Redis volume (pin `name: calevate_redis-data`, or plan the copy in §9.3).
7. Web: `ecosystem.config.cjs` name and log paths, `next.config.ts` build variable.
8. Workflows: runner label, error text, `VPS_CLIENT_PATH` text.
9. Tests that assert any of the above; docs and runbooks commands (`/var/www/<new>`,
   `sudo -u <new>`, unit names, `journalctl -t <new>.backup`).
10. Final sweep: `git grep -n -i calevate -- infra scripts compose.prod.yml docker-compose.yml Dockerfile Makefile .github pyproject.toml apps/*/pyproject.toml packages/shared/pyproject.toml uv.lock apps/web/ecosystem.config.cjs apps/web/next.config.ts`
    must return only names deliberately kept (R2 buckets, the Redis volume pin).
11. In the PR body: the cross-boundary rollback recipe (§9.4).

### 9.3 VPS (maintenance window; outbound campaigns paused; inbound calls drop for the restart minutes)

1. Stop timers that touch the stack or the database:
   `systemctl stop calevate-hygiene.timer calevate-backup-health.timer calevate-basebackup.timer`.
2. Stop the app: `sudo -u calevate pm2 stop calevate-web`;
   `docker compose -p calevate -f /var/www/calevate/compose.prod.yml stop` (stop, NOT `down -v`).
3. Database (only if renaming): connect as postgres and run, in one session:
   `ALTER DATABASE calevate RENAME TO <new>; ALTER ROLE calevate RENAME TO <new>; ALTER ROLE calevate_app RENAME TO <new>_app;`
   Reset any MD5 password flagged in §9.0. Edit `pg_hba.conf` lines that named them, then
   `SELECT pg_reload_conf();`. Edit `PGDATABASE` in `/etc/wal-g/walg.json`.
4. Redis volume (only if NOT pinned): `docker volume create <new>_redis-data`, then
   `docker run --rm -v calevate_redis-data:/from:ro -v <new>_redis-data:/to alpine sh -c 'cp -a /from/. /to/'`.
   Keep `calevate_redis-data` untouched until the new stack has run a week.
5. User: with no process of `calevate` running (`pgrep -u calevate` empty; stop the pm2 daemon
   with `sudo -u calevate pm2 kill`), `usermod -l <new> calevate`, `groupmod -n <new> calevate`,
   `usermod -d /home/<new> -m <new>`; check `id <new>` lists `docker`.
6. Directories: `mv /var/www/calevate /var/www/<new>` and `ln -s /var/www/<new> /var/www/calevate`;
   create `/etc/<new>` (copy `alerts.env` with `cp -p`), `/var/log/<new>`,
   `/var/lib/<new>/nginx-staging/{conf.d,snippets}` (owner `<new>`, 0750), `/var/backups/<new>`
   (postgres, 0700), `/opt/<new>-python` (owner `<new>`).
7. Pull the rename commit into `/var/www/<new>`; update `git remote set-url` if the repo was
   renamed; update `.env` DSNs by hand.
8. Rebuild the host venv per `runbooks/backup-setup-vps.md` Phase 2 with
   `UV_PYTHON_INSTALL_DIR=/opt/<new>-python`; prove `sudo -u postgres /var/www/<new>/.venv/bin/python -c "print('ok')"`.
9. Privileged pieces: install `/usr/local/sbin/<new>-nginx-apply` (root:root 0755) and
   `/etc/sudoers.d/<new>-deploy` (0440); `visudo -c -f`; `sudo -l -U <new>` lists it;
   `sudo -n /usr/local/sbin/<new>-nginx-apply --help` is refused by sudo. Then remove
   `/etc/sudoers.d/calevate-deploy`.
10. nginx: move `/etc/nginx/conf.d/{00-calevate-log-format,calevate-site,calevate-rate-zones,calevate-origin-trust}.conf`
    into `/root/pre-rename/nginx-conf.d/` (not deleted), so the next install does not collide.
    Leave the old snippets for now. The edge keeps serving from memory until the reload.
11. Deploy, as the new user, with the nginx step:
    `cd /var/www/<new> && sudo -u <new> env NGINX_AUTO_RELOAD=1 ROOT_DOMAIN=... TLS_LIVE_DIR=... ORIGIN_CERT_PATH=... ORIGIN_KEY_PATH=... scripts/vps-deploy.sh --expected-sha <sha> --all`.
    If the installer refuses `nginx -t`, it has restored the previous set; but step 10 moved
    the old site files out, so put them back from `/root/pre-rename/nginx-conf.d/` and
    `nginx -t && systemctl reload nginx` before investigating.
12. pm2: `pm2 startup systemd -u <new> --hp /home/<new>` (and `pm2 unstartup` the old unit if
    it exists), confirm `<new>-web` runs, `pm2 save`, remove any leftover `calevate-web`.
13. systemd: install the new units with `OnFailure=<new>-backup-alert@%n.service`, the alert
    template first; `systemd-analyze verify`; `daemon-reload`; `enable --now` the new timers;
    run `<new>-backup-health.service` and `<new>-basebackup.service` once by hand and confirm
    success in the journal under the new syslog tag; trigger the alert template once
    (`systemctl start <new>-backup-alert@test.service`) and confirm the email arrives. Only
    then disable and remove the old `calevate-*` units, copy the `/var/lib/postgresql/.calevate-*`
    stamps to the new names, `daemon-reload`.
14. Old compose project: `docker compose -p calevate -f /var/www/<new>/compose.prod.yml rm -s`
    removes only the stopped OLD containers (no `-v`, so no volume is touched). Confirm
    `docker ps` shows only `<new>-*` containers.
15. Verify: four hostnames answer through Cloudflare; `curl -fsS http://127.0.0.1:8000/healthz`;
    a test inbound call reaches voice-runtime; `systemctl list-timers` shows the new timers
    with next runs; `wal-g backup-list` shows the manual base backup; `ss -tlnp` shows no
    new `0.0.0.0` listener.
16. After seven clean days: remove the `/var/www/calevate` symlink (and update the founder's
    deploy command first), `/etc/calevate`, `/opt/calevate-python`, old nginx snippets, old
    `calevate/app` images, and — only on an explicit decision — the old Redis volume. Keep
    `/var/backups/calevate` dumps.

### 9.4 Rollback across the boundary

The old script's defaults name the old world. To redeploy a pre-rename commit after the host
has been renamed:

```sh
cd /var/www/<new> && sudo -u <new> env COMPOSE_PROJECT=<new> IMAGE_REPO=<new>/app \
  NGINX_STAGING_ROOT=/var/lib/<new>/nginx-staging NGINX_APPLY=/usr/local/sbin/<new>-nginx-apply \
  scripts/vps-deploy.sh --checkout <old sha> api voice-runtime workers
```

Leave `nginx` and `web` out: the old nginx templates name `calevate-*` snippets and the old
pm2 config names `calevate-web` and `/var/log/calevate`. Old code also expects the old Python
package name, which is inside its own image, so the app containers are self-consistent; if
the database or roles were renamed, the old commit's `.env` DSNs are the new ones (it is the
same file), which works. Old migrations that GRANT to `calevate_app` would fail, so a rollback
that crosses a migration is a database restore, not a redeploy.

### 9.5 Local machine (D:\Agency\calevate, Windows 11)

Order matters here because of the machine rulebook: nothing is removed, renamed or pruned
without the owner's explicit decision, and a Docker volume cannot be renamed.

| Name | Current state (read 29 Oct 2026) | Rename steps | Risk |
|---|---|---|---|
| Compose project `calevate-dev`; containers `calevate-dev-postgres-1` (5433), `calevate-dev-redis-1` (6380), `calevate-dev-minio-1` (9000/9001); network `calevate-dev_default`; image `calevate-dev-minio:latest` | running | after the repo rename: `docker compose -p calevate-dev stop` (not `down -v`), then `docker compose up -d` creates `<new>-dev-*` | Same host ports: the old containers must be stopped first or the new ones fail to bind. |
| Volumes `calevate-dev_pgdata`, `calevate-dev_miniodata` | present | Option A (simplest): new empty volumes, then `make db-reset` and the seed. Option B (keep data): create `<new>-dev_pgdata` and copy with a throwaway container while the old Postgres is stopped, same for MinIO. Keep the old volumes until the owner decides | The old cluster's superuser is `calevate`; copying it into a stack whose `POSTGRES_USER` is `<new>` keeps the OLD role (the env var only acts on an empty directory), so with option B leave the dev role names unchanged or rename them inside Postgres. |
| Other `calevate`-named Docker objects | containers `calevate-perf` (exited), `calevate-gate-minio` (exited); volumes `calevate-kb-venv`, `calevate-test-venv`; none referenced in the repo | leave; they are scratch objects of past sessions | Do not prune; the rulebook forbids it without a decision. |
| Repo folder `D:\Agency\calevate` | holds about 100 git worktrees under `.claude\worktrees\` plus one in the scratchpad | if moved: `git worktree repair` from the new root afterwards; or leave the folder name as is (it is invisible to everyone) | Each worktree's `.git` file and `.git\worktrees\*\gitdir` hold absolute paths; a moved folder leaves them all "prunable". |
| `.venv` | Python 3.12 venv, `prompt = calevate`, editable `.pth` pointing at `D:\Agency\calevate\packages\shared\src` | `uv sync --all-packages` after the package rename and after any folder move | Never reinstall Python; the rulebook's Calevate checks change to `import <new>_shared` and its new file path. |
| rememory project `calevate` | `D:\rememory\config\projects.yaml:4-5` (`root: D:\Agency\calevate`); Qdrant collections are shared (`code`, `docs`, `memory`) with the project as a payload field | keep the project KEY `calevate`; if the folder moves, update only `root:` and re-run `sync_index` | Renaming the key orphans every stored memory, which is tagged with the old key. |
| Claude memory `C:\Users\jumes\.claude\projects\D--Agency-calevate\` | folder name is derived from the repo path | if the folder moves, COPY (not move) `memory\` into the new derived folder; `~/.claude/CLAUDE.md` names `D:\Agency\calevate`, `calevate-dev-*` containers and volumes, so update it with the owner | A moved repo starts with an empty project memory. |
| `.claude/launch.json` | untracked; names no product (`web`, `web-mock`, `api-mock`); `api-mock` points at a session scratchpad path that contains `D--Agency-calevate` | nothing for the rename; the scratchpad entry is session-scoped | — |

Local order: stop the old dev stack → pull the rename → `uv lock`/`uv sync --all-packages` →
bring up the new dev stack → `make db-reset` (option A) → run the rulebook checks
(`uv run alembic --version`, `uuid_utils`, `import <new>_shared`) → `make dev-otp`.
