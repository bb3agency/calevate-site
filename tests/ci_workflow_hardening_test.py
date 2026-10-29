"""GitHub Actions hardening that a diff to a workflow can quietly undo.

* Every third-party action is pinned to a full commit SHA (OpenSSF Scorecard
  "Pinned-Dependencies"): a tag can be moved under us, a SHA cannot.
* Every `actions/checkout` sets `persist-credentials: false`, so the job token is not left
  in `.git/config` for dependency install scripts and the test suite to read (Scorecard
  "Token-Permissions", zizmor "artipacked").
* The Python advisory gate audits the hash-pinned lockfile export. The earlier
  `pip-audit --local` under `uv run --with` audited only pip-audit's own environment and
  passed a lockfile carrying a published Pillow advisory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def _steps(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


def _all_steps() -> list[tuple[str, dict[str, Any]]]:
    return [(path.name, step) for path in WORKFLOWS for step in _steps(path)]


def test_the_workflows_are_found() -> None:
    assert {"ci.yml", "deploy.yml"} <= {path.name for path in WORKFLOWS}


@pytest.mark.parametrize(
    ("workflow", "step"),
    [(name, step) for name, step in _all_steps() if "uses" in step],
    ids=lambda value: value if isinstance(value, str) else str(value.get("uses")),
)
def test_every_action_is_pinned_to_a_commit_sha(workflow: str, step: dict[str, Any]) -> None:
    uses = str(step["uses"])
    if uses.startswith(("./", "docker://")):
        return
    _, _, ref = uses.partition("@")
    assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (workflow, uses)


def test_every_checkout_drops_the_persisted_token() -> None:
    checkouts = [
        (name, step)
        for name, step in _all_steps()
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    for name, step in checkouts:
        assert (step.get("with") or {}).get("persist-credentials") is False, name


def test_python_audit_reads_the_hashed_lockfile_export() -> None:
    commands = [
        str(step.get("run", ""))
        for _, step in _all_steps()
        if "pip-audit" in str(step.get("run", ""))
    ]
    assert len(commands) == 1
    command = commands[0]
    assert "uv export --frozen" in command
    assert "--require-hashes" in command
    assert "-r " in command
    assert "pip-audit==" in command
