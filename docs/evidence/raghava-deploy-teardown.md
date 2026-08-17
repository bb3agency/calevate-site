# raghava-organics deploy tooling — teardown and extraction plan

**Read this before touching `scripts/vps-deploy.sh`, `infra/`, or the first-admin bootstrap.**

**What this is.** A file-by-file read of the deploy, bootstrap, secrets, backup/DR,
edge and observability tooling in the founder's other project, done because two
decisions changed our deployment story: **Clerk is removed entirely (first-party auth
only)** and **hosting moves to a Hostinger India VPS**. `docs/DEPLOYMENT.md` already
calls that repo "raghava-proven" and inherits from it by name; this file is the first
time anybody has actually opened it and checked.

**Provenance.** Read-only clone at `/workspace/bb3agency/raghava-organics-site`, on
2026-08-17. Every path below is relative to that clone's root. Every claim carries
`file:line`. Nothing was executed — this is a source read, so where a behaviour depends
on the host (sudo grants, cron, Docker daemon state) the claim is about what the code
*would* do, and is marked as such.

**Posture.** A read-only repo is not a trusted one. The founder's brief was explicit
that its auth layer already yielded five real defects, and the ops tooling yields the
same mix: some of the best single-VPS deploy engineering in either repository, sitting
next to a disaster-recovery suite that **fabricates its own evidence and then validates
it in CI**. Both halves are recorded here with equal specificity. §8 is the defect list;
§9 is what we do about it.

**What this is NOT.** Not a port. Its backend is Node/TypeScript with Prisma and BullMQ;
ours is Python/FastAPI with alembic and ARQ, and CLAUDE.md forbids a second backend
language. Nothing here proposes copying a line of their code. What transfers is
*operational design*: the sequence, the refusals, the failure modes they paid for.

---

## 1. The deploy pipeline, step by step

### 1.1 What triggers it

Two workflows, one per repo layout, materially identical:
`.github/workflows/deploy.yml:1-229` (monorepo — the live one) and
`backend/.github/workflows/deploy.yml:1-175` (backend-only template).

- `workflow_run` on **"Reliability CI"** completing on `main`/`master`, plus
  `workflow_dispatch` (`.github/workflows/deploy.yml:12-25`).
- Gated by repository Variable `VPS_DEPLOY_ENABLED == 'true'` **and** a re-check of
  `workflow_run.conclusion == 'success'` (`.github/workflows/deploy.yml:38-42`) —
  `workflow_run` fires on failed runs too, and this is the check that stops a red build
  shipping. We already have the identical pair of gates.
- `concurrency: vps-deploy-${{ github.repository }}` with `cancel-in-progress: false`
  (`.github/workflows/deploy.yml:30-32`) — cancelling between migrate and swap would
  manufacture the half-deployed state the ordering exists to prevent. Same reasoning,
  same setting, as ours.
- Runs on a **self-hosted runner on the VPS** (`runs-on: ${{ vars.VPS_RUNNER_LABEL ||
  'self-hosted' }}`, `.github/workflows/deploy.yml:37`). No inbound SSH; the runner polls
  GitHub outbound. Paths in Secrets (`VPS_CLIENT_PATH`), flags in Variables — the
  convention `docs/DEPLOYMENT.md` §3 already cites.
- Backend and frontend are **two independent jobs** (`deploy-backend`,
  `deploy-frontend`), the frontend one additionally gated on `FRONTEND_DEPLOY_ENABLED`
  (`.github/workflows/deploy.yml:114-122`).

### 1.2 `backend/scripts/vps-deploy.sh` — 648 lines, in order

Invoked as `bash "$VPS_CLIENT_PATH/scripts/vps-deploy.sh" "$VPS_CLIENT_PATH"
"$COMMIT_SHA"` (`.github/workflows/deploy.yml:112`).

| # | Step | Lines | What it does |
|---|---|---|---|
| 0 | Validate environment | `70-80` | `CLIENT_PATH` exists; `.env` present (**never written by the script**); `docker-compose.yml` and `docker-compose.prod.yml` present. Compose project name = `CLIENT_ID` from `.env`, falling back to the literal `client-backend`. |
| 1 | Pull | `85-97` | `git fetch origin main`; `git checkout main`; `git pull origin main --ff-only`; then **abort if `HEAD != $EXPECTED_SHA`** (`94-96`). This is the CI-validated-commit race guard; we have the same one as `--expected-sha`. |
| 1.25 | `npm ci` | `103` | Lockfile-pinned install on the host, so the host Prisma CLI cannot drift from the pinned version. |
| 1.5 | **Env preflight** | `109` | `node scripts/verify-client-bootstrap-env.mjs` — the only real preflight in the pipeline. See §2. |
| 1.75 | **Dead-container sweep** | `135-205` | Finds `dead`/`exited`/`created`/`removing` containers for this compose project, `docker rm -f`, then `rm -rf /var/lib/docker/containers/<full-id>` (as root, or `sudo -n`). **Re-queries afterwards and aborts the deploy** if tombstones survive (`179-201`), printing the exact recovery command. |
| 1.5b | **Pre-build disk reclaim** | `221-251` | Always: `container prune`, `image prune`, `builder prune --keep-storage 3GB`; trims `~/actions-runner/_diag/*.log` older than 2 days. If free space on the Docker root `< PREBUILD_MIN_FREE_GB` (8): hard `image prune --all` + `builder prune --all`. If still `< PREBUILD_HARD_FLOOR_GB` (3): **abort before building**, with the reclaim commands in the message. |
| 2 | **Serial build** | `265-268` | `for build_svc in backend workers` — one `docker compose build` at a time, because parallel builds OOM the host and the OOM reads as a CI flake. |
| 3 | **Migrations, before the swap** | `275-278` | Reads `DATABASE_URL` out of `.env` and **rewrites `host.docker.internal` → `127.0.0.1`** (`276`), then `prisma migrate deploy` on the *host* via the project-local CLI. |
| 3.5a | Maintenance page install | `367-395` | `sudo -n cp nginx/maintenance.html /etc/nginx/maintenance/maintenance.html` when content differs. Records a status string re-emitted in the final summary. |
| 3.5b | **nginx render + drift + reload** | `397-492` | Resolve live vhost path via `scripts/lib/resolve-nginx-live-conf.sh`; `envsubst` the three placeholders; **refuse if any `${VAR}` survives** (`421-426`); diff against live; under `NGINX_AUTO_RELOAD=1` **back up the live file**, install, `nginx -t`, **restore from backup on a failed test** (`469-480`), else reload. Without the sudo grants it degrades to a warning rather than hanging on a password prompt (`458-462`). |
| 4 | **Container swap** | `522-539` | Deliberately **not** `up --force-recreate`. Instead: `compose stop backend workers redis` → `docker rm -f` **by canonical name** → `compose up -d --remove-orphans redis` then `... backend workers`. The reasoning is in the comment block at `494-521`: force-recreate's rename-then-create path re-triggers the phantom-start failure the §1.75 sweep exists to fix. |
| 5 | Health check | `544-562` | Poll `http://127.0.0.1:$BACKEND_PORT/api/v1/health`, **90 × 2s = 3 min** (`36-37`). The comment at `30-35` records why 60s was wrong: shorter than a migrate-on-boot, so every migration release went red and operators learned to ignore red deploys. On timeout: dump 50 lines of backend + workers logs, then fail. |
| 5.5 | Readiness (**non-blocking**) | `569-579` | `GET /api/v1/health/ready`; warns if `status != ready` or `runtimeConfigMissingKeys != []`, but never fails. Deliberate: ops config is filled in incrementally from a console, and CD must still be able to ship a code fix into a partially-configured platform. |
| 6 | Workers alive | `584-588` | `compose ps workers --format json` → warn if not `running`. Warn only. |
| 7 | Post-build prune | `605-611` | `image prune -f`, `builder prune --keep-storage 3GB`. |
| — | Summary | `618-648` | Re-emits the maintenance-page status as a banner so a warning 400 lines up cannot be missed. |

### 1.3 Where the cutover happens, and whether it is zero-downtime

**It is not zero-downtime, and unlike ours it does not say so.** The cutover is step 4,
`vps-deploy.sh:522-539`: an explicit `stop` → `rm -f` → `up -d`. That is a strictly
*longer* outage than a `compose up -d` recreate, because the container is removed and
recreated rather than replaced, and because `redis` is stopped alongside `backend` and
`workers` on **every** deploy (`523`) — so a code-only change bounces the queue.

The only in-repo acknowledgement is a comment claiming "Nginx maintenance page handles
the ~3–5s window automatically" (`vps-deploy.sh:495-496`). That is half true: the nginx
template does map `error_page 502 503 /maintenance.html`
(`backend/nginx/client.conf.template:103`) with an inline fallback
(`backend/nginx/client.conf.template:123-129`), so a user hitting the gap sees a branded
page rather than a bare nginx 502. A friendly error page is not uptime. There is no
second replica, no upstream drain, no `stop_grace_period` anywhere in
`backend/docker-compose.yml` or `backend/docker-compose.prod.yml` — so in-flight work
gets Docker's default 10s SIGTERM window and no more.

