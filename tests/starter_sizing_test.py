"""`compose.prod.yml`'s defaults are the 1 vCPU / 4 GB starter (DEPLOYMENT §2b), checked as
arithmetic rather than trusted as prose.

PRODUCTION-READINESS P5.16/P5.17 found the defaults sized for a 4 vCPU host with
`max_connections = 200`, so an operator who set nothing oversubscribed the starter's CPU
and its Postgres connections in silence. These tests read the defaults compose would use
with an empty `.env` and fail if a change to one of them breaks a budget.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import yaml
from apps.api.db.session import MAX_NESTED_CONNECTIONS
from arq.worker import Worker
from calevate_shared.config import Settings

COMPOSE = Path(__file__).resolve().parents[1] / "compose.prod.yml"

#: DEPLOYMENT §2b's starter row.
STARTER_VCPU = 1
STARTER_MAX_CONNECTIONS = 100
#: PostgreSQL's default `superuser_reserved_connections`.
SUPERUSER_RESERVED = 3
#: §2a's allowance for psql sessions, backups and the ops scripts.
OPS_CONNECTIONS = 5
#: `migrate` runs alone between build and swap, with a fixed pool.
MIGRATE_POOL = 5


def _defaults() -> dict[str, str]:
    text = COMPOSE.read_text(encoding="utf-8")
    return dict(re.findall(r"\$\{([A-Z_]+):-([^}]+)\}", text))


def test_no_service_defaults_to_more_processes_than_the_starter_has_cores() -> None:
    defaults = _defaults()
    assert int(defaults["API_WORKERS"]) <= STARTER_VCPU
    assert int(defaults["VOICE_RUNTIME_WORKERS"]) <= STARTER_VCPU


def test_the_default_pools_fit_the_starters_max_connections() -> None:
    defaults = _defaults()
    per_process_ceiling = MAX_NESTED_CONNECTIONS - 1  # the pool's overflow
    services = (
        (int(defaults["API_WORKERS"]), int(defaults["API_DB_POOL_SIZE"])),
        (int(defaults["VOICE_RUNTIME_WORKERS"]), int(defaults["VOICE_RUNTIME_DB_POOL_SIZE"])),
        (1, int(defaults["WORKERS_DB_POOL_SIZE"])),
        (1, int(defaults["WORKERS_BULK_DB_POOL_SIZE"])),
        (1, MIGRATE_POOL),
    )
    total = sum(n * (pool + per_process_ceiling) for n, pool in services) + OPS_CONNECTIONS
    assert total <= STARTER_MAX_CONNECTIONS - SUPERUSER_RESERVED, total


def test_the_worker_runs_fewer_jobs_than_it_has_pooled_connections() -> None:
    defaults = _defaults()
    assert int(defaults["WORKERS_MAX_JOBS"]) < int(defaults["WORKERS_DB_POOL_SIZE"])
    assert "WORKER_MAX_JOBS: ${WORKERS_MAX_JOBS:-" in COMPOSE.read_text(encoding="utf-8")


def test_the_bulk_worker_runs_fewer_jobs_than_it_has_pooled_connections() -> None:
    defaults = _defaults()
    assert int(defaults["WORKERS_BULK_MAX_JOBS"]) < int(defaults["WORKERS_BULK_DB_POOL_SIZE"])
    assert "WORKER_MAX_JOBS: ${WORKERS_BULK_MAX_JOBS:-" in COMPOSE.read_text(encoding="utf-8")


def test_unset_the_worker_keeps_arqs_own_concurrency() -> None:
    """Dev and tests set nothing, and must run exactly as before the knob existed."""
    arq_default = inspect.signature(Worker.__init__).parameters["max_jobs"].default
    assert Settings.model_fields["worker_max_jobs"].default == arq_default


#: The production box until five clients (founder, 29 Oct 2026): Hostinger srv1929611,
#: 1 vCPU, 3.8 GB RAM, 4 GB swap, everything on it. 3.8 GB read as 3800 MiB, the smaller
#: of the two readings.
STARTER_RAM_MIB = 3800
#: Peak RSS of importing each entrypoint, idle, no job running: `ru_maxrss` of a fresh
#: `python -c "import <entrypoint>"`, three runs each, highest kept, in the
#: python:3.12-bookworm test container (`calevate-test-venv`), 29 Oct 2026. A FLOOR, not a
#: peak: what a job adds while it runs is not measured.
MEASURED_IDLE_RSS_MIB = {
    "api": 236,  # apps.api.main, 241436 KiB
    "voice-runtime": 83,  # apps/voice-runtime/main.py, 84144 KiB
    "workers": 186,  # apps.workers.settings, 189744 KiB
    "workers-bulk": 186,  # the same module, `BulkWorkerSettings`
}
ECOSYSTEM = COMPOSE.parent / "apps" / "web" / "ecosystem.config.cjs"
DEPLOYMENT = COMPOSE.parent / "docs" / "DEPLOYMENT.md"


def _mib(value: str) -> int:
    number, unit = re.fullmatch(r"(\d+)\s*([a-zA-Z]+)", value.strip()).groups()  # type: ignore[union-attr]
    return int(number) * {"mb": 1, "m": 1, "gb": 1024, "g": 1024}[unit.lower()]


def _memory_ceilings_mib() -> dict[str, int]:
    """Each fixed memory line on the box, read from the file that sets it."""
    shared_buffers = re.search(
        r"^\| Postgres `shared_buffers` \| \*\*(\d+ MB)\*\*", DEPLOYMENT.read_text("utf-8"), re.M
    )
    pm2 = re.search(r'max_memory_restart:\s*"([^"]+)"', ECOSYSTEM.read_text("utf-8"))
    assert shared_buffers and pm2
    return {
        "postgres shared_buffers": _mib(shared_buffers.group(1)),
        "redis maxmemory": _mib(_defaults()["REDIS_MAXMEMORY"]),
        "next.js (pm2 restart ceiling)": _mib(pm2.group(1)),
    }


def test_every_resident_process_fits_the_starter_box() -> None:
    """DEPLOYMENT §2b's memory budget: the fixed ceilings plus each python service's idle
    floor must leave room for the OS, Postgres backends and running jobs. The remainder is
    what those share; swap (4 GB) is the margin, not the budget. It must at least hold
    one service's `/tmp`, which is RAM-backed while an upload is spooled there."""
    tmpfs = re.search(r"/tmp:size=(\d+m)", COMPOSE.read_text(encoding="utf-8"))
    assert tmpfs
    resident = sum(_memory_ceilings_mib().values()) + sum(MEASURED_IDLE_RSS_MIB.values())
    headroom = STARTER_RAM_MIB - resident
    assert headroom >= _mib(tmpfs.group(1)), (resident, headroom)


def test_every_compose_python_service_has_a_measured_floor() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    long_running = {name for name, svc in services.items() if "profiles" not in svc} - {"redis"}
    assert long_running == set(MEASURED_IDLE_RSS_MIB)


def test_redis_is_capped_and_never_evicts_a_queued_job() -> None:
    """arq stores each queued job as a key with a TTL, so an evicting policy could drop one."""
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"\n  redis:\n(.*?)(?=\n  [a-z][a-z0-9-]*:\n)", text, re.S)
    assert block
    assert "--maxmemory-policy\n      - noeviction" in block.group(1)
    assert "${REDIS_MAXMEMORY:-" in block.group(1)
