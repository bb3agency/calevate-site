"""`calevate-nginx-apply` reads staged files as the deploy account, after validation.

The script validates each staged file (regular, not a symlink) and used to hand the
staged PATH to `install` later. The deploy account owns the staging directory, so it could
swap a validated file for a symlink in between, and root's `install` would follow it into
/etc/nginx at mode 0644. The fix copies every staged file into a root-only snapshot by
running `cat` through `runuser -u <deploy account>`, and installs only from the snapshot.

The real script needs root, `runuser` and nginx, so this runs the snapshot block itself
with `runuser` stubbed to model the one property it contributes: the read happens with the
deploy account's permissions (here, "may read only inside the staging tree").
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "infra" / "privileged" / "sbin" / "calevate-nginx-apply"
)
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _snapshot_block() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.find("# --- snapshot the staged files AS THE DEPLOY ACCOUNT")
    assert start >= 0, "the snapshot step is gone from calevate-nginx-apply"
    end = source.index("# --- back up what is about to be overwritten", start)
    return source[start:end]


_HARNESS = r"""
set -Eeuo pipefail
die() { printf '[abort] %s\n' "$*" >&2; exit 1; }
DEPLOY_USER=calevate
work=$(mktemp -d)
mkdir -p "$work/staging/conf.d" "$work/root-only"
printf 'server {}\n' > "$work/staging/conf.d/site.conf"
printf 'root:secret\n' > "$work/root-only/shadow"
ALLOWED="$work/staging"
# The deploy account may read the staging tree and nothing else.
runuser() {
  [[ "$1 $2 $3" == "-u calevate --" ]] || { echo "unexpected runuser argv: $*" >&2; return 2; }
  shift 3
  local target
  target=$(readlink -f "$3")
  [[ "$target" == "$ALLOWED"/* ]] || { echo "cat: $3: Permission denied" >&2; return 1; }
  "$@"
}
sources=("$work/staging/conf.d/site.conf")
# Validation has passed. What happens next is the race.
SWAP
"""


def _run(swap: str, tail: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    script = _HARNESS.replace("SWAP", swap) + _snapshot_block() + tail
    return subprocess.run([BASH, "-s"], input=script, capture_output=True, text=True, timeout=60)


def test_install_reads_a_snapshot_not_the_staged_path() -> None:
    result = _run(
        ":",
        r"""
[[ "${sources[0]}" != "$work/staging/"* ]] || { echo "STILL STAGED PATH"; exit 3; }
cat "${sources[0]}"
""",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "server {}"


def test_a_symlink_swapped_in_after_validation_is_refused() -> None:
    result = _run(
        r"""rm "$work/staging/conf.d/site.conf"
ln -s "$work/root-only/shadow" "$work/staging/conf.d/site.conf"
[[ -L "$work/staging/conf.d/site.conf" ]] || exit 77""",
        '\necho "INSTALLED FROM ${sources[0]}"; cat "${sources[0]}"\n',
    )
    if result.returncode == 77:
        pytest.skip("this bash's `ln -s` copies instead of linking (Git for Windows)")
    assert result.returncode == 1, result.stdout
    assert "INSTALLED" not in result.stdout
    assert "root:secret" not in result.stdout + result.stderr
    assert "could not read staged file" in result.stderr


def test_the_script_installs_from_the_array_the_snapshot_rewrites() -> None:
    """The snapshot only helps if `install_all` reads `sources` after it is rewritten."""
    source = SCRIPT.read_text(encoding="utf-8")
    snapshot_at = source.index("# --- snapshot the staged files AS THE DEPLOY ACCOUNT")
    install_at = source.index("install_all() {")
    assert snapshot_at < install_at
    assert re.search(r'install -o root -g root -m 0644 "\$\{sources\[\$index\]\}"', source)
