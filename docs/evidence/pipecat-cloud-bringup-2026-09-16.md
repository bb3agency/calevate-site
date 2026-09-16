<!-- EVIDENCE CLASS: MIXED, and labelled per claim below. This file records the FIRST time
     any part of the Pipecat Cloud leg was exercised against a real host and a real vendor
     CLI (16 Sep 2026). Everything this repository knew about that CLI before this date was
     REPORTED — transcribed into docs/DEPLOYMENT.md §12.1 from material nobody here could
     open, because `docs.pipecat.ai` is egress-blocked from the development container and
     the `cli` extra is not installed in it. The VERIFIED rows below are the first facts
     about it that came from the tool itself.

     Commands were run by the founder on the deploy host (srv1929611) as the `calevate`
     account and the output relayed. That is why host-observed rows are REPORTED-BY-OPERATOR
     rather than VERIFIED: nobody in this container watched the terminal. Hard rule 11 means
     no row here may be restated as fact from this file alone once it matters to money, a
     wire value or a client-facing claim — re-run the command, which is the point of
     `scripts/deploy/pipecat-worker-setup.sh` existing. -->

# Bringing the voice worker up on Pipecat Cloud — what the first real host taught us

**Date:** 2026-09-16. **Host:** the production VPS, as the `calevate` deploy account.
**Related:** D-592 (the engine swap), D-618 (the Gnani TTS leg), D-619 (this bring-up made
executable), `docs/DEPLOYMENT.md` §12, `docs/PIPECAT-MIGRATION.md` §6.

## Why this file exists

`docs/DEPLOYMENT.md` §12.5 is the CONTRACT — the seven things a human must do, and the pass
condition for each. This file is the RECORD: what actually happened the first time somebody
ran them, which of the unknowns closed, and what the attempt taught us about our own tooling.
The two are deliberately separate. A contract that accumulates war stories stops being
readable as a contract, and a record that gets edited to match the current state stops being
evidence of anything.

## Evidence classes used here

| Class | Meaning in this file |
| --- | --- |
| VERIFIED | Read this session from a primary source: the tool's own output, or an installed file in this tree |
| REPORTED-BY-OPERATOR | Run on the deploy host by the founder and relayed; not observed from this container |
| UNKNOWN | Not filled. The command or page that would close it is named |

## The state before

**NO REAL CALL HAS EVER BEEN PLACED ON THIS PRODUCT** (BLOCKER-1), and the reason had
narrowed to one thing: the worker ran nowhere. The Gnani TTS leg, the Plivo carrier answer
document, the knowledge-pack loader and the pipeline were all built and tested against fakes.
Every one of them was waiting on the same prerequisite — a Pipecat Cloud account — which is
why §12.5 gate 1 was the only gate that mattered.

## What closed

### Gate 1 — the account. CLOSED.

The account exists and `pipecat cloud auth login` was reached. REPORTED-BY-OPERATOR.

### Gate 3 — the base image digest. CLOSED.

```
dailyco/pipecat-base@sha256:c34a7c605b0f42d790a7593c9870417a098b0d6258b87119ebd6142d27c11e82
```

REPORTED-BY-OPERATOR, resolved with `pipecat-worker-setup.sh digest` on the deploy host, which
has the registry access this container does not: Docker Hub's blob CDN answers **403 through
this environment's proxy** (re-measured 16 Sep 2026, on `pgvector/pgvector:pg16` and
`redis:7-alpine`), which is the same failure `apps/voice-worker/Dockerfile` already records.

**It is recorded in the DOC (§12.5 gate 3) and NOT defaulted in the Dockerfile.** A digest is
a statement about what one registry held on one day. Baking it into the build file would make
a stale pin look like a verified one the next time somebody moves hosts, and the `ARG` would
stop being the question it is meant to ask. `build` and `deploy` both REFUSE without
`PIPECAT_BASE`, so the pin cannot be lost by forgetting it.

## What the vendor's CLI told us — the first verified facts about it

### `pipecat` on PATH is NOT `pipecat cloud` available. VERIFIED.

