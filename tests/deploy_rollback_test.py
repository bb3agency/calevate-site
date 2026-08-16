"""The rollback path: `scripts/deploy_revision_check`, and the deploy's use of it.

**What was wrong.** `runbooks/deploy-failed.md` §4 and the deploy's own summary banner both
give the rollback as `git checkout <previous-sha>` then `vps-deploy.sh --all --no-pull`.
`--all` puts the python services in the plan, so migrations run — `alembic upgrade head`
from the OLDER image. If the deploy being rolled back carried a migration, the database is
at a revision that image has no script for, and alembic resolves the stored
`alembic_version` against its script directory before computing any path. Reproduced
against the installed alembic:

    FAILED: Can't locate revision identified by 'deadbeefcafe'        (exit 255)

So the rollback died before swapping a single container, in exactly the incident it exists
for, with production still on the broken release.

**Why an exit code and not a message.** The caller is bash and the two answers it must tell
apart are "the database is ahead of this artefact" (skip the migration; this is a rollback)
and "the check could not run" (do not skip anything). Reading the second as the first would
swap NEW code onto an OLD schema — the one direction hard rule 8 does not protect, and the
only genuinely unsafe outcome available here. Matching alembic's message text would make
that distinction depend on vendor wording, so the contract is `0` / `3` / anything-else,
and every failure path in the checker falls towards "anything else".

This file pins both halves: the checker's own answers, and the fact that the deploy script
still consumes them that way. The second half is a text assertion over bash, which is a
weak instrument — it is here because the alternative is no coverage at all on the artefact
that puts this system in production, and because the exact failure it guards against
(somebody "simplifying" the case statement to `if ! …; then skip`) is a one-line edit.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "vps-deploy.sh"
ALEMBIC_VERSIONS = REPO_ROOT / "alembic" / "versions"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.deploy_revision_check", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _a_real_revision() -> str:
    """Any revision id in this tree — read from the versions directory, not hardcoded.

    A hardcoded id would make this test fail the day that migration is squashed, which is
    a maintenance cost with no safety in it.
    """
    for path in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        match = re.search(
            r"^revision(?::\s*str)?\s*=\s*[\"']([0-9a-f]+)[\"']", path.read_text(), re.M
        )
        if match:
            return match.group(1)
    raise AssertionError("no alembic revision found to test against")


def test_a_revision_this_image_contains_is_present() -> None:
    assert _run(_a_real_revision()).returncode == 0


def test_a_revision_this_image_does_not_contain_is_absent_and_says_so_with_3() -> None:
    """3, specifically. The deploy skips migrations on this and on nothing else."""
    assert _run("deadbeefcafe").returncode == 3


def test_no_argument_is_unanswerable_rather_than_absent() -> None:
    """A usage error must never read as "the database is ahead"."""
    for argv in ([], [""], ["a", "b"]):
        assert _run(*argv).returncode == 2, argv


def test_the_checker_needs_no_database() -> None:
    """It reads the script directory only.

    That is what lets `run_migrations` ask the question BEFORE the migrate container opens
    a connection, and it means a database that is merely unreachable cannot be mistaken for
    a database that is ahead.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.deploy_revision_check", _a_real_revision()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            # Pointed at a closed port: if anything here connected, this would not be 0.
            "DATABASE_URL": "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing",
            "ALEMBIC_DATABASE_URL": "postgresql+psycopg://nobody:nobody@127.0.0.1:1/nothing",
        },
    )
    assert result.returncode == 0, result.stderr


def test_the_deploy_script_skips_only_on_a_clean_3() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "scripts.deploy_revision_check" in script, (
        "vps-deploy.sh no longer asks whether the database is ahead of this image. Without "
        "it, `--all --no-pull` on a previous commit — the documented rollback — dies at "
        "`alembic upgrade head` before swapping a container."
    )
    # The three arms, in the one `case` that reads the checker's exit code.
    verdict = re.search(r"case \"\$verdict\" in(.+?)esac", script, re.S)
    assert verdict, "the exit-code case statement is gone"
    body = verdict.group(1)
    assert re.search(r"^\s*0\)\s*return 1", body, re.M), "exit 0 must NOT skip migrations"
    assert re.search(r"^\s*3\)", body, re.M), "exit 3 is the only skip"
    assert re.search(r"^\s*\*\)\s*die", body, re.M), (
        "an unrecognised exit code must abort the deploy. Treating it as a rollback would "
        "skip a migration this release needs and swap new code onto an old schema."
    )


def test_the_operator_facing_documents_describe_the_behaviour_the_script_has() -> None:
    """Three documents tell an operator to run that rollback; all three must know it works.

    Same shape as `tests/migration_transaction_scope_test.py`: when a mechanism's whole
    value is that the runbook is true at 3am, the runbook is part of the mechanism.
    """
    for relative in ("docs/DEPLOYMENT.md", "runbooks/deploy-failed.md", "scripts/vps-deploy.sh"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "MIGRATIONS SKIPPED" in text or "skipped-rollback" in text, (
            f"{relative} describes the rollback but not the fact that the migration step "
            "recognises it and stands down. A reader who does not know that will read the "
            "yellow banner as a failure and start improvising."
        )


def test_the_image_tag_is_per_commit_so_a_rollback_has_something_to_land_on() -> None:
    """`compose.prod.yml` reads `CALEVATE_IMAGE_TAG`; something must set it.

    While nothing did, every build overwrote one mutable `:local` tag: a rollback had no
    artefact and meant a full serial rebuild on a degraded host, and an api-only build
    replaced the image `voice-runtime` would use at its next recreate — hard rule 3 holding
    at the container level and not at the artefact level.
    """
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"export CALEVATE_IMAGE_TAG=", script), (
        "nothing sets CALEVATE_IMAGE_TAG, so compose.prod.yml falls back to `:local`"
    )
    assert "${HEAD_SHA:0:12}" in script, "the tag must identify the commit"
    compose = (REPO_ROOT / "compose.prod.yml").read_text(encoding="utf-8")
    assert "${CALEVATE_IMAGE_TAG:-local}" in compose, "compose stopped reading the tag"
