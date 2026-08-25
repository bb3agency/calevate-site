# Why the R2 credentials are in `.env` and not in the ops console

**Question (founder, 25 Aug 2026):** the console manages `bolna_api_key`,
`azure_openai_api_key`, `razorpay_key_secret` and the rest under `PLATFORM_KEK`, and it
manages `object_store_endpoint` / `object_store_bucket` — so why are `AWS_ACCESS_KEY_ID`
and `AWS_SECRET_ACCESS_KEY` still hand-edited into `.env` on the VPS?

## Verdict

**(a) It is correct as-is — for BOTH tokens, but on two different loads, and only one of
them is a real bootstrap argument. The two answers must not be merged.**

* **The BACKUP token cannot move, ever.** It is read by `wal-g` on the database host at
  the moment the database is gone. A credential the console holds is a credential you
  cannot read during a restore. This is the same class of argument as `PLATFORM_KEK`
  (`apps/api/core/settings.py:212-215`) and it is absolute.
* **The RECORDINGS token has NO bootstrap dependency of its own** — and this document
  says so plainly rather than borrowing the backup token's reason. Every in-app consumer
  of the recordings bucket already needs the database up. What holds it in the
  environment is a *second consumer with no database*, plus the "one credential, one
  home" rule that already keeps `resend_api_key` out of the console
  (`apps/api/core/settings.py:220-246`). That is a weaker load than the backup token's,
  it is genuinely load-bearing today, and it is stated as such.

Moving either buys nothing and costs something. No change is proposed.

## Two premises in the question, corrected first

1. **It is not `scripts/check_deploy_env.py` that aborts the deploy.** That gate only
   folds the three SDK names into the key set it placeholder-scans
   (`scripts/check_deploy_env.py:110,123`). The abort is
   `scripts/vps-deploy.sh:255-264`, which `grep`s `.env` for `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` by name and `die`s. `AWS_REGION` is **optional** and defaults
   to `auto` (`apps/workers/storage.py:183`; `scripts/vps-deploy.sh:263`), so it is not
   part of the demand at all.
2. **`object_store_endpoint` / `object_store_bucket` are not purely console-managed.**
   They are `LIVE` console fields (`apps/api/core/platform_config.py:374-375`) *and*
   members of `BOOTSTRAP_REQUIRED` (`apps/api/core/settings.py:68-74`), so they must
   already be in the environment for the process to start; the console overrides a value
   that is required to exist. They are configuration, not credentials, which is why they
   can live in both places at all.

## Mechanism: nothing in this repository passes credentials to boto3

