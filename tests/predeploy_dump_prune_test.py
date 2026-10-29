"""Pre-deploy pg_dumps are pruned to the newest 5 or the last 14 days, never fewer."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from tests.platform_support import requires_posix_shell

REPO_ROOT = Path(__file__).resolve().parents[1]
PRUNE = REPO_ROOT / "scripts" / "backup" / "prune-predeploy-dumps.sh"
DAY = 86400


def _dumps(directory: Path, ages_days: list[int]) -> list[Path]:
    now = time.time()
    paths = []
    for i, age in enumerate(ages_days):
        path = directory / f"pre-{i:02d}.dump"
        path.write_bytes(b"x")
        os.utime(path, (now - age * DAY, now - age * DAY))
        paths.append(path)
    return paths


def _prune(directory: Path, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = directory.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "logger").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "logger").chmod(0o755)
    full_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PREDEPLOY_DUMP_DIR": str(directory),
        **env,
    }
    return subprocess.run(
        ["bash", str(PRUNE)], capture_output=True, text=True, env=full_env, timeout=60
    )


@requires_posix_shell
def test_old_dumps_beyond_the_newest_five_are_deleted(tmp_path: Path) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    paths = _dumps(folder, [1, 3, 20, 25, 30, 40, 50, 60])
    proc = _prune(folder)
    assert proc.returncode == 0, proc.stderr
    survivors = sorted(p.name for p in folder.iterdir())
    assert survivors == sorted(p.name for p in paths[:5])
    assert "deleted=3" in proc.stdout


@requires_posix_shell
def test_recent_dumps_are_kept_even_beyond_five(tmp_path: Path) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    _dumps(folder, [1, 2, 3, 4, 5, 6, 7, 8])
    proc = _prune(folder)
    assert proc.returncode == 0, proc.stderr
    assert len(list(folder.iterdir())) == 8


@requires_posix_shell
def test_a_quiet_fortnight_never_leaves_fewer_than_five(tmp_path: Path) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    _dumps(folder, [30, 31, 32, 33, 34, 35])
    proc = _prune(folder)
    assert proc.returncode == 0, proc.stderr
    assert len(list(folder.iterdir())) == 5


@requires_posix_shell
def test_only_dump_files_are_touched(tmp_path: Path) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    _dumps(folder, [40, 41, 42, 43, 44, 45, 46])
    keep = folder / "notes.txt"
    keep.write_text("keep me")
    os.utime(keep, (time.time() - 90 * DAY, time.time() - 90 * DAY))
    proc = _prune(folder)
    assert proc.returncode == 0, proc.stderr
    assert keep.exists()


@requires_posix_shell
def test_a_missing_directory_is_nothing_to_do(tmp_path: Path) -> None:
    proc = _prune(tmp_path / "absent")
    assert proc.returncode == 0, proc.stderr


@requires_posix_shell
def test_a_non_numeric_setting_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "dumps"
    folder.mkdir()
    _dumps(folder, [40, 41, 42, 43, 44, 45, 46])
    proc = _prune(folder, PREDEPLOY_DUMP_KEEP_LAST="five")
    assert proc.returncode == 2
    assert len(list(folder.iterdir())) == 7
