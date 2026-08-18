# Push-to-deploy: what was ported, what was refused, and what a human still has to do

**Date**: 2026-08-18 · **Decisions**: D-290, D-291, D-292 · **Reference**:
`bb3agency/raghava-organics-site` (read-only clone; teardown of its deploy path is
`docs/evidence/raghava-deploy-teardown.md`).

**Status in one line: this repo now has a complete push-to-deploy path and has never
deployed anything.** No image has been built here, no container started, no migration
applied on a VPS, no runner registered, no rollback executed. Everything below distinguishes
what is *verified* (a test runs it, in this repo, and fails when it breaks) from what is
*inferred* (read from the reference, the vendor docs, or the script's own logic) from what
*needs the VPS* (§4, the checklist).

---

## 1. What the pattern is, and why it is the right one

One **self-hosted GitHub Actions runner per VPS**, installed on the box, maintaining an
**outbound** HTTPS connection to GitHub. Jobs are polled, never pushed. The consequences
are the reason to take it:

- **No inbound hole.** No SSH port open to GitHub, no deploy key, no
  `VPS_SSH_PRIVATE_KEY` secret. Nothing in a GitHub settings page can reach this host if
  the runner service is stopped.
- **The deploy runs where the artefacts are.** `scripts/vps-deploy.sh` already builds,
  migrates and swaps locally; a runner on the same box means the workflow is a *trigger*,
  not a transport.
- **The blast radius of a compromised action is the production host**, which is why this
  workflow uses **zero third-party actions — not even `actions/checkout`** (hard rule 9).
  It does not need one: the deploy target is the runner's own host and the checkout it
  deploys already lives at `VPS_CLIENT_PATH`. That is the single biggest departure from
  the reference and it costs two lines of bash.

## 2. Ported, adapted, and deliberately refused

| Reference property | Calevate | Why |
|---|---|---|
| Self-hosted runner per client VPS, outbound-only | **Ported as-is** | The whole point (§1) |
| `workflow_run` on CI completing + `workflow_dispatch` | **Ported**, plus a re-check of `conclusion == 'success'` and `head_branch == 'main'` in the job `if` | `workflow_run` fires on FAILED runs too — the commonest way this pattern ships a red build. The reference checks `conclusion`; it does **not** pin the branch, so CI on a pull request would deploy the PR |
| `vars.VPS_DEPLOY_ENABLED == 'true'` kill switch | **Ported as-is** | Merging the file changes nothing until a human opts in |
| `runs-on: ${{ vars.VPS_RUNNER_LABEL \|\| 'self-hosted' }}` | **Refused.** `runs-on: [self-hosted, calevate-vps]`, literal | The `\|\| 'self-hosted'` fallback is right for a template synced across many client repos and wrong for one repo with one VPS: it is a misroute waiting for the day a second runner registers anywhere in the org. A literal label makes a typo queue forever (loud) instead of deploying to somebody else's host (silent). D-292 |
| Secret preflight step with an actionable `::error::` | **Ported and widened** | Ours also checks the script is present and executable, and that `.env` exists, naming DEPLOYMENT §9 step 4 and §6. A `cd` error forty lines into a deploy is not an error message |
| `concurrency: cancel-in-progress: false` | **Ported as-is**, group `deploy-production` | Cancelling between the migration and the swap manufactures the half-migrated state the script exists to avoid. The guardrail fails CI if this line is ever removed |
| Two jobs (backend + frontend) with `paths`-free triggers | **Refused.** One job | Component selection is a path→component map inside `vps-deploy.sh`. Splitting the job would need a second copy of that map in YAML, drifting the first time a directory moves. The property that matters (an `api` change never restarts `voice-runtime`, hard rule 3) comes from the map plus `--no-deps`, not from job separation |
| Workflow does its own `git fetch` / `checkout` / `pull --ff-only`, duplicated across both jobs | **Refused, and now refusable.** All git work is `sync_checkout` in the script; `scripts/check_deploy_workflow.py` fails CI on a `git checkout` in the workflow | This is the drift, live, in the reference: the duplicated block sits in a file its own comment records as *not* covered by their core-sync mechanism ("carried by hand from the template on 2026-08-10"). D-290 |
| Rollback documented as "revert the commit and push" or "SSH in and `docker compose up --build`" | **Refused.** `workflow_dispatch` with `commit_sha`, which passes `--checkout <sha>` to the script | A revert-and-push rollback waits for a full CI run and a full build during an incident. Theirs also rebuilds because their images are not per-commit; ours reuses the image already tagged for that commit. D-291 |
| `NGINX_AUTO_RELOAD` defaulting to `'1'` | **Adapted**: opt-in, off by default | A CD run that silently rewrites the edge config of a live site is not reviewable afterwards. Unset, the script renders and prints the install commands |
| Their `verify-cd-status.sh` post-setup preflight | **Not ported as a script**; it is DEPLOYMENT §3a step 6 (a `dry_run: true` dispatch that must reach *Deploy* and print a plan) | A dry run of the real thing beats a second script asserting things about it. The pieces it would check are already refusals inside `preflight`/`preflight_plan` |
| Sudoers grants with wildcard argument patterns (`cp /tmp/*.nginx.conf …`, `rm -rf /var/lib/docker/containers/*`) | **Refused, and already was.** `infra/privileged/` grants exactly one command with an **empty** argument list | A root command that takes its destination from the caller is a root command with an argument. Ours reads a fixed staging directory and validates everything in it |
| PM2 process-name derivation by grepping `.env.local`, falling back to a directory basename | **Not ported** | Our web tier is `deploy_web`; a name resolved by fallback is a name that is wrong on the day it matters |

## 3. What is verified here, and by what

Everything in this column runs in `uv run pytest` / `make guardrails` on this machine.

| Claim | Evidence |
|---|---|
| `--checkout <sha>` fetches and moves the deploy checkout to exactly that commit, detached | `tests/deploy_checkout_flag_test.py::test_checkout_moves_the_tree_to_that_commit_and_detaches` — a real `git clone` with an origin and two commits, `docker` stubbed on `PATH`, driven through the real script to the plan and no further |
| An ordinary deploy REFUSES from a rolled-back (detached) tree instead of pulling back to the tip | `…::test_an_ordinary_deploy_refuses_from_a_rolled_back_tree` — and it asserts the message names both ways out |
| `--checkout main` is refused; an unknown sha aborts without moving the tree | `…::test_a_ref_is_not_a_commit`, `…::test_an_unknown_commit_aborts_rather_than_deploying_the_tip` |
| The workflow calls the real script and reimplements no step of it | `scripts/check_deploy_workflow.py`, negative controls in `tests/deploy_workflow_guard_test.py` (five injected reimplementations, each detected; plus the control proving a *printed* `git checkout` is not one) |
| Every flag the workflow passes is a flag the script parses | same guardrail; the mutation renames `--expected-sha` in the script and the check goes red |
| Every `secrets.*`/`vars.*` the workflow reads is documented in `docs/DEPLOYMENT.md` | same guardrail; seven names, all present |
| Every `run:` block in the workflow is valid bash | same guardrail (`bash -n`); CI's shellcheck step only sees `git ls-files '*.sh'`, which inline workflow bash is not |
| The kill switch, the CI-success re-check, the branch pin and `cancel-in-progress: false` are still in the file | same guardrail, one parametrised test per property |
| The guardrail refuses rather than passing when its scan matches nothing | three refusal tests: no workflow, an argument loop it cannot parse, a workflow reading no secrets/vars |
| Migrations run before the swap and a failure stops the deploy | pre-existing: `run_migrations` ordering argument, `set -Eeuo pipefail`, no `|| true` in the file; `tests/deploy_rollback_test.py` pins the skip-only-on-clean-3 contract |
| The workflow is a guardrail that runs in both gates and is in the catalogue | `tests/guardrail_audit_test.py` (globs `scripts/check_*.py`; a new one fails until the Makefile, `ci.yml` and ENGINEERING-PRACTICES §2 all name it) |
| Both workflows are valid YAML and the deploy job's shape is what it says | `yaml.safe_load` in the guardrail; CI's `deploy-artefacts` job for the shell artefacts |

## 4. What is INFERRED and not verified

- **That the runner picks up a job at all.** No runner has been registered. The workflow's
  `runs-on` label, the systemd unit's `User=`, and the outbound-443 claim are all read from
  the reference guide and GitHub's own runner documentation, not observed.
- **That the production image builds.** `docs/evidence/deploy-readiness.md` §"Runtime
  stage" records it precisely: `deb.debian.org` returns 403 through this environment's
  egress proxy and ghcr's blob CDN is likewise refused, so the **runtime stage has never
  been built anywhere** — the builder stage was only proven by substituting those two
  blocked references. `docker compose -f compose.prod.yml build api` has therefore never
  succeeded here, and every downstream claim — migrate-from-the-new-image, the
  health-gated swap, the image reuse that makes a rollback a swap rather than a rebuild —
  is reasoned from the script, not measured.
- **That a rollback deploy completes.** The *git* half is tested (§3). The half that runs
  `docker`, skips the migration and swaps containers has never executed. DEPLOYMENT §4d
  step 7 is the drill that closes this, and it needs a host.
- **The swap gap.** Still "a few seconds" in DEPLOYMENT §4b, still unmeasured.
- **Whether `--replace` on re-registration preserves the label**, and whether GitHub's
  current runner release still ships `svc.sh install <user>` with that signature. Both are
  from the reference's guide, which is itself a year of accumulated practice on a working
  system — good evidence, not observation.

## 5. The human checklist — every step needs the VPS

Nothing here can be done from this repository. Run them in order; §3a and §3b of
`docs/DEPLOYMENT.md` carry the same steps with the surrounding argument.

1. **Finish DEPLOYMENT §4d steps 1–5 first** (pin the uv image by digest, build once by
   hand and time it, first deploy attended with `--dry-run`, `nginx -t` the rendered
   config, measure the swap gap). CD on top of a deploy nobody has run by hand is a way of
   discovering §4d's problems unattended.

2. **Register the runner**, as the `calevate` deploy user, never root:

   ```sh
   sudo -iu calevate
   mkdir -p ~/actions-runner-calevate && cd ~/actions-runner-calevate
   curl -o runner.tar.gz -L https://github.com/actions/runner/releases/download/v<X.Y.Z>/actions-runner-linux-x64-<X.Y.Z>.tar.gz
   tar xzf runner.tar.gz && rm runner.tar.gz
   ./config.sh --url https://github.com/<org>/calevate-site \
               --token <REGISTRATION_TOKEN> \
               --name calevate-vps --labels self-hosted,calevate-vps \
               --unattended --replace
   ```

   The URL/version and the token come from Settings → Actions → Runners → *New
   self-hosted runner*; the token expires in an hour.

3. **Make it survive reboot, and check both facts rather than one:**

   ```sh
   sudo ./svc.sh install calevate
   sudo ./svc.sh start && sudo ./svc.sh status      # active (running)
   systemctl is-enabled 'actions.runner.*.service'  # enabled
   grep -E '^(User|WantedBy)=' /etc/systemd/system/actions.runner.*.service
   ```

4. **Set the repo Secrets and Variables** — the seven in DEPLOYMENT §3a step 5, and
   nothing else. `VPS_DEPLOY_ENABLED` is set **last**. No application secret goes here;
   those are in `/var/www/calevate/.env`, placed by hand from the secrets manager.

5. **Prove it with a dry run before enabling it.** With `VPS_DEPLOY_ENABLED` still unset,
   Actions → Deploy → *Run workflow* with `dry_run: true`. Pass condition: the job is
   picked up by `calevate-vps`, the preflight step passes, and *Deploy* prints a plan.

6. **Enable and do one real cycle.** Set `VPS_DEPLOY_ENABLED=true`, push a no-op commit.
   Pass condition: CI green → deploy starts by itself → summary banner names your commit.

7. **Drill the rollback, deliberately, before you need it** (DEPLOYMENT §4d step 7).
   Actions → Deploy → *Run workflow* with `commit_sha` = the commit before that one. Pass
   conditions, all four: the run reaches the summary banner; `.deploy-state/history` shows
   the older sha; the log says the image already existed and was reused; and the **next**
   automatic deploy refuses with the detached-checkout message until
   `git -C /var/www/calevate checkout main` is run on the box.

8. **Restrict SSH.** Only after step 6: deploys no longer use port 22 at all.

9. **Record what you measured** — the swap gap into DEPLOYMENT §4b, and the fact that
   steps 5–7 passed, into `docs/evidence/deploy-readiness.md`. The §4 list above shrinks
   only when somebody writes down what they saw.

## 6. Things a reader should not conclude from this document

- Not that CD works. It has never run.
- Not that the rollback works end to end. Its git behaviour is tested; the deploy it
  triggers is not.
- Not that the runner is safe because it is outbound-only. It executes whatever a workflow
  file on `main` says, as the `calevate` user, on the production host. Branch protection on
  `main` is the control that matters and it is a GitHub setting, not a file in this repo.
