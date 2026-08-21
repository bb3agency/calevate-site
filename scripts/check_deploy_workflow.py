"""Guardrail: `.github/workflows/deploy.yml` and `scripts/vps-deploy.sh` cannot drift apart.

**The defect this exists for.** A CD workflow and a deploy script are two descriptions of
one procedure, and the workflow is the copy nobody runs by hand. Every property this
deployment relies on — migrations strictly before the container swap, the health-gated
swap, one image per commit so a rollback has an artefact, `--no-deps` so an `api` deploy
never restarts `voice-runtime` (hard rule 3) — lives in the script. The moment the
workflow starts doing any of it itself, there are two orderings, and the one that runs
unattended at 3am is the one nobody reviewed. The reference implementation this pattern
was ported from (`docs/evidence/push-to-deploy.md`) has exactly that shape: its workflow
carries its own `git fetch`/`git checkout`/`git pull --ff-only` block, duplicated verbatim
across two jobs, in a file its own comments note is not covered by the sync mechanism that
keeps every other file in step.

SIX QUESTIONS, all syntax-decidable. No network, no database, no app boot, no daemon.

1. **The workflow invokes the real script.** Some executed command runs
   `scripts/vps-deploy.sh`. A workflow that never reaches it is not a trigger in front of
   the deploy, whatever its steps say they do.
2. **It does not reimplement a step of it.** No executed command may build an image,
   run compose, run alembic, move the git checkout, touch pm2 or reload nginx. Those are
   the script's steps, each with an ordering argument written beside it, and a second
   copy here would be a second ordering.
3. **Every flag it passes is a flag the script parses.** Read off the script's own
   `case` arms, so renaming an option in the script fails CI instead of failing on the
   host. This is the assertion that makes the other five worth having: it is the one that
   fires on the ordinary, well-intentioned change.
4. **Every `secrets.*` / `vars.*` it reads is documented in `docs/DEPLOYMENT.md`.** An
   undocumented input is a value that exists only in a GitHub settings page, which is the
   one place a person setting this up for the first time will not look.
5. **Every `run:` block parses.** `bash -n` on each. CI shellchecks `git ls-files '*.sh'`
   and a workflow's inline bash is in no such file, so without this the first parse of the
   deploy command happens on the production host.
6. **The four safety properties are still in the file.** The kill switch in the job `if`,
   the CI-success re-check, the branch pin, and `cancel-in-progress: false`. Each is one
   line, each is deletable by accident, and each failure is silent: a lost kill switch is
   invisible until a deploy nobody asked for, and a lost `cancel-in-progress: false` is
   invisible until two pushes land close enough together to cancel a deploy between the
   migration and the swap — which is the half-migrated state the script is written to
   avoid, manufactured by the CI system.

**Refusal, not a pass, when it can see nothing** (exit 2): no workflow file, no `run:`
steps, no options parsed out of the script, or no `secrets`/`vars` references at all. A
scan that matches nothing and prints OK is the failure mode every check in this pack is
written against — `check_metadata_columns` (D-176) and `check_raw_sql` (D-172) both carry
the same third exit code for the same reason.

**Deliberately NOT checked.** Whether the runner label matches the one registered on the
VPS (that is a fact about a host, not about this repo — it is `verify_cd_status` territory
and OPERATIONS §2's job); whether the secrets are SET (GitHub is the authority and the
workflow's own preflight step reports it with an actionable error); and the CI workflow's
own contents, which `tests/guardrail_audit_test.py` already holds to a stricter standard.

Run: `uv run python -m scripts.check_deploy_workflow`  (also in `make guardrails`)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "vps-deploy.sh"
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "DEPLOYMENT.md"

#: The script's own name, as the workflow must spell it to be running the real thing.
SCRIPT_MARKER = "scripts/vps-deploy.sh"

#: Question 2. Each entry is a regex over an executed command and the reason that command
#: belongs in the script rather than here. Written as "what the script already owns",
#: never as "dangerous commands": the point is not that `docker build` is risky, it is
#: that `build_images` decides when to skip it and a second builder here would not.
REIMPLEMENTATIONS: tuple[tuple[str, str], ...] = (
    (
        r"\bdocker\s+build\b|\bdocker\s+compose\b|\bdocker-compose\b",
        "building or running compose is `build_images` / `swap_service`, which reuse the "
        "per-commit image tag, pass --no-deps so an api deploy cannot restart "
        "voice-runtime (hard rule 3), and gate each swap on /healthz",
    ),
    (
        r"\balembic\b|\bupgrade\s+head\b",
        "migrations are `run_migrations`, which runs them from the NEW image strictly "
        "before the swap and stands down when the database is ahead of the artefact "
        "(the rollback case). A second invocation here is a second ordering",
    ),
    (
        r"\bgit\b[^|;&\n]*\b(checkout|pull|fetch|reset|merge|rebase)\b",
        "moving the deploy checkout is `sync_checkout`, reached by --checkout for a "
        "rollback and by the pull path otherwise. The pull path refuses from a detached "
        "tree so a rollback is not silently undone; a `git pull` here would undo it",
    ),
    (
        r"\bpm2\b",
        "the web tier is `deploy_web`, which owns the build-then-reload order",
    ),
    (
        r"\bnginx\s+-t\b|\bsystemctl\s+(reload|restart)\b",
        "the edge is `render_nginx` / `install_nginx`, which stage into a fixed directory "
        "that the one privileged script validates — the sudoers grant takes no argument",
    ),
)

#: Question 6. `key` is a substring that must appear in the workflow's SOURCE (these are
#: expressions and comments-adjacent YAML scalars, not `run:` commands, so the reduction
#: used by questions 2/3/5 is the wrong instrument here).
SAFETY_PROPERTIES: tuple[tuple[str, str], ...] = (
    (
        "vars.VPS_DEPLOY_ENABLED == 'true'",
        "the kill switch. Without it in the job `if`, merging this file starts deploying "
        "— and in an incident there is nothing to switch off",
    ),
    (
        "github.event.workflow_run.conclusion == 'success'",
        "`workflow_run` fires on FAILED runs too. Without this re-check the workflow "
        "deploys red builds, which is the commonest way this pattern is got wrong",
    ),
    (
        "github.event.workflow_run.head_branch == 'main'",
        "CI running on a pull request would otherwise deploy the PR's code",
    ),
    (
        "cancel-in-progress: false",
        "cancelling a deploy between the migration and the swap manufactures the exact "
        "half-migrated state the script is written to avoid",
    ),
)


def _load() -> dict[str, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


def _run_blocks(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Every `run:` scalar, paired with the step name that carries it.

    Parsed rather than grepped, for the reason `tests/guardrail_audit_test.py` gives about
    the CI workflow: this file is heavily commented and several comments name the very
    commands they explain, so a check over file text can be satisfied by prose about a
    step that no longer exists.
    """
    blocks: list[tuple[str, str]] = []
    for job_name, job in document.get("jobs", {}).items():
        for step in job.get("steps", []) or []:
            if isinstance(step, dict) and "run" in step:
                blocks.append((f"{job_name}/{step.get('name', 'unnamed step')}", str(step["run"])))
    return blocks