`apps/workers/storage.py::_client` builds the client with an endpoint, a region and a
`Config` — and **no credential arguments**
(`apps/workers/storage.py:196-201`). Resolution is botocore's own: the `Session` walks
its standard chain and reads `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (and
`AWS_SESSION_TOKEN` / `AWS_PROFILE`) out of the process environment. Our code names those
variables in exactly two places, and neither is a hand-off:

* `_CREDENTIAL_ENV` (`apps/workers/storage.py:120`), read only to **hash** into the client
  cache key so a rotated key yields a new client (`storage.py:139`) — the module comment
  at `storage.py:113-119` says outright that these "are deliberately not `Settings`
  fields and never will be";
* `runtime_config_missing_keys`, which reports them **off `os.environ`, not off `cfg`**,
  "because that is where they actually live … a check against a `Settings` field would be
  checking a value the SDK never sees" (`apps/api/core/settings.py:664-689`).

`scripts/check_env_parity.py:130-147` carries the same statement as the registered
argument, and `calevate_shared.config.SDK_OWNED_ENV_KEYS`
(`packages/shared/src/calevate_shared/config.py:30-53`) is the enforcement: `Settings`
must *drop* these three from the `.env` it reads or refuse to construct at all (D-188).

**That is the mechanical reason, precisely stated: the credential never passes through
our code, so there is no place a console-resolved value could be injected without first
making it a `Settings` field and handing it to `Session().client(...)` ourselves.**

## What a move would actually take

The console path a secret takes today, end to end, using `bolna_api_key` as the worked
example:

1. `ops/secret_service.set_secret` seals the plaintext under a DEK wrapped by
   `PLATFORM_KEK`, AAD-bound to `platform_secret:<key>`
   (`apps/api/ops/secret_service.py:41-56`). There is no read-back function and there
   will not be one (`secret_service.py:15-19`).
2. `resolve_secrets` decrypts the current version of every row **for this process only**
   (`apps/api/ops/secret_service.py:315-355`), skipping any key the environment declares.
3. `core/platform_config` merges the result into the override layer via
   `apply_platform_overrides` (`apps/api/core/settings.py:274-304`), which clears the
   `Settings` cache.
4. The consumer just reads `Settings`: `build_engine` does
   `BolnaEngine(api_key=cfg.bolna_api_key, ...)` (`apps/api/engine/__init__.py:62`).

Step 4 is the step the object store does not have. To get it, all of the following change
together: add two `Settings` fields; remove the names from `SDK_OWNED_ENV_KEYS` (and its
asserted twin `SDK_ENV_KEYS`, `scripts/check_env_parity.py:154-161`); pass
`aws_access_key_id=` / `aws_secret_access_key=` explicitly in `storage._client`; re-point
`_client_fingerprint` at the settings values rather than `os.environ`; move the
`runtime_config_missing_keys` check onto `cfg`; drop the `vps-deploy.sh` preflight; update
`tests/conftest.py:143-146`'s ambient-credential stripping. Roughly six files. **It is not
hard, and difficulty is not the argument.**

## Why it should not move anyway

**1. The second consumer has no database.**
`infra/object-lifecycle/apply_lifecycle.py` is a standalone operator script —
"Credentials come from the standard AWS environment variables and are never read from a
file in this repository" (`apply_lifecycle.py:27`), enforced at
`apply_lifecycle.py:159-181`, and it refuses when they are absent (`:164-167`). It is the
*only* thing that configures the bucket lifecycle rule that actually deletes recording
bytes (`apply_lifecycle.py:3-8`). It runs on a laptop or a deploy step, imports nothing
from the app, and therefore cannot decrypt a console secret. A console-managed credential
gives that script no authentication at all — or gives the credential **two homes**, which
is the drift `check_env_parity` exists to prevent and which `storage.py:113-119` already
records as the reason.

**2. Two homes is a rotation trap, and we have already decided this once.** The
environment *silently wins* over the store (`apps/api/core/settings.py:288-294`). That is
exactly the argument that keeps `resend_api_key` env-only: "a credential with two homes is
one an operator can rotate in the place that does not win"
(`apps/api/core/settings.py:230-233,240-245`). Nothing about R2 is different.

**3. Blast radius is not improved; it is widened.** `PLATFORM_KEK` and `DATABASE_URL` are
themselves in `.env` (`apps/api/core/settings.py:210-215`). So anyone who can read `.env`
on the box already holds the key and the store, and therefore every console-managed
secret. The env-var exposure is a **subset** of the console exposure, not a peer of it.
Moving the R2 credentials into the console removes no reader and adds two — a console
operator session, and a database dump paired with the KEK.

**4. The bootstrap question, answered honestly for recordings: no.** Object storage is
*not* needed before the console/database is usable on the app path. `storage._client`
reads `settings.object_store_endpoint` (`storage.py:182`), a console-managed `LIVE` field
— so a recording copy already presupposes a live database. The recording copy, the payload
archive, the delivered-body store and `retention._erase_*` all run in workers that have
loaded config. **There is no ordering problem here, and it would be dishonest to claim
one.**

## The backup credential is a different token in a different place, and it is decisive

The founder's two R2 tokens are not two copies of one arrangement:

* **Recordings** — `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the app hosts' `.env`,
  consumed by botocore as above.
* **Backups** — a separate token, in a separate file, on a separate host:
  `/etc/wal-g/walg.json`, placeholders `<<SECRET:r2/backup/access_key_id>>` /
  `<<SECRET:r2/backup/secret_access_key>>` against `<<SECRET:r2/backup/bucket>>`
  (`infra/backup/walg.json.template`). It is read by `wal-g` via `WALG_CONFIG_PATH`
  (`scripts/backup/basebackup.sh:22-23`), running as `postgres` on the database host
  (D-26 puts Postgres on its own box, per `apps/api/core/settings.py:225`). The template's
  own README explains the format choice: **`archive_command` runs in PostgreSQL's
  environment, not a login shell**, so exported variables are simply not there.