`uv tool install "pipecat-ai[cli]"` succeeds and puts a working `pipecat` on PATH. The
`cloud` verb then answers:

> The `pipecat cloud` command requires the optional `pipecatcloud` plugin, which isn't
> installed.

The base `cli` extra does not carry it, and **every verb this product needs is a `cloud`
verb**. Its two remedies, quoted from the tool:

* `uv tool install "pipecat-ai[cli]" --with pipecat-ai-context-hub --with pipecatcloud`
* `uv pip install pipecatcloud`

The second is what establishes that **`pipecatcloud` alone is the distribution the `cloud`
verb needs** — which is why `pipecat-worker-setup.sh` passes only that. `pipecat-ai-context-hub`
is a different plugin nothing here uses; ⚠ it arrives as a transitive dependency anyway
(`pipecat-ai-context-hub==0.8.0` in the host's install), so omitting it from `--with` is
redundant rather than exclusionary.

The install pulls **131 packages** and installs two executables, `pc` and `pipecat`.
REPORTED-BY-OPERATOR.

### The host's own toolchain. REPORTED-BY-OPERATOR.

| | |
| --- | --- |
| deploy account | `calevate`, uid 1001, home `/home/calevate` |
| docker | 29.8.1 |
| uv | **0.12.5**, already on PATH |
| free disk | 28 GB |

The pre-existing uv matters for one reason: `pipecat-worker-setup.sh` extracts a
**digest-pinned uv 0.8.17** from the image the root `Dockerfile` already trusts, but only
when uv is ABSENT. On this host it was not, so that path went unexercised and the host's own
uv did the install. That is correct — the pinned digest governs what goes INSIDE the image,
not what installs a local tool — but it means the extraction path is still unproven on a real
host. It will run on the next clean VPS, which is exactly the case the script exists for.

## The CLI's real surface, read first-hand (VERIFIED)

Everything this repository knew about this tool before today was REPORTED from material
nobody here could open. These came from the tool itself, on the deploy host.

`pipecat cloud` commands: `deploy`, `docker`, `auth`, `build`, `github`, `organizations`,
`regions`, `secrets`, `spend-limit`, `agent`. Global `--output rich|plain|json` (place it
BEFORE the subcommand), and `--show-cli-config`.

### Gate 2 — the region. CLOSED as a QUESTION; one fact still to fetch.

**The manifest cannot select a region and never could.** The vendor's own scaffold, read
from inside the pinned wheel (`pipecat/cli/templates/server/pcc-deploy.toml.jinja2`), emits
exactly `agent_name`, `secret_set`, `agent_profile`, an optional `[krisp_viva]` and
`[scaling] min_agents`. Ours matches it. So §12.5's "the template has NO region key" was
right, and the reason is that **region is a DEPLOY-TIME flag**: `pipecat cloud deploy`
takes `--region` / `-r`, and there is a whole `regions` command.

⚠ **AND THE ARCHITECTURE TRAP, WHICH NOBODY HAD SPOTTED.** `deploy` also takes
`--architecture` (amd64 or arm64), documented as *"Omitted, the region's default applies.
Regions support specific architectures — see 'regions list'. Must match how the image was
built."* Our image is built on the VPS, which is amd64. If the chosen region defaults to
arm64 the container does not start, and that failure does not announce its cause. Run
`pipecat cloud regions list` BEFORE the first deploy and record the region id and its
architecture here.

Other `deploy` flags worth knowing: `--min-agents`/`--max-agents` (default cap 50),
`--secrets`, `--organization`, `--profile` vs `--resources` (mutually exclusive; the second
is for self-hosted regions), `--max-session-duration` (60–14400s, default 7200) and a
GitHub-source path (`--repo`, `--branch`, `--dockerfile-path`).

### ⚠ EVERY REGION IS arm64. THE BIGGEST FINDING OF THE DAY.

`pipecat cloud regions list`, read on the deploy host 16 Sep 2026 (REPORTED-BY-OPERATOR):

| Code | Name | Architectures | Default |
| --- | --- | --- | --- |
| `ap-south` | Asia Pacific (Mumbai) | arm64 | arm64 |
| `eu-central` | Europe (Frankfurt) | arm64 | arm64 |
| `us-east` | US East (Virginia) | arm64 | arm64 |
| `us-west` | US West (Oregon) | arm64 | arm64 |

**There is no amd64 region.** The deploy host is amd64, so:

* the base image digest closed as gate 3 earlier the same day is the **amd64** manifest — a
  plain `docker pull` resolves a multi-arch tag to the host's architecture — and an image
  built on it cannot start on this platform. **Gate 3 is re-opened** and the digest must be
  re-resolved with `--platform linux/arm64`;
* `docker build` on the VPS must cross-build (`buildx --platform linux/arm64`, which needs
  QEMU binfmt handlers), or the build must be handed to Pipecat's own cloud build
  (`deploy --build-dir/--dockerfile/--build-id`);
* `deploy --architecture` only DESCRIBES the image. It does not convert one.

`pipecat-worker-setup.sh` now pins the platform on every pull and build, REFUSES a digest
whose architecture is not the target, and `doctor` reports the host/platform mismatch with
its remedy before a build is attempted. `ap-south` being Mumbai also confirms the region
this product wants is real and self-serve.

### The organization slug carries a typo

`auth whoami`: *User `calevate.voice@gmail.com`, Active Organization `Calevate Voice
(calevate-coice)`*. The display name is right; the SLUG reads `calevate-coice`. It is what
`deploy --organization` selects, so it is worth correcting in the vendor's dashboard before
an agent and a secret set exist under it. Cosmetic today, awkward later.

### Gate 4 — headless login. CLOSED, and the answer is NOT the browser flow.

**`pipecat cloud auth login` does NOT complete on a headless host.** It prints a URL and
binds a listener on the LOCAL loopback (`127.0.0.1:8400`), so the OAuth callback must reach
*that machine*. Authorising in a laptop browser sends the callback to the LAPTOP's
127.0.0.1:8400, where nothing is listening, and the VPS waits for ever. Observed on the
deploy host, 16 Sep 2026.

**The supported way past it is `pipecat cloud auth use-pat`** — a Personal Access Token,
prompted for and not echoed, which stores credentials to
`~/.config/pipecatcloud/pipecatcloud.toml`. This is the ONE to use on any deploy host.
(An `ssh -L 8400:127.0.0.1:8400` tunnel also works and was the first remedy proposed here;
the PAT is better because it needs no tunnel and no browser at all.)

⚠ **A URL CARRYING AN OAUTH CODE IS A CREDENTIAL.** One was pasted into a shell prompt
during this, where bash tried to EXECUTE it and split it on `&` into background jobs. The
code was single-use and is spent; the habit is the thing to avoid.

## What is still UNKNOWN, by name

None of these is guessed at anywhere in the tree.

1. ✅ **How the region is selected — ANSWERED** (a `--region` flag, see above). What is
   still unfetched is the region's IDENTIFIER and its ARCHITECTURE, from
   `pipecat cloud regions list`. **This one has teeth**: the product is India-latency-bound,
   an agent that silently lands elsewhere is a latency defect nothing in CI can see, and a
   region whose architecture differs from the image is a container that will not start.
2. **Whether Pipecat Cloud injects the secret set as process ENVIRONMENT.** `boot.py` reads
   `os.environ`. The vendor's scaffold wording implies environment; nobody has confirmed it.
   *Closes when*: `--preflight` prints OK inside the deployed container. If it prints FAIL
   listing variables that were definitely set, that IS the answer, and the fix is small and
   local to `boot.py`.
3. **The real syntax of `pipecat cloud secrets set`.** §12.1 records
   `<set> --file <file>` as REPORTED. `pipecat-worker-setup.sh secrets` checks the CLI's own
   `--help` before sending anything and refuses, printing that help, on a mismatch.
4. ✅ **Headless login — ANSWERED.** It does not; `auth use-pat` is the way. See above.
5. **The SIGTERM-to-SIGKILL window.** `PIPECAT_WORKER_DRAIN_GRACE_SECONDS` defaults to 20.0,
   reasoned from OUR bounds and nothing the platform has stated. §12.5 gate 7.
6. **`min_agents`.** One warm instance is a pilot choice; zero means a documented ~10 s cold
   start on an inbound call. §12.5 gate 8.
7. **What a barge-in costs in milliseconds on Gnani.** Their protocol documents no cancel
   message, so closing the socket IS the interruption, and Pipecat awaits `_disconnect()` then
   `_connect()` INLINE when the bot was speaking (`pipecat/services/tts_service.py:2011-2013`,
   VERIFIED). A full WSS reconnect therefore sits between the caller interrupting and the
   agent's next word, inside the 500 ms budget. *Closes when*: measured on a live call.

## The blocker this found, which is the real result of the bring-up

**THE WORKER HAS NO ROUTE TO OUR DATABASE, AND THE DESIGN ASSUMED IT DID.**

Found by running `sources` on the deploy host: `psql` answered *"could not translate host
name `host.docker.internal`"*. REPORTED-BY-OPERATOR, and the cause is VERIFIED from this
tree — this deployment runs Postgres ON THE HOST and containers reach it over the Docker
bridge (`compose.prod.yml:36`, `docs/DEPLOYMENT.md:102`). The voice worker is **box 1**,
Pipecat Cloud, a different network, where that name resolves to nothing and the host's
Postgres is not reachable at all.

`docs/PIPECAT-MIGRATION.md:181` says the adapter *"speaks to the worker through the
database"*. That sentence and the box diagram at §8 were both settled, and between them
sits a network edge nobody drew. Nothing else in the contract has the problem: the object
store is R2 and is internet-reachable already; every other value is a credential.

It is now `docs/DEPLOYMENT.md` §12.5 **gate 6** — ⚠ **CLOSED the same day by D-621**, which
took the third of its four options (the worker stops touching Postgres and speaks HTTP to
`apps/api`); the paragraph below records the state at the time of writing, with four
options and none chosen, because
this is an infrastructure decision and not a credential. `pipecat-worker-setup.sh secrets`
REFUSES a host-local DSN rather than accepting one that cannot work
(`ALLOW_HOST_LOCAL_DSN=1` overrides, for the deployment where somebody has genuinely made
the database reachable).

**Why this matters more than it looks:** it would have been caught anyway, by `--preflight`
inside the deployed container, which opens the pool and runs `SELECT 1`. But it would have
been caught as a confusing boot failure in a container whose logs are on somebody else's
platform, after the secret set was populated and the image pushed — rather than as a
sentence at the prompt. The gates are ordered the way they are for exactly this reason.

## Two defects this found in OUR tooling, not the vendor's

Both were found by RUNNING things, and neither was visible from a diff.

### A diagnostic that hangs is worthless on the only host it matters for

`pipecat-worker-setup.sh doctor` hung indefinitely in its DISK section. Cause: the measurement
asks the daemon where it writes (`docker_root`), and **`docker info` against a wedged daemon
BLOCKS rather than erroring**. A wedged daemon is precisely the host somebody runs a doctor
on. Fixed: every probe goes through `DOCKER_PROBE_TIMEOUT`, doctor distinguishes "did not
answer" from "refused", and DISK skips rather than hangs. Proven against an unroutable
`DOCKER_HOST`: 3.0 s to a clean refusal where it previously never returned.

### CLAUDE.md claimed the Pipecat `cli` extra was installed. It is not.

The `apps/voice-worker` section told the next session to run `check_deprecation` /
`search_api` "rather than recalling an API", on the stated ground that the extra IS
installed. The pin is `pipecat-ai[sarvam,websocket]==1.10.0`; `typer` and `questionary` are
absent and `.venv/bin/pipecat --help` says so. **The claim was written from memory inside the
paragraph that exists to warn against writing from memory.** What made it plausible: the
vendor's `AGENTS.md` IS readable at that path, and it is package DATA that ships with the
wheel whether or not the CLI's dependencies do — so its presence proved nothing about the
extra. Corrected in place, with the substitute that needs no extra: read the installed source
under `site-packages/pipecat/`.

## The sequence that works

Run as the deploy account; `doctor` first on any host, and it changes nothing.

```
scripts/deploy/pipecat-worker-setup.sh doctor
scripts/deploy/pipecat-worker-setup.sh install-cli
scripts/deploy/pipecat-worker-setup.sh login          # needs a tty
scripts/deploy/pipecat-worker-setup.sh digest
scripts/deploy/pipecat-worker-setup.sh secrets        # needs a tty
export PIPECAT_BASE=dailyco/pipecat-base@sha256:<the digest above>
scripts/deploy/pipecat-worker-setup.sh build
scripts/deploy/pipecat-worker-setup.sh preflight
scripts/deploy/pipecat-worker-setup.sh deploy
```

**`preflight` printing FAIL with no secret set injected is the expected result**, and it is
worth saying twice because it looks like a failure and is not. It lists every missing
variable at once, by design (`boot.load_worker_config` raises ONE error naming all of them,
rather than teaching an operator about eight variables across eight deploys). What it proves
locally is the LAYOUT — that `bot.py` and `voice_worker/` are where the base image's
entrypoint will look. An `ImportError` is the real failure.

## What a future session should not repeat

* **Do not transcribe a vendor CLI's flags into a doc and then trust the doc.** Everything in
  §12.1 was written that way and the very first verb we ran contradicted the premise that the
  tool was even complete. The script's `require_cli_shape` exists for this: it reads the
  tool's `--help` and refuses rather than sending a credential to a flag that may not exist,
  because that particular failure LOOKS like success and leaves the key unset.
* **Do not assume a binary on PATH means its subcommand works.** Plugins are a vendor
  mechanism; check by running the verb.
* **Do not conclude a package's extra is installed because a file from that package is
  readable.** Package data and optional dependencies ship independently.
* **Do not build on the VPS without checking disk first.** The worker resolves 76
  distributions on top of a base image of then-unknown size, and this host needed the reclaim
  ladder run earlier the same night. `doctor` and `build` both refuse below a 6 GB floor and
  name `docker-reclaim.sh`.

---

## Addendum, same day: the build moves to Pipecat (D-622)

**How these facts were obtained, and it is a different route from everything above.**
`docs.pipecat.ai` is egress-blocked from this container, but `pipecatcloud` is an ordinary
PyPI package: it was installed into a scratch virtualenv here (**version 1.2.0**) and its
source read directly. That makes the claims below **VERIFIED-VENDOR-SOURCE** — the code that
actually builds the request — rather than REPORTED-BY-OPERATOR readings of `--help`. Two
things in the section above were half wrong and are corrected here.

### `pipecat cloud build` cannot start a build

Its subcommands are `logs`, `status`, `list`. A cloud build is started by `deploy`, and is
what happens when no `image` and no `build_id` are supplied: *"No image specified, using
Pipecat Cloud Build"* (`cli/commands/deploy.py:909-945`). **Cloud builds use managed pull
credentials**, so the `--credentials` image-pull secret a pre-built image requires is skipped
entirely (`:953-957`). That is what removes a registry from this deployment's surface.

### The region IS a manifest key, and "the scaffold has no region key" proved nothing

`_utils/deploy_utils.py::load_deploy_config` has an `expected_keys` set that is both the
schema and a refusal list — an unknown key raises *"Unexpected keys in config file"*. It
contains `agent_name`, `image`, `build_id`, `image_credentials`, `secret_set`, **`region`**,
`scaling`, `docker`, `build`, `agent_profile`, `krisp_viva`, `git`, `websocket_auth`,
`max_session_duration`, `resources`, **`architecture`**.

The earlier conclusion came from the vendor's scaffold TEMPLATE, which emits none of those.
A template is what the vendor chose to generate, not what the parser accepts — that
distinction is the whole error. `apps/voice-worker/pcc-deploy.toml` was then loaded through
that function to confirm it: `region='ap-south'`, `architecture='arm64'`, `image=None`,
`build_id=None`, `build.context_dir='.'`, `build.dockerfile='apps/voice-worker/Dockerfile'`.

### The build request carries no architecture, and no build args

`api.py::_build_create` sends `uploadId`, `dockerfilePath` and `region`. Two consequences:

* **There is no `--build-arg`.** Whatever `ARG PIPECAT_BASE` defaults to in the Dockerfile
  IS what their builder builds on, which is why the digest moved into that file.
* **Region is the only architecture lever the client has.** Builds are cached per
  `(context_hash, region)` (`_cloud_build_flow`), which only makes sense if the output
  differs by region. Combined with every region being arm64-only, that is strong structural
  evidence the build is arm64 — but the server's behaviour is **not in the client source**,
  so it stays UNKNOWN until `build logs` says otherwise. It is safe to settle empirically
  because no live call exists to break (BLOCKER-1).

### The secret set does reach the container as process environment

Previously open. Three independent readings agree, and none of them is an inference from
naming:

* the secrets CLI parses `KEY=VALUE` lines (`cli/commands/secrets.py:148,178`) and the
  vendor's instruction is `pipecat cloud secrets set <name> --file .env`;
* their guide: a deployed bot *"has none of your local `.env`, so without it it starts but
  every service call fails on missing keys"* (`pipecat/cli/agent_templates/AGENTS.md:302-304`,
  inside the pinned wheel);