def _executed_lines(block: str) -> str:
    """The block with comment-only lines and trailing comments removed.

    A `#` inside a quoted string would be stripped too, which would only ever cause a
    MISSED violation and never a false one — the safe direction for a check whose failure
    mode is accusing correct code.
    """
    kept = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept.append(re.sub(r"\s#.*$", "", line))
    return "\n".join(kept)


def script_options() -> set[str]:
    """The long options `vps-deploy.sh` actually parses, off its own `case` arms."""
    body = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    arms = re.search(r"while \[\[ \$# -gt 0 \]\]; do\s*case \"\$1\" in(.+?)\n  esac", body, re.S)
    if not arms:
        return set()
    return set(re.findall(r"^\s*(--[a-z-]+)\)", arms.group(1), re.M))


#: The script in COMMAND position — optionally under `bash`, optionally quoted, at the
#: start of a line. Deliberately not a bare substring search: the preflight step names the
#: same path inside a `[[ ! -x ... ]]` test, and a workflow that only checks the script is
#: executable and then does the deploy some other way would satisfy a substring.
INVOCATION = re.compile(
    r"^\s*(bash\s+)?\"?[^\"\s]*" + re.escape(SCRIPT_MARKER) + r"\"?(\s|$)", re.M
)


def check_invokes_the_script(blocks: list[tuple[str, str]]) -> list[str]:
    if any(INVOCATION.search(_executed_lines(block)) for _, block in blocks):
        return []
    return [
        f"no executed command in {WORKFLOW.name} runs {SCRIPT_MARKER}. This workflow is "
        "supposed to be a trigger in front of that script; a step whose `name:` says "
        "'Deploy' and whose `run:` does something else — or which only checks that the "
        "script EXISTS — is the drift this check exists for."
    ]


def _without_output(commands: str) -> str:
    """Drop `echo`/`printf` lines.

    A deploy step legitimately PRINTS the commands an operator should run — the rollback
    hint names `git ... checkout main` — and a line that only writes to stdout is not a
    second implementation of anything. Without this the check would be satisfiable only
    by workflows that give the operator no instructions, which is the wrong incentive.
    """
    return "\n".join(
        line for line in commands.splitlines() if not re.match(r"\s*(echo|printf)\b", line)
    )


