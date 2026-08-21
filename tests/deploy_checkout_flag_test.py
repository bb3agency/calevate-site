"""`vps-deploy.sh --checkout <sha>` — the rollback path, driven against a real git tree.

**Why this exists.** The rollback used to be two commands: `git checkout <previous-sha>`
then `vps-deploy.sh --all --no-pull`. That is fine for a human at a keyboard and wrong for
a caller, and `.github/workflows/deploy.yml` is now a caller — a `workflow_dispatch` with a
commit sha is the only rollback anybody can reach without SSH. A workflow that did its own
`git checkout` would be a second place that knows how to move the deploy checkout, i.e. the
drift `scripts/check_deploy_workflow.py` exists to refuse.

So the knowledge moved into the script as one flag, and the two properties that make it
safe are asserted here against a REAL repository rather than by reading the source:

1. `--checkout <sha>` fetches, moves the working tree to exactly that commit, and leaves it
   detached — no matter what the branch tip is.
2. A subsequent ordinary deploy (the pull path) REFUSES from that detached state instead of
   pulling straight back to the tip, which would silently undo the rollback the moment CI
   next went green.

The script is driven with `--dry-run api`, so it stops after the plan is resolved: no
build, no migration, no container. `docker` is stubbed on `PATH` so the test needs no
daemon and cannot touch one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.platform_support import requires_posix_shell

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def deploy_host(tmp_path: Path) -> Path:
    """A throwaway `/var/www/calevate`: a clone with an origin, two commits, and the
    files `preflight` refuses without.

    A clone rather than a fixture directory because `--checkout` runs `git fetch origin`
    and the detached-HEAD refusal reads `git symbolic-ref HEAD` — neither is meaningful
    without a real remote.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    root = tmp_path / "calevate"
    subprocess.run(["git", "clone", "-q", str(origin), str(root)], check=True)
    _git(root, "config", "user.email", "deploy@example.invalid")
    _git(root, "config", "user.name", "deploy")
    _git(root, "checkout", "-q", "-B", "main")

    for name in ("compose.prod.yml", "Dockerfile", "docker-compose.yml"):
        shutil.copy(REPO_ROOT / name, root / name)
    shutil.copytree(REPO_ROOT / "scripts" / "deploy", root / "scripts" / "deploy")
    shutil.copy(REPO_ROOT / "scripts" / "vps-deploy.sh", root / "scripts" / "vps-deploy.sh")
    shutil.copytree(REPO_ROOT / "infra" / "nginx", root / "infra" / "nginx")

    # Presence only — `preflight` greps these three names and never reads a value.
    (root / ".env").write_text("AWS_ACCESS_KEY_ID=x\nAWS_SECRET_ACCESS_KEY=y\nPLATFORM_KEK=z\n")
    (root / ".env").chmod(0o600)

    (root / "apps" / "api").mkdir(parents=True)
    (root / "apps" / "api" / "marker.py").write_text("first\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    (root / "apps" / "api" / "marker.py").write_text("second\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "second")
    _git(root, "push", "-q", "origin", "main")
    return root


@pytest.fixture
def stub_path(tmp_path: Path) -> str:
    """`PATH` with a fake `docker` in front. `preflight` runs `docker compose version`
    and `sweep_tombstones` runs `docker ps` — neither is reached by a dry run, but the
    version probe is, and a test of git behaviour must not depend on a daemon."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "compose" && "$2" == "version" ]]; then\n'
        '  echo "Docker Compose version v2.30.0"; exit 0\n'
        "fi\n"
        "exit 0\n"
    )
    docker.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def _deploy(root: Path, stub_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / "vps-deploy.sh"), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": stub_path,
            "VPS_CLIENT_PATH": str(root),
            # Keep every side effect inside tmp_path: the host lock and the deploy state
            # both default to paths a real host owns.
            "CALEVATE_HOST_LOCK": str(root / ".host-lock"),
            "CALEVATE_DEPLOY_STATE": str(root / ".deploy-state"),
        },
    )


@requires_posix_shell
def test_checkout_moves_the_tree_to_that_commit_and_detaches(
    deploy_host: Path, stub_path: str
) -> None:
    tip = _git(deploy_host, "rev-parse", "HEAD")
    previous = _git(deploy_host, "rev-parse", "HEAD~1")
    assert previous != tip

    result = _deploy(deploy_host, stub_path, "--checkout", previous, "--dry-run", "api")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(deploy_host, "rev-parse", "HEAD") == previous, (
        "the deploy did not move the checkout, so a rollback dispatched from the workflow "
        "would have redeployed the commit it was rolling away from"
    )
    assert (
        subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"], cwd=deploy_host, capture_output=True
        ).returncode
        != 0
    ), (
        "the tree must be detached — being on `main` at an older commit is a tree that "
        "the next `git pull` silently fast-forwards"
    )
    assert f"would deploy [api] at {previous}" in result.stdout


@requires_posix_shell
def test_an_ordinary_deploy_refuses_from_a_rolled_back_tree(
    deploy_host: Path, stub_path: str
) -> None:
    """The other half. Without this the FIRST green CI after a rollback pulls the tree
    back to the tip and redeploys the release that was rolled back — automatically, with
    nobody deciding it."""
    previous = _git(deploy_host, "rev-parse", "HEAD~1")
    _deploy(deploy_host, stub_path, "--checkout", previous, "--dry-run", "api")

    result = _deploy(deploy_host, stub_path, "--dry-run", "api")

    assert result.returncode != 0
    assert "detached" in result.stderr
    assert "--checkout <sha> --all" in result.stderr, "the refusal must name the way forward"
    assert "checkout main" in result.stderr, "and the way back to automatic deploys"
    assert _git(deploy_host, "rev-parse", "HEAD") == previous, (
        "the refusal must happen before anything moves"
    )


@requires_posix_shell
def test_a_ref_is_not_a_commit(deploy_host: Path, stub_path: str) -> None:
    """`--checkout main` would deploy whatever the branch points at when the line runs,
    which is the ambiguity `--expected-sha` exists to remove."""
    result = _deploy(deploy_host, stub_path, "--checkout", "main", "--dry-run", "api")
    assert result.returncode != 0
    assert "not 'main'" in result.stderr


@requires_posix_shell
def test_an_unknown_commit_aborts_rather_than_deploying_the_tip(
    deploy_host: Path, stub_path: str
) -> None:
    tip = _git(deploy_host, "rev-parse", "HEAD")
    result = _deploy(deploy_host, stub_path, "--checkout", "0" * 40, "--dry-run", "api")
    assert result.returncode != 0
    assert "is not a commit in this checkout" in result.stderr
    assert _git(deploy_host, "rev-parse", "HEAD") == tip
