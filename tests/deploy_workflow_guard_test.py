"""Negative controls for `scripts/check_deploy_workflow.py`.

Same doctrine as `tests/guardrail_audit_test.py`: WIRING (the check is pointed at the real
workflow and the real script, so a check that has become disconnected fails here) plus
DETECTION (take those real artefacts, apply ONE minimal mutation that is exactly the
violation claimed, assert it is reported). Mutating reality rather than inventing a fixture
is what keeps the mutation meaningful.

The mutations are applied by monkeypatching the module's three path constants at a copied
tree, never by editing the repo.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts import check_deploy_workflow as guard

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the three real artefacts, with the guard pointed at it."""
    workflow = tmp_path / "deploy.yml"
    script = tmp_path / "vps-deploy.sh"
    doc = tmp_path / "DEPLOYMENT.md"
    shutil.copy(guard.WORKFLOW, workflow)
    shutil.copy(guard.DEPLOY_SCRIPT, script)
    shutil.copy(guard.DEPLOYMENT_DOC, doc)
    monkeypatch.setattr(guard, "WORKFLOW", workflow)
    monkeypatch.setattr(guard, "DEPLOY_SCRIPT", script)
    monkeypatch.setattr(guard, "DEPLOYMENT_DOC", doc)
    return tmp_path


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"the anchor this mutation keys on has moved: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# --- wiring -------------------------------------------------------------------


def test_the_live_tree_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main() == 0
    assert "DEPLOY WORKFLOW: OK" in capsys.readouterr().out


def test_it_reads_the_real_script_options() -> None:
    """If the argument loop moves, `check_flags_exist` would pass vacuously — so the
    wiring is asserted against options the script demonstrably has."""
    options = guard.script_options()
    assert {"--expected-sha", "--checkout", "--dry-run", "--all"} <= options


def test_it_finds_the_real_run_blocks() -> None:
    blocks = guard._run_blocks(guard._load())
    assert len(blocks) >= 2
    assert any(guard.SCRIPT_MARKER in body for _, body in blocks)


# --- detection ----------------------------------------------------------------


def test_catches_a_workflow_that_stopped_calling_the_script(tree: Path) -> None:
    """Note WHICH occurrence is removed: the preflight step still names the script inside
    an `[[ ! -x ... ]]` test, so this also pins that a workflow which merely checks the
    script exists — and then deploys some other way — does not satisfy the check."""
    _edit(
        tree / "deploy.yml",
        '          "$VPS_CLIENT_PATH/scripts/vps-deploy.sh" "${args[@]}"',
        "          true  # was the deploy",
    )
    failures = guard.check_invokes_the_script(guard._run_blocks(guard._load()))
    assert failures and "runs scripts/vps-deploy.sh" in failures[0]


@pytest.mark.parametrize(
    ("injected", "expected"),
    [
        ("docker compose -f compose.prod.yml up -d api", "docker"),
        ("uv run alembic upgrade head", "alembic"),
        ('git -C "$VPS_CLIENT_PATH" checkout main', "git"),
        ("pm2 reload calevate-web", "pm2"),
        ("sudo systemctl reload nginx", "systemctl"),
    ],
)
def test_catches_a_step_of_the_script_reimplemented_in_the_workflow(
    tree: Path, injected: str, expected: str
) -> None:
    """The one that matters. Each of these is a real step of `vps-deploy.sh` with an
    ordering argument written beside it; a copy here is a second ordering, and the
    `git checkout` case is the exact shape the reference implementation ships."""
    _edit(
        tree / "deploy.yml",
        '          set -euo pipefail\n          if [[ -n "${ROLLBACK_SHA:-}" ]]',
        f"          set -euo pipefail\n          {injected}\n"
        '          if [[ -n "${ROLLBACK_SHA:-}" ]]',
    )
    failures = guard.check_no_reimplementation(guard._run_blocks(guard._load()))
    assert failures, f"{injected!r} was not reported"
    assert expected in failures[0]


def test_a_printed_command_is_not_a_reimplementation(tree: Path) -> None:
    """The control on the mutation above: a deploy step that TELLS the operator to run
    `git checkout main` is doing the right thing, and a check that forbade it would push
    workflows towards giving no instructions."""
    _edit(
        tree / "deploy.yml",
        '          set -euo pipefail\n          if [[ -n "${ROLLBACK_SHA:-}" ]]',
        '          set -euo pipefail\n          echo "then run: git checkout main"\n'
        '          if [[ -n "${ROLLBACK_SHA:-}" ]]',
    )
    assert guard.check_no_reimplementation(guard._run_blocks(guard._load())) == []


def test_catches_a_flag_the_script_no_longer_parses(tree: Path) -> None:
    """Drift in the direction it actually happens: the SCRIPT is renamed and the
    workflow is not."""
    _edit(tree / "vps-deploy.sh", "--expected-sha) EXPECTED_SHA=", "--require-sha) EXPECTED_SHA=")
    failures = guard.check_flags_exist(guard._run_blocks(guard._load()))
    assert failures and "--expected-sha" in failures[0]


def test_catches_a_flag_invented_in_the_workflow(tree: Path) -> None:
    _edit(tree / "deploy.yml", "args+=(--dry-run)", "args+=(--dry-run --force-rebuild)")
    failures = guard.check_flags_exist(guard._run_blocks(guard._load()))
    assert failures and "--force-rebuild" in failures[0]


def test_catches_an_undocumented_secret(tree: Path) -> None:
    _edit(tree / "deploy.yml", "secrets.VPS_CLIENT_PATH", "secrets.VPS_DEPLOY_TOKEN")
    failures, names = guard.check_inputs_documented(guard._load())
    assert "VPS_DEPLOY_TOKEN" in names
    assert failures and "VPS_DEPLOY_TOKEN" in failures[0]


def test_catches_a_run_block_that_does_not_parse(tree: Path) -> None:
    _edit(
        tree / "deploy.yml",
        'if [[ -n "${ROLLBACK_SHA:-}" ]]; then',
        'if [[ -n "${ROLLBACK_SHA:-}"; then',
    )
    failures = guard.check_run_blocks_parse(guard._run_blocks(guard._load()))
    assert failures and "not valid bash" in failures[0]


@pytest.mark.parametrize("removed", [key for key, _ in guard.SAFETY_PROPERTIES])
def test_catches_a_deleted_safety_property(tree: Path, removed: str) -> None:
    _edit(tree / "deploy.yml", removed, "true")
    failures = guard.check_safety_properties()
    assert failures and removed in failures[0]


# --- refusals -----------------------------------------------------------------


def test_refuses_when_the_workflow_is_gone(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / "deploy.yml").unlink()
    assert guard.main() == 2
    assert "REFUSED" in capsys.readouterr().out


def test_refuses_when_the_scripts_argument_loop_has_moved(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure mode this whole pack is written against: a scan that matches nothing
    and reports OK. Without the refusal, every flag in the workflow would be vacuously
    valid the moment the `case` block is reshaped."""
    _edit(tree / "vps-deploy.sh", "while [[ $# -gt 0 ]]; do", "while (( $# )); do")
    assert guard.script_options() == set()
    assert guard.main() == 2
    assert "parsed no options" in capsys.readouterr().out


def test_refuses_a_workflow_that_reads_no_secrets_or_vars(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tree / "deploy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("secrets.", "x.").replace("vars.", "y."),
        encoding="utf-8",
    )
    assert guard.main() == 2
    assert "references no secrets or vars" in capsys.readouterr().out
