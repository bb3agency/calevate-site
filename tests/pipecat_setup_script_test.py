"""`scripts/deploy/pipecat-worker-setup.sh`, run in bash with its commands stubbed.

Three behaviours:

1. `secrets`: Ctrl-C or SIGTERM ends the run with 130/143 and removes the temp secrets
   file. The trap used to clean up and RETURN, so bash went back to prompting after the
   file it was writing into had been deleted.
2. `sources` never runs `psql` with the deploy `.env`'s DSN as an argument, which put the
   database password in the process table. It prints the query instead.
3. `digest` reads the manifest list with jq, a DEPLOYMENT §2 host prerequisite, instead of
   python3. The fixture follows the OCI image index shape (`manifests[].platform.os`,
   `.architecture`, `.digest`), https://github.com/opencontainers/image-spec/blob/main/image-index.md.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy" / "pipecat-worker-setup.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _functions(*names: str) -> str:
    source = _source()
    bodies = []
    for name in names:
        match = re.search(rf"^{re.escape(name)}\(\) \{{", source, re.M)
        assert match, f"{name}() is gone from pipecat-worker-setup.sh"
        end = source.index("\n}\n", match.start())
        bodies.append(source[match.start() : end + 3])
    return "\n".join(bodies)


def _env_contract() -> str:
    source = _source()
    start = source.index("readonly ENV_CONTRACT=(")
    end = source.index("\n)\n", start)
    return source[start : end + 3]


_PRELUDE = r"""
set -euo pipefail
rule() { :; }
ok()   { printf 'OK %s\n' "$*"; }
bad()  { printf 'FAIL %s\n' "$*"; }
warn() { printf 'NOTE %s\n' "$*"; }
die()  { bad "$*"; exit 1; }
"""


def _run(body: str, **kwargs: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run(
        [BASH, "-s"], input=_PRELUDE + body, capture_output=True, text=True, timeout=60, **kwargs
    )


@pytest.mark.parametrize(("signal", "code"), [("INT", 130), ("TERM", 143)])
def test_a_signal_during_the_prompts_exits_and_removes_the_secrets_file(
    signal: str, code: int
) -> None:
    result = _run(
        _env_contract()
        + _functions("prefill_key", "tail4", "secrets_cmd")
        + f"""
export TMPDIR=$(mktemp -d)
have() {{ return 0; }}
manifest_value() {{ echo calevate-pipecat-worker-secrets; }}
require_cli_shape() {{ :; }}
env_file_value() {{ return 1; }}
pipecat() {{ echo SENT; }}
say() {{
  printf '%s\\n' "$*"
  if [[ "$*" == *PIPECAT_WORKER_API_TOKEN* && "$*" == *required* ]]; then
    kill -{signal} $BASHPID
  fi
}}
trap 'ls -A "$TMPDIR" | sed "s/^/LEFT: /"' EXIT
set +e
( set -e; secrets_cmd <<<$'https://api.example.test\\n' ); rc=$?
set -e
echo "RC=$rc"
"""
    )
    assert f"RC={code}" in result.stdout, result.stdout + result.stderr
    assert "SENT" not in result.stdout
    assert "LEFT:" not in result.stdout, "the temp secrets directory survived the signal"


def test_sources_never_hands_the_database_dsn_to_psql() -> None:
    result = _run(
        _env_contract()
        + _functions("env_file_value", "prefill_key", "tail4", "sources_cmd")
        + r"""
ENV_FILE=$(mktemp)
DSN=postgresql+psycopg://calevate_app:hunter2-not-real@host.docker.internal:5432/calevate
printf 'DATABASE_URL=%s\n' "$DSN" > "$ENV_FILE"
have() { return 0; }
psql() { echo "PSQL_CALLED $*"; }
say() { printf '%s\n' "$*"; }
sources_cmd
rm -f "$ENV_FILE"
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PSQL_CALLED" not in result.stdout
    assert "hunter2-not-real" not in result.stdout + result.stderr
    assert "FROM platform_secrets" in result.stdout


_INDEX = {
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + "a" * 64,
            "platform": {"os": "linux", "architecture": "amd64"},
        },
        {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + "b" * 64,
            "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"},
        },
        {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + "c" * 64,
        },
    ],
}


def _digest(index: object, arch: str = "arm64") -> subprocess.CompletedProcess[str]:
    raw = (index if isinstance(index, str) else json.dumps(index)).replace("'", "")
    return _run(
        _functions("digest_cmd")
        + f"""
PIPECAT_TARGET_ARCH={arch}
TARGET_PLATFORM=linux/{arch}
REPO_ROOT=/nonexistent
have() {{ command -v "$1" >/dev/null 2>&1; }}
python3() {{ echo PYTHON_CALLED >&2; return 1; }}
docker() {{ printf '%s' '{raw}'; }}
dockerfile_base() {{ echo dailyco/pipecat-base@sha256:{"b" * 64}; }}
say() {{ printf '%s\\n' "$*"; }}
digest_cmd dailyco/pipecat-base latest
"""
    )


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


@needs_jq
def test_digest_picks_the_linux_arm64_entry_with_jq() -> None:
    result = _digest(_INDEX)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"dailyco/pipecat-base@sha256:{'b' * 64}" in result.stdout
    assert "already pins exactly this digest" in result.stdout
    assert "PYTHON_CALLED" not in result.stderr


@needs_jq
def test_digest_refuses_an_index_with_no_entry_for_the_platform() -> None:
    result = _digest(_INDEX, arch="s390x")
    assert result.returncode == 1
    assert "publishes no linux/s390x image" in result.stdout


@needs_jq
def test_digest_refuses_output_that_is_not_json() -> None:
    result = _digest("not json at all")
    assert result.returncode == 1
    assert "could not parse the manifest list" in result.stdout
