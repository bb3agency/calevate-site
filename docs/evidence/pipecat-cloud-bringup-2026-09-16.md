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