* their own scaffold branches on `os.environ.get("ENV")` to decide whether Krisp is available
  once deployed (`AGENTS.md:310`), which only works if the platform sets process environment.

### Their `.dockerignore` matcher is not Docker's, and the context was 2.3GB

`_utils/build_utils.py` uses `fnmatch` against **every path component** as well as the whole
relative path, and `load_dockerignore` keeps `!` lines as literal patterns — so **negation
does nothing** and a root-level `*.md` also matches `runbooks/alarm-index.md`. Docker uses
Go's `filepath.Match`, whose `*` does not cross a `/`.

Running their exclusion code over this repository produced **78,540 files / 2.3GB**:
`.dockerignore` had never excluded `.claude/worktrees/` (a full checkout per agent) or
`mergewt/`, both git-ignored. `create_deterministic_tarball` builds the tarball **in memory**
before uploading, so that is an OOM rather than a slow build. After excluding them: **1,268
files / 29.2MB**. `scripts/pipecat_build_context.py` is now the single implementation used by
both `pipecat-worker-setup.sh context` and `tests/build_context_test.py`, whose git-ignore
clause immediately found two more leaks (`apps/web/next-env.d.ts`,
`apps/web/tsconfig.tsbuildinfo`).

### The digest never needed to be relayed from the deploy host

