"""Behaviour of four `scripts/vps-deploy.sh` functions, executed in bash with stubs.

The other deploy guards read the script as text; these run the real function bodies,
lifted out of the script, against a stubbed `docker`/`compose`/`git`. What each pins:

1. A service with no HTTP health endpoint (workers) is watched after its swap. A worker
   that dies on import used to pass: `wait_healthy` returned 0 for anything without a URL,
   and `restart: unless-stopped` kept the container restarting behind a green deploy.
2. `deployed-sha` only advances when every component that changed since it is running
   HEAD. A named-component deploy used to advance it anyway, so the next `--changed` run
   diffed from a commit whose api change had never shipped and reported nothing to do.
3. A range touching the Pipecat voice worker says so, including when it is the only
   change and the deploy would otherwise print "HEAD is already live".
4. A non-revision line from `alembic current` is refused. The revision checker answers
   "absent" for any unresolvable string, and "absent" skips migrations.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vps-deploy.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _functions(*names: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    bodies = []
    for name in names:
        match = re.search(rf"^{re.escape(name)}\(\) \{{", source, re.M)
        assert match, f"{name}() is gone from vps-deploy.sh"
        end = source.index("\n}\n", match.start())
        bodies.append(source[match.start() : end + 3])
    return "\n".join(bodies)


_PRELUDE = r"""
set -Eeuo pipefail
readonly ALL_COMPONENTS=(api voice-runtime workers web nginx)
COMPOSE_PROJECT=calevate
COMPOSE_FILE=compose.prod.yml
ROOT=/nonexistent
HEALTH_ATTEMPTS=1
HEALTH_INTERVAL_S=0
SETTLE_S=0
log()  { printf '%s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*" >&2; }
die()  { printf '[abort] %s\n' "$*" >&2; exit 1; }
step() { log "$1"; }
sleep() { :; }
"""


def _run(body: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run(
        [BASH, "-s"], input=_PRELUDE + body, capture_output=True, text=True, timeout=60
    )


_HEALTH = _functions("health_url", "wait_healthy", "wait_settled")


@pytest.mark.parametrize("state", ["restarting 1", "running 3", "exited 0"])
def test_a_worker_that_is_not_staying_up_fails_its_swap(state: str) -> None:
    result = _run(
        _HEALTH
        + f"""
compose() {{ [[ "$1" == ps ]] && echo 0123456789abcdef; }}
docker() {{ echo '{state}'; }}
wait_healthy workers
echo PASSED
"""
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PASSED" not in result.stdout
    assert "not staying up" in result.stderr


def test_a_worker_with_no_container_fails_its_swap() -> None:
    result = _run(
        _HEALTH
        + """
compose() { :; }
docker() { echo 'running 0'; }
wait_healthy workers
echo PASSED
"""
    )
    assert result.returncode == 1
    assert "no container" in result.stderr


def test_a_worker_that_stays_up_passes_its_swap() -> None:
    result = _run(
        _HEALTH
        + """
compose() { [[ "$1" == ps ]] && echo 0123456789abcdef; }
docker() { echo 'running 0'; }
wait_healthy workers
echo PASSED
"""
    )
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout


_POINTER = _functions(
    "in_plan",
    "components_for_paths",
    "last_deployed_sha",
    "components_since_last_deploy",
    "record_deploy",
)

# The range old..new changes the api monolith and voice-runtime.
_GIT_STUB = r"""
git() {
  case "$*" in
    *cat-file*) return 0 ;;
    *diff*) printf 'apps/api/crm/service.py\napps/voice-runtime/main.py\n' ;;
  esac
}
STATE_DIR=$(mktemp -d)
printf 'old\n' > "$STATE_DIR/deployed-sha"
HEAD_SHA=new
MIGRATIONS_SKIPPED=0
"""


def _pointer_after(mode: str, plan: str) -> str:
    result = _run(
        _POINTER
        + _GIT_STUB
        + f"""
