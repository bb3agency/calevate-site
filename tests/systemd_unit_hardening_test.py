"""Every systemd service this repo installs runs sandboxed.

The units run unattended on the production host, as `postgres` (the backup chain) or as
the deploy account (hygiene). systemd.exec(5) sandboxing is the CIS / systemd-analyze
`security` baseline for such a unit: no privilege gain through setuid binaries
(`NoNewPrivileges`), a private /tmp (`PrivateTmp`), and a read-only /usr, /boot and /etc
(`ProtectSystem`).

`PrivateTmp` is load-bearing beside `ProtectSystem=strict`, which mounts /tmp read-only:
without it the offsite dump's `mktemp -d` read-back fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES = sorted(
    [
        *(REPO_ROOT / "infra" / "backup" / "systemd").glob("*.service"),
        *(REPO_ROOT / "infra" / "hygiene" / "systemd").glob("*.service"),
    ]
)


def _service_settings(path: Path) -> dict[str, str]:
    """The `[Service]` section's `Key=value` lines, last assignment winning (as systemd)."""
    settings: dict[str, str] = {}
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        header = re.fullmatch(r"\[(\w+)\]", line)
        if header:
            section = header.group(1)
            continue
        if section == "Service" and "=" in line:
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip()
    return settings


def test_the_unit_set_is_found() -> None:
    names = {path.name for path in SERVICES}
    assert {
        "calevate-backup-alert@.service",
        "calevate-backup-health.service",
        "calevate-basebackup.service",
        "calevate-dump-offsite.service",
        "calevate-hygiene.service",
    } <= names


@pytest.mark.parametrize("unit", SERVICES, ids=lambda path: path.name)
def test_service_is_sandboxed(unit: Path) -> None:
    settings = _service_settings(unit)
    assert settings.get("User") not in (None, "", "root")
    assert settings.get("NoNewPrivileges") == "yes"
    assert settings.get("PrivateTmp") == "yes"
    assert settings.get("ProtectSystem") in ("full", "strict")


@pytest.mark.parametrize("unit", SERVICES, ids=lambda path: path.name)
def test_strict_filesystem_still_has_a_writable_tmp(unit: Path) -> None:
    settings = _service_settings(unit)
    if settings.get("ProtectSystem") == "strict":
        assert settings.get("PrivateTmp") == "yes"
        assert settings.get("ReadWritePaths")