Current practice for this exact topology is a blue/green pair behind an nginx upstream
whose `proxy_pass` target is rewritten and `nginx -s reload`ed, which keeps in-flight
requests on the old workers while new ones route to the new stack
([MassiveGRID, blue-green and rolling deployments on an Ubuntu VPS](https://massivegrid.com/blog/zero-downtime-deployment-ubuntu-vps/);
[Bhesh Raj Neupane, "Zero-Downtime Deployments with Blue-Green, Docker, and GitHub Actions", July 2026](https://bheshrajneupane.medium.com/guide-to-set-up-zero-downtime-blue-green-deployment-with-docker-nginx-and-github-actions-e0510e3192c6)).
Our `docs/DEPLOYMENT.md` §4b already names that shape, already rejects the third-party
`docker rollout` plugin under hard rule 9, and already states the gap honestly. **On
this axis we are ahead of them and should stay there** — the thing to take from their
script is the *ordering and the refusals*, not the cutover.

### 1.4 What happens on a failed migration

Nothing catches it. `set -euo pipefail` (`vps-deploy.sh:26`) means a non-zero
`prisma migrate deploy` (`278`) terminates the script immediately: no banner naming the
step, no recorded schema revision, no rollback, and — importantly — **the containers have
not been swapped yet**, so the old code keeps serving. That last property is correct and
is the same property our ordering buys.

What is missing relative to ours:

- **No revision recorded before or after.** A manual recovery has to go find the schema
  version itself. Ours records it on both sides precisely so a downgrade has a target
  rather than a guess (`docs/DEPLOYMENT.md` §4a).
- **No rollback path at all.** Their documented rollback is `git checkout <old-sha>` and
  re-run, which re-enters `prisma migrate deploy` from the older checkout. Prisma's
  `migrate deploy` tolerates a database ahead of the migrations folder more gracefully
  than alembic does, so they do not hit our `Can't locate revision` failure — but they
  also have no equivalent of `scripts/deploy_revision_check.py`, and nothing tells the
  operator that the schema is now ahead of the code.
- **`prisma migrate deploy` runs each migration in its own transaction by default**,
  which is the same property our `transaction_per_migration=True` buys. Fine.
- **The migration runs on the host, against a rewritten DSN** (`vps-deploy.sh:276`).
  That `sed 's/host\.docker\.internal/127.0.0.1/'` is a string rewrite of a credential
  string in a shell pipeline, and it is the kind of thing that works until a password
  contains the literal text. Ours runs migrations **inside the new image** via a compose
  profile, so there is exactly one form of the URL and nothing rewrites it. Keep ours.

---

## 2. Preflight — the section that turned out backwards

The brief expected `verify-vps-deploy-preflight.mjs` to be the crown jewel. **It is not,
and saying so is the finding.**

### 2.1 What `verify-vps-deploy-preflight.mjs` actually is

93 lines (`backend/scripts/verify-vps-deploy-preflight.mjs`). It is a **repository
artifact check that never touches a host**, and its own header says so:
"Validates repository artifacts required for VPS deploy (no live VPS connection)"
(`:3-4`). It runs as `npm run verify:vps-preflight`
(`backend/package.json:20`) and — this is the part that matters — **it is not called by
`vps-deploy.sh` at all.** Grep the deploy script: the only verifier it invokes is
`verify-client-bootstrap-env.mjs` (`vps-deploy.sh:109`).

What it checks:

1. **Eleven files exist** (`:12-24`): the compose file, both deploy scripts, three nginx
   files, two workflows, three docs.
2. **Two monorepo workflows exist** (`:26-29`).
3. **`vps-deploy.sh` contains six substrings** — `CLIENT_PATH`, `prisma migrate deploy`,
   `/api/v1/health`, `/api/v1/health/ready`, `runtimeConfigMissingKeys`,
   `docker compose -p` (`:47-62`).
4. **`vps-frontend-deploy.sh` has exactly one shebang** and contains `npm ci`,
   `pm2 reload`, `resolve_storefront_port` (`:64-76`).
5. **`docker-compose.yml` mentions `${CLIENT_ID`** (`:78-84`).

Check 3 is the defect that makes the whole file untrustworthy: it asserts a **string is
present somewhere in a shell script**, which a comment satisfies. Move
`prisma migrate deploy` into a `# TODO` line and delete the call, and this preflight
still passes. Our own `scripts/check_docs_drift.py` records exactly this rejection in
its research note — the raghava `docs:runtime-drift-check` shape was "adopted as the
IDEA, not the mechanism… a grep asserts a string is present somewhere, which stays green
when the string moves into a docstring that also went stale." That judgement was correct
and this file is the evidence for it.

The shebang counter (`:67-69`) is the tell for what this file is really for: it exists
because someone once concatenated two scripts and shipped a file with two shebangs. It
is a scar-tissue linter, not a deploy gate.

### 2.2 What the *real* preflight is: `verify-client-bootstrap-env.mjs`

209 lines (`backend/scripts/verify-client-bootstrap-env.mjs`), called at
`vps-deploy.sh:109`, before any build, migration or swap. It parses `.env` by hand
(`:18-30`) and refuses to deploy over:

| Refusal | Line | Why it is good |
|---|---|---|
| `.env` absent | `:13-16` | Same floor as ours. |
| Eight keys missing: `CLIENT_ID`, `POSTGRES_DB`, `DATABASE_URL`, `REDIS_PASSWORD`, `REDIS_URL`, `JWT_SECRET`, `JWT_REFRESH_SECRET`, `OPS_DB_ENCRYPTION_KEY` | `:41-48` | Presence by name, never by value. |
| `CLIENT_ID` still the template default | `:50-52` | Catches a copied workspace. |
| `POSTGRES_DB` contains a hyphen | `:54-56` | Invalid unquoted PG identifier — a class of error that surfaces two steps later as a connection failure. |
| `DATABASE_URL` still names the template database | `:58-60` | Catches a copied `.env`. |
| **`DATABASE_URL`'s db name ≠ `POSTGRES_DB`** | `:62-64` | **Cross-field consistency. We have no equivalent.** |
| **`REDIS_URL` does not embed `REDIS_PASSWORD`** | `:70-72` | **Same class, same gap on our side.** |
| Any of the three secrets still contains `replace_with` / `change_me` | `:74-82` | Placeholder detection. |
| **`JWT_REFRESH_SECRET == JWT_SECRET`** | `:84-86` | **A real cryptographic refusal: reusing one signing key across two token classes collapses the refresh/access distinction.** |
| `PORT` missing, or `!= 3000` | `:93-98` | Container-internal port is a contract with the compose mapping. |
| `PAYMENT_PROVIDER=razorpay` set in `.env` without the three Razorpay keys | `:113-117` | Refuses a *half*-configured integration rather than one that is simply absent. |
| Any configured Delhivery/Shiprocket key still a placeholder | `:151-168` | Same shape. |

And it **warns** (does not fail) on: unexpected `NODE_ENV` (`:88-91`); `PAYMENT_PROVIDER`
unset (`:109-112` — correct, that is the Phase-1 bootstrap state); `SHIPPING_PROVIDER`
set at all, because it is ignored and its presence misleads (`:138-143`);
`RESEND_API_KEY` placeholder (`:170-172`); `REPLAY_APPROVAL_TOKEN` /
`OPS_METRICS_TOKEN` unset (`:174-180`); and **R2 credentials present in `.env` at all**,
because they belong in the ops console (`:182-195`).

That last one has a dedicated companion, `verify-r2-media-config.mjs:41-48`, which
**fails** on the same condition. Two scripts, two verdicts, one question — a "one way per
problem" violation in their tree, and the reason it survives is that the failing one is
not wired into the deploy.

### 2.3 Which of their checks do we lack — the honest answer

We are ahead. `scripts/vps-deploy.sh:166-251` (`preflight`) already refuses on: missing
tools, docker compose v2, missing compose file and Dockerfile, dev-compose project-name
collision, missing `.env`, `.env` mode (warn), **`AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` by name**, **`PLATFORM_KEK` by name**, a **dirty checkout**,
free disk, and a **Cloudflare IP list older than 180 days**. `preflight_plan`
(`scripts/vps-deploy.sh:268`) adds the plan-dependent refusals, and step 6 of our
sequence runs `validate_bootstrap_env()` + `Settings()` **inside the new image**, which
is a strictly stronger question than parsing `.env` with `grep` on the host.

Three things they check that we genuinely do not:

1. **Cross-field consistency between env vars.** `DATABASE_URL` vs `POSTGRES_DB`,
   `REDIS_URL` vs `REDIS_PASSWORD`. Our analogue: `DATABASE_URL` and
   `ALEMBIC_DATABASE_URL` must name the same host and database but different roles, and
   `REDIS_URL` must name `redis` by service name rather than `localhost` — none of that
   is checked anywhere. A `REDIS_URL` pointing at `localhost` inside a container is a
   deploy that swaps cleanly and then 503s on `/healthz`.
2. **Distinctness of two secrets that must differ.** Once first-party auth lands we will
   have an access-token key and a refresh-token key, and `JWT_REFRESH_SECRET !=
   JWT_SECRET` becomes a refusal we need. Same shape as `PLATFORM_KEK` vs
   `PLATFORM_KEK_RETIRED`, which we also do not check.
3. **Placeholder-text detection.** We check presence; we do not check that the present
   value is not `change_me`. `.env.example` ships placeholder-shaped values, and copying
   it is how a host gets one.

And one thing they do that we should copy verbatim in shape, from the deploy script
rather than the verifier: **pre-build disk reclaim with a two-tier floor**
(`vps-deploy.sh:221-251`). Ours refuses at `< 3GB` and prints the prune commands; theirs
*runs* the safe prunes, escalates to a hard purge under 8GB, and only then refuses under
3GB. Their comment (`:208-219`) records the deadlock that motivated it — the post-build
prune only runs after a *successful* build, so a near-full disk kills the build and
wedges every subsequent deploy. That is a real trap and our version walks into it.

---

## 3. First-admin bootstrap on a bare host

This section matters more than the rest, because Clerk's removal deletes our current
answer. `scripts/bootstrap_admin.py` writes an `admin_users` row keyed on
`--clerk-user-id`, taken from "the ADMIN Clerk application's Users page"
(`scripts/bootstrap_admin.py:39-44`). With Clerk gone there is no such id, so the script
has no input and a fresh Calevate host has **no way in** — the exact failure its own
docstring was written to close.

Their repo has solved this, twice, with one good design and one bad one.

### 3.1 The good one — invite tokens (`ops-newuser.mjs`)

`backend/scripts/ops-newuser.mjs`, 188 lines, run once per host from a trusted operator
shell (`backend/docs/CLIENT_VPS_SETUP_GUIDE.md:628-641`, the command at `:634`):

```
npm run ops:newuser -- --email=<ops@email> --name="Primary Ops" \
  --setup-base-url="https://<client-domain>" --yes
```

End to end:

1. **DSN normalisation for host-shell execution** (`:7-22`): if `DATABASE_URL` names
   `host.docker.internal` and `/.dockerenv` does not exist, rewrite to `127.0.0.1`. The
   container-hostname-outside-a-container trap, handled explicitly. We have the same
   trap and no such guard.
2. **Explicit consent flag**: refuses without `--yes` (`:120-122`).
3. **Permission validation**: only `OPS_READ` / `OPS_WRITE` accepted, anything else
   throws (`:60-72`). The merchant-admin sibling `admin-newuser.mjs:90-111` validates
   against a 25-entry allowlist and **requires** `--permissions` — no implicit grant.
4. **Token**: `crypto.randomBytes(32).toString('base64url')` (`:133`) — 256 bits of
   entropy.
5. **Storage**: only `sha256(token)` is persisted, as `inviteTokenHash` (`:74-76,134`).
   Unsalted SHA-256 is **correct here** and is not the same defect as the 6-digit OTP the
   founder found in their auth layer: a 256-bit random token has no dictionary to attack,
   so a slow KDF buys nothing and the constant-time-lookup-by-hash property is what you
   want. Worth stating explicitly so nobody "fixes" it into bcrypt.
6. **TTL**: `INVITE_TTL_MS = 10 * 60 * 1000` (`:26`) — ten minutes.
7. **Email**: direct `fetch` to `https://api.resend.com/emails` with a 10s
   `AbortSignal.timeout` (`:89-102`), requiring `RESEND_API_KEY` + `RESEND_FROM` and
   throwing a message that names the checklist step when they are absent (`:80-86`).
8. **Status ladder**: row created `CREATED` (`:147-158`), flipped to `EMAIL_SENT` **after
   the send succeeds** (`:169-172`) — so a failed send leaves an auditable `CREATED` row
   rather than a lie.
9. **Consume** (`backend/src/modules/ops/ops.service.ts`): resolve by token hash
   (`:405-425`), reject unless status is `CREATED`/`EMAIL_SENT` (`:412-414`), and on
   expiry mark `EXPIRED_CLEANED` **via a CAS `updateMany` scoped to the active statuses**
   rather than a read-then-write (`:416-421`). Then a second factor — an emailed OTP with
   an attempt counter in Redis that deletes the challenge at the cap (`:861-876`) — then
   cross-domain uniqueness checks against both `User` and `OpsUser` (`:878-892`), then a
   **`$transaction` that creates the ops user and CAS-consumes the invite together**
   (`:900-924`), failing with 409 if `consumeResult.count === 0`. Then an
   `INVITE_CONSUMED` audit-log append (`:928-940`).
10. **Idempotency**: not idempotent, deliberately. Re-running mints a *new* invite; the
    consume is what is single-use, enforced by the CAS. `admin-newuser.mjs:165-177`
    additionally refuses when a user already exists unless it is a deactivated admin
    being reactivated.

This is the right architecture for us and it maps onto our vocabulary with no
translation: `admin_users` gets an invite sibling, `scripts/bootstrap_admin.py` becomes
an invite minter, and the consume path is a route in the admin realm.

**Two defects in it, which we must not carry over:**

- **The setup URL — token and all — is printed to stdout** (`ops-newuser.mjs:178`,
  `admin-newuser.mjs:224`: `logger.info(\`SETUP_URL=${setupUrl}\`)`). Their own docs tell
  the operator to run it "from a trusted operator shell (not CI logs, not shared terminal
  sessions)" (`CLIENT_VPS_SETUP_GUIDE.md:641`), which is a documented mitigation for a
  code-level leak. A bearer credential printed to a terminal ends up in scrollback, in
  `script` captures, and in whatever the shell's history plugin does. Print the invite
  **id** and the expiry; never the token.
- **The TTL is ten minutes for an emailed link.** That is shorter than mail delivery to a
  cold inbox on a first-run host whose sender domain was verified an hour ago. Their
  post-checks acknowledge it by telling the operator to complete setup "within 10
  minutes" (`CLIENT_VPS_SETUP_GUIDE.md:653,685`). Ten minutes is an OTP TTL, not an invite
  TTL; 24h with single-use CAS consume and an explicit revoke path is the ordinary
  design, and their revoke path already exists (`ops.service.ts:1671-1680`).

### 3.2 The bad one — `seed-admin.mjs`, and why it is the pattern NOT to copy

`backend/scripts/seed-admin.mjs:70`:

```js
logger.success(`Admin created: ${admin.email} / ${PASSWORD} (${allPermissions.length} permissions granted)`);
```

**This logs a live administrative password in cleartext.** Say it plainly, because the
surrounding code makes it worse rather than better:

- `PASSWORD` defaults to the literal `'Admin@12345'` (`:24`), so on any host where
  `SEED_ADMIN_PASSWORD` is unset the account is created with a password that is in the
  repository.
- The account is created `isVerified: true, isBanned: false` with **all 27 permissions**
  (`:29-37,66-68`) — the widest authority in the system, in one non-interactive command.
- `--reset` **deletes the existing admin and its grants** and recreates them (`:47-51`),
  so running it against a live database silently rotates a real operator's credentials.
- `logger.success` goes through the same writer as every other level
  (`backend/scripts/lib/logger.mjs:110-121`), so if the process is run under CI or with
  `LOG_JSON`, the password lands in structured logs.
- The sibling `upsert-admin.js:7-8` has the same default password and is invoked **in
  CI** at `.github/workflows/reliability-ci.yml:206` — it writes the user id to stdout
  rather than the password (`:64`), which is the correct choice and shows they knew.

Their own docs already forbid it in production: *"Do not use `scripts/seed-admin.mjs` for
VPS production onboarding. Use invite-based provisioning… only."*
(`CLIENT_VPS_SETUP_GUIDE.md:692-693`). That is the right call and it is also the wrong
control: a footgun that is safe because a document says not to pull it is a footgun that
will be pulled by whoever did not read the document — an agent, a new hire, a 3am
operator grepping for "admin".

**The rule for us:** a bootstrap script may print an identifier, a status and an expiry.
It may never print, echo, log, or write to a file any credential it just created —
including one it generated itself. If a human needs the secret, it goes out of band
(email, in our case) and the process that created it never sees it again.

---

## 4. Secrets on the host

### 4.1 Where they live

Three tiers, described authoritatively in
`backend/docs/ENV_VS_DB_CONFIG_REFERENCE.md:8-14`:

1. **Bootstrap / env-only** — `.env` on the host, read before the process starts. The
   canonical list is a three-element constant:
   `OPS_CONFIG_BOOTSTRAP_ENV_KEYS = ['DATABASE_URL', 'REDIS_URL', 'OPS_DB_ENCRYPTION_KEY']`
   (`backend/src/modules/ops/ops-config-contract.ts:11-15`), and an attempt to store one
   of them through the console is rejected with `BOOTSTRAP_KEY_NOT_DB_APPLICABLE`
   (`ENV_VS_DB_CONFIG_REFERENCE.md:11`).
2. **DB-overlay** — `OpsConfigSecret` rows, AES-256-GCM encrypted, applied into
   `process.env` at boot by `applyOpsConfigRuntimeOverlay()` before any provider
   initialises, editable live from the ops console after an OTP
   (`ENV_VS_DB_CONFIG_REFERENCE.md:12`).
3. **StoreSettings** — typed merchant-facing config in its own table
   (`ENV_VS_DB_CONFIG_REFERENCE.md:13`).

### 4.2 How they reach the process

`.env` is loaded by compose as `env_file: .env` on both `backend` and `workers`
(`backend/docker-compose.yml:10,31`), with a small set of `environment:` overrides that
**take precedence** — `NODE_ENV=production` is forced there rather than trusted from the
file (`:11-15`). That is a good instinct: the one variable that decides the security
posture is not readable from a file an operator edits.

### 4.3 What is committed and what is not

`backend/.dockerignore:3-4` excludes `.env` and `.env.*` while re-admitting
`.env.example`, so the file cannot reach an image layer despite the builder's
`COPY . .` (`backend/Dockerfile:10`). `vps-deploy.sh` reads `.env` with `grep` and never
sources it (`:79,276,308,341-343,544`), and never writes it — the header states the
contract at `:23`. All correct, all matching ours.

### 4.4 Against our doctrine

CLAUDE.md forbids secrets in "DB/env-committed files" and directs us to secrets-manager
references; `docs/DEPLOYMENT.md` §6 and D-95's ops console are the concrete shape.
Compared side by side:

| | raghava | Calevate |
|---|---|---|
| Env-only floor | 3 keys (`ops-config-contract.ts:11-15`) | 8 keys + 2–3 object-store credentials (`DEPLOYMENT.md` §6) |
| Wrapping key | `OPS_DB_ENCRYPTION_KEY` | `PLATFORM_KEK` |
| KDF | **`sha256(passphrase)`, unsalted, no KDF** (`src/common/security/ops-config-crypto.ts:21,34`) | base64 of 32 random bytes, used as the key |
| AAD | **none** | — |
| Key version | column `keyVersion` (`prisma/schema.prisma:347`) written from `OPS_DB_ENCRYPTION_KEY_VERSION` (`ops.service.ts:1218,1269`) | `PLATFORM_KEK_RETIRED` + D-97 re-wrap |
| Deploy-time refusal | presence + placeholder (`verify-client-bootstrap-env.mjs:48,74-82`) | presence, by name, at `scripts/vps-deploy.sh` preflight |

Three specific problems on their side:

- **The KDF is `crypto.createHash('sha256').update(key).digest()`**
  (`ops-config-crypto.ts:21`, and identically at `:34`). Nothing anywhere requires
  `OPS_DB_ENCRYPTION_KEY` to be 32 random bytes — `verify-client-bootstrap-env.mjs:48`
  only checks it is non-empty and not a placeholder. So if an operator types a
  passphrase, the data-encryption key is a single unsalted SHA-256 of a low-entropy
  string, which is exactly the class of mistake that makes an offline database dump
  brute-forceable. Our `PLATFORM_KEK` is specified as `base64(os.urandom(32))` and
  `apps/api/core/envelope.py` refuses a short key at read time. Keep ours.
- **No AAD.** AES-256-GCM is used without additional authenticated data
  (`ops-config-crypto.ts:23`), so a ciphertext is not bound to the config key it belongs
  to. Anyone with DB write access can move the ciphertext of one setting onto another
  row and it will decrypt cleanly. Binding the row's `key` (and `keyVersion`) as AAD is
  one argument and closes it.
- **`keyVersion` is recorded and never honoured.** `resolveOpsEncryptionKeyRaw()` reads
  exactly one env var (`ops-config-crypto.ts:5-13`), and no production path selects a key
  by version — the only mention of `OPS_DB_ENCRYPTION_KEY_V1`/`_V2` in the whole tree is
  a comment inside a test (`src/modules/ops/ops.security.test.ts:157-158`). So rotating
  the key makes every stored secret permanently undecryptable, and the version column
  merely labels which key *would* have worked. A rotation story that looks implemented and
  is not is worse than one that is plainly absent.

One thing of theirs to take: **`maskSecretValue`** (`ops-config-crypto.ts:41-45`) exists
at all, so the console can display a secret without revealing it. But its implementation
leaks the first two characters, the last two, and — via `'*'.repeat(value.length - 4)` —
**the exact length**. For a Razorpay key id that is nearly the whole discriminating
prefix. Mask to a fixed width.

---

## 5. Backups and DR — a working implementation of nothing

`docs/DEPLOYMENT.md` §7 says the `dr-*` family is "a working implementation of what our
`infra/backup/` only hypothesises". **That is wrong and this is the correction.** Our
`infra/backup/` is honest about being unapplied. Theirs is not unapplied; it is
*simulated*, and CI validates the simulation.

### 5.1 What actually runs: `dr-backup-offsite.sh`

128 lines, the only script in the family that touches real data.

- `pg_dump "$DATABASE_URL" --no-owner --no-privileges --clean --if-exists | gzip`
  (`:48`), under `set -euo pipefail` (`:2`) so a `pg_dump` failure does fail the
  pipeline.
- Size sanity check: fail if `< 100` bytes (`:51-54`), then `sha256sum` (`:55`).
- Redis: `BGSAVE`, `sleep 2`, then gzip whatever is at `CONFIG GET dir` /
  `dbfilename` (`:64-83`). Best-effort; skipped with a warning if `redis-cli` is absent.
- Copy: `rsync` if `BACKUP_DEST` contains a colon, else `cp` (`:88-99`).
- Evidence JSON to `./artifacts/dr-drills/backup-<ts>.json` (`:101-126`).

**What is wrong with it:**

| Problem | Evidence |
|---|---|
| **No schedule.** The only mention of one is a cron line in a comment (`:25-26`). Nothing installs it. | `:25-26` |
| **Default destination is the same host.** `BACKUP_DEST="${BACKUP_DEST:-./backups}"` (`:32`) — a relative path next to the thing being backed up. An "offsite" script whose default is onsite. | `:32` |
| **No encryption.** The dump goes to the destination in plaintext gzip. Every customer record, in the clear, on whatever `rsync` target is configured. Our `dump-offsite.sh` pipes through `age`. | `:48,90` |
| **The evidence JSON hardcodes `"pass": true`** (`:122`). It is written unconditionally at the end; there is no path that writes `false`. | `:122` |
| **No verification of the copy.** The sha256 is computed on the local file and recorded; nothing re-reads the destination. A truncated `rsync` is indistinguishable from a good one. | `:55,90-99` |
| **No restore verification of any kind.** `pg_restore --list` is never run, checksums are never validated against a restore. The 2026 baseline for this is three levels — existence/size, checksum integrity, partial restore ([oneuptime, "How to Test PostgreSQL Backup Restoration", Jan 2026](https://oneuptime.com/blog/post/2026-01-21-postgresql-backup-testing/view)); this reaches level 1. | — |
| **No retention or pruning.** Nothing deletes old dumps. The destination grows forever. | — |
| **Destination heuristic is a colon test** (`:88`). Any path containing `:` is treated as a remote rsync target. | `:88` |

### 5.2 The rest of the family: simulation with a hook that simulates

Four "stage" scripts share one shape — `dr-failover-run.js` (87), `dr-restore-run.js`
(87), `dr-reconcile-validate.js` (87), plus the orchestrator `dr-gameday-checklist.js`
(114). Each:

- If `DR_<STAGE>_HOOK` is set, run it and report `executionMode: 'hook'`.
- **Otherwise `setTimeout` for a few seconds and print `status: 'pass'`** with a
  `checks` array naming things it did not do.

`dr-restore-run.js:74-87` is the clearest example. With no hook it waits
`DR_RESTORE_SIM_DELAY_MS` (default 3500ms, `:8`), then emits:

```json
{"stage":"restore","executionMode":"simulation","status":"pass",
 "checks":["postgres-restore-verified","redis-warmup-complete","read-write-smoke"]}
```

`"postgres-restore-verified"` after a 3.5-second sleep. The status is computed as
`durationMs <= 30 * 60 * 1000 ? 'pass' : 'fail'` (`:79`) — it passes because it was
*fast*, which is the inverse of the property a restore drill measures.

### 5.3 The part that makes it worse: CI validates its own fabrication

There is a guard against exactly this, and it is a good one.
`dr-stale-drill-check.js` refuses evidence older than `DR_DRILL_STALE_DAYS` (90,
`:7,31-34`), refuses a file with no `stages` (`:38-42`), requires
`orchestration.environmentId` and `orchestration.snapshotId` to be non-empty strings
(`:43-49`), refuses any failed stage (`:58-62`), and — the important one — when
`DR_ORCHESTRATION_PROFILE` is `production-like`, **refuses any stage whose
`executionMode` is not `hook`** (`:50-57`).

So the gate demands hook execution. And then:

- `.github/workflows/reliability-ci.yml:199-200` runs
  `npm run dr:drill:checklist:hooked` immediately followed by
  `npm run dr:drill:stale-check`.
- `dr-gameday-hooked.js:6-14` sets `DR_ORCHESTRATION_PROFILE=production-like` and points
  every hook at `node scripts/dr-ephemeral-pack.js <stage>`.
- `dr-ephemeral-pack.js:35-45` **writes a JSON file saying the stage passed and exits
  0.** It has no side effects. `stageChecksByType` (`:27-33`) is a hardcoded dictionary
  of strings — `'snapshot-restored'`, `'schema-validated'`,
  `'smoke-read-write-pass'` — that it copies into the artifact.

CI therefore generates the evidence, in hook mode, moments before the checker reads it:
zero days old, every stage `executionMode: 'hook'`, every stage `pass`. **The gate can
never fail.** It is a closed loop that produces a green tick and a committed artifact
asserting that a Postgres snapshot was restored and its schema validated, when no
database was contacted.

Two smaller corroborating defects in the same family:

- The `rollback-validation` stage has **no script at all**
  (`dr-gameday-checklist.js:17`), so it keeps its initial `status = 'simulated-pass'`
  (`:32`) and passes the `allStagesPass` invariant, which tests with
  `String(stage.status).includes('pass')` (`:87`) — a substring match that
  `'simulated-pass'` satisfies. `dr-stale-drill-check.js:58` uses the same substring
  test, and explicitly exempts `rollback-validation` from the hook requirement (`:52`).
- **`dr-rto-rpo-report.js` can never pass**, so nobody wired it into CI. It groups
  drill files by `data.stage || data.type` (`:52`) and requires four keys —
  `backup-restore`, `failover`, `reconciliation`, `full-drill` (`:22-27`) — but the only
  files matching its `drill-*.json` filter (`:38`) are written by
  `dr-gameday-checklist.js:102-106`, whose top-level object has `mode` and `stages`
  and **neither `stage` nor `type`** (`:74-92`). Every drill lands under `'unknown'`;
  all four required stages report "no drill evidence found" (`:106-123`); `overallPass`
  is false; `process.exit(1)` (`:139`). It also reads `drill.timestamp` (`:73`), which
  the checklist never writes (it writes `generatedAt`), so `ageDays` is `Infinity` and
  `isStale` is always true.

### 5.4 What a restore drill consists of, in their world vs ours

Theirs: `npm run dr:drill:checklist` → four stages → a JSON file. Nothing restores.
`CLIENT_VPS_SETUP_GUIDE.md:747` is the whole operational instruction: *"daily `pg_dump`
(or managed backup) off the VPS; periodic restore test."* No procedure, no pass
condition, no evidence template.

Ours: `runbooks/backup-restore-drill.md` plus `scripts/restore_drill.py` (1582 lines),
which seeds a database, dumps it the way `dump-offsite.sh` does, encrypts it with the
same `age` invocation, round-trips it through object storage, restores it, and then
proves five things a zero exit code does not — alembic head, RLS still ENABLEd *and*
FORCEd with a real cross-tenant read returning zero rows under the unprivileged role,
append-only triggers actually raising on `UPDATE`/`DELETE`, the audit hash chain still
verifying, and the row counts matching
(`scripts/restore_drill.py:20-56`). It has a `--sabotage` mode to prove it goes red
(`:69`), and it refuses to call its verdict `PASS` — it says `GREEN (local scope)` and
prints its own coverage next to it (`:14-19`), because it cannot exercise wal-g, R2, the
offsite provider, the age identity or the systemd timers without credentials.

**We should stop citing their DR suite as the reference implementation.** On this axis
the direction of learning runs the other way, and the one thing worth taking is
`dr-stale-drill-check.js`'s idea — evidence has an expiry — with the loop broken. That is
what D-165 below records.

---

## 6. Reverse proxy, TLS, and process supervision

### 6.1 nginx

One template, `backend/nginx/client.conf.template` (427 lines), rendered by `envsubst`
with three placeholders — `CLIENT_DOMAIN`, `STOREFRONT_PORT`, `BACKEND_PORT` (`:10-12`)
— and installed per client at `/etc/nginx/sites-available/<domain>`. Zones live
separately in `backend/nginx/rate-zones.conf.template` (12 lines), included once from
`http {}` (`:1-3`), because `limit_req_zone` is an `http`-context directive — the same
correction our `infra/nginx/README.md` §1 records.

Structure worth taking:

- **Port 80 → 301** (`:29-33`).
- **Per-route-class `limit_req`** with a zone per class (`rate-zones.conf.template:5-12`:
  auth 20r/m, checkout 35r/m, admin 180r/m, catalog 240r/m, cart 90r/m, webhook 300r/m,
  health 60r/m, default 90r/m). Our six zones in `DEPLOYMENT.md` §5.4 are the same idea
  with our numbers, and `check_docs_drift` already pins the table to the template.
- **The maintenance gate**, and this is the hard-won part `DEPLOYMENT.md` §5 tells us not
  to re-derive. Each gated location does `auth_request /_maintenance_gate;` +
  `error_page 401 =503 /maintenance.html;` — **single hop**. The comment at `:59-72`
  records why the obvious two-hop version fails: nginx defaults to
  `recursive_error_pages off`, so a named location returning 503 does not re-enter the
  server-level `error_page 502 503`, and the wire result is nginx's compiled-in bare 503.
  And `:74-80` records the earlier failure: `if ($maintenance_active = "1")` runs in the
  REWRITE phase, before `auth_request` populates `auth_request_set` in the ACCESS phase,
  so it evaluated an empty variable and **never blocked anything** — a maintenance gate
  that silently passed all traffic.
- **`try_files $uri @maintenance_inline`** (`:116`) with the whole fallback page inlined
  in a single `return 503 '...'` (`:128`), so a missing static file cannot degrade to the
  bare nginx page.
- **Which locations are never gated, and why**: `/api/v1/ops/` because it is the only
  surface that can *exit* maintenance (`:348-352`); `= /api/v1/health` because probes need
  a true signal (`:363-366`); `payments/webhook` and `shipping/webhook` because providers
  must keep delivering callbacks during a window (`:331-336`). That third one is exactly
  the doctrine `DEPLOYMENT.md` §5.2 inherits for `hooks.calevate.tech`.
- **The multipart exemption** (`:227-261`): `auth_request` forces nginx to buffer the
  whole request body before the subrequest runs, which 500s on larger uploads. So upload
  locations skip the gate *and* set `proxy_request_buffering off`. The comment records
  that a store-logo upload and a CSV import both failed silently this way, and that the
  route list is now asserted by a test
  (`src/common/plugins/multipart-nginx-coverage.test.ts`). Route-list-in-config drift,
  closed with a test — a pattern worth stealing independent of nginx.

**What is wrong with the nginx config:**

- **No real-IP restoration.** No `set_real_ip_from`, no `real_ip_header`. Every
  `limit_req` zone keys on `$binary_remote_addr` (`rate-zones.conf.template:5-12`), so
  behind a proxy every request shares one key. `DEPLOYMENT.md` §5.3 already flags this as
  "fix their documented gap" and our `infra/nginx/` does fix it — confirmed still absent
  on their side.
- **`ssl_stapling on; ssl_stapling_verify on;`** (`:180-181`) is dead configuration.
  Let's Encrypt removed OCSP URLs from certificates on 7 May 2025 and shut its OCSP
  responders down on 6 August 2025
  ([Let's Encrypt, "Ending OCSP Support in 2025", 5 Dec 2024](https://letsencrypt.org/2024/12/05/ending-ocsp)),
  after which nginx ignores `ssl_stapling` and logs a warning about the missing responder
  URL. There is also no `ssl_trusted_certificate`, which `ssl_stapling_verify` needs.
  Both lines should be deleted. **Check ours in `infra/nginx/snippets/calevate-tls.conf`
  before the first `nginx -t`.**
- **No HTTP/2.** `listen 443 ssl;` (`:36`) with no `http2` parameter and no `http2 on;`
  directive. Since nginx 1.25.1 the listen parameter is deprecated in favour of a
  standalone `http2 on;`
  ([SpinupWP, deprecated HTTP/2 directive in nginx 1.25.1+](https://spinupwp.com/doc/deprecated-http2-directive-nginx/)),
  and neither form is present here — so every client is on HTTP/1.1.
- **`add_header` inheritance is broken for the maintenance responses.** The six security
  headers are set at server level (`:184-189`); nginx's `add_header` does not inherit into
  a block that declares its own, and both `location = /maintenance.html` (`:107-108`) and
  `@maintenance_inline` (`:126-127`) declare two. So the maintenance page ships with no
  HSTS, no `X-Frame-Options`, no `nosniff`.
- **`X-XSS-Protection: 1; mode=block`** (`:188`) is a retired header that browsers ignore
  and that historically introduced its own vulnerabilities. Harmless, but it is in the
  config because a checklist asked for it (`CLIENT_VPS_SETUP_GUIDE.md:537,702`), which is how
  security theatre accretes.
- **`/api/v1/health/ready` is maintenance-gated.** The health exemption is an *exact*
  match (`location = /api/v1/health`, `:363`), so the readiness path falls through to
  `location /api/` (`:377-392`), which has `auth_request`. During a window, readiness
  returns the maintenance page.

### 6.2 TLS and certificates

**Their docs contradict each other, and one of the two answers is dangerous.**

- `CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:18` — *"**Never** run `certbot --nginx` on
  these server blocks — it rewrites the templated maintenance-gate/rate-limit config. Use
  `certbot certonly` (webroot/standalone) instead."* Repeated at `:162`.
- `CLIENT_VPS_SETUP_GUIDE.md:509` — *"`certbot --nginx -d <this-domain> -d
  www.<this-domain>` per client"*, in a mandatory rules table.
- `CLIENT_ONBOARDING_EXECUTION_ORDER.md:548` and `MASTER_DEPLOYMENT_PLAYBOOK.md:925` —
  `certbot --nginx` again.

Three of four documents give the instruction the fourth calls a config-destroying
mistake, and the fourth is right: `vps-deploy.sh:452-490` re-installs the rendered
template on every deploy, so anything the certbot nginx plugin injected is silently
reverted at the next push. Our `DEPLOYMENT.md` §10 already carries the correct lesson
("`certbot --nginx` destroys templated config; `certonly` only") and §9.5a already works
out the certificate ordering that the obvious sequence deadlocks on. **Take the
Cloudflare guide's answer; ignore the other three.**

Renewal: `certbot.timer` handles it, and because `certonly` does not touch nginx the
guide correctly requires a reload hook —
`--deploy-hook "systemctl reload nginx"` or a script under
`/etc/letsencrypt/renewal-hooks/deploy/` (`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:211`).
**We do not have this anywhere.** Our §9.5a obtains certificates and never installs a
renewal hook, so on day 60 the certificate renews on disk and nginx keeps serving the old
one until something else reloads it.

Cloudflare posture (`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:11-17`): Full (strict)
only; a valid publicly-trusted certificate on the **`default_server`** block, because
Cloudflare's strict validation reaches the origin without matching SNI and a certless
default block is the 525; remove the stock `sites-enabled/default`; one proxied A record
per name, no stray AAAA; origin locked to Cloudflare ranges. All four are already in our
§5/§9.6 and our `infra/nginx/000-default.conf.template`.

### 6.3 Process supervision

Split by tier, and the split is the design:

- **Containers**: `restart: unless-stopped` on all four services
  (`backend/docker-compose.yml:5,27,52,72`). That is the supervisor — there is no systemd
  unit for the stack. `cleanup-stale-compose-state.sh:39-42` leans on it explicitly: the
  script restarts the Docker daemon and expects containers to come back on their own.
- **Frontend**: pm2, process named `<CLIENT_ID>-frontend`
  (`vps-frontend-deploy.sh:195`), reloaded with `pm2 reload --update-env` (`:199`), cold
  started with `pm2 start npm --name ... -- start -- -p <port>` when pm2 has never heard
  of it (`:208-209`), then `pm2 save`. `pm2 startup` once per VPS for reboot survival
  (`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:31,152`). Our `deploy_web` has the same
  reload-or-start branch for the same reason.
- **Postgres**: on the host, under its own packaging.
- **No `healthcheck:` on `backend` or `workers`** in either compose file. Only
  `postgres` and `redis` have one (`docker-compose.yml:57-62,80-85`). So Docker has no
  opinion about whether the app is alive; the only health signal is the deploy script's
  own poll, which runs once and then never again. There is no restart-on-unhealthy.
- **No `stop_grace_period` anywhere**, so in-flight BullMQ jobs get 10 seconds.

Health endpoints: `/api/v1/health` (liveness, `vps-deploy.sh:546`),
`/api/v1/health/ready` (readiness with `runtimeConfigMissingKeys`, `:547`), and
`/api/v1/health/live` used by CI (`reliability-ci.yml:212`). The
liveness/readiness split with a *named list of what is still unconfigured* is the same
design as our `/healthz` + `/healthz/ready`, and the non-blocking treatment at deploy
time (`vps-deploy.sh:565-579`) is the right call for a console-configured platform.

### 6.4 Host hygiene

`vps-cleanup-template.sh` (126 lines), installed to
`/etc/cron.daily/vps-cleanup-<CLIENT_ID>` by `install-vps-cleanup.sh:19-43`, running
daily at ~06:25. It does `docker system prune -f` + `docker builder prune --keep-storage
5GB` (`:40-46`), pm2 log flush and `reloadLogs` for one process (`:53-62`), clears
`.next/cache` (`:69-74`), deletes `/var/log/*.gz` and `*.old` older than 7 days
(`:78-79`), `npm cache clean --force` (`:84`), `journalctl --vacuum-size=200M` (`:92`),
and wipes runner `_work/` and `_tool/` (`:97-115`). Then reports disk usage and warns
above 80% (`:118-124`).

Our `DEPLOYMENT.md` §7 already lists this as "still unbuilt". It is worth building — with
three corrections in §8.

---

## 7. Observability on the host

**A fresh host gets nothing.** That is the honest summary, and it is not far from ours.

- `backend/observability/` contains six files, all of them configuration for systems that
  live elsewhere: `slo-rules.yml` (Prometheus recording rules + burn-rate alerts),
  `slo-rules.test.yml`, `alert-routing.yml` (Alertmanager-shaped routes and receivers),
  `dashboards/sre-reliability.json`, plus two coverage-baseline JSONs that are not
  observability at all.
- The SLO rules are genuinely good and are the pattern `DEPLOYMENT.md` §8 already says to
  adopt: named recording rules (`slo:checkout_success:ratio_5m`,
  `slo:webhook_latency:p95_5m`, `slo:outbox_lag_seconds:p95_5m`,
  `slo:queue_oldest_waiting:max_5m`, …) feeding **multi-window burn-rate alerts**
  (`CheckoutErrorBudgetFastBurn` at `14.4 × 0.001` for 5m, plus a slow-burn twin) — the
  Google SRE shape, not a threshold guess. They are validated in CI by `promtool`, which
  the workflow downloads and pins (`reliability-ci.yml:150-153`).
- `alert-routing.yml` routes by `severity=page|ticket` with per-class group/repeat
  intervals and `runbook_base` metadata on each receiver. Also good, also **not deployed
  to anything** — the receivers have no webhook URLs, only `metadata`.
- **Nothing installs Prometheus, Alertmanager or Grafana on the VPS.** There is no
  scrape config, no systemd unit, no compose service. `/ops/metrics` is gated behind
  `OPS_METRICS_TOKEN`, whose absence is a *warning* in the bootstrap preflight
  (`verify-client-bootstrap-env.mjs:178-180`).

`otel-readiness-check.js` (150 lines) is the one host-facing piece, and it is well built:

- Reads `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`,
  `OTEL_SERVICE_NAME`, `OTEL_TRACING_ENABLED` (`:24-29`).
- **If tracing is disabled it exits 0 with `status: 'skip'`** (`:42-50`) — a deliberate
  choice that keeps the check runnable on every host without forcing tracing on.
- If enabled: refuses on missing `OTEL_SERVICE_NAME` (`:54-62`) with the reason ("traces
  will not be identifiable"), refuses on missing endpoint (`:66-74`), then **actually
  probes** it with a `HEAD` and a 5s timeout (`:98-126`).
- Writes evidence to `artifacts/otel/readiness-check.json` and exits on the verdict
  (`:128-148`).

That "enabled-but-unreachable is a failure; disabled is a skip" ladder is exactly the
shape our `DEPLOYMENT.md` §8 needs for Sentry, where the current failure mode is the
opposite: the DSN is accepted by the ops console and error reporting silently stays off
unless `uv sync --all-packages --group errors` has been run on that host.

The OTEL collector itself is a `docker-compose.otel.yml` overlay with Jaeger for local
dev and a documented "point it at a hosted collector in production"
(`docker-compose.otel.yml:1-27`). Note the overlay publishes `16686`, `4317` and `4318`
on all interfaces (`:31-34`) — see §8.

---

## 8. What is wrong or risky in their setup

Ordered by what would fail a competent review hardest. Items already covered above are
cross-referenced rather than repeated.

### 8.1 The backend API is published on `0.0.0.0` and the firewall does not stop it

`backend/docker-compose.yml:6-7`:

```yaml
    ports:
      - "${BACKEND_PORT:-3000}:3000"
```

That binds `0.0.0.0:3001` on the host. Docker writes published-port rules into `nat` and
`FORWARD`, upstream of the `INPUT` chain ufw filters — so the documented hardening
"`ufw` allows only `22`, `80`, `443` inbound"
(`CLIENT_VPS_SETUP_GUIDE.md:45`) does not contain it. **The Fastify API is reachable
directly at `http://<vps-ip>:3001`, bypassing nginx entirely**: no TLS, no `limit_req`
zone, no maintenance gate, no Cloudflare, and no origin IP allowlist. The prod overlay
resets the port mapping for `redis` (`docker-compose.prod.yml:23-24`) and **not** for
`backend`, so the exposure is production-only-by-omission. `docker-compose.otel.yml:31-34`
does the same for Jaeger's UI and both OTLP receivers.

Our `DEPLOYMENT.md` §2 already documents this exact hazard and our `compose.prod.yml`
binds to `127.0.0.1:` explicitly rather than relying on the firewall. This is the single
strongest confirmation that our version of that rule was worth writing down.

### 8.2 The DR gate validates evidence it just fabricated

§5.3. `dr-ephemeral-pack.js` writes pass records with no side effects;
`dr-gameday-hooked.js` wires it in as the "production-like" hook; CI runs the generator
and the validator back to back. A restore has never been proven. Their
`CLIENT_VPS_SETUP_GUIDE.md:747` asks for a "periodic restore test" and nothing in the
repository performs one.

### 8.3 The documented sudoers grants are a root escalation

`CLIENT_VPS_SETUP_GUIDE.md:1238-1268` tells the operator to add, via `visudo`:

```
<runner-user> ALL=(root) NOPASSWD: /usr/bin/rm -rf /var/lib/docker/containers/*
<runner-user> ALL=(root) NOPASSWD: /usr/bin/cp /tmp/*.nginx.conf /etc/nginx/sites-available/*.conf
<runner-user> ALL=(root) NOPASSWD: /usr/bin/cp /tmp/tmp.* /etc/nginx/sites-available/*.conf
<runner-user> ALL=(root) NOPASSWD: /usr/bin/systemctl restart docker
```

sudoers matches command-line arguments as a **single concatenated string**, and a
wildcard there matches `/` and can span multiple words — the canonical illustration in
the sudo documentation is that a rule permitting `cat /var/log/*` also permits
`cat /var/log/messages /etc/shadow`
([Compass Security, "Dangerous Sudoers Entries — Wildcards"](https://blog.compass-security.com/2012/10/dangerous-sudoers-entries-part-4-wildcards/);
[David Hamann, "Beware of wildcard paths in sudo commands", Feb 2023](https://davidhamann.de/2023/02/24/beware-of-wildcard-paths-sudo/)).
So the first line permits
`sudo rm -rf /var/lib/docker/containers/x /etc /home` — **unrestricted root deletion of
any path on the box**, granted to the account that runs code from every merged pull
request. `HARDENING_HISTORY.md:432` records the third line being *widened* to
`/tmp/tmp.*` specifically to accommodate `mktemp`, with the note that it is "still scoped
to a specific dest… so the grant doesn't give the runner general nginx config write
access" — which the traversal defeats. And `/tmp` is world-writable, so any local user
can stage the source file.

The correct shape is the one the security literature has recommended for a decade: a
single root-owned script with no arguments, granted by exact path, doing its own
validation. Whatever we grant the runner on Hostinger, it must be that.

### 8.4 The frontend's rollback does not exist

`vps-frontend-deploy.sh` has three rollback branches that restore `.next` from
`.next.old` (`:136-140`, `:148-151`, `:158-162`) and one that deletes it on success
(`:166`). **Nothing in the repository ever creates `.next.old`** — grep across every
`.sh`, `.js`, `.mjs`, `.yml` and `.md` returns only these four lines and a doc claim.
That doc claim is `frontend/docs/FRONTEND_DEV_LOG.md:57`: *"Uses **atomic swap**: moves
old `.next` → `.next.old` before building, easy rollback if new build fails."* It does
not. A failed `npm run build` leaves a partial `.next` in place with no restore, and the
`.next/BUILD_ID` corruption path (`:155-163`) actively **deletes** the only build on disk
(`:157`) before failing to restore it.

This is the most instructive defect in the repository: a rollback that is documented, has
code, prints a reassuring `::warning::Rolled back…`, and is unreachable.

### 8.5 Two git-sync policies, one of them destructive

Backend: `git pull origin main --ff-only` (`vps-deploy.sh:89`), then abort on SHA
mismatch. Frontend: `git reset --hard "origin/main"` (`vps-frontend-deploy.sh:85`) on the
**same monorepo checkout**. Whichever job runs second discards anything the first left in
the tree, and `--hard` silently destroys an operator's emergency edit — including one
made minutes earlier during an incident. Pick one; it should be `--ff-only`.

### 8.6 The daily cleanup races the deploy, and prunes globally

`vps-cleanup-template.sh:97-115` does `rm -rf "${RUNNER_DIR}/_work/"*` and `_tool/*` from
`/etc/cron.daily`, which is unsynchronised with GitHub Actions. A deploy in flight at
06:25 has its job staging area deleted underneath it. Separately, `docker system prune
-f` (`:40`) is host-global on a host the guide explicitly designs for multiple clients
(`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:22-27`) — the script's own header admits it
(`:8-11`) and installs it anyway. And `install-vps-cleanup.sh:52` **runs the whole thing
immediately as root** as an installation "test".

### 8.7 The maintenance page is best-effort by construction

`vps-deploy.sh:372` uses `sudo -n cp`, so without the grant it warns and continues
(`:377-384`). `HARDENING_HISTORY.md:290` records the outcome: *"The warning was buried
somewhere in a long deploy log and went unnoticed. On a fresh VPS where
`/etc/nginx/maintenance/` had never existed, the file was just missing forever after."*
The fix was to re-emit the warning as a banner in the summary (`:622-636`) — the right
response to "a warning was missed", but the underlying step is still a silent-degrade
path whose failure mode is discovered during an outage.

### 8.8 Preflight is skippable, and one gate is skippable by an env var

- `verify-vps-deploy-preflight.mjs` is not called by the deploy at all (§2.1), so the
  "preflight" is whatever `npm run verify:vps-preflight` was last run against.
- `reliability-release-guard.js:35` reads `RELEASE_TYPE`, and
  `:43` short-circuits the entire freeze/critical-incident/blocked check when it equals
  `hotfix`. A repository or workflow variable therefore disables the release guard, with
  no ticket required — `:48-51`'s approval path at least demands
  `RELEASE_EXCEPTION_TICKET` (`:24-29`), but the hotfix path demands nothing.

### 8.9 Container and image hygiene

- `backend/Dockerfile:1,21` pins `node:22-alpine` **by tag**. A tag is mutable; the same
  correction is item 1 of our own `DEPLOYMENT.md` §4d.
- `RUN npm ci` (`:8`) without `--ignore-scripts` in the builder, which is the lifecycle
  hook hard rule 9 exists for.
- No `HEALTHCHECK` in the image and no `healthcheck:` on the app services (§6.3).
- Good: multi-stage with `npm prune --omit=dev` (`:19`), npm and npx **removed** from the
  runtime image (`:25`), and a non-root `USER app` (`:39-41`).

### 8.10 Redis

`--protected-mode no` with a conditional `--requirepass`
(`docker-compose.yml:74-79`): if `REDIS_PASSWORD` is empty the shell substitution
produces no `--requirepass` and protected mode is off — an unauthenticated Redis. The
prod overlay removes the host port mapping (`docker-compose.prod.yml:23-24`), which is
what keeps this from being reachable, so the only thing between an empty variable and an
open Redis is one line in an overlay file that must be passed on the command line. The
bootstrap preflight does require `REDIS_PASSWORD` non-empty
(`verify-client-bootstrap-env.mjs:44,66-68`) — but that preflight runs in the deploy
script, not at container start.

### 8.11 Smaller things, recorded so they are not rediscovered

- `dr-backup-offsite.sh` writes plaintext dumps (§5.1) and hardcodes `"pass": true`
  (`:122`).
- `maskSecretValue` leaks length and four characters (`ops-config-crypto.ts:41-45`).
- `keyVersion` is written and never read (§4.4).
- `ops-newuser.mjs:178` / `admin-newuser.mjs:224` print the invite token (§3.1).
- `seed-admin.mjs:70` prints a live password (§3.2).
- `verify-r2-media-config.mjs` fails on a condition `verify-client-bootstrap-env.mjs`
  merely warns about (§2.2) — two answers to one question.
- `vps-deploy.sh:276` string-rewrites a DSN with `sed`.
- `COMPOSE_PROJECT` falls back to the literal `client-backend`
  (`vps-deploy.sh:79-80`) — on a shared host, two misconfigured clients collide into one
  compose project, and the §1.75 sweep then removes the other client's containers.
- `install-vps-cleanup.sh:20` installs to `/etc/cron.daily/vps-cleanup-<CLIENT_ID>`;
  `run-parts` silently skips filenames containing a dot, so a client id with a dot
  installs a cleanup job that never runs and never says so.

---

## 9. The plan for Calevate

Reading key: **Ours** = an engineering task with no timeline, done in this session or the
next thing done (CLAUDE.md tempo). **External** = blocked on something outside this
repository, named by name. Nothing below is scheduled; the two columns are the only
scheduling distinction that exists.

| # | Capability | How they do it | What WE build | In our tree today | Depends on |
|---|---|---|---|---|---|
| 1 | CD trigger + gating | `workflow_run` on CI success + `VPS_DEPLOY_ENABLED` + conclusion re-check + concurrency group, self-hosted runner on the VPS (`.github/workflows/deploy.yml:12-42`) | Nothing. Ours is the same design with one extra gate (`head_branch == main`) and no third-party action. | **Yes** — `.github/workflows/deploy.yml`, `DEPLOYMENT.md` §3 | **External: a Hostinger VPS + a registered self-hosted runner.** Ours |
| 2 | Deploy sequence (preflight → build → migrate → swap → health) | `vps-deploy.sh` | Nothing structural. Ours already adds: per-component plan from a path map, `--dry-run`, per-commit image tags, bootstrap validation *inside the new image*, rollback-aware migration skip. | **Yes** — `scripts/vps-deploy.sh` (1105 lines) | — |
| 3 | **Pre-build disk reclaim, two-tier** | Always-prune, hard-purge under 8GB, abort under 3GB, before building (`vps-deploy.sh:221-251`) | Add the escalation ladder to our `preflight`: prune → purge → refuse. Today we only refuse at 3GB and print the commands, which is the deadlock their comment describes. | **Partial** — refusal only, `scripts/vps-deploy.sh:243-249` | Ours |
| 4 | **Cross-field `.env` consistency** | `DATABASE_URL` vs `POSTGRES_DB`; `REDIS_URL` embeds `REDIS_PASSWORD` (`verify-client-bootstrap-env.mjs:62-72`) | Extend `scripts/check_bootstrap_keys.py` (or the deploy preflight) to assert: both DSNs name the same host+database with *different* roles; `REDIS_URL` names `redis` by service name, never `localhost`; `PLATFORM_KEK != PLATFORM_KEK_RETIRED`. | **No** | Ours |
| 5 | **Placeholder-value refusal** | `/replace_with\|change_me/i` on every required secret (`verify-client-bootstrap-env.mjs:79-82`) | Same check against our `.env.example` placeholder vocabulary, in preflight. Presence is not enough. | **No** | Ours |
| 6 | **Distinct-secrets refusal** | `JWT_REFRESH_SECRET !== JWT_SECRET` (`:84-86`) | Once first-party auth lands: refuse equal access/refresh signing keys at preflight *and* at `Settings()` construction. | **No** (no such keys yet) | Ours — **coordinate with the auth agent**, this is their key names |
| 7 | **First-admin bootstrap without Clerk** | `ops-newuser.mjs` → 256-bit token, sha256-at-rest, TTL, emailed link → `/ops/setup` → OTP → CAS-consume inside a transaction → audit append (§3.1) | Rewrite `scripts/bootstrap_admin.py` as an **invite minter**: insert an `admin_user_invites` row (tenant-less, RLS-exempt like `admin_users`), 256-bit token, store `sha256` only, **24h TTL**, send via the existing `apps/workers/transport.py`, print the invite **id and expiry only**. Consume path: a route in the admin realm that CAS-updates `CREATED→CONSUMED` in the same transaction that inserts `admin_users`, with an `audit_log` append. Migration ships with the table. | **No** — current script is `--clerk-user-id` (`scripts/bootstrap_admin.py:39-44`) | Ours — **the auth agent owns the session half; this is the bootstrap half. Agree the table name before writing the migration.** |
| 8 | Do NOT: password-printing seeder | `seed-admin.mjs:70` | Nothing. Explicit non-goal, recorded in §3.2 so nobody adds a "convenience" seeder later. | n/a | — |
| 9 | Secrets tiering (env floor + encrypted console store) | 3 bootstrap keys + AES-256-GCM `OpsConfigSecret` overlay (`ops-config-contract.ts:11-15`) | Nothing. Ours is the same shape, stronger key handling (D-95, D-97, `PLATFORM_KEK`). **Do carry over:** bind the config key name as **AAD** on our envelope encryption if it is not already, and make the wrapping-key version a *read* input rather than only a written column. | **Yes** — `apps/api/core/envelope.py`, `DEPLOYMENT.md` §6 | Ours |
| 10 | Console-managed integrations after first boot | Ops UI; `/health/ready` reports `runtimeConfigMissingKeys`; deploy warns but never blocks (`vps-deploy.sh:565-579`) | Nothing. Ours is `admin.calevate.tech/ops` + `/healthz/ready` + `DEPLOYMENT.md` §9 step 10a. | **Yes** | — |
| 11 | **Backups: a schedule that exists** | A cron line in a comment (`dr-backup-offsite.sh:25-26`) | Nothing new — `infra/backup/systemd/*.timer` already exists and is the better answer (`OnFailure=`, `Persistent=true`). | **Yes, unapplied** | **External: an object-storage account** (R2 backup bucket + scoped token) **and a non-Cloudflare offsite target** (Backblaze B2 / Hetzner Storage Box) |
| 12 | **Backups: encryption at rest** | None — plaintext gzip (`dr-backup-offsite.sh:48`) | Nothing new — ours pipes through `age`. Recorded here only because their script is the one `DEPLOYMENT.md` §7 says we adapted, and this is the half we must not adapt. | **Yes** — `scripts/backup/dump-offsite.sh` | **External: an `age` identity generated off-host** |
| 13 | **Restore drill that proves a restore** | Simulated (§5.2–5.3) | Nothing new — `scripts/restore_drill.py` already proves alembic head, RLS behaviour under the app role, append-only triggers, the audit chain and row counts. **Stop citing theirs as the reference.** | **Yes** | **External: credentials, for the half the local drill cannot cover (wal-g/R2/offsite)** |
| 14 | **Drill-evidence freshness gate** | `dr-stale-drill-check.js` — good idea, closed loop (§5.3) | A guardrail that reads `docs/evidence/restore-drill-YYYY-QN.md`, refuses when the newest record is older than one quarter, and **refuses to run any producer of that evidence** — CI validates, never generates. This is D-165. | **No** | Ours |
| 15 | **Certificate renewal hook** | `--deploy-hook "systemctl reload nginx"` / `/etc/letsencrypt/renewal-hooks/deploy/` (`CLOUDFLARE_SHARED_VPS_DEPLOYMENT_GUIDE.md:211`) | Add the deploy hook to `DEPLOYMENT.md` §9.5a as a numbered step with a pass condition (`certbot renew --dry-run` succeeds *and* the hook fires). Without it, day-60 renewal is invisible to the running nginx. | **No** | Ours (doc + `infra/nginx`), then **External: a domain and issued certificates** |
| 16 | nginx: maintenance gate | Single-hop `error_page 401 =503`, `auth_request` in the ACCESS phase, inline fallback (`client.conf.template:44-140`) | Build it, from their shape, when we need a maintenance window. `DEPLOYMENT.md` §5 already names it as a deliberate gap and warns that a half-remembered version fails exactly when needed. Their comments at `:59-80` are the specification. | **No** (deliberate gap) | Ours |
| 17 | nginx: real-IP restoration | **Absent** (§6.1) | Nothing — ours already has `set_real_ip_from` + `real_ip_header CF-Connecting-IP`, paired with the origin allowlist in one dated file. | **Yes** — `infra/nginx/` | — |
| 18 | **nginx: delete dead TLS config** | `ssl_stapling on` (`client.conf.template:180-181`) — Let's Encrypt OCSP responders off since 6 Aug 2025 | Check `infra/nginx/snippets/calevate-tls.conf` for `ssl_stapling` and remove it if present; add `http2 on;` (the 1.25.1+ form). Both before the first `nginx -t`. | **Unverified** | Ours |
| 19 | **Route-list-in-config drift test** | A test asserts every multipart admin route is in the nginx exemption list (`client.conf.template:243-248`) | Same idea for our `hooks.calevate.tech` never-gated locations and our upload paths: a test that fails when a route is added to the app and not to the edge policy. | **No** | Ours |
| 20 | Container ports bound to loopback | Published on `0.0.0.0` (§8.1) | Nothing — ours already binds `127.0.0.1:` explicitly and publishes redis nowhere. Confirmed correct by their counter-example. | **Yes** — `compose.prod.yml` | — |
| 21 | **Daily host hygiene** | `vps-cleanup-template.sh` + `install-vps-cleanup.sh` | Build it as a **systemd timer**, not `cron.daily` (same argument as `DEPLOYMENT.md` §7): docker prune, builder-cache cap, pm2 log flush, journal vacuum. **Three corrections:** (a) never touch the runner's `_work`; (b) take a lock the deploy also takes, so hygiene and deploy cannot interleave; (c) scope prunes to our compose project. | **No** — named as unbuilt in `DEPLOYMENT.md` §7 | Ours |
| 22 | **Runner privilege model** | Wildcard `NOPASSWD` on `rm -rf` and `cp` (§8.3) | One root-owned, argument-free script per privileged action (install nginx config; install maintenance page), granted by exact path in `/etc/sudoers.d/`. **Never a wildcard in an argument position.** Our deploy already refuses to proceed when `sudo -n` is unavailable rather than hanging, which is the other half. | **Partial** — `NGINX_AUTO_RELOAD` path exists; no sudoers policy written | Ours (the scripts), **External: root on the Hostinger VPS to install them** |
| 23 | Dead-container tombstone handling | Sweep + `rm -rf` under the daemon's state dir, abort if not cleared (`vps-deploy.sh:135-205`) | Nothing. Ours detects and **refuses with the exact command** rather than running an unattended `rm -rf` under `/var/lib/docker` — a deliberate divergence, and §8.3 is why it was right. | **Yes** — `scripts/vps-deploy.sh:548` | — |
| 24 | Health-window sizing | 90×2s, with the reason recorded (`vps-deploy.sh:30-37`) | Nothing — ours is 90×2s for the same reason. | **Yes** | — |
| 25 | Readiness reported, not enforced, at deploy | `/health/ready` warns; `runtimeConfigMissingKeys` named (`vps-deploy.sh:565-579`) | Nothing — ours reports both object-store credentials by name at `/healthz/ready`. | **Yes** | — |
| 26 | **Observability readiness ladder** | `otel-readiness-check.js`: disabled → skip; enabled-but-misconfigured → fail with the reason (`:42-95`) | Apply the ladder to Sentry: a host with `sentry_dsn` set and the `errors` dependency group **not** installed must fail a readiness check by name, not log one warning. `DEPLOYMENT.md` §8 already documents that exact silent failure. | **No** | Ours |
| 27 | SLO recording rules + burn-rate alerts, promtool in CI | `observability/slo-rules.yml`, `reliability-ci.yml:150-153,196` | Adopt the *structure* (recording rule → multi-window burn-rate alert → routed by `severity`) when we ship metrics endpoints. `DEPLOYMENT.md` §8 already says this. Until then, health endpoints + OPERATIONS §4 alerts. | **No** (deliberate) | Ours, once metrics exist |
| 28 | Alert delivery off the box | `alert-routing.yml` receivers carry metadata and no URLs | Nothing — ours goes through `EMAIL_PROVIDER` + `ALERTS_EMAIL` with `alert_delivery_has_no_transport` logged at boot. | **Yes** | **External: Resend domain verification for `calevate.tech`** (DKIM `TXT`, SPF/`MX`, DMARC), and **a Resend API key scoped to Sending** |
| 29 | Do NOT: `git reset --hard` on a shared checkout | `vps-frontend-deploy.sh:85` | Nothing. Ours is `git pull --ff-only` everywhere. Recorded as a non-goal. | **Yes** | — |
| 30 | Do NOT: rollback branches with no backup step | `.next.old` (§8.4) | Nothing. If we ever add a web-build rollback it takes the backup in the same function that restores it, with a test that fails when the backup step is removed. | n/a | — |

### 9.1 External blockers, by name

Everything in this list is outside the repository and none of it is ours to code around:

1. **A Hostinger VPS account and a provisioned India-region instance** — nothing in
   §9 rows 1, 11, 15, 22 becomes real without it. Also settles the sizing question:
   `DEPLOYMENT.md` §7a puts the practical floor at 8GB once self-serve opens, and §2a's
   worker arithmetic needs ≥4 vCPU for the production voice-runtime worker count.
2. **The `calevate.tech` domain's DNS, at Cloudflare** — A records per subdomain, proxied;
   no stray AAAA. Blocks TLS issuance and therefore rows 15 and 18.
3. **A Cloudflare Origin CA certificate** for `*.calevate.tech` — `DEPLOYMENT.md` §9.5a
   step 1; the certificate that breaks the ACME deadlock.
4. **Let's Encrypt issuance for the four hostnames** — blocked on 2, and the renewal hook
   in row 15 cannot be tested until it exists.
5. **Cloudflare R2: a dedicated *backup* bucket and a token scoped to it alone**, separate
   from the recordings bucket and its credential (`DEPLOYMENT.md` §7).
6. **A non-Cloudflare offsite target** — Backblaze B2, S3, or a Hetzner Storage Box —
   with its own credential. `dump-offsite.sh` will not work without one, and the whole
   vendor-concentration argument depends on it.
7. **An `age` identity generated off-host**, with the private half in offline custody
   alongside `PLATFORM_KEK`.
8. **A Resend account with `calevate.tech` verified** (DKIM `TXT`, SPF/`MX` on the sending
   subdomain, DMARC) and an API key scoped to **Sending** only. Row 7's invite email does
   not leave the box without it, which means **the first-admin bootstrap is blocked on a
   DNS record**.
9. **Root on the VPS**, to install the sudoers policy and the root-owned scripts in row 22.
10. **A GitHub self-hosted runner registration token** for the repository, to install the
    runner in row 1.

Note the coupling in 8: with Clerk removed, the invite-email path is the *only* way the
first administrator comes into existence, so Resend domain verification moves from
"needed before the first hot lead" (`DEPLOYMENT.md` §6) to **needed before anyone can log
in at all**. That is a change in the go-live ordering and it is worth saying out loud
before somebody discovers it on the box.

### 9.2 Explicit non-goals from this teardown

Recorded so a future reader does not re-propose them:

- **Their `dr-*` family**, in whole or in part, except the freshness *idea* in D-165.
- **`seed-admin.mjs`'s shape** — no non-interactive full-privilege account creation, no
  credential ever printed.
- **Wildcard sudoers grants**, in any argument position, for any reason.
- **`verify-vps-deploy-preflight.mjs`'s mechanism** — no guardrail that asserts a string
  exists somewhere in a file. `scripts/check_docs_drift.py` already records this
  rejection and this teardown is the evidence for it.
- **A blue/green rollout plugin** installed on the production host — still rejected under
  hard rule 9 (`DEPLOYMENT.md` §4b). If we want zero-downtime it is a decision-log entry
  and an nginx upstream we own, not a third-party CLI on the box.

---

## 10. Corrections this forces on our own docs, and on how we talk about that repo

Flagged, not silently changed, per CLAUDE.md: `docs/` is authoritative and this file is
evidence. The edits belong in the change that acts on §9.

1. **`docs/DEPLOYMENT.md:638-642`** describes chain B as "raghava's
   `dr-backup-offsite.sh` pattern with the schedule actually installed
   (`infra/backup/systemd/*.timer`), which is the gap their script documents and does not
   close." The schedule *is* a gap — but it is not the only one, and naming one gap
   implies the rest of the pattern is sound. It is not. Their version writes **plaintext**
   dumps (`dr-backup-offsite.sh:48`) whose default destination is the same host
   (`:32`), never re-verifies the copy at the destination, never prunes, and stamps
   `"pass": true` into its evidence JSON unconditionally (`:122`). The inheritance should
   be narrowed to: *the shape — dump, checksum, evidence JSON — with encryption, an
   offsite default, a real verdict and an installed schedule all added by us.* Four
   additions, not one.

2. **The `dr-*` family must stop being cited as a reference implementation**, in this
   repository and in conversation. The working assumption behind `DEPLOYMENT.md` §7 —
   that they have a running DR mechanism where we have only a hypothesis — is the reverse
   of what §5 above found. Theirs is a simulation whose CI gate validates evidence
   generated seconds earlier in the same job; ours is an unapplied mechanism that says so,
   plus `scripts/restore_drill.py`, which performs a real restore and checks five
   invariants a zero exit code does not answer. On backups and DR the direction of
   learning runs from us to them, and the one idea worth taking back is evidence expiry —
   D-165.

3. **`docs/DEPLOYMENT.md` §9 step 10a's ordering assumption changes with Clerk's
   removal.** It sends the operator to `admin.calevate.tech/ops` after the first deploy
   and treats email configuration as something set *on* that screen. With first-party auth
   the first administrator arrives by emailed invite (§3.1, §9 row 7), so the email
   transport and a verified sender domain are now prerequisites for reaching the screen
   rather than settings configured at it. §9.1 item 8 states the consequence: **Resend
   domain verification blocks first login.**

---

**Sources cited above (accessed 2026-08-17):**
[Let's Encrypt — Ending OCSP Support in 2025 (5 Dec 2024)](https://letsencrypt.org/2024/12/05/ending-ocsp) ·
[SpinupWP — Deprecated HTTP/2 Directive in Nginx 1.25.1+](https://spinupwp.com/doc/deprecated-http2-directive-nginx/) ·
[MassiveGRID — Blue-Green and Rolling Deployments on Ubuntu VPS](https://massivegrid.com/blog/zero-downtime-deployment-ubuntu-vps/) ·
[Bhesh Raj Neupane — Zero-Downtime Blue-Green with Docker, Nginx and GitHub Actions (Jul 2026)](https://bheshrajneupane.medium.com/guide-to-set-up-zero-downtime-blue-green-deployment-with-docker-nginx-and-github-actions-e0510e3192c6) ·
[oneuptime — How to Test PostgreSQL Backup Restoration (21 Jan 2026)](https://oneuptime.com/blog/post/2026-01-21-postgresql-backup-testing/view) ·
[pgDash — Automated Testing of PostgreSQL Backups](https://pgdash.io/blog/testing-postgres-backups.html) ·
[Compass Security — Dangerous Sudoers Entries, Part 4: Wildcards](https://blog.compass-security.com/2012/10/dangerous-sudoers-entries-part-4-wildcards/) ·
[David Hamann — Beware of wildcard paths in sudo commands (24 Feb 2023)](https://davidhamann.de/2023/02/24/beware-of-wildcard-paths-sudo/)
