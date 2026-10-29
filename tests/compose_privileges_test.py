"""The production app containers cannot regain privileges they were started without.

FAILS IF: an api, voice-runtime, workers or migrate container keeps Docker's default
capability bounding set, or may gain privileges through a setuid binary (CIS Docker
Benchmark 5.3 and 5.25), or runs with a writable root filesystem or an unbounded /tmp
(5.12).
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE_PROD = Path(__file__).resolve().parent.parent / "compose.prod.yml"
APP_SERVICES = ("api", "voice-runtime", "workers", "workers-bulk", "migrate")


def test_every_app_service_drops_capabilities_and_forbids_escalation() -> None:
    services = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))["services"]
    for name in APP_SERVICES:
        service = services[name]
        assert service.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert "cap_add" not in service, name
        assert service.get("privileged") is not True, name


def test_every_app_service_runs_on_a_read_only_root_with_a_bounded_tmp() -> None:
    services = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))["services"]
    for name in APP_SERVICES:
        service = services[name]
        assert service.get("read_only") is True, name
        tmpfs = service.get("tmpfs", [])
        assert any(entry.startswith("/tmp:") and "size=" in entry for entry in tmpfs), name