*"No digest can be resolved from here (the registry is unreachable through this
environment's proxy)"* confused **pulling** with **reading a manifest list**. The blob CDN
does answer 403; the manifest API does not. `docker buildx imagetools inspect
dailyco/pipecat-base:latest --raw`, run in this container on 16 Sep 2026, returns the OCI
index naming `linux/arm64` as
`sha256:7dcc71f3e658b66fcb36fa420a16673d3ca1c52b932d496365763dbbb9844c4c` and `linux/amd64`
as `sha256:613244ff092d65f9d9b5c9ba8f6a405c7557639508680f6a57d38f59069ce071`. Note `--raw`
and not `--format`: the latter fetches each child's config blob and hits the blocked CDN.

That also removes the older failure mode. `docker pull --platform` is silently a no-op on a
host with no binfmt handlers — proven on the deploy host, where `docker run --platform
linux/arm64 alpine:3.20 uname -m` answers `exec format error` while
`/proc/sys/fs/binfmt_misc` holds only `python3.12`.

### Revised bring-up order

```
scripts/deploy/pipecat-worker-setup.sh doctor
scripts/deploy/pipecat-worker-setup.sh install-cli
scripts/deploy/pipecat-worker-setup.sh login          # needs a tty; auth use-pat works headless
scripts/deploy/pipecat-worker-setup.sh digest         # diffs the registry against the committed pin
scripts/deploy/pipecat-worker-setup.sh sources
scripts/deploy/pipecat-worker-setup.sh secrets        # needs a tty
scripts/deploy/pipecat-worker-setup.sh context        # what would be uploaded, and how big
scripts/deploy/pipecat-worker-setup.sh deploy         # uploads, builds on Pipecat, deploys
scripts/deploy/pipecat-worker-setup.sh preflight
```