Three properties make this one un-console-able rather than merely inconvenient:

* **The restore path runs with the database destroyed.**
  `restore_command = '/usr/local/bin/wal-g --config /etc/wal-g/walg.json wal-fetch …'`
  (`runbooks/database-restore.md:157`). A credential stored in the cluster you are
  restoring is unreadable at precisely the moment it is needed. This is `PLATFORM_KEK`'s
  argument — "a database holding both the lock and the key is encryption as theatre"
  (`apps/api/core/settings.py:212-215`) — with one extra turn: here the database is not
  merely holding the key, it is *gone*.
* **The archiver is not our process.** `archive_command` is invoked by PostgreSQL. There
  is no `Settings`, no override layer, and no import of our code to put one in.
* **The whole point of the second chain is surviving the loss of the first.** The drill
  is run with `/etc/wal-g/walg.json` renamed and no R2 credential in the environment
  (`runbooks/backup-restore-drill.md:135-138`), and `scripts/backup/dump-offsite.sh:19-21`
  states that the offsite copy's destination and credential must not be Cloudflare's. That
  chain's credentials are an rclone remote in `/etc/calevate/rclone.conf` plus age
  recipient keys in `/etc/calevate/backup-recipients.txt` (`dump-offsite.sh:30-38`) —
  operator-supplied, deliberately absent from this repository, and equally unreachable
  from a console.

**So yes: the answer differs between the two tokens.** The backup token is a hard
impossibility. The recordings token is a well-argued choice with a live second consumer
behind it. If `apply_lifecycle.py` were ever retired or given database access, the
recordings credential *could* move — and it still should not, on grounds 2 and 3 above.

## Decision-log entry

**Warranted.** The reasoning exists in `storage.py:113-119` and
`settings.py:664-689` but was never written down as a decision, which is why the question
had to be asked at all. Suggested one-line summary:

> **THE OBJECT-STORE CREDENTIALS STAY IN THE ENVIRONMENT, AND THE RECORDINGS TOKEN AND THE
> BACKUP TOKEN STAY THERE FOR DIFFERENT REASONS.** Recordings: botocore resolves
> `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` itself and nothing in the tree passes them
> (`workers/storage._client`), the lifecycle script `infra/object-lifecycle/apply_lifecycle.py`
> is a second consumer with no database, and a credential with two homes is one an
> operator rotates in the place that does not win (`resend_api_key`'s argument). Backups:
> a SEPARATE token in `/etc/wal-g/walg.json`, read by `wal-g` as `postgres` on the database
> host and by `restore_command` when the database is gone — the `PLATFORM_KEK` argument,
> with the store not merely holding the key but absent. **The recordings token has no
> bootstrap dependency of its own and this entry does not claim one.**

## Verification notes (hard rule 11)

Every claim above is cited to a file and line in this repository, read 25 Aug 2026.

* **botocore's credential-resolution chain** (the order in which it consults environment
  variables, shared config and instance metadata) is asserted here only as "it reads those
  environment variable names". That much is proved from our own tree: `storage._client`
  passes no credentials and the deploy demands the names. The full chain order is
  **REPORTED, not verified this session** — botocore's documentation was not fetched.
  Nothing in this verdict depends on the ordering.
* **Cloudflare R2's per-bucket token model** (that the founder's two tokens are separately
  scoped) is taken from the founder's statement in the question and from
  `infra/backup/walg.json.template`'s separate `<<SECRET:r2/backup/*>>` namespace. It is
  **REPORTED**; Cloudflare's docs are not cited here.
* `runbooks/database-restore.md:12-16` marks itself **UNVALIDATED** — no step has been run
  against a real cluster or bucket. The restore *path* is what this document relies on
  (which file wal-g reads, and when), not the outcome of a drill.