MODE={mode}
PLAN=({plan})
record_deploy
cat "$STATE_DIR/deployed-sha"
rm -rf "$STATE_DIR"
"""
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_a_partial_named_deploy_does_not_advance_the_pointer() -> None:
    assert _pointer_after("explicit", "voice-runtime") == "old"


def test_a_named_deploy_covering_every_change_advances_the_pointer() -> None:
    assert _pointer_after("explicit", "api voice-runtime workers") == "new"


def test_a_changed_or_all_deploy_advances_the_pointer() -> None:
    assert _pointer_after("changed", "api voice-runtime workers") == "new"
    assert _pointer_after("all", "api voice-runtime workers web nginx") == "new"


def test_a_voice_worker_only_range_warns_instead_of_reporting_everything_live() -> None:
    result = _run(
        _functions(
            "components_for_paths",
            "last_deployed_sha",
            "components_since_last_deploy",
            "voice_worker_changed_since",
            "resolve_plan",
        )
        + r"""
git() {
  case "$*" in
    *cat-file*) return 0 ;;
    *diff*) printf 'apps/voice-worker/voice_worker/pipeline.py\n' ;;
  esac
}
STATE_DIR=$(mktemp -d)
printf 'old\n' > "$STATE_DIR/deployed-sha"
MODE=changed
resolve_plan
"""
    )
    assert result.returncode == 0, result.stderr
    assert "nothing to deploy" in result.stdout
    assert "pipecat-worker-setup.sh deploy" in result.stderr


def test_an_unrelated_range_does_not_mention_the_voice_worker() -> None:
    result = _run(
        _functions("voice_worker_changed_since")
        + r"""
git() { printf 'apps/web/src/app/page.tsx\ndocs/DEPLOYMENT.md\n'; }
voice_worker_changed_since old && echo CHANGED || echo UNCHANGED
"""
    )
    assert result.stdout.strip() == "UNCHANGED"


@pytest.mark.parametrize(
    "printed",
    [
        '{"event":"x"}',
        "INFO",
        "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.",
        "f1c40d8b6e93 (head)\nunreadable",
        "custom_rev_id",
    ],
)
def test_a_line_that_is_not_a_revision_id_is_refused_not_read_as_a_rollback(
    printed: str,
) -> None:
    result = _run(
        _functions("rolling_back_onto_a_newer_database")
        + f"""
compose() {{ echo CHECKER_CALLED; return 3; }}
DB_REVISION_BEFORE=$'{printed.replace(chr(10), "\\n")}'
if rolling_back_onto_a_newer_database; then echo SKIPPED; else echo MIGRATE; fi
"""
    )
    assert result.returncode == 1, result.stdout
    assert "SKIPPED" not in result.stdout
    assert "CHECKER_CALLED" not in result.stdout


@pytest.mark.parametrize("printed", ["f1c40d8b6e93 (head)", "f1c40d8b6e93"])
def test_a_real_revision_still_reaches_the_checker(printed: str) -> None:
    result = _run(
        _functions("rolling_back_onto_a_newer_database")
        + f"""
compose() {{ return 0; }}
DB_REVISION_BEFORE='{printed}'
if rolling_back_onto_a_newer_database; then echo SKIPPED; else echo MIGRATE; fi
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "MIGRATE"


def test_every_revision_in_the_tree_has_the_shape_the_deploy_accepts() -> None:
    """A custom `--rev-id` would make every deploy refuse at the migration step; this
    catches it in CI instead."""
    versions = SCRIPT.parents[1] / "alembic" / "versions"
    ids = [
        match.group(1)
        for path in sorted(versions.glob("*.py"))
        if (
            match := re.search(
                r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']",
                path.read_text(encoding="utf-8"),
                re.M,
            )
        )
    ]
    assert ids, "no alembic revisions found"
    odd = [rev for rev in ids if not re.fullmatch(r"[0-9a-f]{12}", rev)]
    assert not odd, f"revision ids vps-deploy.sh would refuse: {odd}"