def check_no_reimplementation(blocks: list[tuple[str, str]]) -> list[str]:
    failures = []
    for where, block in blocks:
        commands = _without_output(_executed_lines(block))
        for pattern, reason in REIMPLEMENTATIONS:
            if re.search(pattern, commands):
                failures.append(
                    f"{where} runs a command matching /{pattern}/ — {reason}. "
                    f"Call {SCRIPT_MARKER} instead, adding a flag to it if it needs one."
                )
    return failures


def check_flags_exist(blocks: list[tuple[str, str]]) -> list[str]:
    known = script_options()
    failures = []
    for where, block in blocks:
        commands = _executed_lines(block)
        if SCRIPT_MARKER not in commands:
            continue
        for flag in sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", commands))):
            if flag not in known:
                failures.append(
                    f"{where} passes {flag}, which {DEPLOY_SCRIPT.name} does not parse "
                    f"(it knows {sorted(known)}). The script exits 1 on an unknown option, "
                    "so this is a deploy that fails on the host at the last possible moment."
                )
    return failures


def check_inputs_documented(document: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Question 4. Returns (failures, names) so `main` can refuse on an empty scan."""
    source = WORKFLOW.read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"\b(?:secrets|vars)\.([A-Z][A-Z0-9_]*)", source)))
    doc = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    failures = [
        f"{name} is read by {WORKFLOW.name} and appears nowhere in "
        f"docs/{DEPLOYMENT_DOC.name}. A GitHub Secret or Variable that only exists in a "
        "settings page is one the next person to set this up cannot know to create."
        for name in names
        if name not in doc
    ]
    return failures, names


def check_run_blocks_parse(blocks: list[tuple[str, str]]) -> list[str]:
    failures = []
    for where, block in blocks:
        # BYTES, NOT `text=True`, and the difference is a false failure on one platform.
        # `text=True` opens the child's stdin in text mode, which on Windows translates
        # every `\n` this block holds into `\r\n` on the way down the pipe. bash then
        # reads the carriage return as part of the last token — `then` is no longer the
        # keyword — and every conditional in the workflow reports as a syntax error. The
        # gate called the deploy script broken on a developer's machine and fine in CI,
        # which is the direction that teaches people to dismiss a gate. The YAML is
        # already decoded UTF-8 by `_load()`, so encoding it back is exact.
        result = subprocess.run(
            ["bash", "-n"], input=block.encode("utf-8"), capture_output=True, check=False
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            failures.append(
                f"{where} is not valid bash: {stderr}. CI shellchecks "
                "`git ls-files '*.sh'` and this block is in no such file, so without this "
                "the first parse would happen on the production host."
            )
    return failures


def check_safety_properties() -> list[str]:
    source = WORKFLOW.read_text(encoding="utf-8")
    return [
        f"{WORKFLOW.name} no longer contains `{key}` — {reason}."
        for key, reason in SAFETY_PROPERTIES
        if key not in source
    ]


def main() -> int:
    if not WORKFLOW.exists():
        print(f"DEPLOY WORKFLOW: REFUSED ({WORKFLOW} does not exist)")
        return 2

    document = _load()
    blocks = _run_blocks(document)
    options = script_options()
    if not blocks:
        print(f"DEPLOY WORKFLOW: REFUSED ({WORKFLOW.name} has no `run:` steps to check)")
        return 2
    if not options:
        print(
            f"DEPLOY WORKFLOW: REFUSED (parsed no options out of {DEPLOY_SCRIPT.name}; "
            "its argument loop has moved and every flag would pass vacuously)"
        )
        return 2

    documented, names = check_inputs_documented(document)
    if not names:
        print(
            f"DEPLOY WORKFLOW: REFUSED ({WORKFLOW.name} references no secrets or vars; "
            "the kill switch and the deploy path are both read that way, so a file with "
            "none is one this check cannot vouch for)"
        )
        return 2

    failures = (
        check_invokes_the_script(blocks)
        + check_no_reimplementation(blocks)
        + check_flags_exist(blocks)
        + documented
        + check_run_blocks_parse(blocks)
        + check_safety_properties()
    )
    if failures:
        print("DEPLOY WORKFLOW: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        f"DEPLOY WORKFLOW: OK ({len(blocks)} run blocks, {len(options)} script options, "
        f"{len(names)} secrets/vars all documented in docs/{DEPLOYMENT_DOC.name})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