`build` is gone. There is nothing on an amd64 host to build an arm64 image with, and keeping
a subcommand that cannot run on the only host that runs it is the second way to do one thing
that this repository does not keep.

---

## The first real cloud build, 16 Sep 2026 — it worked

**EVIDENCE CLASS: REPORTED-BY-OPERATOR** — run by the founder on the deploy host as the
`calevate` account, output relayed verbatim. This is the first time any part of this
deployable has been accepted by the vendor's infrastructure.

```
Build context: 1271 files, 10.0 MB compressed, hash=63b65093368e9a4f
No cached build found, starting new build...
Upload complete
Build started: 85554203-766d-4b6c-b379-1169c0249c7c
Build Complete (74s)
```

### What that settles

**The context estimate was right, and the method was sound.** `scripts/pipecat_build_context.py`
predicted 1,268 files / 29.2MB from this repository; the deploy host produced **1,271 files /
29.2MB, 10.0MB compressed**. The three-file difference is `.deploy-state/`, which exists only
on a machine that has deployed — see below. Predicting a vendor-side number to within three
files, from a re-implementation of their matcher, is the check that the matcher was read
correctly rather than approximately.

**A cloud build takes 74 seconds.** For comparison, the alternative was an emulated arm64
build of an ONNX-carrying image on a 1-vCPU VPS. That is the whole of D-622's argument,
measured.

