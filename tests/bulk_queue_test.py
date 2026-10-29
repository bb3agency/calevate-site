"""The slow-job queue (D-929): routing, registration, deployment and readiness.

FAILS IF: a job in `BULK_JOBS` is enqueued on the default queue (or any other job on the
bulk one); the bulk worker answers to anything but `BULK_JOBS`, runs a cron, or loses a
setting the main worker has; the main worker stops answering to bulk jobs a pre-D-929
producer still puts on the default queue; or `/healthz/ready` stops watching either queue.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from apps.api.core import health
from apps.api.core.queue import (
    BULK_JOBS,
    BULK_QUEUE,
    DEFAULT_QUEUE,
    QUEUES,
    WORKER_JOB_TIMEOUT_S,
    enqueue,
    get_queue,
    queue_for,
)
from apps.workers import settings as worker_settings
from apps.workers.settings import BulkWorkerSettings, WorkerSettings
from arq.worker import Worker, get_kwargs

COMPOSE_PROD = Path(__file__).resolve().parents[1] / "compose.prod.yml"


def _names(functions: Any) -> set[str]:
    return {getattr(fn, "__name__", "") for fn in functions}


# --------------------------------------------------------------------------- routing


def test_a_bulk_job_is_routed_to_the_bulk_queue() -> None:
    assert queue_for("ingest_kb_source") == BULK_QUEUE


def test_a_latency_critical_job_stays_on_the_default_queue() -> None:
    for job in ("run_post_call_pipeline", "deliver_auth_email", "push_engine_dnc"):
        assert queue_for(job) == DEFAULT_QUEUE


def test_the_two_queues_are_distinct_and_the_default_is_arqs() -> None:
    assert QUEUES == (DEFAULT_QUEUE, BULK_QUEUE)
    assert DEFAULT_QUEUE == "arq:queue"
    assert BULK_QUEUE != DEFAULT_QUEUE


@pytest.mark.parametrize(
    ("job", "expected", "other"),
    [
        ("ingest_kb_source", BULK_QUEUE, DEFAULT_QUEUE),
        ("run_post_call_pipeline", DEFAULT_QUEUE, BULK_QUEUE),
    ],
)
async def test_enqueue_adds_the_job_to_its_queues_sorted_set(
    job: str, expected: str, other: str
) -> None:
    """Through the real seam and the real Redis, not `queue_for` alone: the producers
    only ever call `enqueue`."""
    job_id = f"bulk-routing-probe:{uuid.uuid4().hex}"
    queue = await get_queue()
    try:
        assert await enqueue(job, {}, job_id=job_id, _expires=60) == job_id
        assert await queue.zscore(expected, job_id) is not None
        assert await queue.zscore(other, job_id) is None
    finally:
        await queue.zrem(expected, job_id)
        await queue.delete(f"arq:job:{job_id}")


# ---------------------------------------------------------------------- registration


async def test_the_bulk_worker_registers_exactly_the_bulk_jobs_and_no_crons() -> None:
    """Built the way `arq` builds it, from the class's own `__dict__`."""
    worker = Worker(**get_kwargs(BulkWorkerSettings), handle_signals=False)
    try:
        assert worker.queue_name == BULK_QUEUE
        assert set(worker.functions) == set(BULK_JOBS)
        assert worker.cron_jobs == []
    finally:
        await worker.close()


async def test_the_main_worker_reads_the_default_queue_and_still_answers_to_bulk_jobs() -> None:
    worker = Worker(**get_kwargs(WorkerSettings), handle_signals=False)
    try:
        assert worker.queue_name == DEFAULT_QUEUE
        assert set(BULK_JOBS) <= set(worker.functions)
        assert worker.cron_jobs
    finally:
        await worker.close()


def test_the_bulk_worker_registers_the_same_objects_as_the_main_one() -> None:
    """Same tracing, outbox-once and result-window wrapping: filtered, never rebuilt."""
    main = {getattr(fn, "__name__", ""): fn for fn in WorkerSettings.functions}
    for fn in BulkWorkerSettings.functions:
        assert fn is main[fn.__name__]


#: The attributes the two classes are deliberately different on.
_DIFFERS = {"functions", "cron_jobs", "timezone", "queue_name", "on_startup"}


def test_the_bulk_worker_shares_every_other_worker_setting() -> None:
    main = get_kwargs(WorkerSettings)
    bulk = get_kwargs(BulkWorkerSettings)
    shared = set(main) - _DIFFERS
    assert shared <= set(bulk), f"BulkWorkerSettings lacks {sorted(shared - set(bulk))}"
    for name in shared:
        assert bulk[name] == main[name], name
    assert set(bulk) - set(main) == set()


def test_bulk_jobs_naming_an_unregistered_job_refuses_to_import() -> None:
    assert worker_settings._unregistered_bulk == set()
    assert _names(worker_settings.FUNCTIONS) >= BULK_JOBS


# ------------------------------------------------------------------------ deployment


def _compose_service(name: str) -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))[
        "services"
    ]
    return services[name]


def test_compose_runs_the_bulk_worker_from_the_same_image() -> None:
    bulk = _compose_service("workers-bulk")
    main = _compose_service("workers")
    assert bulk["command"] == ["arq", "apps.workers.settings.BulkWorkerSettings"]
    assert bulk["image"] == main["image"]
    assert bulk["read_only"] is True


def test_the_bulk_drain_window_fits_inside_its_grace() -> None:
    grace = _compose_service("workers-bulk")["stop_grace_period"]
    assert grace.endswith("s")
    assert BulkWorkerSettings.job_completion_wait < int(grace[:-1])


# ------------------------------------------------------------------------- readiness


def test_readiness_watches_both_queues() -> None:
    assert {key for key, _ in health.WATCHED_QUEUES.values()} == set(QUEUES)


def test_a_stuck_default_queue_is_stale() -> None:
    stats = {"default": (1, health.QUEUE_STALE_AFTER_S + 1), "bulk": (0, None)}
    assert health._stale_queues(stats) == ["default"]


def test_a_bulk_job_waiting_for_a_slot_is_not_stale() -> None:
    """Few slots and jobs that can run `WORKER_JOB_TIMEOUT_S`: its head job can wait that
    long for a slot while the worker is healthy."""
    waiting = float(WORKER_JOB_TIMEOUT_S)
    assert health._stale_queues({"default": (0, None), "bulk": (3, waiting)}) == []


def test_a_bulk_queue_nobody_drains_is_stale() -> None:
    threshold = health.QUEUE_STALE_AFTER_S + WORKER_JOB_TIMEOUT_S
    assert health._stale_queues({"default": (0, None), "bulk": (3, threshold + 1)}) == ["bulk"]
