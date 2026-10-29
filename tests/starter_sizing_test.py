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
        (1, MIGRATE_POOL),
    )
    total = sum(n * (pool + per_process_ceiling) for n, pool in services) + OPS_CONNECTIONS
    assert total <= STARTER_MAX_CONNECTIONS - SUPERUSER_RESERVED, total


def test_the_worker_runs_fewer_jobs_than_it_has_pooled_connections() -> None:
    defaults = _defaults()
    assert int(defaults["WORKERS_MAX_JOBS"]) < int(defaults["WORKERS_DB_POOL_SIZE"])
    assert "WORKER_MAX_JOBS: ${WORKERS_MAX_JOBS:-" in COMPOSE.read_text(encoding="utf-8")


def test_unset_the_worker_keeps_arqs_own_concurrency() -> None:
    """Dev and tests set nothing, and must run exactly as before the knob existed."""
    arq_default = inspect.signature(Worker.__init__).parameters["max_jobs"].default
    assert Settings.model_fields["worker_max_jobs"].default == arq_default


def test_redis_is_capped_and_never_evicts_a_queued_job() -> None:
    """arq stores each queued job as a key with a TTL, so an evicting policy could drop one."""
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(r"\n  redis:\n(.*?)(?=\n  [a-z][a-z0-9-]*:\n)", text, re.S)
    assert block
    assert "--maxmemory-policy\n      - noeviction" in block.group(1)
    assert "${REDIS_MAXMEMORY:-" in block.group(1)


#: DEPLOYMENT §2b's starter row, in MB.
STARTER_RAM_MB = 4096
STARTER_SHARED_BUFFERS_MB = 768
STARTER_REDIS_MAXMEMORY_MB = 256


def _megabytes(value: str) -> int:
    match = re.fullmatch(r"(\d+)([mg])b?", value.lower())
    assert match is not None, value
    number, unit = match.groups()
    return int(number) * (1024 if unit == "g" else 1)


def test_the_worker_has_a_memory_ceiling_inside_what_the_starter_can_spare() -> None:
    """Without a ceiling a ballooning job is the host OOM killer's problem, and its pick
    can be Postgres."""
    text = COMPOSE.read_text(encoding="utf-8")
    workers = text.split("\n  workers:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "mem_limit: ${WORKERS_MEM_LIMIT:-" in workers
    assert _megabytes(_defaults()["REDIS_MAXMEMORY"]) == STARTER_REDIS_MAXMEMORY_MB
    spare = STARTER_RAM_MB - STARTER_SHARED_BUFFERS_MB - STARTER_REDIS_MAXMEMORY_MB
    assert _megabytes(_defaults()["WORKERS_MEM_LIMIT"]) <= spare // 2