**The manifest was accepted exactly as written.** The CLI's own review panel echoed
`Region: ap-south`, `Agent profile: agent-1x`, `Min agents: 1`, `Krisp VIVA: Disabled`,
`Max session duration: Default`, `Organization: calevate-voice` — so `region` in the manifest
is real and load-bearing, closing the last doubt in gate 2. It also warns *"Usage costs will
apply for 1 reserved agent(s)"*, which is `[scaling] min_agents = 1` being charged for, as
that key's comment says it will be.

### And it FAILED CLOSED, which is the part worth keeping

```
Error: Secret set 'calevate-pipecat-worker-secrets' not found in organization 'calevate-voice'
```

`secrets` had aborted earlier on a missing `PLIVO_AUTH_ID`, and because that command pushes
only after collecting every value, nothing had been created. The vendor's `deploy` then
**refused rather than deploying an agent with an empty environment** — which is the outcome
their own guide describes as the bad one ("it starts but every service call fails on missing
keys"). Worth recording as a vendor behaviour we can rely on: a missing secret set is a
deploy-time error, not a runtime surprise.

Note also that the BUILD is unaffected by the secret set and is cached by context hash, so
re-running `deploy` after `secrets` reuses build `85554203-…` rather than paying for it
again.

### `.deploy-state/` — the guard's known blind spot, found in the field

The three extra files were `scripts/vps-deploy.sh`'s `deployed-sha` and `history`. Harmless
content, but git-ignored state and therefore exactly what `tests/build_context_test.py`
forbids in a context. The guard could not have caught it, and its docstring already said why:
that directory exists only on a machine that has run a deploy, and CI always builds from a
fresh clone. Now excluded, and sabotage-checked both ways.

### What is STILL unknown after a successful build

**The architecture of the produced image.** The build completed, which proves the Dockerfile
and the aarch64 wheel set are fine, but a build completing says nothing about what it
targeted — an amd64 build of this image would also have succeeded. The deploy has not yet
placed a container, so nothing has been observed STARTING. That is the gate, and it closes
when a deployed container reaches its own `--preflight` rather than failing to start.
