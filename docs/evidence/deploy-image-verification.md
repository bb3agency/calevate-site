# The production image: what has now been executed, and what still cannot be

18 Aug 2026. The second-wave register lists **"the runtime image stage has never been
built anywhere"** as ours and open. This is the attempt, its one hard blocker, and the
three things that got verified anyway — plus one latent defect the attempt turned up.

## The blocker, stated precisely so nobody re-attempts it blind

`docker build --target runtime` fails at the FIRST instruction of the builder stage:

```
COPY --from=ghcr.io/astral-sh/uv:0.8.17@sha256:e4644cb5… /uv /uvx /bin/
ERROR: failed to resolve source metadata … pkg-containers.githubusercontent.com … 403 Forbidden
```

`ghcr.io` itself is reachable through this environment's egress proxy (a manifest request
returns a well-formed 404). The **blob CDN it redirects to** —
`pkg-containers.githubusercontent.com` — is refused at the proxy's CONNECT tunnel:

```
$ curl https://pkg-containers.githubusercontent.com/
curl: (56) CONNECT tunnel failed, response 403
```

That is an egress policy of the sandbox, not a defect of the Dockerfile, and the proxy's
own README says to report such cases rather than work around them. **The image therefore
remains unbuilt, and this document does not claim otherwise.** Building it needs a host
that can pull from ghcr's blob CDN — the VPS, or CI.

The dependency is worth naming for its own sake: the build's very first instruction has a
single-point-of-failure on one host. The digest pin is deliberate and argued in the file,
and no fallback was added — a second source for the same binary would be exactly the "two
ways to do one thing" this repo treats as a defect. But the build IS one ghcr outage away
from being impossible, and that belongs in the deploy risk list rather than in a comment.

## What was verified without Docker, and how

The substance of "does the image work" is three questions, and none of them actually
needs a container. All three were EXECUTED.

**1. Does the install command populate the environment?** D-188 shipped an image whose
`site-packages` held 3 files because a bare `uv sync` installed nothing and exited 0. The
Dockerfile's current command was run verbatim into a scratch environment
(`UV_PROJECT_ENVIRONMENT` pointed away from the repo venv, `--frozen` so the lock is not
touched):

```
uv sync --frozen --no-dev --all-packages --group errors
→ exit 0, 126 packages in site-packages
```

126, not 3. The flag combination does what the file says it does.

**2. Is the production dependency set sufficient for every entrypoint?** A dev-only
dependency imported from production code is a class of failure that only shows up on the
first deploy. Every command `compose.prod.yml` and `vps-deploy.sh` actually run was
imported from that `--no-dev` environment:

| entrypoint | source | result |
|---|---|---|
| `apps.api.main:app` | compose `api` | OK |
| `main:app` (`--app-dir apps/voice-runtime`) | compose `voice-runtime` | OK |
| `apps.workers.settings:WorkerSettings` | compose `workers` | OK |
| `alembic.config` | compose `migrate` | OK |
| `scripts.seed` | `compose run` (D-168) | OK |
| `scripts.deploy_revision_check` | `compose run` (D-168) | OK |
| `scripts.check_deploy_env` | `compose run` (D-168) | OK |

Seven for seven. The three `scripts.*` are the ones D-168 found would have died with
`No module named 'scripts'`; they now import from a production-shaped environment.

**3. Does anything leak the other way?** `pytest`, `ruff`, `mypy` and `coverage` are all
ABSENT from the synced environment, and `sentry_sdk` (the `--group errors` extra
DEPLOYMENT §8 asks for) is present. `--no-dev --group errors` resolves to what it claims.

## The defect the attempt found

`calevate_shared` is **not** in `site-packages`. What is there is:

```
$ cat site-packages/_editable_impl_calevate_shared.pth
/home/user/calevate-site/packages/shared/src
```

`uv sync` installs a workspace distribution EDITABLE, so the binding between the venv and
the code is one **absolute path, baked at build time from the builder stage's WORKDIR**.
In the image that string is `/app/packages/shared/src`, and it resolves at runtime for
exactly one reason: builder `WORKDIR /app`, runtime `WORKDIR /app`, and
`COPY --from=builder /app /app` all agree.

Nothing checked that they agree, and the Dockerfile's own comment described the mechanism
incorrectly — it called `calevate-shared` "the only real distribution here … rather than a
site-packages install", which reads as though it were copied in as a package while only
`apps/*` ran from source. Both run from source.

**Why it matters.** Change the runtime `WORKDIR` to `/srv/app`, or copy the tree into a
subdirectory — both ordinary tidiness refactors — and: the build succeeds, every layer is
present, `pip list` shows `calevate-shared 0.1.0`, and all four entrypoints die at
`import calevate_shared`, on the VPS, at `vps-deploy.sh` step 7, after the build and
before the swap. That is D-188's shape one layer along: an artefact that looks healthy
and cannot run, invisible because the build exiting 0 was taken as evidence.

**Fixed** by `scripts/check_image_paths.py`, which derives the three paths from the
Dockerfile and fails when they disagree; wired into `make guardrails` and CI. It REFUSES
rather than passing when it cannot find a named stage or the file itself, per the
`check_wiring` doctrine that a check which cannot see its subject gets no verdict. Five
negative controls in `tests/image_paths_guard_test.py` each drive one plausible refactor
— relocated WORKDIR, relocated copy, no copy, renamed stage, missing file — and the real
Dockerfile is the positive control. The comment now states the actual mechanism.

## Still open, and still ours

- **The image has never been built.** Needs CI or the VPS.
- **A full rollback deploy is unrun.** Needs a host with two built artefacts on it.
Neither is closed by anything in this document, and neither should be reported as closed.
